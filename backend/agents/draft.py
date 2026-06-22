from backend.models import ExtractedPO, Issue, OrderDraft, OrderStatus


def build_draft(po: ExtractedPO, issues: list[Issue]) -> OrderDraft:
    for li in po.line_items:
        li.committed_quantity = (
            li.manual_commit if li.manual_commit is not None else li.inventory_commit
        )
        li.difference = li.order_quantity - li.committed_quantity
        li.line_total = (
            round(li.unit_price * li.order_quantity, 2)
            if li.unit_price is not None
            else None
        )

    priced = [li.line_total for li in po.line_items if li.line_total is not None]
    order_total = round(sum(priced), 2) if priced else None

    has_error = any(i.severity == "error" for i in issues)
    status = OrderStatus.NEEDS_REVIEW if has_error else OrderStatus.READY_TO_SUBMIT

    return OrderDraft(
        header=po.header,
        line_items=po.line_items,
        order_total=order_total,
        issues=issues,
        status=status,
        human_summary=_summarize(po, issues, status),
    )


def _summarize(po: ExtractedPO, issues: list[Issue], status: OrderStatus) -> str:
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    cuts = sum(1 for li in po.line_items if li.difference > 0)
    return (
        f"{len(po.line_items)} line item(s); {cuts} with shortfall; "
        f"{errors} error(s), {warnings} warning(s). Status: {status.value}."
    )
