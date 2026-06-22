import io

from reportlab.pdfgen import canvas

from backend import pipeline
from backend.models import ExtractedPO, POHeader, LineItem, OrderStatus
from tests.conftest import FakeClient


def _pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 15
    c.save()
    return buf.getvalue()


def test_pipeline_produces_ready_draft(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-2001"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    )
    client = FakeClient(extracted)
    order, steps = pipeline.run_pipeline(_pdf("PURCHASE ORDER\n..."), repo, client)

    assert [s["step"] for s in steps] == [
        "intake", "extraction", "validation", "exception", "draft"
    ]
    assert order.line_items[0].warehouse_quantity == 30
    assert order.line_items[0].difference == 20
    assert order.status == OrderStatus.READY_TO_SUBMIT


def test_pipeline_unknown_item_needs_review(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="Globex", po_number="PO-2002"),
        line_items=[LineItem(item_number="ITEM-9999", order_quantity=10, unit_price=9.0)],
    )
    client = FakeClient(extracted)
    order, _ = pipeline.run_pipeline(_pdf("PO"), repo, client)
    assert order.status == OrderStatus.NEEDS_REVIEW
    assert any(i.code == "UNKNOWN_ITEM" for i in order.issues)
