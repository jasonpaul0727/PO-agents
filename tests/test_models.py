from backend.models import LineItem, POHeader, ExtractedPO, Issue, OrderStatus, OrderDraft


def test_lineitem_minimal_construction_uses_defaults():
    li = LineItem(item_number="ITEM-1001", order_quantity=50)
    assert li.warehouse_quantity == 0
    assert li.inventory_commit == 0
    assert li.committed_quantity == 0
    assert li.difference == 0
    assert li.manual_commit is None
    assert li.unit_price is None


def test_extractedpo_from_extraction_shape():
    po = ExtractedPO(
        header=POHeader(customer="ACME", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    )
    assert po.header.ship_date is None
    assert po.line_items[0].unit_price == 2.0


def test_orderstatus_values():
    assert OrderStatus.NEEDS_REVIEW.value == "needs_review"
    assert OrderStatus.READY_TO_SUBMIT.value == "ready_to_submit"
    assert OrderStatus.RELEASED_TO_WAREHOUSE.value == "released_to_warehouse"


def test_orderdraft_defaults():
    draft = OrderDraft(header=POHeader(), line_items=[])
    assert draft.issues == []
    assert draft.status == OrderStatus.NEEDS_REVIEW
    assert draft.order_total is None
