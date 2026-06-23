from backend.agents import draft, extraction, intake, validation
from backend.agents import exception as exception_agent
from backend.models import OrderDraft


def run_pipeline(pdf_bytes: bytes, repo, client) -> tuple[OrderDraft, list[dict]]:
    """Run the five agents in sequence. Returns the draft plus per-step status for the UI."""
    steps: list[dict] = []

    try:
        text = intake.extract_text(pdf_bytes)
    except ValueError:
        text = ""  # no text layer (scanned/image PDF) — fall back to vision
    steps.append({"step": "intake", "ok": True})

    if text:
        po = extraction.extract_po(text, client)
    else:
        po = extraction.extract_po_from_pdf(pdf_bytes, client)
    steps.append({"step": "extraction", "ok": True})

    issues = validation.validate(po, repo)
    steps.append({"step": "validation", "ok": True})

    issues += exception_agent.process_exceptions(po, repo)
    steps.append({"step": "exception", "ok": True})

    order = draft.build_draft(po, issues)
    steps.append({"step": "draft", "ok": True})

    return order, steps
