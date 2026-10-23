"""Thin layer between the shop logic and Telegram (aiogram).

Messages are HTML: the bot is created with ``parse_mode=HTML`` as default
(``__main__.make_bot``), so every text goes out formatted.

The shop logic (``services.OrderService``) only needs this interface, so it
can be tested without Telegram and the transport stays in one place.
"""

from __future__ import annotations

from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class MessengerError(Exception):
    pass


class Messenger(Protocol):
    async def send_message(self, chat_id: int, text: str, *,
                           reply_markup: InlineKeyboardMarkup | None = None) -> int:
        """Send an HTML message, return its message id."""

    async def edit_message(self, chat_id: int, message_id: int, text: str, *,
                           reply_markup: InlineKeyboardMarkup | None = None) -> None: ...

    async def answer_callback(self, callback_id: str, text: str | None = None) -> None: ...


def inline_keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """``[[("text", "callback_data"), ...], ...]`` -> inline keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


class AiogramMessenger:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_message(self, chat_id, text, *, reply_markup=None) -> int:
        try:
            msg = await self.bot.send_message(chat_id, text, reply_markup=reply_markup)
        except (TelegramAPIError, TelegramNetworkError) as exc:
            raise MessengerError(str(exc)) from exc
        return msg.message_id

    async def edit_message(self, chat_id, message_id, text, *, reply_markup=None) -> None:
        try:
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id,
                                             reply_markup=reply_markup)
        except (TelegramAPIError, TelegramNetworkError) as exc:
            raise MessengerError(str(exc)) from exc

    async def answer_callback(self, callback_id, text=None) -> None:
        try:
            await self.bot.answer_callback_query(callback_id, text=text)
        except (TelegramAPIError, TelegramNetworkError) as exc:
            raise MessengerError(str(exc)) from exc
