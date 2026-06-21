# PO Intake Agent

**Transform Purchase Orders into Validated Order Records**

An agentic workflow that extracts, validates, and prepares purchase order data from PDF documents and email text for warehouse (WMS) and ERP order entry.

---

## Problem

Operations teams spend significant time manually processing purchase orders received through emails and PDF attachments.

For every PO, an operator must:

1. Open the document
2. Identify the customer
3. Locate the PO number
4. Extract item numbers and quantities
5. Validate the information
6. Enter the data into ERP/WMS systems

This process is **repetitive, time-consuming, and error-prone**.

## Solution

**PO Intake Agent** automates the intake process by converting unstructured purchase orders into validated, human-reviewable order records.

The system uses multiple agents to:

- Extract order information
- Validate data quality
- Detect missing fields
- Flag anomalies
- Generate a ready-to-submit order draft

> The final decision always remains with the human operator.

---

## Features

### 1. PO Input

Two input modes are supported:

- **PDF Upload** — upload a purchase order PDF
- **Email Text Input** — paste customer email content directly

Example email input:

```
Customer: ABC Trading
PO Number: PO-10023

Please ship:
ITEM-1001 Qty 50
ITEM-1002 Qty 120

Ship To:
Los Angeles Warehouse
```

### 2. Field Extraction

Automatically extracts:

**Header Fields**

```json
{
  "customer": "",
  "po_number": "",
  "ship_to": "",
  "requested_date": ""
}
```

**Line Items**

```json
[
  {
    "item_number": "",
    "quantity": 0
  }
]
```

### 3. Validation

Checks performed:

- **Required Fields** — Customer, PO Number, Item Number, Quantity
- **Format Validation** — e.g. quantity must be a positive number
- **Duplicate PO Check** — e.g. `PO-10023 already exists`

> For the demo, validation can run against **mock data**.

### 4. Exception Handling

Flags problems when detected:

| Problem | Message |
| --- | --- |
| Missing Customer | `Customer not found` |
| Missing PO Number | `PO Number missing` |
| Unknown Item | `ITEM-9999 not found in item master` |

### 5. Submission Draft

Generates the final result.

**Status** — either `Ready to Submit` or `Needs Review`.

**Structured JSON**

```json
{
  "customer": "ABC Trading",
  "po_number": "PO-10023",
  "items": [
    {
      "item_number": "ITEM-1001",
      "quantity": 50
    }
  ]
}
```

**Human Summary**

```
Customer: ABC Trading
PO Number: PO-10023

Items:
ITEM-1001 x 50
ITEM-1002 x 120

Status: Ready to Submit
```

---

## Agent Architecture

| # | Agent | Responsibility | Output |
| --- | --- | --- | --- |
| 1 | **Intake Agent** | Receive PDF / email text, clean input | `{ "document_type": "PO" }` |
| 2 | **Extraction Agent** | Extract header fields and line items | Header + line item JSON |
| 3 | **Validation Agent** | Data validation, PO check, item check | Validation results |
| 4 | **Exception Agent** | Handle missing fields, flag anomalies | Exception list |
| 5 | **Draft Agent** | Generate final order draft + summary | Order draft + status |

```
PDF / Email Text
       │
       ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ 1. Intake    │──▶│ 2. Extraction│──▶│ 3. Validation│──▶│ 4. Exception │──▶│ 5. Draft     │
│    Agent     │   │    Agent     │   │    Agent     │   │    Agent     │   │    Agent     │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                                                                                    │
                                                                                    ▼
                                                                          Order Draft + Status
```

---

## UI Layout

A single-page application is sufficient.

```
+------------------------------------------------------+
|                 PO Intake Agent                      |
+------------------------------------------------------+

| Original PO | Agent Workflow | Order Draft          |
|             |                |                      |
| PDF         | Step 1 ✓       | Customer             |
|             |                | ABC Trading          |
|             | Step 2 ✓       |                      |
| Email Text  |                | PO Number            |
|             | Step 3 ✓       | PO-10023             |
|             |                |                      |
|             | Step 4 ✓       | Items                |
|             |                | ITEM-1001 x 50       |
|             |                | ITEM-1002 x 120      |
|             | Status         | Ready to Submit      |
+------------------------------------------------------+
```

Three columns:

1. **Original PO** — the raw PDF / email input
2. **Agent Workflow** — step-by-step agent progress with status checks
3. **Order Draft** — the structured, human-reviewable result

---

## Demo Scenarios

Three buttons are enough to demonstrate the full range of outcomes.

| Scenario | Input | Result |
| --- | --- | --- |
| **1. Valid PO** | Complete, correct PO | `Ready to Submit` |
| **2. Missing Customer** | PO with no customer | `Needs Review` |
| **3. Unknown Item** | PO referencing an unknown item | `Item Not Found` |
