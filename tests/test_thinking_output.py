"""Verify thinking is streamed but excluded from completed answers."""
from unittest.mock import AsyncMock

import pytest

from pilot.app import PilotApp


@pytest.mark.asyncio
async def test_thinking_is_streamed():
    app = PilotApp.__new__(PilotApp)
    app.current_text = ""
    app.current_thinking = ""
    app.current_status = "Thinking…"
    app.update_reply = AsyncMock()

    await app._handle_message_update(
        {"assistantMessageEvent": {"type": "thinking_delta", "delta": "Internal reasoning"}}
    )
    assert "Internal reasoning" in app._compose_display()


def test_leading_think_block_is_removed_from_completed_answer():
    app = PilotApp.__new__(PilotApp)
    app.current_text = ""
    app.current_thinking = ""
    app.current_status = ""

    app._capture_message(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "<think>Internal reasoning</think>Final answer",
                }
            ],
        }
    )

    assert app.current_text == "Final answer"


@pytest.mark.asyncio
async def test_think_tags_are_hidden_during_streaming():
    app = PilotApp.__new__(PilotApp)
    app.current_text = ""
    app.current_thinking = ""
    app.current_status = ""
    app.update_reply = AsyncMock()

    # Simulate the model streaming a <think>…</think> block followed by the
    # real answer as text_delta events.
    for delta in ["<think>Internal reasoning</think>", "Hello ", "world"]:
        await app._handle_message_update(
            {"assistantMessageEvent": {"type": "text_delta", "delta": delta}}
        )

    display = app._compose_display()
    assert "<think>" not in display
    assert "</think>" not in display
    assert "Hello world" in display
