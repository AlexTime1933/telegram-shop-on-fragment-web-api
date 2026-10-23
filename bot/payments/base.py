"""Payment provider interface.

To add a real provider (YooKassa, CryptoBot, ...):

1. subclass :class:`PaymentProvider` in a new module of this package;
2. implement :meth:`create_invoice`, :meth:`get_status` and (optionally) :meth:`cancel`;
3. register it in ``payments/__init__.py`` (``build_providers``) and enable it
   with ``PAYMENT_PROVIDERS`` in ``.env``.

The shop never trusts the client: an order is paid only when
:meth:`get_status` of the provider says so.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from ..models import Order


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED = "failed"
    REFUNDED = "refunded"  # money returned / charged back after a successful payment


@dataclass(frozen=True)
class Invoice:
    """What the provider returned for a new payment."""

    payment_id: str
    amount: Decimal
    currency: str  # "RUB" or "USD"
    url: str | None = None  # payment page, if the provider has one
    instructions: str | None = None  # text shown to the client
    expires_at: float | None = None  # unix time the payment link expires (the order expires with it)
    status: PaymentStatus | None = None  # as reported on creation; a new invoice must be PENDING
    extra: dict = field(default_factory=dict)


class PaymentError(Exception):
    pass


class PaymentProvider(ABC):
    #: short id stored in orders, e.g. "yookassa"
    code: str = ""
    #: button text shown to clients
    title: str = ""
    #: currency the provider charges in: "RUB" or "USD"
    currency: str = "RUB"
    #: if True, only shop admins see this method (test / manual methods)
    admin_only: bool = False
    #: seconds between status checks by the bot; None = the provider notifies us (webhook)
    poll_interval: float | None = 0

    def amount_for(self, order: Order) -> Decimal:
        return order.price_rub if self.currency == "RUB" else order.price_usd

    def price_label(self, order: Order) -> tuple[str, str]:
        """Amount and currency sign shown on the payment method button."""
        return str(self.amount_for(order)), "₽" if self.currency == "RUB" else "$"

    @abstractmethod
    async def create_invoice(self, order: Order, amount: Decimal) -> Invoice:
        """Ask the provider to create a payment for ``amount`` in :attr:`currency`."""

    @abstractmethod
    async def get_status(self, payment_id: str) -> PaymentStatus:
        """Current state of a payment created by :meth:`create_invoice`."""

    async def cancel(self, payment_id: str) -> None:
        """Cancel an unpaid payment (when the order expires). Optional."""

    async def aclose(self) -> None:
        """Release network resources. Optional."""
