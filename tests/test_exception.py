from backend.agents import exception
from backend.models import ExtractedPO, POHeader, LineItem


def test_known_item_backfills_stock_and_commit(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50)],  # stock 30
    )
    issues = exception.process_exceptions(po, repo)
    li = po.line_items[0]
    assert li.warehouse_quantity == 30
    assert li.inventory_commit == 30           # min(50, 30)
    assert issues == []


def test_order_within_stock_commits_full(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=40)],  # stock 100
    )
    exception.process_exceptions(po, repo)
    assert po.line_items[0].inventory_commit == 40


def test_unknown_item_errors_and_zeroes(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-9999", order_quantity=10)],
    )
    issues = exception.process_exceptions(po, repo)
    assert any(i.code == "UNKNOWN_ITEM" and i.severity == "error"
               and i.message == "Not found" for i in issues)
    li = po.line_items[0]
    assert li.warehouse_quantity == 0
    assert li.inventory_commit == 0
