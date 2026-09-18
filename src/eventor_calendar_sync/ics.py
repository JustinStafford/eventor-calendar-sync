"""A small, deterministic iCalendar (RFC 5545) writer.

The same input always produces the same bytes, so the published files only change
when an event does. That is why ``DTSTAMP`` is the event's own modification time,
not "now". Timed entries are written in UTC, which needs no ``VTIMEZONE`` and is
displayed in the viewer's own time zone by every calendar app.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

from eventor_calendar_sync import __version__
from eventor_calendar_sync.calendars import sort_key
from eventor_calendar_sync.models import CalendarEntry

PRODID = f"-//eventor-calendar-sync//{__version__}//EN"
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
DTSTART = re.compile(r"^DTSTART[^:]*:(\d{8})", re.MULTILINE)


def escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold to 75 octets per line without splitting a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks, limit = [], 75
    while raw:
        cut = min(limit, len(raw))
        while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(raw[:cut].decode("utf-8"))
        raw, limit = raw[cut:], 74  # continuation lines carry a leading space
    return "\r\n ".join(chunks)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _when(name: str, value: date | datetime) -> str:
    if isinstance(value, datetime):
        return f"{name}:{_stamp(value)}"
    return f"{name};VALUE=DATE:{value.strftime('%Y%m%d')}"


def render_calendar(
    name: str,
    description: str,
    entries: Iterable[CalendarEntry],
    *,
    timezone: str,
    url: str = "",
    refresh_hours: int = 12,
) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"NAME:{escape(name)}",
        f"X-WR-CALNAME:{escape(name)}",
    ]
    if description:
        lines += [f"DESCRIPTION:{escape(description)}", f"X-WR-CALDESC:{escape(description)}"]
    if url:
        lines.append(f"URL:{url}")
    lines += [
        f"X-WR-TIMEZONE:{timezone}",
        f"REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_hours}H",
        f"X-PUBLISHED-TTL:PT{refresh_hours}H",
    ]
    for entry in sorted(entries, key=sort_key):
        stamp = _stamp(entry.modified or EPOCH)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{entry.uid}",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{stamp}",
            _when("DTSTART", entry.start),
            _when("DTEND", entry.end),
            f"SUMMARY:{escape(entry.summary)}",
        ]
        if entry.description:
            lines.append(f"DESCRIPTION:{escape(entry.description)}")
        if entry.location:
            lines.append(f"LOCATION:{escape(entry.location)}")
        if entry.geo:
            lines.append(f"GEO:{entry.geo[0]:.6f};{entry.geo[1]:.6f}")
        if entry.url:
            lines.append(f"URL:{entry.url}")
        lines.append("STATUS:CANCELLED" if entry.cancelled else "STATUS:CONFIRMED")
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def count_from(ics_text: str, day: date) -> int:
    """How many entries in a published file start on or after ``day`` (for the safety guard)."""
    floor = day.strftime("%Y%m%d")
    return sum(1 for start in DTSTART.findall(ics_text) if start >= floor)
