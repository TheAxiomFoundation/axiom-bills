"""Wyoming bill scraper.

Wyoming publishes bill lists and detail records through the same official
OData endpoints used by wyoleg.gov. Bill text PDFs are served under
wyoleg.gov/{year}/... document paths returned by the API.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlencode, urljoin
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

API_ROOT = "https://api.wyoleg.gov"
SITE_ROOT = "https://wyoleg.gov"
MT = ZoneInfo("America/Denver")


class WyomingScraper(BillScraper):
    jurisdiction = "us-wy"
    source_name = "wyoleg.gov official OData API"
    min_interval_per_host = 0.2

    def __init__(self, *, year: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.year = year or datetime.now(tz=MT).year

    def scrape(self) -> ScrapeResult:
        session = session_for_year(self.year)
        rows = self._bill_rows()
        if self.limit is not None:
            rows = rows[:self.limit]
        bills = [
            parse_bill(
                row,
                self._bill_detail(row["billNum"]),
                session=session,
            )
            for row in rows
            if row.get("billNum")
        ]
        bills = [bill for bill in bills if bill is not None]
        bills.sort(key=lambda bill: bill.number)
        return ScrapeResult(
            jurisdiction=self.jurisdiction,
            session=session,
            bills=bills,
        )

    def _bill_rows(self) -> list[dict]:
        params = {
            "select": (
                "BillNum,ShortTitle,Year,ChapterNo,Sponsor,EnrolledNo,"
                "LastActionDate,LastAction,SignedDate,EffectiveDate,"
                "BillType,SpecialSessionValue,BillStatus"
            ),
            "filter": f"Year eq {self.year} and SpecialSessionValue eq null",
            "orderby": "SpecialSessionValue,BillNum",
        }
        data = self.http.get_json(f"{API_ROOT}/v1/odata/BillInformations?{urlencode(params)}")
        return data.get("value") or []

    def _bill_detail(self, number: str) -> dict:
        params = {
            "year": str(self.year),
            "billNumber": number,
            "expand": "substituteBills,vetoes,amendments($expand=amendmentBudgetSections)",
        }
        return self.http.get_json(f"{API_ROOT}/v1/odata/BillReferences?{urlencode(params)}")


def session_for_year(year: int) -> Session:
    session_type = "Budget Session" if year % 2 == 0 else "General Session"
    return Session(
        name=f"{year} Wyoming {session_type}",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now(tz=MT).year,
    )


def parse_bill(row: dict, detail: dict, *, session: Session) -> Bill | None:
    number = _clean_text(detail.get("bill") or row.get("billNum"))
    if not number:
        return None
    title = _clean_text(detail.get("catchTitle") or row.get("shortTitle")) or number
    summary = _clean_text(detail.get("billTitle") or detail.get("summary")) or title
    return Bill(
        jurisdiction=WyomingScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(number),
        number=number,
        title=title,
        summary=summary,
        subjects=[],
        sponsors=_sponsors(detail, row),
        source_url=f"{SITE_ROOT}/Legislation/{_year(session)}/{number}",
        actions=_actions(detail.get("billActions") or [], row),
        versions=_versions(detail),
        kind=classify_kind(f"{title} {summary}"),
    )


def _sponsors(detail: dict, row: dict) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[str] = set()
    for item in detail.get("sponsors") or []:
        name = _clean_text(item.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        role = "primary" if item.get("primarySponsor") else "cosponsor"
        title = _clean_text(item.get("sponsorTitle"))
        sponsors.append(Sponsor(name=name, role=role if title is None else f"{role} {title}"))
    if sponsors:
        return sponsors
    sponsor = _clean_text(detail.get("sponsor") or row.get("sponsor"))
    return [Sponsor(name=sponsor, role="sponsor")] if sponsor else []


def _actions(rows: list[dict], bill_row: dict) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        occurred_at = _parse_datetime(row.get("statusDate"))
        text = _clean_text(row.get("statusMessage"))
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_for_location(row.get("location")) or _chamber_for_action(text),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    if not actions:
        occurred_at = _parse_datetime(bill_row.get("lastActionDate"))
        text = _clean_text(bill_row.get("lastAction"))
        if occurred_at is not None and text:
            actions.append(BillAction(
                occurred_at=occurred_at,
                chamber=_chamber_for_action(text),
                action_text=text,
                normalized_status=match_first(text, PATTERNS),
            ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def _versions(detail: dict) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for key, label in (
        ("introduced", "introduced"),
        ("substitute", "substitute"),
        ("engrossedVersion", "engrossed"),
        ("enrolledAct", "enrolled"),
        ("summary", "summary"),
        ("digest", "digest"),
        ("fiscalNote", "fiscal note"),
        ("concurrenceLink", "concurrence"),
        ("veto", "veto"),
    ):
        _append_version(versions, seen, label, detail.get(key))
    for item in detail.get("substituteBills") or []:
        _append_version(versions, seen, _clean_text(item.get("linkText")) or "substitute", item.get("filePath"))
    for item in detail.get("vetoes") or []:
        _append_version(
            versions,
            seen,
            _clean_text(item.get("vetoLinkText") or item.get("customEnrolledLinkText")) or "veto",
            item.get("vetoLinkPath") or item.get("customEnrolledPath"),
        )
    return versions


def _append_version(
    versions: list[BillVersion],
    seen: set[str],
    label: str,
    path: str | None,
) -> None:
    clean_path = _clean_text(path)
    if not clean_path:
        return
    source_url = urljoin(f"{SITE_ROOT}/", clean_path)
    if source_url in seen:
        return
    seen.add(source_url)
    suffix = source_url.rsplit(".", 1)[-1].lower()
    versions.append(BillVersion(
        label=label,
        source_url=source_url,
        format=suffix if suffix in {"html", "pdf", "xml", "txt"} else "pdf",
    ))


def _parse_datetime(raw: str | None) -> datetime | None:
    text = _clean_text(raw)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%m/%d/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _chamber_for_location(raw: str | None) -> Chamber | None:
    text = (_clean_text(raw) or "").lower()
    if text == "house":
        return Chamber.LOWER
    if text == "senate":
        return Chamber.UPPER
    return None


def _chamber_for_action(text: str) -> Chamber | None:
    normalized = text.strip().lower()
    if normalized.startswith("h ") or normalized.startswith("house:"):
        return Chamber.LOWER
    if normalized.startswith("s ") or normalized.startswith("senate:"):
        return Chamber.UPPER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("SF") else Chamber.LOWER


def _year(session: Session) -> int:
    return session.start_date.year if session.start_date is not None else datetime.now(tz=MT).year


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
