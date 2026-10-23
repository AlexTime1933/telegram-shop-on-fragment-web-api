"""Order lifecycle: quote -> invoice -> payment confirmed -> purchase on Fragment.

    awaiting_payment --(provider says paid)--> paid --(Fragment ok)--> completed
           |                                    |
           +--(timeout)--> expired               +--(failure)--> error

An order is bought on Fragment at most once automatically: ``claim_fulfillment``
lets exactly one task start the purchase, and a purchase interrupted by a
restart is NOT retried (the TON may already be sent) but marked ``error`` for
an admin to check.
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Iterable

from fragment_api import (
    PAY_USDT_TON,
    Fragment,
    FragmentAPIError,
    InsufficientBalanceError,
    InvalidAmountError,
    RecipientNotFoundError,
    TransactionSafetyError,
    TransactionTimeoutError,
    VerificationRequiredError,
    WalletLinkRequiredError,
)
from fragment_api.fragment.client import normalize_username

from . import texts
from .formatting import esc, num, ts
from .messenger import Messenger, MessengerError
from .models import Order, Product, Status
from .payments import Invoice, PaymentError, PaymentProvider, PaymentStatus
from .pricing import Pricing, ShopSettings
from .storage import Storage

log = logging.getLogger(__name__)

# Fragment's TON price may move between the quote and the purchase; above this we stop.
MAX_PRICE_DRIFT = Decimal("0.05")

# Anti-spam: orders in these statuses count towards the per-buyer daily limit.
LIMITED_STATUSES = (Status.AWAITING_PAYMENT, Status.EXPIRED, Status.ERROR)
ORDER_LIMIT_WINDOW = 24 * 3600  # seconds
# How long expired orders are still polled for a late payment (webhook mode gets it by webhook).
LATE_PAYMENT_WINDOW = 3600  # seconds

# Funds check: TON Fragment asks to attach for gas to one USDT payment (the unused part comes back).
USDT_GAS_TON = Decimal("0.05")
# At most one "not enough funds" alert to admins per this many seconds.
LOW_FUNDS_ALERT_INTERVAL = 1800


class ShopError(Exception):
    """A problem to show to the user as is (always a text from ``texts.py``, never a raw error)."""


def log_client_error(exc: BaseException, *, user_id: int | None, order: Order | None = None,
                     where: str = "") -> None:
    """Technical errors are hidden from clients: the details go to the server log only.

    The log line has the time (log format), the user, the order (if any) and the error text.
    """
    log.error("client error%s: user=%s order=%s: %s: %s", f" in {where}" if where else "", user_id,
              f"{order.number} ({order.code})" if order else "-", type(exc).__name__, exc)


class OrderService:
    def __init__(self, storage: Storage, pricing: Pricing, settings: ShopSettings, fragment: Fragment,
                 providers: dict[str, PaymentProvider], notifier: Messenger, admin_ids: Iterable[int]) -> None:
        self.storage = storage
        self.pricing = pricing
        self.settings = settings
        self.fragment = fragment
        self.providers = providers
        self.notifier = notifier
        self.admin_ids = frozenset(admin_ids)
        #: called with Fragment's current cookies after a real purchase, so the app can persist them
        self.on_cookies = None
        self._tasks: set[asyncio.Task] = set()
        self._last_check: dict[tuple[str, str], float] = {}  # (provider, payment_id) -> last status poll
        self._order_locks: dict[int, asyncio.Lock] = {}  # one invoice creation at a time per order
        #: how Fragment is paid: "usdt_ton" or "ton" (FRAGMENT_PAYMENT_METHOD)
        self.payment_method = PAY_USDT_TON
        self._funds_lock = asyncio.Lock()  # funds are checked and reserved for one new invoice at a time
        self._low_funds_alert_at = 0.0

    # ------------------------------------------------------------- helpers
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def providers_for(self, user_id: int) -> list[PaymentProvider]:
        return [p for p in self.providers.values() if not p.admin_only or self.is_admin(user_id)]

    def payment_deadline(self, order: Order) -> float:
        """When an unpaid order expires: the payment link's own expiry, else PAYMENT_TIMEOUT_MIN."""
        expires = order.extra.get("payment_expires_at")
        return float(expires) if expires else order.created_at + self.settings.payment_timeout_min * 60

    def _expired(self, order: Order) -> bool:
        return time.time() > self.payment_deadline(order)

    async def _notify(self, chat_id: int, text: str) -> None:
        try:
            await self.notifier.send_message(chat_id, text)
        except MessengerError as exc:
            log.warning("notify %s failed: %s", chat_id, exc)

    async def _notify_admins(self, text: str) -> None:
        for admin in self.admin_ids:
            await self._notify(admin, text)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --------------------------------------------------------------- order
    async def check_recipient(self, product: Product, username: str, quantity: int,
                              user_id: int | None = None) -> str:
        """Validate the Telegram username on Fragment; returns it without ``@``."""
        try:
            username = normalize_username(username)
            if product == Product.STARS:
                await self.fragment.find_stars_recipient(username, quantity)
            else:
                await self.fragment.find_premium_recipient(username, quantity)
        except RecipientNotFoundError as exc:  # not an error for the client: ask for another username
            log.info("recipient %r rejected for user %s: %s", username, user_id, exc)
            raise ShopError(texts.ERR_RECIPIENT) from exc
        except FragmentAPIError as exc:
            log_client_error(exc, user_id=user_id, where="recipient check")
            raise ShopError(texts.ERR_GENERIC) from exc
        return username

    def check_quantity(self, product: Product, quantity: int) -> None:
        """Shop limits for Stars (set in the admin panel); raises ShopError."""
        if product == Product.STARS and not self.settings.stars_allowed(quantity):
            raise ShopError(texts.ERR_STARS_LIMIT.format(min=num(self.settings.stars_min),
                                                         max=num(self.settings.stars_max)))

    def check_order_limit(self, buyer_id: int) -> None:
        """At most N unpaid / expired / failed orders per buyer in 24 h (admins are exempt)."""
        limit = self.settings.order_limit_per_day
        if not limit or self.is_admin(buyer_id):
            return
        now = time.time()
        times = self.storage.recent_order_times(buyer_id, LIMITED_STATUSES, now - ORDER_LIMIT_WINDOW)
        if len(times) >= limit:
            # a new order becomes possible when enough of these leave the 24 h window
            free_at = times[len(times) - limit] + ORDER_LIMIT_WINDOW
            raise ShopError(texts.ERR_ORDER_LIMIT.format(limit=limit, time=ts(free_at)))

    async def create_order(self, *, buyer_id: int, chat_id: int, buyer_username: str | None,
                           product: Product, quantity: int, recipient: str) -> Order:
        self.check_order_limit(buyer_id)
        self.check_quantity(product, quantity)
        try:
            quote = await self.pricing.quote(product, quantity)
        except InvalidAmountError as exc:
            log.info("quantity %s %s rejected for user %s: %s", quantity, product.value, buyer_id, exc)
            raise ShopError(texts.ERR_QUANTITY) from exc
        except (FragmentAPIError, ValueError) as exc:
            log_client_error(exc, user_id=buyer_id, where="price quote")
            raise ShopError(texts.ERR_GENERIC) from exc
        await self.check_funds(quote.fragment_usd, quote.fragment_ton, user_id=buyer_id)
        order = self.storage.create_order(
            buyer_id=buyer_id, buyer_chat_id=chat_id, buyer_username=buyer_username,
            product=product, quantity=quantity, recipient=recipient,
            fragment_price_ton=quote.fragment_ton, fragment_price_usd=quote.fragment_usd,
            markup_percent=quote.markup_percent, usd_rub_rate=quote.usd_rub_rate,
            price_usd=quote.price_usd, price_rub=quote.price_rub,
        )
        log.info("order %s created: %s for @%s, $%s", order.number, order.title, recipient, order.price_usd)
        return order

    def get_order_for(self, order_id: int, user_id: int) -> Order:
        order = self.storage.get(order_id)
        if order is None or (order.buyer_id != user_id and not self.is_admin(user_id)):
            raise ShopError(texts.ERR_ORDER_NOT_FOUND)
        return order

    def current_invoice(self, order: Order) -> Invoice | None:
        """The (only) invoice of the order, rebuilt from the database."""
        if not order.payment_id:
            return None
        return Invoice(payment_id=order.payment_id, amount=order.payment_amount, currency=order.payment_currency,
                       url=order.extra.get("payment_url"), instructions=order.extra.get("payment_instructions"),
                       expires_at=order.extra.get("payment_expires_at"))

    async def start_payment(self, order_id: int, provider_code: str, user_id: int) -> tuple[Order, Invoice]:
        """Create the order's invoice, or return the existing one.

        Anti-fraud: an order gets exactly ONE invoice with ONE provider. Once a method
        is chosen the others are unavailable, and pressing "pay" again shows the same
        invoice instead of creating a second one.
        """
        lock = self._order_locks.setdefault(order_id, asyncio.Lock())
        async with lock:  # two quick presses must not create two invoices
            order = self.get_order_for(order_id, user_id)
            if order.status != Status.AWAITING_PAYMENT:
                raise ShopError(texts.ERR_ORDER_STATUS.format(status=order.status.label))
            if self._expired(order):
                await self.expire(order)
                raise ShopError(texts.ERR_PAYMENT_TIMEOUT)
            if order.payment_id:
                if provider_code != order.payment_provider:
                    chosen = self.providers.get(order.payment_provider or "")
                    raise ShopError(texts.ERR_METHOD_LOCKED.format(
                        method=chosen.title if chosen else order.payment_provider))
                return order, self.current_invoice(order)
            provider = next((p for p in self.providers_for(user_id) if p.code == provider_code), None)
            if provider is None:
                raise ShopError(texts.ERR_METHOD_UNAVAILABLE)
            # The wallet must be able to pay Fragment for this order on top of all orders that
            # already have an invoice; checked and reserved under one lock (no two invoices race).
            async with self._funds_lock:
                await self.check_funds(order.fragment_price_usd, order.fragment_price_ton, user_id=user_id,
                                       order=order)
                return await self._create_invoice(order, provider, user_id)

    async def _create_invoice(self, order: Order, provider: PaymentProvider, user_id: int) -> tuple[Order, Invoice]:
        try:
            invoice = await provider.create_invoice(order, provider.amount_for(order))
        except PaymentError as exc:
            log_client_error(exc, user_id=user_id, order=order, where=f"invoice {provider.code}")
            raise ShopError(texts.ERR_GENERIC) from exc
        # Anti-fraud: a NEW invoice must be unpaid and must not belong to another order
        # (e.g. a provider handing out a link that was already paid).
        reused = self.storage.get_by_payment(provider.code, invoice.payment_id)
        if reused is not None or (invoice.status not in (None, PaymentStatus.PENDING)):
            reason = (texts.REASON_INVOICE_REUSED.format(other=reused.number) if reused
                      else texts.REASON_INVOICE_NOT_NEW.format(status=invoice.status.value))
            await self._alert_once(order, f"suspicious:{provider.code}:{invoice.payment_id}",
                                   texts.ADMIN_NOTIFY_SUSPICIOUS_INVOICE, provider=provider.code,
                                   payment_id=invoice.payment_id, reason=reason)
            log.error("order %s (%s), user %s: invoice %s/%s rejected: %s", order.number, order.code,
                      user_id, provider.code, invoice.payment_id, reason)
            raise ShopError(texts.ERR_GENERIC)
        # the order now expires together with the payment link
        deadline = invoice.expires_at or time.time() + self.settings.payment_timeout_min * 60
        extra = dict(order.extra, payment_expires_at=deadline, payment_url=invoice.url,
                     payment_instructions=invoice.instructions)
        order = self.storage.update(order.id, payment_provider=provider.code, payment_id=invoice.payment_id,
                                    payment_amount=invoice.amount, payment_currency=invoice.currency,
                                    extra=extra)
        self.storage.add_payment(order.id, provider.code, invoice.payment_id, invoice.amount,
                                 invoice.currency, invoice.expires_at)
        self.storage.add_event(order.id, f"user:{user_id}", None, None,
                               texts.REASON_INVOICE.format(provider=provider.code, payment_id=invoice.payment_id,
                                                           amount=invoice.amount, currency=invoice.currency))
        return order, invoice

    # ------------------------------------------------------------------ funds
    def _cost(self, fragment_usd: Decimal, fragment_ton: Decimal) -> tuple[Decimal, Decimal]:
        """(USDT, TON) the wallet needs to buy one order on Fragment, incl. the allowed price rise."""
        k = 1 + MAX_PRICE_DRIFT
        if self.payment_method == PAY_USDT_TON:
            return fragment_usd * k, USDT_GAS_TON
        return Decimal(0), fragment_ton * k

    def reserved_funds(self, exclude_order_id: int | None = None) -> tuple[Decimal, Decimal]:
        """(USDT, TON) promised to orders that will be bought: paid ones and unpaid ones with an invoice."""
        orders = self.storage.orders_with_status(Status.PAID) + [
            o for o in self.storage.orders_with_status(Status.AWAITING_PAYMENT) if o.payment_id]
        usdt = ton = Decimal(0)
        for o in orders:
            if o.id != exclude_order_id:
                u, t = self._cost(o.fragment_price_usd, o.fragment_price_ton)
                usdt, ton = usdt + u, ton + t
        return usdt, ton

    async def check_funds(self, fragment_usd: Decimal, fragment_ton: Decimal, *, user_id: int,
                          order: Order | None = None) -> None:
        """Refuse new orders / invoices the wallet could not pay for on Fragment.

        The client sees "temporarily unavailable"; admins get an alert (at most every 30 min).
        """
        need_usdt, need_ton = self._cost(fragment_usd, fragment_ton)
        res_usdt, res_ton = self.reserved_funds(order.id if order else None)
        usdt_mode = self.payment_method == PAY_USDT_TON
        try:
            have_ton = await self.fragment.get_balance()
            have_usdt = await self.fragment.get_usdt_balance() if usdt_mode else Decimal(0)
        except Exception as exc:  # no wallet / tonapi down: do not take money we may not be able to spend
            log_client_error(exc, user_id=user_id, order=order, where="wallet balance")
            raise ShopError(texts.ERR_GENERIC) from exc
        reserve_ton = self.fragment.safety.fee_reserve_ton
        lacks_usdt = usdt_mode and have_usdt < res_usdt + need_usdt
        lacks_ton = have_ton < res_ton + need_ton + reserve_ton
        if not (lacks_usdt or lacks_ton):
            return
        if lacks_usdt:
            need, have, reserved, cur = res_usdt + need_usdt, have_usdt, res_usdt, "USDT"
        else:
            need, have, reserved, cur = res_ton + need_ton + reserve_ton, have_ton, res_ton, "TON"
        need, have, reserved = (v.quantize(Decimal("0.01")) for v in (need, have, reserved))
        log.warning("not enough funds for a new %s (user %s): need %s %s, have %s, reserved %s",
                    f"invoice of order {order.number}" if order else "order", user_id, need, cur, have, reserved)
        now = time.time()
        if now - self._low_funds_alert_at >= LOW_FUNDS_ALERT_INTERVAL:
            self._low_funds_alert_at = now
            await self._notify_admins(texts.ADMIN_NOTIFY_LOW_FUNDS.format(need=need, have=have,
                                                                          reserved=reserved, currency=cur))
        raise ShopError(texts.ERR_OUT_OF_STOCK)

    async def check_payment(self, order_id: int, user_id: int | None = None) -> Order:
        """Ask the provider about the order's current payment and apply the result."""
        order = self.storage.get(order_id) if user_id is None else self.get_order_for(order_id, user_id)
        if order is None or not order.payment_id or order.payment_provider not in self.providers:
            return order
        return await self._sync_payment(order, order.payment_provider, order.payment_id)

    async def on_payment_event(self, provider_code: str, payment_id: str) -> Order | None:
        """Entry point for provider notifications (webhooks).

        The notification itself is not trusted: the order is looked up by the
        payment id (the order's only invoice) and the status is
        re-checked with the provider.
        """
        order = self.storage.get_by_payment(provider_code, payment_id)
        if order is None or provider_code not in self.providers:
            log.warning("payment event for unknown payment %s/%s", provider_code, payment_id)
            return None
        return await self._sync_payment(order, provider_code, payment_id)

    async def _sync_payment(self, order: Order, provider_code: str, payment_id: str) -> Order:
        """Apply the provider's status of one invoice to its order."""
        provider = self.providers[provider_code]
        self._last_check[(provider_code, payment_id)] = time.time()
        try:
            status = await provider.get_status(payment_id)
        except PaymentError as exc:
            log.warning("payment status %s/%s for %s failed: %s", provider_code, payment_id, order.number, exc)
            return order
        current = payment_id == order.payment_id and provider_code == order.payment_provider
        if status == PaymentStatus.PAID:
            if current and order.status == Status.AWAITING_PAYMENT:
                # the ONLY automatic way to "paid": awaiting payment -> paid, by the order's own invoice
                paid = await self.mark_paid(order.id, actor=f"provider:{provider_code}")
                return paid or self.storage.get(order.id)
            if current and order.status == Status.EXPIRED:
                # money arrived after the order expired: not fulfilled automatically
                await self._alert_once(order, f"late:{provider_code}:{payment_id}", texts.ADMIN_NOTIFY_LATE_PAYMENT,
                                       provider=provider_code, payment_id=payment_id)
            elif not current:  # an invoice that is not the order's own one got paid
                await self._alert_once(order, f"dup:{provider_code}:{payment_id}", texts.ADMIN_NOTIFY_DOUBLE_PAYMENT,
                                       provider=provider_code, payment_id=payment_id)
        elif status in (PaymentStatus.EXPIRED, PaymentStatus.FAILED):
            if current and order.status == Status.AWAITING_PAYMENT:
                await self.expire(order, note=texts.REASON_PROVIDER_STATUS.format(status=status.value))
        elif status == PaymentStatus.REFUNDED:
            if order.status in (Status.PAID, Status.COMPLETED, Status.ERROR):
                await self._alert_once(order, f"refund:{provider_code}:{payment_id}", texts.ADMIN_NOTIFY_REFUND,
                                       provider=provider_code, payment_id=payment_id)
        return self.storage.get(order.id)

    async def _alert_once(self, order: Order, key: str, template: str, **values) -> None:
        """Admin alert + history note, at most once per key (webhooks are retried)."""
        alerts = list(order.extra.get("alerts", []))
        if key in alerts:
            return
        self.storage.update(order.id, extra=dict(order.extra, alerts=[*alerts, key]))
        text = template.format(number=order.number, **values)
        self.storage.add_event(order.id, "system", None, None, text)
        await self._notify_admins(text)

    async def mark_paid(self, order_id: int, *, actor: str) -> Order | None:
        """awaiting_payment -> paid after the provider confirmed the payment; starts the purchase.

        Only this transition marks the order ``payment_confirmed``, and only such orders are
        bought on Fragment automatically (a status set by hand in the admin panel is not).
        """
        current = self.storage.get(order_id)
        if current is None:
            return None
        order = self.storage.transition(order_id, Status.PAID, from_statuses=[Status.AWAITING_PAYMENT],
                                        actor=actor, note=texts.REASON_PAID, paid_at=time.time(),
                                        extra=dict(current.extra, payment_confirmed=True))
        if order is None:
            return None
        # no message yet: the buyer gets ONE message when the order is done (or a problem notice)
        self._spawn(self.fulfill(order.id, actor="system"))
        return order

    async def expire(self, order: Order, note: str = texts.REASON_TIMEOUT) -> None:
        if order.payment_id and order.payment_provider in self.providers:
            try:
                await self.providers[order.payment_provider].cancel(order.payment_id)
            except PaymentError as exc:
                log.warning("cancel invoice failed: %s", exc)
        if self.storage.transition(order.id, Status.EXPIRED, from_statuses=[Status.AWAITING_PAYMENT],
                                   note=note):
            await self._notify(order.buyer_chat_id, texts.NOTIFY_EXPIRED.format(number=order.number,
                                                                                 reason=esc(note)))

    # --------------------------------------------------------- fulfillment
    async def fulfill(self, order_id: int, *, actor: str, manual: bool = False) -> Order:
        """Buy the order on Fragment (once). Safe to call concurrently.

        Automatic runs (``manual=False``) require the order to have gone through
        ``mark_paid`` (awaiting payment -> paid confirmed by its provider). Only an
        admin's explicit "run purchase" (``manual=True``) may skip that.
        """
        existing = self.storage.get(order_id)
        if existing is None or (not manual and not existing.extra.get("payment_confirmed")):
            log.warning("order %s: automatic purchase refused, payment was not confirmed by its provider",
                        existing.number if existing else order_id)
            return existing
        order = self.storage.claim_fulfillment(order_id)
        if order is None:
            return self.storage.get(order_id)
        try:
            quote = await self.pricing.quote(order.product, order.quantity)
            # compare in the currency the bot pays Fragment with
            if self.payment_method == PAY_USDT_TON:
                if quote.fragment_usd > order.fragment_price_usd * (1 + MAX_PRICE_DRIFT):
                    raise ShopError(texts.REASON_PRICE_DRIFT_USD.format(now=quote.fragment_usd,
                                                                        paid=order.fragment_price_usd))
            elif quote.fragment_ton > order.fragment_price_ton * (1 + MAX_PRICE_DRIFT):
                raise ShopError(texts.REASON_PRICE_DRIFT.format(now=quote.fragment_ton, paid=order.fragment_price_ton))
            if order.product == Product.STARS:
                result = await self.fragment.buy_stars(order.recipient, order.quantity,
                                                       payment_method=self.payment_method)
            else:
                result = await self.fragment.gift_premium(order.recipient, order.quantity,
                                                          payment_method=self.payment_method)
        except Exception as exc:  # every failure ends in "error" for an admin to look at
            return await self._fail(order, self._describe(exc), actor)
        order = self.storage.transition(
            order.id, Status.COMPLETED, from_statuses=[Status.PAID], actor=actor, note=texts.REASON_BOUGHT,
            completed_at=time.time(), fragment_req_id=result.request.req_id, tx_hash=result.message_hash,
        ) or self.storage.get(order.id)
        if self.on_cookies:
            try:
                self.on_cookies(self.fragment.cookies)
            except OSError as exc:
                log.warning("could not save cookies: %s", exc)
        await self._notify(order.buyer_chat_id, texts.NOTIFY_COMPLETED.format(
            number=order.number, title=esc(order.title), recipient=esc(order.recipient)))
        return order  # admins are notified about errors only

    async def _fail(self, order: Order, reason: str, actor: str) -> Order:
        log.warning("order %s failed: %s", order.number, reason)
        order = self.storage.transition(order.id, Status.ERROR, actor=actor, note=reason, error=reason) \
            or self.storage.get(order.id)
        await self._notify(order.buyer_chat_id, texts.NOTIFY_PROBLEM.format(number=order.number))
        await self._notify_admins(texts.ADMIN_NOTIFY_ERROR.format(number=order.number, reason=esc(reason)))
        return order

    @staticmethod
    def _describe(exc: Exception) -> str:
        if isinstance(exc, ShopError):
            return str(exc)
        if isinstance(exc, TransactionTimeoutError):
            return texts.REASON_TX_TIMEOUT.format(hash=exc.message_hash)
        if isinstance(exc, InsufficientBalanceError):
            return texts.REASON_NO_FUNDS.format(error=exc)
        if isinstance(exc, WalletLinkRequiredError):
            return texts.REASON_WALLET_LINK
        if isinstance(exc, VerificationRequiredError):
            return texts.REASON_KYC
        if isinstance(exc, TransactionSafetyError):
            return texts.REASON_SAFETY.format(error=exc)
        if isinstance(exc, RecipientNotFoundError):
            return texts.REASON_RECIPIENT.format(error=exc)
        if isinstance(exc, FragmentAPIError):
            return texts.REASON_FRAGMENT.format(kind=type(exc).__name__, error=exc)
        return texts.REASON_INTERNAL.format(kind=type(exc).__name__, error=exc)

    # --------------------------------------------------------------- admin
    async def admin_set_status(self, order_id: int, status: Status, admin_id: int) -> Order | None:
        """Plain status change from the admin panel (no payment / purchase side effects)."""
        return self.storage.transition(order_id, status, actor=f"admin:{admin_id}", note=texts.REASON_MANUAL_STATUS)

    async def admin_fulfill(self, order_id: int, admin_id: int) -> Order:
        """Run (or re-run) the Fragment purchase for a paid / failed order."""
        order = self.storage.get(order_id)
        if order is None:
            raise ShopError(texts.ERR_ORDER_NOT_FOUND)
        if order.status not in (Status.PAID, Status.ERROR):
            raise ShopError(texts.ADMIN_FULFILL_ONLY_PAID)
        reset = self.storage.transition(order_id, Status.PAID, from_statuses=[Status.PAID, Status.ERROR],
                                        actor=f"admin:{admin_id}", note=texts.REASON_MANUAL_FULFILL,
                                        fulfillment_started_at=None, error=None)
        if reset is None:
            raise ShopError(texts.ADMIN_STATUS_RACE)
        return await self.fulfill(order_id, actor=f"admin:{admin_id}", manual=True)

    # ----------------------------------------------------------- background
    async def recover_after_restart(self) -> None:
        for order in self.storage.orders_with_status(Status.PAID):
            if order.fulfillment_started_at is not None:
                await self._fail(order, texts.REASON_RESTART, "system")

    def _poll_due(self, order: Order) -> bool:
        """Polling mode: is it time to ask the provider about this order's payment again?"""
        provider = self.providers.get(order.payment_provider or "")
        if provider is None or not order.payment_id or provider.poll_interval is None:
            return False  # unknown provider, no invoice yet, or webhook mode
        last = self._last_check.get((provider.code, order.payment_id), 0.0)
        return time.time() - last >= provider.poll_interval

    async def tick(self) -> None:
        """One pass of the background loop: payments, expiries, late payments, pending purchases."""
        for order in self.storage.orders_with_status(Status.AWAITING_PAYMENT):
            expired = self._expired(order)
            # poll when due; and always look once more right before expiring (also in webhook mode)
            if order.payment_id and (self._poll_due(order) or expired):
                order = await self.check_payment(order.id)
            if order and order.status == Status.AWAITING_PAYMENT and self._expired(order):
                await self.expire(order)
        # money can arrive after the link expired: keep polling recently expired orders for a while
        # (such a payment is NOT fulfilled automatically, admins are alerted)
        for order in self.storage.orders_with_status_since(Status.EXPIRED, time.time() - LATE_PAYMENT_WINDOW):
            if self._poll_due(order):
                await self.check_payment(order.id)
        for order in self.storage.orders_with_status(Status.PAID):
            # e.g. the bot restarted right after mark_paid; a status set by hand is skipped
            if order.fulfillment_started_at is None and order.extra.get("payment_confirmed"):
                self._spawn(self.fulfill(order.id, actor="system"))

    async def run_background(self, interval: float = 10.0) -> None:
        await self.recover_after_restart()
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("background tick failed")
            await asyncio.sleep(interval)
