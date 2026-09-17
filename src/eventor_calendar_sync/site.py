"""The landing page: one branded page with a subscribe button per calendar and app.

Printed (or saved as a PDF from the browser) it turns into a handout: the buttons
give way to each calendar's address and a QR code that opens that calendar's
section of the page on a phone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import segno
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from eventor_calendar_sync.calendars import sort_key
from eventor_calendar_sync.config import CalendarDef, SiteDef
from eventor_calendar_sync.models import CalendarEntry

UPCOMING_SHOWN = 4


@dataclass(frozen=True, slots=True)
class Links:
    ics_url: str
    webcal_url: str
    google_url: str
    outlook_live_url: str
    outlook_office_url: str
    page_url: str


def links(base_url: str, slug: str, name: str) -> Links:
    ics_url = f"{base_url}/{slug}.ics"
    webcal_url = "webcal://" + ics_url.removeprefix("https://")
    outlook = f"/calendar/0/addfromweb?url={quote(ics_url, safe='')}&name={quote(name, safe='')}"
    return Links(
        ics_url=ics_url,
        webcal_url=webcal_url,
        google_url=f"https://calendar.google.com/calendar/render?cid={quote(webcal_url, safe='')}",
        outlook_live_url=f"https://outlook.live.com{outlook}",
        outlook_office_url=f"https://outlook.office.com{outlook}",
        page_url=f"{base_url}/#{slug}",
    )


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b %Y}"


def _when(entry: CalendarEntry, timezone: ZoneInfo) -> str:
    if isinstance(entry.start, datetime):
        return _day(entry.start.astimezone(timezone).date())
    return _day(entry.start)


def render_index(
    site: SiteDef,
    calendars: dict[str, CalendarDef],
    entries: dict[str, list[CalendarEntry]],
    *,
    today: date,
    timezone: ZoneInfo,
    source_url: str,
    logo: str = "",
) -> str:
    groups: dict[str, list[dict]] = {}
    for slug, calendar in calendars.items():
        upcoming = sorted((e for e in entries[slug] if e.last_day >= today), key=sort_key)
        link = links(site.base_url, slug, calendar.name)
        qr = segno.make(link.page_url, error="m").svg_inline(scale=3, border=1, omitsize=True)
        groups.setdefault(calendar.group, []).append(
            {
                "slug": slug,
                "name": calendar.name,
                "description": calendar.description,
                "ics_url": link.ics_url,
                "webcal_url": link.webcal_url,
                "google_url": link.google_url,
                "outlook_live_url": link.outlook_live_url,
                "outlook_office_url": link.outlook_office_url,
                "qr": Markup(qr),
                "upcoming": [
                    {"when": _when(e, timezone), "summary": e.summary, "url": e.url}
                    for e in upcoming[:UPCOMING_SHOWN]
                ],
                "more": max(0, len(upcoming) - UPCOMING_SHOWN),
            }
        )
    env = Environment(
        loader=PackageLoader("eventor_calendar_sync", "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("index.html.j2").render(
        site=site,
        groups=[{"name": name, "calendars": cals} for name, cals in groups.items()],
        updated=_day(today),
        source_url=source_url,
        logo=logo,
    )
