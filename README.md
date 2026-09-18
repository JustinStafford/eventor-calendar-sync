# eventor-calendar-sync

Turn the events in **Eventor** into calendars people can **subscribe to** in Apple Calendar,
Google Calendar or Outlook: one feed per event series ("Newcastle Summer Street Series", "NSW State
League", "National events"...), plus a branded page with the instructions and a subscribe button
for each.

Every night a GitHub Action pulls the events, sorts them into series, and publishes plain `.ics`
files and the page to GitHub Pages. There is no server, no database and no account with anyone but
GitHub. Subscribers pick up new events, date changes and cancellations by themselves.

```
$ eventor-calendar-sync build --dry-run
## Calendars, 2026-09-18 (dry-run)

565 events pulled, 2 overridden.

| Calendar | Upcoming | Was | All entries |
| --- | ---: | ---: | ---: |
| NSW State League (`nsw-state-league`) | 14 | 14 | 30 |
| Newcastle Summer Street Series (`newcastle-street-series`) | 18 | 18 | 36 |
...
```

## How it is put together

**This repository is the tool, and only the tool.** It is public and holds no club's settings.

**Each organisation runs it from its own small "runner" repository**, which holds `config.toml`
(which series and calendars to publish, and the page branding), two workflow files (the nightly
publish and a weekly digest), a `CLAUDE.md` that tells a Claude Code session how to look after
the patterns, and one secret: an Eventor API key. The workflows install this tool straight from
GitHub at a version you pin, so there is no code to maintain in the runner. The published site is the runner's `gh-pages` branch: the page at its
root, the calendars beside it as `<slug>.ics`.

The runner can be private: GitHub Pages sites are public either way, which is the point. Pages from
a private repository needs a paid GitHub plan; a public runner is free, and nothing in it is
sensitive.

[`examples/runner/`](examples/runner/) is a complete runner to copy, and its
[README](examples/runner/README.md) is the step-by-step setup, including the custom domain.

### One run

1. `GET /events` from Eventor for each `[[source.queries]]`, from `days_back` to `days_forward`.
2. Sort every listing into series by its name, and set aside the listings that are not events at
   all (uniform orders, season tickets, "club communication").
3. For each calendar, take the events matching its criteria and write one entry **per race**, so a
   three-day carnival is three entries, each with its own time and map pin.
4. Compare with what is already published. If a calendar would lose more than
   `max_shrink_percent` of its upcoming entries, or Eventor returned nothing, **nothing is
   written** and the run fails (exit code 4; `--force` overrides).
5. Write `<slug>.ics` for each calendar, `index.html`, and `calendars.json`. Output is
   deterministic, so files only change when an event does, and the `gh-pages` history is a log of
   every change ever published.

### What a calendar entry holds

| | |
| --- | --- |
| Title | the event name, plus the race name for multi-race events; `CANCELLED: ` in front if so |
| Time | Eventor's start and finish. No finish: `default_duration_hours`. No start time (Eventor stores midnight), or 18 hours and longer: an all-day entry |
| Location | the assembly area's GPS position, which phones and cars can navigate to |
| Description | organising club, discipline and distance, the Eventor link, the event website |
| Identity | a stable UID per race, so calendar apps update entries rather than duplicating them |

## Series are name patterns

Eventor has no series field. The event name is the only signal, so a series is a list of
case-insensitive regular expressions searched for in the name:

```toml
[series.saturday-orienteering-series]
name = "Saturday Orienteering Series (SOS)"
description = "Saturday events for newcomers and families around Sydney."
name_patterns = ['\bSOS\b', 'saturday orienteering series']
organisers = [647]          # hard constraint: only this organiser's events can match
```

- A listing may belong to **several series** ("NSW State League #11 - NSW Schools Champs").
- `organisers` and `disciplines` are **hard constraints**, so a short acronym cannot pick up
  another club's events. `exclude_name_patterns` carve out exceptions.
- `[defaults].not_event_patterns` hide the listings that are not events.
- `[overrides]` settles any single listing by its Eventor event ID.
- Calendars that need no judgement need no patterns: "everything this club organises" and
  "every national-level event" are facts in the data (`organisers`, `levels`, `disciplines`).

Nothing is inferred at run time, on purpose: the nightly job is deterministic and has no
dependencies to fail. Checked against a year of NSW listings (490 of them), one careful pass over
the patterns sorted 21 series with no wrong matches and no missed rounds found on review. The
judgement goes in when the patterns are **reviewed**, which is the one piece of upkeep this tool
asks for.

## Keeping the patterns current

Patterns are written against last season's names, and organisers rename things. The failure is
quiet, never dramatic: a renamed series stops gaining events, or a new kind of junk listing turns
up in an "all events" calendar. Review the patterns **at each season launch, whenever a run summary
shows surprises, and when someone reports a missing event**. It takes minutes.

```bash
eventor-calendar-sync review --config config.toml          # add --all for the one-offs too
```

The report changes nothing. It asks four questions:

| Section | The question | The usual fix |
| --- | --- | --- |
| 1. What each series caught | Does anything here not belong? | tighten the pattern, add an `organisers` constraint or an `exclude_name_patterns` entry |
| 2. Treated as not an event | Is a real event hidden? It shows the pattern responsible | tighten it: `'singlet'` also hides every event at Singleton, `'\bsinglets?\b'` does not |
| 3. In no series: name groups | A renamed round of an existing series? A new series? Junk? | add an alternative to `name_patterns`; add a series and calendar; add to `not_event_patterns`; or leave it |
| 4. Series with nothing upcoming | Season over, or renamed so that nothing matches any more? | check section 3 for its new name |

Then run `review` again until it reads clean, run `build --dry-run`, and compare each calendar's
*Upcoming* with *Was*.

**The weekly digest** (`review --brief`) is the short form: one line per series, only the upcoming
hidden listings, the unmatched name groups and the quiet series. The runner's second workflow
posts it every Monday as a comment on a GitHub issue, and GitHub emails it to the issue's
assignee: ongoing visibility with no mail server and no extra secret. Most weeks it needs no
action.

**This is a good job for a Claude Code session**, and the runner's
[`CLAUDE.md`](examples/runner/CLAUDE.md) is written for one: open the runner repository, say
"review the patterns", and it runs the report, proposes the `config.toml` changes with its
reasoning, and waits for your say-so before committing. Judging whether "SummerSaturdays #2"
belongs with "Summer Saturdays #3" is exactly what it is good at; doing so once, in a change you
read, is better than having a model decide silently every night.

Every nightly run also lists, in its summary, the upcoming listings it treated as not an event and
the upcoming events that are in no calendar, so drift shows up without anyone running anything.

## Configuration

See the commented [`examples/runner/config.toml`](examples/runner/config.toml). In short:

| Section | Purpose |
| --- | --- |
| `[site]` | `base_url` (required), title, organisation, intro, `logo`, `accent_color`, contact |
| `[source]`, `[[source.queries]]` | what to pull: by `organisers` (a state association's ID covers its clubs) and/or `levels` |
| `[defaults]` | `timezone`, `default_duration_hours`, `cancelled` (`mark`/`drop`), `max_shrink_percent`, `not_event_patterns` |
| `[series.<slug>]` | `name`, `description` (for the next reviewer), `name_patterns`, `exclude_name_patterns`, constraint `organisers`/`disciplines` |
| `[calendars.<slug>]` | `name`, `description`, `group`, and criteria: `series`, `organisers`, `disciplines`, `levels`, `name_patterns`, `exclude_name_patterns`, `event_ids`, `exclude_event_ids`; `default_duration_hours` |
| `[overrides]` | `<event id> = { series = ["..."], not_event = true, note = "..." }` |

Calendar criteria are ANDed, and any value within one criterion may match. Levels:
`international`, `championship`, `national`, `state`, `local`, `club`. Disciplines: `foot`, `mtbo`,
`ski`, `trail`, `park-street`. Write patterns in single quotes (TOML literal strings) so that
backslashes mean what they say. Unknown keys are errors, so a typo cannot silently switch a filter
off.

**A calendar's slug is its address** (`<base_url>/<slug>.ics`). Renaming one breaks every
subscriber's link, so choose them once. Serving the site from a domain you control
(`calendars.yourclub.org`) means the addresses survive a move to another GitHub account, or to
another tool altogether.

Environment: `EVENTOR_API_KEY` (required; any club's key can read events), `EVENTOR_BASE_URL`
(optional, another Eventor instance). A `.env` file is loaded if present.

## Commands

```bash
eventor-calendar-sync build   [--config config.toml] [--out public] [--dry-run] [--force] [--report report.json]
eventor-calendar-sync review  [--config config.toml] [--all | --brief] [--min 3] [--days-back 365]
eventor-calendar-sync explore 5              # before there is a config: name groups for an organiser
eventor-calendar-sync orgs newcastle         # look up organiser IDs
eventor-calendar-sync whoami                 # check the Eventor key
```

Exit codes: `0` success, `1` configuration problem, `2` Eventor failure, `4` safety guard refused.

## Development

```bash
uv sync
cp .env.example .env            # add your Eventor key
cp examples/runner/config.toml config.toml
uv run eventor-calendar-sync build --dry-run
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

No test touches the network: Eventor responses come from `tests/fixtures/events.xml` (real public
listings with contact details scrubbed), and a guard in `tests/conftest.py` refuses socket
connections. Generated calendars are parsed back with the `icalendar` library to prove they are
valid.

Eventor is the only source today, and only [`eventor.py`](src/eventor_calendar_sync/eventor.py)
knows about it. Everything else works on the small model in
[`models.py`](src/eventor_calendar_sync/models.py), so another event system is one new module.

Sibling tools: [eventor-mailchimp-sync](https://github.com/JustinStafford/eventor-mailchimp-sync),
[eventor-contacts-sync](https://github.com/JustinStafford/eventor-contacts-sync).
