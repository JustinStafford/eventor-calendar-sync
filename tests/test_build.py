from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import icalendar
import pytest
from typer.testing import CliRunner

from eventor_calendar_sync import build, cli
from eventor_calendar_sync.config import ConfigError
from eventor_calendar_sync.eventor import EventorSource, SourceError
from helpers import FakeClaude, fake_source
from test_classify import llm_for, smart

TODAY = date(2026, 9, 18)


def run(config, events, tmp_path, **kwargs):
    return build.run(
        config,
        events,
        out_dir=tmp_path / "public",
        cache_path=tmp_path / "classifications.json",
        llm=kwargs.pop("llm", None),
        today=kwargs.pop("today", TODAY),
        **kwargs,
    )


def test_a_build_writes_the_whole_site(config, events, tmp_path):
    result = run(config, events, tmp_path)
    public = tmp_path / "public"
    assert sorted(p.name for p in public.iterdir()) == [
        ".nojekyll", "CNAME", "calendars.json", "index.html", "newcastle.ics", "state-league.ics",
        "street.ics",
    ]  # fmt: skip
    assert (public / "CNAME").read_text() == "calendars.example.org\n"
    assert b"\r\n" in (public / "street.ics").read_bytes()
    street = icalendar.Calendar.from_ical((public / "street.ics").read_bytes())
    assert [str(v["SUMMARY"]) for v in street.walk("VEVENT")] == [
        "Newcastle Summer Street Series #1 - Bolton Point",
        "Newcastle Summer Street Series #2 - Kurri East",
    ]
    assert result.report["calendars"]["street"] == {
        "name": "Street Series", "entries": 2, "upcoming": 2, "previous_upcoming": None,
        "url": "https://calendars.example.org/street.ics",
    }  # fmt: skip
    assert not (tmp_path / "classifications.json").exists()  # rules mode keeps no cache


def test_admin_listings_stay_out_of_organiser_calendars(config, events, tmp_path):
    run(config, events, tmp_path)
    newcastle = (tmp_path / "public" / "newcastle.ics").read_text()
    assert "Newcastle NOY8" in newcastle
    assert "Club Communication" not in newcastle and "CAMPING" not in newcastle


def test_a_second_run_changes_nothing(config, events, tmp_path):
    assert len(run(config, events, tmp_path).written) == 7
    assert run(config, events, tmp_path).written == []


def test_dry_run_writes_no_site_but_keeps_paid_for_classifications(config, events, tmp_path):
    llm = llm_for(config, FakeClaude(smart))
    result = run(config, events, tmp_path, llm=llm, dry_run=True)
    assert not (tmp_path / "public").exists() and result.written == []
    assert result.report["mode"] == "dry-run"
    cache = json.loads((tmp_path / "classifications.json").read_text())
    assert len(cache["events"]) == 20


def test_the_page(config, events, tmp_path):
    run(config, events, tmp_path)
    page = (tmp_path / "public" / "index.html").read_text()
    assert "<title>Test calendars</title>" in page
    assert 'href="webcal://calendars.example.org/street.ics"' in page
    assert "calendar.google.com/calendar/render?cid=webcal%3A%2F%2Fcalendars.example.org" in page
    assert (
        "outlook.office.com/calendar/0/addfromweb?url=https%3A%2F%2Fcalendars.example.org" in page
    )
    assert 'id="street"' in page and "<svg" in page
    assert "Updated Fri 18 Sep 2026" in page
    assert (
        page.index("Newcastle</h2>") < page.index('id="street"') < page.index('id="state-league"')
    )


def test_event_names_are_escaped_on_the_page(config, events, tmp_path, by_name):
    hostile = replace(
        by_name("Street Series #1"), name="Summer Street Series <script>alert(1)</script>"
    )
    run(config, [hostile if e.id == hostile.id else e for e in events], tmp_path)
    page = (tmp_path / "public" / "index.html").read_text()
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page


def test_the_guard_refuses_a_collapsing_calendar(config, events, tmp_path):
    early = date(2025, 10, 1)  # most of the fixture is still to come
    result = run(config, events, tmp_path, today=early)
    assert result.report["calendars"]["newcastle"]["upcoming"] >= 10
    before = (tmp_path / "public" / "newcastle.ics").read_bytes()
    survivors = [e for e in events if 29 not in e.organiser_ids][:3] + [
        e for e in events if 29 in e.organiser_ids
    ][:1]
    with pytest.raises(build.GuardError) as refused:
        run(config, survivors, tmp_path, today=early)
    assert "newcastle: upcoming entries would drop from" in refused.value.problems[0]
    assert refused.value.result.report["ok"] is False
    assert (tmp_path / "public" / "newcastle.ics").read_bytes() == before  # nothing written

    forced = run(config, survivors, tmp_path, today=early, force=True)
    assert forced.report["guard"] and forced.report["ok"] is True
    assert (tmp_path / "public" / "newcastle.ics").read_bytes() != before


def test_small_calendars_may_empty_out(config, events, tmp_path):
    run(config, events, tmp_path)  # street has 2 upcoming: below the guard's floor
    run(config, [e for e in events if "Street Series" not in e.name], tmp_path)
    assert "BEGIN:VEVENT" not in (tmp_path / "public" / "street.ics").read_text()


def test_a_calendar_removed_from_the_config_is_unpublished(config, events, tmp_path):
    run(config, events, tmp_path)
    fewer = replace(config, calendars={k: v for k, v in config.calendars.items() if k != "street"})
    result = run(fewer, events, tmp_path)
    assert result.report["removed_calendars"] == ["street"]
    assert not (tmp_path / "public" / "street.ics").exists()
    assert (tmp_path / "public" / "newcastle.ics").exists()


def test_the_summary_reports_what_a_person_needs(config, events, tmp_path):
    result = run(config, events, tmp_path, llm=llm_for(config, FakeClaude(smart)))
    assert "20 events pulled. Classifier: `llm:claude-opus-5`, 0 from cache, 20 newly" in (
        result.summary
    )
    assert "| Street Series (`street`) | 2 | new | 2 |" in result.summary
    assert "### Newly classified" in result.summary
    assert "upcoming event(s) are in no calendar" in result.summary
    hidden = {e["name"] for e in result.report["not_events_upcoming"]}
    assert "2026/2027 Sydney Summer Series Season Ticket" in hidden
    assert "upcoming listing(s) treated as not an event" in result.summary
    unplaced = {e["name"] for e in result.report["unplaced_upcoming"]["events"]}
    assert "2026/2027 Sydney Summer Series Season Ticket" not in unplaced  # admin: not an event


def test_a_missing_logo_is_a_config_error(config, events, tmp_path):
    with pytest.raises(ConfigError, match="logo not found"):
        run(replace(config, site=replace(config.site, logo="logo.png")), events, tmp_path)
    (config.path.parent / "logo.png").write_bytes(b"png")
    run(replace(config, site=replace(config.site, logo="logo.png")), events, tmp_path)
    assert (tmp_path / "public" / "logo.png").read_bytes() == b"png"
    assert 'src="logo.png"' in (tmp_path / "public" / "index.html").read_text()


def test_an_empty_eventor_is_never_published(config):
    empty = EventorSource(api_key="k", fetch=lambda _p, _q: b"<EventList></EventList>")
    with pytest.raises(SourceError, match="no events"):
        build.pull(config, empty, TODAY)


# -- the command line ----------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_source", lambda _base_url: fake_source())
    return CliRunner()


def invoke(runner: CliRunner, *args: str):
    return runner.invoke(cli.app, ["--env-file", "absent.env", *args])


def test_cli_build(cli_env, config_path, tmp_path):
    out, report = tmp_path / "site", tmp_path / "report.json"
    result = invoke(cli_env, "build", "-c", str(config_path), "-o", str(out), "--report",
                    str(report), "--as-of", "2026-09-18")  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "ANTHROPIC_API_KEY is not set" in result.output
    assert "7 file(s) changed" in result.output
    assert json.loads(report.read_text())["classifier"]["mode"] == "rules"
    assert (out / "street.ics").is_file()


def test_cli_guard_exit_code(cli_env, config_path, tmp_path, monkeypatch):
    out = tmp_path / "site"
    args = ("build", "-c", str(config_path), "-o", str(out), "--as-of", "2026-09-18")
    assert invoke(cli_env, *args).exit_code == 0
    monkeypatch.setattr(build, "GUARD_MIN_PREVIOUS", 1)
    later = ("build", "-c", str(config_path), "-o", str(out), "--as-of", "2026-09-18")
    monkeypatch.setattr(
        build, "pull", lambda *_a: [e for e in fake_source().events(
            [cli.Query(organisers=(5,))], date(2025, 1, 1), date(2028, 1, 1)
        ) if "Street Series" not in e.name]
    )  # fmt: skip
    result = invoke(cli_env, *later)
    assert result.exit_code == 4
    assert "safety guard: street" in result.output
    assert invoke(cli_env, *later, "--force").exit_code == 0


def test_cli_config_error(cli_env, tmp_path):
    result = invoke(cli_env, "build", "-c", str(tmp_path / "absent.toml"))
    assert result.exit_code == 1 and "config file not found" in result.output


def test_cli_explore(cli_env, config_path):
    result = invoke(cli_env, "explore", "-c", str(config_path), "--min", "2",
                    "--as-of", "2026-09-18")  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "newcastle summer street series" in result.output
    assert "street x2" in result.output


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Newcastle Summer Street Series #12 - Cooks Hill", "newcastle summer street series"),
        ("2025/26 Sydney Summer Series #1 \u2013 Glebe", "sydney summer series"),
        ("2026 NSW State League #13 - NSW Middle Champs - Gulgong", "nsw state league"),
        ("Newcastle BOSS 1 MTBO - Hawkemount South", "newcastle boss mtbo"),
    ],
)
def test_stem(name, expected):
    assert cli.stem(name) == expected
