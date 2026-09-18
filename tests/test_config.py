from __future__ import annotations

from pathlib import Path

import pytest

from eventor_calendar_sync.config import ConfigError, load_config
from helpers import CONFIG

EXAMPLE = Path(__file__).parents[1] / "examples" / "runner" / "config.toml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_shipped_example_loads():
    config = load_config(EXAMPLE)
    assert len(config.calendars) >= 10
    assert all(c.series <= set(config.series) for c in config.calendars.values())
    assert config.source.queries[0].organisers == (5,)


def test_defaults(config):
    street = config.calendars["street"]
    assert street.default_duration_hours == 1.5
    assert [p.pattern for p in config.settings.not_event_patterns][1] == r"\bsocks\b"
    assert config.settings.timezone.key == "Australia/Sydney"
    assert config.site.custom_domain == "calendars.example.org"
    assert config.series["street"].organisers == {29}


def test_a_github_io_address_needs_no_cname(tmp_path):
    text = CONFIG.replace("https://calendars.example.org", "https://someone.github.io/calendars")
    assert load_config(write(tmp_path, text)).site.custom_domain is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("[calendars.street]", "[calendars.Street_Series]"), "lower-case"),
        (('series = ["street"]', 'series = ["nope"]'), "undefined series: nope"),
        (('series = ["street"]', 'series = ["street"]\nexclude_series = ["nope"]'),
         "exclude_series refers to undefined series: nope"),
        (("default_duration_hours = 1.5", "default_duration = 1.5"), "unknown key"),
        (('name_patterns = ["state league"]', 'name_patterns = ["(state"]'), "bad regular expr"),
        (("organisers = [5]", "levels = []"), "needs organisers and/or levels"),
        (('base_url = "https://calendars.example.org"', 'base_url = "calendars.example.org"'),
         "https"),
        (("[defaults]", '[defaults]\ncancelled = "hide"'), "'mark' or 'drop'"),
        (("[defaults]", '[classifier]\nmodel = "x"\n\n[defaults]'), "unknown key"),
        (('name_patterns = ["state league"]', "name_patterns = []"), "can never match"),
        (("[site]", '[site]\nwebsite = "example.org"'), r"\[site\].website must be an https"),
    ],
)  # fmt: skip
def test_mistakes_are_refused(tmp_path, change, message):
    assert change[0] in CONFIG
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, CONFIG.replace(change[0], change[1], 1)))


def test_overrides(tmp_path):
    text = CONFIG + (
        '\n[overrides]\n24550 = { not_event = true, note = "ticket" }\n'
        '1 = { series = [] }\n2 = { series = ["street", "sss"] }\n'
    )
    overrides = load_config(write(tmp_path, text)).overrides
    assert overrides[24550].not_event is True and overrides[24550].series is None
    assert overrides[1].series == frozenset() and overrides[1].not_event is None
    assert overrides[2].series == {"street", "sss"}
    for bad, message in [
        ('1 = { series = ["nope"] }', "undefined series"),
        ('1 = { series = "street" }', "must be a list"),
        ('1 = { note = "nothing" }', "sets nothing"),
        ('1 = { kind = "admin" }', "unknown key"),
    ]:
        with pytest.raises(ConfigError, match=message):
            load_config(write(tmp_path, CONFIG + f"\n[overrides]\n{bad}\n"))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")
