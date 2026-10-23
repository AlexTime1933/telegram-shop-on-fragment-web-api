"""RollyPay (https://docs.rollypay.io): RUB payments (SBP, cards) with a hosted payment page.

* create: ``POST /api/v1/payments`` -> ``pay_url`` + ``expires_at``
* status: ``GET /api/v1/payments/{payment_id}``
* auth:   ``X-API-Key`` + a unique ``X-Nonce`` per request
* webhooks: HMAC-SHA256 of ``timestamp + "." + raw_body`` with the terminal's
  ``signing_secret`` in ``X-Signature`` (``X-Timestamp`` header); see ``bot/webhook.py``
* sandbox: ``"test": true`` in the create request (``ROLLYPAY_TEST``)

There is no cancel endpoint in the API: an unpaid link simply expires.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import secrets
import uuid
from decimal import Decimal
from urllib.parse import quote

import httpx

from .. import texts
from ..models import Order
from .base import Invoice, PaymentError, PaymentProvider, PaymentStatus

log = logging.getLogger(__name__)

BASE_URL = "https://rollypay.io"

_STATUS = {
    "created": PaymentStatus.PENDING,
    "processing": PaymentStatus.PENDING,
    "paid": PaymentStatus.PAID,
    "expired": PaymentStatus.EXPIRED,
    "canceled": PaymentStatus.FAILED,
    "cancelled": PaymentStatus.FAILED,
    "chargeback": PaymentStatus.REFUNDED,
    "refunded": PaymentStatus.REFUNDED,
}


def map_status(status: str) -> PaymentStatus:
    try:
        return _STATUS[status.lower()]
    except (KeyError, AttributeError):
        raise PaymentError(f"unknown RollyPay status {status!r}") from None


def parse_time(value: str | None) -> float | None:
    """``"2026-02-23T12:30:00Z"`` -> unix time."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sign(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, timestamp: str | None, signature: str | None, secret: str) -> bool:
    """Webhook signature check (constant-time)."""
    if not timestamp or not signature or not secret:
        return False
    return hmac.compare_digest(sign(body, timestamp, secret), signature.strip().lower())


class RollyPayProvider(PaymentProvider):
    code = "rollypay"
    currency = "RUB"

    def __init__(self, api_key: str, *, test: bool = False, poll_interval: float | None = 30.0,
                 base_url: str = BASE_URL, http_client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ValueError("RollyPay API key is empty")
        self.title = texts.ROLLYPAY_TITLE
        self.test = test
        # A sandbox payment is "paid" with a button, but the bot then spends real TON on
        # Fragment: in test mode only shop admins may use it.
        self.admin_only = test
        self.poll_interval = poll_interval
        self.return_url: str | None = None  # set at start: link back to the bot
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = {"X-API-Key": self._key, "X-Nonce": str(uuid.uuid4()), "Accept": "application/json"}
        try:
            resp = await self._http.request(method, f"{self._base}/api/v1{path}", headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise PaymentError(f"RollyPay: network error {type(exc).__name__}") from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            message = (data.get("error") or data.get("message")) if isinstance(data, dict) else None
            raise PaymentError(f"RollyPay {resp.status_code}: {message or resp.text[:200]}")
        if not isinstance(data, dict):
            raise PaymentError("RollyPay: unexpected response")
        return data

    async def create_invoice(self, order: Order, amount: Decimal) -> Invoice:
        body = {
            "amount": f"{amount:.2f}",
            "payment_currency": "RUB",
            # random, never the sequential number: a reset database must not reproduce an old
            # order_id (RollyPay could hand back that order's already paid link)
            "order_id": f"{order.code}-{secrets.token_hex(3)}",
            "description": texts.ROLLYPAY_DESCRIPTION.format(number=order.number, title=order.title,
                                                             recipient=order.recipient),
            "customer_id": str(order.buyer_id),
            "metadata": {"order": order.id, "code": order.code},
        }
        if self.return_url:
            body["redirect_url"] = self.return_url
        if self.test:
            body["test"] = True
        data = await self._request("POST", "/payments", json=body)
        if not data.get("payment_id") or not data.get("pay_url"):
            raise PaymentError("RollyPay: no payment_id / pay_url in response")
        return Invoice(
            payment_id=str(data["payment_id"]),
            amount=Decimal(str(data.get("amount") or body["amount"])),
            currency=str(data.get("payment_currency") or "RUB"),
            url=str(data["pay_url"]),
            instructions=texts.ROLLYPAY_TEST_INSTRUCTIONS if self.test else None,
            expires_at=parse_time(data.get("expires_at")),
            status=map_status(str(data["status"])) if data.get("status") else None,
            extra={"order_id": body["order_id"], "test": bool(data.get("test", self.test))},
        )

    async def get_status(self, payment_id: str) -> PaymentStatus:
        data = await self._request("GET", f"/payments/{quote(payment_id, safe='')}")
        return map_status(str(data.get("status", "")))
