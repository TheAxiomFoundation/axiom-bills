"""Pennsylvania bill scraper.

Pennsylvania publishes an official current-session Bill History ZIP
archive containing XML for all bills and resolutions. The archive is
updated hourly and includes sponsors, actions, amendments, and bill text
links.
"""
from __future__ import annotations

import re
import zipfile
from datetime import date, datetime
from io import BytesIO
from xml.etree import ElementTree as ET

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

ROOT = "https://www.palegis.us"
DATA_PAGE = f"{ROOT}/data"
BILL_HISTORY_URL = f"{ROOT}/data/file?documentType=BillHistoryData&session=2025_0"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class PennsylvaniaScraper(BillScraper):
    jurisdiction = "us-pa"
    source_name = "palegis.us official Pennsylvania General Assembly bill history XML"
    min_interval_per_host = 0.2

    def __init__(self, *, limit: int | None = None) -> None:
        self.limit = limit
        self.http = RateLimitedClient(
            min_interval_per_host=self.min_interval_per_host,
            headers={"User-Agent": USER_AGENT},
        )

    def scrape(self) -> ScrapeResult:
        xml_bytes = self._current_xml()
        session = session_from_xml(xml_bytes)
        bills: list[Bill] = []
        for bill_elem in bill_elements(xml_bytes):
            bills.append(parse_bill(bill_elem, session=session))
            if self.limit is not None and len(bills) >= self.limit:
                break
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _current_xml(self) -> bytes:
        response = self.http.get(BILL_HISTORY_URL, headers={"Referer": DATA_PAGE})
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                raise ValueError("Pennsylvania bill history archive was empty")
            return archive.read(names[0])


def session_from_xml(xml_bytes: bytes) -> Session:
    root = ET.fromstring(xml_bytes)
    session_elem = root.find("session")
    year = int(_text(session_elem, "year") or "2025")
    session_label = "Regular Session"
    start_year = year
    end_year = year + 1
    return Session(
        name=f"{start_year}-{end_year} Pennsylvania {session_label}",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_current=start_year <= datetime.now().year <= end_year,
    )


def bill_elements(xml_bytes: bytes) -> list[ET.Element]:
    root = ET.fromstring(xml_bytes)
    session_elem = root.find("session")
    return list(session_elem.findall("bill") if session_elem is not None else [])


def parse_bill(elem: ET.Element, *, session: Session) -> Bill:
    number = _bill_number(elem)
    title = _clean_text(_text(elem, "shortTitle")) or number
    return Bill(
        jurisdiction=PennsylvaniaScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_from_body(_text(elem, "body")),
        number=number,
        title=title,
        summary=title,
        subjects=[],
        sponsors=parse_sponsors(elem),
        source_url=_source_url(elem),
        actions=parse_actions(elem),
        versions=parse_versions(elem),
        kind=classify_kind(title),
    )


def parse_sponsors(elem: ET.Element) -> list[Sponsor]:
    sponsors: list[Sponsor] = []
    for sponsor_elem in elem.findall("./sponsors/sponsor"):
        name = _clean_text(sponsor_elem.text)
        if not name:
            continue
        role = "primary" if sponsor_elem.attrib.get("sequenceNumber") == "01" else "cosponsor"
        sponsors.append(Sponsor(
            name=name,
            role=role,
            party=_clean_text(sponsor_elem.attrib.get("party")) or None,
            district=_clean_text(sponsor_elem.attrib.get("districtNumber")) or None,
        ))
    return sponsors


def parse_actions(elem: ET.Element) -> list[BillAction]:
    actions: list[BillAction] = []
    source_url = _source_url(elem)
    for action_elem in elem.findall("./actionHistory/action"):
        action_text = _clean_text(_text(action_elem, "fullAction"))
        occurred_at = _parse_action_date(_text(action_elem, "date"))
        if occurred_at is None or not action_text:
            continue
        actions.append(BillAction(
            occurred_at=occurred_at,
            chamber=_chamber_from_body(action_elem.attrib.get("actionChamber")),
            action_text=action_text,
            normalized_status=match_first(action_text, PATTERNS),
            source_url=source_url,
        ))
    actions.sort(key=lambda action: action.occurred_at)
    return actions


def parse_versions(elem: ET.Element) -> list[BillVersion]:
    versions: list[BillVersion] = []
    seen: set[str] = set()
    for number_elem in elem.findall("./printersNumberHistory/number"):
        source_url = _clean_text(number_elem.attrib.get("billTextPdfUrl"))
        label = _clean_text(number_elem.text)
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        versions.append(BillVersion(label=f"PN {label}", source_url=source_url, format="pdf"))
    return versions


def _bill_number(elem: ET.Element) -> str:
    prefix = f"{_text(elem, 'body')}{_text(elem, 'type')}".upper()
    raw_number = _text(elem, "number")
    return f"{prefix} {int(raw_number)}" if raw_number.isdigit() else f"{prefix} {raw_number}".strip()


def _source_url(elem: ET.Element) -> str:
    year = _text(elem, "sessionYear") or "2025"
    compact = _bill_number(elem).replace(" ", "").lower()
    return f"{ROOT}/legislation/bills/{year}/{compact}"


def _chamber_from_body(body: str | None) -> Chamber:
    normalized = (body or "").upper()
    if normalized == "H":
        return Chamber.LOWER
    if normalized == "S":
        return Chamber.UPPER
    return Chamber.EXECUTIVE


def _parse_action_date(value: str) -> datetime | None:
    cleaned = _clean_text(value)
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return datetime.combine(parsed.date(), datetime.min.time())
        except ValueError:
            continue
    return None


def _text(elem: ET.Element | None, tag: str) -> str:
    if elem is None:
        return ""
    child = elem.find(tag)
    return _clean_text(child.text if child is not None else "")


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())
