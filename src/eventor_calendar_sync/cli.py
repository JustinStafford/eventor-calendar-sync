"""Command-line interface.

Exit codes: 0 success, 1 configuration problem, 2 Eventor failure,
4 safety guard refused to publish.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from eventor_calendar_sync import __version__, build
from eventor_calendar_sync.classify import make_llm, rules_classify
from eventor_calendar_sync.config import Config, ConfigError, load_config
from eventor_calendar_sync.eventor import AU_BASE_URL, EventorSource, Query, SourceError

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_SOURCE = 2
EXIT_GUARD = 4

app = typer.Typer(
    help="Publish subscribable iCalendar feeds of orienteering event series from Eventor.",
    add_completion=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="The calendars to publish.")]
AsOf = Annotated[datetime | None, typer.Option("--as-of", hidden=True, formats=["%Y-%m-%d"])]


def _echo(message: str = "") -> None:
    typer.echo(message)


def _err(message: str) -> None:
    typer.echo(message, err=True)


@app.callback()
def _common(
    ctx: typer.Context,
    env_file: Annotated[
        Path, typer.Option("--env-file", help="Load environment variables from this file.")
    ] = Path(".env"),
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
    version: Annotated[bool, typer.Option("--version", help="Print the version and exit.")] = False,
) -> None:
    if version:
        _echo(f"eventor-calendar-sync {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _echo(ctx.get_help())
        raise typer.Exit()
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    if not verbose:
        for noisy in ("httpx", "httpx2", "httpcore", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _config(path: Path) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        _err(f"configuration error: {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc


def _source(base_url: str) -> EventorSource:
    key = (os.environ.get("EVENTOR_API_KEY") or "").strip()
    if not key:
        _err("configuration error: EVENTOR_API_KEY is not set")
        raise typer.Exit(EXIT_CONFIG)
    return EventorSource(api_key=key, base_url=os.environ.get("EVENTOR_BASE_URL") or base_url)


def _today(as_of: datetime | None) -> date:
    return as_of.date() if as_of else date.today()


@app.command("build")
def build_command(
    config: ConfigOption = Path("config.toml"),
    out: Annotated[
        Path, typer.Option("--out", "-o", help="The site directory (the gh-pages checkout).")
    ] = Path("public"),
    cache: Annotated[
        Path, typer.Option("--cache", help="Classification cache; commit it next to config.toml.")
    ] = Path("classifications.json"),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Build and report, but do not write the site.")
    ] = False,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Classify with the name-pattern rules only.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Publish even if the safety guard objects.")
    ] = False,
    report: Annotated[
        Path | None, typer.Option("--report", help="Write the JSON run report here.")
    ] = None,
    as_of: AsOf = None,
) -> None:
    """Pull events, classify them, and write every calendar plus the landing page."""
    cfg = _config(config)
    source = _source(cfg.source.base_url)
    today = _today(as_of)
    llm = None if no_llm else make_llm(cfg, (os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    if llm is None and cfg.classifier.enabled and not no_llm:
        _err("note: ANTHROPIC_API_KEY is not set; classifying with name patterns only")

    try:
        events = build.pull(cfg, source, today)
        result = build.run(
            cfg, events, out_dir=out, cache_path=cache, llm=llm, today=today,
            force=force, dry_run=dry_run,
        )  # fmt: skip
        code = EXIT_OK
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc
    except ConfigError as exc:
        _err(f"configuration error: {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    except build.GuardError as exc:
        result, code = exc.result, EXIT_GUARD
        for problem in exc.problems:
            _err(f"safety guard: {problem}")
        _err("nothing was written; run again with --force if this is expected")

    _echo(result.summary)
    if report:
        report.write_text(json.dumps(result.report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as handle:
            handle.write(result.summary)
    for error in result.report["classifier"]["errors"]:
        prefix = "::warning title=Classifier::" if os.environ.get("GITHUB_ACTIONS") else "warning: "
        _echo(f"{prefix}{error}")
    if code == EXIT_OK and not dry_run:
        _echo(f"{len(result.written)} file(s) changed in {out}")
    raise typer.Exit(code)


STEM_YEAR = re.compile(r"\b20\d\d(\s*/\s*\d\d(\d\d)?)?\b|\b\d\d/\d\d\b")
STEM_ORDINAL = re.compile(r"(#|\b(no|event|round|race|day|week)\.?)?\s*\d+\b", re.IGNORECASE)


def stem(name: str) -> str:
    """The part of an event name that a series' rounds tend to share."""
    text = re.split(r"\s[-\u2013\u2014]\s", name, maxsplit=1)[0]
    text = STEM_ORDINAL.sub(" ", STEM_YEAR.sub(" ", text))
    return " ".join(text.split()).strip(" -:#,.").lower()


@app.command()
def explore(
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Use this file's [source] and series.")
    ] = None,
    organisers: Annotated[
        str, typer.Option("--organisers", help="Without --config: organiser IDs, comma separated.")
    ] = "",
    minimum: Annotated[int, typer.Option("--min", help="Hide name groups smaller than this.")] = 3,
    days_back: Annotated[int, typer.Option("--days-back")] = 365,
    days_forward: Annotated[int, typer.Option("--days-forward")] = 365,
    as_of: AsOf = None,
) -> None:
    """Group event names to find series worth a calendar, and show which rules catch them."""
    cfg = _config(config) if config else None
    if cfg:
        queries, base_url = cfg.source.queries, cfg.source.base_url
    elif organisers:
        ids = tuple(int(i) for i in organisers.split(",") if i.strip())
        queries, base_url = (Query(organisers=ids),), AU_BASE_URL
    else:
        _err("give --config, or --organisers (a state association's ID covers all its clubs)")
        raise typer.Exit(EXIT_CONFIG)
    source, today = _source(base_url), _today(as_of)
    try:
        names = source.organisations()
        events = source.events(
            queries, today - timedelta(days=days_back), today + timedelta(days=days_forward), names
        )
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc

    groups = defaultdict(list)
    for event in events:
        groups[stem(event.name)].append(event)
    _echo(f"{len(events)} events in {len(groups)} name groups; groups of {minimum}+ shown\n")
    _echo(f"{'n':>4}  {'name group':<44} {'organisers':<34} {'disciplines':<18} rules say")
    for key, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) < minimum:
            continue
        orgs = Counter(f"{o.name or o.id} ({o.id})" for e in members for o in e.organisers)
        disciplines = Counter("+".join(e.disciplines) for e in members)
        verdict = ""
        if cfg:
            verdicts = Counter(
                (c.series or ("(admin)" if c.kind == "admin" else "-"))
                for c in (rules_classify(e, cfg) for e in members)
            )
            verdict = ", ".join(f"{k} x{n}" for k, n in verdicts.most_common(3))
        _echo(
            f"{len(members):>4}  {key[:44]:<44} "
            f"{', '.join(k for k, _ in orgs.most_common(2))[:34]:<34} "
            f"{', '.join(k for k, _ in disciplines.most_common(2))[:18]:<18} {verdict}"
        )


@app.command()
def orgs(
    search: Annotated[str, typer.Argument(help="Part of an organisation's name.")] = "",
) -> None:
    """Look up organiser IDs for ``organisers = [...]`` in config.toml."""
    try:
        names = _source(AU_BASE_URL).organisations()
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc
    for org_id, name in sorted(names.items(), key=lambda kv: kv[1].lower()):
        if search.lower() in name.lower():
            _echo(f"{org_id:>6}  {name}")


@app.command()
def whoami() -> None:
    """Check the Eventor key."""
    try:
        _echo(f"Eventor: {_source(AU_BASE_URL).whoami()}")
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc


def main() -> None:
    app()


if __name__ == "__main__":
    main()
