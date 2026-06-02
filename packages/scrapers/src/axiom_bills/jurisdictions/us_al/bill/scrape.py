"""Alabama bill scraper.

Alabama publishes official bill metadata, text links, and history actions
through the ALISON GraphQL endpoint under alison.legislature.state.al.us.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

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

ROOT = "https://alison.legislature.state.al.us"
GRAPHQL_URL = f"{ROOT}/graphql"

SESSION_QUERY = """
query sessionForProvider {
  currentSession: session(where: { current: { eq: true } }) {
    name
    abbreviation
    startDate
    endDate
  }
}
"""

BILLS_QUERY = """
query bills($sessionAbbreviation: String, $limit: Int, $offset: Int) {
  instruments(
    where: [{ sessionAbbreviation: { eq: $sessionAbbreviation }, instrumentType: { eq: B } }]
    order: ["instrumentNbr", "ASC"]
    limit: $limit
    offset: $offset
  ) {
    count
    data {
      id
      sessionAbbreviation
      sessionYear
      sessionName
      instrumentNbr
      instrumentType
      sponsor
      body
      subject
      shortTitle
      assignedCommittee
      allCommittees
      prefiledDate
      firstReadDate
      currentStatus
      lastAction
      lastActionDate
      actSummary
      viewEnacted
      actNbr
      companionInstrumentNbr
      effectiveDateCertain
      effectiveDateOther
    }
  }
}
"""

DETAIL_QUERY = """
query billModal($sessionAbbreviation: String, $instrumentNbr: String, $instrumentType: InstrumentType) {
  instrument: instrument(
    where: {
      sessionAbbreviation: { eq: $sessionAbbreviation }
      instrumentNbr: { eq: $instrumentNbr }
      instrumentType: { eq: $instrumentType }
    }
  ) {
    id
    instrumentNbr
    sessionName
    currentStatus
    shortTitle
    introducedFileUrl
    engrossedFileUrl
    enrolledFileUrl
    reenrolledFileUrl
    viewEnacted
    actNbr
  }
  histories: instrumentHistories(
    where: {
      sessionAbbreviation: { eq: $sessionAbbreviation }
      instrumentNbr: { eq: $instrumentNbr }
    }
  ) {
    data {
      instrumentNbr
      sessionName
      sessionYear
      calendarDate
      body
      matter
      amdSub
      amdSubFileUrl
      committee
      voteType
      voteTitle
      rollCallNbr
      yeas
      nays
    }
  }
}
"""


class AlabamaScraper(BillScraper):
    jurisdiction = "us-al"
    source_name = "alison.legislature.state.al.us official GraphQL"
    min_interval_per_host = 0.2

    def __init__(self, *, session_abbreviation: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_abbreviation = session_abbreviation

    def scrape(self) -> ScrapeResult:
        session_data = self._session_data()
        session_abbreviation = self.session_abbreviation or session_data["abbreviation"]
        session = session_from_row(session_data)
        rows = self._bill_rows(session_abbreviation)
        if self.limit is not None:
            rows = rows[:self.limit]
        bills: list[Bill] = []
        for row in rows:
            number = _clean_text(row.get("instrumentNbr"))
            if not number:
                continue
            detail = self._graphql(DETAIL_QUERY, {
                "sessionAbbreviation": session_abbreviation,
                "instrumentNbr": number,
                "instrumentType": "B",
            })
            bill = parse_bill(row, detail, session=session)
            if bill is not None:
                bills.append(bill)
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session_data(self) -> dict[str, Any]:
        data = self._graphql(SESSION_QUERY, {})
        session = data.get("currentSession")
        if not isinstance(session, dict):
            raise ValueError("ALISON currentSession was missing")
        return session

    def _bill_rows(self, session_abbreviation: str) -> list[dict[str, Any]]:
        limit = self.limit or 250
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self._graphql(BILLS_QUERY, {
                "sessionAbbreviation": session_abbreviation,
                "limit": limit,
                "offset": offset,
            })
            instruments = data.get("instruments") or {}
            batch = instruments.get("data") or []
            rows.extend(row for row in batch if isinstance(row, dict))
            count = int(instruments.get("count") or len(rows))
            if self.limit is not None or not batch or len(rows) >= count:
                break
            offset += len(batch)
        return rows

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(GRAPHQL_URL, json={"query": query, "variables": variables})
        payload = response.json()
        if payload.get("errors"):
            raise ValueError(f"ALISON GraphQL errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("ALISON GraphQL response did not contain data")
        return data


def session_from_row(row: dict[str, Any]) -> Session:
    name = _clean_text(row.get("name")) or "Alabama Regular Session"
    start = _parse_datetime(row.get("startDate"))
    end = _parse_datetime(row.get("endDate"))
    return Session(
        name=name,
        start_date=start.date() if start else None,
        end_date=end.date() if end else None,
        is_current=True,
    )


def parse_bill(summary: dict[str, Any], detail_data: dict[str, Any], *, session: Session) -> Bill | None:
    detail = detail_data.get("instrument") if isinstance(detail_data.get("instrument"), dict) else {}
    number = _clean_text(detail.get("instrumentNbr") or summary.get("instrumentNbr"))
    if not number:
        return None
    title = _clean_text(detail.get("shortTitle") or summary.get("shortTitle")) or number
    histories = ((detail_data.get("histories") or {}).get("data") or [])
    actions = _actions(histories, summary, number)
    if not actions:
        actions = _fallback_actions(summary, number)
    return Bill(
        jurisdiction=AlabamaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(summary.get("body")) or _chamber_for_number(number),
        number=number,
        title=title,
        summary=_clean_text(summary.get("actSummary")) or title,
        subjects=_subjects(summary),
        sponsors=_sponsors(summary),
        source_url=f"{ROOT}/bill-search?tab=1&search={number}",
        actions=actions,
        versions=_versions(detail),
        kind=classify_kind(title),
    )


def _actions(rows: list[dict[str, Any]], summary: dict[str, Any], number: str) -> list[BillAction]:
    actions: list[BillAction] = []
    for row in rows:
        text = _history_text(row)
        occurred_at = _parse_action_date(row.get("calendarDate"))
        if not text or occurred_at is None:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber(row.get("body")) or _chamber_for_number(number),
            action_text=text,
            normalized_status=match_first(text, PATTERNS),
            source_url=_clean_text(row.get("amdSubFileUrl")),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    if not actions:
        return _fallback_actions(summary, number)
    return actions


def _history_text(row: dict[str, Any]) -> str | None:
    parts = [_clean_text(row.get("matter"))]
    committee = _clean_text(row.get("committee"))
    if committee:
        parts.append(f"Committee: {committee}")
    amd_sub = _clean_text(row.get("amdSub"))
    if amd_sub:
        parts.append(f"Amendment/Substitute: {amd_sub}")
    roll_call = row.get("rollCallNbr")
    if roll_call:
        vote = f"Roll Call {roll_call}"
        if row.get("yeas") is not None and row.get("nays") is not None:
            vote += f" ({row['yeas']}-{row['nays']})"
        parts.append(vote)
    return "; ".join(part for part in parts if part)


def _fallback_actions(summary: dict[str, Any], number: str) -> list[BillAction]:
    text = _clean_text(summary.get("lastAction") or summary.get("currentStatus"))
    occurred_at = _parse_action_date(summary.get("lastActionDate") or summary.get("firstReadDate") or summary.get("prefiledDate"))
    if not text or occurred_at is None:
        return []
    return [BillAction(
        occurred_at=occurred_at,
        chamber=_chamber(summary.get("body")) or _chamber_for_number(number),
        action_text=text,
        normalized_status=match_first(text, PATTERNS),
    )]


def _versions(detail: dict[str, Any]) -> list[BillVersion]:
    labels = [
        ("introduced", detail.get("introducedFileUrl")),
        ("engrossed", detail.get("engrossedFileUrl")),
        ("enrolled", detail.get("enrolledFileUrl")),
        ("reenrolled", detail.get("reenrolledFileUrl")),
        ("enacted", detail.get("viewEnacted")),
    ]
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for label, raw_url in labels:
        source_url = _clean_text(raw_url)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(label=label, source_url=source_url, format=_format_for_url(source_url)))
    return versions


def _subjects(row: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for value in (row.get("subject"), row.get("assignedCommittee")):
        text = _clean_text(value)
        if text and text not in subjects:
            subjects.append(text)
    committees = row.get("allCommittees")
    if isinstance(committees, list):
        for committee in committees:
            text = _clean_text(committee)
            if text and text not in subjects:
                subjects.append(text)
    return subjects


def _sponsors(row: dict[str, Any]) -> list[Sponsor]:
    name = _clean_text(row.get("sponsor"))
    return [Sponsor(name=name, role="sponsor")] if name else []


def _chamber(raw: Any) -> Chamber | None:
    text = _clean_text(raw)
    if text == "House":
        return Chamber.LOWER
    if text == "Senate":
        return Chamber.UPPER
    return None


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.UPPER if number.upper().startswith("S") else Chamber.LOWER


def _parse_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_action_date(raw: Any) -> datetime | None:
    parsed = _parse_datetime(raw)
    if parsed is not None:
        return parsed
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d")
    except ValueError:
        return None


def _format_for_url(url: str) -> str:
    lower = url.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".html") or "actdetail" in lower:
        return "html"
    return "txt"


def _number_sort_key(number: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in number if ch.isalpha())
    digits = "".join(ch for ch in number if ch.isdigit())
    return (prefix, int(digits) if digits else 0, number)


def _clean_text(raw: Any) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).replace("\xa0", " ").split())
    return text or None
