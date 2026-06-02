"""Arizona bill scraper.

Arizona publishes official Bill Status Inquiry JSON APIs under
apps.azleg.gov/api for sessions, bill lists, actions, sponsors,
documents, keywords, and sections affected.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from axiom_bills._common.base import BillScraper
from axiom_bills._common.http import RateLimitedClient
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

ROOT = "https://apps.azleg.gov"
AZLEG_ROOT = "https://www.azleg.gov"


class ArizonaScraper(BillScraper):
    jurisdiction = "us-az"
    source_name = "apps.azleg.gov official Bill Status Inquiry API"
    min_interval_per_host = 0.2

    def __init__(self, *, session_id: int | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.http.close()
        self.http = RateLimitedClient(
            min_interval_per_host=self.min_interval_per_host,
            timeout=120.0,
        )
        self.session_id = session_id

    def scrape(self) -> ScrapeResult:
        session_row = self._session_row()
        session = session_from_row(session_row)
        if self.limit is not None:
            rows = self._limited_bill_rows(session_row, self.limit)
            bills = [self._bill_from_row(row, session=session) for row in rows]
            return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=[bill for bill in bills if bill is not None])
        payload = self.http.get_json(f"{ROOT}/api/Bill/", params={"sessionId": session_row["SessionId"]})
        rows = payload.get("ListItems") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Arizona bill list response was not a list")
        rows = sorted((row for row in rows if isinstance(row, dict)), key=lambda row: _number_sort_key(_clean_text(row.get("Number") or row.get("BillNumber")) or ""))
        if self.limit is not None:
            rows = rows[:self.limit]
        bills = [self._bill_from_row(row, session=session) for row in rows]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=[bill for bill in bills if bill is not None])

    def _session_row(self) -> dict[str, Any]:
        rows = self.http.get_json(f"{ROOT}/api/Session/")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Arizona sessions response was empty")
        if self.session_id is None:
            return rows[0]
        for row in rows:
            if isinstance(row, dict) and row.get("SessionId") == self.session_id:
                return row
        raise ValueError(f"Arizona session {self.session_id} was not found")

    def _limited_bill_rows(self, session_row: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        probes = (("HB", 2001, "H"), ("SB", 1001, "S"))
        for prefix, start, body in probes:
            misses = 0
            number = start
            while len(rows) < limit and misses < 100:
                bill_number = f"{prefix}{number}"
                row = self.http.get_json(
                    f"{ROOT}/api/Bill/",
                    params={
                        "billNumber": bill_number,
                        "sessionId": session_row["SessionId"],
                        "legislativeBody": body,
                    },
                )
                if isinstance(row, dict) and row.get("BillId"):
                    rows.append(row)
                    misses = 0
                else:
                    misses += 1
                number += 1
            if len(rows) >= limit:
                break
        rows.sort(key=lambda row: _number_sort_key(_clean_text(row.get("Number") or row.get("BillNumber")) or ""))
        return rows

    def _bill_from_row(self, row: dict[str, Any], *, session: Session) -> Bill | None:
        number = _clean_text(row.get("Number") or row.get("BillNumber"))
        bill_id = row.get("BillId")
        if not number or not bill_id:
            return None
        overview = self.http.get_json(f"{ROOT}/api/BillStatusOverview/", params={"billNumber": number, "sessionId": row.get("SessionId")})
        sponsors = self.http.get_json(f"{ROOT}/api/BillSponsor/", params={"id": bill_id})
        doc_groups = self.http.get_json(f"{ROOT}/api/DocType/", params={"billStatusId": bill_id})
        title = _clean_text(row.get("NOWTitle") or row.get("ShortTitle") or row.get("Description")) or number
        return Bill(
            jurisdiction=self.jurisdiction,
            session_name=session.name,
            chamber=_chamber_for_number(number),
            number=number,
            title=title,
            summary=_clean_text(row.get("Description")) or title,
            subjects=[],
            sponsors=parse_sponsors(sponsors),
            source_url=f"{ROOT}/BillStatus/BillOverview/{bill_id}",
            actions=parse_actions(overview, row=row),
            versions=parse_versions(doc_groups),
            kind=classify_kind(title),
        )


def session_from_row(row: dict[str, Any]) -> Session:
    name = _clean_text(row.get("Name")) or "Arizona Legislature"
    year = _year_from_name(name)
    return Session(
        name=name,
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=True,
    )


def parse_actions(rows: Any, *, row: dict[str, Any] | None = None) -> list[BillAction]:
    actions: list[BillAction] = []
    if isinstance(rows, list):
        for action_row in rows:
            if not isinstance(action_row, dict):
                continue
            action = _action_from_overview(action_row)
            if action is not None:
                actions.append(action)
    if row:
        actions.extend(_bill_row_actions(row))
    actions.sort(key=lambda action: action.occurred_at)
    return _dedupe_actions(actions)


def parse_sponsors(rows: Any) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    seen: set[tuple[str, str | None]] = set()
    if not isinstance(rows, list):
        return sponsors
    for row in rows:
        if not isinstance(row, dict):
            continue
        legislator = row.get("Legislator") if isinstance(row.get("Legislator"), dict) else {}
        name = _clean_text(legislator.get("FullName") or row.get("PrimarySponsorName"))
        if not name:
            continue
        role = _sponsor_role(row.get("SponsorType"))
        key = (name, role)
        if key in seen:
            continue
        seen.add(key)
        sponsors.append(Sponsor(
            name=name,
            role=role,
            party=_clean_text(legislator.get("Party")),
        ))
    return sponsors


def parse_versions(groups: Any) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    if not isinstance(groups, list):
        return versions
    for group in groups:
        if not isinstance(group, dict) or group.get("DocumentGroupCode") != "BillDocuments":
            continue
        documents = group.get("Documents") if isinstance(group.get("Documents"), list) else []
        for document in documents:
            if not isinstance(document, dict):
                continue
            label = _version_label(document.get("DocumentName"))
            for raw_url in (document.get("HtmlPath"), document.get("PdfPath")):
                url = _document_url(raw_url)
                if not url or url in seen:
                    continue
                seen.add(url)
                versions.append(BillVersion(label=label, source_url=url, format=_format_for_url(url)))
                break
    return versions


def _action_from_overview(row: dict[str, Any]) -> BillAction | None:
    occurred_at = _parse_datetime(row.get("SortedDate"))
    if occurred_at is None:
        return None
    date_type = _clean_text(row.get("DateType")) or ""
    text = _action_text(row, date_type)
    if not text:
        return None
    return BillAction(
        occurred_at=occurred_at,
        chamber=_chamber(row.get("Body")),
        action_text=text,
        normalized_status=match_first(text, PATTERNS),
    )


def _action_text(row: dict[str, Any], date_type: str) -> str | None:
    action = _clean_text(row.get("Action"))
    comments = _clean_text(row.get("Comments"))
    upper = date_type.upper()
    if upper == "FIRST":
        return "First reading"
    if upper == "SECOND":
        return "Second reading"
    if upper == "TRANSMIT":
        return f"Transmitted to {_body_name(row.get('Body'))}"
    if upper == "_STANDING":
        committee = _clean_text(row.get("col6"))
        result = _clean_text(row.get("col7") or row.get("col4"))
        vote = _clean_text(row.get("col5"))
        return _join_parts("Standing committee", committee, result, vote)
    if upper in {"COW", "ADCOW", "SCOW", "MOTION", "MOTIONADCOW"}:
        return _join_parts("Committee of the whole", action, _clean_text(row.get("col7")), comments)
    if upper in {"THIRD", "FINAL", "CONCUR"}:
        return _join_parts(f"{date_type.title()} reading", action or _clean_text(row.get("col11")), _vote_text(row))
    if upper in {"MAJCAUCUS", "MINCAUCUS"}:
        return f"{'Majority' if upper == 'MAJCAUCUS' else 'Minority'} caucus"
    if upper == "CONSENT":
        return "Consent calendar"
    return _join_parts(date_type.replace("_", " ").title(), action, comments)


def _bill_row_actions(row: dict[str, Any]) -> list[BillAction]:
    actions: list[BillAction] = []
    for label, date_value, text in [
        ("prefiled", row.get("PreFileDate"), "Prefiled"),
        ("introduced", row.get("DateIntroduced") or row.get("IntroducedDate"), "Introduced"),
        ("governor", row.get("GovernorActionDate"), _clean_text(row.get("GovernorAction"))),
    ]:
        occurred_at = _parse_datetime(date_value)
        if occurred_at is None or not text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=Chamber.EXECUTIVE if label == "governor" else _chamber_for_number(_clean_text(row.get("Number") or row.get("BillNumber")) or ""),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
        ))
    return actions


def _dedupe_actions(actions: list[BillAction]) -> list[BillAction]:
    deduped: list[BillAction] = []
    seen: set[tuple[datetime, str, Chamber | None]] = set()
    for action in actions:
        key = (action.occurred_at, action.action_text, action.chamber)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _document_url(raw: Any) -> str | None:
    text = _clean_text(raw)
    if not text:
        return None
    if text.startswith("/"):
        return urljoin(ROOT, text)
    return text


def _version_label(raw: Any) -> str:
    text = (_clean_text(raw) or "document").lower()
    if "introduced" in text:
        return "introduced"
    if "engrossed" in text:
        return "engrossed"
    if "chapter" in text:
        return "chaptered"
    return text


def _sponsor_role(raw: Any) -> str:
    text = (_clean_text(raw) or "").lower()
    if "prime" in text:
        return "primary"
    if "co-sponsor" in text or "cosponsor" in text:
        return "cosponsor"
    return "sponsor"


def _vote_text(row: dict[str, Any]) -> str | None:
    votes = [_clean_text(row.get(key)) for key in ("col1", "col2", "col3", "col4")]
    if not any(votes):
        return None
    return "-".join(vote or "0" for vote in votes)


def _join_parts(*parts: str | None) -> str:
    return "; ".join(part for part in parts if part)


def _body_name(raw: Any) -> str:
    chamber = _chamber(raw)
    if chamber == Chamber.LOWER:
        return "House"
    if chamber == Chamber.UPPER:
        return "Senate"
    if chamber == Chamber.EXECUTIVE:
        return "Governor"
    return _clean_text(raw) or "other body"


def _chamber(raw: Any) -> Chamber | None:
    text = (_clean_text(raw) or "").upper()
    if text.startswith("H"):
        return Chamber.LOWER
    if text.startswith("S"):
        return Chamber.UPPER
    if text.startswith("G"):
        return Chamber.EXECUTIVE
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw: Any) -> datetime | None:
    text = _clean_text(raw)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_for_url(url: str) -> str:
    lower = url.lower()
    if ".pdf" in lower or "getdocumentpdf" in lower:
        return "pdf"
    if ".htm" in lower or ".html" in lower:
        return "html"
    if ".docx" in lower:
        return "docx"
    return "txt"


def _year_from_name(name: str) -> int:
    for token in name.split():
        if token.isdigit() and len(token) == 4:
            return int(token)
    return datetime.now().year


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _clean_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
