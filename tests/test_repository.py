from backend.repository import Repository, Item


def make_repo(tmp_path):
    (tmp_path / "customers.json").write_text('[{"name": "ACME"}]')
    (tmp_path / "items.json").write_text(
        '[{"item_number": "ITEM-1001", "warehouse_quantity": 30}]'
    )
    return Repository(db_path=":memory:", seed_dir=str(tmp_path))


def test_seed_loads_customers_and_items(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.customer_exists("ACME") is True
    assert repo.customer_exists("NOPE") is False


def test_find_item_returns_item_or_none(tmp_path):
    repo = make_repo(tmp_path)
    item = repo.find_item("ITEM-1001")
    assert isinstance(item, Item)
    assert item.warehouse_quantity == 30
    assert repo.find_item("ITEM-9999") is None


def test_duplicate_po_registry(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.is_duplicate_po("PO-1") is False
    repo.record_po("PO-1")
    assert repo.is_duplicate_po("PO-1") is True
