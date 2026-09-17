"""One run: pull, sort into series, build every calendar, check it against what is published, write.

The output directory is the published site itself (the ``gh-pages`` checkout in the
workflow), so what is already there is the "previous state" the safety guard
compares against. Nothing is written unless the whole build succeeded and the
guard is satisfied.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from eventor_calendar_sync import site as site_page
from eventor_calendar_sync.calendars import build_entries, matches
from eventor_calendar_sync.config import Config, ConfigError
from eventor_calendar_sync.eventor import EventorSource, SourceError
from eventor_calendar_sync.ics import count_from, render_calendar
from eventor_calendar_sync.models import CalendarEntry, Event
from eventor_calendar_sync.rules import judge_all

log = logging.getLogger(__name__)

MANIFEST = "calendars.json"
GUARD_MIN_PREVIOUS = 5  # small calendars legitimately empty out at the end of a season
UNPLACED_LISTED = 60


@dataclass(slots=True)
class BuildResult:
    report: dict[str, Any]
    summary: str
    written: list[str] = field(default_factory=list)


class GuardError(Exception):
    """A calendar would lose so many upcoming entries that something is probably wrong."""

    def __init__(self, problems: list[str], result: BuildResult):
        super().__init__("; ".join(problems))
        self.problems = problems
        self.result = result  # the report of the build that was not written


def pull(
    config: Config, source: EventorSource, today: date, days_back: int | None = None
) -> list[Event]:
    log.info("fetching organisations")
    names = source.organisations()
    log.info("fetching events")
    events = source.events(
        config.source.queries,
        today - timedelta(days=days_back or config.source.days_back),
        today + timedelta(days=config.source.days_forward),
        names,
    )
    if not events:
        raise SourceError("Eventor returned no events at all; refusing to publish empty calendars")
    return events


def upcoming(event: Event, today: date) -> bool:
    return event.start is None or event.start.date() >= today


def _previous_manifest(out_dir: Path) -> list[str]:
    try:
        data = json.loads((out_dir / MANIFEST).read_text(encoding="utf-8"))
        return [str(c["slug"]) for c in data["calendars"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def run(
    config: Config,
    events: list[Event],
    *,
    out_dir: Path,
    today: date,
    force: bool = False,
    dry_run: bool = False,
) -> BuildResult:
    verdicts = judge_all(events, config)
    uid_domain = urlparse(config.source.base_url).hostname or "eventor"
    entries: dict[str, list[CalendarEntry]] = {}
    placed: set[int] = set()
    for slug, calendar in config.calendars.items():
        entries[slug] = []
        for event in events:
            if matches(calendar, event, verdicts[event.id]):
                placed.add(event.id)
                entries[slug] += build_entries(
                    event, config.settings, uid_domain, calendar.default_duration_hours
                )

    files: dict[str, str] = {}
    calendars_report: dict[str, Any] = {}
    problems: list[str] = []
    for slug, calendar in config.calendars.items():
        link = site_page.links(config.site.base_url, slug, calendar.name)
        text = render_calendar(
            calendar.name,
            calendar.description,
            entries[slug],
            timezone=config.settings.timezone.key,
            url=link.page_url,
        )
        files[f"{slug}.ics"] = text
        now = count_from(text, today)
        previous_file = out_dir / f"{slug}.ics"
        previous = (
            count_from(previous_file.read_text(encoding="utf-8"), today)
            if previous_file.is_file()
            else None
        )
        calendars_report[slug] = {
            "name": calendar.name,
            "entries": len(entries[slug]),
            "upcoming": now,
            "previous_upcoming": previous,
            "url": link.ics_url,
        }
        floor = (previous or 0) * (1 - config.settings.max_shrink_percent / 100)
        if previous is not None and previous >= GUARD_MIN_PREVIOUS and now < floor:
            problems.append(
                f"{slug}: upcoming entries would drop from {previous} to {now} "
                f"(more than {config.settings.max_shrink_percent}%)"
            )

    logo_name = ""
    if config.site.logo:
        logo_source = config.path.parent / config.site.logo
        if not logo_source.is_file():
            raise ConfigError(f"[site].logo not found: {logo_source}")
        logo_name = f"logo{logo_source.suffix.lower()}"
    files["index.html"] = site_page.render_index(
        config.site,
        config.calendars,
        entries,
        today=today,
        timezone=config.settings.timezone,
        source_url=config.source.base_url.removesuffix("/api"),
        logo=logo_name,
    )
    manifest = {
        "calendars": [
            {"slug": slug, "name": c["name"], "url": c["url"], "upcoming": c["upcoming"]}
            for slug, c in calendars_report.items()
        ]
    }
    files[MANIFEST] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    files[".nojekyll"] = ""
    if config.site.custom_domain:
        files["CNAME"] = config.site.custom_domain + "\n"

    removed = [s for s in _previous_manifest(out_dir) if s not in config.calendars]
    # Both lists are in every run's summary, so a pattern that hides a real event, or a
    # renamed series that stopped matching, is noticed the first night.
    not_events = [e for e in events if verdicts[e.id].not_event and upcoming(e, today)]
    unplaced = [
        e
        for e in events
        if e.id not in placed
        and not verdicts[e.id].not_event
        and not e.cancelled
        and upcoming(e, today)
    ]
    report = {
        "ok": not problems or force,
        "date": today.isoformat(),
        "mode": "dry-run" if dry_run else "publish",
        "source": {"events": len(events), "base_url": config.source.base_url},
        "calendars": calendars_report,
        "removed_calendars": removed,
        "guard": problems,
        "overridden": sum(1 for v in verdicts.values() if v.overridden),
        "not_events_upcoming": [
            {"id": e.id, "name": e.name, "because": verdicts[e.id].because} for e in not_events
        ],
        "unplaced_upcoming": {
            "count": len(unplaced),
            "events": [{"id": e.id, "name": e.name} for e in unplaced[:UNPLACED_LISTED]],
        },
    }
    summary = _summary(report)
    if problems and not force:
        raise GuardError(problems, BuildResult(report=report, summary=summary))

    written: list[str] = []
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            path, data = out_dir / name, text.encode("utf-8")
            if not path.is_file() or path.read_bytes() != data:
                path.write_bytes(data)  # bytes: the CRLF line ends of the .ics files must survive
                written.append(name)
        if logo_name:
            shutil.copyfile(config.path.parent / config.site.logo, out_dir / logo_name)
        for slug in removed:
            (out_dir / f"{slug}.ics").unlink(missing_ok=True)
    return BuildResult(report=report, summary=summary, written=written)


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _folded(title: str, items: list[str]) -> list[str]:
    return ["", f"<details><summary>{title}</summary>", "", *items, "", "</details>"]


def _summary(report: dict[str, Any]) -> str:
    """Markdown for the GitHub Actions job summary."""
    lines = [
        f"## Calendars, {report['date']} ({report['mode']})",
        "",
        f"{report['source']['events']} events pulled, {report['overridden']} overridden.",
        "",
        "| Calendar | Upcoming | Was | All entries |",
        "| --- | ---: | ---: | ---: |",
    ]
    for slug, c in report["calendars"].items():
        was = "new" if c["previous_upcoming"] is None else c["previous_upcoming"]
        lines.append(
            f"| {_cell(c['name'])} (`{slug}`) | {c['upcoming']} | {was} | {c['entries']} |"
        )
    if report["guard"]:
        lines += ["", "### Guard", *[f"- {_cell(item)}" for item in report["guard"]]]
    hidden = report["not_events_upcoming"]
    if hidden:
        lines += _folded(
            f"{len(hidden)} upcoming listing(s) treated as not an event",
            [f"- {_cell(e['name'])} ({e['id']}): `{_cell(e['because'])}`" for e in hidden],
        )
    unplaced = report["unplaced_upcoming"]
    if unplaced["count"]:
        lines += _folded(
            f"{unplaced['count']} upcoming event(s) are in no calendar",
            [f"- {_cell(e['name'])} ({e['id']})" for e in unplaced["events"]],
        )
    if report["removed_calendars"]:
        lines += ["", "Removed calendars: " + ", ".join(report["removed_calendars"])]
    return "\n".join(lines) + "\n"
