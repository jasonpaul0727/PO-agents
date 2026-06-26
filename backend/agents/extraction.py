import base64
import os

from backend.models import ExtractedDocument, ExtractedPO, LineItem

SYSTEM_PROMPT = (
    "Extract only what is present in the purchase order. "
    "Do not invent missing fields — set them to null. "
    "Always capture the PO number (labelled PO#, PO No, Purchase Order, etc.). "
    "For each line item fill order_quantity (units ordered) and unit_price (unit cost). "
    "Item numbers printed on a customer's purchase order are the CUSTOMER's own "
    "item/model numbers — put them in customer_item_number. Only set item_number "
    "when you are confident a number is OUR internal SKU; otherwise leave item_number null."
)

MAX_ATTEMPTS = 3  # initial + 2 retries


class ExtractionError(Exception):
    """Raised when the extraction call fails after all retries."""


def _to_extracted_po(doc: ExtractedDocument) -> ExtractedPO:
    """Map the slim extraction schema onto the full ExtractedPO. The extra
    LineItem fields keep their defaults and are populated by later agents."""
    return ExtractedPO(
        header=doc.header,
        line_items=[
            LineItem(
                # On a customer PO the printed number is the customer's, not ours.
                # Leave OUR item_number empty when a customer number is present —
                # the resolution step fills it from the mapping, or the operator
                # does. Never echo the customer's number into our field.
                item_number="" if li.customer_item_number else li.item_number,
                customer_item_number=li.customer_item_number,
                order_quantity=li.order_quantity,
                unit_price=li.unit_price,
            )
            for li in doc.line_items
        ],
    )


def _parse_with_retries(client, content) -> ExtractedPO:
    """Call messages.parse with the slim schema, retrying transient failures."""
    model = os.getenv("PO_MODEL", "claude-opus-4-8")
    last_err: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=ExtractedDocument,
            )
            return _to_extracted_po(response.parsed_output)
        except Exception as e:  # noqa: BLE001 — retry any call failure
            last_err = e
    raise ExtractionError(f"Extraction failed after {MAX_ATTEMPTS} attempts: {last_err}")


def extract_po(text: str, client) -> ExtractedPO:
    """Extract from a text layer (text-based PDFs)."""
    return _parse_with_retries(client, text)


def extract_po_from_pdf(pdf_bytes: bytes, client) -> ExtractedPO:
    """Extract directly from the PDF using Claude's vision/document support.
    Used for scanned/image PDFs that have no extractable text layer."""
    data = base64.standard_b64encode(pdf_bytes).decode("ascii")
    content = [
        {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        },
        {"type": "text", "text": (
            "Extract the purchase order header (including the PO number) and line items. "
            "For each line, if there is a customer/model item number column distinct from "
            "an internal SKU, put it in customer_item_number."
        )},
    ]
    return _parse_with_retries(client, content)
