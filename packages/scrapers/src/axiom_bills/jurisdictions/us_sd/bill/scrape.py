"""South Dakota bill scraper.

South Dakota publishes current session metadata and bill data through
official JSON endpoints under sdlegislature.gov/api. Bill text PDFs are
served by the official mylrc.sdlegislature.gov document API.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillVersion,
    Chamber,
    ScrapeResult,
    Session,
    Sponsor,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

ROOT = "https://sdlegislature.gov"
DOCUMENT_ROOT = "https://mylrc.sdlegislature.gov/api/Documents"


class SouthDakotaScraper(BillScraper):
    jurisdiction = "us-sd"
    source_name = "sdlegislature.gov official API"
    min_interval_per_host = 0.2

    def __init__(self, *, session_id: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_id = session_id

    def scrape(self) -> ScrapeResult:
        session_row = self._session_row()
        session_id = int(session_row["SessionId"])
        rows = self.http.get_json(f"{ROOT}/api/Bills/Session/{session_id}")
        if self.limit is not None:
            rows = rows[:self.limit]
        bills = [
            parse_bill(
                self.http.get_json(f"{ROOT}/api/Bills/{row['BillId']}"),
                row,
                self.http.get_json(f"{ROOT}/api/Bills/ActionLog/{row['BillId']}"),
                self.http.get_json(f"{ROOT}/api/Bills/Versions/{row['BillId']}"),
                session=session_from_row(session_row),
            )
            for row in rows
            if row.get("BillId")
        ]
        bills = [bill for bill in bills if bill is not None]
        bills.sort(key=lambda bill: bill.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session_from_row(session_row),
            bills=bills,
        )

    def _session_row(self) -> dict:
        if self.session_id is not None:
            for row in self.http.get_json(f"{ROOT}/api/Sessions"):
                if int(row["SessionId"]) == self.session_id:
                    return row
        current = self.http.get_json(f"{ROOT}/api/Sessions/Current")
        for row in self.http.get_json(f"{ROOT}/api/Sessions"):
            if int(row["SessionId"]) == int(current["SessionId"]):
                return row
        return current


def session_from_row(row: dict) -> Session:
    year = _year(row.get("YearString") or row.get("Year"))
    return Session(
        name=_clean_text(row.get("LongName")) or _clean_text(row.get("YearString")) or f"{year} Session",
        start_date=_parse_date(row.get("StartDate")) or date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=bool(row.get("CurrentSession")),
    )


def parse_bill(
    detail: dict,
    summary: dict,
    action_rows: list[dict],
    version_rows: list[dict],
    *,
    session: Session,
) -> Bill | None:
    bill_id = detail.get("BillId") or summary.get("BillId")
    number = _bill_number(detail or summary)
    if bill_id is None or not number:
        return None
    title = _clean_text(detail.get("Title") or summary.get("Title")) or number
    return Bill(
        jurisdiction=SouthDakotaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=title,
        subjects=_subjects(detail),
        sponsors=_sponsors(detail),
        source_url=f"{ROOT}/Session/Bill/{bill_id}",
        actions=_actions(action_rows, number),
        versions=_versions(version_rows),
        kind=classify_kind(title),
    )


def _bill_number(row: dict) -> str | None:
    bill_type = _clean_text(row.get("BillType"))
    raw_number = row.get("BillNumber") or row.get("BillNumberOnly")
    if not bill_type or raw_number in (None, ""):
        return None
    if str(raw_number).upper().startswith(bill_type.upper()):
        return str(raw_number).upper()
    return f"{bill_type}{raw_number}".upper()


def _subjects(row: dict) -> list[str]:
    subjects: list[str] = []
    for keyword in row.get("Keywords") or []:
        label = _clean_text(keyword.get("Keyword"))
        if label and label not in subjects:
            subjects.append(label)
    return subjects


def _sponsors(row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for sponsor in row.get("BillSponsor") or []:
        name = _clean_text(sponsor.get("Name") or sponsor.get("FullName") or sponsor.get("SponsorName"))
        if name:
            sponsors.append(Sponsor(name=name, role="sponsor"))
    committee = _clean_text(_strip_tags(row.get("BillCommitteeSponsor")))
    if committee:
        sponsors.append(Sponsor(name=committee, role="committee"))
    return sponsors


def _actions(rows: list[dict], number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        text = _action_text(row)
        when = _parse_datetime(row.get("ActionDate"))
        if not text or when is None:
            continue
        actions.append(BillAction(
            occurred_at=when,
            chamber=_chamber((row.get("ActionCommittee") or {}).get("Body")) or _chamber_for_number(number),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _action_text(row: dict) -> str | None:
    parts = [_clean_text(row.get("StatusText")) or _clean_text(row.get("Description"))]
    assigned = row.get("AssignedCommittee") or {}
    assigned_name = _clean_text(assigned.get("FullName") or assigned.get("Name"))
    if row.get("ShowAssignedCommittee") and assigned_name:
        parts.append(assigned_name)
    vote = row.get("Vote") or {}
    if vote:
        parts.append(
            f"Yea {vote.get('Yeas', 0)}, Nay {vote.get('Nays', 0)}, "
            f"Excused {vote.get('Excused', 0)}, Absent {vote.get('Absent', 0)}"
        )
    return "; ".join(part for part in parts if part)


def _versions(rows: list[dict]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for row in rows:
        document_id = row.get("DocumentId")
        if document_id is None:
            continue
        url = f"{DOCUMENT_ROOT}/{document_id}.pdf"
        if url in seen:
            continue
        seen.add(url)
        versions.append(BillVersion(
            label=_clean_text(row.get("BillVersion")) or "Bill Text",
            source_url=url,
            format="pdf",
        ))
    return versions


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "S":
        return Chamber.UPPER
    if raw == "H":
        return Chamber.LOWER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _parse_date(raw) -> date | None:
    parsed = _parse_datetime(raw)
    return parsed.date() if parsed is not None else None


def _year(raw) -> int:
    match = re.search(r"\d{4}", str(raw or ""))
    if match:
        return int(match.group(0))
    return datetime.now().year


def _strip_tags(raw) -> str | None:
    if raw is None:
        return None
    return re.sub(r"<[^>]+>", "", str(raw))


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None
