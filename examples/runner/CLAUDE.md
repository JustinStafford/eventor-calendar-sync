# This repository publishes event calendars

It holds no code. A nightly GitHub Action (`.github/workflows/publish.yml`) installs
[eventor-calendar-sync](https://github.com/JustinStafford/eventor-calendar-sync), reads
`config.toml`, pulls events from Eventor, and publishes one `.ics` file per calendar plus a landing
page to the `gh-pages` branch, which GitHub Pages serves. People subscribe to those files from
their calendar apps.

Almost all the work here is one job: **keeping the name patterns in `config.toml` matched to what
organisers actually call their events.** Eventor has no series field; a series is a list of regular
expressions searched for in event names. The tool deliberately infers nothing at run time, so the
judgement is yours, applied here, in a change a person reads before it ships.

## Rules that are easy to break

- **Never rename a calendar's slug** (`[calendars.<slug>]`). The slug is the address people have
  subscribed to (`<base_url>/<slug>.ics`). Renaming or removing one silently breaks their
  calendars. Adding calendars is fine. Ask before removing one. Series slugs are internal and may
  change, as long as the calendars that use them are updated.
- **Never commit to `gh-pages` by hand.** The job owns it.
- **Propose, then wait.** Show the `config.toml` diff and your reasoning, and get a yes before
  committing or pushing. A wrong pattern either hides real events from subscribers or shows them
  junk.
- The Eventor key lives in `.env` locally (git-ignored) and in the `EVENTOR_API_KEY` Actions
  secret. Never print it or commit it. If `.env` is missing, ask the user to create it with
  `EVENTOR_API_KEY=...`; any club's key can read events.

## Running the tool

In this file `ecs` is shorthand. Write the command out in full each time, because shell aliases
and variables do not survive from one command to the next in a Claude Code session:

```bash
uvx --from git+https://github.com/JustinStafford/eventor-calendar-sync@main eventor-calendar-sync <command>
```

Replace `main` with the version the nightly job runs, if it is pinned:
`gh variable get TOOL_REF` (no output means `main`).

```bash
ecs review            # the pattern report; add --all to list one-off events too
ecs build --dry-run   # what would be published; writes nothing
ecs orgs wagga        # look up an organiser's Eventor ID
```

All of these only read from Eventor, using the key in `.env`. None of them publishes anything.

## Reviewing the patterns

Do this when asked to "review the patterns", at the start of a season, when a nightly run's summary
lists surprises, or when someone reports a missing or misplaced event.

1. Run `ecs review --all` and read the whole report. It covers the past year and everything
   upcoming, in five sections.

2. **Section 1, what each series caught.** Names are grouped with years and numbers stripped. For
   each series ask: does every group belong? A group marked *(not an event)* is already kept out
   of calendars and is fine. For a wrong catch, prefer in this order: a more specific phrase; an
   `organisers` (or `disciplines`) constraint on the series; an `exclude_name_patterns` entry.

3. **Section 2, treated as not an event.** Each line ends with the pattern responsible. Ask: is any
   of these a real event people would attend? If so the pattern is too loose. The classic mistake
   is a missing word boundary: `'singlet'` hides every event held at Singleton, `'\bsinglets?\b'`
   does not.

4. **Section 3, name groups in no series.** Decide what each group is:
   - *A renamed or abbreviated round of an existing series* ("SummerSaturdays #2", "RBOS #4", "NTOC
     SS#6"): add an alternative to that series' `name_patterns`.
   - *A series worth a calendar*: usually four or more events a year that the public can enter.
     Propose a `[series.<slug>]` and a `[calendars.<slug>]`, and ask the user to confirm the
     calendar's slug and name, because the slug is permanent. School sessions and private bookings
     are not worth one.
   - *Junk* (merchandise, passes, memberships, nominations, placeholders, test listings): add a
     word-bounded entry to `[defaults].not_event_patterns`.
   - *Nothing*: one-offs that merely share words. Leave them. They still appear in the organiser
     and "all events" calendars, which need no patterns.

5. **Section 4, series with nothing upcoming.** Usually the season is simply over. Compare the
   last listing's date with when that series normally runs. If new-season events should be in
   Eventor by now, look in sections 3 and 5 for them under a new name.

6. **Section 5, everything else.** Scan for junk the patterns missed, and for single events that
   plainly belong to a series but are named differently. For a one-off oddity, prefer an
   `[overrides]` entry keyed by the event ID (the number at the start of the line) over bending a
   pattern: `24550 = { not_event = true, note = "season ticket" }` or
   `23647 = { series = ["ncn-ufo"], note = "named differently this year" }`.

7. Edit `config.toml`, then **run `ecs review` again** and confirm that each change did what you
   meant and nothing else. A pattern change can move listings you were not looking at, so re-read
   sections 1 and 2 in full, not just the series you touched.

8. Run `ecs build --dry-run`. To compare against what is live, check the published site out first
   and remove it afterwards:

   ```bash
   git fetch origin gh-pages && git worktree add public origin/gh-pages
   ecs build --dry-run          # the "Was" column is now the live count
   git worktree remove --force public
   ```

   A calendar whose upcoming count falls by more than `max_shrink_percent` makes the nightly job
   refuse to publish. If your change legitimately moves that many events, tell the user, who can
   run the workflow once with *force* ticked.

9. Report to the user: what you found, the diff, and anything you were unsure about. After they
   agree, commit and push `config.toml`. Offer to check the result with a manual dry run:
   `gh workflow run publish.yml -f dry_run=true`, then read that run's summary.

## Writing patterns

- Patterns are Python regular expressions, case-insensitive, **searched for anywhere** in the
  event name (not anchored). Write them in **single quotes** (TOML literal strings) so backslashes
  need no doubling: `'\bSOS\b'`.
- Put `\b` word boundaries around acronyms and short words. Check what else contains the letters.
- Use the most distinctive phrase that every round shares: `'summer street series'`, not
  `'series'`. Allow for the variations that actually occur (`'summer ?saturdays'`,
  `'river (and|&) bay'`), not ones you imagine.
- An acronym shared between clubs needs an `organisers` constraint ("SSS" is the Sydney Summer
  Series in Sydney and the Summer Street Series in Newcastle).
- A listing can be in several series; that is normal ("NSW State League #11 - NSW Schools Champs").
- A listing that carries a series' name but is not an event (a season ticket) is handled by
  `not_event_patterns`, not by weakening the series.
- Calendars defined by `organisers`, `levels` or `disciplines` need no patterns and cannot drift.
  Prefer them wherever "everything this club runs" is what people want.
- Unknown keys in `config.toml` are errors, so a typo fails loudly rather than switching a filter
  off. The tool's README has the full reference.

## Other jobs

- **Branding and wording of the page**: `[site]` in `config.toml`, and an optional logo file beside
  it. The page's layout belongs to the tool, not to this repository.
- **Moving to a newer version of the tool**: read the tool's commit log between the old and new
  `TOOL_REF`, run `review` and `build --dry-run` with the new ref, compare, then change the
  `TOOL_REF` variable (`gh variable set TOOL_REF --body <tag-or-commit>`). If the workflow example
  in the tool changed, copy the new one across.
- **A run failed**: read its log. Exit code 2 is Eventor being unreachable (it will recover by
  itself); 4 is the safety guard (see step 8); 1 is a mistake in `config.toml`.
