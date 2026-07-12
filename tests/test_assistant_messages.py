"""Characterize how completed pi messages are presented to Telegram."""

from pilot.assistant_messages import extract_error, extract_text, extract_thinking


def test_extracts_each_assistant_content_type():
    message = {
        "content": [
            {"type": "thinking", "thinking": "Internal reasoning"},
            {"type": "text", "text": "<think>Hidden copy</think>Final answer"},
        ]
    }

    assert extract_thinking(message) == "Internal reasoning"
    assert extract_text(message) == "Final answer"


def test_error_includes_available_debugging_context():
    message = {
        "stopReason": "error",
        "errorMessage": "Provider failed",
        "provider": "example",
        "model": "model-1",
        "responseId": "response-123",
    }

    error = extract_error(message, "/sessions/current.jsonl")

    assert "Provider failed" in error
    assert "provider/model: example/model-1" in error
    assert "responseId: response-123" in error
    assert "session: /sessions/current.jsonl" in error
