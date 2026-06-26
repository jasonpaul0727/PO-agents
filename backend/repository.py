import json
import re
import sqlite3
from pathlib import Path

from pydantic import BaseModel


def _normalize_name(s: str | None) -> str:
    """Lowercase + strip all non-alphanumerics, so 'OLLIE'S BARGAIN OUTLET, INC.'
    and 'Ollies' both reduce to a comparable form."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class Item(BaseModel):
    item_number: str
    warehouse_quantity: int


def _ollies_rule(customer_item_number: str) -> str | None:
    """Ollies orders use their own numbers whose LAST TWO DIGITS equal our item's
    two-digit suffix, e.g. 75023 -> ITEM-023. Items sharing the same last two
    digits are treated as the same item."""
    tail = customer_item_number[-2:]
    if len(tail) == 2 and tail.isdigit():
        n = int(tail) or 100  # '00' -> 100
        return f"ITEM-{n:03d}"
    return None


# Per-customer derivation rules. A customer here resolves by rule instead of by
# the customer_items lookup table. Everyone else uses the table (+ learn-as-you-go).
CUSTOMER_RULES = {
    "Ollies": _ollies_rule,
}


def _canonical_customer(name: str) -> str:
    """Map a free-form customer name to a canonical key when it matches a known
    rule customer, e.g. 'OLLIE'S BARGAIN OUTLET, INC.' -> 'Ollies'."""
    norm = _normalize_name(name)
    for key in CUSTOMER_RULES:
        if _normalize_name(key) in norm:
            return key
    return name


class Repository:
    """Master data + submitted-PO registry. Swap this class for a real ERP/WMS adapter later."""

    def __init__(self, db_path: str = ":memory:", seed_dir: str | None = None):
        # check_same_thread=False: FastAPI serves requests from a threadpool, so the
        # connection (created at import time) is reused across threads. Safe here — access
        # is serialized and writes are tiny single-row registry inserts.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()
        if seed_dir:
            self._load_seed(seed_dir)

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS items (
                item_number TEXT PRIMARY KEY,
                warehouse_quantity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submitted_pos (po_number TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS customer_items (
                customer TEXT NOT NULL,
                customer_item_number TEXT NOT NULL,
                item_number TEXT NOT NULL,
                PRIMARY KEY (customer, customer_item_number)
            );
            """
        )
        self.conn.commit()

    def _load_seed(self, seed_dir: str) -> None:
        seed = Path(seed_dir)
        customers = json.loads((seed / "customers.json").read_text(encoding="utf-8"))
        items = json.loads((seed / "items.json").read_text(encoding="utf-8"))
        self.conn.executemany(
            "INSERT OR REPLACE INTO customers(name) VALUES (?)",
            [(c["name"],) for c in customers],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO items(item_number, warehouse_quantity) VALUES (?, ?)",
            [(i["item_number"], i["warehouse_quantity"]) for i in items],
        )
        xref_path = seed / "customer_items.json"
        if xref_path.exists():
            xref = json.loads(xref_path.read_text(encoding="utf-8"))
            self.conn.executemany(
                "INSERT OR REPLACE INTO customer_items"
                "(customer, customer_item_number, item_number) VALUES (?, ?, ?)",
                [(x["customer"], x["customer_item_number"], x["item_number"]) for x in xref],
            )
        self.conn.commit()

    def add_customer(self, name: str) -> None:
        """Register a new customer in the master so it stops flagging UNKNOWN_CUSTOMER."""
        self.conn.execute("INSERT OR IGNORE INTO customers(name) VALUES (?)", (name,))
        self.conn.commit()

    def customer_exists(self, name: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM customers WHERE name = ?", (name,))
        if cur.fetchone() is not None:
            return True
        # Alias match: e.g. "OLLIE'S BARGAIN OUTLET, INC." -> known customer "Ollies".
        canonical = _canonical_customer(name)
        if canonical != name:
            cur = self.conn.execute("SELECT 1 FROM customers WHERE name = ?", (canonical,))
            return cur.fetchone() is not None
        return False

    def find_item(self, item_number: str) -> Item | None:
        cur = self.conn.execute(
            "SELECT item_number, warehouse_quantity FROM items WHERE item_number = ?",
            (item_number,),
        )
        row = cur.fetchone()
        return Item(item_number=row[0], warehouse_quantity=row[1]) if row else None

    def resolve_customer_item(self, customer: str, customer_item_number: str) -> str | None:
        """Map a customer's own item number to our internal item number, or None.

        Customers with a derivation rule (e.g. Ollies) resolve by rule; everyone
        else falls back to the customer_items table (incl. learn-as-you-go entries).
        """
        # 1) Explicit table entries win — these are operator overrides and
        #    learn-as-you-go mappings, which must take precedence over any rule.
        cur = self.conn.execute(
            "SELECT item_number FROM customer_items "
            "WHERE customer = ? AND customer_item_number = ?",
            (customer, customer_item_number),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        # 2) Fall back to the per-customer derivation rule (e.g. Ollies last-2-digits).
        rule = CUSTOMER_RULES.get(_canonical_customer(customer))
        if rule:
            derived = rule(customer_item_number)
            if derived:
                return derived
        return None

    def add_customer_item_mapping(
        self, customer: str, customer_item_number: str, item_number: str
    ) -> None:
        """Persist a learned cross-reference so this customer item resolves next time."""
        self.conn.execute(
            "INSERT OR REPLACE INTO customer_items"
            "(customer, customer_item_number, item_number) VALUES (?, ?, ?)",
            (customer, customer_item_number, item_number),
        )
        self.conn.commit()

    def is_duplicate_po(self, po_number: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM submitted_pos WHERE po_number = ?", (po_number,)
        )
        return cur.fetchone() is not None

    def record_po(self, po_number: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO submitted_pos(po_number) VALUES (?)", (po_number,)
        )
        self.conn.commit()
