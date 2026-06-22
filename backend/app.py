import os

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from backend import pipeline
from backend.agents import draft, validation
from backend.agents import exception as exception_agent
from backend.agents.extraction import ExtractionError
from backend.models import ExtractedPO, OrderDraft, OrderStatus
from backend.repository import Repository

load_dotenv()

app = FastAPI(title="PO Intake Agent")
repo = Repository(db_path=os.getenv("PO_DB", "po.db"), seed_dir=os.getenv("PO_SEED", "backend/seed"))


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
