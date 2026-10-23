"""RollyPay provider: fake RollyPay API (httpx MockTransport) + the shop bot simulation."""

import asyncio
import datetime as dt
import json
import time
from decimal import Decimal

import httpx
import pytest

from bot.models import Status
from bot.payments import PaymentStatus, RollyPayProvider, build_providers
from bot.payments.rollypay import map_status, parse_time, sign, verify_signature
from bot.settings import Settings
from fragment_web_api.exceptions import ConfigError

from .test_shop import ADMIN, CLIENT, Sim, buy_to_invoice, wallet  # noqa: F401  (fixture)

KEY = "rpk_test_key"
SECRET = "whsec_test"


class FakeRollyPay:
    def __init__(self) -> None:
        self.payments: dict[str, dict] = {}
        self.created: list[dict] = []
        self.gets = 0
        self.nonces: list[str] = []
        self.lifetime = 30 * 60

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == KEY
        self.nonces.append(request.headers["x-nonce"])
        if request.method == "POST" and request.url.path == "/api/v1/payments":
            body = json.loads(request.content)
            self.created.append(body)
            pid = f"pay_{len(self.payments) + 1}"
            expires = dt.datetime.fromtimestamp(time.time() + self.lifetime, dt.timezone.utc)
            p = {"payment_id": pid, "order_id": body["order_id"], "status": "created",
                 "pay_url": f"https://pay.rollypay.io/pay/tok_{pid}", "amount": body["amount"],
                 "payment_currency": "RUB", "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "test": body.get("test", False)}
            self.payments[pid] = p
            return httpx.Response(200, json=p)
        if request.method == "GET" and request.url.path.startswith("/api/v1/payments/"):
            self.gets += 1
            pid = request.url.path.rsplit("/", 1)[-1]
            if pid not in self.payments:
                return httpx.Response(404, json={"error": "payment not found"})
            return httpx.Response(200, json=self.payments[pid])
        return httpx.Response(404, json={"error": "no route"})

    def set(self, pid: str, status: str) -> None:
        self.payments[pid]["status"] = status


@pytest.fixture
def rp(tmp_path, wallet):  # noqa: F811
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    s = Sim(tmp_path, wallet)
    fake = FakeRollyPay()
    provider = RollyPayProvider(KEY, poll_interval=30, http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handle)))
    s.service.providers = {"rollypay": provider, **s.service.providers}
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


def pay_with_rollypay(sim, uid=CLIENT) -> int:
    oid = buy_to_invoice(sim, uid)
    sim.press(sim.button("💳 СБП / карта"), uid)
    return oid


# ------------------------------------------------------------------ unit
def test_status_map_and_time():
    assert map_status("created") == map_status("processing") == PaymentStatus.PENDING
    assert map_status("paid") == PaymentStatus.PAID
    assert map_status("canceled") == PaymentStatus.FAILED
    assert map_status("chargeback") == map_status("refunded") == PaymentStatus.REFUNDED
    assert parse_time("2026-02-23T12:30:00Z") == dt.datetime(2026, 2, 23, 12, 30, tzinfo=dt.timezone.utc).timestamp()
    assert parse_time(None) is None


def test_signature():
    body = b'{"payment_id":"pay_1","status":"paid"}'
    sig = sign(body, "1700000000", SECRET)
    assert verify_signature(body, "1700000000", sig, SECRET)
    assert not verify_signature(body + b" ", "1700000000", sig, SECRET)
    assert not verify_signature(body, "1700000001", sig, SECRET)
    assert not verify_signature(body, "1700000000", sig, "other")
    assert not verify_signature(body, None, sig, SECRET)


# -------------------------------------------------------------- settings
def _env(tmp_path, monkeypatch, text):
    for k in list(__import__("os").environ):
        if k.startswith("ROLLYPAY_") or k == "rollypay_api":
            monkeypatch.delenv(k)
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\n" + text, encoding="utf-8")
    return Settings.load(tmp_path / ".env")


def test_rollypay_enabled_only_with_key(tmp_path, monkeypatch):
    from bot.shop import build_rollypay

    s = _env(tmp_path, monkeypatch, "ROLLYPAY_API=\n")
    assert build_rollypay(s) is None
    assert list(build_providers([], rollypay=build_rollypay(s))) == []
    s = _env(tmp_path, monkeypatch, "rollypay_api=" + KEY + "\n")  # lower-case name works too
    p = build_rollypay(s)
    assert p is not None and not p.admin_only and p.poll_interval == 30 and not p.test
    assert list(build_providers([], rollypay=p)) == ["rollypay"]


def test_rollypay_test_mode_is_admin_only(tmp_path, monkeypatch):
    from bot.shop import build_rollypay

    p = build_rollypay(_env(tmp_path, monkeypatch, f"ROLLYPAY_API={KEY}\nROLLYPAY_TEST=true\n"))
    assert p.test and p.admin_only


def test_rollypay_webhook_mode_settings(tmp_path, monkeypatch):
    from bot.shop import build_rollypay

    with pytest.raises(ConfigError, match="SIGNING_SECRET"):
        _env(tmp_path, monkeypatch, f"ROLLYPAY_API={KEY}\nROLLYPAY_MODE=webhook\n")
    s = _env(tmp_path, monkeypatch, f"ROLLYPAY_API={KEY}\nROLLYPAY_MODE=webhook\nROLLYPAY_SIGNING_SECRET={SECRET}\n"
                                    "ROLLYPAY_WEBHOOK_PORT=9000\nROLLYPAY_WEBHOOK_PATH=hook\n")
    assert build_rollypay(s).poll_interval is None  # webhook: no polling
    assert (s.webhook_port, s.webhook_path) == (9000, "/hook")
    with pytest.raises(ConfigError):
        _env(tmp_path, monkeypatch, f"ROLLYPAY_API={KEY}\nROLLYPAY_MODE=sometimes\n")


# ---------------------------------------------------------- client flow
def test_invoice_request_and_screen(rp):
    sim, fake, provider = rp
    provider.return_url = "https://t.me/shop_bot"
    oid = pay_with_rollypay(sim)
    body = fake.created[0]
    order = sim.service.storage.get(oid)
    assert body["amount"] == f"{order.price_rub:.2f}" and body["payment_currency"] == "RUB"
    assert body["order_id"].startswith(order.code) and "test" not in body
    assert body["redirect_url"] == "https://t.me/shop_bot" and order.number in body["description"]
    assert sim.buttons()["💳 Перейти к оплате"] == "https://pay.rollypay.io/pay/tok_pay_1"
    assert "Оплатите до" in sim.last().text
    # the order now expires together with the link (30 min), not after PAYMENT_TIMEOUT_MIN (10 min)
    assert abs(sim.service.payment_deadline(order) - (time.time() + 30 * 60)) < 5


def test_test_flag_in_request(rp):
    sim, fake, provider = rp
    provider.test = True
    pay_with_rollypay(sim, ADMIN)
    assert fake.created[0]["test"] is True
    assert "ТЕСТОВЫЙ режим RollyPay" in sim.last().text


def test_each_request_has_new_nonce(rp):
    sim, fake, _ = rp
    pay_with_rollypay(sim)
    tick(sim)
    assert len(fake.nonces) == len(set(fake.nonces)) >= 2


# -------------------------------------------------------------- polling
def test_polling_every_30_seconds(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    tick(sim)
    tick(sim)  # within 30 s: no second request
    assert fake.gets == 1
    sim.service._last_check = {k: v - 31 for k, v in sim.service._last_check.items()}
    fake.set("pay_1", "paid")
    tick(sim)
    order = sim.service.storage.get(oid)
    assert fake.gets == 2 and order.status == Status.COMPLETED and len(sim.ton.sent) == 1


def test_expires_with_payment_link(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    order = sim.service.storage.get(oid)
    sim.service.storage.update(oid, extra=dict(order.extra, payment_expires_at=time.time() - 1))
    fake.set("pay_1", "expired")
    tick(sim)
    assert sim.service.storage.get(oid).status == Status.EXPIRED


def test_paid_just_before_expiry_is_not_lost(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    tick(sim)  # polled once, next poll not due for 30 s
    order = sim.service.storage.get(oid)
    sim.service.storage.update(oid, extra=dict(order.extra, payment_expires_at=time.time() - 1))
    fake.set("pay_1", "paid")
    tick(sim)  # deadline passed: one last check before expiring finds the payment
    assert sim.service.storage.get(oid).status == Status.COMPLETED


def test_late_payment_after_expiry(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    order = sim.service.storage.get(oid)
    sim.service.storage.update(oid, extra=dict(order.extra, payment_expires_at=time.time() - 1))
    fake.set("pay_1", "expired")
    tick(sim)
    assert sim.service.storage.get(oid).status == Status.EXPIRED
    fake.set("pay_1", "paid")  # the money arrived late (allowed by RollyPay)
    for _ in range(2):
        sim.service._last_check.clear()
        tick(sim)
    # not awaiting_payment -> paid: no automatic purchase, admins decide (one alert)
    assert sim.service.storage.get(oid).status == Status.EXPIRED and sim.ton.sent == []
    alerts = [t for t in sim.to(ADMIN) if "после истечения заказа" in t]
    assert len(alerts) == 1 and "pay_1" in alerts[0]


# --------------------------------------------------------------- webhook
def _webhook(sim, payload: dict, *, secret=SECRET, timestamp=None, signature=None):
    from aiohttp.test_utils import TestClient, TestServer

    from bot.webhook import Route, make_app

    body = json.dumps(payload).encode()
    ts = str(int(time.time()) if timestamp is None else timestamp)
    headers = {"X-Timestamp": ts, "X-Signature": signature or sign(body, ts, secret),
               "Content-Type": "application/json"}

    async def go():
        client = TestClient(TestServer(make_app(sim.service, rollypay=Route("/webhooks/rollypay", SECRET))))
        await client.start_server()
        try:
            resp = await client.post("/webhooks/rollypay", data=body, headers=headers)
            return resp.status
        finally:
            await client.close()

    status = run(go())
    drain(sim)
    return status


def test_webhook_paid(rp):
    sim, fake, provider = rp
    provider.poll_interval = None  # webhook mode
    oid = pay_with_rollypay(sim)
    tick(sim)
    assert fake.gets == 0  # webhook mode: the bot does not poll
    fake.set("pay_1", "paid")
    assert _webhook(sim, {"event_type": "payment.paid", "payment_id": "pay_1", "status": "paid"}) == 200
    assert sim.service.storage.get(oid).status == Status.COMPLETED and len(sim.ton.sent) == 1


def test_notifications_one_to_buyer_none_to_admin(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    before_client, before_admin = len(sim.to(CLIENT)), len(sim.to(ADMIN))
    fake.set("pay_1", "paid")
    _webhook(sim, {"payment_id": "pay_1", "status": "paid"})
    order = sim.service.storage.get(oid)
    assert order.status == Status.COMPLETED
    assert sim.to(CLIENT)[before_client:] == [
        f"✅ Заказ {order.number} оплачен и выполнен: 100 ⭐ Stars отправлены @alice."]
    assert sim.to(ADMIN)[before_admin:] == []  # admins hear about errors only


def test_admin_notified_on_error(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    sim.ton.usdt_balance = 0  # the USDT was spent elsewhere after the invoice was created
    before_admin = len(sim.to(ADMIN))
    fake.set("pay_1", "paid")
    _webhook(sim, {"payment_id": "pay_1", "status": "paid"})
    order = sim.service.storage.get(oid)
    assert order.status == Status.ERROR
    assert any("❗" in t for t in sim.to(CLIENT))
    (alert,) = sim.to(ADMIN)[before_admin:]
    assert alert.startswith(f"❌ Ошибка заказа {order.number}")


def test_webhook_signature_and_trust(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    event = {"event_type": "payment.paid", "payment_id": "pay_1", "status": "paid"}
    assert _webhook(sim, event, secret="wrong") == 403
    assert _webhook(sim, event, timestamp=int(time.time()) - 3600) == 403  # replayed old webhook
    # correctly signed, but RollyPay's API says the payment is not paid: nothing happens
    assert _webhook(sim, event) == 200
    assert sim.service.storage.get(oid).status == Status.AWAITING_PAYMENT
    assert _webhook(sim, {"payment_id": "pay_unknown", "status": "paid"}) == 200
    assert _webhook(sim, {"status": "paid"}) == 400


def test_one_invoice_per_order(rp):
    sim, fake, _ = rp
    oid = buy_to_invoice(sim, CLIENT)
    sim.press(sim.button("💳 СБП / карта"), CLIENT)  # invoice pay_1
    assert set(sim.buttons()) == {"💳 Перейти к оплате", "❌ Отменить заказ"}  # no "other method"
    # old method-list buttons are still in the chat: the same method gives the same invoice...
    sim.press(f"o:pay:{oid}:rollypay", CLIENT)
    assert len(fake.created) == 1 and sim.service.storage.get(oid).payment_id == "pay_1"
    # ...any other method is refused
    for code in ("fake", "xrocket"):
        sim.press(f"o:pay:{oid}:{code}", CLIENT)
        assert "уже выбран способ оплаты" in sim.alerts()[-1]
    assert sim.service.storage.get(oid).payment_provider == "rollypay"
    # "My orders" -> the order shows that same invoice, not the method list
    sim.session.calls.clear()
    sim.press(f"o:view:{oid}:pay", CLIENT)
    assert "💳 Перейти к оплате" in sim.buttons() and "СБП" in sim.last().text
    assert len(fake.created) == 1


def test_concurrent_presses_create_one_invoice(rp):
    sim, fake, _ = rp
    oid = buy_to_invoice(sim, CLIENT)
    results = run(asyncio.gather(*(sim.service.start_payment(oid, "rollypay", CLIENT) for _ in range(3))))
    assert len(fake.created) == 1 and {inv.payment_id for _, inv in results} == {"pay_1"}


def test_already_paid_link_is_rejected(rp):
    """E.g. the bot's database was lost and RollyPay returned a payment that is already paid."""
    sim, fake, provider = rp
    original = fake.handle

    def paid_on_creation(request):
        resp = original(request)
        if request.method == "POST":
            pid = f"pay_{len(fake.payments)}"
            fake.set(pid, "paid")
            return httpx.Response(200, json=fake.payments[pid])
        return resp

    provider._http = httpx.AsyncClient(transport=httpx.MockTransport(paid_on_creation))
    oid = pay_with_rollypay(sim)
    order = sim.service.storage.get(oid)
    assert order.status == Status.AWAITING_PAYMENT and order.payment_id is None
    assert sim.alerts()[-1] == "⚠️ Ошибка. Попробуйте позже или напишите в поддержку."
    assert any("подозрительный счёт pay_1" in t and "paid" in t for t in sim.to(ADMIN))
    tick(sim)
    assert sim.ton.sent == []


def test_invoice_of_another_order_is_rejected(rp):
    sim, fake, provider = rp
    first = pay_with_rollypay(sim)  # pay_1 belongs to the first order
    original = fake.handle

    def same_payment(request):
        if request.method == "POST":  # the provider hands out the old payment again
            return httpx.Response(200, json=fake.payments["pay_1"])
        return original(request)

    provider._http = httpx.AsyncClient(transport=httpx.MockTransport(same_payment))
    second = pay_with_rollypay(sim)
    assert second != first and sim.service.storage.get(second).payment_id is None
    assert any("уже принадлежит заказу" in t for t in sim.to(ADMIN))


def test_refund_after_completion(rp):
    sim, fake, _ = rp
    oid = pay_with_rollypay(sim)
    fake.set("pay_1", "paid")
    _webhook(sim, {"payment_id": "pay_1", "status": "paid"})
    fake.set("pay_1", "chargeback")
    _webhook(sim, {"payment_id": "pay_1", "status": "chargeback"})
    assert sim.service.storage.get(oid).status == Status.COMPLETED
    assert any("возврате/чарджбэке" in t for t in sim.to(ADMIN))


def test_rollypay_errors_are_shown(rp):
    sim, fake, provider = rp

    def broken(request):
        return httpx.Response(400, json={"error": "payment cap exceeded"})

    provider._http = httpx.AsyncClient(transport=httpx.MockTransport(broken))
    buy_to_invoice(sim, CLIENT)
    sim.press(sim.button("💳 СБП / карта"), CLIENT)
    # the client sees a neutral message, the provider's error text goes to the server log only
    assert sim.alerts()[-1] == "⚠️ Ошибка. Попробуйте позже или напишите в поддержку."
    assert not any("payment cap" in a for a in sim.alerts())
