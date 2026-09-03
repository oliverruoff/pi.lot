"""Verify /new and /session are queued and processed sequentially."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pilot.app import PilotApp
from pilot.config import Config
from pilot.models import WorkItem


@pytest.fixture
def cfg():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Config(
            telegram_bot_token="dummy",
            workdir=str(tmpdir),
            behavior_prompt="test",
            log_level="INFO",
            pi_command="pi",
            pi_args=["--mode", "rpc"],
            telegram_parse_mode="MarkdownV2",
            data_dir=str(tmpdir),
        )


@pytest.fixture
def app(cfg):
    with patch("pilot.app.PiRPC"):
        app = PilotApp(cfg)
        # Mock pi RPC
        app.pi = MagicMock()
        app.pi.new_session = AsyncMock()
        app.pi.switch_session = AsyncMock()
        app.pi.get_state = AsyncMock(
            return_value={"sessionFile": str(Path(cfg.data_dir) / "test.jsonl")}
        )
        app.pi.prompt_and_wait = AsyncMock()

        # Mock Telegram bot
        app.app = MagicMock()
        app.app.bot = MagicMock()
        app.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        app.app.bot.send_chat_action = AsyncMock()
        app.app.bot.edit_message_text = AsyncMock()
        app.app.bot.edit_message_reply_markup = AsyncMock()
        app.app.bot.delete_message = AsyncMock()

        app.main_chat_id = 12345
        session_path = str(Path(cfg.data_dir) / "session1.jsonl")
        app.sessions[1] = session_path
        app.active_session_no = 1
        # Ensure mocked get_state returns the same session file so
        # _remember_current_session does not create a duplicate entry.
        app.pi.get_state = AsyncMock(return_value={"sessionFile": session_path})
        return app


async def _drain_queue(app: PilotApp, worker_task: asyncio.Task, timeout: float = 5.0):
    """Poll until the queue is empty and worker is idle, then cancel the worker."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if app.queue.empty() and not app.busy:
            break
        await asyncio.sleep(0.05)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_busy_app_reports_new_queue_item(app):
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    app.busy = True

    await app._enqueue_text_prompt("Queued prompt", context)

    assert (await app.queue.get()).prompt == "Queued prompt"
    app.queue.task_done()
    context.bot.send_message.assert_awaited_once_with(12345, "Queued (1 pending).")


@pytest.mark.asyncio
async def test_new_is_queued_after_prompt(app):
    """A /new command enqueued while busy runs AFTER the preceding prompt."""
    call_order = []

    async def track_prompt(*args, **kwargs):
        call_order.append("prompt")

    async def track_new(*args, **kwargs):
        call_order.append("new")

    app.pi.prompt_and_wait = AsyncMock(side_effect=track_prompt)
    app.pi.new_session = AsyncMock(side_effect=track_new)

    worker = asyncio.create_task(app.worker())
    await asyncio.sleep(0.05)  # let worker reach queue.get()

    await app.queue.put(WorkItem("First prompt"))
    await app.queue.put(WorkItem("", command="/new"))
    await app.queue.put(WorkItem("Second prompt"))

    await _drain_queue(app, worker)

    assert app.queue.empty()
    assert call_order == ["prompt", "new", "prompt"], f"Calls were: {call_order}"
    # After /new ran, inject_behavior_next was set to True, but the following
    # normal prompt resets it to False again – that is expected.
    assert app.inject_behavior_next is False


@pytest.mark.asyncio
async def test_new_reports_the_session_id(app):
    await app._do_new_session()

    app.app.bot.send_message.assert_awaited_once_with(
        12345,
        "Session ID: 1\n\nStarted a new pi session.",
    )


def test_behavior_file_is_reloaded_for_new_session(app):
    app.behavior_file.write_text("Updated behavior\n", encoding="utf-8")
    app.inject_behavior_next = True

    prompt = app._build_prompt(WorkItem("Hello"))

    assert prompt == "Updated behavior\n\nUser prompt:\nHello"
    assert app.inject_behavior_next is False


@pytest.mark.asyncio
async def test_behavior_change_updates_behavior_file(app):
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    await app._change_behavior("Be concise.", context)

    assert app.behavior_file.read_text(encoding="utf-8") == "Be concise.\n"


@pytest.mark.asyncio
async def test_new_aborts_run_waiting_for_pending_ui_before_it_is_queued(app):
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    app.pending_ui = {
        "id": "question-1",
        "method": "select",
        "options": ["A"],
        "message_id": 99,
    }
    app.pi.extension_ui_response = AsyncMock()
    app.pi.abort = AsyncMock()

    handled = await app._handle_pilot_command("/new", context)

    assert handled is True
    app.app.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=12345,
        message_id=99,
        reply_markup=None,
    )
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
async def test_new_without_pending_ui_does_not_abort_current_run(app):
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    app.pi.abort = AsyncMock()

    await app._handle_pilot_command("/new", context)

    app.pi.abort.assert_not_awaited()
    item = await app.queue.get()
    assert item.command == "/new"
    app.queue.task_done()


def test_startup_message_reports_the_current_session_id(app):
    assert app._session_message("pi.lot started.", app.active_session_no) == (
        "Session ID: 1\n\npi.lot started."
    )


@pytest.mark.asyncio
async def test_cronjob_final_answer_starts_with_its_session_id(app):
    cron_session_path = str(Path(app.cfg.data_dir) / "cron.jsonl")
    app.pi.get_state = AsyncMock(return_value={"sessionFile": cron_session_path})
    app.current_text = "Cron result"
    app.send_final_reply = AsyncMock()

    await app._do_prompt(WorkItem("Run report", cronjob_id="daily"), previous_active=1)

    app.send_final_reply.assert_awaited_once_with("Session ID: 2\n\nCron result")


@pytest.mark.asyncio
async def test_cronjob_cancels_pending_ui_before_it_is_queued(app):
    app.prompt_inbox_dir.mkdir()
    inbox_item = app.prompt_inbox_dir / "cron.json"
    inbox_item.write_text(json.dumps({
        "id": "daily",
        "source": "cronjobs-skill",
        "prompt": "Run report",
    }))
    app.pending_ui = {
        "id": "question-1",
        "method": "select",
        "options": ["A"],
        "message_id": 99,
    }
    app.pi.extension_ui_response = AsyncMock()

    await app._process_prompt_inbox()

    app.app.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=12345,
        message_id=99,
        reply_markup=None,
    )
    app.pi.extension_ui_response.assert_awaited_once_with({
        "id": "question-1",
        "cancelled": True,
    })
    item = await app.queue.get()
    assert item.prompt == "Run report"
    assert item.cronjob_id == "daily"
    assert app.pending_ui is None
    assert not inbox_item.exists()
    app.queue.task_done()


@pytest.mark.asyncio
async def test_session_switch_is_queued_after_prompt(app):
    """A /session command enqueued while busy runs AFTER the preceding prompt."""
    call_order = []

    async def track_prompt(*args, **kwargs):
        call_order.append("prompt")

    async def track_switch(*args, **kwargs):
        call_order.append("switch")

    app.pi.prompt_and_wait = AsyncMock(side_effect=track_prompt)
    app.pi.switch_session = AsyncMock(side_effect=track_switch)

    worker = asyncio.create_task(app.worker())
    await asyncio.sleep(0.05)

    await app.queue.put(WorkItem("First prompt"))
    await app.queue.put(WorkItem("", command="/session", session_no=1))
    await app.queue.put(WorkItem("Second prompt"))

    await _drain_queue(app, worker)

    assert app.queue.empty()
    assert call_order == ["prompt", "switch", "prompt"], f"Calls were: {call_order}"
    assert app.active_session_no == 1
    assert app.inject_behavior_next is False


@pytest.mark.asyncio
async def test_stop_clears_queued_commands(app):
    """/stop empties the queue even when it contains /new or /session commands."""
    # Make prompt_and_wait slow so the worker stays busy while we clear.
    async def _slow(*a, **k):
        await asyncio.sleep(10)
    app.pi.prompt_and_wait = AsyncMock(side_effect=_slow)

    worker = asyncio.create_task(app.worker())
    await asyncio.sleep(0.05)

    await app.queue.put(WorkItem("Prompt"))
    await app.queue.put(WorkItem("", command="/new"))
    await app.queue.put(WorkItem("", command="/session", session_no=1))

    # Wait until the worker grabbed the first item and is blocked in prompt_and_wait.
    for _ in range(20):
        if app.busy:
            break
        await asyncio.sleep(0.05)

    cleared = app._clear_queue()
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    assert cleared == 2
    assert app.queue.empty()
