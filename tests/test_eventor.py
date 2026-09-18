from __future__ import annotations

import urllib.error
from datetime import UTC, date, datetime

import pytest

from eventor_calendar_sync.eventor import LEVEL_IDS, EventorSource, Query, SourceError
from eventor_calendar_sync.models import LEVELS
from helpers import fake_source


def test_levels_cover_the_model():
    assert set(LEVEL_IDS) == set(LEVELS)


def test_clock_values_are_utc(by_name):
    event = by_name("Street Series #2")
    assert event.start == datetime(2026, 10, 21, 6, 0, tzinfo=UTC)  # 17:00 in Sydney
    assert event.finish == datetime(2026, 10, 21, 7, 30, tzinfo=UTC)
    assert event.url == "https://eventor.orienteering.asn.au/Events/Show/24536"


def test_every_discipline_is_kept(by_name):
    assert by_name("UFO1").disciplines == ("foot", "park-street")
    assert by_name("BOSS 1").disciplines == ("mtbo",)


def test_organisers_are_named_and_multi_valued(by_name):
    event = by_name("WINTER SPRINTS")
    assert event.organiser_ids == {23, 29}
    assert {o.name for o in event.organisers} == {
        "Central Coast Orienteers",
        "Newcastle Orienteering Club",
    }


def test_position_is_latitude_longitude(by_name):
    race = by_name("Street Series #2").races[0]
    assert race.lat == pytest.approx(-32.8, abs=0.3)
    assert race.lon == pytest.approx(151.5, abs=0.3)
    assert by_name("Street Series #1").races[0].lat is None


def test_multi_day_event_has_a_race_per_day(by_name):
    event = by_name("2025 XMAS 5 DAYS")
    assert [r.name for r in event.races] == ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5"]
    assert len({r.start for r in event.races}) == 5


def test_cancelled_level_and_message(by_name):
    assert by_name("Goldseekers").cancelled
    assert not by_name("NOY8").cancelled
    assert by_name("State League #13").level == "state"
    assert "UFO" in by_name("UFO1").message


def test_queries_become_parameters_and_results_are_merged():
    calls: list = []
    source = fake_source(calls)
    queries = [Query(organisers=(5,)), Query(levels=("championship", "national"))]
    events = source.events(queries, date(2026, 1, 1), date(2026, 12, 31))
    event_calls = [params for path, params in calls if path == "/events"]
    assert event_calls[0] == {
        "fromDate": "2026-01-01 00:00:00",
        "toDate": "2026-12-31 23:59:59",
        "organisationIds": "5",
    }
    assert event_calls[1]["classificationIds"] == "1,2"
    assert len(events) == len({e.id for e in events}) == 20  # the same 20, not 40
    assert events == sorted(events, key=lambda e: (e.start, e.id))


def test_a_rejected_key_is_explained(monkeypatch: pytest.MonkeyPatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(SourceError, match="EVENTOR_API_KEY"):
        EventorSource(api_key="bad").whoami()


def test_transient_failures_are_retried(monkeypatch: pytest.MonkeyPatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"<Organisation><Name>Test Club</Name></Organisation>"

    def flaky(request, timeout):
        attempts.append(request.get_header("User-agent"))
        if len(attempts) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", flaky)
    source = EventorSource(api_key="k", _sleep=lambda _s: None)
    assert source.whoami() == "Test Club"
    assert len(attempts) == 3
    assert attempts[0].startswith("eventor-calendar-sync/")  # the default urllib agent gets a 403


def test_garbage_is_a_source_error():
    source = EventorSource(api_key="k", fetch=lambda _p, _q: b"<html>Service unavailable")
    with pytest.raises(SourceError, match="unparseable"):
        source.organisations()
