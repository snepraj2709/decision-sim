"""Pydantic schemas — the API's wire format.

These are the source of truth for what crosses the network boundary. The
frontend's TypeScript types in `apps/web/lib/api.ts` are written to match.
Step 5 will codegen the TS from these (via OpenAPI); for Step 1, manual sync.

Naming convention:
  - `*Create`  — request body for creating a resource
  - `*Read`    — response body for reading a resource
  - `*Update`  — request body for partial updates (PATCH)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Shared types (mirror frontend) ──────────────────────────────────────────
Confidence = Literal["high", "medium", "low"]
DecisionType = Literal["pricing", "copy", "feature", "bundle", "onboarding"]
SimStatus = Literal["pending", "running", "completed", "failed"]


# ── Health ──────────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: Literal["ok"]
    env: str
    version: str


# ── Field with confidence — the recurring "confidence chip" pattern ─────────
class ConfidentField(BaseModel):
    """A factual field paired with confidence + source count.

    Used in the Product Snapshot — every field on the snapshot card has this
    shape so the UI can render a confidence chip next to each one.
    """

    value: str
    confidence: Confidence
    sources: int = Field(ge=0, description="Number of independent sources supporting this")


# ── Product Snapshot (Step 2 will populate these) ───────────────────────────
class ProductSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    created_at: datetime

    category: ConfidentField | None
    value_prop: ConfidentField | None
    pricing: ConfidentField | None
    features: ConfidentField | None
    audience: ConfidentField | None
    competitors: ConfidentField | None


class SnapshotCreateRequest(BaseModel):
    """Kick off a snapshot run for a URL."""

    url: str = Field(min_length=4, max_length=1024)


# Job status for async snapshot processing
JobStatus = Literal["queued", "started", "finished", "failed"]


class SnapshotJobResponse(BaseModel):
    """Response when a snapshot job is enqueued."""

    job_id: str
    status_url: str


class SnapshotJobStatus(BaseModel):
    """Status of a snapshot job."""

    status: JobStatus
    snapshot_id: uuid.UUID | None = None
    error: str | None = None


# ── Evidence ────────────────────────────────────────────────────────────────
EvidenceKind = Literal["reddit", "g2", "twitter", "capterra", "review", "press", "other"]


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    quote: str
    source: str
    source_url: str | None
    kind: EvidenceKind
    captured_at: datetime | None


# ── Segment ─────────────────────────────────────────────────────────────────
class DriverWeight(BaseModel):
    label: str
    weight: float = Field(ge=0.0, le=1.0)


class SegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    descriptor: str | None
    job_to_be_done: str | None
    share_pct: int | None
    confidence: Confidence
    drivers: list[DriverWeight] | None
    leaves: str | None
    evidence: list[EvidenceRead] = []


# ── Simulation ──────────────────────────────────────────────────────────────
class OptionInput(BaseModel):
    letter: str = Field(min_length=1, max_length=2)
    title: str = Field(min_length=1, max_length=128)
    sub: str | None = Field(default=None, max_length=512)


class SimulationCellRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    segment_id: uuid.UUID
    option_letter: str
    range_low: int
    range_high: int
    confidence: Confidence
    reasoning_trace: str | None
    top_concern: str | None
    invalidating_experiment: str | None


class SimulationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    decision_type: DecisionType
    options: list[OptionInput]
    status: SimStatus
    overall_confidence: Confidence | None
    created_at: datetime
    completed_at: datetime | None
    cells: list[SimulationCellRead] = []


class SimulationCreateRequest(BaseModel):
    snapshot_id: uuid.UUID
    decision_type: DecisionType
    options: list[OptionInput] = Field(min_length=2, max_length=4)
