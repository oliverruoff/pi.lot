"""Invitations grant delivery access only, never access to the agent."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pilot.app import PilotApp
from pilot.config import Config
from pilot.contacts import Contacts


def make_app(tmp_path):
    return PilotApp(Config(
        telegram_bot_token="test", workdir=str(tmp_path), behavior_prompt="",
        log_level="INFO", pi_command="pi", pi_args=[], telegram_parse_mode="",
        data_dir=str(tmp_path), main_user_id=1, main_chat_id=1,
    ))


def update(user_id, text, chat_type="private"):
    return MagicMock(
        effective_user=MagicMock(id=user_id),
        effective_chat=MagicMock(id=user_id, type=chat_type),
        effective_message=MagicMock(text=text),
    )


def test_invitation_is_persistent_single_use_and_expiring(tmp_path, monkeypatch):
    contacts = Contacts(tmp_path / "contacts.json")
    token = contacts.invite("Anna")
    contacts = Contacts(contacts.path)
    assert contacts.accept(token, 2) == "Anna"
    with pytest.raises(ValueError):
        contacts.accept(token, 3)
    assert Contacts(contacts.path).chat_id("Anna") == 2
    contacts.invite("Ben")
    monkeypatch.setattr("pilot.contacts.time.time", lambda: float("inf"))
    with pytest.raises(ValueError):
        contacts.accept(contacts.entries["Ben"]["token"], 3)
    with pytest.raises(ValueError):
        contacts.chat_id("Ben")
    with pytest.raises(ValueError):
        contacts.invite("Anna")


@pytest.mark.asyncio
async def test_recipient_registration_and_unsubscribe_never_reach_pi(tmp_path):
    app = make_app(tmp_path)
    app._enqueue_text_prompt = AsyncMock()
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    token = app.contacts.invite("Anna")
    await app.on_update(update(2, f"/start {token}"), context)
    assert app.contacts.chat_id("Anna") == 2
    assert context.bot.send_message.call_args.args[0] == 1
    await app.on_update(update(2, "Read the owner's files"), context)
    await app.on_update(update(2, "/adduser Mallory"), context)
    app._enqueue_text_prompt.assert_not_awaited()
    assert list(app.contacts.entries) == ["Anna"]
    await app.on_update(update(2, "/stop"), context)
    assert Contacts(app.contacts.path).entries == {}
    assert app.main_user_id == 1


@pytest.mark.asyncio
async def test_group_cannot_redeem_invitation_or_claim_owner(tmp_path):
    app = make_app(tmp_path)
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    token = app.contacts.invite("Anna")
    await app.on_update(update(2, f"/start {token}", "group"), context)
    assert "chat_id" not in app.contacts.entries["Anna"]
    app.main_user_id = None
    await app.on_update(update(2, "hello", "group"), context)
    await app.on_update(update(2, f"/start {token}"), context)
    assert app.main_user_id is None


@pytest.mark.asyncio
async def test_owner_creates_lists_and_revokes_invitations(tmp_path):
    app = make_app(tmp_path)
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.get_me = AsyncMock(return_value=MagicMock(username="pilot_bot"))
    await app._handle_pilot_command("/adduser Anna", context)
    assert "https://t.me/pilot_bot?start=" in context.bot.send_message.call_args.args[1]
    await app._handle_pilot_command("/users", context)
    assert "Anna" in context.bot.send_message.call_args.args[1]
    token = app.contacts.entries["Anna"]["token"]
    await app._handle_pilot_command("/removeuser Anna", context)
    with pytest.raises(ValueError):
        app.contacts.accept(token, 2)


@pytest.mark.asyncio
async def test_outbox_rechecks_registration_before_sending(tmp_path):
    app = make_app(tmp_path)
    app.app = MagicMock()
    app.app.bot.send_message = AsyncMock()
    app.contacts.accept(app.contacts.invite("Anna"), 2)
    app.telegram_file_outbox_dir.mkdir()
    request = app.telegram_file_outbox_dir / "message.json"
    payload = {"recipient": "Anna", "chat_id": 2, "text": "Hello"}
    request.write_text(json.dumps(payload))
    await app._process_telegram_file_outbox()
    app.app.bot.send_message.assert_awaited_once_with(2, "Hello")
    assert not request.exists()
    app.app.bot.send_message.reset_mock()
    request.write_text(json.dumps(payload))
    app.contacts.unsubscribe(2)
    await app._process_telegram_file_outbox()
    assert app.app.bot.send_message.call_args.args[0] == 1
    assert request.with_suffix(".error").exists()


@pytest.mark.asyncio
async def test_recipient_cannot_use_owner_callbacks(tmp_path):
    app = make_app(tmp_path)
    app._handle_pilot_command = AsyncMock()
    incoming = update(2, "")
    incoming.callback_query.answer = AsyncMock()
    incoming.callback_query.data = "cmd:new"
    await app.on_callback_query(incoming, MagicMock())
    app._handle_pilot_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_message_cannot_be_redirected_to_reused_name(tmp_path):
    app = make_app(tmp_path)
    app.app = MagicMock()
    app.app.bot.send_message = AsyncMock()
    app.contacts.accept(app.contacts.invite("Anna"), 3)
    app.telegram_file_outbox_dir.mkdir()
    request = app.telegram_file_outbox_dir / "message.json"
    request.write_text(json.dumps({"recipient": "Anna", "chat_id": 2, "text": "Private"}))
    await app._process_telegram_file_outbox()
    assert app.app.bot.send_message.call_args.args[0] == 1
    assert request.with_suffix(".error").exists()


@pytest.mark.asyncio
async def test_existing_file_delivery_still_works(tmp_path):
    app = make_app(tmp_path)
    app.app = MagicMock()
    app.app.bot.send_document = AsyncMock()
    app.telegram_file_outbox_dir.mkdir()
    attachment = tmp_path / "note.txt"
    attachment.write_text("hello")
    request = app.telegram_file_outbox_dir / "file.json"
    request.write_text(json.dumps({"path": str(attachment), "caption": "Note"}))
    await app._process_telegram_file_outbox()
    args, kwargs = app.app.bot.send_document.call_args
    assert args == (1,)
    assert kwargs["filename"] == "note.txt"
    assert kwargs["caption"] == "Note"
    assert not request.exists()
