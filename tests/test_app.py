import io

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from backend import app as app_module
from backend.app import app, get_client
from backend.repository import Repository
from backend.models import ExtractedPO, POHeader, LineItem
from tests.conftest import FakeClient
from pathlib import Path

SEED = str(Path(__file__).resolve().parents[1] / "backend" / "seed")


def _pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 800, text)
    c.save()
    return buf.getvalue()


def setup_overrides(extracted: ExtractedPO):
    test_repo = Repository(db_path=":memory:", seed_dir=SEED)
    app_module.repo = test_repo
    app.dependency_overrides[get_client] = lambda: FakeClient(extracted)
    return test_repo


def teardown_module(module):
    app.dependency_overrides.clear()


def test_process_returns_order_and_steps():
    setup_overrides(ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-3001"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    ))
    client = TestClient(app)
    resp = client.post("/api/process", files={"file": ("po.pdf", _pdf("PO"), "application/pdf")})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["steps"]) == 5
    assert body["order"]["line_items"][0]["difference"] == 20


def test_submit_overstock_blocks_release():
    setup_overrides(ExtractedPO(header=POHeader(), line_items=[]))
    client = TestClient(app)
    draft = {
        "header": {"customer": "ACME Corp", "po_number": "PO-3002"},
        "line_items": [{
            "item_number": "ITEM-1001", "order_quantity": 50, "manual_commit": 40
        }],
        "status": "ready_to_submit",
    }
    resp = client.post("/api/submit", json=draft)
    assert resp.status_code == 200
    body = resp.json()
    assert body["released"] is False
    assert any(i["code"] == "COMMIT_EXCEEDS_STOCK" for i in body["order"]["issues"])


def test_submit_clean_releases_and_records_po():
    repo = setup_overrides(ExtractedPO(header=POHeader(), line_items=[]))
    client = TestClient(app)
    draft = {
        "header": {"customer": "ACME Corp", "po_number": "PO-3003"},
        "line_items": [{"item_number": "ITEM-1002", "order_quantity": 40, "unit_price": 5.0}],
        "status": "ready_to_submit",
    }
    resp = client.post("/api/submit", json=draft)
    body = resp.json()
    assert body["released"] is True
    assert body["order"]["status"] == "released_to_warehouse"
    assert repo.is_duplicate_po("PO-3003") is True
