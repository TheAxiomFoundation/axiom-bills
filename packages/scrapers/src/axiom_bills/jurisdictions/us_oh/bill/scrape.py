"""Ohio bill scraper.

Ohio exposes current General Assembly legislation through the official
SOLAR/LIS API. It includes bill metadata, sponsors, subjects, journal
actions, and document version download links.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from axiom_bills._common.base import BillScraper
from axiom_bills._common.models import (
    Bill,
    BillAction,
    BillVersion,
    Chamber,
    NormalizedStatus,
    ScrapeResult,
    Session,
    Sponsor,
)
from axiom_bills._common.status import match_first

from .kind import classify as classify_kind
from .status import PATTERNS

API_ROOT = "https://search-prod.lis.state.oh.us/api/v2"
PUBLIC_ROOT = "https://www.legislature.ohio.gov"
ET = ZoneInfo("America/New_York")


class OhioScraper(BillScraper):
    jurisdiction = "us-oh"
    source_name = "Ohio SOLAR/LIS API"
    min_interval_per_host = 0.3

    def __init__(self, *, session_id: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_id = session_id

    def scrape(self) -> ScrapeResult:
        session_row = self._session_row()
        session_id = session_row["id"]
        bills = self.http.get_json(f"{API_ROOT}/{session_id}/legislation/")
        if self.limit is not None:
            bills = bills[:self.limit]
        out: list[Bill] = []
        for row in bills:
            number = str(row.get("number") or "").lower()
            if not number:
                continue
            actions = self.http.get_json(f"{API_ROOT}/{session_id}/legislation/{number}/actions/")
            documents = self.http.get_json(f"{API_ROOT}/{session_id}/legislation/{number}/documents/")
            bill = parse_bill(row, session_row, actions, documents)
            if bill is not None:
                out.append(bill)
        out.sort(key=lambda bill: bill.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=parse_session(session_row),
            bills=out,
        )

    def _session_row(self) -> dict:
        if self.session_id:
            rows = self.http.get_json(f"{API_ROOT}/{self.session_id}/")
            if rows:
                return rows[0]
        rows = self.http.get_json(API_ROOT)
        selected = rows[0]
        hydrated = self.http.get_json(f"{API_ROOT}/{selected['id']}/")
        return hydrated[0] if hydrated else selected


def parse_session(row: dict) -> Session:
    name = row.get("name") or f"{_assembly_number(row)}th General Assembly"
    return Session(
        name=str(name),
        start_date=_parse_date(row.get("start")),
        end_date=_parse_date(row.get("end")),
        is_current=bool(row.get("current")) or _parse_date(row.get("end")) is None,
    )


def parse_bill(
    row: dict,
    session_row: dict,
    action_rows: list[dict],
    document_rows: list[dict],
) -> Bill | None:
    number = str(row.get("number") or "").upper()
    if not number:
        return None
    title = _clean_text(row.get("long_title") or row.get("short_title") or row.get("name")) or number
    actions = _actions(action_rows)
    actions.extend(_date_actions(row, number))
    actions.sort(key=lambda action: action.occurred_at)
    return Bill(
        jurisdiction=OhioScraper.jurisdiction,
        session_name=parse_session(session_row).name,
        chamber=_chamber(row.get("chamber")) or _chamber_for_number(number),
        number=number,
        title=title,
        summary=_clean_text(row.get("short_title")),
        subjects=_subjects(row),
        sponsors=_sponsors(row),
        source_url=f"{PUBLIC_ROOT}/legislation/{_assembly_number(session_row)}/{number.lower()}",
        actions=actions,
        versions=_versions(document_rows),
        kind=classify_kind(title),
    )


def _actions(rows: list[dict]) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        text = _clean_text(row.get("description") or row.get("action"))
        occurred_at = _parse_datetime(row.get("occurred"))
        if not text or occurred_at is None:
            continue
        committee = row.get("committee")
        if committee and str(committee).lower() not in text.lower():
            text = f"{text}: {row['committee']}"
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber(row.get("chamber")),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    return actions


def _date_actions(row: dict, number: str) -> list[BillAction]:
    fields = [
        ("concurrence_date", "Concurred", NormalizedStatus.PASSED_CHAMBER),
        ("governor_signed_date", "Governor signed", NormalizedStatus.SIGNED),
        ("effective_date", "Effective", NormalizedStatus.ENACTED),
    ]
    actions: list[BillAction] = []
    for field, text, status in fields:
        when = _parse_date(row.get(field))
        if when is None:
            continue
        actions.append(BillAction(
            occurred_at=datetime.combine(when, time.min, tzinfo=ET),
            chamber=_chamber_for_number(number),
            action_text=text,
            normalized_status=status,
        ))
    return actions


def _sponsors(row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for person in row.get("sponsors") or []:
        sponsors.append(_sponsor(person, "primary"))
    for person in row.get("cosponsors") or []:
        sponsors.append(_sponsor(person, "cosponsor"))
    return sponsors


def _sponsor(person: dict, role: str) -> Sponsor:
    return Sponsor(
        name=str(person.get("full_name") or "Unknown"),
        role=role,
        party=_party(person.get("party")),
        district=person.get("district"),
    )


def _versions(rows: list[dict]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    for row in sorted(rows, key=lambda r: int(r.get("version_number") or 0)):
        label = row.get("version")
        download = row.get("download")
        if not label or not download:
            continue
        versions.append(BillVersion(
            label=str(label),
            source_url=f"{API_ROOT}{download}",
            format="pdf",
        ))
    return versions


def _subjects(row: dict) -> list[str]:
    subjects: list[str] = []
    for subject in row.get("subjects") or []:
        for key in ("primary", "secondary"):
            value = subject.get(key)
            if value:
                subjects.append(str(value))
    return subjects


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "Senate":
        return Chamber.UPPER
    if raw == "House":
        return Chamber.LOWER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _assembly_number(row: dict) -> str:
    session_id = str(row.get("id") or "")
    return session_id.rsplit("_", 1)[-1]


def _party(raw: str | None) -> str | None:
    if not raw:
        return None
    if "republican" in raw:
        return "Republican"
    if "democrat" in raw:
        return "Democratic"
    return str(raw)


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ET)


def _parse_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    return " ".join(str(raw).split())
