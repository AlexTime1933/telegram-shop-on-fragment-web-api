"""aiogram routers of the shop bot."""

from aiogram import Router

from . import admin, client, menu


def build_router() -> Router:
    root = Router(name="shop")
    root.include_router(menu.make_router())  # bottom keyboard first: works in any state
    root.include_router(admin.make_router())  # admin first: its text inputs take precedence for admins
    root.include_router(client.make_router())
    return root


__all__ = ["build_router"]
