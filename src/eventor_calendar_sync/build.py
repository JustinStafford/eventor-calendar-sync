"""One run: pull, classify, build every calendar, check it against what is published, write.

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
from eventor_calendar_sync.classify import Cache, ClassifyResult, LLMClassifier, classify_all
from eventor_calendar_sync.config import Config, ConfigError
from eventor_calendar_sync.eventor import EventorSource, SourceError
from eventor_calendar_sync.ics import count_from, render_calendar
from eventor_calendar_sync.models import CalendarEntry, Event

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


def pull(config: Config, source: EventorSource, today: date) -> list[Event]:
    log.info("fetching organisations")
    names = source.organisations()
    log.info("fetching events")
    events = source.events(
        config.source.queries,
        today - timedelta(days=config.source.days_back),
        today + timedelta(days=config.source.days_forward),
        names,
    )
    if not events:
        raise SourceError("Eventor returned no events at all; refusing to publish empty calendars")
    return events


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
    cache_path: Path,
    llm: LLMClassifier | None,
    today: date,
    force: bool = False,
    dry_run: bool = False,
) -> BuildResult:
    cache = Cache.load(cache_path)
    classified = classify_all(events, config, cache, llm, today)
    if classified.newly_classified or classified.pruned:
        # Saved even on a dry run or a guard refusal: these answers were paid for.
        cache.save(cache_path)

    uid_domain = urlparse(config.source.base_url).hostname or "eventor"
    entries: dict[str, list[CalendarEntry]] = {}
    placed: set[int] = set()
    for slug, calendar in config.calendars.items():
        entries[slug] = []
        for event in events:
            if matches(calendar, event, classified.classifications[event.id]):
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
        upcoming = count_from(text, today)
        previous_file = out_dir / f"{slug}.ics"
        previous = (
            count_from(previous_file.read_text(encoding="utf-8"), today)
            if previous_file.is_file()
            else None
        )
        calendars_report[slug] = {
            "name": calendar.name,
            "entries": len(entries[slug]),
            "upcoming": upcoming,
            "previous_upcoming": previous,
            "url": link.ics_url,
        }
        floor = (previous or 0) * (1 - config.settings.max_shrink_percent / 100)
        if previous is not None and previous >= GUARD_MIN_PREVIOUS and upcoming < floor:
            problems.append(
                f"{slug}: upcoming entries would drop from {previous} to {upcoming} "
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
    by_id = {e.id: e for e in events}
    unplaced = [
        e
        for e in events
        if e.id not in placed
        and classified.classifications[e.id].kind != "admin"
        and not e.cancelled
        and (e.start is None or e.start.date() >= today)
    ]
    # Visible every run, so a pattern that hides a real event is noticed the first night.
    not_events = [
        e
        for e in events
        if classified.classifications[e.id].kind == "admin"
        and (e.start is None or e.start.date() >= today)
    ]
    report = {
        "ok": not problems or force,
        "date": today.isoformat(),
        "mode": "dry-run" if dry_run else "publish",
        "source": {"events": len(events), "base_url": config.source.base_url},
        "classifier": _classifier_report(classified, llm, by_id),
        "calendars": calendars_report,
        "removed_calendars": removed,
        "guard": problems,
        "not_events_upcoming": [{"id": e.id, "name": e.name} for e in not_events],
        "unplaced_upcoming": {
            "count": len(unplaced),
            "events": [
                {
                    "id": e.id,
                    "name": e.name,
                    "series": classified.classifications[e.id].series,
                    "kind": classified.classifications[e.id].kind,
                }
                for e in unplaced[:UNPLACED_LISTED]
            ],
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


def _classifier_report(
    classified: ClassifyResult, llm: LLMClassifier | None, by_id: dict[int, Event]
) -> dict[str, Any]:
    def row(event_id: int) -> dict[str, Any]:
        c = classified.classifications[event_id]
        return {
            "id": event_id,
            "name": by_id[event_id].name,
            "kind": c.kind,
            "series": c.series,
            "confidence": c.confidence,
            "reason": c.reason,
        }

    return {
        "mode": llm.source if llm else "rules",
        "from_cache": classified.cached,
        "new": [row(i) for i in classified.newly_classified],
        "fell_back_to_rules": [row(i) for i in classified.fallback],
        "overrides": sum(1 for c in classified.classifications.values() if c.source == "override"),
        "pruned_from_cache": classified.pruned,
        "notes": classified.notes,
        "errors": classified.errors,
    }


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _summary(report: dict[str, Any]) -> str:
    """Markdown for the GitHub Actions job summary."""
    classifier = report["classifier"]
    lines = [
        f"## Calendars, {report['date']} ({report['mode']})",
        "",
        (
            f"{report['source']['events']} events pulled. Classifier: `{classifier['mode']}`, "
            f"{classifier['from_cache']} from cache, {len(classifier['new'])} newly classified, "
            f"{classifier['overrides']} overridden."
        ),
        "",
        "| Calendar | Upcoming | Was | All entries |",
        "| --- | ---: | ---: | ---: |",
    ]
    for slug, c in report["calendars"].items():
        was = "new" if c["previous_upcoming"] is None else c["previous_upcoming"]
        lines.append(
            f"| {_cell(c['name'])} (`{slug}`) | {c['upcoming']} | {was} | {c['entries']} |"
        )
    for title, key in (("Guard", "guard"), ("Classifier errors", "errors"), ("Notes", "notes")):
        items = report[key] if key == "guard" else classifier[key]
        if items:
            lines += ["", f"### {title}", *[f"- {_cell(item)}" for item in items]]
    if classifier["fell_back_to_rules"]:
        lines += [
            "",
            (
                f"{len(classifier['fell_back_to_rules'])} listing(s) used the name-pattern "
                "rules because the model was unavailable; they are retried on the next run."
            ),
        ]
    if classifier["new"]:
        lines += [
            "",
            "### Newly classified",
            "| Event | Kind | Series | Confidence | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
        ordered = sorted(classifier["new"], key=lambda r: (r["confidence"] == "high", r["name"]))
        lines += [
            f"| {_cell(r['name'])} ({r['id']}) | {r['kind']} | {_cell(r['series'] or '')} | "
            f"{r['confidence']} | {_cell(r['reason'])} |"
            for r in ordered[:200]
        ]
    if report["not_events_upcoming"]:
        hidden = report["not_events_upcoming"]
        lines += [
            "",
            (
                f"<details><summary>{len(hidden)} upcoming listing(s) treated as not an event"
                "</summary>"
            ),
            "",
            *[f"- {_cell(e['name'])} ({e['id']})" for e in hidden],
            "",
            "</details>",
        ]
    unplaced = report["unplaced_upcoming"]
    if unplaced["count"]:
        lines += [
            "",
            f"<details><summary>{unplaced['count']} upcoming event(s) are in no calendar</summary>",
            "",
            *[f"- {_cell(e['name'])} ({e['id']})" for e in unplaced["events"]],
            "",
            "</details>",
        ]
    if report["removed_calendars"]:
        lines += ["", "Removed calendars: " + ", ".join(report["removed_calendars"])]
    return "\n".join(lines) + "\n"
