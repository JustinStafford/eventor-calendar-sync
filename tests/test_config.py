from __future__ import annotations

from pathlib import Path

import pytest

from eventor_calendar_sync.config import DEFAULT_KINDS, ConfigError, load_config
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
    assert street.kinds == DEFAULT_KINDS and "admin" not in street.kinds
    assert street.default_duration_hours == 1.5
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
        (("default_duration_hours = 1.5", "default_duration = 1.5"), "unknown key"),
        (('name_patterns = ["state league"]', 'name_patterns = ["(state"]'), "bad regular expr"),
        (("organisers = [5]", "levels = []"), "needs organisers and/or levels"),
        (('base_url = "https://calendars.example.org"', 'base_url = "calendars.example.org"'),
         "https"),
        (("[defaults]", '[defaults]\ncancelled = "hide"'), "'mark' or 'drop'"),
    ],
)  # fmt: skip
def test_mistakes_are_refused(tmp_path, change, message):
    assert change[0] in CONFIG
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, CONFIG.replace(change[0], change[1], 1)))


def test_overrides(tmp_path):
    text = (
        CONFIG + '\n[overrides]\n24550 = { kind = "admin", note = "ticket" }\n1 = { series = "" }\n'
    )
    overrides = load_config(write(tmp_path, text)).overrides
    assert overrides[24550].kind == "admin" and overrides[24550].series is None
    assert overrides[1].series == ""
    with pytest.raises(ConfigError, match="undefined series"):
        load_config(write(tmp_path, CONFIG + '\n[overrides]\n1 = { series = "nope" }\n'))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.toml")
