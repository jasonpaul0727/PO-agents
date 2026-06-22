import io

import pytest
from reportlab.pdfgen import canvas

from backend.agents import intake


def _pdf_with_text(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 15
    c.save()
    return buf.getvalue()


def test_extract_text_reads_pdf():
    pdf = _pdf_with_text("Customer: ACME Corp\nPO Number: PO-1001")
    text = intake.extract_text(pdf)
    assert "ACME Corp" in text
    assert "PO-1001" in text


def test_extract_text_raises_on_empty_pdf():
    blank = _pdf_with_text("")
    with pytest.raises(ValueError):
        intake.extract_text(blank)
