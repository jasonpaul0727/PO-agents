import io

import pdfplumber


def extract_text(pdf_bytes: bytes) -> str:
    """Extract and clean text from a PO PDF. Raises ValueError if no text is extractable."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("PDF has no extractable text (scanned/image PDF?)")
    return text
