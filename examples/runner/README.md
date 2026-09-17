# Running the calendars for your organisation

[eventor-calendar-sync](https://github.com/JustinStafford/eventor-calendar-sync) is the tool. This
directory is everything *your* repository needs to run it every night and publish the result:

```
config.toml                      what to publish (no secrets; edit freely)
.github/workflows/publish.yml    the nightly job
classifications.json             created and maintained by the job
logo.png                         optional
```

The repository can be private (GitHub Pages from a private repository needs a paid plan) or
public (free). The published site is public either way.

## Setup

1. **Create the repository** and copy `config.toml` and `.github/workflows/publish.yml` into it.
   Do not fork the tool: there is nothing in it you need to change.
2. **Edit `config.toml`.** Set `[site].base_url` to where the site will live: your own domain if
   you have one (see below), otherwise `https://<owner>.github.io/<repository>`. Trim the series
   and calendars to the ones you want. `uvx --from git+https://github.com/JustinStafford/eventor-calendar-sync eventor-calendar-sync explore --organisers <your state or club ID>`
   shows the series hiding in your event names.
3. **Secrets** (*Settings > Secrets and variables > Actions*):
   `EVENTOR_API_KEY`, any club's Eventor API key, and optionally `ANTHROPIC_API_KEY` from
   [console.anthropic.com](https://console.anthropic.com) for LLM classification. Give that key
   a low monthly spend limit; this job costs cents.
4. **Variable** `TOOL_REF`: a tag or commit of the tool, so that your calendars only change
   behaviour when you decide to move it.
5. **First run.** *Actions > Publish calendars > Run workflow* with *dry run* ticked. Read the run
   summary: what landed in each calendar, how each listing was classified and why, and which
   upcoming events are in no calendar. Fix surprises with `[overrides]` or better series
   descriptions, then run it again without *dry run*. That creates the `gh-pages` branch.
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

## Day to day

- **A listing is in the wrong calendar, or is not an event:** add it to `[overrides]` by its
  Eventor event ID (the number in its URL).
- **A new series:** add a `[series.<slug>]` with a good description and a `[calendars.<slug>]`
  that uses it. Changing the series catalogue makes the next run reclassify everything once.
- **Never rename a calendar's slug** once people have subscribed: the slug is the address.
  Removing a calendar from `config.toml` unpublishes its file.
- **The handout:** open the site and print it (or *Save as PDF*). The print layout swaps the
  buttons for each calendar's address and a QR code.
- **History:** the `gh-pages` branch is a complete log of every change ever published.
