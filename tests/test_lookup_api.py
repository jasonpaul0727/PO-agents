"""Tests for the deterministic, no-LLM lookup endpoints:
  - GET /api/check-item   (our item number -> found / stock / auto-commit)
  - GET /api/resolve-item (customer's item number -> our item number, then check)

These mirror exception.process_exceptions, so a regression here would silently
break the live item-number editing UX. Seed data: items ITEM-001..100 excluding
any number containing the digit '3'; customer cross-ref Ollies 7001..7030 -> 001..030.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import app
from backend.repository import Repository

SEED = str(Path(__file__).resolve().parents[1] / "backend" / "seed")


def client_with_seed() -> TestClient:
    """Point the app at a fresh in-memory repo loaded from the real seed."""
    app_module.repo = Repository(db_path=":memory:", seed_dir=SEED)
    return TestClient(app)


# --------------------------- /api/check-item ---------------------------

def test_check_item_found():
    resp = client_with_seed().get(
        "/api/check-item", params={"item_number": "ITEM-004", "order_quantity": 70}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["item_number"] == "ITEM-004"
    assert body["warehouse_quantity"] == 100
    assert body["inventory_commit"] == 70  # min(70, 100)


def test_check_item_not_found():
    # ITEM-003 contains '3' -> deliberately not seeded -> not found.
    resp = client_with_seed().get(
        "/api/check-item", params={"item_number": "ITEM-003", "order_quantity": 50}
    )
    body = resp.json()
    assert body["found"] is False
    assert body["warehouse_quantity"] == 0
    assert body["inventory_commit"] == 0


def test_check_item_commit_capped_at_stock():
    resp = client_with_seed().get(
        "/api/check-item", params={"item_number": "ITEM-004", "order_quantity": 150}
    )
    body = resp.json()
    assert body["found"] is True
    assert body["inventory_commit"] == 100  # capped at warehouse_quantity, not 150


# --------------------------- /api/resolve-item ---------------------------

def test_resolve_item_found():
    resp = client_with_seed().get(
        "/api/resolve-item",
        params={"customer": "Ollies", "customer_item_number": "7005", "order_quantity": 70},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"] is True
    assert body["item_number"] == "ITEM-005"
    assert body["found"] is True
    assert body["warehouse_quantity"] == 100
    assert body["inventory_commit"] == 70


def test_resolve_item_resolved_but_item_not_found():
    # 7003 resolves to ITEM-003, which contains '3' and is not in the item master.
    resp = client_with_seed().get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "7003"}
    )
    body = resp.json()
    assert body["resolved"] is True
    assert body["item_number"] == "ITEM-003"
    assert body["found"] is False
    assert body["inventory_commit"] == 0


def test_resolve_item_cross_customer_isolation():
    # 7005 is Ollies' number; a different customer must NOT resolve it.
    resp = client_with_seed().get(
        "/api/resolve-item", params={"customer": "ACME Corp", "customer_item_number": "7005"}
    )
    body = resp.json()
    assert body["resolved"] is False
    assert "item_number" not in body


def test_resolve_item_unmatched():
    # 9999 is not in Ollies' cross-reference at all.
    resp = client_with_seed().get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "9999"}
    )
    body = resp.json()
    assert body["resolved"] is False


def test_resolve_item_commit_capped_at_stock():
    resp = client_with_seed().get(
        "/api/resolve-item",
        params={"customer": "Ollies", "customer_item_number": "7005", "order_quantity": 150},
    )
    body = resp.json()
    assert body["resolved"] is True
    assert body["inventory_commit"] == 100  # capped at stock


# --------------------------- /api/map-item (learn-as-you-go) ---------------------------

def test_map_item_learns_new_mapping():
    client = client_with_seed()
    # A customer with no cross-ref: their number does not resolve yet.
    pre = client.get(
        "/api/resolve-item", params={"customer": "ACME Corp", "customer_item_number": "8001"}
    ).json()
    assert pre["resolved"] is False

    # Operator maps it once.
    save = client.post(
        "/api/map-item",
        json={"customer": "ACME Corp", "customer_item_number": "8001", "item_number": "ITEM-004"},
    )
    assert save.status_code == 200
    assert save.json()["saved"] is True

    # Now the same customer number resolves automatically.
    post = client.get(
        "/api/resolve-item",
        params={"customer": "ACME Corp", "customer_item_number": "8001", "order_quantity": 70},
    ).json()
    assert post["resolved"] is True
    assert post["item_number"] == "ITEM-004"
    assert post["found"] is True
    assert post["inventory_commit"] == 70


def test_map_item_is_per_customer():
    client = client_with_seed()
    client.post(
        "/api/map-item",
        json={"customer": "ACME Corp", "customer_item_number": "8001", "item_number": "ITEM-004"},
    )
    # A different customer must NOT inherit ACME's learned mapping.
    other = client.get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "8001"}
    ).json()
    assert other["resolved"] is False
