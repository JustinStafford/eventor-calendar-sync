"""Source-agnostic event model.

Everything downstream of :mod:`eventor_calendar_sync.eventor` (classification,
calendar selection, the iCalendar files and the landing page) works on these
dataclasses only, so replacing Eventor with another event system means writing
one new source module and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Event levels, highest first. Eventor calls these "event classifications".
LEVELS = ("international", "championship", "national", "state", "local", "club")
DISCIPLINES = ("foot", "mtbo", "ski", "trail", "park-street")


@dataclass(frozen=True, slots=True)
class Organiser:
    id: int
    name: str = ""


@dataclass(frozen=True, slots=True)
class Race:
    """One race of an event. Single-day events have exactly one."""

    id: int
    name: str = ""
    start: datetime | None = None  # timezone-aware UTC
    lat: float | None = None
    lon: float | None = None
    distance: str | None = None  # "Sprint", "Middle", "Long", ...
    light: str | None = None  # "Night", "DayAndNight"


@dataclass(frozen=True, slots=True)
class Event:
    id: int
    name: str
    url: str  # the public page for the event in the source system
    start: datetime | None = None  # timezone-aware UTC
    finish: datetime | None = None
    level: str | None = None  # one of LEVELS
    disciplines: tuple[str, ...] = ()  # names from DISCIPLINES, or the raw ID as text
    organisers: tuple[Organiser, ...] = ()
    races: tuple[Race, ...] = ()
    cancelled: bool = False
    web_url: str | None = None
    message: str = ""  # organiser's free text; untrusted
    modified: datetime | None = None

    @property
    def organiser_ids(self) -> frozenset[int]:
        return frozenset(o.id for o in self.organisers)


@dataclass(frozen=True, slots=True)
class Classification:
    """What an event *is*, as decided by an override, the LLM or the fallback rules."""

    kind: str  # one of classify.KINDS
    series: str | None = None  # slug of a configured series
    confidence: str = "high"  # high | medium | low
    reason: str = ""
    source: str = "rules"  # rules | llm:<model> | override


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One VEVENT. ``start``/``end`` are dates for all-day entries, else aware UTC datetimes."""

    uid: str
    summary: str
    start: date | datetime
    end: date | datetime  # exclusive for all-day entries, as iCalendar wants
    all_day: bool
    event_id: int
    description: str = ""
    location: str = ""
    geo: tuple[float, float] | None = None
    url: str = ""
    cancelled: bool = False
    modified: datetime | None = None

    @property
    def last_day(self) -> date:
        """The last day the entry covers (all-day ends are exclusive)."""
        if isinstance(self.end, datetime):
            return self.end.date()
        return self.end - timedelta(days=1)
