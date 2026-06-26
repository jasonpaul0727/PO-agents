from backend.models import ExtractedPO, Issue


def process_exceptions(po: ExtractedPO, repo) -> list[Issue]:
    """Check item existence against item master; backfill stock and auto-commit. Mutates line_items."""
    issues: list[Issue] = []
    for idx, li in enumerate(po.line_items):
        # A number printed on a customer PO that is NOT one of ours is the
        # customer's own number. Treat it as such so it stays in the customer
        # column and our column is filled only by a mapping.
        if not li.customer_item_number and li.item_number and repo.find_item(li.item_number) is None:
            li.customer_item_number = li.item_number
            li.item_number = ""

        # Resolve the customer's number to our item number (per-customer
        # rule/table). Leave ours empty when it can't be mapped yet.
        if li.customer_item_number:
            li.item_number = repo.resolve_customer_item(
                po.header.customer or "", li.customer_item_number
            ) or ""

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
