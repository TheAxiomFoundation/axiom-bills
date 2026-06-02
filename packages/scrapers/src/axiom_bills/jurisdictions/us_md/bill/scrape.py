"""Maryland bill scraper.

Maryland publishes an hourly open legislative data JSON file for each
regular session. It includes bill metadata, current status, subjects,
sponsors, and enough dated milestones to build a useful action history.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    Chamber,
    NormalizedStatus,
    ScrapeResult,
    Session,
    Sponsor,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

ROOT = "https://mgaleg.maryland.gov"
ET = ZoneInfo("America/New_York")


class MarylandScraper(BillScraper):
    jurisdiction = "us-md"
    source_name = "mgaleg.maryland.gov open legislative data"
    min_interval_per_host = 0.5

    def __init__(self, *, session_year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_year = session_year or datetime.now(tz=ET).year

    def scrape(self) -> ScrapeResult:
        session = Session(
            name=f"{self.session_year} Regular Session",
            start_date=date(self.session_year, 1, 1),
            end_date=date(self.session_year, 12, 31),
            is_current=True,
        )
        rows = self.http.get_json(_master_list_url(self.session_year))
        bills = [parse_bill(row, session.name, self.session_year) for row in rows]
        bills = [b for b in bills if b is not None]
        bills.sort(key=lambda b: b.number)
        if self.limit is not None:
            bills = bills[:self.limit]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def _master_list_url(year: int) -> str:
    return f"{ROOT}/{year}rs/misc/billsmasterlist/legislation.json"


def parse_bill(row: dict, session_name: str, session_year: int) -> Bill | None:
    number = str(row.get("BillNumber") or "").upper()
    if not number:
        return None
    title = row.get("Title") or number
    status = str(row.get("Status") or "")
    status_at = _parse_datetime(row.get("StatusCurrentAsOf")) or datetime.now(tz=ET)

    actions = _actions(row, status, status_at)
    if status and not any(a.action_text == status for a in actions):
        actions.append(BillAction(
            occurred_at=status_at,
            chamber=_chamber_for_number(number),
            action_text=status,
            normalized_status=match_first(status, PATTERNS),
        ))

    return Bill(
        jurisdiction=MarylandScraper.jurisdiction,
        session_name=session_name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=row.get("Synopsis"),
        subjects=_subjects(row),
        sponsors=[
            Sponsor(name=s.get("Name") or "Unknown", role="sponsor")
            for s in row.get("Sponsors") or []
            if isinstance(s, dict)
        ],
        source_url=f"{ROOT}/mgawebsite/Legislation/Details/{number.lower()}?ys={session_year}RS",
        actions=actions,
        versions=[],
        kind=classify_kind(title),
    )


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.startswith("SB") else Chamber.LOWER


def _subjects(row: dict) -> list[str]:
    out: list[str] = []
    for group in ("BroadSubjects", "NarrowSubjects"):
        for subject in row.get(group) or []:
            if isinstance(subject, dict) and subject.get("Name"):
                out.append(subject["Name"])
    return out


def _actions(row: dict, status: str, status_at: datetime) -> list[BillAction]:
    number = str(row.get("BillNumber") or "")
    chamber = _chamber_for_number(number)
    milestones = [
        ("FirstReadingDateHouseOfOrigin", "First reading"),
        ("HearingDateTimePrimaryHouseOfOrigin", "Hearing"),
        ("ReportDateHouseOfOrigin", row.get("ReportActionHouseOfOrigin") or "Committee report"),
        ("SecondReadingDateHouseOfOrigin", row.get("SecondReadingActionHouseOfOrigin") or "Second reading"),
        ("ThirdReadingDateHouseOfOrigin", row.get("ThirdReadingActionHouseOfOrigin") or "Third reading passed"),
        ("FirstReadingDateOppositeHouse", "First reading opposite house"),
        ("HearingDateTimePrimaryOppositeHouse", "Hearing opposite house"),
        ("ReportDateOppositeHouse", row.get("ReportActionOppositeHouse") or "Committee report opposite house"),
        ("SecondReadingDateOppositeHouse", row.get("SecondReadingActionOppositeHouse") or "Second reading opposite house"),
        ("ThirdReadingDateOppositeHouse", row.get("ThirdReadingActionOppositeHouse") or "Third reading passed opposite house"),
    ]
    actions: list[BillAction] = []
    for key, text in milestones:
        when = _parse_datetime(row.get(key))
        if when is None:
            continue
        actions.append(BillAction(
            occurred_at=when,
            chamber=chamber,
            action_text=str(text),
            normalized_status=match_first(str(text), PATTERNS),
        ))
    if row.get("PassedByMGA"):
        actions.append(BillAction(
            occurred_at=status_at,
            chamber=chamber,
            action_text="Passed by the General Assembly",
            normalized_status=NormalizedStatus.ENROLLED,
        ))
    return actions


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw)).replace(tzinfo=ET)
        except ValueError:
            return None
