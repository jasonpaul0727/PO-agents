"""Compose release-request and follow-up email bodies."""
from __future__ import annotations

from backend.sample_request.parser import ParsedRequest


def _format_item_line(item: dict) -> str:
    item_no = item.get("item_number")
    name = item["name"]
    qty = item["qty"]
    unit = item.get("qty_unit") or "each"
    if item_no:
        return f"- Item #{item_no} | {name} | Qty: {qty} {unit}"
    return f"- {name} | Qty: {qty} {unit}"


def build_release_email(
    parsed: ParsedRequest,
    original_subject: str,
    original_sender: str,
) -> tuple[str, str]:
    subject = f"Release Request: {original_subject} - {parsed.recipient}"

    item_lines = "\n".join(_format_item_line(i.model_dump()) for i in parsed.items)
    body = (
        "Hi Warehouse,\n\n"
        "Please release the following sample shipment:\n\n"
        f"Recipient: {parsed.recipient}\n"
        f"Ship-To Address: {parsed.address}\n\n"
        "Items:\n"
        f"{item_lines}\n\n"
        "Please reply to this thread with the UPS tracking number "
        "(format: 1Z…) once shipped.\n\n"
        "Thanks,\n"
        f"PO Intake Agent (on behalf of {original_sender})\n"
    )
    return subject, body


_FOLLOWUP_TEMPLATES = (
    # n=1: gentle nudge
    "Hi Warehouse,\n\n"
    "Just following up on the release request for {recipient} (sent {released_at}).\n"
    "Could you confirm whether this has shipped? When it has, please reply\n"
    "with the UPS tracking number (1Z…).\n\n"
    "Items requested:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",

    # n=2: firmer ping
    "Hi Warehouse,\n\n"
    "Checking in again on the release request for {recipient} (sent {released_at}).\n"
    "We haven't seen a UPS tracking number come back yet — could you let me\n"
    "know the current status?\n\n"
    "Items:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",

    # n>=3: escalation
    "Hi Warehouse,\n\n"
    "This is a final automated follow-up on the sample release request for\n"
    "{recipient} (sent {released_at}). The request has been outstanding for\n"
    "several cycles without a shipment confirmation.\n\n"
    "Please respond with either (a) the UPS tracking number, or (b) why the\n"
    "shipment is blocked.\n\n"
    "Items:\n{items}\n\n"
    "Thanks,\n"
    "PO Intake Agent\n",
)


def build_followup_email(req: dict, n_th: int) -> str:
    idx = min(max(n_th, 1), len(_FOLLOWUP_TEMPLATES)) - 1
    template = _FOLLOWUP_TEMPLATES[idx]
    parsed = req["parsed"]
    items_block = "\n".join(_format_item_line(i) for i in parsed.get("items", []))
    return template.format(
        recipient=parsed.get("recipient", "unknown"),
        released_at=req.get("released_at", "earlier"),
        items=items_block,
    )
