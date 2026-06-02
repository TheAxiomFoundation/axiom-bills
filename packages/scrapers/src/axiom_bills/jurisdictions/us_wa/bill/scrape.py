"""Washington bill scraper.

Washington publishes official XML web services at wslwebservices.leg.wa.gov.
This scraper uses HTTP GET endpoints for the biennium bill list, bill
metadata, sponsors, status changes, and bill-text documents.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET
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

ROOT = "https://wslwebservices.leg.wa.gov"
SUMMARY_ROOT = "https://apps.leg.wa.gov/billsummary"
PT = ZoneInfo("America/Los_Angeles")


class WashingtonScraper(BillScraper):
    jurisdiction = "us-wa"
    source_name = "wslwebservices.leg.wa.gov official XML web services"
    min_interval_per_host = 0.1

    def __init__(self, *, biennium: str | None = None, limit: int | None = None) -> None:
        super().__init__(limit=limit)
        self.biennium = biennium or _current_biennium()

    def scrape(self) -> ScrapeResult:
        session = session_from_biennium(self.biennium)
        year = int(self.biennium.split("-", 1)[0]) + 1
        rows = parse_legislation_info(
            self.http.get(f"{ROOT}/LegislationService.asmx/GetLegislationByYear?year={year}").text
        )
        rows = _dedupe_info(rows)
        rows.sort(key=lambda row: _number_sort_key(_canonical_number(row)))
        if self.limit is not None:
            rows = rows[:self.limit]

        bills: list[Bill] = []
        for row in rows:
            bill_number = _text(row.get("BillNumber"))
            detail_rows = parse_legislation(
                self.http.get(_url("LegislationService.asmx/GetLegislation", biennium=self.biennium, billNumber=bill_number)).text
            )
            detail = _preferred_legislation(detail_rows) or row
            bill_id = _canonical_number(detail)
            sponsors = parse_sponsors(
                self.http.get(_url("LegislationService.asmx/GetSponsors", biennium=self.biennium, billId=bill_id)).text
            )
            actions = parse_actions(self.http.get(_url(
                "LegislationService.asmx/GetLegislativeStatusChangesByBillNumber",
                biennium=self.biennium,
                billNumber=bill_number,
                beginDate=f"{self.biennium[:4]}-01-01",
                endDate=f"20{self.biennium[-2:]}-12-31",
            )).text)
            versions = parse_versions(self.http.get(_url(
                "LegislativeDocumentService.asmx/GetDocuments",
                biennium=self.biennium,
                namedLike=bill_number,
            )).text)
            bills.append(parse_bill(detail, sponsors=sponsors, actions=actions, versions=versions, session=session))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)


def session_from_biennium(biennium: str) -> Session:
    start_year = int(biennium.split("-", 1)[0])
    end_year = int(f"20{biennium[-2:]}")
    return Session(
        name=f"{start_year}-{end_year} Washington Regular Session",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=biennium == _current_biennium(),
    )


def parse_bill(
    raw: dict[str, Any],
    *,
    sponsors: list[Sponsor],
    actions: list[BillAction],
    versions: list[BillVersion],
    session: Session,
) -> Bill:
    title = _text(raw.get("LongDescription")) or _text(raw.get("ShortDescription")) or _canonical_number(raw)
    summary = _text(raw.get("LegalTitle")) or title
    return Bill(
        jurisdiction=WashingtonScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber(raw),
        number=_canonical_number(raw),
        title=title,
        summary=summary,
        subjects=[],
        sponsors=sponsors,
        source_url=f"{SUMMARY_ROOT}?BillNumber={_text(raw.get('BillNumber'))}&Year={raw.get('Biennium', '')[:4]}",
        actions=actions,
        versions=versions,
        kind=classify_kind(" ".join([title, summary, str(raw.get("Appropriations") or "")])),
    )


def parse_legislation_info(xml: str) -> list[dict[str, Any]]:
    return [_element_dict(node) for node in _nodes(xml, "LegislationInfo")]


def parse_legislation(xml: str) -> list[dict[str, Any]]:
    return [_element_dict(node) for node in _nodes(xml, "Legislation")]


def parse_sponsors(xml: str) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for node in _nodes(xml, "Sponsor"):
        row = _element_dict(node)
        first = _text(row.get("FirstName"))
        last = _text(row.get("LastName"))
        long_name = _text(row.get("LongName"))
        name = f"{first} {last}".strip() or long_name or _text(row.get("Name"))
        if not name:
            continue
        sponsors.append(Sponsor(
            name=name,
            role=_text(row.get("Type")).lower() if row.get("Type") else None,
        ))
    sponsors.sort(key=lambda sponsor: 0 if sponsor.role == "primary" else 1)
    return sponsors


def parse_actions(xml: str) -> list[BillAction]:
    actions: list[BillAction] = []
    seen: set[tuple[str, datetime | None, str]] = set()
    for node in _nodes(xml, "LegislativeStatus"):
        row = _element_dict(node)
        occurred_at = _parse_datetime(row.get("ActionDate"))
        text = _text(row.get("HistoryLine"))
        if occurred_at is None or not text:
            continue
        key = (_text(row.get("BillId")), occurred_at, text)
        if key in seen:
            continue
        seen.add(key)
        status_text = " ".join(part for part in (text, row.get("Status")) if part)
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_bill_id(_text(row.get("BillId"))),
            action_text=text,
            normalized_status=match_first(status_text, PATTERNS),
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(xml: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for node in _nodes(xml, "LegislativeDocument"):
        row = _element_dict(node)
        if _text(row.get("Class")) != "Bills":
            continue
        label = _text(row.get("ShortFriendlyName")) or _text(row.get("LongFriendlyName")) or _text(row.get("Name")) or "Bill text"
        for key, fmt in (("PdfUrl", "pdf"), ("HtmUrl", "html")):
            url = _text(row.get(key)).replace("http://", "https://")
            if not url or url in seen:
                continue
            seen.add(url)
            versions.append(BillVersion(label=label, source_url=url, format=fmt))
    return versions


def _dedupe_info(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_number: dict[str, dict[str, Any]] = {}
    for row in rows:
        number = _canonical_number(row)
        current = by_number.get(number)
        if current is None or _is_active(row) or not _is_active(current):
            by_number[number] = row
    return list(by_number.values())


def _preferred_legislation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = [row for row in rows if _is_active(row)]
    if active:
        return active[-1]
    return rows[0] if rows else None


def _is_active(row: dict[str, Any]) -> bool:
    return str(row.get("Active") or "").lower() == "true"


def _canonical_number(row: dict[str, Any]) -> str:
    bill_id = _text(row.get("BillId"))
    match = re.search(r"\b(HB|SB|HJR|SJR|HCR|SCR|HR|SR|HJM|SJM)\s+(\d+)\b", bill_id)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    agency = _text(row.get("OriginalAgency"))
    prefix = "SB" if agency == "Senate" else "HB"
    return f"{prefix} {_text(row.get('BillNumber'))}"


def _chamber(row: dict[str, Any]) -> Chamber:
    return _chamber_from_bill_id(_canonical_number(row))


def _chamber_from_bill_id(bill_id: str) -> Chamber:
    text = bill_id.upper()
    if text.startswith(("SB", "SR")):
        return Chamber.UPPER
    if text.startswith(("HB", "HR")):
        return Chamber.LOWER
    return Chamber.JOINT


def _parse_datetime(raw: object) -> datetime | None:
    text = _text(raw)
    if not text or text.startswith("0001-"):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=PT)
        except ValueError:
            continue
    return None


def _nodes(xml: str, name: str) -> list[ET.Element]:
    root = ET.fromstring(xml)
    return [node for node in root.iter() if _local_name(node.tag) == name]


def _element_dict(node: ET.Element) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for child in node:
        name = _local_name(child.tag)
        if list(child):
            out[name] = _element_dict(child)
        else:
            out[name] = _text(child.text)
    return out


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return ""
    return re.sub(r"\s+", " ", str(raw)).strip()


def _number_sort_key(number: str) -> tuple[int, int, str]:
    prefix, _, digits = number.partition(" ")
    order = {
        "HB": 0,
        "SB": 1,
        "HJR": 2,
        "SJR": 3,
        "HCR": 4,
        "SCR": 5,
        "HR": 6,
        "SR": 7,
        "HJM": 8,
        "SJM": 9,
    }.get(prefix, 10)
    return order, int(digits) if digits.isdigit() else 0, number


def _url(path: str, **params: str) -> str:
    return f"{ROOT}/{path}?{urlencode(params, quote_via=quote)}"


def _current_biennium() -> str:
    year = datetime.now(tz=PT).year
    start_year = year if year % 2 == 1 else year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"
