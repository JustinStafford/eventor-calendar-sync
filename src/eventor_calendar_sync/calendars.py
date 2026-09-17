"""Which events go in which calendar, and what each calendar entry looks like."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from eventor_calendar_sync.config import CalendarDef, Settings
from eventor_calendar_sync.models import CalendarEntry, Classification, Event, Race

LONG_ENTRY = timedelta(hours=18)  # from here up, show dates rather than times
DISCIPLINE_LABELS = {"foot": "Foot", "mtbo": "MTBO", "ski": "Ski", "trail": "Trail",
                     "park-street": "Park/Street"}  # fmt: skip


def matches(calendar: CalendarDef, event: Event, classification: Classification) -> bool:
    """Criteria are ANDed; within one criterion any value may match.

    ``event_ids`` force an event in whatever else the calendar asks for, and
    ``exclude_event_ids`` force it out.
    """
    if event.id in calendar.exclude_event_ids:
        return False
    if event.id in calendar.event_ids:
        return True
    if classification.kind not in calendar.kinds:
        return False
    if calendar.series and classification.series not in calendar.series:
        return False
    if calendar.organisers and not (event.organiser_ids & calendar.organisers):
        return False
    if calendar.disciplines and not (set(event.disciplines) & calendar.disciplines):
        return False
    if calendar.levels and event.level not in calendar.levels:
        return False
    if calendar.name_patterns and not any(p.search(event.name) for p in calendar.name_patterns):
        return False
    return not any(p.search(event.name) for p in calendar.exclude_name_patterns)


def _description(event: Event, race: Race | None) -> str:
    lines = []
    organisers = " / ".join(o.name for o in event.organisers if o.name)
    if organisers:
        lines.append(organisers)
    facts = [DISCIPLINE_LABELS.get(d, d) for d in event.disciplines]
    if race and race.distance:
        facts.append(race.distance)
    if race and race.light == "Night":
        facts.append("Night")
    if facts:
        lines.append(" · ".join(facts))
    lines.append(f"Details and entry: {event.url}")
    if event.web_url:
        lines.append(f"Event website: {event.web_url}")
    return "\n".join(lines)


def build_entries(
    event: Event, settings: Settings, uid_domain: str, default_duration_hours: float | None = None
) -> list[CalendarEntry]:
    """One entry per race.

    Eventor stores "no time given" as local midnight, so a midnight start becomes an
    all-day entry, as does anything running 18 hours or more (week-long MapRun
    courses, multi-day listings without races). A timed event with no finish gets the
    default duration.
    """
    if event.cancelled and settings.cancelled == "drop":
        return []
    hours = default_duration_hours or settings.default_duration_hours
    multi = len(event.races) > 1
    entries = []
    for race in event.races or (None,):
        start = (race.start if race else None) or event.start
        if start is None:
            continue
        # The event's finish only describes a race when that race is the whole event.
        finish = event.finish if not multi and event.finish and event.finish > start else None
        local_start = start.astimezone(settings.timezone)
        all_day = local_start.time() == time(0, 0) or (finish and finish - start >= LONG_ENTRY)

        summary = event.name
        if multi and race and race.name:
            summary = f"{event.name}: {race.name}"
        if event.cancelled:
            summary = f"CANCELLED: {summary}"

        if all_day:
            first = local_start.date()
            last = finish.astimezone(settings.timezone).date() if finish else first
            begin, end = first, max(first, last) + timedelta(days=1)
        else:
            begin = start.astimezone(UTC)
            end = (finish or start + timedelta(hours=hours)).astimezone(UTC)

        has_position = race is not None and race.lat is not None and race.lon is not None
        suffix = f"-{race.id}" if race else ""
        entries.append(
            CalendarEntry(
                uid=f"eventor-{event.id}{suffix}@{uid_domain}",
                summary=summary,
                start=begin,
                end=end,
                all_day=bool(all_day),
                event_id=event.id,
                description=_description(event, race),
                location=f"{race.lat:.6f}, {race.lon:.6f}" if has_position else "",
                geo=(race.lat, race.lon) if has_position else None,
                url=event.url,
                cancelled=event.cancelled,
                modified=event.modified,
            )
        )
    return entries


def sort_key(entry: CalendarEntry) -> tuple[datetime, str]:
    start = entry.start
    if not isinstance(start, datetime):
        start = datetime.combine(start, time(0, 0), tzinfo=UTC)
    return (start, entry.uid)
