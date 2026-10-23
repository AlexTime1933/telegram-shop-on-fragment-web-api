"""Inline keyboards and callback data."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from .models import Order, Product, Status
from .payments import Invoice, PaymentProvider
from .pricing import Quote
from . import texts
from .formatting import order_button, quote_line


class MenuCB(CallbackData, prefix="m"):
    action: str  # home | stars | premium | orders | info


class BuyCB(CallbackData, prefix="b"):
    product: str
    quantity: int  # 0 = enter another amount


class RecipientCB(CallbackData, prefix="r"):
    action: str  # self


class OrderCB(CallbackData, prefix="o"):
    action: str  # view | pay | cancel
    order_id: int
    arg: str = ""


class AdminCB(CallbackData, prefix="a"):
    action: str  # home | list | view | status | fulfill | fulfill_ok | markup | rate | stars_limits | xrocket_fee
    #               | info | find | wallet
    order_id: int = 0
    arg: str = ""
    page: int = 0


# Main menu buttons: shown inline under messages and in the keyboard at the bottom of the chat.
MENU_BUTTONS = {texts.BTN_STARS: "stars", texts.BTN_PREMIUM: "premium", texts.BTN_ORDERS: "orders",
                texts.BTN_INFO: "info"}


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, action in MENU_BUTTONS.items():
        kb.button(text=text, callback_data=MenuCB(action=action))
    kb.adjust(2, 2)
    return kb.as_markup()


def reply_menu() -> ReplyKeyboardMarkup:
    """Persistent keyboard under the input field with the same main menu buttons."""
    kb = ReplyKeyboardBuilder()
    for text in MENU_BUTTONS:
        kb.button(text=text)
    kb.adjust(2, 2)
    return kb.as_markup(resize_keyboard=True, is_persistent=True)


def back_home() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_HOME, callback_data=MenuCB(action="home"))
    return kb.as_markup()


def products(quotes: list[Quote], product: Product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for q in quotes:
        kb.button(text=quote_line(q), callback_data=BuyCB(product=product.value, quantity=q.quantity))
    if product == Product.STARS:
        kb.button(text=texts.BTN_OTHER_AMOUNT, callback_data=BuyCB(product=product.value, quantity=0))
    kb.button(text=texts.BTN_BACK, callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def recipient(own_username: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if own_username:
        kb.button(text=texts.BTN_SELF.format(username=own_username), callback_data=RecipientCB(action="self"))
    kb.button(text=texts.BTN_CANCEL_INPUT, callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def payment_methods(order: Order, providers: list[PaymentProvider]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in providers:
        amount, sign = p.price_label(order)
        kb.button(text=texts.BTN_PAYMENT_METHOD.format(title=p.title, amount=amount, currency_sign=sign),
                  callback_data=OrderCB(action="pay", order_id=order.id, arg=p.code))
    kb.button(text=texts.BTN_CANCEL_ORDER, callback_data=OrderCB(action="cancel", order_id=order.id))
    kb.adjust(1)
    return kb.as_markup()


def invoice(order: Order, inv: Invoice) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if inv.url:
        kb.button(text=texts.BTN_GO_TO_PAYMENT, url=inv.url)
    kb.button(text=texts.BTN_CANCEL_ORDER, callback_data=OrderCB(action="cancel", order_id=order.id))
    kb.adjust(1)
    return kb.as_markup()


def order_actions(order: Order) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if order.status == Status.AWAITING_PAYMENT:
        kb.button(text=texts.BTN_PAY, callback_data=OrderCB(action="view", order_id=order.id, arg="pay"))
    kb.button(text=texts.BTN_ORDERS, callback_data=MenuCB(action="orders"))
    kb.button(text=texts.BTN_HOME, callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def my_orders(orders: list[Order]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(text=order_button(o), callback_data=OrderCB(action="view", order_id=o.id))
    kb.button(text=texts.BTN_HOME, callback_data=MenuCB(action="home"))
    kb.adjust(1)
    return kb.as_markup()


# ------------------------------------------------------------------ admin
def admin_home(counts: dict[Status, int], markup: str, rate: str, stars_min: str,
               stars_max: str, xrocket_fee: str | None = None) -> InlineKeyboardMarkup:
    """``xrocket_fee``: e.g. "0.5 USDT"; the fee button is shown only when xRocket is enabled."""
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_ADMIN_ALL_ORDERS.format(count=sum(counts.values())), callback_data=AdminCB(action="list"))
    for st in Status:
        kb.button(text=texts.BTN_ADMIN_STATUS_FILTER.format(status=st.label, count=counts.get(st, 0)),
                  callback_data=AdminCB(action="list", arg=st.value))
    kb.button(text=texts.BTN_ADMIN_FIND, callback_data=AdminCB(action="find"))
    kb.button(text=texts.BTN_ADMIN_MARKUP.format(value=markup), callback_data=AdminCB(action="markup"))
    kb.button(text=texts.BTN_ADMIN_RATE.format(value=rate), callback_data=AdminCB(action="rate"))
    kb.button(text=texts.BTN_ADMIN_STARS_LIMITS.format(min=stars_min, max=stars_max),
              callback_data=AdminCB(action="stars_limits"))
    if xrocket_fee is not None:
        value, currency = xrocket_fee.split(" ", 1)
        kb.button(text=texts.BTN_ADMIN_XROCKET_FEE.format(value=value, currency=currency),
                  callback_data=AdminCB(action="xrocket_fee"))
    kb.button(text=texts.BTN_ADMIN_INFO, callback_data=AdminCB(action="info"))
    kb.button(text=texts.BTN_ADMIN_WALLET, callback_data=AdminCB(action="wallet"))
    kb.adjust(1, 2, 2, 1, 1, 2, 1, *([1] if xrocket_fee is not None else []), 1, 1)
    return kb.as_markup()


def admin_list(orders: list[Order], status: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(text=order_button(o), callback_data=AdminCB(action="view", order_id=o.id, arg=status, page=page))
    nav = 0
    if page > 0:
        kb.button(text=texts.BTN_ADMIN_PREV, callback_data=AdminCB(action="list", arg=status, page=page - 1))
        nav += 1
    if has_next:
        kb.button(text=texts.BTN_ADMIN_NEXT, callback_data=AdminCB(action="list", arg=status, page=page + 1))
        nav += 1
    kb.button(text=texts.BTN_ADMIN_HOME, callback_data=AdminCB(action="home"))
    kb.adjust(*([1] * len(orders)), *([nav] if nav else []), 1)
    return kb.as_markup()


def admin_order(order: Order, back_status: str = "", back_page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    others = [st for st in Status if st != order.status]
    for st in others:
        kb.button(text=texts.BTN_ADMIN_SET_STATUS.format(status=st.label),
                  callback_data=AdminCB(action="status", order_id=order.id, arg=st.value))
    rows = [2] * (len(others) // 2) + ([1] if len(others) % 2 else [])
    if order.status in (Status.PAID, Status.ERROR):
        kb.button(text=texts.BTN_ADMIN_FULFILL, callback_data=AdminCB(action="fulfill", order_id=order.id))
        rows.append(1)
    kb.button(text=texts.BTN_ADMIN_REFRESH, callback_data=AdminCB(action="view", order_id=order.id, arg=back_status,
                                                        page=back_page))
    kb.button(text=texts.BTN_ADMIN_TO_LIST, callback_data=AdminCB(action="list", arg=back_status, page=back_page))
    rows.append(2)
    kb.adjust(*rows)
    return kb.as_markup()


def confirm(yes: AdminCB, no: AdminCB, yes_text: str = texts.BTN_YES, no_text: str = texts.BTN_NO) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=yes_text, callback_data=yes)
    kb.button(text=no_text, callback_data=no)
    kb.adjust(2)
    return kb.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=texts.BTN_ADMIN_HOME, callback_data=AdminCB(action="home"))
    return kb.as_markup()
