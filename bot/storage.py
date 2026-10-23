"""SQLite storage for orders, their status history and shop settings (stdlib ``sqlite3``)."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from . import texts
from .models import Order, Product, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    buyer_id INTEGER NOT NULL,
    buyer_chat_id INTEGER NOT NULL,
    buyer_username TEXT,
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    fragment_price_ton TEXT NOT NULL,
    fragment_price_usd TEXT NOT NULL,
    markup_percent TEXT NOT NULL,
    usd_rub_rate TEXT NOT NULL,
    price_usd TEXT NOT NULL,
    price_rub TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    payment_provider TEXT,
    payment_id TEXT,
    payment_amount TEXT,
    payment_currency TEXT,
    paid_at REAL,
    fulfillment_started_at REAL,
    completed_at REAL,
    fragment_req_id TEXT,
    tx_hash TEXT,
    error TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS orders_buyer ON orders(buyer_id);
CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    at REAL NOT NULL,
    actor TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- webhook deliveries already processed (providers retry; de-duplicate on their event id)
CREATE TABLE IF NOT EXISTS webhook_events (
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (provider, event_id)
);
-- every invoice ever issued for an order: an old payment link may still be paid
CREATE TABLE IF NOT EXISTS payments (
    provider TEXT NOT NULL,
    payment_id TEXT NOT NULL,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    amount TEXT,
    currency TEXT,
    expires_at REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY (provider, payment_id)
);
"""

_DECIMALS = {"fragment_price_ton", "fragment_price_usd", "markup_percent", "usd_rub_rate",
             "price_usd", "price_rub", "payment_amount"}
_FIELDS = [f.name for f in fields(Order)]
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _to_db(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _DECIMALS:
        return str(value)
    if name in ("product", "status"):
        return value.value
    if name == "extra":
        return json.dumps(value, ensure_ascii=False)
    return value


def _from_row(row: sqlite3.Row) -> Order:
    data = {}
    for name in _FIELDS:
        v = row[name]
        if v is not None and name in _DECIMALS:
            v = Decimal(v)
        elif name == "product":
            v = Product(v)
        elif name == "status":
            v = Status(v)
        elif name == "extra":
            v = json.loads(v or "{}")
        data[name] = v
    return Order(**data)


class Storage:
    def __init__(self, path: "str | Path") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, tuple(params))

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._exec("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # -------------------------------------------------------------- orders
    def create_order(self, **values: Any) -> Order:
        now = time.time()
        values.setdefault("status", Status.AWAITING_PAYMENT)
        values.setdefault("created_at", now)
        values.setdefault("updated_at", now)
        values.setdefault("extra", {})
        for _ in range(10):
            values["code"] = new_code()
            cols = [k for k in values if k in _FIELDS and k != "id"]
            try:
                cur = self._exec(
                    f"INSERT INTO orders({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                    [_to_db(c, values[c]) for c in cols],
                )
            except sqlite3.IntegrityError as exc:
                if "code" in str(exc):
                    continue  # random code collision, try another one
                raise
            order = self.get(cur.lastrowid)
            self.add_event(order.id, "system", None, order.status, texts.REASON_CREATED)
            return order
        raise RuntimeError("could not generate a unique order code")

    def get(self, order_id: int) -> Order | None:
        row = self._exec("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return _from_row(row) if row else None

    def get_by_code(self, code: str) -> Order | None:
        row = self._exec("SELECT * FROM orders WHERE code = ?", (code.upper(),)).fetchone()
        return _from_row(row) if row else None

    def add_payment(self, order_id: int, provider: str, payment_id: str, amount: Any, currency: str | None,
                    expires_at: float | None) -> None:
        self._exec("INSERT OR IGNORE INTO payments(provider, payment_id, order_id, amount, currency, expires_at, "
                   "created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                   (provider, payment_id, order_id, str(amount) if amount is not None else None, currency,
                    expires_at, time.time()))

    def webhook_seen(self, provider: str, event_id: str) -> bool:
        return self._exec("SELECT 1 FROM webhook_events WHERE provider = ? AND event_id = ?",
                          (provider, event_id)).fetchone() is not None

    def mark_webhook(self, provider: str, event_id: str) -> None:
        self._exec("INSERT OR IGNORE INTO webhook_events(provider, event_id, received_at) VALUES(?, ?, ?)",
                   (provider, event_id, time.time()))

    def get_by_payment(self, provider: str, payment_id: str) -> Order | None:
        """The order an invoice belongs to (current or an earlier one of the same order)."""
        row = self._exec("SELECT order_id FROM payments WHERE provider = ? AND payment_id = ?",
                         (provider, payment_id)).fetchone()
        if row:
            return self.get(row[0])
        row = self._exec("SELECT * FROM orders WHERE payment_provider = ? AND payment_id = ?",
                         (provider, payment_id)).fetchone()
        return _from_row(row) if row else None

    def orders_with_status_since(self, status: Status, updated_after: float) -> list[Order]:
        rows = self._exec("SELECT * FROM orders WHERE status = ? AND updated_at > ? ORDER BY id",
                          (status.value, updated_after)).fetchall()
        return [_from_row(r) for r in rows]

    def list_orders(self, *, status: Status | None = None, buyer_id: int | None = None,
                    limit: int = 10, offset: int = 0) -> list[Order]:
        where, params = self._where(status, buyer_id)
        rows = self._exec(f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                          [*params, limit, offset]).fetchall()
        return [_from_row(r) for r in rows]

    def count_orders(self, *, status: Status | None = None, buyer_id: int | None = None) -> int:
        where, params = self._where(status, buyer_id)
        return self._exec(f"SELECT COUNT(*) FROM orders {where}", params).fetchone()[0]

    def recent_order_times(self, buyer_id: int, statuses: Iterable[Status], since: float) -> list[float]:
        """``created_at`` of the buyer's orders in ``statuses`` created after ``since``, oldest first."""
        values = [s.value for s in statuses]
        rows = self._exec(
            f"SELECT created_at FROM orders WHERE buyer_id = ? AND created_at > ? "
            f"AND status IN ({', '.join('?' * len(values))}) ORDER BY created_at",
            [buyer_id, since, *values],
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _where(status: Status | None, buyer_id: int | None) -> tuple[str, list[Any]]:
        conds, params = [], []
        if status is not None:
            conds.append("status = ?")
            params.append(status.value)
        if buyer_id is not None:
            conds.append("buyer_id = ?")
            params.append(buyer_id)
        return ("WHERE " + " AND ".join(conds)) if conds else "", params

    def update(self, order_id: int, **values: Any) -> Order:
        values["updated_at"] = time.time()
        cols = [k for k in values if k in _FIELDS and k not in ("id", "code")]
        self._exec(f"UPDATE orders SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                   [*(_to_db(c, values[c]) for c in cols), order_id])
        return self.get(order_id)

    def transition(self, order_id: int, to_status: Status, *, from_statuses: Iterable[Status] | None = None,
                   actor: str = "system", note: str | None = None, **values: Any) -> Order | None:
        """Atomically change the status; ``None`` if the order was not in ``from_statuses``."""
        values["status"] = to_status
        values["updated_at"] = time.time()
        cols = [k for k in values if k in _FIELDS and k not in ("id", "code")]
        sql = f"UPDATE orders SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?"
        params = [*(_to_db(c, values[c]) for c in cols), order_id]
        with self._lock:
            before = self._db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
            if before is None:
                return None
            if from_statuses is not None:
                allowed = [s.value for s in from_statuses]
                sql += f" AND status IN ({', '.join('?' * len(allowed))})"
                params += allowed
            if self._db.execute(sql, params).rowcount != 1:
                return None
        self.add_event(order_id, actor, Status(before["status"]), to_status, note)
        return self.get(order_id)

    def claim_fulfillment(self, order_id: int) -> Order | None:
        """Mark a paid order as "being bought on Fragment"; only one caller ever wins."""
        with self._lock:
            n = self._db.execute(
                "UPDATE orders SET fulfillment_started_at = ?, updated_at = ? "
                "WHERE id = ? AND status = ? AND fulfillment_started_at IS NULL",
                (time.time(), time.time(), order_id, Status.PAID.value),
            ).rowcount
        return self.get(order_id) if n == 1 else None

    def orders_with_status(self, status: Status) -> list[Order]:
        rows = self._exec("SELECT * FROM orders WHERE status = ? ORDER BY id", (status.value,)).fetchall()
        return [_from_row(r) for r in rows]

    # -------------------------------------------------------------- events
    def add_event(self, order_id: int, actor: str, from_status: Status | None, to_status: Status | None,
                  note: str | None = None) -> None:
        self._exec("INSERT INTO order_events(order_id, at, actor, from_status, to_status, note) "
                   "VALUES(?, ?, ?, ?, ?, ?)",
                   (order_id, time.time(), actor, from_status.value if from_status else None,
                    to_status.value if to_status else None, note))

    def events(self, order_id: int) -> list[dict]:
        rows = self._exec("SELECT * FROM order_events WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
        return [dict(r) for r in rows]
