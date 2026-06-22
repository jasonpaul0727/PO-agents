from backend.agents import draft
from backend.models import ExtractedPO, POHeader, LineItem, Issue, OrderStatus


def _po(li, **header):
    return ExtractedPO(header=POHeader(**header), line_items=[li])


def test_derives_committed_difference_and_amounts():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0,
                  warehouse_quantity=30, inventory_commit=30)
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    out = order.line_items[0]
    assert out.committed_quantity == 30
    assert out.difference == 20                 # 50 - 30
    assert out.line_total == 100.0              # 2.0 * 50 (by order qty)
    assert order.order_total == 100.0
    assert order.status == OrderStatus.READY_TO_SUBMIT


def test_manual_commit_overrides_inventory_commit():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0,
                  warehouse_quantity=30, inventory_commit=30, manual_commit=20)
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    out = order.line_items[0]
    assert out.committed_quantity == 20
    assert out.difference == 30


def test_error_issue_forces_needs_review():
    li = LineItem(item_number="ITEM-9999", order_quantity=10, warehouse_quantity=0)
    issues = [Issue(severity="error", code="UNKNOWN_ITEM", message="Not found")]
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), issues)
    assert order.status == OrderStatus.NEEDS_REVIEW


def test_order_total_none_when_no_prices():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, warehouse_quantity=30,
                  inventory_commit=30)  # no unit_price
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    assert order.line_items[0].line_total is None
    assert order.order_total is None
