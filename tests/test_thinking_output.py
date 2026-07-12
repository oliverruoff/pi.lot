"""Verify thinking is streamed but excluded once answer text starts."""
from unittest.mock import AsyncMock

import pytest

from pilot.__main__ import PilotApp


@pytest.mark.asyncio
async def test_thinking_is_replaced_by_answer_text():
    app = PilotApp.__new__(PilotApp)
    app.current_text = ""
    app.current_thinking = ""
    app.current_status = "Thinking…"
    app.update_reply = AsyncMock()

    await app._handle_message_update(
        {"assistantMessageEvent": {"type": "thinking_delta", "delta": "Internal reasoning"}}
    )
    assert "Internal reasoning" in app._compose_display()

    await app._handle_message_update(
        {"assistantMessageEvent": {"type": "text_delta", "delta": "Final answer"}}
    )
    assert app._compose_display() == "Final answer"
    assert app.current_thinking == ""
