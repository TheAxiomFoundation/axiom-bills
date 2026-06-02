"""New Mexico bill scraper.

New Mexico publishes a WebForms Daily Bill Locator and open session file
directories. The locator provides bill metadata and compact actions; the
directories provide official HTML/PDF bill text versions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

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

ROOT = "https://www.nmlegis.gov"
LOCATOR_PATH = "/Legislation/Legislation_List"


@dataclass(frozen=True)
class NewMexicoSession:
    year_code: str
    locator_id: str
    display: str
    directory_name: str


@dataclass(frozen=True)
class NewMexicoLocatorItem:
    number: str
    title: str
    sponsors: list[str]
    actions: str
    detail_url: str


class NewMexicoScraper(BillScraper):
    jurisdiction = "us-nm"
    source_name = "nmlegis.gov official New Mexico Daily Bill Locator"
    min_interval_per_host = 0.1

    def scrape(self) -> ScrapeResult:
        session_info, locator_html = self._current_locator_html()
        session = session_from_info(session_info)
        version_index = self._version_index(session_info.directory_name)
        bills: list[Bill] = []
        for item in parse_locator(locator_html):
            if self.limit is not None and len(bills) >= self.limit:
                break
            bills.append(parse_bill(item, session=session, versions=version_index.get(_file_base(item.number), [])))
        bills.sort(key=lambda bill: _number_sort_key(bill.number))
        return ScrapeResult(jurisdiction=self.jurisdiction, session=session, bills=bills)

    def _current_locator_html(self) -> tuple[NewMexicoSession, str]:
        locator_url = urljoin(ROOT, LOCATOR_PATH)
        response = self.http.get(locator_url)
        session_info = current_session_from_locator(response.text)
        form_data = form_payload(response.text)
        form_data["ctl00$MainContent$ddlSessionStart"] = session_info.locator_id
        form_data["ctl00$MainContent$ddlSessionEnd"] = session_info.locator_id
        form_data["ctl00$MainContent$ddlResultsPerPage"] = "2000"
        form_data["ctl00$MainContent$chkSearchBills"] = "on"
        form_data["ctl00$MainContent$chkSearchMemorials"] = "on"
        form_data["ctl00$MainContent$chkSearchResolutions"] = "on"
        form_data["ctl00$MainContent$btnSearch"] = "Go"
        return session_info, self.http.post(locator_url, data=form_data).text

    def _version_index(self, directory_name: str) -> dict[str, list[BillVersion]]:
        index: dict[str, list[BillVersion]] = {}
        for path in _session_directories(directory_name):
            html = self.http.get(urljoin(ROOT, path)).text
            for version in parse_directory_versions(html):
                index.setdefault(_file_base_from_url(version.source_url), []).append(version)
        for versions in index.values():
            versions.sort(key=lambda version: (version.label, version.format))
        return index


def current_session_from_locator(html: str) -> NewMexicoSession:
    tree = HTMLParser(html)
    option = tree.css_first("#MainContent_ddlSessionStart option")
    if option is None:
        return NewMexicoSession("26", "72", "2026 Regular", "26 Regular")
    display = _clean_text(option.text())
    year = display.split()[0]
    year_code = year[-2:]
    return NewMexicoSession(
        year_code=year_code,
        locator_id=_clean_text(option.attributes.get("value")),
        display=display,
        directory_name=f"{year_code} {' '.join(display.split()[1:])}",
    )


def form_payload(html: str) -> dict[str, str]:
    tree = HTMLParser(html)
    data: dict[str, str] = {}
    for node in tree.css("input"):
        name = node.attributes.get("name")
        if not name:
            continue
        input_type = (node.attributes.get("type") or "").lower()
        if input_type in {"checkbox", "radio"} and "checked" not in node.attributes:
            continue
        data[name] = node.attributes.get("value") or ""
    return data


def session_from_info(info: NewMexicoSession) -> Session:
    year = int("20" + info.year_code)
    return Session(
        name=f"{year} New Mexico {info.display.split(' ', 1)[1]} Session",
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        is_current=year == datetime.now().year,
    )


def parse_locator(html: str) -> list[NewMexicoLocatorItem]:
    tree = HTMLParser(html)
    table = tree.css_first("#MainContent_gridViewLegislation")
    if table is None:
        return []
    items: list[NewMexicoLocatorItem] = []
    for row in table.css("tr")[1:]:
        cells = row.css("td")
        if len(cells) < 5:
            continue
        link = cells[0].css_first("a[href*='Legislation?']")
        if link is None:
            continue
        number = _format_number(_clean_text(link.text()))
        title = _clean_text(cells[1].text())
        actions = _clean_text(cells[3].text())
        items.append(NewMexicoLocatorItem(
            number=number,
            title=title or number,
            sponsors=parse_sponsor_names(cells[2]),
            actions=actions,
            detail_url=urljoin(ROOT, link.attributes.get("href") or ""),
        ))
    return items


def parse_bill(
    item: NewMexicoLocatorItem,
    *,
    session: Session,
    versions: list[BillVersion] | None = None,
) -> Bill:
    return Bill(
        jurisdiction=NewMexicoScraper.jurisdiction,
        session_name=session.name,
        chamber=_chamber_for_number(item.number),
        number=item.number,
        title=item.title,
        summary=item.title,
        subjects=[],
        sponsors=[Sponsor(name=name, role="primary" if index == 0 else "cosponsor") for index, name in enumerate(item.sponsors)],
        source_url=item.detail_url,
        actions=parse_actions(item.actions, session=session, source_url=item.detail_url),
        versions=versions or [],
        kind=classify_kind(item.title),
    )


def parse_actions(text: str, *, session: Session, source_url: str | None = None) -> list[BillAction]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    occurred_at = _action_date(cleaned, session)
    return [BillAction(
        occurred_at=occurred_at,
        chamber=_chamber_from_action(cleaned),
        action_text=cleaned,
        normalized_status=match_first(cleaned, PATTERNS),
        source_url=source_url,
    )]


def parse_sponsor_names(node: Node) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for link in node.css("a"):
        name = _clean_text(link.text())
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def parse_directory_versions(html: str) -> list[BillVersion]:
    versions: list[BillVersion] = []
    tree = HTMLParser(html)
    for link in tree.css("a[href]"):
        href = link.attributes.get("href") or ""
        label = _clean_text(link.text())
        lower = href.lower()
        if not lower.endswith((".html", ".pdf")):
            continue
        file_format = "pdf" if lower.endswith(".pdf") else "html"
        versions.append(BillVersion(
            label=_version_label(label, file_format),
            source_url=urljoin(ROOT, href),
            format=file_format,
        ))
    return versions


def _session_directories(directory_name: str) -> list[str]:
    encoded = directory_name.replace(" ", "%20")
    return [
        f"/Sessions/{encoded}/bills/house/",
        f"/Sessions/{encoded}/bills/senate/",
        f"/Sessions/{encoded}/memorials/house/",
        f"/Sessions/{encoded}/memorials/senate/",
        f"/Sessions/{encoded}/resolutions/house/",
        f"/Sessions/{encoded}/resolutions/senate/",
        f"/Sessions/{encoded}/final/",
    ]


def _version_label(file_name: str, file_format: str) -> str:
    stem = re.sub(r"\.[A-Za-z]+$", "", file_name).replace("%20", " ").strip()
    return f"{stem} {file_format.upper()}"


def _file_base_from_url(url: str) -> str:
    file_name = url.rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z]+$", "", file_name).upper().replace("%20", " ")
    match = re.match(r"([A-Z]+)\s*0*(\d+)", stem)
    if match is None:
        return stem
    return _base_with_width(match.group(1), int(match.group(2)))


def _file_base(number: str) -> str:
    match = re.match(r"([A-Z]+)\s*(\d+)", number.upper())
    if match is None:
        return number.upper().replace(" ", "")
    return _base_with_width(match.group(1), int(match.group(2)))


def _base_with_width(prefix: str, number: int) -> str:
    width = 4 if prefix in {"HB", "SB"} else 3 if prefix in {"HM", "SM", "HJM", "SJM"} else 2
    return f"{prefix}{number:0{width}d}"


def _format_number(text: str) -> str:
    value = text.replace("*", "").strip().upper()
    match = re.match(r"([A-Z]+)\s*0*(\d+)", value)
    if match is None:
        return value
    return f"{match.group(1)} {int(match.group(2))}"


def _chamber_for_number(number: str) -> Chamber:
    return Chamber.LOWER if number.upper().startswith("H") else Chamber.UPPER


def _chamber_from_action(text: str) -> Chamber | None:
    lowered = text.lower()
    if "passed/h" in lowered or "hpref" in lowered or " h/" in lowered:
        return Chamber.LOWER
    if "passed/s" in lowered or "spref" in lowered or " s/" in lowered:
        return Chamber.UPPER
    return None


def _action_date(text: str, session: Session) -> datetime:
    year = session.start_date.year if session.start_date else datetime.now().year
    match = re.search(r"\(([A-Z][a-z]{2})\.\s*(\d{1,2})\)", text)
    if match:
        for fmt in ("%b. %d %Y",):
            try:
                parsed = datetime.strptime(f"{match.group(1)}. {match.group(2)} {year}", fmt)
                return datetime.combine(parsed.date(), datetime.min.time())
            except ValueError:
                continue
    return datetime.combine(date(year, 1, 1), datetime.min.time())


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number_sort_key(number: str) -> tuple[str, int, str]:
    match = re.match(r"^([A-Z]+)\s*(\d+)$", number.upper())
    if match is None:
        return (number.upper(), 0, number.upper())
    return (match.group(1), int(match.group(2)), number.upper())
