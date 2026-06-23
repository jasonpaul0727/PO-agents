# PO Intake Agent — Design Spec

- **Date:** 2026-06-19
- **Status:** Approved design, pending implementation plan
- **Scope:** Production-leaning MVP

## Goal

Transform Purchase Orders (PDF) into validated, human-reviewable order records ready for ERP/WMS entry. A code-orchestrated pipeline of five agents extracts, validates, and prepares PO data; the human operator makes the final decision and can edit before release.

## Positioning

- **MVP, production-leaning.** Architecture leaves room to plug in real ERP/WMS later (via the Repository interface). Demo runs on mock master data.
- **Input: PDF only.** Parsed to text with `pdfplumber`. (Email-text input is out of scope for the MVP; the pipeline from Extraction onward can be reused later if added.)
- **Only the Extraction agent calls Claude.** The other four agents are deterministic Python. This keeps the system controllable, testable, and cheap.

## Architecture

```
浏览器 (单页三栏)
   │  POST /api/process   (multipart PDF)
   ▼
FastAPI 后端
   │
   ├─ Pipeline (顺序编排 5 个 agent)
   │    1. IntakeAgent      —— PDF→文本 (pdfplumber)，清洗
   │    2. ExtractionAgent  —— Claude structured output → JSON
   │    3. ValidationAgent  —— 必填/格式/重复 PO，对 mock master data
   │    4. ExceptionAgent   —— 缺失/未知项标记
   │    5. DraftAgent       —— 拼 OrderDraft + human summary + 状态
   │
   ├─ Repository 层 (接口可替换)  —— customer master / item master / 已提交 PO
   │    MVP: SQLite + 种子 JSON；预留以后接真实 ERP/WMS
   │
   └─ POST /api/submit   (edited OrderDraft) —— 重新校验 + 落库 + 登记 PO
```

The five agents run as a **deterministic sequential pipeline** (not an LLM-driven agentic loop). Only `ExtractionAgent` calls Claude.

## Claude usage (Extraction)

- **Method:** `client.messages.parse(...)` with a Pydantic schema (`output_config.format` JSON schema under the hood) — guarantees strict, validated JSON. This is the recommended extraction approach over prompting for JSON.
- **Model:** default `claude-opus-4-8` (highest extraction quality). **Cost option:** `claude-sonnet-4-6` ($3/$15 per 1M vs Opus $5/$25) is a strong price/quality point for higher volume — operator/owner decision, configurable via env.
- **Params:** `output_config={"effort": "low"}`, no thinking (extraction needs no deep reasoning), `max_tokens=2048`.
- **System prompt:** "Extract only what is present. Do not invent missing fields — set them to null."
- **Optional fallback:** a rule/regex parser may serve as a fallback/cross-check if the Claude call fails; not required for the first cut.

## Data models (Pydantic)

```python
class LineItem(BaseModel):
    item_number: str
    order_quantity: int                       # 订购数量（PO 提取）
   bu warehouse_quantity: int                   # 仓库库存（item master mock）
    difference: int                           # = order_quantity - warehouse_quantity（缺口/cut 量）
    cut_reason_type: str | None = None        # cut 原因，下拉选择
    on_the_way_quantity: int = 0              # 在途数量，scroll bar (0 ~ order_quantity)
    on_the_way_tracking_no: str | None = None # 在途单号，隐藏 text bar，仅 on_the_way>0 才显示
    note: str | None = None                   # 行备注

class POHeader(BaseModel):
    customer: str | None
    po_number: str | None
    ship_to: str | None
    requested_date: str | None                # 客户要求到货日，ISO 或 None
    ship_date: str | None = None              # 计划发货日，ISO 或 None（提取/operator 可填）
    carrier: str | None = None                # 承运商，自由字符串（UPS/FedEx...），operator 可填/改

class ExtractedPO(BaseModel):                 # ExtractionAgent 的 structured output schema
    header: POHeader
    line_items: list[LineItem]                # 抽取阶段只填 item_number / order_quantity

class Issue(BaseModel):
    severity: Literal["error", "warning"]
    code: str                                 # MISSING_CUSTOMER / UNKNOWN_ITEM / DUP_PO ...
    message: str
    field: str | None                         # 指向字段/行，前端高亮

class OrderStatus(str, Enum):
    NEEDS_REVIEW          = "needs_review"           # 有 error，必须人工处理
    REVISE                = "revise"                 # operator 主动标记待修订/退回
    READY_TO_SUBMIT       = "ready_to_submit"        # 校验通过，可提交
    RELEASED_TO_WAREHOUSE = "released_to_warehouse"  # 终态，已下发 WMS

class OrderDraft(BaseModel):
    header: POHeader
    line_items: list[LineItem]
    issues: list[Issue]
    order_note: str | None = None
    status: OrderStatus
    human_summary: str
```

**Field notes**
- `difference` 是派生值 `order_quantity - warehouse_quantity`（缺口/被 cut 的量）。
- Cut 不是数量滑动条，而是 `cut_reason_type` 下拉（为什么 cut）。默认下拉选项：`缺货 / 已停产 / 客户要求 / 货损 / 其他`。
- `on_the_way_quantity` 是独立的 scroll bar（0 ~ order_quantity）。
- `on_the_way_tracking_no` 是隐藏 text bar，仅当 `on_the_way_quantity > 0` 时显示。
- `warehouse_quantity` 来自 item master mock；Extraction 阶段不填，由 Exception/Validation 阶段补。
- `ship_date` / `carrier` 是订单级（header）字段：Extraction 若 PO 上写了就提取，否则 null；operator 在草稿里填/改。`ship_date` 是计划发货日（区别于 `requested_date` 客户要求到货日），`carrier` 是自由字符串（如 `UPS` / `FedEx`），不是枚举。

## Agent contracts

| Agent | 输入 | 输出 | 调 Claude? |
|---|---|---|---|
| Intake | `{pdf bytes}` | 干净纯文本 + `document_type` | 否（pdfplumber + 清洗） |
| Extraction | 文本 | `ExtractedPO` (header + line items) | **是**（`messages.parse` + schema） |
| Validation | `ExtractedPO` | `list[Issue]`（必填/格式/重复 PO） | 否（规则 + repository 查询） |
| Exception | `ExtractedPO` + master data | `list[Issue]` + 回填 `warehouse_quantity` | 否（查 master data） |
| Draft | `ExtractedPO` + 合并 issues | `OrderDraft` | 否（拼装 + 算状态/差额） |

**Status 规则（系统初判）**：任何 `severity == "error"` 的 issue → `NEEDS_REVIEW`；否则 `READY_TO_SUBMIT`。`UNKNOWN_ITEM`（README 场景 3）按 error。

**Status 流转**：`系统初判 (needs_review | ready_to_submit)` → operator 编辑（改 header/数量、选 cut reason、调 on-the-way、写备注）→ 可手动设 `revise` 或重新校验 → `ready_to_submit` → 点 Release → `released_to_warehouse`（落库 + 登记 PO 防重复）。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST /api/process` | 上传 PDF（multipart）→ 跑流水线 → 返回 `OrderDraft` + 每步 step 状态 |
| `POST /api/submit` | 提交编辑后的 `OrderDraft` → 服务端重新校验 → 落库 + 登记 PO → 返回终态 |

## Frontend (单页三栏)

```
| Original PO (PDF 预览) | Agent Workflow (Step1-5 ✓) | Order Draft (可编辑) |
                                                  Customer  [______]
                                                  PO Number [______]
                                                  Ship To   [______]
                                                  Ship Date [______]
                                                  Carrier   [______]
                                                  Items:
                                                    ITEM-1001  订购50 | 库存30 | 差额(cut)20
                                                       Cut reason:[缺货 ▼]
                                                       On the way:[===●----]15  单号:[TRK-...]
                                                       📝 note
                                                    ITEM-9999  ⚠ 未知物品
                                                  Order note:[__________]
                                                  Status: needs_review
                                                  [Revise] [Save] [Release to Warehouse]
```

- header 字段、order_quantity 可 inline 编辑
- 每行：`cut_reason_type` 下拉 / `on_the_way_quantity` scroll bar / 在途单号（>0 显示）/ 行备注
- `Release to Warehouse` 仅在 `ready_to_submit` 时可点

## Error handling

- PDF 解析失败 / 抽不到文本（扫描版）→ 返回明确错误，前端提示「PDF 无可提取文本」。
- Claude 调用失败 → 重试 2 次后返回 502 + 友好信息。
- 校验/异常不是错误，是正常的 `issues`，照常返回 draft。

## Testing

- pytest。三个 README demo 场景端到端：Valid PO / Missing Customer / Unknown Item。
- 各 agent 单测；Extraction 用录制的样例文本，避免每次打 API。
- mock master data 用固定种子（customers / items）。

## Repository / data

- MVP: SQLite + 种子 JSON（`customers.json`、`items.json`，items 含 `warehouse_quantity`）。
- 已提交 PO 表用于重复检测（`DUP_PO`）。
- Repository 做成接口，以后可替换为真实 ERP/WMS 适配器。

## File structure

```
po-agents/
  backend/
    app.py                # FastAPI 入口 + 两个路由
    pipeline.py           # 顺序编排
    agents/
      intake.py extraction.py validation.py exception.py draft.py
    models.py             # Pydantic 模型
    repository.py         # master data + 已提交 PO（SQLite，接口可替换）
    seed/customers.json  seed/items.json
  frontend/
    index.html  app.js  styles.css   # 单页三栏
  tests/
  samples/                # 3 个 demo PDF
  requirements.txt
  .env.example            # ANTHROPIC_API_KEY, PO_MODEL (default claude-opus-4-8)
  README.md
```

## Demo scenarios

| Scenario | Input | Result |
|---|---|---|
| 1. Valid PO | 完整正确 | `ready_to_submit` |
| 2. Missing Customer | 无 customer | `needs_review` |
| 3. Unknown Item | ITEM-9999 不在 item master | `needs_review`（`UNKNOWN_ITEM` error） |

## Out of scope (MVP)

- 邮件文本输入、扫描版 PDF / OCR、真实 ERP/WMS 对接、多用户/鉴权、并发处理。
