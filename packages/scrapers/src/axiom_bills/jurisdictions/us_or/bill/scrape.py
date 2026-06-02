"""Oregon bill scraper.

Oregon publishes OLIS legislative data through a public OData API. The
Measures table has bill metadata, with linked tables for history actions,
sponsors, and measure documents.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from urllib.parse import urlencode
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

ROOT = "https://olis.oregonlegislature.gov"
ODATA = "https://api.oregonlegislature.gov/odata/odataservice.svc"
PT = ZoneInfo("America/Los_Angeles")


class OregonScraper(BillScraper):
    jurisdiction = "us-or"
    source_name = "Oregon OLIS OData API"
    min_interval_per_host = 0.3

    def __init__(self, *, session_key: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.session_key = session_key

    def scrape(self) -> ScrapeResult:
        session_row = self._session_row(self.session_key)
        session_key = session_row["SessionKey"]
        session = parse_session(session_row)
        measures = self._odata_all(
            "Measures",
            filters=f"SessionKey eq '{session_key}'",
            order_by="MeasurePrefix,MeasureNumber",
        )
        if self.limit is not None:
            measures = measures[:self.limit]

        actions, sponsors, documents = self._related_rows(session_key, measures)
        bills = [
            parse_measure(
                row,
                session.name,
                actions[_key(row)],
                sponsors[_key(row)],
                documents[_key(row)],
            )
            for row in measures
        ]
        bills = [bill for bill in bills if bill is not None]
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _session_row(self, session_key: str | None) -> dict:
        if session_key:
            rows = self._odata_all("LegislativeSessions", filters=f"SessionKey eq '{session_key}'")
            if rows:
                return rows[0]
        rows = self._odata_all("LegislativeSessions")
        today = datetime.now(tz=PT).date()
        real_sessions = [
            row for row in rows
            if _parse_date(row.get("BeginDate")) is not None
            and _parse_date(row.get("BeginDate")) <= today
            and "mock" not in str(row.get("SessionName") or "").lower()
            and "interim" not in str(row.get("SessionName") or "").lower()
        ]
        real_sessions.sort(key=lambda row: _parse_date(row.get("BeginDate")) or date.min)
        return real_sessions[-1]

    def _related_rows(self, session_key: str, measures: list[dict]):
        if self.limit is None:
            action_rows = self._odata_all("MeasureHistoryActions", filters=f"SessionKey eq '{session_key}'")
            sponsor_rows = self._odata_all("MeasureSponsors", filters=f"SessionKey eq '{session_key}'")
            document_rows = self._odata_all("MeasureDocuments", filters=f"SessionKey eq '{session_key}'")
        else:
            action_rows = []
            sponsor_rows = []
            document_rows = []
            for row in measures:
                filters = _bill_filter(session_key, row["MeasurePrefix"], row["MeasureNumber"])
                action_rows.extend(self._odata_all("MeasureHistoryActions", filters=filters))
                sponsor_rows.extend(self._odata_all("MeasureSponsors", filters=filters))
                document_rows.extend(self._odata_all("MeasureDocuments", filters=filters))

        return (
            _group_by_bill(action_rows),
            _group_by_bill(sponsor_rows),
            _group_by_bill(document_rows),
        )

    def _odata_all(
        self,
        entity: str,
        *,
        filters: str | None = None,
        order_by: str | None = None,
        page_size: int = 500,
    ) -> list[dict]:
        rows: list[dict] = []
        skip = 0
        while True:
            params = {"$format": "json", "$top": str(page_size), "$skip": str(skip)}
            if filters:
                params["$filter"] = filters
            if order_by:
                params["$orderby"] = order_by
            payload = self.http.get_json(f"{ODATA}/{entity}?{urlencode(params)}")
            page = payload.get("value") or []
            rows.extend(page)
            if len(page) < page_size:
                return rows
            skip += page_size


def parse_session(row: dict) -> Session:
    return Session(
        name=str(row["SessionName"]),
        start_date=_parse_date(row.get("BeginDate")),
        end_date=_parse_date(row.get("EndDate")),
        is_current=bool(row.get("DefaultSession")) or _parse_date(row.get("EndDate")) is None,
    )


def parse_measure(
    row: dict,
    session_name: str,
    action_rows: list[dict],
    sponsor_rows: list[dict],
    document_rows: list[dict],
) -> Bill | None:
    prefix = str(row.get("MeasurePrefix") or "").upper()
    number = row.get("MeasureNumber")
    if not prefix or number is None:
        return None
    bill_number = f"{prefix}{number}"
    title = _clean_text(row.get("RelatingTo") or row.get("CatchLine") or bill_number)
    summary = _clean_text(row.get("MeasureSummary"))
    actions = [_parse_action(action, bill_number) for action in action_rows]
    actions = [action for action in actions if action is not None]
    if row.get("CurrentLocation"):
        when = _parse_datetime(row.get("ModifiedDate")) or datetime.now(tz=PT)
        actions.append(BillAction(
            occurred_at=when,
            chamber=_chamber_for_number(bill_number),
            action_text=str(row["CurrentLocation"]),
            normalized_status=match_first(str(row["CurrentLocation"]), PATTERNS),
        ))

    return Bill(
        jurisdiction=OregonScraper.jurisdiction,
        session_name=session_name,
        chamber=_chamber_for_number(bill_number),
        number=bill_number,
        title=title,
        summary=summary,
        subjects=[],
        sponsors=_sponsors(sponsor_rows),
        source_url=f"{ROOT}/liz/{row['SessionKey']}/Measures/Overview/{bill_number}",
        actions=actions,
        versions=_versions(document_rows),
        kind=classify_kind(title),
    )


def _parse_action(row: dict, bill_number: str) -> BillAction | None:
    action_text = _clean_text(row.get("ActionText"))
    occurred_at = _parse_datetime(row.get("ActionDate"))
    if not action_text or occurred_at is None:
        return None
    return BillAction(
        occurred_at=occurred_at,
        chamber=_chamber(row.get("Chamber")) or _chamber_for_number(bill_number),
        action_text=action_text,
        normalized_status=match_first(action_text, PATTERNS),
    )


def _sponsors(rows: list[dict]) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for row in sorted(rows, key=lambda r: int(r.get("PrintOrder") or 999)):
        name = row.get("LegislatoreCode") or row.get("CommitteeCode") or row.get("PresessionFiledMessage")
        if not name:
            continue
        role = str(row.get("SponsorLevel") or row.get("SponsorType") or "sponsor").lower()
        sponsors.append(Sponsor(name=str(name), role=role))
    return sponsors


def _versions(rows: list[dict]) -> list[BillVersion]:
    versions: list[BillVersion] = []
    for row in sorted(rows, key=lambda r: str(r.get("CreatedDate") or "")):
        url = row.get("DocumentUrl")
        label = row.get("VersionDescription")
        if not url or not label:
            continue
        versions.append(BillVersion(label=str(label), source_url=str(url), format="html"))
    return versions


def _group_by_bill(rows: list[dict]) -> dict[tuple[str, int], list[dict]]:
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        key = _key(row)
        if key is not None:
            grouped[key].append(row)
    return grouped


def _key(row: dict) -> tuple[str, int] | None:
    prefix = row.get("MeasurePrefix")
    number = row.get("MeasureNumber")
    if prefix is None or number is None:
        return None
    return (str(prefix).upper(), int(number))


def _bill_filter(session_key: str, prefix: str, number: int) -> str:
    return (
        f"SessionKey eq '{session_key}' and "
        f"MeasurePrefix eq '{prefix}' and MeasureNumber eq {number}"
    )


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
        return datetime.fromisoformat(str(raw)).replace(tzinfo=PT)
    except ValueError:
        return None


def _parse_date(raw) -> date | None:
    parsed = _parse_datetime(raw)
    return parsed.date() if parsed else None


def _clean_text(raw) -> str | None:
    if raw is None:
        return None
    return " ".join(str(raw).split())
