"""Buttons of the persistent keyboard at the bottom of the chat.

They work in any state: pressing one cancels whatever the user was typing
(quantity, recipient, admin input) instead of being taken as that input.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import keyboards as kb
from ..models import Product
from ..services import OrderService
from ._registry import HandlerRegistry
from .client import show_my_orders, show_products

router = HandlerRegistry()


def make_router() -> Router:
    return router.build("menu")


@router.message(F.text.in_(kb.MENU_BUTTONS))
async def menu_button(message: Message, state: FSMContext, service: OrderService) -> None:
    await state.clear()
    action = kb.MENU_BUTTONS[message.text]
    if action == "stars":
        await show_products(message, Product.STARS, service)
    elif action == "premium":
        await show_products(message, Product.PREMIUM, service)
    elif action == "orders":
        await show_my_orders(message, service)
    else:
        await message.answer(service.settings.info_text, reply_markup=kb.back_home())
