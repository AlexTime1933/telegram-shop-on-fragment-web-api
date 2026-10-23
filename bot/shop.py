"""Assemble the shop: storage, settings, pricing, payment providers, order service, dispatcher."""

from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from fragment_api import Fragment

from .handlers import build_router
from .messenger import Messenger
from .payments import RollyPayProvider, XRocketProvider, build_providers
from .pricing import Pricing, ShopSettings
from .services import OrderService, log_client_error
from .settings import Settings
from .storage import Storage
from . import texts

log = logging.getLogger(__name__)

COMMANDS = [
    ("start", texts.CMD_START),
    ("myid", texts.CMD_MYID),
    ("info", texts.CMD_INFO),
]


def build_rollypay(settings: Settings) -> RollyPayProvider | None:
    """RollyPay is a payment method only when ROLLYPAY_API is set."""
    if not settings.rollypay_api_key:
        return None
    return RollyPayProvider(
        settings.rollypay_api_key,
        test=settings.rollypay_test,
        # webhook mode: RollyPay notifies us, the bot does not poll
        poll_interval=None if settings.rollypay_mode == "webhook" else settings.rollypay_poll_interval,
    )


def build_xrocket(settings: Settings, fee=None) -> XRocketProvider | None:
    """xRocket is a payment method only when the token for the selected network is set."""
    if not settings.xrocket_api_token:
        return None
    return XRocketProvider(
        settings.xrocket_api_token,
        currency=settings.xrocket_currency,
        fee=settings.xrocket_fee if fee is None else fee,  # fee: function -> value from the admin panel
        expire_seconds=settings.xrocket_expire_seconds,
        testnet=settings.xrocket_testnet,
        poll_interval=None if settings.xrocket_mode == "webhook" else settings.xrocket_poll_interval,
        webhook_url=settings.xrocket_webhook_url,
    )


def build_service(settings: Settings, fragment: Fragment, notifier: Messenger) -> OrderService:
    storage = Storage(settings.db_path)
    shop_settings = ShopSettings(storage, default_markup=settings.default_markup,
                                 default_usd_rub=settings.default_usd_rub, default_info=texts.DEFAULT_INFO,
                                 payment_timeout_min=settings.payment_timeout_min,
                                 order_limit_per_day=settings.order_limit_per_day,
                                 default_stars_min=settings.default_stars_min,
                                 default_stars_max=settings.default_stars_max,
                                 default_xrocket_fee=settings.xrocket_fee)
    service = OrderService(storage, Pricing(fragment, shop_settings), shop_settings, fragment,
                           build_providers(settings.payment_providers, rollypay=build_rollypay(settings),
                                           xrocket=build_xrocket(settings, lambda: shop_settings.xrocket_fee)),
                           notifier, settings.admin_ids)
    service.on_cookies = settings.save_cookies
    service.payment_method = settings.fragment_payment_method
    return service


def build_dispatcher(service: OrderService) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["service"] = service  # injected into handlers as the `service` argument
    dp.include_router(build_router())
    dp.errors.register(_on_error)
    return dp


async def _on_error(event: ErrorEvent, service: OrderService) -> bool:
    """Any unexpected failure: details to the server log, a neutral message to the user."""
    update = event.update
    cq, message = update.callback_query, update.message
    user = (cq or message).from_user if (cq or message) else None
    order = None
    if cq and cq.data and cq.data.startswith(("o:", "a:")):  # order / admin buttons carry the order id
        try:
            order = service.storage.get(int(cq.data.split(":")[2]))
        except Exception:
            order = None
    log_client_error(event.exception, user_id=user.id if user else None, order=order, where="handler")
    log.debug("traceback", exc_info=event.exception)
    try:
        if cq:
            await cq.answer(texts.ERR_GENERIC, show_alert=True)
        elif message:
            await message.answer(texts.ERR_GENERIC)
    except Exception:  # Telegram unreachable: nothing more to do
        pass
    return True
