"""Render the recorded sample texts to demo PDFs in samples/. Run: python tests/make_sample_pdfs.py"""
from pathlib import Path

from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)

MAP = {
    "sample_valid.txt": "valid.pdf",
    "sample_missing_customer.txt": "missing_customer.pdf",
    "sample_unknown_item.txt": "unknown_item.pdf",
}


def render(text: str, path: Path) -> None:
    c = canvas.Canvas(str(path))
    y = 800
    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 15
    c.save()


if __name__ == "__main__":
    for src, dst in MAP.items():
        render((FIXTURES / src).read_text(encoding="utf-8"), OUT / dst)
        print(f"wrote {OUT / dst}")
