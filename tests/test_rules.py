from __future__ import annotations

import re
from dataclasses import replace

from eventor_calendar_sync.config import Override, load_config
from eventor_calendar_sync.rules import in_series, judge, judge_all
from helpers import CONFIG


def test_name_patterns_pick_the_series(config, by_name):
    assert judge(by_name("Street Series #1"), config).series == {"street"}
    assert judge(by_name("State League #13"), config).series == {"state-league"}
    plain = judge(by_name("NOY8"), config)
    assert plain.series == frozenset() and not plain.not_event and not plain.overridden


def test_a_listing_can_belong_to_several_series(config, by_name):
    verdict = judge(by_name("2027 NSW State League - NSW Schools Champs"), config)
    assert verdict.series == {"state-league", "schools"}


def test_not_an_event_and_which_pattern_said_so(config, by_name):
    socks = judge(by_name("Steigen Socks"), config)
    assert socks.not_event and socks.because == r"\bsocks\b"
    # The season ticket carries the series' name; being not-an-event is what keeps it out.
    ticket = judge(by_name("Season Ticket"), config)
    assert ticket.not_event and ticket.series == {"sss"}


def test_word_boundaries_matter(config, by_name):
    """'singlet' would hide every event held at Singleton; r'\\bsinglets?\\b' does not."""
    singleton = replace(by_name("BOSS 1"), name="Newcastle BOSS 5 MTBO - Singleton")

    def with_pattern(pattern: str):
        settings = replace(config.settings, not_event_patterns=(re.compile(pattern, re.I),))
        return judge(singleton, replace(config, settings=settings))

    assert with_pattern("singlet").not_event
    assert not with_pattern(r"\bsinglets?\b").not_event


def test_constraints_stop_an_acronym_picking_up_another_clubs_events(config, by_name):
    street = config.series["street"]
    event = by_name("Street Series #1")
    assert in_series(street, event)
    assert not in_series(street, replace(event, organisers=()))
    mtbo_only = replace(street, disciplines=frozenset({"mtbo"}))
    assert not in_series(mtbo_only, event)


def test_exclude_name_patterns_carve_out_exceptions(config, by_name):
    street = replace(
        config.series["street"], exclude_name_patterns=(re.compile("bolton point", re.I),)
    )
    assert not in_series(street, by_name("Street Series #1"))  # Bolton Point
    assert in_series(street, by_name("Street Series #2"))


def test_overrides_have_the_last_word(tmp_path, by_name):
    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG
        + "\n[overrides]\n"
        + '24037 = { series = ["state-league"], note = "counts this year" }\n'  # NOY8
        + "24535 = { series = [] }\n"  # Street Series #1
        + "24550 = { not_event = false }\n"  # the season ticket
        + "24109 = { not_event = true }\n"  # Night Champs
    )
    config = load_config(path)
    noy = judge(by_name("NOY8"), config)
    assert noy.series == {"state-league"} and noy.overridden
    assert judge(by_name("Street Series #1"), config).series == frozenset()
    assert not judge(by_name("Season Ticket"), config).not_event
    night = judge(by_name("Night Champs"), config)
    assert night.not_event and night.because == "[overrides]"
    assert not judge(by_name("Street Series #2"), config).overridden


def test_an_override_that_leaves_a_field_alone_keeps_the_patterns_answer(config, by_name):
    overridden = replace(config, overrides={24550: Override(series=frozenset())})
    ticket = judge(by_name("Season Ticket"), overridden)
    assert ticket.series == frozenset() and ticket.not_event  # still hidden by its pattern


def test_judge_all_covers_every_event(config, events):
    verdicts = judge_all(events, config)
    assert set(verdicts) == {e.id for e in events}
    assert sorted(e.name for e in events if verdicts[e.id].not_event) == [
        "2026/2027 Sydney Summer Series Season Ticket",
        "Newcastle Club Communication 2026",
        "ONSW Steigen Socks brought to you by ONSW Juniors",
        "Xmas 5 Days - CAMPING",
    ]
