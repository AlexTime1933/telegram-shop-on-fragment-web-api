"""Builds messages from the templates in ``texts.py`` (the texts themselves live there)."""

from __future__ import annotations

import datetime as dt
import html

from . import texts
from .models import Order, Product, Status
from .pricing import Quote


def esc(value: object) -> str:
    """Escape a value for HTML messages (usernames, errors, ...)."""
    return html.escape(str(value), quote=False)


def ts(value: float | None) -> str:
    return dt.datetime.fromtimestamp(value).strftime(texts.DATETIME_FORMAT) if value else texts.NO_VALUE


def num(value: int) -> str:
    """1000000 -> "1 000 000"."""
    return f"{value:,}".replace(",", " ")


def quote_line(q: Quote) -> str:
    if q.product == Product.STARS:
        return texts.BTN_QUOTE_STARS.format(quantity=num(q.quantity), usd=q.price_usd, rub=q.price_rub)
    return texts.BTN_QUOTE_PREMIUM.format(months=q.quantity, usd=q.price_usd, rub=q.price_rub)


def order_card(order: Order, *, deadline: float | None = None) -> str:
    lines = [
        texts.ORDER_CARD_TITLE.format(number=order.number),
        texts.ORDER_CARD_ITEM.format(title=esc(order.title), recipient=esc(order.recipient)),
        texts.ORDER_CARD_PRICE.format(usd=order.price_usd, rub=order.price_rub),
        texts.ORDER_CARD_STATUS.format(status=order.status.label),
    ]
    if order.payment_amount is not None:
        lines.append(texts.ORDER_CARD_INVOICE.format(amount=order.payment_amount, currency=order.payment_currency))
    if order.status == Status.AWAITING_PAYMENT and deadline:
        lines.append(texts.ORDER_CARD_PAY_UNTIL.format(time=ts(deadline)))
    return "\n".join(lines)


def admin_order_card(order: Order, events: list[dict]) -> str:
    buyer = texts.ADMIN_CARD_BUYER.format(buyer_id=order.buyer_id)
    if order.buyer_username:
        buyer += texts.ADMIN_CARD_BUYER_USERNAME.format(username=esc(order.buyer_username))
    payment = texts.ADMIN_CARD_PAYMENT.format(provider=esc(order.payment_provider or texts.NO_VALUE),
                                              payment_id=esc(order.payment_id or ""))
    if order.payment_amount is not None:
        payment += texts.ADMIN_CARD_PAYMENT_AMOUNT.format(amount=order.payment_amount,
                                                          currency=order.payment_currency)
    lines = [
        texts.ADMIN_CARD_TITLE.format(number=order.number, status=order.status.label),
        texts.ORDER_CARD_ITEM.format(title=esc(order.title), recipient=esc(order.recipient)),
        buyer,
        texts.ADMIN_CARD_DATES.format(created=ts(order.created_at), updated=ts(order.updated_at)),
        "",
        texts.ADMIN_CARD_FRAGMENT.format(ton=order.fragment_price_ton, usd=order.fragment_price_usd),
        texts.ADMIN_CARD_PRICING.format(markup=order.markup_percent, rate=order.usd_rub_rate,
                                        usd=order.price_usd, rub=order.price_rub),
        payment,
        texts.ADMIN_CARD_PAID.format(paid=ts(order.paid_at), completed=ts(order.completed_at)),
    ]
    if order.fragment_req_id:
        lines.append(texts.ADMIN_CARD_FRAGMENT_ORDER.format(req_id=esc(order.fragment_req_id)))
    if order.tx_hash:
        lines.append(texts.ADMIN_CARD_HASH.format(hash=esc(order.tx_hash)))
    if order.error:
        lines.append(texts.ADMIN_CARD_ERROR.format(error=esc(order.error)))
    if events:
        lines.append(texts.ADMIN_CARD_HISTORY)
        for e in events[-8:]:
            change = ""
            if e["to_status"]:
                frm = Status(e["from_status"]).label if e["from_status"] else texts.NO_VALUE
                change = f"{frm} → {Status(e['to_status']).label}"
            lines.append(f"{ts(e['at'])} {esc(e['actor'])}: {change} {esc(e['note'] or '')}".rstrip())
    return "\n".join(lines)


def order_button(order: Order) -> str:
    if order.product == Product.STARS:
        what = texts.BTN_ORDER_WHAT_STARS.format(quantity=order.quantity)
    else:
        what = texts.BTN_ORDER_WHAT_PREMIUM.format(months=order.quantity)
    return texts.BTN_ORDER.format(id=order.id, icon=order.status.label.split()[0], what=what,
                                  recipient=order.recipient, usd=order.price_usd)
