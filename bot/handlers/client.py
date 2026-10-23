"""Client side: menu, choosing a product and recipient, paying, own orders.

All texts come from ``texts.py``.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..formatting import esc, num, order_card
from ..models import Product, Status
from ..services import OrderService, ShopError, log_client_error
from ._registry import HandlerRegistry

log = logging.getLogger(__name__)
router = HandlerRegistry()


def make_router() -> Router:
    return router.build("client")


class Buy(StatesGroup):
    quantity = State()
    recipient = State()


async def _show(target: "Message | CallbackQuery", text: str, markup=None) -> None:
    """Edit the message behind a button, or send a new one for typed commands."""
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:  # message too old / unchanged: send a fresh one
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


# ----------------------------------------------------------------- menu
@router.message(CommandStart())
@router.message(Command("menu"))
async def start(message: Message, state: FSMContext, service: OrderService) -> None:
    await state.clear()
    await message.answer(texts.WELCOME, reply_markup=kb.reply_menu())  # keyboard at the bottom
    await message.answer(texts.MENU, reply_markup=kb.main_menu())


@router.message(Command("info", "help"))
async def info_cmd(message: Message, service: OrderService) -> None:
    await message.answer(service.settings.info_text, reply_markup=kb.back_home())


@router.message(Command("myid"))
async def myid(message: Message) -> None:
    await message.answer(texts.MY_ID.format(user_id=message.from_user.id))


@router.callback_query(kb.MenuCB.filter(F.action == "home"))
async def home(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.clear()
    await _show(cq, texts.MENU, kb.main_menu())


@router.callback_query(kb.MenuCB.filter(F.action == "info"))
async def info_btn(cq: CallbackQuery, service: OrderService) -> None:
    await _show(cq, service.settings.info_text, kb.back_home())


# -------------------------------------------------------- choose product
@router.callback_query(kb.MenuCB.filter(F.action.in_({"stars", "premium"})))
async def choose_product(cq: CallbackQuery, callback_data: kb.MenuCB, service: OrderService) -> None:
    await show_products(cq, Product(callback_data.action), service)


async def show_products(target: "Message | CallbackQuery", product: Product, service: OrderService) -> None:
    try:
        service.check_order_limit(target.from_user.id)  # tell early, before the whole flow
    except ShopError as exc:
        await _show(target, str(exc), kb.back_home())
        return
    try:
        quotes = await (service.pricing.stars_menu() if product == Product.STARS else service.pricing.premium_menu())
    except Exception as exc:
        log_client_error(exc, user_id=target.from_user.id, where="price menu")
        await _show(target, texts.ERR_GENERIC, kb.back_home())
        return
    title = texts.CHOOSE_STARS if product == Product.STARS else texts.CHOOSE_PREMIUM
    await _show(target, title, kb.products(quotes, product))


@router.callback_query(kb.BuyCB.filter())
async def choose_quantity(cq: CallbackQuery, callback_data: kb.BuyCB, state: FSMContext,
                          service: OrderService) -> None:
    await state.update_data(product=callback_data.product)
    if callback_data.quantity == 0:
        await state.set_state(Buy.quantity)
        await _show(cq, texts.ASK_QUANTITY.format(min=num(service.settings.stars_min),
                                                  max=num(service.settings.stars_max)), kb.back_home())
        return
    try:
        service.check_quantity(Product(callback_data.product), callback_data.quantity)
    except ShopError as exc:  # a package outside the limits (button from an old menu message)
        await cq.answer(str(exc), show_alert=True)
        return
    await _ask_recipient(cq, state, callback_data.quantity)


@router.message(StateFilter(Buy.quantity), F.text)
async def typed_quantity(message: Message, state: FSMContext, service: OrderService) -> None:
    raw = message.text.replace(" ", "").replace("\u00a0", "")
    if not raw.isdigit() or not service.settings.stars_allowed(int(raw)):
        await message.answer(texts.BAD_QUANTITY.format(min=num(service.settings.stars_min),
                                                       max=num(service.settings.stars_max)),
                             reply_markup=kb.back_home())
        return
    await _ask_recipient(message, state, int(raw))


async def _ask_recipient(target: "Message | CallbackQuery", state: FSMContext, quantity: int) -> None:
    await state.update_data(quantity=quantity)
    await state.set_state(Buy.recipient)
    user = target.from_user
    await _show(target, texts.ASK_RECIPIENT if user.username else texts.ASK_RECIPIENT_NO_SELF,
                kb.recipient(user.username))


# ------------------------------------------------------------ recipient
@router.callback_query(StateFilter(Buy.recipient), kb.RecipientCB.filter(F.action == "self"))
async def recipient_self(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    if not cq.from_user.username:
        await cq.answer(texts.NO_OWN_USERNAME, show_alert=True)
        return
    await _create_order(cq, state, service, cq.from_user.username)


@router.message(StateFilter(Buy.recipient), F.text)
async def recipient_typed(message: Message, state: FSMContext, service: OrderService) -> None:
    await _create_order(message, state, service, message.text.strip())


async def _create_order(target: "Message | CallbackQuery", state: FSMContext, service: OrderService,
                        username: str) -> None:
    data = await state.get_data()
    product, quantity = Product(data["product"]), int(data["quantity"])
    user = target.from_user
    chat_id = target.message.chat.id if isinstance(target, CallbackQuery) else target.chat.id
    try:
        recipient = await service.check_recipient(product, username, quantity, user.id)
        order = await service.create_order(buyer_id=user.id, chat_id=chat_id, buyer_username=user.username,
                                           product=product, quantity=quantity, recipient=recipient)
    except ShopError as exc:
        await _show(target, texts.RECIPIENT_FAILED.format(error=esc(exc)), kb.recipient(user.username))
        return
    await state.clear()
    await _show_payment_choice(target, service, order)


async def _show_payment_choice(target, service: OrderService, order) -> None:
    providers = service.providers_for(target.from_user.id)
    text = order_card(order, deadline=service.payment_deadline(order))
    if not providers:
        await _show(target, text + texts.PAYMENT_UNAVAILABLE, kb.back_home())
        return
    await _show(target, text + texts.CHOOSE_PAYMENT, kb.payment_methods(order, providers))


# --------------------------------------------------------------- orders
@router.callback_query(kb.OrderCB.filter(F.action == "view"))
async def view_order(cq: CallbackQuery, callback_data: kb.OrderCB, service: OrderService) -> None:
    try:
        order = service.get_order_for(callback_data.order_id, cq.from_user.id)
    except ShopError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    if order.status == Status.AWAITING_PAYMENT:
        if order.payment_id:  # the method is already chosen: show that same invoice, nothing else
            await _show_invoice(cq, service, order, service.current_invoice(order))
        else:
            await _show_payment_choice(cq, service, order)
        return
    await _show(cq, order_card(order, deadline=service.payment_deadline(order)), kb.order_actions(order))


@router.callback_query(kb.OrderCB.filter(F.action == "pay"))
async def pay(cq: CallbackQuery, callback_data: kb.OrderCB, service: OrderService) -> None:
    try:
        order, invoice = await service.start_payment(callback_data.order_id, callback_data.arg, cq.from_user.id)
    except ShopError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    await _show_invoice(cq, service, order, invoice)


async def _show_invoice(cq: CallbackQuery, service: OrderService, order, invoice) -> None:
    provider = service.providers.get(order.payment_provider or "")
    if provider is None:  # provider switched off in .env after the invoice was created
        await _show(cq, order_card(order, deadline=service.payment_deadline(order)), kb.order_actions(order))
        return
    lines = [order_card(order, deadline=service.payment_deadline(order)), "", texts.PAYMENT_METHOD.format(title=provider.title),
             texts.PAYMENT_AMOUNT.format(amount=invoice.amount, currency=invoice.currency)]
    if invoice.instructions:
        lines += ["", esc(invoice.instructions)]
    lines += ["", texts.PAYMENT_AUTO_CHECK]
    await _show(cq, "\n".join(lines), kb.invoice(order, invoice))


@router.callback_query(kb.OrderCB.filter(F.action == "cancel"))
async def cancel(cq: CallbackQuery, callback_data: kb.OrderCB, service: OrderService) -> None:
    try:
        order = service.get_order_for(callback_data.order_id, cq.from_user.id)
    except ShopError as exc:
        await cq.answer(str(exc), show_alert=True)
        return
    if order.status == Status.AWAITING_PAYMENT:
        await service.expire(order, note=texts.REASON_CANCELLED_BY_BUYER)
    order = service.storage.get(order.id)
    await _show(cq, order_card(order), kb.order_actions(order))


@router.callback_query(kb.MenuCB.filter(F.action == "orders"))
async def my_orders(cq: CallbackQuery, service: OrderService) -> None:
    await show_my_orders(cq, service)


async def show_my_orders(target: "Message | CallbackQuery", service: OrderService) -> None:
    orders = service.storage.list_orders(buyer_id=target.from_user.id, limit=10)
    if not orders:
        await _show(target, texts.NO_ORDERS, kb.back_home())
        return
    await _show(target, texts.MY_ORDERS, kb.my_orders(orders))
