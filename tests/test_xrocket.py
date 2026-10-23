"""xRocket Pay provider: fake Pay API (httpx MockTransport) + the shop bot simulation."""

import asyncio
import datetime as dt
import json
import logging
import time
from decimal import Decimal

import httpx
import pytest

from bot.models import Status
from bot.payments import PaymentStatus, XRocketProvider, build_providers
from bot.payments.xrocket import MAINNET_URL, TESTNET_URL, map_status, sign, verify_signature
from bot.settings import Settings
from fragment_api.exceptions import ConfigError

from .test_shop import ADMIN, CLIENT, Sim, buy_to_invoice, wallet  # noqa: F401  (fixture)

TOKEN = "xr_test_token"
SECRET = "xr_webhook_secret"


class FakeXRocket:
    def __init__(self) -> None:
        self.invoices: dict[str, dict] = {}
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.gets = 0
        self.hosts: set[str] = set()

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.hosts.add(f"{request.url.scheme}://{request.url.host}")
        path = request.url.path
        if path == "/api/v1/rates":  # public
            return httpx.Response(200, json=[{"currency": "GRAM", "rate": "1.314"}, {"currency": "USDT", "rate": "1"}])
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"type": "/api/problems/unauthorized", "title": "Unauthorized",
                                             "status": 401, "detail": "bad token", "kind": "unauthorized"})
        if request.method == "POST" and path == "/api/v1/invoices":
            body = json.loads(request.content)
            self.created.append(body)
            iid = f"inv_{len(self.invoices) + 1}"
            now = dt.datetime.now(dt.timezone.utc)
            inv = {"id": iid, "priceAmount": body["priceAmount"], "priceCurrency": body["priceCurrency"],
                   "clientInvoiceId": body.get("clientInvoiceId"), "expiresIn": body.get("expiresIn"),
                   "createdAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                   "expiresAt": (now + dt.timedelta(milliseconds=body["expiresIn"])).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                   "status": "active", "links": {"telegramBotLink": f"https://t.me/xRocket?start={iid}"}}
            self.invoices[iid] = inv
            return httpx.Response(201, json=inv)
        if path == "/api/v1/invoice":
            iid = request.url.params.get("invoiceId")
            inv = self.invoices.get(iid)
            if inv is None:
                return httpx.Response(404, json={"type": "/api/problems/invoice_not_found", "title": "Not found",
                                                 "status": 404, "kind": "not_found"})
            if request.method == "GET":
                self.gets += 1
                return httpx.Response(200, json=inv)
            if request.method == "DELETE":
                self.deleted.append(iid)
                if inv["status"] != "active":
                    return httpx.Response(400, json={"type": "/api/problems/invoice_not_active", "status": 400})
                inv["status"] = "cancelled"
                return httpx.Response(200, json=inv)
        return httpx.Response(404, json={"type": "/api/problems/not_found", "status": 404})

    def set(self, iid: str, status: str) -> None:
        self.invoices[iid]["status"] = status


@pytest.fixture
def xr(tmp_path, wallet):  # noqa: F811
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    s = Sim(tmp_path, wallet)
    fake = FakeXRocket()
    provider = XRocketProvider(TOKEN, poll_interval=30, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handle)))
    s.service.providers = {"xrocket": provider, **s.service.providers}
    yield s, fake, provider
    s.service.storage.close()
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def drain(sim):
    while sim.service._tasks:
        run(asyncio.gather(*list(sim.service._tasks)))


def tick(sim):
    run(sim.service.tick())
    drain(sim)


def pay_with_xrocket(sim, uid=CLIENT) -> int:
    oid = buy_to_invoice(sim, uid)
    sim.press(sim.button("🚀 Криптовалюта"), uid)
    return oid


# ------------------------------------------------------------------ unit
def test_status_map():
    assert map_status("active") == map_status("partially_paid") == PaymentStatus.PENDING
    assert map_status("paid") == PaymentStatus.PAID
    assert map_status("expired") == PaymentStatus.EXPIRED
    assert map_status("cancelled") == PaymentStatus.FAILED
    assert map_status("something_new") == PaymentStatus.PENDING  # open enum: unknown = in progress


def _headers(body: bytes, *, secret=SECRET, ts=None, version="v1"):
    ts = str(int(time.time() * 1000) if ts is None else ts)
    return {"Signature": sign(body, ts, secret), "Signature-Version": version, "Signature-Timestamp": ts}


def test_signature_rules():
    body = b'{"id":"1","type":"invoice"}'
    assert verify_signature(body, _headers(body), SECRET) is None
    assert verify_signature(body + b" ", _headers(body), SECRET) == "invalid signature"
    assert verify_signature(body, _headers(body, secret="other"), SECRET) == "invalid signature"
    assert verify_signature(body, _headers(body, version="v2"), SECRET).startswith("unsupported")
    old = int(time.time() * 1000) - 6 * 60 * 1000
    assert verify_signature(body, _headers(body, ts=old), SECRET) == "stale timestamp"  # 5 min window
    h = _headers(body)
    del h["Signature"]
    assert verify_signature(body, h, SECRET) == "missing signature headers"
    assert verify_signature(body, _headers(body), "") == "no webhook secret configured"


# -------------------------------------------------------------- settings
def _env(tmp_path, monkeypatch, text):
    for k in list(__import__("os").environ):
        if k.startswith(("XROCKET_", "WEBHOOK_")):
            monkeypatch.delenv(k)
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\n" + text, encoding="utf-8")
    return Settings.load(tmp_path / ".env")


def test_enabled_only_with_token(tmp_path, monkeypatch):
    from bot.shop import build_xrocket

    s = _env(tmp_path, monkeypatch, "XROCKET_API=\n")
    assert build_xrocket(s) is None
    s = _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\n")
    p = build_xrocket(s)
    assert p._base == MAINNET_URL and not p.testnet and not p.admin_only and p.poll_interval == 30
    assert (p.currency, p.fee, p.expire_seconds) == ("USDT", Decimal("0.5"), 1800)
    assert list(build_providers([], xrocket=p)) == ["xrocket"]


def test_testnet_uses_testnet_url_and_token(tmp_path, monkeypatch):
    from bot.shop import build_xrocket

    # testnet selected but only the mainnet token given: xRocket is not offered (no mixing)
    assert build_xrocket(_env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_TESTNET=true\n")) is None
    s = _env(tmp_path, monkeypatch, f"XROCKET_API=main\nXROCKET_TESTNET=true\nXROCKET_TESTNET_API={TOKEN}\n")
    p = build_xrocket(s)
    assert p._base == TESTNET_URL and p._token == TOKEN and p.testnet and p.admin_only


def test_settings_validation(tmp_path, monkeypatch):
    with pytest.raises(ConfigError, match="WEBHOOK_SECRET"):
        _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_MODE=webhook\n")
    with pytest.raises(ConfigError, match="86400"):
        _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_EXPIRE_SECONDS=90000\n")
    with pytest.raises(ConfigError, match="https"):
        _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_WEBHOOK_URL=http://x.com/hook\n")
    s = _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_CURRENCY=gram\nXROCKET_FEE=0,25\n"
                                    f"XROCKET_MODE=webhook\nXROCKET_WEBHOOK_SECRET={SECRET}\nWEBHOOK_PORT=9100\n")
    assert (s.xrocket_currency, s.xrocket_fee, s.webhook_port) == ("GRAM", Decimal("0.25"), 9100)


# ---------------------------------------------------------- client flow
def test_invoice_request_price_and_screen(xr):
    sim, fake, provider = xr
    provider.return_url = "https://t.me/shop_bot"
    oid = buy_to_invoice(sim, CLIENT)
    expected = sim.service.storage.get(oid).price_usd + Decimal("0.5")  # USDT 1:1 + fixed fee
    assert f"🚀 Криптовалюта USDT (xRocket) — {expected:.2f} USDT" in sim.buttons()
    sim.press(sim.button("🚀 Криптовалюта"), CLIENT)
    body = fake.created[0]
    order = sim.service.storage.get(oid)
    assert body["priceAmount"] == f"{expected:.2f}" and body["priceCurrency"] == "USDT"
    assert body["payCurrencies"] == ["USDT"]
    assert body["expiresIn"] == 1800 * 1000  # milliseconds in the Pay API
    assert body["clientInvoiceId"].startswith(order.code) and order.number in body["description"]
    assert body["url"]["successUrl"] == "https://t.me/shop_bot" and "callback" not in body
    assert sim.buttons()["💳 Перейти к оплате"] == "https://t.me/xRocket?start=inv_1"
    assert (order.payment_amount, order.payment_currency) == (expected, "USDT")
    assert abs(sim.service.payment_deadline(order) - (time.time() + 1800)) < 5


def test_non_stablecoin_uses_rate(xr):
    sim, fake, provider = xr
    provider.currency = "GRAM"
    oid = buy_to_invoice(sim, CLIENT)
    sim.press(sim.button("🚀 Криптовалюта"), CLIENT)
    from decimal import ROUND_CEILING
    usd = sim.service.storage.get(oid).price_usd
    expected = (usd / Decimal("1.314") + Decimal("0.5")).quantize(Decimal("0.0001"), ROUND_CEILING)
    assert fake.created[0]["priceAmount"] == str(expected) and fake.created[0]["payCurrencies"] == ["GRAM"]
    # sanity check of the formula on round numbers: $1.65 -> 1.65 / 1.314 + 0.5 = 1.7557.. -> 1.7558
    assert (Decimal("1.65") / Decimal("1.314") + Decimal("0.5")).quantize(Decimal("0.0001"), ROUND_CEILING)         == Decimal("1.7558")


def test_webhook_url_sent_with_invoice(xr):
    sim, fake, provider = xr
    provider.webhook_url = "https://shop.example.com/webhooks/xrocket"
    pay_with_xrocket(sim)
    assert fake.created[0]["callback"]["callbackUrl"] == "https://shop.example.com/webhooks/xrocket"


def test_testnet_is_admin_only(xr):
    sim, fake, provider = xr
    provider.testnet = provider.admin_only = True
    buy_to_invoice(sim, CLIENT)
    assert not any("Криптовалюта" in b for b in sim.buttons())
    pay_with_xrocket(sim, ADMIN)
    assert "ТЕСТОВАЯ сеть xRocket" in sim.last().text


def test_api_errors_are_logged_not_shown(xr, caplog):
    sim, fake, provider = xr
    provider._token = "wrong"
    oid = buy_to_invoice(sim, CLIENT)
    sim.press(sim.button("🚀 Криптовалюта"), CLIENT)
    assert sim.alerts()[-1] == "⚠️ Ошибка. Попробуйте позже или напишите в поддержку."
    assert not any("401" in a for a in sim.alerts())
    order = sim.service.storage.get(oid)
    line = next(r.getMessage() for r in caplog.records if "client error" in r.getMessage())
    assert f"user={CLIENT}" in line and order.number in line and order.code in line
    assert "xRocket 401 unauthorized" in line


# -------------------------------------------------------------- polling
def test_polling_every_30_seconds(xr):
    sim, fake, _ = xr
    oid = pay_with_xrocket(sim)
    tick(sim)
    tick(sim)
    assert fake.gets == 1  # not again within 30 s
    sim.service._last_check = {k: v - 31 for k, v in sim.service._last_check.items()}
    fake.set("inv_1", "paid")
    tick(sim)
    assert sim.service.storage.get(oid).status == Status.COMPLETED and len(sim.ton.sent) == 1
    sim.service._last_check.clear()
    tick(sim)  # paid invoice seen again: still one purchase
    assert len(sim.ton.sent) == 1


def test_expiry_cancels_invoice(xr):
    sim, fake, _ = xr
    oid = pay_with_xrocket(sim)
    order = sim.service.storage.get(oid)
    sim.service.storage.update(oid, extra=dict(order.extra, payment_expires_at=time.time() - 1))
    tick(sim)  # last status check (active) -> expire -> DELETE the invoice
    assert sim.service.storage.get(oid).status == Status.EXPIRED
    assert fake.deleted == ["inv_1"] and fake.invoices["inv_1"]["status"] == "cancelled"


def test_fee_changed_in_admin_panel(xr):
    sim, fake, provider = xr
    provider.fee = lambda: sim.service.settings.xrocket_fee  # as wired by build_service
    sim.say("/admin")
    assert "🚀 Комиссия xRocket: 0.5 USDT" in sim.buttons()
    sim.press(sim.button("🚀 Комиссия xRocket"))
    sim.say("-1")
    assert "от 0 до 1000" in sim.last().text
    sim.say("1,25")
    assert sim.service.settings.xrocket_fee == Decimal("1.25")
    assert "🚀 Комиссия xRocket: 1.25 USDT" in sim.buttons()
    oid = buy_to_invoice(sim, CLIENT)
    price = sim.service.storage.get(oid).price_usd
    assert any(f"{price + Decimal('1.25')} USDT" in b for b in sim.buttons())  # method button
    sim.press(sim.button("🚀 Криптовалюта"), CLIENT)
    assert Decimal(fake.created[-1]["priceAmount"]) == price + Decimal("1.25")


def test_fee_wired_to_settings(tmp_path, monkeypatch, wallet):  # noqa: F811
    from bot.shop import build_service

    s = Sim(tmp_path, wallet)
    settings = _env(tmp_path, monkeypatch, f"XROCKET_API={TOKEN}\nXROCKET_FEE=0.7\n")
    service = build_service(settings, s.service.fragment, s.service.notifier)
    xr = service.providers["xrocket"]
    assert xr.fee == Decimal("0.7")  # initial value from .env
    service.settings.xrocket_fee = Decimal("10")
    assert xr.fee == Decimal("10") and service.settings._s.get_setting("xrocket_fee", "") == "10"
    service.storage.close()
    s.service.storage.close()


def test_method_cannot_be_switched(xr):
    sim, fake, _ = xr
    oid = pay_with_xrocket(sim)
    sim.press(f"o:pay:{oid}:fake", CLIENT)  # old method-list button
    assert "уже выбран способ оплаты" in sim.alerts()[-1]
    sim.press(f"o:pay:{oid}:xrocket", CLIENT)
    order = sim.service.storage.get(oid)
    assert order.payment_id == "inv_1" and len(fake.invoices) == 1 and fake.deleted == []


# --------------------------------------------------------------- webhook
def _post(sim, payload, *, headers=None, raw=None):
    from aiohttp.test_utils import TestClient, TestServer

    from bot.webhook import Route, make_app

    body = raw if raw is not None else json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", **(_headers(body) if headers is None else headers)}

    async def go():
        client = TestClient(TestServer(make_app(sim.service, xrocket=Route("/webhooks/xrocket", SECRET))))
        await client.start_server()
        try:
            resp = await client.post("/webhooks/xrocket", data=body, headers=hdrs)
            return resp.status
        finally:
            await client.close()

    status = run(go())
    drain(sim)
    return status


def _event(eid, invoice_id="inv_1", event="invoice_status_changed", status="paid"):
    return {"id": eid, "type": "invoice", "timestamp": "2026-10-23T10:30:00.000Z",
            "data": {"event": event, "invoice": {"id": invoice_id, "status": status}}}


def test_webhook_paid_once(xr):
    sim, fake, provider = xr
    provider.poll_interval = None  # webhook mode
    oid = pay_with_xrocket(sim)
    tick(sim)
    assert fake.gets == 0  # no polling in webhook mode
    fake.set("inv_1", "paid")
    # xRocket sends both events when a payment completes an invoice, and may retry each of them
    assert _post(sim, _event("e1", event="payment_status_changed")) == 200
    assert _post(sim, _event("e2")) == 200
    assert _post(sim, _event("e2")) == 200  # retried delivery
    assert sim.service.storage.get(oid).status == Status.COMPLETED
    assert len(sim.ton.sent) == 1  # bought exactly once
    assert sim.service.storage.webhook_seen("xrocket", "e2")


def test_webhook_rejected_and_logged(xr, caplog):
    sim, fake, _ = xr
    oid = pay_with_xrocket(sim)
    fake.set("inv_1", "paid")
    body = json.dumps(_event("e1")).encode()
    caplog.set_level(logging.WARNING, logger="bot.webhook")
    assert _post(sim, None, raw=body, headers={}) == 401  # no signature at all
    assert _post(sim, None, raw=body, headers=_headers(body, secret="forged")) == 401
    assert _post(sim, None, raw=body, headers=_headers(body, version="v9")) == 401
    assert _post(sim, None, raw=body, headers=_headers(body, ts=int(time.time() * 1000) - 600_000)) == 401
    assert sim.service.storage.get(oid).status == Status.AWAITING_PAYMENT and sim.ton.sent == []
    assert sum("xrocket webhook ignored" in r.message for r in caplog.records) == 4


def test_webhook_body_not_trusted(xr):
    sim, fake, _ = xr
    oid = pay_with_xrocket(sim)
    # correctly signed "paid", but the API says the invoice is still active
    assert _post(sim, _event("e1")) == 200
    assert sim.service.storage.get(oid).status == Status.AWAITING_PAYMENT
    assert _post(sim, {"id": "e2", "type": "cheque", "data": {}}) == 200  # other event types ignored
    assert _post(sim, _event("e3", invoice_id="inv_unknown")) == 200
    assert _post(sim, {"type": "invoice"}) == 400
