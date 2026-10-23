"""Checks texts.py after manual edits: braces and {labels} must stay valid."""

from __future__ import annotations

import string

from . import texts

# Labels each text may use (the ones the code fills in).
ALLOWED_FIELDS: dict[str, set[str]] = {
    'ADMIN_ASK_MARKUP': {'value'},
    'ADMIN_ASK_XROCKET_FEE': {'value', 'currency'},
    'ADMIN_XROCKET_FEE_SET': {'value', 'currency'},
    'BTN_ADMIN_XROCKET_FEE': {'value', 'currency'},
    'ADMIN_ASK_STARS_LIMITS': {'min', 'max'},
    'ADMIN_STARS_LIMITS_SET': {'min', 'max'},
    'ASK_QUANTITY': {'min', 'max'},
    'BAD_QUANTITY': {'min', 'max'},
    'BTN_ADMIN_STARS_LIMITS': {'min', 'max'},
    'ERR_STARS_LIMIT': {'min', 'max'},
    'ERR_ORDER_LIMIT': {'limit', 'time'},
    'ERR_METHOD_LOCKED': {'method'},
    'ADMIN_NOTIFY_LATE_PAYMENT': {'number', 'provider', 'payment_id'},
    'ADMIN_NOTIFY_SUSPICIOUS_INVOICE': {'number', 'provider', 'payment_id', 'reason'},
    'REASON_INVOICE_REUSED': {'other'},
    'REASON_INVOICE_NOT_NEW': {'status'},
    'ROLLYPAY_DESCRIPTION': {'number', 'title', 'recipient'},
    'XROCKET_DESCRIPTION': {'number', 'title', 'recipient'},
    'XROCKET_TITLE': {'currency'},
    'ADMIN_NOTIFY_DOUBLE_PAYMENT': {'number', 'provider', 'payment_id'},
    'ADMIN_NOTIFY_REFUND': {'number', 'provider', 'payment_id'},
    'ERR_STARS_LIMITS_RANGE': {'min', 'max'},
    'ADMIN_ASK_RATE': {'value'},
    'ADMIN_BAD_INFO': {'error'},
    'ADMIN_BAD_VALUE': {'error'},
    'ADMIN_CARD_BUYER': {'buyer_id'},
    'ADMIN_CARD_BUYER_USERNAME': {'username'},
    'ADMIN_CARD_DATES': {'updated', 'created'},
    'ADMIN_CARD_ERROR': {'error'},
    'ADMIN_CARD_FRAGMENT': {'usd', 'ton'},
    'ADMIN_CARD_FRAGMENT_ORDER': {'req_id'},
    'ADMIN_CARD_HASH': {'hash'},
    'ADMIN_CARD_PAID': {'paid', 'completed'},
    'ADMIN_CARD_PAYMENT': {'provider', 'payment_id'},
    'ADMIN_CARD_PAYMENT_AMOUNT': {'amount', 'currency'},
    'ADMIN_CARD_PRICING': {'rate', 'rub', 'usd', 'markup'},
    'ADMIN_CARD_TITLE': {'status', 'number'},
    'ADMIN_ERROR': {'error'},
    'ADMIN_FULFILL_CONFIRM': {'title', 'number', 'recipient'},
    'ADMIN_HOME': {'markup', 'rate', 'stars_min', 'stars_max', 'minutes'},
    'ADMIN_INFO_CURRENT': {'text'},
    'ADMIN_MARKUP_SET': {'value'},
    'ADMIN_NOTIFY_ERROR': {'number', 'reason'},
    'ADMIN_NOTIFY_LOW_FUNDS': {'need', 'have', 'reserved', 'currency'},
    'ADMIN_ORDERS_TITLE': {'page'},
    'ADMIN_ORDERS_TITLE_STATUS': {'status', 'page'},
    'ADMIN_RATE_SET': {'value'},
    'ADMIN_STATUS_CHANGED': {'status'},
    'ADMIN_WALLET_ADDRESS': {'version', 'address'},
    'ADMIN_WALLET_BALANCE': {'ton'},
    'ADMIN_WALLET_BALANCE_ERROR': {'error'},
    'ADMIN_WALLET_FRAGMENT_ERROR': {'error'},
    'BTN_ADMIN_ALL_ORDERS': {'count'},
    'BTN_ADMIN_MARKUP': {'value'},
    'BTN_ADMIN_RATE': {'value'},
    'BTN_ADMIN_SET_STATUS': {'status'},
    'BTN_ADMIN_STATUS_FILTER': {'status', 'count'},
    'BTN_ORDER': {'icon', 'id', 'recipient', 'usd', 'what'},
    'BTN_ORDER_WHAT_PREMIUM': {'months'},
    'BTN_ORDER_WHAT_STARS': {'quantity'},
    'BTN_PAYMENT_METHOD': {'title', 'currency_sign', 'amount'},
    'BTN_QUOTE_PREMIUM': {'rub', 'usd', 'months'},
    'BTN_QUOTE_STARS': {'rub', 'usd', 'quantity'},
    'BTN_SELF': {'username'},
    'ERR_ORDER_STATUS': {'status'},
    'MY_ID': {'user_id'},
    'NOTIFY_COMPLETED': {'title', 'number', 'recipient'},
    'NOTIFY_EXPIRED': {'number', 'reason'},
    'NOTIFY_PROBLEM': {'number'},
    'ORDER_CARD_INVOICE': {'amount', 'currency'},
    'ORDER_CARD_ITEM': {'title', 'recipient'},
    'ORDER_CARD_PAY_UNTIL': {'time'},
    'ORDER_CARD_PRICE': {'rub', 'usd'},
    'ORDER_CARD_STATUS': {'status'},
    'ORDER_CARD_TITLE': {'number'},
    'PAYMENT_AMOUNT': {'amount', 'currency'},
    'PAYMENT_METHOD': {'title'},
    'REASON_FRAGMENT': {'error', 'kind'},
    'REASON_INTERNAL': {'error', 'kind'},
    'REASON_INVOICE': {'provider', 'amount', 'payment_id', 'currency'},
    'REASON_NO_FUNDS': {'error'},
    'REASON_PRICE_DRIFT': {'paid', 'now'},
    'REASON_PRICE_DRIFT_USD': {'paid', 'now'},
    'ADMIN_WALLET_USDT': {'usdt'},
    'ADMIN_WALLET_PAY_METHOD': {'method'},
    'REASON_PROVIDER_STATUS': {'status'},
    'REASON_RECIPIENT': {'error'},
    'REASON_SAFETY': {'error'},
    'REASON_TX_TIMEOUT': {'hash'},
    'RECIPIENT_FAILED': {'error'},
    'TITLE_PREMIUM': {'months'},
    'TITLE_STARS': {'quantity'},
}


def check_texts() -> list[str]:
    """Problems found in texts.py, in Russian, for the person who edited it."""
    problems = []
    for name, value in vars(texts).items():
        if not name.isupper() or not isinstance(value, str):
            continue
        try:
            used = {f for _, f, _, _ in string.Formatter().parse(value) if f is not None}
        except ValueError:
            problems.append(f"{name}: непарная фигурная скобка {{ или }} (чтобы вывести скобку, пишите {{{{ или }}}})")
            continue
        unknown = used - ALLOWED_FIELDS.get(name, set())
        if unknown:
            allowed = ", ".join(sorted("{" + f + "}" for f in ALLOWED_FIELDS.get(name, set()))) or "меток нет"
            problems.append(f"{name}: неизвестная метка {', '.join('{' + f + '}' for f in sorted(unknown))} "
                            f"(доступно: {allowed})")
    return problems
