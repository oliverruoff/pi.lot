"""Verify final replies are separate, notifying Telegram messages."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pilot.__main__ import PilotApp, ReplyHandle


@pytest.mark.asyncio
async def test_final_reply_is_sent_separately_before_placeholder_is_deleted():
    app = PilotApp.__new__(PilotApp)
    app.cfg = MagicMock(telegram_parse_mode="")
    app.current_reply = ReplyHandle(chat_id=123, main_message_id=456)
    app.app = MagicMock()
    app.app.bot = MagicMock()
    app.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=789))
    app.app.bot.delete_message = AsyncMock()

    await app.send_final_reply("Final answer")

    app.app.bot.send_message.assert_awaited_once_with(
        123,
        "Final answer",
        parse_mode=None,
        disable_notification=False,
    )
    app.app.bot.delete_message.assert_awaited_once_with(123, 456)
