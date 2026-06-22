from backend import pipeline
from backend.models import ExtractedPO, POHeader, LineItem, OrderStatus
from tests.conftest import FakeClient

DUMMY_PDF_TEXT_BYTES = None  # pipeline reads PDF; we feed a real PDF below


def _pdf(text):
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 800, text)
    c.save()
    return buf.getvalue()


def test_scenario_valid_po_ready(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1001", ship_to="123 Main St"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=40, unit_price=5.0)],
    )
    order, _ = pipeline.run_pipeline(_pdf("PO"), repo, FakeClient(extracted))
    assert order.status == OrderStatus.READY_TO_SUBMIT
    assert order.issues == []
    assert order.order_total == 200.0


def test_scenario_missing_customer_needs_review(repo):
    extracted = ExtractedPO(
        header=POHeader(customer=None, po_number="PO-1002"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    )
    order, _ = pipeline.run_pipeline(_pdf("PO"), repo, FakeClient(extracted))
    assert order.status == OrderStatus.NEEDS_REVIEW
    assert any(i.code == "MISSING_CUSTOMER" for i in order.issues)


def test_scenario_unknown_item_needs_review(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="Globex", po_number="PO-1003"),
        line_items=[LineItem(item_number="ITEM-9999", order_quantity=10, unit_price=9.0)],
    )
    order, _ = pipeline.run_pipeline(_pdf("PO"), repo, FakeClient(extracted))
    assert order.status == OrderStatus.NEEDS_REVIEW
    assert any(i.code == "UNKNOWN_ITEM" and i.message == "Not found" for i in order.issues)
