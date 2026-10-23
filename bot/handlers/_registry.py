"""Collect handlers with decorators, build a fresh aiogram ``Router`` on demand.

aiogram routers can be attached to one parent only; building a new router for
every dispatcher keeps the handler modules reusable (several bots, tests).
"""

from __future__ import annotations

from typing import Any, Callable

from aiogram import Router


class HandlerRegistry:
    def __init__(self) -> None:
        self._items: list[tuple[str, tuple, dict, Callable]] = []

    def _add(self, kind: str, filters: tuple, kwargs: dict):
        def decorator(func: Callable) -> Callable:
            self._items.append((kind, filters, kwargs, func))
            return func
        return decorator

    def message(self, *filters: Any, **kwargs: Any):
        return self._add("message", filters, kwargs)

    def callback_query(self, *filters: Any, **kwargs: Any):
        return self._add("callback_query", filters, kwargs)

    def build(self, name: str, *, guard: Callable | None = None) -> Router:
        router = Router(name=name)
        if guard is not None:
            router.message.filter(guard)
            router.callback_query.filter(guard)
        for kind, filters, kwargs, func in self._items:
            getattr(router, kind).register(func, *filters, **kwargs)
        return router
