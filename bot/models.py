"""Domain objects of the shop: orders and their statuses."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal

from . import texts


class Status(str, enum.Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ERROR = "error"

    @property
    def label(self) -> str:
        """Text shown to people; edit it in ``texts.py`` (STATUS_*)."""
        return getattr(texts, "STATUS_" + self.name)


class Product(str, enum.Enum):
    STARS = "stars"
    PREMIUM = "premium"


@dataclass
class Order:
    """One purchase. ``id`` is the sequential number, ``code`` the random public one."""

    id: int
    code: str
    buyer_id: int
    buyer_chat_id: int
    buyer_username: str | None
    product: Product
    quantity: int  # stars count or premium months
    recipient: str  # Telegram username without @
    fragment_price_ton: Decimal
    fragment_price_usd: Decimal
    markup_percent: Decimal
    usd_rub_rate: Decimal
    price_usd: Decimal
    price_rub: Decimal
    status: Status
    created_at: float
    updated_at: float
    payment_provider: str | None = None
    payment_id: str | None = None
    payment_amount: Decimal | None = None
    payment_currency: str | None = None
    paid_at: float | None = None
    fulfillment_started_at: float | None = None
    completed_at: float | None = None
    fragment_req_id: str | None = None
    tx_hash: str | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        if self.product == Product.STARS:
            return texts.TITLE_STARS.format(quantity=f"{self.quantity:,}".replace(",", " "))
        return texts.TITLE_PREMIUM.format(months=self.quantity)

    @property
    def number(self) -> str:
        """Human-readable order number: sequential + random code."""
        return f"№{self.id} ({self.code})"
