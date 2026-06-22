import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel


class Item(BaseModel):
    item_number: str
    warehouse_quantity: int


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
        self.conn.commit()

    def customer_exists(self, name: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM customers WHERE name = ?", (name,))
        return cur.fetchone() is not None

    def find_item(self, item_number: str) -> Item | None:
        cur = self.conn.execute(
            "SELECT item_number, warehouse_quantity FROM items WHERE item_number = ?",
            (item_number,),
        )
        row = cur.fetchone()
        return Item(item_number=row[0], warehouse_quantity=row[1]) if row else None

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
