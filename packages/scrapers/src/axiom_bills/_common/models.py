"""Shared Pydantic models that scrapers emit and the writer consumes.

These are the in-memory shape — the SQL schema is the wire shape. The two
are intentionally similar but not identical: the models carry derived
fields (normalized_status on actions) that the SQL layer stores directly.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Chamber(str, Enum):
    LOWER = "lower"
    UPPER = "upper"
    JOINT = "joint"
    EXECUTIVE = "executive"


class NormalizedStatus(str, Enum):
    INTRODUCED = "introduced"
    IN_COMMITTEE = "in_committee"
    PASSED_CHAMBER = "passed_chamber"
    PASSED_BOTH = "passed_both"
    ENROLLED = "enrolled"
    SIGNED = "signed"
    ENACTED = "enacted"
    VETOED = "vetoed"
    VETO_OVERRIDDEN = "veto_overridden"
    FAILED = "failed"
    UNKNOWN = "unknown"


# Strictly ordered: a later status never overrides an earlier one when
# rolling up actions to bill.current_status. This is what stops a
# committee-referral action from clobbering a prior 'signed' status when
# the source publishes events out of order.
STATUS_ORDER: dict[NormalizedStatus, int] = {
    NormalizedStatus.UNKNOWN: 0,
    NormalizedStatus.INTRODUCED: 10,
    NormalizedStatus.IN_COMMITTEE: 20,
    NormalizedStatus.PASSED_CHAMBER: 30,
    NormalizedStatus.PASSED_BOTH: 40,
    NormalizedStatus.ENROLLED: 50,
    NormalizedStatus.VETOED: 60,
    NormalizedStatus.VETO_OVERRIDDEN: 70,
    NormalizedStatus.SIGNED: 80,
    NormalizedStatus.ENACTED: 90,
    NormalizedStatus.FAILED: 5,  # terminal but doesn't outrank progress
}


class Session(BaseModel):
    name: str
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False


class Sponsor(BaseModel):
    name: str
    role: str | None = None       # 'primary', 'cosponsor'
    party: str | None = None
    district: str | None = None


class BillAction(BaseModel):
    occurred_at: datetime
    chamber: Chamber | None = None
    action_text: str
    normalized_status: NormalizedStatus | None = None
    source_url: str | None = None


class BillVersion(BaseModel):
    label: str                    # 'introduced', 'engrossed', 'enrolled'
    source_url: str
    format: str                   # 'html', 'pdf', 'xml', 'txt'


class Bill(BaseModel):
    jurisdiction: str
    session_name: str
    chamber: Chamber
    number: str
    title: str | None = None
    summary: str | None = None
    subjects: list[str] = Field(default_factory=list)
    sponsors: list[Sponsor] = Field(default_factory=list)
    source_url: str
    actions: list[BillAction] = Field(default_factory=list)
    versions: list[BillVersion] = Field(default_factory=list)

    def derived_status(self) -> tuple[NormalizedStatus, datetime | None]:
        """Pick the highest-ranked normalized status across actions."""
        best: tuple[int, NormalizedStatus, datetime | None] = (
            STATUS_ORDER[NormalizedStatus.UNKNOWN],
            NormalizedStatus.UNKNOWN,
            None,
        )
        for action in self.actions:
            if action.normalized_status is None:
                continue
            rank = STATUS_ORDER[action.normalized_status]
            if rank > best[0]:
                best = (rank, action.normalized_status, action.occurred_at)
        return best[1], best[2]


class ScrapeResult(BaseModel):
    jurisdiction: str
    session: Session
    bills: list[Bill]
    notes: dict[str, Any] = Field(default_factory=dict)
