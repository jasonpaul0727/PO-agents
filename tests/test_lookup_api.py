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
    # Globex has no derivation rule and no cross-ref rows, so nothing resolves.
    resp = client_with_seed().get(
        "/api/resolve-item", params={"customer": "Globex", "customer_item_number": "9999"}
    )
    body = resp.json()
    assert body["resolved"] is False


def test_resolve_item_ollies_rule():
    client = client_with_seed()
    # Ollies resolves by rule: last two digits -> our ITEM-0XX, regardless of prefix.
    r1 = client.get(
        "/api/resolve-item",
        params={"customer": "Ollies", "customer_item_number": "75022", "order_quantity": 30},
    ).json()
    assert r1["resolved"] is True
    assert r1["item_number"] == "ITEM-022"
    assert r1["found"] is True

    # Same last two digits -> same item, even with a different prefix.
    r2 = client.get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "88822"}
    ).json()
    assert r2["item_number"] == "ITEM-022"

    # 75023 -> ITEM-023, which is excluded from the item master (digit '3') -> not found.
    r3 = client.get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "75023"}
    ).json()
    assert r3["resolved"] is True
    assert r3["item_number"] == "ITEM-023"
    assert r3["found"] is False


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


def test_resolve_item_alias_customer_name():
    # The PO's legal name resolves to the Ollies rule via alias matching.
    body = client_with_seed().get(
        "/api/resolve-item",
        params={
            "customer": "OLLIE'S BARGAIN OUTLET, INC.",
            "customer_item_number": "75022",
            "order_quantity": 30,
        },
    ).json()
    assert body["resolved"] is True
    assert body["item_number"] == "ITEM-022"
    assert body["found"] is True


def test_resolve_item_rule_double_zero_is_100():
    body = client_with_seed().get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "75100"}
    ).json()
    assert body["item_number"] == "ITEM-100"  # '00' -> 100, not 000


def test_customer_exists_alias():
    repo = Repository(db_path=":memory:", seed_dir=SEED)
    assert repo.customer_exists("OLLIE'S BARGAIN OUTLET, INC.") is True  # alias of Ollies
    assert repo.customer_exists("Totally Unknown LLC") is False


def test_manual_mapping_overrides_rule():
    client = client_with_seed()
    # By default Ollies 75022 resolves to ITEM-022 via the last-2-digits rule.
    pre = client.get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "75022"}
    ).json()
    assert pre["item_number"] == "ITEM-022"

    # Operator manually overrides it.
    client.post(
        "/api/map-item",
        json={"customer": "Ollies", "customer_item_number": "75022", "item_number": "ITEM-050"},
    )

    # The saved table entry now wins over the rule (no second release needed).
    post = client.get(
        "/api/resolve-item", params={"customer": "Ollies", "customer_item_number": "75022"}
    ).json()
    assert post["item_number"] == "ITEM-050"


def test_add_customer_registers_new_customer():
    from backend import app as app_module

    client = client_with_seed()
    assert app_module.repo.customer_exists("Brand New Co") is False
    resp = client.post("/api/add-customer", json={"name": "Brand New Co"})
    assert resp.status_code == 200
    assert resp.json()["added"] is True
    assert app_module.repo.customer_exists("Brand New Co") is True


def test_map_item_is_per_customer():
    client = client_with_seed()
    client.post(
        "/api/map-item",
        json={"customer": "ACME Corp", "customer_item_number": "8001", "item_number": "ITEM-004"},
    )
    # A different customer must NOT inherit ACME's learned mapping.
    # (Use Globex, which has no derivation rule, so only ACME's table row applies.)
    other = client.get(
        "/api/resolve-item", params={"customer": "Globex", "customer_item_number": "8001"}
    ).json()
    assert other["resolved"] is False
