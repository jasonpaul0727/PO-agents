from backend.models import ExtractedPO, Issue


def validate(po: ExtractedPO, repo) -> list[Issue]:
    """Required-field, format, and duplicate-PO checks. Does not check item existence."""
    issues: list[Issue] = []

    if not po.header.customer:
        issues.append(Issue(severity="error", code="MISSING_CUSTOMER",
                            message="Customer is required", field="header.customer"))
    elif not repo.customer_exists(po.header.customer):
        issues.append(Issue(severity="error", code="UNKNOWN_CUSTOMER",
                            message="Customer not found in master", field="header.customer"))
    if not po.header.po_number:
        issues.append(Issue(severity="error", code="MISSING_PO_NUMBER",
                            message="PO number is required", field="header.po_number"))
    elif repo.is_duplicate_po(po.header.po_number):
        issues.append(Issue(severity="error", code="DUP_PO",
                            message=f"PO {po.header.po_number} already submitted",
                            field="header.po_number"))

    for idx, li in enumerate(po.line_items):
        if li.order_quantity is None or li.order_quantity <= 0:
            issues.append(Issue(severity="error", code="INVALID_QUANTITY",
                                message="Order quantity must be > 0",
                                field=f"line_items[{idx}].order_quantity"))
    return issues


def check_commits(po: ExtractedPO) -> list[Issue]:
    """Submit-time check: manual_commit must not exceed warehouse_quantity (no overselling)."""
    issues: list[Issue] = []
    for idx, li in enumerate(po.line_items):
        if li.manual_commit is not None and li.manual_commit > li.warehouse_quantity:
            issues.append(Issue(severity="error", code="COMMIT_EXCEEDS_STOCK",
                                message="Manual commit exceeds warehouse stock",
                                field=f"line_items[{idx}].manual_commit"))
    return issues
