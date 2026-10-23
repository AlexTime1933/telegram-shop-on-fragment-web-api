"""HTTP endpoint for payment webhooks (RollyPay and/or xRocket in ``*_MODE=webhook``).

One aiohttp server (WEBHOOK_HOST / WEBHOOK_PORT) with a path per provider. Every
webhook is authenticated by its HMAC signature; after that the order service
re-checks the payment status through the provider's API, so the body itself is
never trusted for money, and a repeated notification cannot pay an order twice.

RollyPay: ``X-Signature`` = HMAC-SHA256(signing_secret, timestamp + "." + body), ``X-Timestamp``
in seconds; answers 200 / 403 (bad signature) / 400 / 503 (retry).

xRocket (Pay API): ``Signature`` = HMAC-SHA256(webhook secret, "{Signature-Timestamp}.{body}"),
``Signature-Version: v1``, ``Signature-Timestamp`` in ms; answers 200 / 401 (bad signature,
logged and ignored) / 400 / 503 (retry). Deliveries are de-duplicated on the envelope ``id``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from aiohttp import web

from .payments import rollypay as rp
from .payments import xrocket as xr
from .services import OrderService

log = logging.getLogger(__name__)

ROLLYPAY_MAX_CLOCK_SKEW = 600  # seconds
PROCESS_TIMEOUT = 8.0  # both providers wait 10 s for an answer


@dataclass(frozen=True)
class Route:
    path: str
    secret: str


async def _process(service: OrderService, provider: str, payment_id: str) -> web.Response | None:
    """Re-check the payment via the provider API; a Response only on failure (to make it retry)."""
    try:
        await asyncio.wait_for(service.on_payment_event(provider, payment_id), PROCESS_TIMEOUT)
    except asyncio.TimeoutError:
        return web.Response(status=503, text="busy, retry")
    except Exception:
        log.exception("%s webhook processing failed", provider)
        return web.Response(status=503, text="error, retry")
    return None


def _rollypay_handler(service: OrderService, secret: str):
    async def handle(request: web.Request) -> web.Response:
        body = await request.read()
        timestamp = request.headers.get("X-Timestamp")
        if not rp.verify_signature(body, timestamp, request.headers.get("X-Signature"), secret):
            log.warning("rollypay webhook: bad signature from %s", request.remote)
            return web.Response(status=403, text="invalid signature")
        try:
            if abs(time.time() - int(timestamp)) > ROLLYPAY_MAX_CLOCK_SKEW:
                return web.Response(status=403, text="stale timestamp")
        except (TypeError, ValueError):
            return web.Response(status=403, text="bad timestamp")
        try:
            event = json.loads(body)
            payment_id = str(event["payment_id"])
        except (ValueError, KeyError, TypeError):
            return web.Response(status=400, text="bad body")
        log.info("rollypay webhook: %s %s (test=%s)", event.get("event_type"), payment_id, event.get("test"))
        return await _process(service, "rollypay", payment_id) or web.Response(text="OK")

    return handle


def _xrocket_handler(service: OrderService, secret: str):
    async def handle(request: web.Request) -> web.Response:
        body = await request.read()  # raw bytes: the signature covers them exactly
        problem = xr.verify_signature(body, request.headers, secret)
        if problem:
            log.warning("xrocket webhook ignored from %s: %s", request.remote, problem)
            return web.Response(status=401, text=problem)
        try:
            event = json.loads(body)
            event_id = str(event["id"])
            event_type = event.get("type")
            data = event.get("data") or {}
        except (ValueError, KeyError, TypeError, AttributeError):
            return web.Response(status=400, text="bad body")
        if event_type != "invoice":
            return web.Response(text="OK")  # cheques, payouts, ...: not used by the shop
        if service.storage.webhook_seen("xrocket", event_id):
            return web.Response(text="OK")  # a retry of something already processed
        invoice_id = str((data.get("invoice") or {}).get("id") or "")
        if not invoice_id:
            return web.Response(status=400, text="no invoice id")
        log.info("xrocket webhook %s: %s invoice %s", event_id, data.get("event"), invoice_id)
        failed = await _process(service, "xrocket", invoice_id)
        if failed:
            return failed
        service.storage.mark_webhook("xrocket", event_id)
        return web.Response(text="OK")

    return handle


def make_app(service: OrderService, *, rollypay: Route | None = None, xrocket: Route | None = None
             ) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    if rollypay:
        app.router.add_post(rollypay.path, _rollypay_handler(service, rollypay.secret))
    if xrocket:
        app.router.add_post(xrocket.path, _xrocket_handler(service, xrocket.secret))
    return app


async def start_webhook_server(service: OrderService, *, host: str, port: int, rollypay: Route | None = None,
                               xrocket: Route | None = None) -> web.AppRunner:
    runner = web.AppRunner(make_app(service, rollypay=rollypay, xrocket=xrocket), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    for name, route in (("RollyPay", rollypay), ("xRocket", xrocket)):
        if route:
            log.info("%s webhook listening on http://%s:%s%s", name, host, port, route.path)
    return runner
