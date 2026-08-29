"""Verify extension UI questions are rendered and resolved through Telegram."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from telegram import InlineKeyboardMarkup

from pilot.app import PilotApp


def _make_app() -> PilotApp:
    app = PilotApp.__new__(PilotApp)
    app.cfg = MagicMock(telegram_parse_mode="")
    app.main_user_id = 7
    app.main_chat_id = 12345
    app.pending_ui = None
    app.typing_task = None
    app.current_reply = None
    app.current_text = ""
    app.current_thinking = ""
    app.current_status = ""
    app.pi = MagicMock()
    app.pi.extension_ui_response = AsyncMock()
    app.app = MagicMock()
    app.app.bot = MagicMock()
    sent = MagicMock(message_id=99)
    app.app.bot.send_message = AsyncMock(return_value=sent)
    app.app.bot.edit_message_reply_markup = AsyncMock()
    app.app.bot.delete_message = AsyncMock()
    return app


@pytest.mark.asyncio
async def test_select_request_uses_dynamic_labels_as_buttons():
    app = _make_app()
    event = {
        "id": "request-1",
        "method": "select",
        "title": "Wie möchtest du weitermachen?",
        "options": ["Direkt umsetzen", "Erst den Diff zeigen"],
    }

    await app._handle_extension_ui_request(event)

    _, kwargs = app.app.bot.send_message.call_args
    markup = kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    assert [button.text for row in markup.inline_keyboard for button in row] == event["options"]
    assert app.pending_ui["message_id"] == 99


@pytest.mark.asyncio
async def test_select_request_extracts_label_from_structured_option():
    app = _make_app()
    event = {
        "id": "request-1",
        "method": "select",
        "title": "Wie möchtest du weitermachen?",
        "options": [
            {"label": "Direkt umsetzen"},
            "Erst den Diff zeigen",
        ],
    }

    await app._handle_extension_ui_request(event)

    _, kwargs = app.app.bot.send_message.call_args
    labels = [button.text for row in kwargs["reply_markup"].inline_keyboard for button in row]
    assert labels == ["Direkt umsetzen", "Erst den Diff zeigen"]
    assert app.pending_ui["options"] == labels


@pytest.mark.asyncio
async def test_select_request_removes_progress_reply_and_stops_typing():
    app = _make_app()
    app.current_reply = MagicMock(
        chat_id=12345,
        main_message_id=50,
        extra_message_ids=[51],
    )
    app.typing_task = MagicMock()

    await app._handle_extension_ui_request({
        "id": "request-1",
        "method": "select",
        "title": "Wie weiter?",
        "options": ["A"],
    })

    assert app.typing_task is None
    app.app.bot.delete_message.assert_has_awaits([
        call(12345, 50),
        call(12345, 51),
    ])
    assert app.current_reply is None


@pytest.mark.asyncio
async def test_select_request_preserves_answer_before_question():
    app = _make_app()
    app.current_reply = MagicMock(
        chat_id=12345,
        main_message_id=50,
        extra_message_ids=[],
    )
    app.current_text = "Hier ist die eigentliche Antwort."

    await app._handle_extension_ui_request({
        "id": "request-1",
        "method": "select",
        "title": "Möchtest du noch ein Beispiel?",
        "options": ["Ja, bitte"],
    })

    assert app.app.bot.send_message.await_args_list[0].args == (
        12345,
        "Hier ist die eigentliche Antwort.",
    )
    assert app.app.bot.send_message.await_args_list[1].args == (
        12345,
        "Möchtest du noch ein Beispiel?",
    )
    app.app.bot.delete_message.assert_awaited_once_with(12345, 50)
    assert app.current_text == ""


@pytest.mark.asyncio
async def test_one_option_is_allowed():
    app = _make_app()

    await app._handle_extension_ui_request({
        "id": "request-1",
        "method": "select",
        "title": "Bereit?",
        "options": ["Los geht's"],
    })

    _, kwargs = app.app.bot.send_message.call_args
    assert kwargs["reply_markup"].inline_keyboard[0][0].text == "Los geht's"


@pytest.mark.asyncio
async def test_more_than_eight_options_falls_back_to_numbered_text():
    app = _make_app()
    options = [f"Option {i}" for i in range(9)]

    await app._handle_extension_ui_request({
        "id": "request-1",
        "method": "select",
        "title": "Auswahl",
        "options": options,
    })

    args, kwargs = app.app.bot.send_message.call_args
    assert kwargs["reply_markup"] is None
    assert "9. Option 8" in args[1]


@pytest.mark.asyncio
async def test_button_click_returns_selected_label_and_clears_keyboard():
    app = _make_app()
    app.pending_ui = {
        "id": "request-1",
        "method": "select",
        "options": ["A", "B"],
        "message_id": 99,
    }
    update = MagicMock()
    update.effective_user.id = 7

    await app._answer_pending_ui_callback(update, MagicMock(), "ui:request-1:1")

    app.pi.extension_ui_response.assert_awaited_once_with({"id": "request-1", "value": "B"})
    app.app.bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=12345, message_id=99, reply_markup=None
    )
    assert app.app.bot.send_message.await_args_list[0].args == (12345, "B")
    assert app.app.bot.send_message.await_args_list[1].args == (12345, "Thinking…")
    assert app.pending_ui is None
    app.typing_task.cancel()


@pytest.mark.asyncio
async def test_typed_answer_remains_supported_and_clears_keyboard():
    app = _make_app()
    app.pending_ui = {
        "id": "request-1",
        "method": "select",
        "options": ["A"],
        "message_id": 99,
    }
    context = MagicMock()
    context.bot.send_message = AsyncMock()

    await app._answer_pending_ui("Etwas anderes", context)

    app.pi.extension_ui_response.assert_awaited_once_with(
        {"id": "request-1", "value": "Etwas anderes"}
    )
    app.app.bot.edit_message_reply_markup.assert_awaited_once()
    app.typing_task.cancel()


@pytest.mark.asyncio
async def test_stale_or_foreign_button_is_ignored():
    app = _make_app()
    app.pending_ui = {"id": "current", "options": ["A"]}
    update = MagicMock()
    update.effective_user.id = 999

    await app._answer_pending_ui_callback(update, MagicMock(), "ui:current:0")

    app.pi.extension_ui_response.assert_not_awaited()
    assert app.pending_ui is not None
