# eventor-calendar-sync

Turn the events in **Eventor** into calendars people can **subscribe to** in Apple Calendar,
Google Calendar or Outlook: one feed per event series ("Newcastle Summer Street Series", "NSW State
League", "National events"...), plus a branded page with a subscribe button for each.

Every night a GitHub Action pulls the events, sorts them into series, and publishes plain `.ics`
files and the page to GitHub Pages. There is no server, no database and no Google account involved.
Subscribers pick up new events, date changes and cancellations by themselves.

```
$ eventor-calendar-sync build --dry-run
## Calendars, 2026-09-18 (dry-run)

512 events pulled. Classifier: `llm:claude-opus-5`, 509 from cache, 3 newly classified, 1 overridden.

| Calendar | Upcoming | Was | All entries |
| --- | ---: | ---: | ---: |
| NSW State League (`nsw-state-league`) | 4 | 4 | 19 |
| Newcastle Summer Street Series (`newcastle-street-series`) | 18 | 18 | 35 |
...
```

## How it is put together

**This repository is the tool, and only the tool.** It is public and holds no club's settings.

**Each organisation runs it from its own small "runner" repository**, which holds exactly four
things: `config.toml` (which series and calendars to publish, and the page branding),
`classifications.json` (maintained by the tool), one workflow file, and the repository's two
secrets. The workflow installs this tool straight from GitHub at a version you pin, so there is no
code to maintain in the runner. The published site is the runner's `gh-pages` branch.

The runner can be private: GitHub Pages sites are public either way, which is the point. Pages from
a private repository needs a paid GitHub plan; a public runner is free, and nothing in it is
sensitive (the secrets stay in GitHub's secret store either way).

[`examples/runner/`](examples/runner/) is a complete runner to copy, and its
[README](examples/runner/README.md) is the step-by-step setup, including the custom domain.

### One run

1. `GET /events` from Eventor for each `[[source.queries]]`, from `days_back` to `days_forward`.
2. **Classify** every listing: its *kind* (competition, training, social, course, or *admin* for
   things that are not events at all: uniform orders, season tickets, "club communication") and the
   *series* it belongs to. See below.
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

## Classification

Eventor has no series field; the name is the only signal, and names are inconsistent ("SOS" and
"Saturday Orienteering Series", "Queens Park (new map) River and Bay Orienteering Series #5").
So the fuzzy part goes to an LLM (the Claude API), under rules that keep calendars stable and cheap:

- **Classified once.** Answers are stored in `classifications.json`, committed in the runner. A
  listing is sent again only if its details or your series catalogue change. A normal night sends
  nothing or a handful; the first run sends everything (a few hundred listings: about a dollar on
  `claude-opus-5`, cents on `claude-haiku-4-5`).
- **You have the last word.** `[overrides]` in `config.toml` beats the model, per event ID.
- **The model proposes, rules verify.** A series can carry hard `organisers` / `disciplines`
  constraints; a classification that breaks them is dropped and reported.
- **It never blocks publishing.** With no `ANTHROPIC_API_KEY`, or if the API is down, listings
  fall back to each series' `name_patterns` and `admin_name_patterns` for that run and are retried
  the next night. The tool works with no key at all, on patterns alone.
- **It is contained.** The model gets no tools and must answer in a fixed JSON schema, so the
  worst a hostile event description can do is mislabel that one listing. For models behind
  Anthropic's safety classifiers (`claude-opus-5`, `claude-fable-5*`) the request opts in to the
  API's server-side refusal fallback.

Each run's summary (in the Actions run page) lists what was newly classified, with the model's
confidence and reason, plus upcoming events that landed in no calendar: that list is where new
series show up.

`eventor-calendar-sync explore` groups event names and shows what the patterns catch, which is the
quickest way to find series worth a calendar.

## Configuration

See the commented [`examples/runner/config.toml`](examples/runner/config.toml). In short:

| Section | Purpose |
| --- | --- |
| `[site]` | `base_url` (required), title, organisation, intro, `logo`, `accent_color`, contact |
| `[source]`, `[[source.queries]]` | what to pull: by `organisers` (a state association's ID covers its clubs) and/or `levels` |
| `[defaults]` | `timezone`, `default_duration_hours`, `cancelled` (`mark`/`drop`), `max_shrink_percent`, `admin_name_patterns` |
| `[classifier]` | `enabled`, `model`, `effort`, `context` (background for the model), `batch_size` |
| `[series.<slug>]` | `name`, `description` (the model reads it), `name_patterns`, constraint `organisers`/`disciplines` |
| `[calendars.<slug>]` | `name`, `description`, `group`, and criteria: `series`, `organisers`, `disciplines`, `levels`, `kinds`, `name_patterns`, `exclude_name_patterns`, `event_ids`, `exclude_event_ids`; `default_duration_hours` |
| `[overrides]` | `<event id> = { kind = "...", series = "...", note = "..." }` |

Calendar criteria are ANDed, and any value within one criterion may match. `kinds` defaults to
everything except `admin`. Levels: `international`, `championship`, `national`, `state`, `local`,
`club`. Disciplines: `foot`, `mtbo`, `ski`, `trail`, `park-street`. Unknown keys are errors, so a
typo cannot silently switch a filter off.

**A calendar's slug is its address** (`<base_url>/<slug>.ics`). Renaming one breaks every
subscriber's link, so choose them once. Serving the site from a domain you control
(`calendars.yourclub.org`) means the addresses survive a move to another GitHub account, or to
another tool altogether.

Environment: `EVENTOR_API_KEY` (required; any club's key can read events), `ANTHROPIC_API_KEY`
(optional), `EVENTOR_BASE_URL` (optional, another Eventor instance). A `.env` file is loaded if
present.

## Commands

```bash
eventor-calendar-sync build [--config config.toml] [--out public] [--cache classifications.json]
                            [--dry-run] [--no-llm] [--force] [--report report.json]
eventor-calendar-sync explore --config config.toml      # or: --organisers 5
eventor-calendar-sync orgs newcastle                    # look up organiser IDs
eventor-calendar-sync whoami                            # check the Eventor key
```

Exit codes: `0` success, `1` configuration problem, `2` Eventor failure, `4` safety guard refused.
A classifier failure is a warning, not an exit code, because the calendars are still published.
`--dry-run` leaves the site untouched but does save new classifications, since they were paid for.

## Development

```bash
uv sync
cp .env.example .env            # add your Eventor key
cp examples/runner/config.toml config.toml
uv run eventor-calendar-sync build --dry-run --no-llm
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

No test touches the network: Eventor responses come from `tests/fixtures/events.xml` (real public
listings with contact details scrubbed), the Claude client is a fake, and a guard in
`tests/conftest.py` refuses socket connections. Generated calendars are parsed back with the
`icalendar` library to prove they are valid.

Eventor is the only source today, and only [`eventor.py`](src/eventor_calendar_sync/eventor.py)
knows about it. Everything else works on the small model in
[`models.py`](src/eventor_calendar_sync/models.py), so another event system is one new module.

Sibling tools: [eventor-mailchimp-sync](https://github.com/JustinStafford/eventor-mailchimp-sync),
[eventor-contacts-sync](https://github.com/JustinStafford/eventor-contacts-sync).
