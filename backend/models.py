from enum import Enum
from typing import Literal

from pydantic import BaseModel


class LineItem(BaseModel):
    item_number: str                            # our internal item number
    customer_item_number: str | None = None     # the customer's own item number (cross-ref source)
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


class ExtractedLineItem(BaseModel):
    """Slim line item the LLM actually reads off the PO. The remaining LineItem
    fields are derived/backfilled by later agents, so they are kept out of the
    extraction schema."""

    item_number: str
    order_quantity: int
    unit_price: float | None = None


class ExtractedDocument(BaseModel):
    """`output_format` for `messages.parse`. Deliberately minimal so the
    constrained-decoding grammar compiles fast — the full ExtractedPO/LineItem
    schema intermittently triggers 'Grammar compilation timed out'."""

    header: POHeader
    line_items: list[ExtractedLineItem]


class ItemMapping(BaseModel):
    """A learned (customer item number -> our item number) cross-reference row."""

    customer: str
    customer_item_number: str
    item_number: str


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
