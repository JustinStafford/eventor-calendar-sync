"""Which series a listing belongs to, and whether it is an event at all.

Eventor has no series field, and clubs also use it for things that are not events
(uniform orders, season tickets, "club communication"). The event name is the only
signal, so series are defined by name patterns in ``config.toml``.

Nothing is inferred at run time, on purpose: the nightly job is deterministic, and
the judgement goes in when the patterns are reviewed (``eventor-calendar-sync
review``, see the README). Three things keep patterns honest:

* a series can carry hard ``organisers``/``disciplines`` constraints, so a short
  acronym cannot pick up another club's events;
* ``exclude_name_patterns`` carve exceptions out of a series;
* ``[overrides]`` settles any single listing by its event ID.

A listing may belong to several series ("NSW State League #11 - NSW Schools Champs").
"""

from __future__ import annotations

from eventor_calendar_sync.config import Config, SeriesDef
from eventor_calendar_sync.models import Event, Verdict


def in_series(series: SeriesDef, event: Event) -> bool:
    if not any(p.search(event.name) for p in series.name_patterns):
        return False
    if any(p.search(event.name) for p in series.exclude_name_patterns):
        return False
    if series.organisers and not (event.organiser_ids & series.organisers):
        return False
    return not series.disciplines or bool(set(event.disciplines) & series.disciplines)


def judge(event: Event, config: Config) -> Verdict:
    because = next(
        (p.pattern for p in config.settings.not_event_patterns if p.search(event.name)), ""
    )
    series = frozenset(s.slug for s in config.series.values() if in_series(s, event))
    override = config.overrides.get(event.id)
    if override is None:
        return Verdict(series=series, not_event=bool(because), because=because)
    not_event = bool(because) if override.not_event is None else override.not_event
    return Verdict(
        series=series if override.series is None else override.series,
        not_event=not_event,
        because=(because if not_event else "") or "[overrides]",
        overridden=True,
    )


def judge_all(events: list[Event], config: Config) -> dict[int, Verdict]:
    return {event.id: judge(event, config) for event in events}
