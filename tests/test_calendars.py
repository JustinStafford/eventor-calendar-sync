from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from eventor_calendar_sync.calendars import build_entries, matches
from eventor_calendar_sync.models import Verdict

DOMAIN = "eventor.example"
PLAIN = Verdict()


def entries_for(event, config, hours=None):
    return build_entries(event, config.settings, DOMAIN, hours)


# -- selection -----------------------------------------------------------------------


def test_series_calendar(config, by_name):
    street = config.calendars["street"]
    event = by_name("Street Series #1")
    assert matches(street, event, Verdict(series=frozenset({"street"})))
    assert matches(street, event, Verdict(series=frozenset({"street", "state-league"})))
    assert not matches(street, event, PLAIN)
    assert not matches(street, event, Verdict(series=frozenset({"street"}), not_event=True))


def test_organiser_calendar_takes_co_organised_events_but_not_non_events(config, by_name):
    newcastle = config.calendars["newcastle"]
    assert matches(newcastle, by_name("WINTER SPRINTS"), PLAIN)  # Central Coast + Newcastle
    assert not matches(newcastle, by_name("Sydney Summer Series #1"), PLAIN)
    assert not matches(newcastle, by_name("Club Communication"), Verdict(not_event=True))


def test_criteria_are_anded_and_any_discipline_counts(config, by_name):
    sprints = replace(
        config.calendars["newcastle"], disciplines=frozenset({"park-street"}), levels=frozenset()
    )
    assert matches(sprints, by_name("UFO1"), PLAIN)  # foot AND park-street
    assert not matches(sprints, by_name("NOY8"), PLAIN)  # foot only
    state = replace(config.calendars["newcastle"], organisers=frozenset(), levels={"state"})
    assert matches(state, by_name("State League #13"), PLAIN)
    assert not matches(state, by_name("NOY8"), PLAIN)


def test_name_patterns_and_event_ids(config, by_name):
    base = config.calendars["newcastle"]
    import re

    night = replace(base, name_patterns=(re.compile("night", re.I),))
    assert matches(night, by_name("Night Champs"), PLAIN)
    assert not matches(night, by_name("NOY8"), PLAIN)
    no_night = replace(base, exclude_name_patterns=(re.compile("night", re.I),))
    assert not matches(no_night, by_name("Night Champs"), PLAIN)

    glebe = by_name("Sydney Summer Series #1")
    forced = replace(base, event_ids=frozenset({glebe.id}))
    assert matches(forced, glebe, PLAIN)
    assert matches(forced, glebe, Verdict(not_event=True))  # event_ids beat everything
    noy = by_name("NOY8")
    assert not matches(replace(base, exclude_event_ids=frozenset({noy.id})), noy, PLAIN)


# -- entries -------------------------------------------------------------------------


def test_timed_event_with_a_finish(config, by_name):
    (entry,) = entries_for(by_name("Street Series #2"), config)
    assert entry.start == datetime(2026, 10, 21, 6, 0, tzinfo=UTC)
    assert entry.end == datetime(2026, 10, 21, 7, 30, tzinfo=UTC)
    assert not entry.all_day and not entry.cancelled
    assert entry.uid == "eventor-24536-25132@eventor.example"
    assert entry.location.startswith("-32.") and entry.geo[1] > 151
    assert "Newcastle Orienteering Club" in entry.description
    assert "https://eventor.orienteering.asn.au/Events/Show/24536" in entry.description


def test_no_finish_means_the_default_duration(config, by_name):
    event = by_name("UFO1")  # start == finish in Eventor
    (entry,) = entries_for(event, config)
    assert (entry.end - entry.start).total_seconds() == 3 * 3600
    (short,) = entries_for(event, config, hours=1.5)
    assert (short.end - short.start).total_seconds() == 1.5 * 3600
    assert "Foot · Park/Street · Sprint" in entry.description


def test_local_midnight_means_all_day(config, by_name):
    event = by_name("2027 NSW State League")  # 14:00 UTC on the 20th is midnight on the 21st
    (entry,) = entries_for(event, config)
    assert entry.all_day
    assert (entry.start, entry.end) == (date(2027, 8, 21), date(2027, 8, 22))
    assert entry.last_day == date(2027, 8, 21)
    assert entry.location == ""


def test_week_long_maprun_is_all_day_not_a_22_hour_block(config, by_name):
    (entry,) = entries_for(by_name("MapRun #19"), config)
    assert entry.all_day and entry.start == date(2026, 9, 20)


def test_one_entry_per_race(config, by_name):
    entries = entries_for(by_name("King's Birthday 3 Day"), config)
    assert [e.summary for e in entries] == [
        "King's Birthday 3 Day: Middle SL7 Baal Bone Junction",
        "King's Birthday 3 Day: Long SL8 Lidsdale State Forest",
        "King's Birthday 3 Day: Sprint SL9 Rydal Showground",
    ]
    assert len({e.uid for e in entries}) == 3
    assert all(not e.all_day for e in entries)
    # The parent's three-day span must not stretch each race.
    assert all((e.end - e.start).total_seconds() == 3 * 3600 for e in entries)
    assert len({e.location for e in entries}) == 3


def test_cancelled_events_are_marked_or_dropped(config, by_name):
    event = by_name("Goldseekers")
    (entry,) = entries_for(event, config)
    assert entry.cancelled and entry.summary.startswith("CANCELLED: Goldseekers")
    dropping = replace(config, settings=replace(config.settings, cancelled="drop"))
    assert entries_for(event, dropping) == []


def test_an_event_without_races_still_gets_an_entry(config, by_name):
    bare = replace(by_name("NOY8"), races=())
    (entry,) = entries_for(bare, config)
    assert entry.uid == "eventor-24037@eventor.example" and entry.location == ""
