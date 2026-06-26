import os

from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import pipeline
from backend.agents import draft, validation
from backend.agents import exception as exception_agent
from backend.agents.extraction import ExtractionError
from backend.models import CustomerName, ExtractedPO, ItemMapping, OrderDraft, OrderStatus
from backend.repository import Repository

load_dotenv()

app = FastAPI(title="PO Intake Agent")
repo = Repository(db_path=os.getenv("PO_DB", "po.db"), seed_dir=os.getenv("PO_SEED", "backend/seed"))

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.middleware("http")
async def no_store_static(request, call_next):
    """Dev convenience: never cache frontend assets, so a plain refresh always
    loads the latest app.js/styles.css (no more stale-cache confusion)."""
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "index.html"))


def get_client():
    return anthropic.Anthropic()


@app.post("/api/process")
async def process(file: UploadFile = File(...), client=Depends(get_client)):
    pdf_bytes = await file.read()
    try:
        order, steps = pipeline.run_pipeline(pdf_bytes, repo, client)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ExtractionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"order": order.model_dump(), "steps": steps}


@app.get("/api/check-item")
def check_item(item_number: str, order_quantity: int | None = None):
    """Lightweight item-master lookup for live found/not-found + stock/commit feedback.

    Mirrors exception.process_exceptions so the row updates the same way a full
    re-validation would. No LLM, no cost.
    """
    item = repo.find_item(item_number.strip())
    if item is None:
        return {"found": False, "item_number": item_number,
                "warehouse_quantity": 0, "inventory_commit": 0}
    commit = None
    if order_quantity is not None:
        commit = min(order_quantity, item.warehouse_quantity)
    return {
        "found": True,
        "item_number": item.item_number,
        "warehouse_quantity": item.warehouse_quantity,
        "inventory_commit": commit,
    }


@app.get("/api/resolve-item")
def resolve_item(customer: str, customer_item_number: str, order_quantity: int | None = None):
    """Map a customer's own item number to our internal item number, then check stock.

    Used when a PO lists the customer's item numbers instead of ours. No LLM, no cost.
    """
    our = repo.resolve_customer_item(customer.strip(), customer_item_number.strip())
    if our is None:
        return {"resolved": False, "customer_item_number": customer_item_number}

    item = repo.find_item(our)
    found = item is not None
    commit = None
    if found and order_quantity is not None:
        commit = min(order_quantity, item.warehouse_quantity)
    return {
        "resolved": True,
        "customer_item_number": customer_item_number,
        "item_number": our,
        "found": found,
        "warehouse_quantity": item.warehouse_quantity if found else 0,
        "inventory_commit": commit if found else 0,
    }


@app.post("/api/add-customer")
def add_customer(payload: CustomerName):
    """Register a previously-unknown customer so it no longer blocks release."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Customer name is required")
    repo.add_customer(name)
    return {"added": True, "name": name}


@app.post("/api/map-item")
def map_item(mapping: ItemMapping):
    """Learn-as-you-go: persist an operator-supplied customer->our item mapping."""
    repo.add_customer_item_mapping(
        mapping.customer.strip(),
        mapping.customer_item_number.strip(),
        mapping.item_number.strip(),
    )
    return {"saved": True}


@app.post("/api/submit")
async def submit(order: OrderDraft):
    po = ExtractedPO(header=order.header, line_items=order.line_items)

    issues = validation.validate(po, repo)
    issues += exception_agent.process_exceptions(po, repo)   # re-query stock, backfill
    issues += validation.check_commits(po)                   # overstock guard

    rebuilt = draft.build_draft(po, issues)
    rebuilt.order_note = order.order_note

    if any(i.severity == "error" for i in rebuilt.issues):
        rebuilt.status = OrderStatus.NEEDS_REVIEW
        return {"order": rebuilt.model_dump(), "released": False}

    repo.record_po(rebuilt.header.po_number)
    rebuilt.status = OrderStatus.RELEASED_TO_WAREHOUSE
    return {"order": rebuilt.model_dump(), "released": True}
