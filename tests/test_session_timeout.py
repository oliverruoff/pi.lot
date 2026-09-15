"""Verify the automatic session reset after chat inactivity."""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pilot.app import PilotApp
from pilot.config import Config, _load_session_timeout
from pilot.models import WorkItem


def _make_cfg(session_timeout_minutes: int | None = None, tmpdir: str = "") -> Config:
    kwargs = dict(
        telegram_bot_token="dummy",
        workdir=tmpdir,
        behavior_prompt="test",
        log_level="INFO",
        pi_command="pi",
        pi_args=["--mode", "rpc"],
        telegram_parse_mode="MarkdownV2",
        data_dir=tmpdir,
    )
    if session_timeout_minutes is not None:
        kwargs["session_timeout_minutes"] = session_timeout_minutes
    return Config(**kwargs)


@pytest.fixture
def cfg():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield _make_cfg(tmpdir=tmpdir)


@pytest.fixture
def app(cfg):
    with patch("pilot.app.PiRPC"):
        app = PilotApp(cfg)
        app.pi = MagicMock()
        app.pi.new_session = AsyncMock()
        app.pi.abort = AsyncMock()
        app.pi.get_state = AsyncMock(
            return_value={"sessionFile": str(Path(cfg.data_dir) / "session1.jsonl")}
        )
        app.app = MagicMock()
        app.app.bot = MagicMock()
        app.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        app.main_chat_id = 12345
        return app


def _make_idle(app: PilotApp, minutes: float = 400.0) -> None:
    app.last_activity = time.monotonic() - minutes * 60.0


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def test_config_defaults_to_six_hours():
    cfg = _make_cfg(tmpdir="/tmp/x")
    assert cfg.session_timeout_minutes == 360


def test_config_reads_env_override(monkeypatch):
    monkeypatch.setenv("PILOT_SESSION_TIMEOUT_MINUTES", "120")
    assert _load_session_timeout({}) == 120


def test_config_reads_persisted_value(monkeypatch):
    monkeypatch.delenv("PILOT_SESSION_TIMEOUT_MINUTES", raising=False)
    assert _load_session_timeout({"session_timeout_minutes": 30}) == 30
    # Environment wins over the persisted value.
    monkeypatch.setenv("PILOT_SESSION_TIMEOUT_MINUTES", "-1")
    assert _load_session_timeout({"session_timeout_minutes": 30}) == -1


def test_config_minus_one_disables_timeout(monkeypatch):
    monkeypatch.setenv("PILOT_SESSION_TIMEOUT_MINUTES", "-1")
    assert _load_session_timeout({}) == -1
    assert _make_cfg(session_timeout_minutes=-1, tmpdir="/tmp/x").session_timeout_minutes == -1


def test_config_invalid_values_fall_back_to_default(monkeypatch):
    monkeypatch.delenv("PILOT_SESSION_TIMEOUT_MINUTES", raising=False)
    for bad in (0, -5, "nonsense", None):
        assert _load_session_timeout({"session_timeout_minutes": bad}) == 360


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def test_timeout_seconds_mapping(app):
    assert app.session_timeout_seconds == 360 * 60.0


def test_minus_one_disables_auto_reset(cfg):
    with patch("pilot.app.PiRPC"):
        app = PilotApp(_make_cfg(session_timeout_minutes=-1, tmpdir=cfg.data_dir))
    assert app.session_timeout_seconds is None


@pytest.mark.asyncio
async def test_idle_watcher_triggers_new_session(app):
    _make_idle(app)

    triggered = await app._maybe_start_idle_session()

    assert triggered is True
    item = await app.queue.get()
    assert item.command == "/new"
    app.queue.task_done()


@pytest.mark.asyncio
async def test_idle_watcher_waits_for_timeout(app):
    # Default: last_activity is "now", so nothing should happen.
    triggered = await app._maybe_start_idle_session()

    assert triggered is False
    assert app.queue.empty()


@pytest.mark.asyncio
async def test_idle_watcher_skips_running_prompt(app):
    _make_idle(app)
    app.busy = True

    triggered = await app._maybe_start_idle_session()

    assert triggered is False
    assert app.queue.empty()


@pytest.mark.asyncio
async def test_idle_watcher_keeps_unused_session(app):
    """A brand-new, message-less session stays active instead of rotating."""
    session_file = Path(app.cfg.data_dir) / "session1.jsonl"
    session_file.write_text(
        '{"type":"session","id":"a"}\n'
        '{"type":"model_change","id":"b"}\n',
        encoding="utf-8",
    )
    app.sessions[1] = str(session_file)
    app.active_session_no = 1
    _make_idle(app)

    triggered = await app._maybe_start_idle_session()

    assert triggered is False
    assert app.queue.empty()
    # The idle timer restarts so the watcher does not re-inspect every tick.
    assert app.last_activity > time.monotonic() - 5


@pytest.mark.asyncio
async def test_idle_watcher_keeps_session_with_missing_file(app):
    """A session file that was never persisted counts as unused."""
    app.sessions[1] = str(Path(app.cfg.data_dir) / "never-written.jsonl")
    app.active_session_no = 1
    _make_idle(app)

    triggered = await app._maybe_start_idle_session()

    assert triggered is False
    assert app.queue.empty()


@pytest.mark.asyncio
async def test_idle_watcher_rotates_used_session(app):
    """A session that already contains a message rotates like before."""
    session_file = Path(app.cfg.data_dir) / "session1.jsonl"
    session_file.write_text(
        '{"type":"session","id":"a"}\n'
        '{"type":"message","id":"c","message":{"role":"user",'
        '"content":[{"type":"text","text":"Hallo"}]}}\n',
        encoding="utf-8",
    )
    app.sessions[1] = str(session_file)
    app.active_session_no = 1
    _make_idle(app)

    triggered = await app._maybe_start_idle_session()

    assert triggered is True
    item = await app.queue.get()
    assert item.command == "/new"
    app.queue.task_done()


@pytest.mark.asyncio
async def test_idle_watcher_cancels_pending_ui_like_new(app):
    _make_idle(app)
    app.busy = True
    app.pending_ui = {
        "id": "question-1",
        "method": "select",
        "options": ["A"],
        "message_id": 99,
    }
    app.pi.extension_ui_response = AsyncMock()
    app.app.bot.edit_message_reply_markup = AsyncMock()

    triggered = await app._maybe_start_idle_session()

    assert triggered is True
    app.pi.extension_ui_response.assert_awaited_once_with({
        "id": "question-1",
        "cancelled": True,
    })
    app.pi.abort.assert_awaited_once_with(timeout=2.0)
    item = await app.queue.get()
    assert item.command == "/new"
    app.queue.task_done()
    assert app.pending_ui is None


@pytest.mark.asyncio
async def test_idle_watcher_never_fires_when_disabled(cfg):
    with patch("pilot.app.PiRPC"):
        app = PilotApp(_make_cfg(session_timeout_minutes=-1, tmpdir=cfg.data_dir))
    app.pi = MagicMock()
    app.pi.new_session = AsyncMock()
    app.pi.get_state = AsyncMock(return_value={"sessionFile": "/tmp/s.jsonl"})
    app.main_chat_id = 12345
    _make_idle(app, minutes=10_000)

    triggered = await app._maybe_start_idle_session()

    assert triggered is False
    assert app.queue.empty()


@pytest.mark.asyncio
async def test_triggered_reset_sends_session_message(app):
    """The automatic reset produces the exact /new message."""
    _make_idle(app)
    await app._maybe_start_idle_session()
    app.queue.task_done()

    await app._do_new_session()

    app.app.bot.send_message.assert_awaited_once_with(
        12345,
        "Session ID: 1\n\nStarted a new pi session.",
    )


@pytest.mark.asyncio
async def test_user_message_refreshes_activity(app):
    _make_idle(app)
    context = MagicMock()

    class FakeUpdate:
        effective_user = MagicMock(id=42)
        effective_chat = MagicMock(id=12345)
        effective_message = MagicMock(
            text="/sessions", caption=None, document=None, photo=None,
            effective_attachment=None,
        )

    context.bot.send_message = AsyncMock()
    app._list_sessions = AsyncMock()
    app.main_user_id = 42

    await app.on_update(FakeUpdate(), context)

    assert app.last_activity > time.monotonic() - 5
