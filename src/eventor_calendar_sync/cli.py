"""Command-line interface.

Exit codes: 0 success, 1 configuration problem, 2 Eventor failure,
4 safety guard refused to publish.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from eventor_calendar_sync import __version__, build, review
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
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Build and report, but write nothing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Publish even if the safety guard objects.")
    ] = False,
    report: Annotated[
        Path | None, typer.Option("--report", help="Write the JSON run report here.")
    ] = None,
    as_of: AsOf = None,
) -> None:
    """Pull events, sort them into series, and write every calendar plus the landing page."""
    cfg = _config(config)
    source = _source(cfg.source.base_url)
    today = _today(as_of)
    try:
        events = build.pull(cfg, source, today)
        result = build.run(cfg, events, out_dir=out, today=today, force=force, dry_run=dry_run)
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
    if code == EXIT_OK and not dry_run:
        _echo(f"{len(result.written)} file(s) changed in {out}")
    raise typer.Exit(code)


@app.command("review")
def review_command(
    config: ConfigOption = Path("config.toml"),
    minimum: Annotated[
        int, typer.Option("--min", help="Smallest unmatched name group worth listing.")
    ] = 3,
    show_all: Annotated[
        bool, typer.Option("--all", help="Also list every listing that is in no series.")
    ] = False,
    brief: Annotated[
        bool, typer.Option("--brief", help="The weekly digest: what needs a look, nothing else.")
    ] = False,
    days_back: Annotated[
        int, typer.Option("--days-back", help="Look back this far: a full year shows every season.")
    ] = 365,
    as_of: AsOf = None,
) -> None:
    """Show what the name patterns catch, hide and miss. Changes nothing."""
    cfg = _config(config)
    today = _today(as_of)
    try:
        events = build.pull(cfg, _source(cfg.source.base_url), today, days_back=days_back)
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc
    _echo(review.render(cfg, events, today, minimum=minimum, show_all=show_all, brief=brief))


@app.command()
def explore(
    organisers: Annotated[
        str,
        typer.Argument(
            help="Organiser IDs, comma separated. A state association covers its clubs."
        ),
    ],
    minimum: Annotated[int, typer.Option("--min", help="Hide name groups smaller than this.")] = 3,
    days_back: Annotated[int, typer.Option("--days-back")] = 365,
    days_forward: Annotated[int, typer.Option("--days-forward")] = 365,
    as_of: AsOf = None,
) -> None:
    """Before there is a config: group event names to find the series worth a calendar."""
    try:
        ids = tuple(int(i) for i in organisers.split(",") if i.strip())
    except ValueError as exc:
        _err("organisers must be numbers, for example: explore 5")
        raise typer.Exit(EXIT_CONFIG) from exc
    source, today = _source(AU_BASE_URL), _today(as_of)
    try:
        events = source.events(
            [Query(organisers=ids)],
            today - timedelta(days=days_back),
            today + timedelta(days=days_forward),
            source.organisations(),
        )
    except SourceError as exc:
        _err(f"Eventor failure: {exc}")
        raise typer.Exit(EXIT_SOURCE) from exc
    groups = review.name_groups(events)
    _echo(f"{len(events)} listings in {len(groups)} name groups; groups of {minimum}+ shown\n")
    for key, members in groups:
        if len(members) >= minimum:
            disciplines = sorted({d for e in members for d in e.disciplines})
            _echo(f"{len(members):>4}  {key[:48]:<48} {', '.join(disciplines):<20} "
                  f"{review.organisers_of(members)}")  # fmt: skip


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
