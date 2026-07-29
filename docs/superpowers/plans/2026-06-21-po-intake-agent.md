# PO Intake Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a code-orchestrated 5-agent pipeline that turns a Purchase Order PDF into a validated, human-reviewable, editable order draft ready for warehouse release.

**Architecture:** A deterministic sequential pipeline (Intake → Extraction → Validation → Exception → Draft). Only Extraction calls Claude (`messages.parse` with a Pydantic schema); the other four are pure Python. A FastAPI backend exposes `POST /api/process` (PDF → draft) and `POST /api/submit` (edited draft → re-validate/recompute → release). A Repository layer (SQLite + seed JSON) backs master data and duplicate-PO detection behind a replaceable interface. A single-page three-column frontend renders the draft for editing.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pydantic v2, pdfplumber, anthropic SDK, pytest + httpx. Frontend: vanilla HTML/CSS/JS.

**Working root:** all paths below are relative to the `po-agents/` repo root (the parent of `docs/`).

**Spec:** `docs/superpowers/specs/2026-06-19-po-intake-agent-design.md` — read it before starting.

---

## File Structure

```
po-agents/
  backend/
    __init__.py
    app.py                  # FastAPI app + 2 routes
    pipeline.py             # sequential orchestration of the 5 agents
    models.py               # Pydantic models (single source of truth for types)
    repository.py           # SQLite-backed master data + submitted-PO registry
    agents/
      __init__.py
      intake.py             # PDF bytes -> clean text (pdfplumber)
      extraction.py         # text -> ExtractedPO (Claude messages.parse)
      validation.py         # required/format/dup-PO/commit checks -> issues
      exception.py          # item existence + stock backfill + inventory_commit
      draft.py              # assemble OrderDraft + derived fields + status + summary
    seed/
      customers.json
      items.json
  frontend/
    index.html
    app.js
    styles.css
  tests/
    __init__.py
    conftest.py             # shared fixtures (repo, sample text, fake client)
    test_models.py
    test_repository.py
    test_intake.py
    test_validation.py
    test_exception.py
    test_draft.py
    test_extraction.py
    test_pipeline.py
    test_app.py
    test_e2e_scenarios.py
    fixtures/
      sample_valid.txt      # recorded extraction-input text for the 3 scenarios
      sample_missing_customer.txt
      sample_unknown_item.txt
    make_sample_pdfs.py     # dev helper: renders the 3 sample texts to PDFs
  samples/                  # 3 demo PDFs (generated)
  requirements.txt
  .env.example
  README.md
  pytest.ini
```

**Decomposition notes:**
- `models.py` is the single source of truth for all data shapes. Every other module imports from it. Define it first (Task 1) so later tasks reference stable types.
- Each agent is one focused file with one public function. They share nothing but `models.py` and the `Repository` interface.
- `Repository` hides all SQLite/seed details behind plain methods so agents never touch SQL.

**Type contract (locked here, used by every task):**

| Symbol | Signature |
|---|---|
| `intake.extract_text` | `(pdf_bytes: bytes) -> str` (raises `ValueError` if no text) |
| `extraction.extract_po` | `(text: str, client) -> ExtractedPO` (raises `ExtractionError`) |
| `validation.validate` | `(po: ExtractedPO, repo: Repository) -> list[Issue]` |
| `validation.check_commits` | `(po: ExtractedPO) -> list[Issue]` |
| `exception.process_exceptions` | `(po: ExtractedPO, repo: Repository) -> list[Issue]` (mutates `po.line_items` in place: backfills `warehouse_quantity`, `inventory_commit`) |
| `draft.build_draft` | `(po: ExtractedPO, issues: list[Issue]) -> OrderDraft` (computes `committed_quantity`, `difference`, `line_total`, `order_total`, `status`, `human_summary`) |
| `pipeline.run_pipeline` | `(pdf_bytes: bytes, repo: Repository, client) -> tuple[OrderDraft, list[dict]]` |
| `Repository.customer_exists` | `(name: str) -> bool` |
| `Repository.find_item` | `(item_number: str) -> Item \| None` |
| `Repository.is_duplicate_po` | `(po_number: str) -> bool` |
| `Repository.record_po` | `(po_number: str) -> None` |

---

## Task 0: Project scaffold + tooling

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.env.example`
- Create: `backend/__init__.py`, `backend/agents/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create the directory layout and empty package markers**

```bash
cd po-agents
mkdir -p backend/agents backend/seed frontend tests/fixtures samples
touch backend/__init__.py backend/agents/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
# Runtime
anthropic>=0.69            # needs messages.parse (structured outputs). pip install -U if parse is missing.
fastapi>=0.115
uvicorn[standard]>=0.32
pydantic>=2.9
pdfplumber>=0.11
python-multipart>=0.0.12   # FastAPI file uploads
python-dotenv>=1.0
# Dev / test
pytest>=8.3
httpx>=0.27                # FastAPI TestClient
reportlab>=4.2             # generate demo sample PDFs
```

- [ ] **Step 3: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

- [ ] **Step 4: Write `.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-...
PO_MODEL=claude-opus-4-8
PO_DB=po.db
PO_SEED=backend/seed
```

- [ ] **Step 5: Create a venv and install**

Run:
```bash
python3.12 -m venv .venv
. .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
Expected: installs succeed. If `anthropic` lacks `messages.parse`, run `pip install -U anthropic` and re-freeze.

- [ ] **Step 6: Lock exact versions**

Run: `pip freeze > requirements.lock.txt`
Expected: a `requirements.lock.txt` with pinned versions for reproducibility.

- [ ] **Step 7: Commit**

```bash
git add po-agents/requirements.txt po-agents/requirements.lock.txt po-agents/pytest.ini po-agents/.env.example po-agents/backend po-agents/tests
git commit -m "chore: scaffold po-agents project (py3.12, fastapi, pytest)"
```

---

## Task 1: Data models (`models.py`)

**Files:**
- Create: `backend/models.py`
- Test: `tests/test_models.py`

> All fields that Extraction does **not** fill (`warehouse_quantity`, `inventory_commit`, `committed_quantity`, `difference`) get defaults so an `ExtractedPO` can be constructed from extraction output alone. They are populated later by Exception/Draft.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from backend.models import LineItem, POHeader, ExtractedPO, Issue, OrderStatus, OrderDraft


def test_lineitem_minimal_construction_uses_defaults():
    li = LineItem(item_number="ITEM-1001", order_quantity=50)
    assert li.warehouse_quantity == 0
    assert li.inventory_commit == 0
    assert li.committed_quantity == 0
    assert li.difference == 0
    assert li.manual_commit is None
    assert li.unit_price is None


def test_extractedpo_from_extraction_shape():
    po = ExtractedPO(
        header=POHeader(customer="ACME", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    )
    assert po.header.ship_date is None
    assert po.line_items[0].unit_price == 2.0


def test_orderstatus_values():
    assert OrderStatus.NEEDS_REVIEW.value == "needs_review"
    assert OrderStatus.READY_TO_SUBMIT.value == "ready_to_submit"
    assert OrderStatus.RELEASED_TO_WAREHOUSE.value == "released_to_warehouse"


def test_orderdraft_defaults():
    draft = OrderDraft(header=POHeader(), line_items=[])
    assert draft.issues == []
    assert draft.status == OrderStatus.NEEDS_REVIEW
    assert draft.order_total is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.models'`

- [ ] **Step 3: Write `backend/models.py`**

```python
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class LineItem(BaseModel):
    item_number: str
    order_quantity: int
    unit_price: float | None = None             # extracted
    line_total: float | None = None             # derived = unit_price * order_quantity
    warehouse_quantity: int = 0                 # backfilled by Exception
    inventory_commit: int = 0                   # = min(order_quantity, warehouse_quantity)
    manual_commit: int | None = None            # operator override, 0..warehouse_quantity
    committed_quantity: int = 0                 # = manual_commit if set else inventory_commit
    difference: int = 0                         # = order_quantity - committed_quantity
    cut_reason_type: str | None = None          # set when difference > 0
    on_the_way_quantity: int = 0                # 0..difference (info only)
    on_the_way_tracking_no: str | None = None
    note: str | None = None


class POHeader(BaseModel):
    customer: str | None = None
    po_number: str | None = None
    ship_to: str | None = None
    requested_date: str | None = None
    ship_date: str | None = None
    carrier: str | None = None
    ship_from_warehouse: str | None = None


class ExtractedPO(BaseModel):
    header: POHeader
    line_items: list[LineItem]


class Issue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    field: str | None = None


class OrderStatus(str, Enum):
    NEEDS_REVIEW = "needs_review"
    REVISE = "revise"
    READY_TO_SUBMIT = "ready_to_submit"
    RELEASED_TO_WAREHOUSE = "released_to_warehouse"


class OrderDraft(BaseModel):
    header: POHeader
    line_items: list[LineItem]
    order_total: float | None = None
    issues: list[Issue] = []
    order_note: str | None = None
    status: OrderStatus = OrderStatus.NEEDS_REVIEW
    human_summary: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/models.py po-agents/tests/test_models.py
git commit -m "feat: pydantic data models for PO intake"
```

---

## Task 2: Repository (`repository.py`)

**Files:**
- Create: `backend/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repository.py
from backend.repository import Repository, Item


def make_repo(tmp_path):
    (tmp_path / "customers.json").write_text('[{"name": "ACME"}]')
    (tmp_path / "items.json").write_text(
        '[{"item_number": "ITEM-1001", "warehouse_quantity": 30}]'
    )
    return Repository(db_path=":memory:", seed_dir=str(tmp_path))


def test_seed_loads_customers_and_items(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.customer_exists("ACME") is True
    assert repo.customer_exists("NOPE") is False


def test_find_item_returns_item_or_none(tmp_path):
    repo = make_repo(tmp_path)
    item = repo.find_item("ITEM-1001")
    assert isinstance(item, Item)
    assert item.warehouse_quantity == 30
    assert repo.find_item("ITEM-9999") is None


def test_duplicate_po_registry(tmp_path):
    repo = make_repo(tmp_path)
    assert repo.is_duplicate_po("PO-1") is False
    repo.record_po("PO-1")
    assert repo.is_duplicate_po("PO-1") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.repository'`

- [ ] **Step 3: Write `backend/repository.py`**

```python
import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel


class Item(BaseModel):
    item_number: str
    warehouse_quantity: int


class Repository:
    """Master data + submitted-PO registry. Swap this class for a real ERP/WMS adapter later."""

    def __init__(self, db_path: str = ":memory:", seed_dir: str | None = None):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()
        if seed_dir:
            self._load_seed(seed_dir)

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS items (
                item_number TEXT PRIMARY KEY,
                warehouse_quantity INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS submitted_pos (po_number TEXT PRIMARY KEY);
            """
        )
        self.conn.commit()

    def _load_seed(self, seed_dir: str) -> None:
        seed = Path(seed_dir)
        customers = json.loads((seed / "customers.json").read_text(encoding="utf-8"))
        items = json.loads((seed / "items.json").read_text(encoding="utf-8"))
        self.conn.executemany(
            "INSERT OR REPLACE INTO customers(name) VALUES (?)",
            [(c["name"],) for c in customers],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO items(item_number, warehouse_quantity) VALUES (?, ?)",
            [(i["item_number"], i["warehouse_quantity"]) for i in items],
        )
        self.conn.commit()

    def customer_exists(self, name: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM customers WHERE name = ?", (name,))
        return cur.fetchone() is not None

    def find_item(self, item_number: str) -> Item | None:
        cur = self.conn.execute(
            "SELECT item_number, warehouse_quantity FROM items WHERE item_number = ?",
            (item_number,),
        )
        row = cur.fetchone()
        return Item(item_number=row[0], warehouse_quantity=row[1]) if row else None

    def is_duplicate_po(self, po_number: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM submitted_pos WHERE po_number = ?", (po_number,)
        )
        return cur.fetchone() is not None

    def record_po(self, po_number: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO submitted_pos(po_number) VALUES (?)", (po_number,)
        )
        self.conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repository.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/repository.py po-agents/tests/test_repository.py
git commit -m "feat: SQLite repository for master data + dup-PO registry"
```

---

## Task 3: Seed data + shared test fixtures

**Files:**
- Create: `backend/seed/customers.json`, `backend/seed/items.json`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_valid.txt`, `sample_missing_customer.txt`, `sample_unknown_item.txt`

- [ ] **Step 1: Write seed data `backend/seed/customers.json`**

```json
[
  { "name": "ACME Corp" },
  { "name": "Globex" }
]
```

- [ ] **Step 2: Write seed data `backend/seed/items.json`**

```json
[
  { "item_number": "ITEM-1001", "warehouse_quantity": 30 },
  { "item_number": "ITEM-1002", "warehouse_quantity": 100 }
]
```

- [ ] **Step 3: Write recorded extraction-input texts (the 3 demo scenarios)**

`tests/fixtures/sample_valid.txt`:
```
PURCHASE ORDER
Customer: ACME Corp
PO Number: PO-1001
Ship To: 123 Main St
Requested Date: 2026-07-01

Item        Qty   Unit Price
ITEM-1002   40    5.00
```

`tests/fixtures/sample_missing_customer.txt`:
```
PURCHASE ORDER
PO Number: PO-1002
Ship To: 456 Oak Ave
Requested Date: 2026-07-02

Item        Qty   Unit Price
ITEM-1001   50    2.00
```

`tests/fixtures/sample_unknown_item.txt`:
```
PURCHASE ORDER
Customer: Globex
PO Number: PO-1003
Ship To: 789 Pine Rd

Item        Qty   Unit Price
ITEM-9999   10    9.00
```

- [ ] **Step 4: Write `tests/conftest.py` with shared fixtures**

```python
from pathlib import Path

import pytest

from backend.models import ExtractedPO, POHeader, LineItem
from backend.repository import Repository

SEED = Path(__file__).resolve().parents[1] / "backend" / "seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo() -> Repository:
    return Repository(db_path=":memory:", seed_dir=str(SEED))


@pytest.fixture
def valid_po() -> ExtractedPO:
    return ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1001", ship_to="123 Main St"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=40, unit_price=5.0)],
    )


class FakeParseResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed


class FakeClient:
    """Stand-in for anthropic.Anthropic — returns a preset ExtractedPO from messages.parse."""

    def __init__(self, parsed: ExtractedPO):
        self._parsed = parsed
        self.calls = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def parse(self, **kwargs):
                self._outer.calls.append(kwargs)
                return FakeParseResponse(self._outer._parsed)

        self.messages = _Messages(self)


@pytest.fixture
def fake_client(valid_po):
    return FakeClient(valid_po)
```

- [ ] **Step 5: Verify fixtures import cleanly**

Run: `pytest tests/ -q`
Expected: PASS (existing model + repository tests still pass; no new failures from conftest import).

- [ ] **Step 6: Commit**

```bash
git add po-agents/backend/seed po-agents/tests/conftest.py po-agents/tests/fixtures
git commit -m "feat: seed master data + shared test fixtures and recorded sample texts"
```

---

## Task 4: Intake agent (`agents/intake.py`)

**Files:**
- Create: `backend/agents/intake.py`
- Test: `tests/test_intake.py`

> `document_type` from the spec's agent contract is YAGNI for the PDF-only MVP — omitted until a second input type exists.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intake.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.intake'`

- [ ] **Step 3: Write `backend/agents/intake.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intake.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/agents/intake.py po-agents/tests/test_intake.py
git commit -m "feat: intake agent (PDF -> clean text via pdfplumber)"
```

---

## Task 5: Validation agent (`agents/validation.py`)

**Files:**
- Create: `backend/agents/validation.py`
- Test: `tests/test_validation.py`

> `validate` handles required/format/dup-PO (no master-data item checks — that's Exception's job). `check_commits` is a separate function used at submit time, after Exception has backfilled `warehouse_quantity`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validation.py
from backend.agents import validation
from backend.models import ExtractedPO, POHeader, LineItem


def test_valid_po_has_no_issues(repo, valid_po):
    assert validation.validate(valid_po, repo) == []


def test_missing_customer_is_error(repo):
    po = ExtractedPO(
        header=POHeader(po_number="PO-9"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=1)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "MISSING_CUSTOMER" and i.severity == "error" for i in issues)


def test_unknown_customer_is_error(repo):
    po = ExtractedPO(
        header=POHeader(customer="NoSuchCo", po_number="PO-6"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=1)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "UNKNOWN_CUSTOMER" and i.severity == "error" for i in issues)


def test_duplicate_po_is_error(repo, valid_po):
    repo.record_po("PO-1001")
    issues = validation.validate(valid_po, repo)
    assert any(i.code == "DUP_PO" and i.severity == "error" for i in issues)


def test_nonpositive_quantity_is_error(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-7"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=0)],
    )
    issues = validation.validate(po, repo)
    assert any(i.code == "INVALID_QUANTITY" for i in issues)


def test_check_commits_flags_overstock():
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-8"),
        line_items=[
            LineItem(item_number="ITEM-1001", order_quantity=50,
                     warehouse_quantity=30, manual_commit=40)
        ],
    )
    issues = validation.check_commits(po)
    assert any(i.code == "COMMIT_EXCEEDS_STOCK" and i.severity == "error" for i in issues)


def test_check_commits_passes_within_stock():
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-8"),
        line_items=[
            LineItem(item_number="ITEM-1001", order_quantity=50,
                     warehouse_quantity=30, manual_commit=25)
        ],
    )
    assert validation.check_commits(po) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.validation'`

- [ ] **Step 3: Write `backend/agents/validation.py`**

```python
from backend.models import ExtractedPO, Issue


def validate(po: ExtractedPO, repo) -> list[Issue]:
    """Required-field, format, and duplicate-PO checks. Does not check item existence."""
    issues: list[Issue] = []

    if not po.header.customer:
        issues.append(Issue(severity="error", code="MISSING_CUSTOMER",
                            message="Customer is required", field="header.customer"))
    elif not repo.customer_exists(po.header.customer):
        issues.append(Issue(severity="error", code="UNKNOWN_CUSTOMER",
                            message="Customer not found in master", field="header.customer"))
    if not po.header.po_number:
        issues.append(Issue(severity="error", code="MISSING_PO_NUMBER",
                            message="PO number is required", field="header.po_number"))
    elif repo.is_duplicate_po(po.header.po_number):
        issues.append(Issue(severity="error", code="DUP_PO",
                            message=f"PO {po.header.po_number} already submitted",
                            field="header.po_number"))

    for idx, li in enumerate(po.line_items):
        if li.order_quantity is None or li.order_quantity <= 0:
            issues.append(Issue(severity="error", code="INVALID_QUANTITY",
                                message="Order quantity must be > 0",
                                field=f"line_items[{idx}].order_quantity"))
    return issues


def check_commits(po: ExtractedPO) -> list[Issue]:
    """Submit-time check: manual_commit must not exceed warehouse_quantity (no overselling)."""
    issues: list[Issue] = []
    for idx, li in enumerate(po.line_items):
        if li.manual_commit is not None and li.manual_commit > li.warehouse_quantity:
            issues.append(Issue(severity="error", code="COMMIT_EXCEEDS_STOCK",
                                message="Manual commit exceeds warehouse stock",
                                field=f"line_items[{idx}].manual_commit"))
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validation.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/agents/validation.py po-agents/tests/test_validation.py
git commit -m "feat: validation agent (required/dup-PO/quantity + commit overstock check)"
```

---

## Task 6: Exception agent (`agents/exception.py`)

**Files:**
- Create: `backend/agents/exception.py`
- Test: `tests/test_exception.py`

> Exception owns item existence. Unknown item → `UNKNOWN_ITEM` error (message `Not found`) and zeroes stock/commit. Known item → backfill `warehouse_quantity` and `inventory_commit = min(order_quantity, warehouse_quantity)`. Mutates `po.line_items` in place.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exception.py
from backend.agents import exception
from backend.models import ExtractedPO, POHeader, LineItem


def test_known_item_backfills_stock_and_commit(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50)],  # stock 30
    )
    issues = exception.process_exceptions(po, repo)
    li = po.line_items[0]
    assert li.warehouse_quantity == 30
    assert li.inventory_commit == 30           # min(50, 30)
    assert issues == []


def test_order_within_stock_commits_full(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-1002", order_quantity=40)],  # stock 100
    )
    exception.process_exceptions(po, repo)
    assert po.line_items[0].inventory_commit == 40


def test_unknown_item_errors_and_zeroes(repo):
    po = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-1"),
        line_items=[LineItem(item_number="ITEM-9999", order_quantity=10)],
    )
    issues = exception.process_exceptions(po, repo)
    assert any(i.code == "UNKNOWN_ITEM" and i.severity == "error"
               and i.message == "Not found" for i in issues)
    li = po.line_items[0]
    assert li.warehouse_quantity == 0
    assert li.inventory_commit == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exception.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.exception'`

- [ ] **Step 3: Write `backend/agents/exception.py`**

```python
from backend.models import ExtractedPO, Issue


def process_exceptions(po: ExtractedPO, repo) -> list[Issue]:
    """Check item existence against item master; backfill stock and auto-commit. Mutates line_items."""
    issues: list[Issue] = []
    for idx, li in enumerate(po.line_items):
        item = repo.find_item(li.item_number)
        if item is None:
            issues.append(Issue(severity="error", code="UNKNOWN_ITEM",
                                message="Not found",
                                field=f"line_items[{idx}].item_number"))
            li.warehouse_quantity = 0
            li.inventory_commit = 0
        else:
            li.warehouse_quantity = item.warehouse_quantity
            li.inventory_commit = min(li.order_quantity, item.warehouse_quantity)
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_exception.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/agents/exception.py po-agents/tests/test_exception.py
git commit -m "feat: exception agent (item existence + stock/inventory_commit backfill)"
```

---

## Task 7: Draft agent (`agents/draft.py`)

**Files:**
- Create: `backend/agents/draft.py`
- Test: `tests/test_draft.py`

> Draft computes `committed_quantity = manual_commit ?? inventory_commit`, `difference = order_quantity - committed_quantity`, `line_total = unit_price * order_quantity` (amounts by **order quantity**, not committed), `order_total = sum(line_total)`, status (`NEEDS_REVIEW` if any error else `READY_TO_SUBMIT`), and `human_summary`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft.py
from backend.agents import draft
from backend.models import ExtractedPO, POHeader, LineItem, Issue, OrderStatus


def _po(li, **header):
    return ExtractedPO(header=POHeader(**header), line_items=[li])


def test_derives_committed_difference_and_amounts():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0,
                  warehouse_quantity=30, inventory_commit=30)
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    out = order.line_items[0]
    assert out.committed_quantity == 30
    assert out.difference == 20                 # 50 - 30
    assert out.line_total == 100.0              # 2.0 * 50 (by order qty)
    assert order.order_total == 100.0
    assert order.status == OrderStatus.READY_TO_SUBMIT


def test_manual_commit_overrides_inventory_commit():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0,
                  warehouse_quantity=30, inventory_commit=30, manual_commit=20)
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    out = order.line_items[0]
    assert out.committed_quantity == 20
    assert out.difference == 30


def test_error_issue_forces_needs_review():
    li = LineItem(item_number="ITEM-9999", order_quantity=10, warehouse_quantity=0)
    issues = [Issue(severity="error", code="UNKNOWN_ITEM", message="Not found")]
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), issues)
    assert order.status == OrderStatus.NEEDS_REVIEW


def test_order_total_none_when_no_prices():
    li = LineItem(item_number="ITEM-1001", order_quantity=50, warehouse_quantity=30,
                  inventory_commit=30)  # no unit_price
    order = draft.build_draft(_po(li, customer="ACME Corp", po_number="PO-1"), [])
    assert order.line_items[0].line_total is None
    assert order.order_total is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.draft'`

- [ ] **Step 3: Write `backend/agents/draft.py`**

```python
from backend.models import ExtractedPO, Issue, OrderDraft, OrderStatus


def build_draft(po: ExtractedPO, issues: list[Issue]) -> OrderDraft:
    for li in po.line_items:
        li.committed_quantity = (
            li.manual_commit if li.manual_commit is not None else li.inventory_commit
        )
        li.difference = li.order_quantity - li.committed_quantity
        li.line_total = (
            round(li.unit_price * li.order_quantity, 2)
            if li.unit_price is not None
            else None
        )

    priced = [li.line_total for li in po.line_items if li.line_total is not None]
    order_total = round(sum(priced), 2) if priced else None

    has_error = any(i.severity == "error" for i in issues)
    status = OrderStatus.NEEDS_REVIEW if has_error else OrderStatus.READY_TO_SUBMIT

    return OrderDraft(
        header=po.header,
        line_items=po.line_items,
        order_total=order_total,
        issues=issues,
        status=status,
        human_summary=_summarize(po, issues, status),
    )


def _summarize(po: ExtractedPO, issues: list[Issue], status: OrderStatus) -> str:
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    cuts = sum(1 for li in po.line_items if li.difference > 0)
    return (
        f"{len(po.line_items)} line item(s); {cuts} with shortfall; "
        f"{errors} error(s), {warnings} warning(s). Status: {status.value}."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/agents/draft.py po-agents/tests/test_draft.py
git commit -m "feat: draft agent (commit/difference/amounts/status/summary)"
```

---

## Task 8: Extraction agent (`agents/extraction.py`)

**Files:**
- Create: `backend/agents/extraction.py`
- Test: `tests/test_extraction.py`

> Uses `client.messages.parse(..., output_format=ExtractedPO)` and returns `response.parsed_output`. Tests use the `FakeClient` from conftest — no real API calls. Retries the call up to 2 times, then raises `ExtractionError` (mapped to HTTP 502 by the route).
>
> **Effort note:** the spec wants `effort: "low"`. With `messages.parse`, schema is passed via `output_format`; passing a separate `output_config={"effort": "low"}` may conflict with the SDK-built `output_config.format`. The implementation below passes `output_format` only (default effort). If you confirm your installed SDK accepts both, add `output_config={"effort": "low"}` — it does not change behavior under test (the client is faked).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extraction.py
import pytest

from backend.agents import extraction
from backend.agents.extraction import ExtractionError
from backend.models import ExtractedPO


def test_extract_po_returns_parsed_output(fake_client, valid_po):
    result = extraction.extract_po("some PO text", fake_client)
    assert isinstance(result, ExtractedPO)
    assert result.header.customer == "ACME Corp"
    # the model + schema were passed to parse
    call = fake_client.calls[0]
    assert call["output_format"] is ExtractedPO
    assert "model" in call


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agents.extraction'`

- [ ] **Step 3: Write `backend/agents/extraction.py`**

```python
import os

from backend.models import ExtractedPO

SYSTEM_PROMPT = (
    "Extract only what is present in the purchase order. "
    "Do not invent missing fields — set them to null. "
    "Fill item_number, order_quantity, and unit_price for each line item."
)

MAX_ATTEMPTS = 3  # initial + 2 retries


class ExtractionError(Exception):
    """Raised when the extraction call fails after all retries."""


def extract_po(text: str, client) -> ExtractedPO:
    model = os.getenv("PO_MODEL", "claude-opus-4-8")
    last_err: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                output_format=ExtractedPO,
            )
            return response.parsed_output
        except Exception as e:  # noqa: BLE001 — retry any call failure
            last_err = e
    raise ExtractionError(f"Extraction failed after {MAX_ATTEMPTS} attempts: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/agents/extraction.py po-agents/tests/test_extraction.py
git commit -m "feat: extraction agent (Claude messages.parse + retry)"
```

---

## Task 9: Pipeline (`pipeline.py`)

**Files:**
- Create: `backend/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import io

from reportlab.pdfgen import canvas

from backend import pipeline
from backend.models import ExtractedPO, POHeader, LineItem, OrderStatus
from tests.conftest import FakeClient


def _pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 15
    c.save()
    return buf.getvalue()


def test_pipeline_produces_ready_draft(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="ACME Corp", po_number="PO-2001"),
        line_items=[LineItem(item_number="ITEM-1001", order_quantity=50, unit_price=2.0)],
    )
    client = FakeClient(extracted)
    order, steps = pipeline.run_pipeline(_pdf("PURCHASE ORDER\n..."), repo, client)

    assert [s["step"] for s in steps] == [
        "intake", "extraction", "validation", "exception", "draft"
    ]
    assert order.line_items[0].warehouse_quantity == 30
    assert order.line_items[0].difference == 20
    assert order.status == OrderStatus.READY_TO_SUBMIT


def test_pipeline_unknown_item_needs_review(repo):
    extracted = ExtractedPO(
        header=POHeader(customer="Globex", po_number="PO-2002"),
        line_items=[LineItem(item_number="ITEM-9999", order_quantity=10, unit_price=9.0)],
    )
    client = FakeClient(extracted)
    order, _ = pipeline.run_pipeline(_pdf("PO"), repo, client)
    assert order.status == OrderStatus.NEEDS_REVIEW
    assert any(i.code == "UNKNOWN_ITEM" for i in order.issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline'`

- [ ] **Step 3: Write `backend/pipeline.py`**

```python
from backend.agents import draft, extraction, intake, validation
from backend.agents import exception as exception_agent
from backend.models import OrderDraft


def run_pipeline(pdf_bytes: bytes, repo, client) -> tuple[OrderDraft, list[dict]]:
    """Run the five agents in sequence. Returns the draft plus per-step status for the UI."""
    steps: list[dict] = []

    text = intake.extract_text(pdf_bytes)
    steps.append({"step": "intake", "ok": True})

    po = extraction.extract_po(text, client)
    steps.append({"step": "extraction", "ok": True})

    issues = validation.validate(po, repo)
    steps.append({"step": "validation", "ok": True})

    issues += exception_agent.process_exceptions(po, repo)
    steps.append({"step": "exception", "ok": True})

    order = draft.build_draft(po, issues)
    steps.append({"step": "draft", "ok": True})

    return order, steps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/pipeline.py po-agents/tests/test_pipeline.py
git commit -m "feat: sequential pipeline orchestration of the five agents"
```

---

## Task 10: FastAPI routes (`app.py`)

**Files:**
- Create: `backend/app.py`
- Test: `tests/test_app.py`

> `/api/process`: PDF → pipeline → `{order, steps}`. ValueError (no text) → 422; ExtractionError → 502.
> `/api/submit`: re-runs Exception (re-query stock) + commit checks + Draft (recompute derived). If any error → return draft `needs_review`, not released. Else record PO + status `released_to_warehouse`. Save/Revise buttons are client-side only in the MVP — `/api/submit` is the release path.
> The anthropic client is created lazily via `get_client()` so tests can override it through dependency injection.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.app'`

- [ ] **Step 3: Write `backend/app.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add po-agents/backend/app.py po-agents/tests/test_app.py
git commit -m "feat: FastAPI routes /api/process and /api/submit"
```

---

## Task 11: End-to-end scenario tests + sample PDFs

**Files:**
- Create: `tests/make_sample_pdfs.py`
- Create: `tests/test_e2e_scenarios.py`
- Generates: `samples/valid.pdf`, `samples/missing_customer.pdf`, `samples/unknown_item.pdf`

> These tests drive the full pipeline through the three README scenarios using `FakeClient` seeded with the ExtractedPO each sample text would yield. They are the acceptance tests.

- [ ] **Step 1: Write `tests/make_sample_pdfs.py` (dev helper)**

```python
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
```

- [ ] **Step 2: Generate the sample PDFs**

Run: `python tests/make_sample_pdfs.py`
Expected: writes `samples/valid.pdf`, `samples/missing_customer.pdf`, `samples/unknown_item.pdf`.

- [ ] **Step 3: Write `tests/test_e2e_scenarios.py`**

```python
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
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests across all files green).

- [ ] **Step 5: Commit**

```bash
git add po-agents/tests/make_sample_pdfs.py po-agents/tests/test_e2e_scenarios.py po-agents/samples
git commit -m "test: end-to-end README scenarios + demo sample PDFs"
```

---

## Task 12: Frontend (three-column single page)

**Files:**
- Create: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
- Modify: `backend/app.py` (serve static frontend)

> The frontend is a single page with three columns: PDF preview (left), agent workflow steps (middle), editable order draft (right). It is delivered as complete files plus a manual verification step (frontends are validated by running, not unit-tested here).

- [ ] **Step 1: Write `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PO Intake Agent</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <header><h1>PO Intake Agent</h1></header>
  <main class="cols">
    <section class="col" id="col-pdf">
      <h2>Original PO</h2>
      <input type="file" id="pdf-input" accept="application/pdf" />
      <iframe id="pdf-preview" title="PDF preview"></iframe>
    </section>

    <section class="col" id="col-steps">
      <h2>Agent Workflow</h2>
      <ol id="steps"></ol>
    </section>

    <section class="col" id="col-draft">
      <h2>Order Draft</h2>
      <form id="draft-form">
        <div class="header-fields">
          <label>Customer <input name="customer" /></label>
          <label>PO Number <input name="po_number" /></label>
          <label>Ship To <input name="ship_to" /></label>
          <label>Ship From <input name="ship_from_warehouse" /></label>
          <label>Ship Date <input name="ship_date" /></label>
          <label>Carrier <input name="carrier" /></label>
        </div>
        <div id="items"></div>
        <div class="order-total">Order Total: <span id="order-total">—</span></div>
        <label>Order note <input name="order_note" /></label>
        <div class="status">Status: <span id="status">—</span></div>
        <div class="actions">
          <button type="button" id="btn-revise">Revise</button>
          <button type="button" id="btn-save">Save</button>
          <button type="button" id="btn-release">Release to Warehouse</button>
        </div>
      </form>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `frontend/styles.css`**

```css
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; }
header { padding: 12px 20px; border-bottom: 1px solid #ddd; }
h1 { font-size: 18px; margin: 0; }
.cols { display: grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 12px; padding: 12px; }
.col { border: 1px solid #e2e2e2; border-radius: 8px; padding: 12px; min-height: 70vh; }
.col h2 { font-size: 14px; margin: 0 0 8px; color: #555; }
#pdf-preview { width: 100%; height: 60vh; border: 1px solid #eee; }
#steps li { padding: 4px 0; color: #888; }
#steps li.done { color: #137333; }
#steps li.done::before { content: "✓ "; }
.header-fields { display: grid; gap: 6px; margin-bottom: 12px; }
.header-fields label, .order-total, .status { display: block; font-size: 13px; }
.header-fields input { width: 100%; padding: 4px; }
.item { border-top: 1px solid #eee; padding: 8px 0; }
.item .ids { font-weight: 600; }
.item .commit-row { font-size: 12px; color: #444; display: flex; gap: 8px; align-items: center; }
.item.unknown .ids::after { content: " ⚠ Not found"; color: #b00020; }
.actions { margin-top: 12px; display: flex; gap: 8px; }
.actions button { padding: 6px 10px; cursor: pointer; }
#btn-release:disabled { opacity: 0.5; cursor: not-allowed; }
.issue { color: #b00020; font-size: 12px; }
```

- [ ] **Step 3: Write `frontend/app.js`**

```javascript
const $ = (sel) => document.querySelector(sel);
let currentOrder = null;

$("#pdf-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  $("#pdf-preview").src = URL.createObjectURL(file);
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/process", { method: "POST", body: form });
  if (!resp.ok) {
    alert("Process failed: " + (await resp.text()));
    return;
  }
  const body = await resp.json();
  renderSteps(body.steps);
  currentOrder = body.order;
  renderDraft(currentOrder);
});

function renderSteps(steps) {
  $("#steps").innerHTML = steps
    .map((s) => `<li class="${s.ok ? "done" : ""}">${s.step}</li>`)
    .join("");
}

function renderDraft(order) {
  for (const k of ["customer", "po_number", "ship_to", "ship_from_warehouse", "ship_date", "carrier"]) {
    const el = document.querySelector(`[name=${k}]`);
    if (el) el.value = order.header[k] ?? "";
  }
  $("[name=order_note]").value = order.order_note ?? "";
  $("#order-total").textContent = order.order_total != null ? `$${order.order_total.toFixed(2)}` : "—";
  $("#status").textContent = order.status;
  $("#btn-release").disabled = order.status !== "ready_to_submit";
  $("#items").innerHTML = order.line_items.map(itemRow).join("");
}

function itemRow(li, idx) {
  const unknown = (currentOrder.issues || []).some(
    (i) => i.code === "UNKNOWN_ITEM" && i.field === `line_items[${idx}].item_number`
  );
  const price = li.unit_price != null ? `$${li.unit_price.toFixed(2)}` : "—";
  const lineTotal = li.line_total != null ? `$${li.line_total.toFixed(2)}` : "—";
  return `
    <div class="item ${unknown ? "unknown" : ""}" data-idx="${idx}">
      <div class="ids">${li.item_number}</div>
      <div>Order ${li.order_quantity} | Unit ${price} | Line ${lineTotal} | Stock ${li.warehouse_quantity}</div>
      <div class="commit-row">
        Commit auto ${li.inventory_commit} →
        manual <input type="number" min="0" max="${li.warehouse_quantity}"
          value="${li.manual_commit ?? li.inventory_commit}" data-field="manual_commit" />
        → ships ${li.committed_quantity} | cut ${li.difference}
      </div>
      <div class="commit-row">
        Cut reason
        <select data-field="cut_reason_type">
          ${["", "缺货", "已停产", "客户要求", "货损", "其他"]
            .map((o) => `<option ${o === (li.cut_reason_type ?? "") ? "selected" : ""}>${o}</option>`)
            .join("")}
        </select>
      </div>
      <div class="commit-row">
        On the way <input type="range" min="0" max="${li.difference}"
          value="${li.on_the_way_quantity}" data-field="on_the_way_quantity" />
        <span>${li.on_the_way_quantity}</span>
        <input placeholder="tracking #" value="${li.on_the_way_tracking_no ?? ""}"
          data-field="on_the_way_tracking_no" />
      </div>
      <input class="note" placeholder="📝 note" value="${li.note ?? ""}" data-field="note" />
    </div>`;
}

function collectDraft() {
  const header = {};
  for (const k of ["customer", "po_number", "ship_to", "ship_from_warehouse", "ship_date", "carrier"]) {
    header[k] = document.querySelector(`[name=${k}]`).value || null;
  }
  const line_items = currentOrder.line_items.map((li, idx) => {
    const row = document.querySelector(`.item[data-idx="${idx}"]`);
    const get = (f) => row.querySelector(`[data-field=${f}]`);
    const manual = get("manual_commit").value;
    return {
      ...li,
      manual_commit: manual === "" ? null : Number(manual),
      cut_reason_type: get("cut_reason_type").value || null,
      on_the_way_quantity: Number(get("on_the_way_quantity").value),
      on_the_way_tracking_no: get("on_the_way_tracking_no").value || null,
      note: get("note").value || null,
    };
  });
  return { ...currentOrder, header, line_items, order_note: $("[name=order_note]").value || null };
}

async function submitDraft() {
  const resp = await fetch("/api/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectDraft()),
  });
  const body = await resp.json();
  currentOrder = body.order;
  renderDraft(currentOrder);
  if (body.released) alert("Released to warehouse.");
}

$("#btn-release").addEventListener("click", submitDraft);
$("#btn-save").addEventListener("click", () => { currentOrder = collectDraft(); renderDraft(currentOrder); });
$("#btn-revise").addEventListener("click", () => { $("#status").textContent = "revise"; });
```

- [ ] **Step 4: Serve the frontend from FastAPI — modify `backend/app.py`**

Add near the top after `app = FastAPI(...)`:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "index.html"))
```

- [ ] **Step 5: Manual verification**

Run:
```bash
uvicorn backend.app:app --reload
```
Open `http://localhost:8000`, upload `samples/valid.pdf`. Verify: 5 steps show ✓; draft populates; Order Total shows `$200.00`; Status `ready_to_submit`; Release enabled. Upload `samples/unknown_item.pdf`: item shows ⚠ Not found; Status `needs_review`; Release disabled.

- [ ] **Step 6: Commit**

```bash
git add po-agents/frontend po-agents/backend/app.py
git commit -m "feat: three-column single-page frontend + static serving"
```

---

## Task 13: README + final docs

**Files:**
- Modify: `README.md` (append only — see warning)

> ⚠️ **Do NOT overwrite the existing `README.md`.** It is the product-requirements document (problem/solution/features/agent architecture/UI/demo scenarios) and is what the design spec refers to as "the README scenarios". **Append** a new `## Development (MVP)` section to the END of the existing file. When appending: drop the duplicate top-level `# PO Intake Agent` heading and the `## Architecture` block from the snippet below (already covered in the existing README); keep Setup / Run / Test / Demo scenarios. Start the appended block with `---` then `## Development (MVP)`, and include a one-line scope note that this MVP is **PDF-only** (the existing README lists email-text input, which is future work).

- [ ] **Step 1: Append the `## Development (MVP)` section to the end of `README.md`** (append, do not overwrite — see warning above)

```markdown
# PO Intake Agent

Turns a Purchase Order PDF into a validated, human-reviewable, editable order draft ready for warehouse release. A deterministic 5-agent pipeline (only Extraction calls Claude).

## Setup
```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY
python tests/make_sample_pdfs.py
```

## Run
```bash
uvicorn backend.app:app --reload
# open http://localhost:8000
```

## Test
```bash
pytest -q
```

## Demo scenarios
| Sample PDF | Result |
|---|---|
| samples/valid.pdf | ready_to_submit |
| samples/missing_customer.pdf | needs_review (MISSING_CUSTOMER) |
| samples/unknown_item.pdf | needs_review (UNKNOWN_ITEM / Not found) |

## Architecture
Intake (pdfplumber) → Extraction (Claude `messages.parse`) → Validation → Exception → Draft.
Repository (SQLite + seed JSON) is a replaceable interface for real ERP/WMS later.
See `docs/superpowers/specs/2026-06-19-po-intake-agent-design.md`.
```

- [ ] **Step 2: Final full-suite check**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add po-agents/README.md
git commit -m "docs: README with setup, run, test, and demo scenarios"
```

---

## Self-Review (completed by plan author)

**1. Spec coverage:**
- 5 agents → Tasks 4–9. ✅
- Only Extraction calls Claude → Task 8 (faked in tests). ✅
- Data models incl. commit fields, ship_date/carrier/ship_from_warehouse, amounts → Task 1. ✅
- inventory_commit/manual_commit/committed_quantity/difference rules → Tasks 6 (auto-commit), 7 (committed/difference). ✅
- COMMIT_EXCEEDS_STOCK (manual ≤ stock) → Task 5 `check_commits`, enforced at submit Task 10. ✅
- UNKNOWN_ITEM = Exception, message "Not found", zeroes stock/commit → Task 6. ✅
- Amounts by order_quantity, order_total = Σ line_total → Task 7. ✅
- Repository (SQLite + seed, dup-PO) → Tasks 2–3. ✅
- `/api/process` + `/api/submit` (submit recomputes via Exception+Draft) → Task 10. ✅
- Error handling: no-text → 422, Claude failure → 502 → Tasks 4/8/10. ✅
- Three README scenarios as acceptance tests → Task 11. ✅
- Three-column frontend with all fields → Task 12. ✅
- File structure matches spec → all tasks. ✅

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". All code blocks complete. ✅

**3. Type consistency:** `extract_text`, `extract_po`, `validate`/`check_commits`, `process_exceptions`, `build_draft`, `run_pipeline`, and `Repository.{customer_exists,find_item,is_duplicate_po,record_po}` are used identically across Tasks 1–12 and match the Type Contract table. `OrderStatus` values match the spec strings. ✅

**Customer existence:** `validation.validate` checks both non-empty customer (`MISSING_CUSTOMER`) and existence in the customer master (`UNKNOWN_CUSTOMER`), mirroring the item-existence and dup-PO patterns. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-po-intake-agent.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
