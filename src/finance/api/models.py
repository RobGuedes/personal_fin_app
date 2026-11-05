"""Response models. Nothing here carries raw_json, documents or full account numbers."""

from typing import Literal

from pydantic import BaseModel, Field


class LineOut(BaseModel):
    id: str
    label: str


class CategoryOut(BaseModel):
    id: str
    line: str
    label: str
    icon: str
    color_slot: int | None


class TaxonomyOut(BaseModel):
    lines: list[LineOut]
    categories: list[CategoryOut]
    first_month: str | None = None  # earliest YYYY-MM with ledger rows (lower bound of the month picker)


class Totals(BaseModel):
    income: float
    tax_provision: float
    commissions: float
    expenses: float
    net_income: float


class RendaSplitOut(BaseModel):
    renda: float
    despesas: float
    outros: float
    sobrou: float
    scale: float
    deficit: bool


class SpendingOut(BaseModel):
    spent: float
    reference_to_date: float
    reference_month: float


class CategoryStatusOut(BaseModel):
    category_id: str
    spent: float
    reference_to_date: float | None
    reference_month: float | None
    reference_kind: str
    unusual: bool
    pct_over: float | None
    note: str | None


class IncomeSourceOut(BaseModel):
    key: str
    label: str
    amount: float


class MonthSummary(BaseModel):
    month: str
    day: int
    days_in_month: int
    is_current: bool
    totals: Totals
    renda_split: RendaSplitOut
    spending: SpendingOut
    categories: list[CategoryStatusOut]
    income_sources: list[IncomeSourceOut]
    review_count: int


class TrendPoint(BaseModel):
    month: str
    income: float
    spending: float


class TxOut(BaseModel):
    id: str
    date: str
    month: str
    description: str
    counterparty: str | None
    account: str
    amount: float
    category_id: str
    category_label: str | None
    line: str
    excluded: bool
    installment: str | None
    method: str | None
    source: str | None
    note: str | None
    in_review: bool


class TxDetail(TxOut):
    pluggy_category: str | None
    transfer_pair: TxOut | None
    suggestion: str | None


class TxPage(BaseModel):
    items: list[TxOut]
    next_cursor: str | None


class TxPatch(BaseModel):
    category_id: str | None = None
    note: str | None = None


class Suggestion(BaseModel):
    category_id: str
    reason: Literal["rule", "past_choice", "model", "transfer", "current"]
    detail: str


class ReviewItem(TxOut):
    suggestion: Suggestion | None
    top_categories: list[str]


class PreviousClassification(BaseModel):
    category_id: str
    source: Literal["rule", "pluggy_map", "transfer_detector", "manual"]  # classifications.source CHECK
    rule_id: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class ConfirmBody(BaseModel):
    category_id: str
    note: str | None = None
    create_rule: bool = False


class ConfirmOut(BaseModel):
    previous: PreviousClassification | None
    rule_id: str | None


class UndoBody(BaseModel):
    previous: PreviousClassification | None = None


class RuleBody(BaseModel):
    transaction_id: str
    category_id: str


class RuleOut(BaseModel):
    rule_id: str


class BudgetBody(BaseModel):
    monthly_amount: float


class ManualEntryBody(BaseModel):
    month: str
    pnl_line: str
    amount: float
    note: str


class SankeyNode(BaseModel):
    id: str
    label: str
    side: Literal["source", "middle", "target"]
    key: str
    value: float
    filter: dict[str, str] | None = None
    income: float | None = None  # middle node only: line 1


class SankeyLink(BaseModel):
    source: str
    target: str
    value: float


class SankeyOut(BaseModel):
    nodes: list[SankeyNode]
    links: list[SankeyLink]


class PanoramaCategory(BaseModel):
    category_id: str
    label: str
    total: float
    monthly_avg: float
    sparkline: list[float]
    usual: float | None


class PanoramaOut(BaseModel):
    months: list[str]
    savings_rate: float | None
    avg_income: float
    avg_spending: float
    categories: list[PanoramaCategory]


class PnlRowOut(BaseModel):
    key: str
    label: str
    level: int
    line: str
    values: dict[str, float]
    total: float
    average: float


class PnlOut(BaseModel):
    months: list[str]
    rows: list[PnlRowOut]


class ChannelOut(BaseModel):
    method: str
    label: str
    values: dict[str, float]
    total: float


class ChannelsOut(BaseModel):
    months: list[str]
    totals: dict[str, float]
    channels: list[ChannelOut]


class CounterpartyOut(BaseModel):
    name: str
    total: float
    count: int


class CounterpartiesOut(BaseModel):
    months: list[str]
    counterparties: list[CounterpartyOut]


class MonthValue(BaseModel):
    month: str
    value: float


class CategoryPageOut(BaseModel):
    category_id: str
    label: str
    monthly: list[MonthValue]
    total: float
    usual: float | None
    budget: float | None
    top_counterparties: list[CounterpartyOut]


class NetWorthAccount(BaseModel):
    label: str
    value: float
    updated_at: str | None


class NetWorthGroup(BaseModel):
    grp: str
    label: str
    value: float
    accounts: list[NetWorthAccount]


class NetWorthOut(BaseModel):
    total: float
    groups: list[NetWorthGroup]
    as_of: str | None


class ContributionsOut(BaseModel):
    months: list[str]
    values: dict[str, float]
    total: float


class AccountOut(BaseModel):
    id: str
    label: str
    type: str | None
    institution: str | None
