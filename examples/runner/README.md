# Running the calendars for your organisation

[eventor-calendar-sync](https://github.com/JustinStafford/eventor-calendar-sync) is the tool. This
directory is everything *your* repository needs to run it every night and publish the result:

```
config.toml                      what to publish (no secrets; edit freely)
.github/workflows/publish.yml    the nightly job
.github/workflows/review.yml     the weekly digest, emailed to you through a GitHub issue
CLAUDE.md                        how a Claude Code session looks after the patterns here
.gitignore
logo.png                         optional
```

The repository can be private (GitHub Pages from a private repository needs a paid plan) or
public (free). The published site is public either way: the instructions page at its root, and
each calendar beside it as `<slug>.ics`.

## Setup

1. **Create the repository** and copy the files above into it. Do not fork the tool: there
   is nothing in it you need to change.
2. **Edit `config.toml`.** Set `[site].base_url` to where the site will live: your own domain if
   you have one (see below), otherwise `https://<owner>.github.io/<repository>`. Trim the series
   and calendars to the ones you want. To see the series hiding in your event names:
   `uvx --from git+https://github.com/JustinStafford/eventor-calendar-sync eventor-calendar-sync explore <your state or club ID>`
3. **Secret** (*Settings > Secrets and variables > Actions*): `EVENTOR_API_KEY`. Any club's
   Eventor API key can read events.
4. **Variable** `TOOL_REF`: a tag or commit of the tool, so that your calendars only change
   behaviour when you decide to move it.
5. **First run.** *Actions > Publish calendars > Run workflow* with *dry run* ticked. Read the run
   summary: how many events landed in each calendar, which upcoming listings were treated as not
   an event, and which upcoming events are in no calendar. Fix surprises in `config.toml` (see
   below), then run it again without *dry run*. That creates the `gh-pages` branch.
6. **Turn on Pages.** *Settings > Pages > Build and deployment*: *Deploy from a branch*, branch
   `gh-pages`, folder `/ (root)`.
7. **Subscribe to one calendar yourself** on a phone and a computer before telling anyone else.

After that it runs nightly. GitHub emails you if a run fails. A run fails rather than publishes
when Eventor returns nothing or a calendar would lose more than `max_shrink_percent` of its
upcoming entries; if that loss is real (end of a season), run it once by hand with *force* ticked.

## Your own domain (recommended)

A calendar's address is what subscribers keep forever. `calendars.yourclub.org` stays yours if the
repository is renamed, moves to another GitHub account, or is one day replaced by something else
entirely; a `github.io` address does not.

1. In `config.toml` set `base_url = "https://calendars.yourclub.org"`. The job then writes the
   `CNAME` file GitHub Pages looks for.
2. Ask whoever manages the domain's DNS for one record:

   | Type | Name | Value | TTL |
   | --- | --- | --- | --- |
   | `CNAME` | `calendars` | `<owner>.github.io.` | 3600 |

   `<owner>` is the GitHub user or organisation that owns this repository, in lower case. It is
   the same value whatever the repository is called. If the domain is behind Cloudflare, set the
   record to *DNS only* (grey cloud). If the domain has `CAA` records, `letsencrypt.org` must be
   allowed, because that is who issues GitHub's certificates.
3. In *Settings > Pages*, enter the custom domain, wait for the DNS check to pass, then tick
   **Enforce HTTPS** (the certificate can take up to an hour to appear).
4. Recommended: verify the domain for your account (*your profile > Settings > Pages > Add a
   domain*). GitHub gives you a `TXT` record to add; with it in place nobody else can claim the
   domain on GitHub Pages if this repository ever goes away.

## Looking after the patterns

A series is a list of name patterns, and organisers rename things. This is the one piece of
upkeep, and it takes minutes: **at each season launch, when a run summary shows surprises, or when
someone reports a missing event.**

**You do not have to remember.** Every Monday morning the *Weekly pattern digest* workflow posts
a short report as a comment on an issue labelled `pattern-review` in this repository, and GitHub
emails it to the issue's assignee (the repository owner unless you set the `REVIEW_ASSIGNEE`
variable). It shows how many upcoming events each series has, which upcoming listings are hidden
as not-an-event and by which pattern, the event names that matched nothing, and the series with
nothing upcoming. Most weeks it needs no action. Keep the issue open; it is the thread.

When something looks wrong: open this repository in [Claude Code](https://claude.com/claude-code)
and say **"review the patterns"**. [`CLAUDE.md`](CLAUDE.md) tells it exactly what to do: it runs the
tool's `review` report, works out what has drifted, proposes the `config.toml` changes with its
reasoning, and waits for your yes before committing.

By hand, the same steps are in `CLAUDE.md`, and the tool's
[README](https://github.com/JustinStafford/eventor-calendar-sync#keeping-the-patterns-current)
explains the report. In short:

- **A listing is in the wrong calendar, or is not an event:** fix the pattern if it will recur,
  or settle that one listing in `[overrides]` by its Eventor event ID (the number in its URL).
- **A new series:** add a `[series.<slug>]` with `name_patterns`, and a `[calendars.<slug>]` that
  uses it.
- **Never rename a calendar's slug** once people have subscribed: the slug is the address.
  Removing a calendar from `config.toml` unpublishes its file.

## Also

- **The page is the instructions.** Send people to the site's address; there is no separate
  document to maintain. Printed, the page swaps its buttons for each calendar's address and a QR
  code, which makes a usable noticeboard handout.
- **History:** the `gh-pages` branch is a complete log of every change ever published.
