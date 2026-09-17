"""``config.toml``: which events to pull, the series catalogue, the calendars and the site.

The file holds no secrets and is meant to be committed to the runner repository.
The one secret, ``EVENTOR_API_KEY``, comes from the environment. Unknown keys are
rejected so that a typo cannot silently turn a filter off.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from eventor_calendar_sync.eventor import AU_BASE_URL, Query
from eventor_calendar_sync.models import DISCIPLINES, LEVELS

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ConfigError(Exception):
    """``config.toml`` is missing, malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class SeriesDef:
    slug: str
    name: str
    description: str = ""
    name_patterns: tuple[re.Pattern[str], ...] = ()
    exclude_name_patterns: tuple[re.Pattern[str], ...] = ()
    # Hard constraints: a name match only counts if they hold.
    organisers: frozenset[int] = frozenset()
    disciplines: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CalendarDef:
    slug: str
    name: str
    description: str = ""
    group: str = ""
    series: frozenset[str] = frozenset()
    organisers: frozenset[int] = frozenset()
    disciplines: frozenset[str] = frozenset()
    levels: frozenset[str] = frozenset()
    name_patterns: tuple[re.Pattern[str], ...] = ()
    exclude_name_patterns: tuple[re.Pattern[str], ...] = ()
    event_ids: frozenset[int] = frozenset()
    exclude_event_ids: frozenset[int] = frozenset()
    default_duration_hours: float | None = None


@dataclass(frozen=True, slots=True)
class Override:
    series: frozenset[str] | None = None  # replaces whatever the patterns said; [] means none
    not_event: bool | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class Settings:
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Australia/Sydney"))
    default_duration_hours: float = 3.0
    cancelled: str = "mark"  # mark | drop
    # Listings that are not events at all: uniform orders, season tickets, placeholders...
    not_event_patterns: tuple[re.Pattern[str], ...] = ()
    max_shrink_percent: int = 40


@dataclass(frozen=True, slots=True)
class SourceDef:
    base_url: str = AU_BASE_URL
    queries: tuple[Query, ...] = ()
    days_back: int = 180
    days_forward: int = 730


@dataclass(frozen=True, slots=True)
class SiteDef:
    base_url: str = ""
    title: str = "Orienteering calendars"
    organisation: str = ""
    intro: str = ""
    logo: str = ""  # path relative to config.toml; copied into the site
    accent_color: str = "#0b6b3a"
    contact: str = ""

    @property
    def custom_domain(self) -> str | None:
        host = urlparse(self.base_url).hostname or ""
        return host if host and not host.endswith(".github.io") else None


@dataclass(frozen=True, slots=True)
class Config:
    path: Path
    source: SourceDef
    settings: Settings
    site: SiteDef
    series: dict[str, SeriesDef] = field(default_factory=dict)
    calendars: dict[str, CalendarDef] = field(default_factory=dict)
    overrides: dict[int, Override] = field(default_factory=dict)


# -- helpers ---------------------------------------------------------------------


def _table(data: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{where}[{key}] must be a table")
    return value


def _check_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})"
        )


def _patterns(values: Any, where: str) -> tuple[re.Pattern[str], ...]:
    if not isinstance(values, list):
        raise ConfigError(f"{where} must be a list of regular expressions")
    compiled = []
    for value in values:
        try:
            compiled.append(re.compile(str(value), re.IGNORECASE))
        except re.error as exc:
            raise ConfigError(f"{where}: bad regular expression {value!r}: {exc}") from exc
    return tuple(compiled)


def _ints(values: Any, where: str) -> frozenset[int]:
    if not isinstance(values, list) or not all(isinstance(v, int) for v in values):
        raise ConfigError(f"{where} must be a list of integers")
    return frozenset(values)


def _choices(values: Any, allowed: tuple[str, ...], where: str) -> frozenset[str]:
    if not isinstance(values, list):
        raise ConfigError(f"{where} must be a list")
    chosen = frozenset(str(v) for v in values)
    bad = sorted(chosen - set(allowed))
    if bad:
        raise ConfigError(f"{where}: unknown value(s) {', '.join(bad)} (use: {', '.join(allowed)})")
    return chosen


def _disciplines(values: Any, where: str) -> frozenset[str]:
    """Discipline names, or a bare Eventor discipline ID for ones this tool has no name for."""
    if not isinstance(values, list):
        raise ConfigError(f"{where} must be a list")
    chosen = frozenset(str(v) for v in values)
    bad = sorted(v for v in chosen if v not in DISCIPLINES and not v.isdigit())
    if bad:
        raise ConfigError(
            f"{where}: unknown discipline(s) {', '.join(bad)} (use: {', '.join(DISCIPLINES)})"
        )
    return chosen


def _slug(slug: str, where: str) -> str:
    if not SLUG.match(slug):
        raise ConfigError(
            f"{where}: {slug!r} must be lower-case letters, digits and hyphens "
            "(it becomes a file name and a link)"
        )
    return slug


# -- sections --------------------------------------------------------------------


def _source(table: dict[str, Any]) -> SourceDef:
    _check_keys(table, {"base_url", "queries", "days_back", "days_forward"}, "[source]")
    queries = []
    for i, raw in enumerate(table.get("queries", []), 1):
        where = f"[[source.queries]] #{i}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be a table")
        _check_keys(raw, {"organisers", "levels"}, where)
        query = Query(
            organisers=tuple(sorted(_ints(raw.get("organisers", []), f"{where}.organisers"))),
            levels=tuple(sorted(_choices(raw.get("levels", []), LEVELS, f"{where}.levels"))),
        )
        if not query.organisers and not query.levels:
            raise ConfigError(f"{where} needs organisers and/or levels (it would pull everything)")
        queries.append(query)
    if not queries:
        raise ConfigError("[source] needs at least one [[source.queries]] table")
    base_url = str(table.get("base_url") or AU_BASE_URL).rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigError(f"[source].base_url must be an https URL, got {base_url!r}")
    return SourceDef(
        base_url=base_url,
        queries=tuple(queries),
        days_back=int(table.get("days_back", 180)),
        days_forward=int(table.get("days_forward", 730)),
    )


def _settings(table: dict[str, Any]) -> Settings:
    allowed = {"timezone", "default_duration_hours", "cancelled", "not_event_patterns",
               "max_shrink_percent"}  # fmt: skip
    _check_keys(table, allowed, "[defaults]")
    try:
        timezone = ZoneInfo(str(table.get("timezone", "Australia/Sydney")))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"[defaults].timezone: {exc}") from exc
    cancelled = str(table.get("cancelled", "mark"))
    if cancelled not in {"mark", "drop"}:
        raise ConfigError("[defaults].cancelled must be 'mark' or 'drop'")
    shrink = int(table.get("max_shrink_percent", 40))
    if not 0 <= shrink <= 100:
        raise ConfigError("[defaults].max_shrink_percent must be between 0 and 100")
    return Settings(
        timezone=timezone,
        default_duration_hours=float(table.get("default_duration_hours", 3.0)),
        cancelled=cancelled,
        not_event_patterns=_patterns(
            table.get("not_event_patterns", []), "[defaults].not_event_patterns"
        ),
        max_shrink_percent=shrink,
    )


def _site(table: dict[str, Any]) -> SiteDef:
    allowed = {"base_url", "title", "organisation", "intro", "logo", "accent_color", "contact"}
    _check_keys(table, allowed, "[site]")
    base_url = str(table.get("base_url", "")).rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigError(
            "[site].base_url is required and must be the https address the site is served from, "
            "for example https://calendars.example.org"
        )
    accent = str(table.get("accent_color", "#0b6b3a"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise ConfigError("[site].accent_color must look like #0b6b3a")
    return SiteDef(
        base_url=base_url,
        title=str(table.get("title", "Orienteering calendars")),
        organisation=str(table.get("organisation", "")),
        intro=str(table.get("intro", "")).strip(),
        logo=str(table.get("logo", "")),
        accent_color=accent,
        contact=str(table.get("contact", "")),
    )


def _series(tables: dict[str, Any]) -> dict[str, SeriesDef]:
    result = {}
    for slug, raw in tables.items():
        where = f"[series.{slug}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be a table")
        allowed = {"name", "description", "name_patterns", "exclude_name_patterns", "organisers",
                   "disciplines"}  # fmt: skip
        _check_keys(raw, allowed, where)
        if not raw.get("name"):
            raise ConfigError(f"{where} needs a name")
        if not raw.get("name_patterns"):
            raise ConfigError(f"{where} needs name_patterns: without them it can never match")
        result[_slug(slug, where)] = SeriesDef(
            slug=slug,
            name=str(raw["name"]),
            description=str(raw.get("description", "")).strip(),
            name_patterns=_patterns(raw["name_patterns"], f"{where}.name_patterns"),
            exclude_name_patterns=_patterns(
                raw.get("exclude_name_patterns", []), f"{where}.exclude_name_patterns"
            ),
            organisers=_ints(raw.get("organisers", []), f"{where}.organisers"),
            disciplines=_disciplines(raw.get("disciplines", []), f"{where}.disciplines"),
        )
    return result


def _calendars(tables: dict[str, Any], series: dict[str, SeriesDef]) -> dict[str, CalendarDef]:
    allowed = {"name", "description", "group", "series", "organisers", "disciplines", "levels",
               "name_patterns", "exclude_name_patterns", "event_ids", "exclude_event_ids",
               "default_duration_hours"}  # fmt: skip
    result = {}
    for slug, raw in tables.items():
        where = f"[calendars.{slug}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be a table")
        _check_keys(raw, allowed, where)
        if not raw.get("name"):
            raise ConfigError(f"{where} needs a name")
        wanted = frozenset(str(s) for s in raw.get("series", []))
        missing = sorted(wanted - set(series))
        if missing:
            raise ConfigError(f"{where}.series refers to undefined series: {', '.join(missing)}")
        duration = raw.get("default_duration_hours")
        result[_slug(slug, where)] = CalendarDef(
            slug=slug,
            name=str(raw["name"]),
            description=str(raw.get("description", "")).strip(),
            group=str(raw.get("group", "")),
            series=wanted,
            organisers=_ints(raw.get("organisers", []), f"{where}.organisers"),
            disciplines=_disciplines(raw.get("disciplines", []), f"{where}.disciplines"),
            levels=_choices(raw.get("levels", []), LEVELS, f"{where}.levels"),
            name_patterns=_patterns(raw.get("name_patterns", []), f"{where}.name_patterns"),
            exclude_name_patterns=_patterns(
                raw.get("exclude_name_patterns", []), f"{where}.exclude_name_patterns"
            ),
            event_ids=_ints(raw.get("event_ids", []), f"{where}.event_ids"),
            exclude_event_ids=_ints(raw.get("exclude_event_ids", []), f"{where}.exclude_event_ids"),
            default_duration_hours=float(duration) if duration is not None else None,
        )
    if not result:
        raise ConfigError("no [calendars.<slug>] tables: there is nothing to publish")
    return result


def _overrides(tables: dict[str, Any], series: dict[str, SeriesDef]) -> dict[int, Override]:
    result = {}
    for key, raw in tables.items():
        where = f"[overrides].{key}"
        if not key.isdigit() or not isinstance(raw, dict):
            raise ConfigError(f'{where}: use <event id> = {{ series = ["..."], not_event = true }}')
        _check_keys(raw, {"series", "not_event", "note"}, where)
        chosen = raw.get("series")
        if chosen is not None:
            if not isinstance(chosen, list):
                raise ConfigError(f"{where}.series must be a list of series slugs ([] for none)")
            missing = sorted(set(map(str, chosen)) - set(series))
            if missing:
                raise ConfigError(
                    f"{where}.series refers to undefined series: {', '.join(missing)}"
                )
            chosen = frozenset(str(c) for c in chosen)
        not_event = raw.get("not_event")
        if not_event is not None and not isinstance(not_event, bool):
            raise ConfigError(f"{where}.not_event must be true or false")
        if chosen is None and not_event is None:
            raise ConfigError(f"{where} sets nothing: give series and/or not_event")
        result[int(key)] = Override(
            series=chosen, not_event=not_event, note=str(raw.get("note", ""))
        )
    return result


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    sections = {"source", "defaults", "site", "series", "calendars", "overrides"}
    _check_keys(data, sections, str(path))
    series = _series(_table(data, "series", str(path)))
    return Config(
        path=path,
        source=_source(_table(data, "source", str(path))),
        settings=_settings(_table(data, "defaults", str(path))),
        site=_site(_table(data, "site", str(path))),
        series=series,
        calendars=_calendars(_table(data, "calendars", str(path)), series),
        overrides=_overrides(_table(data, "overrides", str(path)), series),
    )
