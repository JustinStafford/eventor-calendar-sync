"""The Eventor source: ``GET /events`` parsed into :class:`~.models.Event`.

This is the only module that knows about Eventor. It uses the standard library
for HTTP on purpose: one endpoint, one header, nothing worth a dependency.
Eventor's front end rejects the default ``Python-urllib`` User-Agent with a 403,
so a descriptive one is always sent.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from eventor_calendar_sync import __version__
from eventor_calendar_sync.models import Event, Organiser, Race

log = logging.getLogger(__name__)

AU_BASE_URL = "https://eventor.orienteering.asn.au/api"
USER_AGENT = f"eventor-calendar-sync/{__version__} (+https://github.com/JustinStafford/eventor-calendar-sync)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
CANCELLED_STATUS_ID = 10

LEVEL_BY_ID = {1: "championship", 2: "national", 3: "state", 4: "local", 5: "club",
               6: "international"}  # fmt: skip
LEVEL_IDS = {name: level_id for level_id, name in LEVEL_BY_ID.items()}
DISCIPLINE_BY_ID = {1: "foot", 2: "mtbo", 3: "ski", 4: "trail", 6: "park-street"}

# (path, query parameters) -> response body
Fetch = Callable[[str, Mapping[str, str]], bytes]


class SourceError(Exception):
    """Eventor could not be reached, refused the key, or returned something unparseable."""


@dataclass(frozen=True, slots=True)
class Query:
    """One ``/events`` request. An event matching any configured query is pulled."""

    organisers: tuple[int, ...] = ()  # a state association's ID matches every club in the state
    levels: tuple[str, ...] = ()


@dataclass(slots=True)
class EventorSource:
    api_key: str
    base_url: str = AU_BASE_URL
    fetch: Fetch | None = None
    max_retries: int = 3
    timeout: float = 120.0
    _sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    # -- transport -------------------------------------------------------------

    def _get(self, path: str, params: Mapping[str, str]) -> bytes:
        if self.fetch is not None:
            return self.fetch(path, params)
        url = f"{self.base_url.rstrip('/')}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"ApiKey": self.api_key, "User-Agent": USER_AGENT}
        )
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise SourceError(
                        f"Eventor refused the request to {path} (HTTP {exc.code}): "
                        "check EVENTOR_API_KEY"
                    ) from exc
                if exc.code not in RETRY_STATUSES or attempt >= self.max_retries:
                    raise SourceError(f"GET {path} failed: HTTP {exc.code}") from exc
                why = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise SourceError(f"GET {path} failed: {exc}") from exc
                why = repr(exc)
            delay = 2.0 * (2**attempt)
            log.warning("%s from Eventor; retrying in %.0fs", why, delay)
            self._sleep(delay)
            attempt += 1

    def _xml(self, path: str, params: Mapping[str, str]) -> ET.Element:
        body = self._get(path, params)
        try:
            return ET.fromstring(body)
        except ET.ParseError as exc:
            raise SourceError(f"GET {path} returned unparseable XML: {exc}") from exc

    @property
    def site_url(self) -> str:
        """The public website that event links point at."""
        return self.base_url.rstrip("/").removesuffix("/api")

    # -- endpoints -------------------------------------------------------------

    def whoami(self) -> str:
        """Name of the organisation the API key belongs to."""
        root = self._xml("/organisation/apiKey", {})
        return root.findtext("Name") or root.findtext("ShortName") or "(unnamed organisation)"

    def organisations(self) -> dict[int, str]:
        root = self._xml("/organisations", {})
        names: dict[int, str] = {}
        for el in root.iter("Organisation"):
            org_id = _int(el.findtext("OrganisationId"))
            if org_id is not None:
                names[org_id] = (el.findtext("Name") or el.findtext("ShortName") or "").strip()
        return names

    def events(
        self,
        queries: Iterable[Query],
        from_date: date,
        to_date: date,
        organiser_names: Mapping[int, str] | None = None,
    ) -> list[Event]:
        """Every event matching any query, de-duplicated, in start order."""
        found: dict[int, Event] = {}
        for query in queries:
            params = {
                "fromDate": f"{from_date.isoformat()} 00:00:00",
                "toDate": f"{to_date.isoformat()} 23:59:59",
            }
            if query.organisers:
                params["organisationIds"] = ",".join(str(i) for i in query.organisers)
            if query.levels:
                params["classificationIds"] = ",".join(str(LEVEL_IDS[n]) for n in query.levels)
            root = self._xml("/events", params)
            for el in root.iter("Event"):
                event = parse_event(el, self.site_url, organiser_names or {})
                if event is not None:
                    found.setdefault(event.id, event)
        return sorted(
            found.values(), key=lambda e: (e.start or datetime.max.replace(tzinfo=UTC), e.id)
        )


# -- parsing -------------------------------------------------------------------


def _int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except ValueError:
        return None


def _float(text: str | None) -> float | None:
    try:
        return float((text or "").strip())
    except ValueError:
        return None


def _utc(el: ET.Element | None) -> datetime | None:
    """Eventor's ``<Date>``/``<Clock>`` pairs are UTC."""
    if el is None:
        return None
    day = (el.findtext("Date") or "").strip()
    if not day:
        return None
    clock = (el.findtext("Clock") or "00:00:00").strip() or "00:00:00"
    try:
        return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_race(el: ET.Element) -> Race | None:
    race_id = _int(el.findtext("EventRaceId"))
    if race_id is None:
        return None
    position = el.find("EventCenterPosition")
    lat = lon = None
    if position is not None:
        lat, lon = _float(position.get("y")), _float(position.get("x"))
        if lat is None or lon is None or (lat == 0 and lon == 0):
            lat = lon = None
    return Race(
        id=race_id,
        name=(el.findtext("Name") or "").strip(),
        start=_utc(el.find("RaceDate")),
        lat=lat,
        lon=lon,
        distance=el.get("raceDistance"),
        light=el.get("raceLightCondition"),
    )


def parse_event(el: ET.Element, site_url: str, organiser_names: Mapping[int, str]) -> Event | None:
    event_id = _int(el.findtext("EventId"))
    name = " ".join((el.findtext("Name") or "").split())
    if event_id is None or not name:
        return None
    organiser_ids = [_int(o.text) for o in el.findall("Organiser/OrganisationId")]
    disciplines = []
    for d in el.findall("DisciplineId"):
        discipline_id = _int(d.text)
        if discipline_id is not None:
            disciplines.append(DISCIPLINE_BY_ID.get(discipline_id, str(discipline_id)))
    message = ""
    for entry in el.findall("HashTableEntry"):
        if entry.findtext("Key") == "Eventor_Message":
            message = (entry.findtext("Value") or "").strip()
    races = tuple(r for r in (parse_race(race) for race in el.findall("EventRace")) if r)
    return Event(
        id=event_id,
        name=name,
        url=f"{site_url}/Events/Show/{event_id}",
        start=_utc(el.find("StartDate")),
        finish=_utc(el.find("FinishDate")),
        level=LEVEL_BY_ID.get(_int(el.findtext("EventClassificationId")) or 0),
        disciplines=tuple(dict.fromkeys(disciplines)),
        organisers=tuple(
            Organiser(id=i, name=organiser_names.get(i, "")) for i in organiser_ids if i is not None
        ),
        races=races,
        cancelled=_int(el.findtext("EventStatusId")) == CANCELLED_STATUS_ID,
        web_url=(el.findtext("WebURL") or "").strip() or None,
        message=message,
        modified=_utc(el.find("ModifyDate")),
    )
