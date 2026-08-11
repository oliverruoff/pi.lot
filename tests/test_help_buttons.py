"""Verify /help exposes buttons and that button presses trigger commands."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram import InlineKeyboardMarkup

from pilot.app import PilotApp, _BUTTON_COMMANDS, _MY_COMMANDS


def _make_app() -> PilotApp:
    app = PilotApp.__new__(PilotApp)
    app.main_chat_id = 12345
    app.pending_ui = None
    app.app = MagicMock()
    app.app.bot = MagicMock()
    app.app.bot.send_message = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_help_message_includes_button_keyboard():
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    app = _make_app()
    await app._send_help(context)

    context.bot.send_message.assert_awaited_once()
    _, kwargs = context.bot.send_message.call_args
    assert kwargs["reply_markup"] is not None
    # One button per command (tuples expand to multiple buttons),
    # all in a single column.
    markup = kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    expected = [
        f"/{c}"
        for entry in _BUTTON_COMMANDS
        for c in (entry if isinstance(entry, tuple) else (entry,))
    ]
    assert labels == expected


@pytest.mark.asyncio
async def test_question_mark_alias_dispatches_to_help():
    """Typing /? should behave exactly like /help."""
    context = MagicMock()

    app = _make_app()
    app._send_help = AsyncMock()

    handled = await app._handle_pilot_command("/? ", context)

    assert handled is True
    app._send_help.assert_awaited_once_with(context)


@pytest.mark.asyncio
async def test_help_button_click_runs_command_and_hides_keyboard():
    """Pressing /new should enqueue a new-session work item and remove the buttons."""
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    app = _make_app()
    app._enqueue_command = AsyncMock()

    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "cmd:new"
    query.edit_message_reply_markup = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await app.on_callback_query(update, context)

    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    app._enqueue_command.assert_awaited_once_with("/new", context)


@pytest.mark.asyncio
async def test_help_button_with_unknown_callback_is_ignored():
    context = MagicMock()

    app = _make_app()
    app._enqueue_command = AsyncMock()

    query = MagicMock()
    query.answer = AsyncMock()
    query.data = "something:else"
    query.edit_message_reply_markup = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    await app.on_callback_query(update, context)

    app._enqueue_command.assert_not_called()
    query.edit_message_reply_markup.assert_not_called()


def test_my_commands_lists_all_pilot_commands():
    """Telegram's '/' menu must list every pilot command with a description."""
    names = {c.command for c in _MY_COMMANDS}
    assert names == {
        "help",
        "new",
        "sessions",
        "session",
        "behavior",
        "behavior_change",
        "stop",
    }
    # Telegram only accepts [a-z0-9_] for command names, so /? cannot be
    # registered. Make sure no invalid name slips in.
    for c in _MY_COMMANDS:
        assert c.command.replace("_", "").isalnum()
        assert c.description, f"missing description for /{c.command}"