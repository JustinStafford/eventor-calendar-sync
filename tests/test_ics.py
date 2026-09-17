from __future__ import annotations

from datetime import UTC, date, datetime

import icalendar

from eventor_calendar_sync.calendars import build_entries
from eventor_calendar_sync.ics import count_from, escape, fold, render_calendar
from eventor_calendar_sync.models import CalendarEntry


def render(entries, name="Test, calendar; one"):
    return render_calendar(name, "About it", entries, timezone="Australia/Sydney")


def all_entries(events, config):
    return [e for event in events for e in build_entries(event, config.settings, "eventor.example")]


def test_escape():
    assert escape("a, b; c\\d\r\ne") == "a\\, b\\; c\\\\d\\ne"


def test_fold_keeps_lines_to_75_octets_and_characters_whole():
    line = "SUMMARY:" + "\u00d8rienteering \u2013 caf\u00e9 " * 12
    folded = fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert "".join([parts[0]] + [p[1:] for p in parts[1:]]) == line


def test_output_parses_and_round_trips(events, config):
    entries = all_entries(events, config)
    text = render(entries)
    assert text.endswith("END:VCALENDAR\r\n") and "\n" not in text.replace("\r\n", "")
    calendar = icalendar.Calendar.from_ical(text)
    assert "X-WR-CALNAME:Test\\, calendar\\; one\r\n" in text  # escaped like any other text
    vevents = list(calendar.walk("VEVENT"))
    assert len(vevents) == len(entries)
    assert len({str(v["UID"]) for v in vevents}) == len(entries)

    by_uid = {str(v["UID"]): v for v in vevents}
    street = by_uid["eventor-24536-25132@eventor.example"]
    assert street["DTSTART"].dt == datetime(2026, 10, 21, 6, 0, tzinfo=UTC)
    assert str(street["URL"]) == "https://eventor.orienteering.asn.au/Events/Show/24536"
    description = str(street["DESCRIPTION"])  # escaped newlines come back as real ones
    assert description.startswith("Newcastle Orienteering Club\nPark/Street\nDetails and entry: ")
    assert "\\" not in description
    assert street["GEO"].latitude < 0 < street["GEO"].longitude

    schools = next(v for v in vevents if "Schools Champs" in str(v["SUMMARY"]))
    assert schools["DTSTART"].dt == date(2027, 8, 21)
    assert schools["DTEND"].dt == date(2027, 8, 22)

    cancelled = [v for v in vevents if str(v["STATUS"]) == "CANCELLED"]
    assert [str(v["SUMMARY"]) for v in cancelled] == [
        "CANCELLED: Goldseekers Summer Series #1 2026"
    ]


def test_output_is_deterministic_and_ordered(events, config):
    entries = all_entries(events, config)
    assert render(entries) == render(list(reversed(entries)))
    starts = [line for line in render(entries).split("\r\n") if line.startswith("DTSTART")]
    assert len(starts) == len(entries)


def test_dtstamp_is_the_modification_time_not_now(events, config):
    text = render(all_entries(events[:1], config))
    assert events[0].modified is not None
    assert f"DTSTAMP:{events[0].modified:%Y%m%dT%H%M%SZ}" in text


def test_count_from():
    def entry(uid, start, end, all_day):
        return CalendarEntry(
            uid=uid, summary=uid, start=start, end=end, all_day=all_day, event_id=1
        )

    text = render(
        [
            entry(
                "past", datetime(2026, 9, 1, 6, tzinfo=UTC), datetime(2026, 9, 1, 8, tzinfo=UTC), 0
            ),
            entry("today", date(2026, 9, 18), date(2026, 9, 19), True),
            entry(
                "later",
                datetime(2026, 10, 1, 6, tzinfo=UTC),
                datetime(2026, 10, 1, 8, tzinfo=UTC),
                0,
            ),
        ]
    )
    assert count_from(text, date(2026, 9, 18)) == 2
    assert count_from(text, date(2027, 1, 1)) == 0
