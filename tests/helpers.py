"""Test doubles: a canned Eventor, a fake Claude client and a small config."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from eventor_calendar_sync.eventor import EventorSource
from eventor_calendar_sync.models import Event

FIXTURES = Path(__file__).parent / "fixtures"

ORGANISATIONS = b"""<?xml version="1.0" encoding="utf-8"?>
<OrganisationList>
  <Organisation><OrganisationId>5</OrganisationId><Name>Orienteering NSW</Name></Organisation>
  <Organisation>
    <OrganisationId>23</OrganisationId><Name>Central Coast Orienteers</Name>
  </Organisation>
  <Organisation>
    <OrganisationId>29</OrganisationId><Name>Newcastle Orienteering Club</Name>
  </Organisation>
</OrganisationList>"""

CONFIG = """
[site]
base_url = "https://calendars.example.org"
title = "Test calendars"
organisation = "Test Orienteering"

[[source.queries]]
organisers = [5]

[defaults]
admin_name_patterns = ["communication", "socks", "season ticket", "camping"]

[classifier]
model = "claude-opus-5"
effort = "low"
context = "Test context."

[series.street]
name = "Newcastle Summer Street Series"
description = "Wednesday evening street events."
name_patterns = ["summer street series"]
organisers = [29]

[series.state-league]
name = "NSW State League"
name_patterns = ["state league"]

[series.sss]
name = "Sydney Summer Series"
name_patterns = ["sydney summer series"]

[calendars.street]
group = "Newcastle"
name = "Street Series"
series = ["street"]
default_duration_hours = 1.5

[calendars.newcastle]
group = "Newcastle"
name = "All Newcastle"
organisers = [29]

[calendars.state-league]
name = "State League"
series = ["state-league"]
"""


def fake_fetch(calls: list | None = None) -> Callable[[str, Mapping[str, str]], bytes]:
    def fetch(path: str, params: Mapping[str, str]) -> bytes:
        if calls is not None:
            calls.append((path, dict(params)))
        if path == "/organisations":
            return ORGANISATIONS
        if path == "/events":
            return (FIXTURES / "events.xml").read_bytes()
        raise AssertionError(f"unexpected request {path}")

    return fetch


def fake_source(calls: list | None = None) -> EventorSource:
    return EventorSource(api_key="test", fetch=fake_fetch(calls))


def load_events() -> list[Event]:
    from datetime import date

    from eventor_calendar_sync.eventor import Query

    source = fake_source()
    return source.events(
        [Query(organisers=(5,))], date(2025, 1, 1), date(2028, 1, 1), source.organisations()
    )


class FakeClaude:
    """Stands in for ``anthropic.Anthropic``: records requests, answers from a function."""

    def __init__(self, answer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]):
        self.answer = answer
        self.requests: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None
        self.stop_reason = "end_turn"
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request: Any) -> Any:
        self.requests.append(request)
        if self.fail_with:
            raise self.fail_with
        content = request["messages"][0]["content"]
        body = content[
            content.index("<listings>") + len("<listings>") : content.index("</listings>")
        ]
        text = json.dumps({"results": self.answer(json.loads(body))})
        return SimpleNamespace(
            stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)]
        )


def label_all(kind: str = "competition", series: str = "none"):
    def answer(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "kind": kind,
                "series": series,
                "confidence": "high",
                "reason": "test",
            }
            for item in listings
        ]

    return answer
