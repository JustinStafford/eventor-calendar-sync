"""The pattern review: everything needed to judge whether the name patterns still fit.

Patterns are written against last season's names, and organisers rename things. This
report puts the four questions worth asking side by side. It changes nothing; the
person (or Claude Code session) reading it edits ``config.toml``. The procedure is
in the README under "Keeping the patterns current".
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date

from eventor_calendar_sync.build import upcoming
from eventor_calendar_sync.config import Config
from eventor_calendar_sync.models import Event
from eventor_calendar_sync.rules import judge_all

STEM_YEAR = re.compile(r"\b20\d\d(\s*/\s*\d\d(\d\d)?)?\b|\b\d\d/\d\d\b")
STEM_ORDINAL = re.compile(r"(#|\b(no|event|round|race|day|week)\.?)?\s*\d+\b", re.IGNORECASE)


def stem(name: str) -> str:
    """The part of an event name that a series' rounds tend to share."""
    text = re.split(r"\s[-\u2013\u2014]\s", name, maxsplit=1)[0]
    text = STEM_ORDINAL.sub(" ", STEM_YEAR.sub(" ", text))
    return " ".join(text.split()).strip(" -:#,.").lower()


def name_groups(events: list[Event]) -> list[tuple[str, list[Event]]]:
    groups: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        groups[stem(event.name)].append(event)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def organisers_of(events: list[Event]) -> str:
    counts = Counter(f"{o.name or 'organisation'} ({o.id})" for e in events for o in e.organisers)
    return ", ".join(name for name, _ in counts.most_common(2))


def in_scope(config: Config) -> frozenset[int]:
    """Organisers the config cares about; interstate events pulled for a national
    calendar are not candidates for new local series."""
    ids: set[int] = set()
    for calendar in config.calendars.values():
        ids |= calendar.organisers
    for series in config.series.values():
        ids |= series.organisers
    return frozenset(ids)


def render(
    config: Config,
    events: list[Event],
    today: date,
    *,
    minimum: int = 3,
    show_all: bool = False,
    brief: bool = False,
) -> str:
    """The full report, or with ``brief`` the weekly digest: one line per series, only the
    upcoming listings hidden as not-an-event, and no one-offs."""
    verdicts = judge_all(events, config)
    first = min((e.start.date() for e in events if e.start), default=today)
    last = max((e.start.date() for e in events if e.start), default=today)
    title = "Pattern digest" if brief else "Pattern review"
    out = [f"{title}, {today}: {len(events)} listings from {first} to {last}", ""]

    out += ["1. WHAT EACH SERIES CAUGHT", "   Look for listings that do not belong.", ""]
    quiet: list[str] = []
    for slug in config.series:
        members = [e for e in events if slug in verdicts[e.id].series]
        ahead = [e for e in members if upcoming(e, today) and not verdicts[e.id].not_event]
        out.append(f"   {slug}: {len(members)} listings, {len(ahead)} upcoming")
        if not brief:
            for key, group in name_groups(members)[:15]:
                flag = "  (not an event)" if all(verdicts[e.id].not_event for e in group) else ""
                out.append(f"      {len(group):4d}  {key}{flag}")
            out.append("")
        if not ahead:
            latest = max((e.start.date() for e in members if e.start), default=None)
            quiet.append(f"   {slug}: " + (f"last listing {latest}" if latest else "never matched"))
    if brief:
        out.append("")

    out += [
        "2. TREATED AS NOT AN EVENT" + (" (UPCOMING)" if brief else ""),
        "   Look for real events hidden by a loose pattern.",
        "",
    ]
    hidden = [e for e in events if verdicts[e.id].not_event and (upcoming(e, today) or not brief)]
    out += [f"   {e.id:>6}  {e.name}   <- {verdicts[e.id].because}" for e in hidden] or [
        "   (none)"
    ]
    out.append("")

    scope = in_scope(config)
    loose = [
        e
        for e in events
        if not verdicts[e.id].series
        and not verdicts[e.id].not_event
        and (not scope or e.organiser_ids & scope)
    ]
    out += [
        f"3. IN NO SERIES: NAME GROUPS OF {minimum}+",
        "   Each is a renamed or abbreviated round of an existing series, a series worth",
        "   adding, junk for not_event_patterns, or nothing (one-offs with similar names).",
        "",
    ]
    groups = name_groups(loose)
    big = [(key, group) for key, group in groups if len(group) >= minimum]
    out += [f"      {len(g):4d}  {key:<48} {organisers_of(g)}" for key, g in big] or ["   (none)"]
    out.append("")

    out += ["4. SERIES WITH NOTHING UPCOMING", "   Season over, or renamed?", ""]
    out += quiet or ["   (none)"]
    out.append("")

    small = [e for key, group in groups if len(group) < minimum for e in group]
    if show_all and not brief:
        out += ["5. IN NO SERIES: EVERYTHING ELSE", "   Mostly one-offs. Scan for junk.", ""]
        out += [f"   {e.id:>6}  {e.name}" for e in sorted(small, key=lambda e: e.name.lower())]
    elif brief:
        out.append(
            f"({len(small)} other listings are in no series. For the full report run "
            '`eventor-calendar-sync review --all`, or say "review the patterns" in Claude Code.)'
        )
    else:
        out.append(f"({len(small)} other listings are in no series; --all lists them.)")
    return "\n".join(out) + "\n"
