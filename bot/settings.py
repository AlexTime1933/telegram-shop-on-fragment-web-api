"""Bot settings from ``.env`` (and real environment variables, which take precedence).

All secrets are read here, by the application; the ``fragment_api`` library
only receives the values. Every secret can be given inline or as a file::

    TON_MNEMONIC=word1 word2 ...      or  TON_MNEMONIC_FILE=seed.txt
    TONAPI_KEY=AE...                  or  TONAPI_KEY_FILE=tonconsole_api
    BOT_TOKEN=123:ABC                 or  BOT_TOKEN_FILE=bot_token
    FRAGMENT_COOKIES=stel_ssid=...    or  FRAGMENT_COOKIES_FILE=cookie.json
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fragment_api import PAY_TON, PAY_USDT_TON, Fragment, SafetyPolicy
from fragment_api.exceptions import ConfigError

_PREFIXES = ("FRAGMENT_", "TON_", "TONAPI_", "BOT_", "SHOP_", "PAYMENT_", "ROLLYPAY_", "XROCKET_", "WEBHOOK_")


def parse_env_file(path: "str | Path") -> dict[str, str]:
    """Minimal ``.env`` parser: ``KEY=value``, ``#`` comments, optional quotes, ``export``."""
    values: dict[str, str] = {}
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: ожидается строка вида КЛЮЧ=значение")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def _providers(value: str) -> list[str]:
    codes = [p.strip() for p in value.split(",") if p.strip()]
    if "stub" in codes:  # the test payment was removed from the bot
        logging.getLogger(__name__).warning("PAYMENT_PROVIDERS: тестовой оплаты \"stub\" больше нет, "
                                            "уберите её из .env")
        codes.remove("stub")
    return codes


@dataclass
class Settings:
    cookies: str = field(repr=False)
    cookies_file: Path | None = None
    mnemonic: str | None = field(default=None, repr=False)
    mnemonic_password: str = field(default="", repr=False)
    wallet_version: str = "v5r1"
    tonapi_key: str | None = field(default=None, repr=False)
    network: str = "mainnet"
    max_purchase_ton: Decimal | None = Decimal("100")
    #: how the bot pays Fragment: "usdt_ton" (USDT on TON) or "ton"
    fragment_payment_method: str = PAY_USDT_TON
    max_purchase_usdt: Decimal | None = Decimal("100")
    allowed_destinations: list[str] | None = None  # None = library default (Fragment wallets)
    bot_token: str | None = field(default=None, repr=False)
    admin_ids: frozenset[int] = frozenset()
    db_path: Path = Path("bot.db")
    default_markup: Decimal = Decimal("10")
    default_usd_rub: Decimal = Decimal("95")
    default_stars_min: int = 100
    default_stars_max: int = 10000
    payment_providers: list[str] = field(default_factory=list)
    payment_timeout_min: int = 10
    order_limit_per_day: int = 5
    # RollyPay: enabled when the API key is set
    rollypay_api_key: str | None = field(default=None, repr=False)
    rollypay_test: bool = False
    rollypay_mode: str = "polling"  # "polling" (check every N s) or "webhook"
    rollypay_poll_interval: float = 30.0
    rollypay_signing_secret: str | None = field(default=None, repr=False)
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080
    webhook_path: str = "/webhooks/rollypay"
    # xRocket Pay: enabled when the token for the selected network is set
    xrocket_api_token: str | None = field(default=None, repr=False)
    xrocket_testnet: bool = False
    xrocket_mode: str = "polling"  # "polling" or "webhook"
    xrocket_poll_interval: float = 30.0
    xrocket_webhook_secret: str | None = field(default=None, repr=False)
    xrocket_webhook_path: str = "/webhooks/xrocket"
    xrocket_webhook_url: str | None = None  # public HTTPS URL sent with each invoice (optional)
    xrocket_expire_seconds: int = 1800
    xrocket_currency: str = "USDT"
    xrocket_fee: Decimal = Decimal("0.5")

    @classmethod
    def load(cls, env_file: "str | Path" = ".env") -> "Settings":
        p = Path(env_file)
        env: dict[str, str] = parse_env_file(p) if p.is_file() else {}
        env.update({k: v for k, v in os.environ.items() if k.startswith(_PREFIXES)})
        base = p.resolve().parent if p.is_file() else Path.cwd()

        def secret(name: str, required: bool = False) -> tuple[str | None, Path | None]:
            """``NAME`` (value) or ``NAME_FILE`` (path, relative to the .env folder)."""
            if env.get(name, "").strip():
                return env[name].strip(), None
            file_value = env.get(f"{name}_FILE", "").strip()
            if file_value:
                fp = Path(file_value)
                fp = fp if fp.is_absolute() else base / fp
                if fp.is_file():
                    return fp.read_text(encoding="utf-8").strip(), fp
                if len(file_value) > 40 or " " in file_value:
                    raise ConfigError(
                        f"в {name}_FILE, похоже, вписано само значение, а не имя файла. "
                        f"Напишите строку как {name}=значение"
                    )
                raise ConfigError(f"{name}_FILE: файл не найден: {fp}")
            if required:
                raise ConfigError(f"не задано {name} (или {name}_FILE) в {p}")
            return None, None

        cookies, cookies_file = secret("FRAGMENT_COOKIES", required=True)
        mnemonic, _ = secret("TON_MNEMONIC")
        tonapi_key, _ = secret("TONAPI_KEY")
        bot_token, _ = secret("BOT_TOKEN")

        max_ton = env.get("FRAGMENT_MAX_PURCHASE_TON", "100").strip().lower()
        try:
            max_purchase = None if max_ton in ("", "0", "off", "none") else Decimal(max_ton)
        except InvalidOperation:
            raise ConfigError("FRAGMENT_MAX_PURCHASE_TON должно быть числом, например 100") from None
        max_usdt = env.get("FRAGMENT_MAX_PURCHASE_USDT", "100").strip().lower()
        try:
            max_purchase_usdt = None if max_usdt in ("", "0", "off", "none") else Decimal(max_usdt)
        except InvalidOperation:
            raise ConfigError("FRAGMENT_MAX_PURCHASE_USDT должно быть числом, например 100") from None
        method = env.get("FRAGMENT_PAYMENT_METHOD", PAY_USDT_TON).strip().lower().replace("-", "_")
        method = {"usdt": PAY_USDT_TON, "usdt_ton": PAY_USDT_TON, "ton": PAY_TON}.get(method)
        if method is None:
            raise ConfigError("FRAGMENT_PAYMENT_METHOD: usdt_ton (USDT в сети TON) или ton")
        allowed = env.get("FRAGMENT_ALLOWED_DESTINATIONS")
        try:
            admins = frozenset(int(x) for x in env.get("BOT_ADMIN_IDS", "").replace(" ", "").split(",") if x)
        except ValueError:
            raise ConfigError("BOT_ADMIN_IDS: числовые Telegram id через запятую (узнать: /myid)") from None

        def dec(name: str, default: str) -> Decimal:
            try:
                return Decimal(env.get(name, default).strip().replace(",", "."))
            except InvalidOperation:
                raise ConfigError(f"{name} должно быть числом") from None

        try:
            stars_min = int(env.get("SHOP_STARS_MIN", "100"))
            stars_max = int(env.get("SHOP_STARS_MAX", "10000"))
        except ValueError:
            raise ConfigError("SHOP_STARS_MIN и SHOP_STARS_MAX должны быть целыми числами") from None
        if not 50 <= stars_min <= stars_max <= 10_000_000:
            raise ConfigError("SHOP_STARS_MIN/SHOP_STARS_MAX: нужно 50 <= минимум <= максимум <= 10000000")

        try:
            order_limit = int(env.get("SHOP_ORDER_LIMIT_PER_DAY", "5"))
        except ValueError:
            raise ConfigError("SHOP_ORDER_LIMIT_PER_DAY должно быть целым числом (0 = без ограничения)") from None
        if order_limit < 0:
            raise ConfigError("SHOP_ORDER_LIMIT_PER_DAY не может быть отрицательным")

        # RollyPay (also accepts the lower-case name rollypay_api)
        rp_key = (env.get("ROLLYPAY_API") or env.get("rollypay_api") or "").strip() or None
        rp_mode = env.get("ROLLYPAY_MODE", "polling").strip().lower()
        if rp_mode not in ("polling", "webhook"):
            raise ConfigError("ROLLYPAY_MODE: polling (бот проверяет оплату) или webhook (RollyPay сообщает сам)")
        rp_secret = env.get("ROLLYPAY_SIGNING_SECRET", "").strip() or None
        if rp_key and rp_mode == "webhook" and not rp_secret:
            raise ConfigError("ROLLYPAY_MODE=webhook требует ROLLYPAY_SIGNING_SECRET (секрет подписи кассы)")
        try:
            rp_poll = float(env.get("ROLLYPAY_POLL_INTERVAL", "30"))
            webhook_port = int(env.get("WEBHOOK_PORT") or env.get("ROLLYPAY_WEBHOOK_PORT") or "8080")
        except ValueError:
            raise ConfigError("ROLLYPAY_POLL_INTERVAL и ROLLYPAY_WEBHOOK_PORT должны быть числами") from None

        # xRocket Pay: separate tokens for mainnet and testnet (@xrocket_testnet_bot)
        xr_testnet = env.get("XROCKET_TESTNET", "false").strip().lower() in ("1", "true", "yes", "on")
        if xr_testnet:
            xr_token = env.get("XROCKET_TESTNET_API", "").strip() or None
            xr_secret = env.get("XROCKET_TESTNET_WEBHOOK_SECRET", "").strip() or None
        else:
            xr_token = env.get("XROCKET_API", "").strip() or None
            xr_secret = env.get("XROCKET_WEBHOOK_SECRET", "").strip() or None
        xr_mode = env.get("XROCKET_MODE", "polling").strip().lower()
        if xr_mode not in ("polling", "webhook"):
            raise ConfigError("XROCKET_MODE: polling (бот проверяет оплату) или webhook (xRocket сообщает сам)")
        if xr_token and xr_mode == "webhook" and not xr_secret:
            raise ConfigError("XROCKET_MODE=webhook требует секрет вебхуков (Webhook Token приложения): "
                              + ("XROCKET_TESTNET_WEBHOOK_SECRET" if xr_testnet else "XROCKET_WEBHOOK_SECRET"))
        try:
            xr_expire = int(env.get("XROCKET_EXPIRE_SECONDS", "1800"))
            xr_poll = float(env.get("XROCKET_POLL_INTERVAL", "30"))
            xr_fee = Decimal(env.get("XROCKET_FEE", "0.5").strip().replace(",", ".") or "0")
        except (ValueError, InvalidOperation):
            raise ConfigError("XROCKET_EXPIRE_SECONDS, XROCKET_POLL_INTERVAL и XROCKET_FEE должны быть числами") from None
        if not 60 <= xr_expire <= 86400:
            raise ConfigError("XROCKET_EXPIRE_SECONDS: от 60 до 86400 секунд (1 сутки)")
        if xr_fee < 0:
            raise ConfigError("XROCKET_FEE не может быть отрицательной")
        xr_url = env.get("XROCKET_WEBHOOK_URL", "").strip() or None
        if xr_url and not xr_url.startswith("https://"):
            raise ConfigError("XROCKET_WEBHOOK_URL должен быть публичным адресом https://...")

        db = Path(env.get("BOT_DB_PATH", "bot.db").strip() or "bot.db")
        try:
            timeout = int(env.get("PAYMENT_TIMEOUT_MIN", "10"))
        except ValueError:
            raise ConfigError("PAYMENT_TIMEOUT_MIN должно быть целым числом минут") from None

        return cls(
            db_path=db if db.is_absolute() else base / db,
            default_markup=dec("SHOP_MARKUP_PERCENT", "10"),
            default_usd_rub=dec("SHOP_USD_RUB", "95"),
            default_stars_min=stars_min,
            default_stars_max=stars_max,
            payment_providers=_providers(env.get("PAYMENT_PROVIDERS", "")),
            payment_timeout_min=timeout,
            order_limit_per_day=order_limit,
            rollypay_api_key=rp_key,
            rollypay_test=env.get("ROLLYPAY_TEST", "false").strip().lower() in ("1", "true", "yes", "on"),
            rollypay_mode=rp_mode,
            rollypay_poll_interval=max(rp_poll, 5.0),
            rollypay_signing_secret=rp_secret,
            webhook_host=(env.get("WEBHOOK_HOST") or env.get("ROLLYPAY_WEBHOOK_HOST") or "0.0.0.0").strip(),
            webhook_port=webhook_port,
            webhook_path="/" + env.get("ROLLYPAY_WEBHOOK_PATH", "/webhooks/rollypay").strip().lstrip("/"),
            xrocket_api_token=xr_token,
            xrocket_testnet=xr_testnet,
            xrocket_mode=xr_mode,
            xrocket_poll_interval=max(xr_poll, 5.0),
            xrocket_webhook_secret=xr_secret,
            xrocket_webhook_path="/" + env.get("XROCKET_WEBHOOK_PATH", "/webhooks/xrocket").strip().lstrip("/"),
            xrocket_webhook_url=xr_url,
            xrocket_expire_seconds=xr_expire,
            xrocket_currency=(env.get("XROCKET_CURRENCY", "USDT").strip() or "USDT").upper(),
            xrocket_fee=xr_fee,
            cookies=cookies,
            cookies_file=cookies_file if cookies_file and cookies_file.suffix == ".json" else None,
            mnemonic=mnemonic,
            mnemonic_password=env.get("TON_MNEMONIC_PASSWORD", ""),
            wallet_version=env.get("TON_WALLET_VERSION", "v5r1").strip().lower(),
            tonapi_key=tonapi_key,
            network=env.get("TON_NETWORK", "mainnet").strip().lower(),
            max_purchase_ton=max_purchase,
            fragment_payment_method=method,
            max_purchase_usdt=max_purchase_usdt,
            allowed_destinations=(
                None if allowed is None
                else [] if allowed.strip().lower() in ("", "any", "off", "none")
                else [a.strip() for a in allowed.split(",") if a.strip()]
            ),
            bot_token=bot_token,
            admin_ids=admins,
        )

    def build_fragment(self) -> Fragment:
        """Hand the secrets to the library as plain values."""
        safety = SafetyPolicy(max_amount_ton=self.max_purchase_ton, max_amount_usdt=self.max_purchase_usdt)
        if self.allowed_destinations is not None:
            safety.allowed_destinations = self.allowed_destinations or None
        return Fragment.create(
            self.cookies,
            mnemonic=self.mnemonic,
            mnemonic_password=self.mnemonic_password,
            tonapi_key=self.tonapi_key,
            wallet_version=self.wallet_version,
            network=self.network,
            safety=safety,
        )

    def save_cookies(self, cookies: dict[str, str]) -> None:
        """Persist cookies rotated by Fragment (only when they come from a JSON file)."""
        if self.cookies_file is None:
            return
        try:
            current = json.loads(self.cookies_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = None
        if current != cookies:
            self.cookies_file.write_text(json.dumps(cookies, indent=1), encoding="utf-8")
