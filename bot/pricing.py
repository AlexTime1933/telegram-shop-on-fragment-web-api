"""Shop settings (markup, USD/RUB rate, info text) and client price calculation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from fragment_api import Fragment
from fragment_api.fragment.client import STARS_MAX as FRAGMENT_STARS_MAX
from fragment_api.fragment.client import STARS_MIN as FRAGMENT_STARS_MIN

from . import texts
from .models import Product
from .storage import Storage

# Standard packages offered as buttons; only those within the shop's limits are shown,
# any other amount within the limits can be typed in.
STARS_PACKAGES = (50, 100, 250, 500, 1000, 2500)
PREMIUM_MONTHS = (3, 6, 12)


class ShopSettings:
    """Values the admin can change from the bot; persisted in the database."""

    def __init__(self, storage: Storage, *, default_markup: Decimal, default_usd_rub: Decimal,
                 default_info: str = "", payment_timeout_min: int = 30, order_limit_per_day: int = 5,
                 default_stars_min: int = 100, default_stars_max: int = 10000,
                 default_xrocket_fee: Decimal = Decimal("0.5")) -> None:
        self._s = storage
        self._defaults = {"markup_percent": str(default_markup), "usd_rub_rate": str(default_usd_rub),
                          "info_text": default_info, "stars_min": str(default_stars_min),
                          "stars_max": str(default_stars_max), "xrocket_fee": str(default_xrocket_fee)}
        self.payment_timeout_min = payment_timeout_min
        #: max unpaid / expired / failed orders per buyer in 24 h (0 = no limit)
        self.order_limit_per_day = order_limit_per_day

    def _get(self, key: str) -> str:
        return self._s.get_setting(key, self._defaults[key])

    @property
    def markup_percent(self) -> Decimal:
        return Decimal(self._get("markup_percent"))

    @markup_percent.setter
    def markup_percent(self, value: Decimal) -> None:
        if not Decimal("0") <= value <= Decimal("500"):
            raise ValueError(texts.ERR_MARKUP_RANGE)
        self._s.set_setting("markup_percent", str(value))

    @property
    def usd_rub_rate(self) -> Decimal:
        return Decimal(self._get("usd_rub_rate"))

    @usd_rub_rate.setter
    def usd_rub_rate(self, value: Decimal) -> None:
        if not Decimal("1") <= value <= Decimal("10000"):
            raise ValueError(texts.ERR_RATE_RANGE)
        self._s.set_setting("usd_rub_rate", str(value))

    @property
    def info_text(self) -> str:
        """HTML text of the "Информация" screen, editable from the admin panel."""
        return self._get("info_text")

    @info_text.setter
    def info_text(self, value: str) -> None:
        value = value.strip()
        if not value:
            raise ValueError(texts.ERR_INFO_EMPTY)
        if len(value) > 3500:
            raise ValueError(texts.ERR_INFO_TOO_LONG)
        self._s.set_setting("info_text", value)

    @property
    def xrocket_fee(self) -> Decimal:
        """Fixed xRocket fee in XROCKET_CURRENCY (e.g. USDT), added to each new xRocket invoice."""
        return Decimal(self._get("xrocket_fee"))

    @xrocket_fee.setter
    def xrocket_fee(self, value: Decimal) -> None:
        if not Decimal("0") <= value <= Decimal("1000"):
            raise ValueError(texts.ERR_FEE_RANGE)
        self._s.set_setting("xrocket_fee", format(value.normalize(), "f") if value else "0")

    @property
    def stars_min(self) -> int:
        return int(self._get("stars_min"))

    @property
    def stars_max(self) -> int:
        return int(self._get("stars_max"))

    def set_stars_limits(self, minimum: int, maximum: int) -> None:
        check_stars_limits(minimum, maximum)
        self._s.set_setting("stars_min", str(minimum))
        self._s.set_setting("stars_max", str(maximum))

    def stars_allowed(self, quantity: int) -> bool:
        return self.stars_min <= quantity <= self.stars_max


def check_stars_limits(minimum: int, maximum: int) -> None:
    if not FRAGMENT_STARS_MIN <= minimum <= maximum <= FRAGMENT_STARS_MAX:
        raise ValueError(texts.ERR_STARS_LIMITS_RANGE.format(min=FRAGMENT_STARS_MIN, max=FRAGMENT_STARS_MAX))


def parse_stars_limits(text: str) -> tuple[int, int]:
    """``"100 10000"``, ``"100-10000"``, ``"100 – 10 000"`` -> ``(100, 10000)``."""
    raw = text.strip()
    for sep in ("—", "–", "-", ",", ";", "/"):
        if sep in raw:
            parts = raw.split(sep)
            break
    else:
        parts = raw.split()
    numbers = [p.replace(" ", "").replace("\u00a0", "") for p in parts]
    if len(numbers) != 2 or not all(n.isdigit() for n in numbers):
        raise ValueError(texts.ERR_STARS_LIMITS_FORMAT)
    return int(numbers[0]), int(numbers[1])


def parse_decimal(text: str) -> Decimal:
    """``"12,5"`` / ``"12.5 %"`` -> ``Decimal("12.5")``."""
    cleaned = text.strip().replace(",", ".").replace("%", "").replace("₽", "").replace(" ", "")
    return Decimal(cleaned)


@dataclass(frozen=True)
class Quote:
    product: Product
    quantity: int
    fragment_ton: Decimal
    fragment_usd: Decimal
    markup_percent: Decimal
    usd_rub_rate: Decimal
    price_usd: Decimal
    price_rub: Decimal

    def text(self) -> str:
        return f"${self.price_usd} / {self.price_rub} ₽"


def apply_markup(base_usd: Decimal, markup_percent: Decimal, usd_rub: Decimal) -> tuple[Decimal, Decimal]:
    """Client price: base + markup, rounded UP to a cent (USD) and to a rouble (RUB)."""
    usd = (base_usd * (Decimal(100) + markup_percent) / Decimal(100)).quantize(Decimal("0.01"), ROUND_CEILING)
    rub = (usd * usd_rub).quantize(Decimal("1"), ROUND_CEILING)
    return usd, rub


class Pricing:
    """Fragment prices + markup. Lists are cached briefly; a quote for an order is always fresh."""

    def __init__(self, fragment: Fragment, settings: ShopSettings, cache_ttl: float = 60.0) -> None:
        self.fragment = fragment
        self.settings = settings
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, object]] = {}

    def _make(self, product: Product, quantity: int, ton: Decimal, usd: Decimal | None) -> Quote:
        if usd is None:
            raise ValueError("Fragment did not return a USD price")
        markup, rate = self.settings.markup_percent, self.settings.usd_rub_rate
        price_usd, price_rub = apply_markup(usd, markup, rate)
        return Quote(product, quantity, ton, usd, markup, rate, price_usd, price_rub)

    async def _cached(self, key: str, loader):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        value = await loader()
        self._cache[key] = (time.monotonic(), value)
        return value

    async def stars_menu(self) -> list[Quote]:
        packages = await self._cached("stars", self.fragment.get_stars_packages)
        by_qty = {p.quantity: p for p in packages}
        return [self._make(Product.STARS, q, by_qty[q].price_ton, by_qty[q].price_usd)
                for q in STARS_PACKAGES if q in by_qty and self.settings.stars_allowed(q)]

    async def premium_menu(self) -> list[Quote]:
        prices = await self._cached("premium", self.fragment.get_premium_prices)
        return [self._make(Product.PREMIUM, p.months, p.price_ton, p.price_usd)
                for p in sorted(prices, key=lambda p: p.months) if p.months in PREMIUM_MONTHS]

    async def quote(self, product: Product, quantity: int) -> Quote:
        """Fresh price straight from Fragment, used when an order is created."""
        if product == Product.STARS:
            p = await self.fragment.get_stars_price(quantity)
        else:
            p = await self.fragment.get_premium_price(quantity)
        return self._make(product, quantity, p.price_ton, p.price_usd)
