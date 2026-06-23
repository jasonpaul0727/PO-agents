import pytest

from backend.agents import extraction
from backend.agents.extraction import ExtractionError
from backend.models import ExtractedDocument, ExtractedLineItem, ExtractedPO, POHeader
from tests.conftest import FakeClient


def test_extract_po_returns_parsed_output():
    doc = ExtractedDocument(
        header=POHeader(customer="ACME Corp", po_number="PO-1001"),
        line_items=[ExtractedLineItem(item_number="ITEM-1002", order_quantity=40, unit_price=5.0)],
    )
    client = FakeClient(doc)
    result = extraction.extract_po("some PO text", client)
    # the slim ExtractedDocument is mapped back to a full ExtractedPO
    assert isinstance(result, ExtractedPO)
    assert result.header.customer == "ACME Corp"
    assert result.line_items[0].item_number == "ITEM-1002"
    assert result.line_items[0].order_quantity == 40
    # the model + slim schema were passed to parse
    call = client.calls[0]
    assert call["output_format"] is ExtractedDocument
    assert "model" in call


def test_extract_po_from_pdf_sends_document_block():
    doc = ExtractedDocument(
        header=POHeader(customer="ACME Corp"),
        line_items=[ExtractedLineItem(item_number="ITEM-1001", order_quantity=5)],
    )
    client = FakeClient(doc)
    result = extraction.extract_po_from_pdf(b"%PDF-1.4 fake bytes", client)
    assert isinstance(result, ExtractedPO)
    assert result.line_items[0].item_number == "ITEM-1001"
    # the PDF was sent as a base64 document block, not text
    content = client.calls[0]["messages"][0]["content"]
    doc_block = next(b for b in content if b["type"] == "document")
    assert doc_block["source"]["type"] == "base64"
    assert doc_block["source"]["media_type"] == "application/pdf"
    assert client.calls[0]["output_format"] is ExtractedDocument


def test_extract_po_retries_then_raises():
    class FlakyClient:
        def __init__(self):
            self.attempts = 0

            class _M:
                def __init__(self, outer):
                    self.outer = outer

                def parse(self, **kwargs):
                    self.outer.attempts += 1
                    raise RuntimeError("api down")

            self.messages = _M(self)

    client = FlakyClient()
    with pytest.raises(ExtractionError):
        extraction.extract_po("text", client)
    assert client.attempts == 3   # initial + 2 retries
