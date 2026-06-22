from backend.agents import validation
from backend.models import ExtractedPO, POHeader, LineItem


def test_valid_po_has_no_issues(repo, valid_po):
    assert validation.validate(valid_po, repo) == []


def test_missing_customer_is_error(repo):
    po = ExtractedPO(
        header=POHeader(po_number="PO-9"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=1)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "MISSING_CUSTOMER" and i.severity == "error" for i in issues)


def test_unknown_customer_is_error(repo):
    po = ExtractedPO(
        header=POHeader(customer="NoSuchCo", po_number="PO-6"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=1)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "UNKNOWN_CUSTOMER" and i.severity == "error" for i in issues)


def test_duplicate_po_is_error(repo, valid_po):
    repo.record_po("PO-1001")
    issues = validation.validate(valid_po, repo)
    assert any(i.code == "DUP_PO" and i.severity == "error" for i in issues)


def test_nonpositive_quantity_is_error(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-7"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=0)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "INVALID_QUANTITY" for i in issues)


def test_check_commits_flags_overstock():
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-8"),
        line_items=[
            LineItem(item_number="ITEM-1001", order_quantity=50,
                     warehouse_quantity=30, manual_commit=40)
        ],
    )
    issues = validation.check_commits(po)
    assert any(i.code == "COMMIT_EXCEEDS_STOCK" and i.severity == "error" for i in issues)


def test_check_commits_passes_within_stock():
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-8"),
        line_items=[
            LineItem(item_number="ITEM-1001", order_quantity=50,
                     warehouse_quantity=30, manual_commit=25)
        ],
    )
    assert validation.check_commits(po) == []
