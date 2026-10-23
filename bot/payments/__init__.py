"""Payment providers available to the shop."""

from __future__ import annotations

from .base import Invoice, PaymentError, PaymentProvider, PaymentStatus
from .rollypay import RollyPayProvider
from .xrocket import XRocketProvider

# code -> factory for your own providers listed in PAYMENT_PROVIDERS. RollyPay and xRocket need
# their own settings and are added automatically when their API key / token is set.
REGISTRY: dict[str, type[PaymentProvider]] = {}
CONFIGURED = (RollyPayProvider.code, XRocketProvider.code)


def build_providers(codes: list[str], *, rollypay: RollyPayProvider | None = None,
                    xrocket: XRocketProvider | None = None) -> dict[str, PaymentProvider]:
    """Providers in button order: RollyPay, xRocket (if configured), then ``PAYMENT_PROVIDERS``."""
    providers: dict[str, PaymentProvider] = {}
    for configured in (rollypay, xrocket):
        if configured is not None:
            providers[configured.code] = configured
    for code in codes:
        if code in CONFIGURED:
            continue  # enabled by ROLLYPAY_API / XROCKET_API
        if code not in REGISTRY:
            raise ValueError(f"неизвестная платёжка {code!r}; доступны: {', '.join([*REGISTRY, *CONFIGURED])}")
        providers[code] = REGISTRY[code]()
    return providers


__all__ = ["Invoice", "PaymentError", "PaymentProvider", "PaymentStatus", "REGISTRY", "RollyPayProvider",
           "XRocketProvider", "build_providers"]
