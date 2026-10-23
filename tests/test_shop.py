"""Shop bot tests: real aiogram dispatching with a fake Telegram session, fake Fragment and tonapi."""

import asyncio
import datetime as dt
import time
from decimal import Decimal

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, Message, Update

from bot.messenger import AiogramMessenger
from bot.models import Product, Status
from bot.payments import build_providers
from bot.pricing import apply_markup, parse_decimal
from bot.settings import Settings
from bot.shop import build_dispatcher, build_service
from bot.storage import Storage
from fragment_api import Fragment
from fragment_api.fragment import FragmentClient
from fragment_api.ton import WalletV5R1, mnemonic
from fragment_api.ton.tonapi import TonApiClient

from .fakes import FakeFragment, FakeProvider, FakeTonApi, mock_client

ADMIN, CLIENT = 111, 222


class FakeSession(BaseSession):
    """Records Bot API calls instead of sending them."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list = []
        self._mid = 1000

    async def close(self) -> None:
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText"):
            self._mid += 1
            return Message(message_id=self._mid, date=dt.datetime.now(),
                           chat=Chat(id=method.chat_id or 0, type="private"), text=method.text)
        return True


class Sim:
    """A user talking to the bot through real aiogram updates."""

    def __init__(self, tmp_path, wallet) -> None:
        self.frag = FakeFragment(wallet.address.to_raw())
        self.ton = FakeTonApi(balance=10**15)  # rich wallet: the fake Fragment price is $15000
        self.ton.usdt_balance = 10**12
        fragment = Fragment(
            FragmentClient({"stel_ssid": "s", "stel_token": "t"}, http_client=mock_client(self.frag.handle)),
            wallet=wallet,
            tonapi=TonApiClient("test-key", http_client=mock_client(self.ton.handle), max_retries=0),
            confirm_timeout=2,
        )
        self.session = FakeSession()
        self.bot = Bot("123456:" + "A" * 35, session=self.session, default=DefaultBotProperties(parse_mode="HTML"))
        settings = Settings(cookies="x", admin_ids=frozenset({ADMIN}), db_path=tmp_path / "shop.db",
                            default_markup=Decimal("10"), default_usd_rub=Decimal("90"))
        self.service = build_service(settings, fragment, AiogramMessenger(self.bot))
        self.fake_pay = FakeProvider()
        self.service.providers["fake"] = self.fake_pay
        self.dp = build_dispatcher(self.service)
        self._uid = 0

    def _feed(self, payload: dict) -> None:
        async def go():
            self._uid += 1
            await self.dp.feed_update(self.bot, Update.model_validate({"update_id": self._uid, **payload}))
            while self.service._tasks:  # wait for background purchases started by the update
                await asyncio.gather(*list(self.service._tasks))
        asyncio.get_event_loop().run_until_complete(go())

    @staticmethod
    def _user(uid, username="alice_buyer"):
        return {"id": uid, "is_bot": False, "first_name": "U", "username": username}

    def say(self, text: str, uid: int = ADMIN, username: str = "alice_buyer", entities: list | None = None) -> None:
        msg = {"message_id": 1, "date": 0, "chat": {"id": uid, "type": "private"},
               "from": self._user(uid, username), "text": text}
        if entities:
            msg["entities"] = entities
        self._feed({"message": msg})

    def press(self, data: str, uid: int = ADMIN, username: str = "alice_buyer") -> None:
        msg = {"message_id": 5, "date": 0, "chat": {"id": uid, "type": "private"}, "text": "x"}
        self._feed({"callback_query": {"id": "cb", "from": self._user(uid, username), "chat_instance": "c",
                                       "data": data, "message": msg}})

    # -- inspecting what the bot sent
    def screens(self) -> list:
        return [c for c in self.session.calls if type(c).__name__ in ("SendMessage", "EditMessageText")]

    def last(self):
        return self.screens()[-1]

    def buttons(self, call=None) -> dict[str, str]:
        call = call or self.last()
        rm = call.reply_markup
        if rm is None:
            return {}
        if hasattr(rm, "keyboard"):  # reply keyboard at the bottom of the chat
            return {b.text: None for row in rm.keyboard for b in row}
        return {b.text: (b.callback_data or b.url) for row in rm.inline_keyboard for b in row}

    def button(self, prefix: str) -> str:
        for text, data in self.buttons().items():
            if text.startswith(prefix):
                return data
        raise AssertionError(f"no button {prefix!r} in {list(self.buttons())}")

    def alerts(self) -> list[str]:
        return [c.text for c in self.session.calls if type(c).__name__ == "AnswerCallbackQuery" and c.text]

    def to(self, chat_id: int) -> list[str]:
        return [c.text for c in self.screens() if c.chat_id == chat_id]


@pytest.fixture(scope="module")
def wallet():
    return WalletV5R1.from_mnemonic(mnemonic.generate())


@pytest.fixture
def sim(tmp_path, wallet):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    s = Sim(tmp_path, wallet)
    yield s
    s.service.storage.close()
    loop.close()


def buy_to_invoice(sim: Sim, uid: int = ADMIN) -> int:
    sim.say("/start", uid)
    sim.press(sim.button("⭐ Купить Stars"), uid)
    sim.press(sim.button("100 ⭐"), uid)
    sim.say("@alice", uid)
    order = sim.service.storage.list_orders(limit=1)[0]
    return order.id


# ---------------------------------------------------------------- pricing
def test_markup_rounding():
    assert apply_markup(Decimal("1.50"), Decimal("10"), Decimal("90")) == (Decimal("1.65"), Decimal("149"))
    assert apply_markup(Decimal("0.75"), Decimal("12.5"), Decimal("95.5")) == (Decimal("0.85"), Decimal("82"))
    assert parse_decimal(" 12,5 % ") == Decimal("12.5")


def test_unknown_payment_provider():
    with pytest.raises(ValueError):
        build_providers(["nope"])


def test_storage_codes_and_guarded_transitions(tmp_path):
    st = Storage(tmp_path / "s.db")
    common = dict(buyer_id=1, buyer_chat_id=1, buyer_username=None, product=Product.STARS, quantity=50,
                  recipient="bob", fragment_price_ton=Decimal("1"), fragment_price_usd=Decimal("1"),
                  markup_percent=Decimal("0"), usd_rub_rate=Decimal("90"), price_usd=Decimal("1"),
                  price_rub=Decimal("90"))
    a, b = st.create_order(**common), st.create_order(**common)
    assert (a.id, b.id) == (1, 2) and a.code != b.code and len(a.code) == 9 and a.code[4] == "-"
    assert st.get_by_code(a.code.lower()).id == 1
    assert st.transition(1, Status.PAID, from_statuses=[Status.AWAITING_PAYMENT]) is not None
    assert st.transition(1, Status.PAID, from_statuses=[Status.AWAITING_PAYMENT]) is None  # already paid
    assert st.claim_fulfillment(1) is not None and st.claim_fulfillment(1) is None  # only once
    assert [e["to_status"] for e in st.events(1)] == ["awaiting_payment", "paid"]
    st.close()


# ------------------------------------------------------------ client flow
def test_menu_and_prices_with_markup(sim):
    sim.say("/start", ADMIN)
    assert list(sim.buttons()) == ["⭐ Купить Stars", "💎 Купить Premium", "📦 Мои заказы", "ℹ️ Информация"]
    sim.say("/start", CLIENT)
    sim.press(sim.button("⭐ Купить Stars"), CLIENT)
    # Fragment: 100 stars = $1.50 -> +10% = $1.65 -> * 90 = 149 RUB
    assert "100 ⭐ — $1.65 / 149 ₽" in sim.buttons()
    sim.press(sim.button("⬅️ Назад"), CLIENT)
    sim.press(sim.button("💎 Купить Premium"), CLIENT)
    assert any(t.startswith("3 мес.") for t in sim.buttons())


def test_client_order_without_public_payment_methods(sim):
    oid = buy_to_invoice(sim, CLIENT)
    order = sim.service.storage.get(oid)
    assert order.buyer_id == CLIENT and order.recipient == "alice" and order.status == Status.AWAITING_PAYMENT
    assert "Оплата временно недоступна" in sim.last().text  # the fake provider is admin-only
    assert "Fake" not in "".join(sim.buttons())


def test_bot_has_no_test_payment(sim):
    from bot import payments, texts

    assert payments.REGISTRY == {} and not hasattr(payments, "StubProvider")
    assert not any(n.startswith(("STUB_", "BTN_SIMULATE")) for n in dir(texts))
    assert Settings(cookies="x", payment_providers=[]).payment_providers == []


def test_unexpected_error_is_hidden(sim, caplog, monkeypatch):
    oid = buy_to_invoice(sim, CLIENT)

    def boom(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sim.service, "get_order_for", boom)
    sim.press(f"o:view:{oid}:", CLIENT)
    assert sim.alerts()[-1] == "⚠️ Ошибка. Попробуйте позже или напишите в поддержку."
    order = sim.service.storage.get(oid)
    line = next(r.getMessage() for r in caplog.records if "client error" in r.getMessage())
    assert f"user={CLIENT}" in line and order.code in line and "database is locked" in line


def test_recipient_self_and_validation(sim):
    sim.say("/start", CLIENT)
    sim.press(sim.button("⭐ Купить Stars"), CLIENT)
    sim.press(sim.button("100 ⭐"), CLIENT)
    sim.say("@nobody_here", CLIENT)
    assert "получатель не найден" in sim.last().text and "No Telegram" not in sim.last().text
    assert sim.service.storage.count_orders() == 0
    sim.frag.users["alice_buyer"] = "RCPT_SELF"
    sim.press(sim.button("🙋 Себе"), CLIENT)
    assert sim.service.storage.get(1).recipient == "alice_buyer"


def test_custom_quantity(sim):
    sim.say("/start", CLIENT)
    sim.press(sim.button("⭐ Купить Stars"), CLIENT)
    sim.press(sim.button("✏️ Другое"), CLIENT)
    sim.say("10", CLIENT)
    assert "от 100 до 10 000" in sim.last().text
    sim.say("777", CLIENT)
    sim.say("@alice", CLIENT)
    assert sim.service.storage.get(1).quantity == 777


def test_full_paid_flow(sim):
    oid = buy_to_invoice(sim)
    sim.press(sim.button("🧪 Fake pay"))
    assert "К оплате: <b>" in sim.last().text and "проверяется автоматически" in sim.last().text
    assert not any("Проверить" in b for b in sim.buttons())  # no manual "check payment" button
    sim.fake_pay.pay(sim.service.storage.get(oid).payment_id)
    asyncio.get_event_loop().run_until_complete(  # like a provider webhook
        sim.service.on_payment_event("fake", sim.service.storage.get(oid).payment_id))
    while sim.service._tasks:
        asyncio.get_event_loop().run_until_complete(asyncio.gather(*list(sim.service._tasks)))
    order = sim.service.storage.get(oid)
    assert order.status == Status.COMPLETED and order.tx_hash
    assert len(sim.ton.sent) == 1  # real purchase, there is no test mode
    # the buyer (here an admin) gets exactly one message about the order; no admin reports on success
    notes = [t for t in sim.to(ADMIN) if order.number in t and "Заказ" in t and "<b>" not in t]
    assert notes == [f"✅ Заказ {order.number} оплачен и выполнен: 100 ⭐ Stars отправлены @alice."]


def test_payment_found_by_background_timer(sim):
    oid = buy_to_invoice(sim)
    sim.press(sim.button("🧪 Fake pay"))
    order = sim.service.storage.get(oid)
    sim.fake_pay.pay(order.payment_id)  # paid, but nobody told the bot
    assert sim.service.storage.get(oid).status == Status.AWAITING_PAYMENT
    loop = asyncio.get_event_loop()
    loop.run_until_complete(sim.service.tick())  # the timer notices it
    while sim.service._tasks:
        loop.run_until_complete(asyncio.gather(*list(sim.service._tasks)))
    assert sim.service.storage.get(oid).status == Status.COMPLETED and len(sim.ton.sent) == 1


def test_webhook_entry_point_rechecks_provider(sim):
    oid = buy_to_invoice(sim)
    sim.press(sim.button("🧪 Fake pay"))
    order = sim.service.storage.get(oid)
    loop = asyncio.get_event_loop()
    # a fake "paid" notification without an actual payment changes nothing
    assert loop.run_until_complete(sim.service.on_payment_event("fake", order.payment_id)).status         == Status.AWAITING_PAYMENT
    assert loop.run_until_complete(sim.service.on_payment_event("fake", "unknown")) is None


def test_my_orders_and_cancel(sim):
    oid = buy_to_invoice(sim, CLIENT)
    sim.press(f"o:cancel:{oid}:", CLIENT)
    assert sim.service.storage.get(oid).status == Status.EXPIRED
    sim.press(sim.button("📦 Мои заказы"), CLIENT)
    assert any(t.startswith(f"№{oid} ⌛") for t in sim.buttons())


def test_cannot_view_foreign_order(sim):
    oid = buy_to_invoice(sim, ADMIN)
    sim.press(f"o:view:{oid}:", CLIENT)
    assert "Заказ не найден" in sim.alerts()


# ---------------------------------------------------------- background
def test_expiry(sim):
    oid = buy_to_invoice(sim, CLIENT)
    sim.service.storage.update(oid, created_at=time.time() - 3600)
    asyncio.get_event_loop().run_until_complete(sim.service.tick())
    assert sim.service.storage.get(oid).status == Status.EXPIRED
    assert any("истёк" in t for t in sim.to(CLIENT))


def test_interrupted_purchase_is_not_retried(sim):
    oid = buy_to_invoice(sim)
    st = sim.service.storage
    st.transition(oid, Status.PAID)
    st.claim_fulfillment(oid)  # as if the bot died mid-purchase
    loop = asyncio.get_event_loop()
    loop.run_until_complete(sim.service.recover_after_restart())
    loop.run_until_complete(sim.service.tick())
    order = st.get(oid)
    assert order.status == Status.ERROR and "перезапуском" in order.error
    assert sim.ton.emulated == [] and sim.ton.sent == []


def confirm_paid(sim, oid):
    """As if the provider confirmed the payment: awaiting_payment -> paid with payment_confirmed."""
    st = sim.service.storage
    st.transition(oid, Status.PAID, extra=dict(st.get(oid).extra, payment_confirmed=True))


def test_concurrent_fulfillment_buys_once(sim):
    oid = buy_to_invoice(sim)
    confirm_paid(sim, oid)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(*(sim.service.fulfill(oid, actor="t") for _ in range(3))))
    assert len(sim.ton.sent) == 1 and sim.service.storage.get(oid).status == Status.COMPLETED


def test_price_drift_stops_purchase(sim):
    oid = buy_to_invoice(sim)
    st = sim.service.storage
    # paid in USDT (default): the USD price is compared; a TON price change does not matter
    st.update(oid, fragment_price_ton=Decimal("1000"), fragment_price_usd=Decimal("10000"))
    confirm_paid(sim, oid)
    asyncio.get_event_loop().run_until_complete(sim.service.fulfill(oid, actor="t"))
    order = st.get(oid)
    assert order.status == Status.ERROR and "$15000" in order.error and sim.ton.sent == []


def test_price_drift_ton_mode(sim):
    sim.service.payment_method = "ton"
    oid = buy_to_invoice(sim)
    st = sim.service.storage
    st.update(oid, fragment_price_ton=Decimal("1000"))  # paid for much less than Fragment now wants
    confirm_paid(sim, oid)
    asyncio.get_event_loop().run_until_complete(sim.service.fulfill(oid, actor="t"))
    order = st.get(oid)
    assert order.status == Status.ERROR and "TON" in order.error and sim.ton.sent == []


def test_purchase_paid_in_usdt(sim):
    """Default FRAGMENT_PAYMENT_METHOD=usdt_ton: one jetton transfer through our own USDT wallet."""
    from fragment_api.ton.jetton import parse_transfer

    from .fakes import JETTON_WALLET, decode_external, parse_v5_body

    oid = buy_to_invoice(sim)
    confirm_paid(sim, oid)
    asyncio.get_event_loop().run_until_complete(sim.service.fulfill(oid, actor="t"))
    assert sim.service.storage.get(oid).status == Status.COMPLETED
    assert sim.frag.calls[[c["method"] for c in sim.frag.calls].index("initBuyStarsRequest")]["payment_method"]         == "usdt_ton"
    (msg,) = parse_v5_body(decode_external(sim.ton.sent[0])[1])["messages"]
    assert msg["dest"].to_raw() == JETTON_WALLET and msg["value"] == 50_000_000
    assert parse_transfer(msg["payload"]).amount == 1_500_000


def test_ton_mode_still_works(sim):
    sim.service.payment_method = "ton"
    oid = buy_to_invoice(sim)
    confirm_paid(sim, oid)
    asyncio.get_event_loop().run_until_complete(sim.service.fulfill(oid, actor="t"))
    assert sim.service.storage.get(oid).status == Status.COMPLETED
    assert [c for c in sim.frag.calls if c["method"] == "initBuyStarsRequest"][-1]["payment_method"] == "ton"


def _funds_sim(sim, usdt: str, ton: str = "10"):
    """Wallet with ``usdt`` USDT / ``ton`` TON; one order costs $15000 on the fake Fragment."""
    sim.ton.usdt_balance = int(Decimal(usdt) * 10**6)
    sim.ton.balance = int(Decimal(ton) * 10**9)


def test_no_order_without_funds(sim):
    _funds_sim(sim, usdt="15000")  # < 15000 * 1.05 (price may still rise 5 %)
    assert _try_order(sim, CLIENT) == 0
    assert "временно недоступен" in sim.last().text and "USDT" not in sim.last().text
    alerts = [t for t in sim.to(ADMIN) if "Не хватает средств" in t]
    assert len(alerts) == 1 and "нужно 15750.00 USDT, есть 15000.00 USDT" in alerts[0]
    sim.say("@alice", CLIENT)  # tries again: still refused, but admins are not spammed
    assert len([t for t in sim.to(ADMIN) if "Не хватает средств" in t]) == 1


def _try_order(sim, uid=ADMIN):
    """Go through the order flow; returns the number of orders afterwards."""
    sim.say("/start", uid)
    sim.press(sim.button("⭐ Купить Stars"), uid)
    sim.press(sim.button("100 ⭐"), uid)
    sim.say("@alice", uid)
    return sim.service.storage.count_orders()


def test_funds_reserved_for_orders_with_invoice(sim):
    _funds_sim(sim, usdt="20000")  # enough for one order (15750), not for two
    first = buy_to_invoice(sim)
    sim.press(sim.button("🧪 Fake pay"))  # invoice created: 15750 USDT reserved for it
    assert sim.service.storage.get(first).payment_id
    assert _try_order(sim) == 1  # 20000 - 15750 left: no second order
    assert "временно недоступен" in sim.last().text
    # the first order expires -> the reservation is released
    order = sim.service.storage.get(first)
    asyncio.get_event_loop().run_until_complete(sim.service.expire(order))
    assert _try_order(sim) == 2


def test_concurrent_invoices_share_funds(sim):
    from bot.services import ShopError

    first, second = buy_to_invoice(sim), buy_to_invoice(sim)
    _funds_sim(sim, usdt="20000")  # enough for one invoice only

    async def pay(oid):
        try:
            return await sim.service.start_payment(oid, "fake", ADMIN)
        except ShopError as exc:
            return exc

    results = asyncio.get_event_loop().run_until_complete(asyncio.gather(pay(first), pay(second)))
    assert sum(isinstance(r, ShopError) for r in results) == 1
    assert [bool(sim.service.storage.get(o).payment_id) for o in (first, second)].count(True) == 1


def test_invoice_refused_when_funds_ran_out(sim):
    oid = buy_to_invoice(sim)  # order created while the wallet was rich
    _funds_sim(sim, usdt="100")
    sim.press(sim.button("🧪 Fake pay"))
    assert sim.alerts()[-1] == "😔 Сейчас этот товар временно недоступен. Попробуйте позже."
    assert sim.service.storage.get(oid).payment_id is None  # no invoice, the client pays nothing
    _funds_sim(sim, usdt="20000")  # topped up: the same order can be paid now
    sim.press(f"o:pay:{oid}:fake")
    assert sim.service.storage.get(oid).payment_id


def test_funds_need_ton_for_gas(sim):
    _funds_sim(sim, usdt="20000", ton="0.09")  # 0.05 gas + 0.05 reserve = 0.1 TON needed
    assert _try_order(sim) == 0
    assert any("TON" in t and "Не хватает средств" in t for t in sim.to(ADMIN))


def test_funds_ton_mode(sim):
    sim.service.payment_method = "ton"
    _funds_sim(sim, usdt="0", ton="11500")  # 11007.11 TON * 1.05 + 0.05 = 11557.52 > 11500
    assert _try_order(sim) == 0
    assert any("нужно 11557.52 TON" in t for t in sim.to(ADMIN))
    _funds_sim(sim, usdt="0", ton="11600")  # USDT is not needed in TON mode
    assert _try_order(sim) == 1


def test_balance_unavailable_means_no_order(sim):
    async def broken():
        raise RuntimeError("tonapi is down")

    sim.service.fragment.get_balance = broken
    assert _try_order(sim) == 0
    assert "⚠️ Ошибка. Попробуйте позже" in sim.last().text and "tonapi" not in sim.last().text


def test_not_enough_usdt(sim):
    oid = buy_to_invoice(sim)
    confirm_paid(sim, oid)
    sim.ton.usdt_balance = 10**6  # USDT was spent elsewhere after the payment: 1 USDT < 1.5 USDT asked
    asyncio.get_event_loop().run_until_complete(sim.service.fulfill(oid, actor="t"))
    order = sim.service.storage.get(oid)
    assert order.status == Status.ERROR and "не хватает средств" in order.error and "USDT" in order.error
    assert sim.ton.sent == []


def test_status_set_by_hand_is_not_bought_automatically(sim):
    """Only awaiting_payment -> paid confirmed by the provider starts the purchase."""
    oid = buy_to_invoice(sim)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(sim.service.admin_set_status(oid, Status.PAID, ADMIN))
    loop.run_until_complete(sim.service.tick())
    loop.run_until_complete(sim.service.fulfill(oid, actor="system"))  # refused: not confirmed
    assert sim.service.storage.get(oid).status == Status.PAID and sim.ton.sent == []
    loop.run_until_complete(sim.service.admin_fulfill(oid, ADMIN))  # explicit admin decision
    assert sim.service.storage.get(oid).status == Status.COMPLETED and len(sim.ton.sent) == 1


# ------------------------------------------------------------------ admin
def test_admin_only(sim):
    sim.say("/start", ADMIN)
    assert not any("Админка" in b for b in sim.buttons())  # only via /admin
    sim.session.calls.clear()
    sim.say("/admin", CLIENT)
    assert sim.screens() == []  # ignored for non-admins
    sim.press("a:home:0::0", CLIENT)
    assert not any("Админка" in (c.text or "") for c in sim.screens())


def test_admin_settings(sim):
    sim.say("/admin")
    assert "Наценка: <b>10%" in sim.last().text
    sim.press(sim.button("📈 Наценка"))
    sim.say("abc")
    assert "Не получилось" in sim.last().text
    sim.say("25,5")
    sim.press(sim.button("💱 Курс"))
    sim.say("100")
    s = sim.service.settings
    assert s.markup_percent == Decimal("25.5") and s.usd_rub_rate == Decimal("100")
    # new prices use the new settings: $1.50 * 1.255 = 1.8825 -> 1.89 -> 189 RUB
    sim.press("m:stars")
    assert "100 ⭐ — $1.89 / 189 ₽" in sim.buttons()


def test_info_text_editable_with_formatting(sim):
    sim.say("/start", CLIENT)
    sim.press(sim.button("ℹ️ Информация"), CLIENT)
    assert "<b>Как купить</b>" in sim.last().text
    sim.say("/admin")
    sim.press(sim.button("ℹ️ Текст"))
    sim.say("Работаем 24/7, поддержка @help", entities=[{"type": "bold", "offset": 0, "length": 8}])
    assert sim.service.settings.info_text == "<b>Работаем</b> 24/7, поддержка @help"
    sim.say("/info", CLIENT)
    assert sim.last().text == "<b>Работаем</b> 24/7, поддержка @help"


def test_html_parse_mode_is_default(tmp_path):
    from bot.__main__ import make_bot

    bot = make_bot(Settings(cookies="x", bot_token="123456:" + "A" * 35))
    assert bot.default.parse_mode == "HTML"


def test_admin_orders_status_and_fulfill(sim):
    oid = buy_to_invoice(sim, CLIENT)
    sim.say("/admin")
    sim.press(sim.button("⏳ ожидает оплаты (1)"))
    sim.press(sim.button(f"№{oid}"))
    assert f"Покупатель: <code>{CLIENT}</code>" in sim.last().text
    sim.press(sim.button("→ ❌ ошибка"))
    assert sim.service.storage.get(oid).status == Status.ERROR
    sim.press(sim.button("▶️ Выполнить"))
    assert "Будут потрачены средства" in sim.last().text
    sim.press(sim.button("▶️ Выполнить"))
    order = sim.service.storage.get(oid)
    assert order.status == Status.COMPLETED and len(sim.ton.sent) == 1
    events = [e["actor"] for e in sim.service.storage.events(oid)]
    assert f"admin:{ADMIN}" in events


def test_admin_find_order(sim):
    oid = buy_to_invoice(sim, CLIENT)
    code = sim.service.storage.get(oid).code
    sim.say("/admin")
    sim.press(sim.button("🔎 Найти"))
    sim.say(code.lower())
    assert f"Заказ №{oid} ({code})" in sim.last().text


# ------------------------------------------------------- bottom keyboard
def test_start_sets_bottom_keyboard(sim):
    sim.say("/start", CLIENT)
    welcome, menu = sim.screens()[-2:]
    kb = welcome.reply_markup
    assert [[b.text for b in row] for row in kb.keyboard] == [
        ["⭐ Купить Stars", "💎 Купить Premium"], ["📦 Мои заказы", "ℹ️ Информация"]]
    assert kb.resize_keyboard and kb.is_persistent
    assert list(sim.buttons(menu)) == ["⭐ Купить Stars", "💎 Купить Premium", "📦 Мои заказы", "ℹ️ Информация"]


def test_bottom_keyboard_buttons(sim):
    sim.say("⭐ Купить Stars", CLIENT)
    assert "100 ⭐ — $1.65 / 149 ₽" in sim.buttons()
    sim.say("💎 Купить Premium", CLIENT)
    assert "Telegram Premium" in sim.last().text
    sim.say("📦 Мои заказы", CLIENT)
    assert "нет заказов" in sim.last().text
    sim.say("ℹ️ Информация", CLIENT)
    assert "<b>Как купить</b>" in sim.last().text


def test_bottom_keyboard_interrupts_input(sim):
    sim.say("/start", CLIENT)
    sim.press(sim.button("⭐ Купить Stars"), CLIENT)
    sim.press(sim.button("100 ⭐"), CLIENT)  # bot now waits for a recipient
    sim.say("💎 Купить Premium", CLIENT)   # ...but the user changed their mind
    assert "Telegram Premium" in sim.last().text
    assert sim.service.storage.count_orders() == 0  # button text was not taken as a username
    sim.say("/admin")
    sim.press(sim.button("📈 Наценка"))  # admin is asked for a number
    sim.say("⭐ Купить Stars")
    assert sim.service.settings.markup_percent == Decimal("10")
    assert "Telegram Stars" in sim.last().text


# ------------------------------------------------------------- texts.py
def test_texts_are_valid():
    from bot.text_check import check_texts

    assert check_texts() == []


def test_broken_texts_are_reported(monkeypatch):
    from bot import texts
    from bot.text_check import check_texts

    monkeypatch.setattr(texts, "NOTIFY_COMPLETED", "Заказ {numbr} выполнен")  # typo in a label
    monkeypatch.setattr(texts, "MENU", "Выберите {что-нибудь")  # unbalanced brace
    problems = check_texts()
    assert any(p.startswith("NOTIFY_COMPLETED: неизвестная метка {numbr}") and "{number}" in p for p in problems)
    assert any(p.startswith("MENU: непарная фигурная скобка") for p in problems)


def test_edited_text_reaches_the_user(sim, monkeypatch):
    from bot import texts

    monkeypatch.setattr(texts, "MENU", "Что будем покупать?")
    sim.say("/start", CLIENT)
    assert sim.last().text == "Что будем покупать?"


# --------------------------------------------------------- Stars limits
def test_default_limits_hide_packages(sim):
    sim.say("/start", CLIENT)
    sim.press(sim.button("⭐ Купить Stars"), CLIENT)
    packages = [b.split(" ⭐")[0] for b in sim.buttons() if " ⭐ — " in b]
    assert packages == ["100", "250", "500", "1 000", "2 500"]  # 50 is below the default minimum


def test_admin_changes_limits(sim):
    sim.say("/admin")
    assert "от <b>100</b> до <b>10 000</b>" in sim.last().text
    sim.press(sim.button("⭐ Лимит Stars"))
    sim.say("1000 100")  # min > max
    assert "Не получилось" in sim.last().text
    sim.say("сто тысяча")
    assert "два целых числа" in sim.last().text
    sim.say("250 - 1 000")
    s = sim.service.settings
    assert (s.stars_min, s.stars_max) == (250, 1000)
    sim.press("m:stars")
    packages = [b.split(" ⭐")[0] for b in sim.buttons() if " ⭐ — " in b]
    assert packages == ["250", "500", "1 000"]
    sim.press(sim.button("✏️ Другое"))
    assert "от 250 до 1 000" in sim.last().text
    sim.say("2000")
    assert "от 250 до 1 000" in sim.last().text and sim.service.storage.count_orders() == 0


def test_limits_cannot_be_bypassed(sim):
    sim.service.settings.set_stars_limits(250, 1000)
    sim.say("/start", CLIENT)
    sim.press("b:stars:50", CLIENT)  # forged / outdated package button
    assert any("от 250 до 1 000" in a for a in sim.alerts())
    from bot.services import ShopError
    with pytest.raises(ShopError):
        asyncio.get_event_loop().run_until_complete(sim.service.create_order(
            buyer_id=CLIENT, chat_id=CLIENT, buyer_username=None, product=Product.STARS, quantity=5000,
            recipient="alice"))
    assert sim.service.storage.count_orders() == 0


def test_parse_stars_limits():
    from bot.pricing import parse_stars_limits

    assert parse_stars_limits("100 10000") == (100, 10000)
    assert parse_stars_limits("100 – 10 000") == (100, 10000)
    assert parse_stars_limits("100,5000") == (100, 5000)
    for bad in ("100", "a b", "1 2 3", "-5 10"):
        with pytest.raises(ValueError):
            parse_stars_limits(bad)


def test_stars_limits_from_env(tmp_path, monkeypatch):
    for k in ("SHOP_STARS_MIN", "SHOP_STARS_MAX"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nSHOP_STARS_MIN=500\nSHOP_STARS_MAX=5000\n")
    s = Settings.load(tmp_path / ".env")
    assert (s.default_stars_min, s.default_stars_max) == (500, 5000)
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nSHOP_STARS_MIN=10\n")
    from fragment_api.exceptions import ConfigError
    with pytest.raises(ConfigError):
        Settings.load(tmp_path / ".env")


# ------------------------------------------------ daily limit of open orders
def _orders(sim, n, status=Status.EXPIRED, buyer=CLIENT, age=0.0):
    st = sim.service.storage
    for _ in range(n):
        o = st.create_order(buyer_id=buyer, buyer_chat_id=buyer, buyer_username=None, product=Product.STARS,
                            quantity=100, recipient="alice", fragment_price_ton=Decimal("1"),
                            fragment_price_usd=Decimal("1.5"), markup_percent=Decimal("10"),
                            usd_rub_rate=Decimal("90"), price_usd=Decimal("1.65"), price_rub=Decimal("149"),
                            created_at=time.time() - age)
        if status != Status.AWAITING_PAYMENT:
            st.transition(o.id, status)


def test_daily_limit_blocks_sixth_order(sim):
    _orders(sim, 2, Status.AWAITING_PAYMENT)
    _orders(sim, 2, Status.EXPIRED)
    _orders(sim, 1, Status.ERROR)
    sim.say("⭐ Купить Stars", CLIENT)
    assert "уже 5 неоплаченных" in sim.last().text and "после" in sim.last().text
    assert " ⭐ — " not in "".join(sim.buttons())  # no packages shown
    from bot.services import ShopError
    with pytest.raises(ShopError):  # direct order creation is blocked too
        asyncio.get_event_loop().run_until_complete(sim.service.create_order(
            buyer_id=CLIENT, chat_id=CLIENT, buyer_username=None, product=Product.STARS, quantity=100,
            recipient="alice"))
    assert sim.service.storage.count_orders() == 5


def test_daily_limit_counts_only_unpaid_expired_error(sim):
    _orders(sim, 4, Status.EXPIRED)
    _orders(sim, 3, Status.COMPLETED)
    _orders(sim, 2, Status.PAID)
    oid = buy_to_invoice(sim, CLIENT)  # 4 counted orders -> the 5th is allowed
    assert sim.service.storage.get(oid).buyer_id == CLIENT
    sim.say("💎 Купить Premium", CLIENT)  # now 5 counted -> blocked
    assert "уже 5" in sim.last().text


def test_daily_limit_window_is_24h(sim):
    _orders(sim, 5, Status.EXPIRED, age=25 * 3600)  # older than a day: not counted
    _orders(sim, 4, Status.EXPIRED, age=3600)
    sim.say("⭐ Купить Stars", CLIENT)
    assert " ⭐ — " in "".join(sim.buttons())


def test_daily_limit_shows_when_possible_again(sim):
    _orders(sim, 1, Status.EXPIRED, age=23 * 3600)  # leaves the window in ~1 h
    _orders(sim, 4, Status.EXPIRED, age=600)
    with pytest.raises(Exception) as ei:
        sim.service.check_order_limit(CLIENT)
    expected = dt.datetime.fromtimestamp(time.time() + 3600).strftime("%d.%m.%Y %H:")
    assert expected in str(ei.value)


def test_daily_limit_other_buyers_and_admins(sim):
    _orders(sim, 5, Status.EXPIRED, buyer=CLIENT)
    sim.service.check_order_limit(333)  # another client is not affected
    _orders(sim, 7, Status.EXPIRED, buyer=ADMIN)
    sim.service.check_order_limit(ADMIN)  # admins are exempt
    sim.service.settings.order_limit_per_day = 0  # 0 = no limit
    sim.service.check_order_limit(CLIENT)


def test_order_limit_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOP_ORDER_LIMIT_PER_DAY", raising=False)
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\n")
    assert Settings.load(tmp_path / ".env").order_limit_per_day == 5
    (tmp_path / ".env").write_text("FRAGMENT_COOKIES=stel_ssid=a; stel_token=b\nSHOP_ORDER_LIMIT_PER_DAY=0\n")
    assert Settings.load(tmp_path / ".env").order_limit_per_day == 0
