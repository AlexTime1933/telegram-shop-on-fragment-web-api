"""xRocket Pay (https://docs.xrocket.exchange/api/pay/pay-api-overview): crypto payments via @xRocket.

Uses the current Pay API (not the deprecated Legacy API):

* base URL: ``https://pay.api.xrocket.exchange`` (testnet ``https://pay.api.testnet.xrocket.exchange``,
  bot @xrocket_testnet_bot with its own token)
* auth:    ``Authorization: Bearer <app API token>``
* create:  ``POST /api/v1/invoices`` (amounts are decimal strings, ``expiresIn`` in MILLISECONDS)
* status:  ``GET /api/v1/invoice?invoiceId=...`` -> ``active | paid | partially_paid | expired | cancelled``
* cancel:  ``DELETE /api/v1/invoice?invoiceId=...``
* rates:   ``GET /api/v1/rates?base=USD&assets=GRAM`` (public; TON is called GRAM)
* webhooks: HMAC-SHA256(webhook secret, "{Signature-Timestamp}.{raw body}") in ``Signature``,
  plus ``Signature-Version: v1`` and ``Signature-Timestamp`` in milliseconds; see ``bot/webhook.py``.
  The webhook secret ("Webhook Token" in the app settings) is NOT the API token.

The client pays in @xRocket via ``links.telegramBotLink``. Expiry sends no webhook, so the
bot expires orders itself and cancels the invoice (which also prevents a late payment).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import time
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal, InvalidOperation

import httpx

from .. import texts
from ..models import Order
from .base import Invoice, PaymentError, PaymentProvider, PaymentStatus

log = logging.getLogger(__name__)

MAINNET_URL = "https://pay.api.xrocket.exchange"
TESTNET_URL = "https://pay.api.testnet.xrocket.exchange"

# Assets pegged to the US dollar: priced 1:1 from the order's USD price, no rate request.
USD_STABLECOINS = {"USDT", "USDC"}
SIGNATURE_VERSION = "v1"
SIGNATURE_TOLERANCE_MS = 5 * 60 * 1000  # recommended by the docs

_STATUS = {
    "active": PaymentStatus.PENDING,
    "partially_paid": PaymentStatus.PENDING,
    "paid": PaymentStatus.PAID,
    "expired": PaymentStatus.EXPIRED,
    "cancelled": PaymentStatus.FAILED,
    "canceled": PaymentStatus.FAILED,
}


def map_status(status: str) -> PaymentStatus:
    # the docs: statuses are an open enum, treat unknown ones as "in progress"
    return _STATUS.get((status or "").lower(), PaymentStatus.PENDING)


def parse_time(value) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sign(body: bytes, timestamp_ms: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp_ms.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, headers, secret: str, *, now_ms: int | None = None) -> str | None:
    """``None`` if the webhook is authentic, otherwise the reason it is rejected."""
    signature = headers.get("Signature")
    version = headers.get("Signature-Version")
    timestamp = headers.get("Signature-Timestamp")
    if not secret:
        return "no webhook secret configured"
    if not (signature and version and timestamp):
        return "missing signature headers"
    if version != SIGNATURE_VERSION:
        return f"unsupported signature version {version!r}"
    try:
        ts = int(timestamp)
    except ValueError:
        return "bad timestamp"
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(now_ms - ts) > SIGNATURE_TOLERANCE_MS:
        return "stale timestamp"
    if not hmac.compare_digest(sign(body, timestamp, secret), signature.strip().lower()):
        return "invalid signature"
    return None


class XRocketProvider(PaymentProvider):
    code = "xrocket"

    def __init__(self, api_token: str, *, currency: str = "USDT",
                 fee: "Decimal | Callable[[], Decimal]" = Decimal("0.5"),
                 expire_seconds: int = 1800, testnet: bool = False, poll_interval: float | None = 30.0,
                 webhook_url: str | None = None, base_url: str | None = None,
                 http_client: httpx.AsyncClient | None = None) -> None:
        if not api_token:
            raise ValueError("xRocket API token is empty")
        self.title = texts.XROCKET_TITLE.format(currency=currency)
        self.currency = currency.upper()
        # a number, or a function returning the current fee (the admin panel can change it)
        self._fee = fee
        self.expire_seconds = expire_seconds
        self.testnet = testnet
        # testnet money is free, but a "paid" invoice makes the bot spend REAL TON on Fragment
        self.admin_only = testnet
        self.poll_interval = poll_interval
        self.webhook_url = webhook_url
        self.return_url: str | None = None  # set at start: link back to the bot
        self._token = api_token
        self._base = (base_url or (TESTNET_URL if testnet else MAINNET_URL)).rstrip("/")
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    # --------------------------------------------------------------- pricing
    @property
    def fee(self) -> Decimal:
        """Fixed fee in :attr:`currency`, read when each invoice is created."""
        return Decimal(self._fee()) if callable(self._fee) else Decimal(self._fee)

    @fee.setter
    def fee(self, value: "Decimal | Callable[[], Decimal]") -> None:
        self._fee = value

    @property
    def _precision(self) -> Decimal:
        return Decimal("0.01") if self.currency in USD_STABLECOINS else Decimal("0.0001")

    def amount_for(self, order: Order) -> Decimal:
        """Exact amount for USD stablecoins: order price in USD + fixed fee."""
        return (order.price_usd + self.fee).quantize(self._precision, ROUND_CEILING)

    def price_label(self, order: Order) -> tuple[str, str]:
        if self.currency in USD_STABLECOINS:
            return str(self.amount_for(order)), self.currency
        return f"≈ {order.price_usd}", "$"  # converted at the current rate when the invoice is created

    async def _usd_rate(self) -> Decimal:
        """Price of 1 unit of ``currency`` in USD (public endpoint)."""
        data = await self._request("GET", "/api/v1/rates", auth=False,
                                   params={"base": "USD", "assets": self.currency})
        for item in data if isinstance(data, list) else []:
            if str(item.get("currency", "")).upper() == self.currency:
                try:
                    rate = Decimal(str(item["rate"]))
                except (InvalidOperation, KeyError):
                    break
                if rate > 0:
                    return rate
        raise PaymentError(f"xRocket: no USD rate for {self.currency}")

    async def invoice_amount(self, order: Order) -> Decimal:
        if self.currency in USD_STABLECOINS:
            return self.amount_for(order)
        rate = await self._usd_rate()
        return (order.price_usd / rate + self.fee).quantize(self._precision, ROUND_CEILING)

    # ------------------------------------------------------------------ http
    async def _request(self, method: str, path: str, *, auth: bool = True, **kwargs):
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            resp = await self._http.request(method, f"{self._base}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise PaymentError(f"xRocket: network error {type(exc).__name__}") from None
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code >= 400:  # RFC 9457 problem details; never trust a "success" flag
            if isinstance(data, dict):
                kind = str(data.get("type", "")).rsplit("/", 1)[-1]
                message = data.get("detail") or data.get("title")
            else:
                kind, message = "", None
            raise PaymentError(f"xRocket {resp.status_code} {kind}: {message or resp.text[:200]}".strip())
        return data

    async def create_invoice(self, order: Order, amount: Decimal) -> Invoice:
        amount = await self.invoice_amount(order)  # the provider's own currency, fee included
        body = {
            "priceAmount": format(amount, "f"),
            "priceCurrency": self.currency,
            "payCurrencies": [self.currency],
            "numPayments": 1,
            # random code + time, never the sequential number (see rollypay.py)
            "clientInvoiceId": f"{order.code}-{int(time.time() * 1000)}",
            "description": texts.XROCKET_DESCRIPTION.format(number=order.number, title=order.title,
                                                            recipient=order.recipient),
            "expiresIn": self.expire_seconds * 1000,  # milliseconds
            "customer": {"id": str(order.buyer_id), "telegramId": str(order.buyer_id)},
            "data": {"order": order.id, "code": order.code},
        }
        if order.buyer_username:
            body["customer"]["telegramUsername"] = order.buyer_username
        if self.return_url:
            body["url"] = {"successUrl": self.return_url, "cancelUrl": self.return_url}
        if self.webhook_url:
            body["callback"] = {"callbackUrl": self.webhook_url, "payload": {"order": order.id}}
        data = await self._request("POST", "/api/v1/invoices", json=body)
        link = (data.get("links") or {}).get("telegramBotLink") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not data.get("id") or not link:
            raise PaymentError("xRocket: no invoice id / telegramBotLink in response")
        expires_at = parse_time(data.get("expiresAt")) or time.time() + self.expire_seconds
        return Invoice(
            payment_id=str(data["id"]),
            amount=Decimal(str(data.get("priceAmount") or body["priceAmount"])),
            currency=str(data.get("priceCurrency") or self.currency),
            url=link,
            instructions=texts.XROCKET_TESTNET_INSTRUCTIONS if self.testnet else texts.XROCKET_INSTRUCTIONS,
            expires_at=expires_at,
            status=map_status(str(data["status"])) if data.get("status") else None,
            extra={"clientInvoiceId": body["clientInvoiceId"]},
        )

    async def get_status(self, payment_id: str) -> PaymentStatus:
        data = await self._request("GET", "/api/v1/invoice", params={"invoiceId": payment_id})
        return map_status(str(data.get("status", "")) if isinstance(data, dict) else "")

    async def cancel(self, payment_id: str) -> None:
        """Delete an unpaid invoice so its link can no longer be paid."""
        try:
            await self._request("DELETE", "/api/v1/invoice", params={"invoiceId": payment_id})
        except PaymentError as exc:
            log.info("xRocket: cancel %s: %s", payment_id, exc)  # e.g. already paid / expired
