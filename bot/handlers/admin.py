"""Admin panel (only for BOT_ADMIN_IDS, opened with /admin): orders, statuses, markup, USD rate,
Stars limits, xRocket fee, info text, wallet. All texts come from ``texts.py``."""

from __future__ import annotations

import logging
from decimal import InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject
from fragment_web_api import PAY_USDT_TON

from .. import keyboards as kb
from .. import texts
from ..formatting import admin_order_card, esc, num
from ..models import Status
from ..pricing import parse_decimal, parse_stars_limits
from ..services import OrderService, ShopError
from ._registry import HandlerRegistry
from .client import _show

log = logging.getLogger(__name__)
router = HandlerRegistry()
PAGE = 8


class AdminInput(StatesGroup):
    markup = State()
    rate = State()
    find = State()
    info = State()
    stars_limits = State()
    xrocket_fee = State()


async def _is_admin(event: TelegramObject, service: OrderService) -> bool:
    user = getattr(event, "from_user", None)
    return bool(user and service.is_admin(user.id))


def make_router() -> Router:
    # every handler in this router is admin-only
    return router.build("admin", guard=_is_admin)


async def _home_text(service: OrderService) -> tuple[str, object]:
    counts = {st: service.storage.count_orders(status=st) for st in Status}
    s = service.settings
    text = texts.ADMIN_HOME.format(markup=s.markup_percent, rate=s.usd_rub_rate, stars_min=num(s.stars_min),
                                   stars_max=num(s.stars_max), minutes=s.payment_timeout_min)
    xr = service.providers.get("xrocket")
    return text, kb.admin_home(counts, str(s.markup_percent), str(s.usd_rub_rate), num(s.stars_min),
                               num(s.stars_max), xrocket_fee=f"{s.xrocket_fee} {xr.currency}" if xr else None)


def _card(order, service: OrderService) -> str:
    return admin_order_card(order, service.storage.events(order.id))


@router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext, service: OrderService) -> None:
    await state.clear()
    text, markup = await _home_text(service)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "home"))
async def admin_home(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.clear()
    text, markup = await _home_text(service)
    await _show(cq, text, markup)


# ---------------------------------------------------------------- orders
@router.callback_query(kb.AdminCB.filter(F.action == "list"))
async def order_list(cq: CallbackQuery, callback_data: kb.AdminCB, service: OrderService) -> None:
    status = Status(callback_data.arg) if callback_data.arg else None
    page = max(callback_data.page, 0)
    orders = service.storage.list_orders(status=status, limit=PAGE + 1, offset=page * PAGE)
    if status:
        title = texts.ADMIN_ORDERS_TITLE_STATUS.format(status=status.label, page=page + 1)
    else:
        title = texts.ADMIN_ORDERS_TITLE.format(page=page + 1)
    if not orders:
        title += texts.ADMIN_NO_ORDERS
    await _show(cq, title, kb.admin_list(orders[:PAGE], callback_data.arg, page, len(orders) > PAGE))


@router.callback_query(kb.AdminCB.filter(F.action == "view"))
async def order_view(cq: CallbackQuery, callback_data: kb.AdminCB, service: OrderService) -> None:
    order = service.storage.get(callback_data.order_id)
    if order is None:
        await cq.answer(texts.ERR_ORDER_NOT_FOUND, show_alert=True)
        return
    await _show(cq, _card(order, service), kb.admin_order(order, callback_data.arg, callback_data.page))


@router.callback_query(kb.AdminCB.filter(F.action == "status"))
async def order_set_status(cq: CallbackQuery, callback_data: kb.AdminCB, service: OrderService) -> None:
    order = await service.admin_set_status(callback_data.order_id, Status(callback_data.arg), cq.from_user.id)
    if order is None:
        await cq.answer(texts.ERR_ORDER_NOT_FOUND, show_alert=True)
        return
    await _show(cq, _card(order, service), kb.admin_order(order))
    await cq.answer(texts.ADMIN_STATUS_CHANGED.format(status=order.status.label))


@router.callback_query(kb.AdminCB.filter(F.action == "fulfill"))
async def fulfill_ask(cq: CallbackQuery, callback_data: kb.AdminCB, service: OrderService) -> None:
    order = service.storage.get(callback_data.order_id)
    if order is None:
        await cq.answer(texts.ERR_ORDER_NOT_FOUND, show_alert=True)
        return
    text = texts.ADMIN_FULFILL_CONFIRM.format(number=order.number, title=esc(order.title),
                                              recipient=esc(order.recipient))
    if order.tx_hash:
        text += texts.ADMIN_FULFILL_WARNING
    await _show(cq, text, kb.confirm(kb.AdminCB(action="fulfill_ok", order_id=order.id),
                                     kb.AdminCB(action="view", order_id=order.id), texts.BTN_ADMIN_FULFILL_CONFIRM))


@router.callback_query(kb.AdminCB.filter(F.action == "fulfill_ok"))
async def fulfill_run(cq: CallbackQuery, callback_data: kb.AdminCB, service: OrderService) -> None:
    await cq.answer(texts.ADMIN_FULFILLING)
    try:
        order = await service.admin_fulfill(callback_data.order_id, cq.from_user.id)
    except ShopError as exc:
        await cq.message.answer(texts.ADMIN_ERROR.format(error=esc(exc)))
        return
    await cq.message.answer(_card(order, service), reply_markup=kb.admin_order(order))


@router.callback_query(kb.AdminCB.filter(F.action == "find"))
async def find_ask(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminInput.find)
    await _show(cq, texts.ADMIN_ASK_ORDER, kb.admin_back())


@router.message(StateFilter(AdminInput.find), F.text)
async def find_run(message: Message, state: FSMContext, service: OrderService) -> None:
    raw = message.text.strip().lstrip("№#")
    order = service.storage.get(int(raw)) if raw.isdigit() else service.storage.get_by_code(raw)
    if order is None:
        await message.answer(texts.ADMIN_ORDER_NOT_FOUND, reply_markup=kb.admin_back())
        return
    await state.clear()
    await message.answer(_card(order, service), reply_markup=kb.admin_order(order))


# -------------------------------------------------------------- settings
@router.callback_query(kb.AdminCB.filter(F.action == "markup"))
async def markup_ask(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.set_state(AdminInput.markup)
    await _show(cq, texts.ADMIN_ASK_MARKUP.format(value=service.settings.markup_percent), kb.admin_back())


@router.message(StateFilter(AdminInput.markup), F.text)
async def markup_set(message: Message, state: FSMContext, service: OrderService) -> None:
    try:
        service.settings.markup_percent = parse_decimal(message.text)
    except (InvalidOperation, ValueError) as exc:
        await message.answer(texts.ADMIN_BAD_VALUE.format(error=esc(exc) or texts.ADMIN_NEED_NUMBER),
                             reply_markup=kb.admin_back())
        return
    await state.clear()
    text, markup = await _home_text(service)
    await message.answer(texts.ADMIN_MARKUP_SET.format(value=service.settings.markup_percent) + text,
                         reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "rate"))
async def rate_ask(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.set_state(AdminInput.rate)
    await _show(cq, texts.ADMIN_ASK_RATE.format(value=service.settings.usd_rub_rate), kb.admin_back())


@router.message(StateFilter(AdminInput.rate), F.text)
async def rate_set(message: Message, state: FSMContext, service: OrderService) -> None:
    try:
        service.settings.usd_rub_rate = parse_decimal(message.text)
    except (InvalidOperation, ValueError) as exc:
        await message.answer(texts.ADMIN_BAD_VALUE.format(error=esc(exc) or texts.ADMIN_NEED_NUMBER),
                             reply_markup=kb.admin_back())
        return
    await state.clear()
    text, markup = await _home_text(service)
    await message.answer(texts.ADMIN_RATE_SET.format(value=service.settings.usd_rub_rate) + text,
                         reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "xrocket_fee"))
async def xrocket_fee_ask(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    xr = service.providers.get("xrocket")
    if xr is None:
        await cq.answer()
        return
    await state.set_state(AdminInput.xrocket_fee)
    await _show(cq, texts.ADMIN_ASK_XROCKET_FEE.format(value=service.settings.xrocket_fee, currency=xr.currency),
                kb.admin_back())


@router.message(StateFilter(AdminInput.xrocket_fee), F.text)
async def xrocket_fee_set(message: Message, state: FSMContext, service: OrderService) -> None:
    try:
        service.settings.xrocket_fee = parse_decimal(message.text)
    except (InvalidOperation, ValueError) as exc:
        await message.answer(texts.ADMIN_BAD_VALUE.format(error=esc(exc) or texts.ADMIN_NEED_NUMBER),
                             reply_markup=kb.admin_back())
        return
    await state.clear()
    xr = service.providers.get("xrocket")
    text, markup = await _home_text(service)
    await message.answer(texts.ADMIN_XROCKET_FEE_SET.format(value=service.settings.xrocket_fee,
                                                           currency=xr.currency if xr else "") + text,
                         reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "stars_limits"))
async def stars_limits_ask(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.set_state(AdminInput.stars_limits)
    s = service.settings
    await _show(cq, texts.ADMIN_ASK_STARS_LIMITS.format(min=num(s.stars_min), max=num(s.stars_max)),
                kb.admin_back())


@router.message(StateFilter(AdminInput.stars_limits), F.text)
async def stars_limits_set(message: Message, state: FSMContext, service: OrderService) -> None:
    try:
        minimum, maximum = parse_stars_limits(message.text)
        service.settings.set_stars_limits(minimum, maximum)
    except ValueError as exc:
        await message.answer(texts.ADMIN_BAD_VALUE.format(error=esc(exc)), reply_markup=kb.admin_back())
        return
    await state.clear()
    text, markup = await _home_text(service)
    await message.answer(texts.ADMIN_STARS_LIMITS_SET.format(min=num(minimum), max=num(maximum)) + text,
                         reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "info"))
async def info_ask(cq: CallbackQuery, state: FSMContext, service: OrderService) -> None:
    await state.set_state(AdminInput.info)
    await _show(cq, texts.ADMIN_INFO_CURRENT.format(text=service.settings.info_text))
    await cq.message.answer(texts.ADMIN_ASK_INFO, reply_markup=kb.admin_back())


@router.message(StateFilter(AdminInput.info), F.text)
async def info_set(message: Message, state: FSMContext, service: OrderService) -> None:
    try:
        service.settings.info_text = message.html_text  # keeps the admin's bold/italic/links as HTML
    except ValueError as exc:
        await message.answer(texts.ADMIN_BAD_INFO.format(error=esc(exc)), reply_markup=kb.admin_back())
        return
    await state.clear()
    await message.answer(texts.ADMIN_INFO_SET)
    text, markup = await _home_text(service)
    await message.answer(service.settings.info_text)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.AdminCB.filter(F.action == "wallet"))
async def wallet(cq: CallbackQuery, service: OrderService) -> None:
    f = service.fragment
    lines = [texts.ADMIN_WALLET_TITLE]
    if f.wallet is None:
        lines.append(texts.ADMIN_WALLET_NO_SEED)
    else:
        lines.append(texts.ADMIN_WALLET_ADDRESS.format(version=f.wallet.VERSION, address=f.wallet_address))
        usdt = service.payment_method == PAY_USDT_TON
        lines.append(texts.ADMIN_WALLET_PAY_METHOD.format(
            method=texts.ADMIN_PAY_METHOD_USDT if usdt else texts.ADMIN_PAY_METHOD_TON))
        try:
            lines.append(texts.ADMIN_WALLET_BALANCE.format(ton=await f.get_balance()))
            lines.append(texts.ADMIN_WALLET_USDT.format(usdt=await f.get_usdt_balance()))
        except Exception as exc:
            lines.append(texts.ADMIN_WALLET_BALANCE_ERROR.format(error=esc(exc)))
        try:
            linked = await f.check_session_wallet()
            lines.append(texts.ADMIN_WALLET_LINKED if linked else texts.ADMIN_WALLET_NOT_LINKED)
        except Exception as exc:
            lines.append(texts.ADMIN_WALLET_FRAGMENT_ERROR.format(error=esc(exc)))
    await _show(cq, "\n".join(lines), kb.admin_back())
