# eventor-calendar-sync

A Python tool that pulls events from Eventor (orienteering's event system), sorts them into series
by **name patterns**, and writes one subscribable `.ics` file per calendar plus a landing page, for
a nightly GitHub Action to publish on GitHub Pages. The README is the full description.

## Two repositories

- **This one is the tool**: public, no organisation's settings, no secrets.
- **Each organisation has a "runner" repository** holding its `config.toml`, the workflow, and a
  `CLAUDE.md`. [`examples/runner/`](examples/runner/) is the template they copy. The ONSW runner is
  separate and private.

**Reviewing or updating name patterns is runner work.** The procedure is in
[`examples/runner/CLAUDE.md`](examples/runner/CLAUDE.md); follow it there, against the runner's
`config.toml`. In *this* repository the only patterns are the starter set in
`examples/runner/config.toml`. To refresh those, follow the same procedure with
`uv run eventor-calendar-sync review -c examples/runner/config.toml`.

## Decisions that are not up for re-litigation

- **No LLM or other inference at run time.** An optional Claude API classifier was built and
  deliberately removed (it is in git history, commit `684978c`). Patterns measured well, the job
  stays deterministic and dependency-free, and judgement is applied at review time by a person or
  a Claude Code session, in a change someone reads.
- **Static files on GitHub Pages, not Google Calendar.** No accounts, no auth.
- **Keep it simple and standalone.** No shared library with the sibling tools
  (eventor-mailchimp-sync, eventor-contacts-sync). Eventor is expected to be replaced within about
  a year, so `eventor.py` is the only module that knows about it; everything else uses
  `models.py`.
- **Output is deterministic.** No timestamps of "now" in the `.ics` files (`DTSTAMP` is the
  event's modification time). Files change only when events do.
- **A calendar's slug is a public address.** Never rename slugs in the example config casually;
  real runners were copied from it.

## Layout

```
src/eventor_calendar_sync/
  eventor.py     GET /events -> models.Event   (stdlib HTTP; needs a custom User-Agent)
  config.py      config.toml -> dataclasses; unknown keys are errors
  rules.py       name patterns -> Verdict(series, not_event)
  calendars.py   which events a calendar takes; one CalendarEntry per race
  ics.py         deterministic RFC 5545 writer
  site.py        landing page (templates/index.html.j2), subscribe links, QR codes
  build.py       one run: judge, build, safety guard, write, report
  review.py      the pattern review report
  cli.py         build | review | explore | orgs | whoami
examples/runner/ what an organisation copies: config.toml, publish.yml, CLAUDE.md, README.md
tests/           no network; fixtures/events.xml is real public data with contacts scrubbed
```

## Working here

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run eventor-calendar-sync build --dry-run      # needs .env (EVENTOR_API_KEY) and config.toml
```

- Local `config.toml`, `public/` and `.env` are git-ignored. Preview a built site with the
  `site-preview` launch configuration (serves `public/` on port 8123).
- If a CLI flag or config key changes, update `examples/runner/` (workflow, config, CLAUDE.md,
  README) and the README's tables in the same change: runners copy those files.
- Event names and descriptions are untrusted text typed by any organiser. The page escapes them
  (Jinja2 autoescape); keep it that way.
- In `.env`, the old `API_KEY` line belongs to the retired Google Calendar script; the tool reads
  `EVENTOR_API_KEY`.
