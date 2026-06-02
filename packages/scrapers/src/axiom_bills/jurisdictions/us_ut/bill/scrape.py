"""Utah bill scraper.

Utah publishes session bill data as official JSON under le.utah.gov/data.
The bill list gives current bill numbers, and each bill JSON includes
metadata, sponsors, subjects, affected sections, documents, and actions.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

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

ROOT = "https://le.utah.gov"
MT = ZoneInfo("America/Denver")


class UtahScraper(BillScraper):
    jurisdiction = "us-ut"
    source_name = "le.utah.gov official JSON"
    min_interval_per_host = 0.2

    def __init__(self, *, session_id: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_id = session_id or _current_session_id()

    def scrape(self) -> ScrapeResult:
        rows = self.http.get_json(f"{ROOT}/data/{self.session_id}/billlist.json")
        if self.limit is not None:
            rows = rows[:self.limit]
        bills = [
            parse_bill(self.http.get_json(f"{ROOT}/data/{self.session_id}/{row['number']}.json"))
            for row in rows
            if row.get("number")
        ]
        bills = [bill for bill in bills if bill is not None]
        bills.sort(key=lambda bill: bill.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session_from_id(self.session_id),
            bills=bills,
        )


def session_from_id(session_id: str) -> Session:
    year = int(session_id[:4])
    return Session(
        name=f"{year} General Session",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=True,
    )


def parse_bill(row: dict) -> Bill | None:
    number = str(row.get("billNumberLong") or row.get("billNumber") or "").upper()
    if not number:
        return None
    title = _clean_text(row.get("shortTitle")) or number
    return Bill(
        jurisdiction=UtahScraper.jurisdiction,
        session_name=session_from_id(row["sessionID"]).name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=_summary(row),
        subjects=_subjects(row),
        sponsors=_sponsors(row),
        source_url=f"{ROOT}/~{row['year']}/bills/static/{number}.html",
        actions=_actions(row.get("actionHistoryList") or [], number),
        versions=_versions(row.get("billVersionList") or []),
        kind=classify_kind(title),
    )


def _summary(row: dict) -> str | None:
    parts = [_clean_text(row.get("generalProvisions")), _clean_text(row.get("highlightedProvisions"))]
    parts = [part for part in parts if part]
    return "\n\n".join(parts) if parts else None


def _subjects(row: dict) -> list[str]:
    out: list[str] = []
    for version in row.get("billVersionList") or []:
        for subject in version.get("subjectList") or []:
            description = subject.get("description")
            if description and description not in out:
                out.append(str(description))
        for section in version.get("sectionAffectedList") or []:
            sec_no = section.get("secNo")
            if sec_no:
                out.append(f"Utah Code {sec_no}")
    return out


def _sponsors(row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    if row.get("primeSponsorName"):
        sponsors.append(Sponsor(
            name=str(row["primeSponsorName"]),
            role="primary",
        ))
    if row.get("floorSponsorName") and row.get("floorSponsorName") != row.get("primeSponsorName"):
        sponsors.append(Sponsor(
            name=str(row["floorSponsorName"]),
            role="floor",
        ))
    for version in row.get("billVersionList") or []:
        for sponsor in version.get("coSponsorList") or []:
            name = sponsor.get("sponsorName")
            if name:
                sponsors.append(Sponsor(name=str(name), role="cosponsor"))
    return sponsors


def _actions(rows: list[dict], number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        text = _clean_text(row.get("description"))
        when = _parse_datetime(row.get("actionDate"))
        if not text or when is None:
            continue
        actions.append(BillAction(
            occurred_at=when,
            chamber=_chamber(row.get("actionClass")) or _chamber_for_number(number),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(rows: list[dict]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[tuple[str, str]] = set()
    for version in rows:
        for doc in version.get("billDocs") or []:
            label = doc.get("shortDesc") or doc.get("fileType")
            url = doc.get("url")
            if not label or not url:
                continue
            source_url = str(url) if str(url).startswith("http") else f"{ROOT}{url}"
            key = (str(label), source_url)
            if key in seen:
                continue
            seen.add(key)
            versions.append(BillVersion(
                label=str(label),
                source_url=source_url,
                format=_format(source_url),
            ))
    return versions


def _chamber(raw: str | None) -> Chamber | None:
    if raw == "S":
        return Chamber.UPPER
    if raw == "H":
        return Chamber.LOWER
    if raw == "G":
        return Chamber.EXECUTIVE
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed.replace(tzinfo=MT)


def _format(url: str) -> str:
    suffix = url.rsplit(".", 1)[-1].lower()
    return suffix if suffix in {"html", "pdf", "xml", "txt"} else "html"


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    return (
        " ".join(str(raw).replace("<hr>", "\n").replace("<ltbullet>", "- ").split())
    )


def _current_session_id() -> str:
    return f"{datetime.now(tz=MT).year}GS"
