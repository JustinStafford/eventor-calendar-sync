"""Shared pytest fixtures. No test in this suite may touch the network."""

from __future__ import annotations

from pathlib import Path

import pytest

from eventor_calendar_sync.config import Config, load_config
from eventor_calendar_sync.models import Event
from helpers import CONFIG, load_events


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse any real socket connection."""
    import socket

    def guard(*_args, **_kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture(autouse=True)
def _no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("EVENTOR_API_KEY", "EVENTOR_BASE_URL", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def events() -> list[Event]:
    return load_events()


@pytest.fixture
def by_name(events: list[Event]):
    def find(fragment: str) -> Event:
        matches = [e for e in events if fragment.lower() in e.name.lower()]
        assert len(matches) == 1, f"{fragment!r} matched {[e.name for e in matches]}"
        return matches[0]

    return find


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def config(config_path: Path) -> Config:
    return load_config(config_path)
