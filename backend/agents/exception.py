from backend.models import ExtractedPO, Issue


def process_exceptions(po: ExtractedPO, repo) -> list[Issue]:
    """Check item existence against item master; backfill stock and auto-commit. Mutates line_items."""
    issues: list[Issue] = []
    for idx, li in enumerate(po.line_items):
        item = repo.find_item(li.item_number)
        if item is None:
            issues.append(Issue(severity="error", code="UNKNOWN_ITEM",
                                message="Not found",
                                field=f"line_items[{idx}].item_number"))
            li.warehouse_quantity = 0
            li.inventory_commit = 0
        else:
            li.warehouse_quantity = item.warehouse_quantity
            li.inventory_commit = min(li.order_quantity, item.warehouse_quantity)
    return issues
