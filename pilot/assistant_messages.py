"""Read text, thinking, and errors from pi assistant messages."""

from __future__ import annotations

import re
from typing import Any


_LEADING_THINK_BLOCKS = re.compile(r"^\s*(?:<think>.*?</think>\s*)+", re.DOTALL)


def extract_text(message: Any) -> str:
    """Return finalized assistant text without leaked leading thinking blocks."""
    if not isinstance(message, dict):
        return ""

    text = "".join(
        str(item.get("text") or "")
        for item in message.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ).strip()
    return _LEADING_THINK_BLOCKS.sub("", text)


def extract_thinking(message: Any) -> str:
    """Return thinking content included in a completed assistant message."""
    if not isinstance(message, dict):
        return ""

    return "".join(
        str(item.get("thinking") or "")
        for item in message.get("content") or []
        if isinstance(item, dict) and item.get("type") == "thinking"
    ).strip()


def extract_error(message: Any, session_path: str | None = None) -> str:
    """Return a readable error, including available provider context."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""

    error = str(message.get("errorMessage") or message.get("message") or "").strip()
    if not error:
        error = next(
            (
                str(item.get("errorMessage") or item.get("message") or "").strip()
                for item in message.get("content") or []
                if isinstance(item, dict) and item.get("type") == "error"
            ),
            "",
        )

    if message.get("stopReason") != "error":
        return error

    provider_and_model = "/".join(
        str(value)
        for value in (message.get("provider"), message.get("model"))
        if value
    )
    details = [
        value
        for value in (
            f"provider/model: {provider_and_model}",
            f"responseId: {message.get('responseId')}",
            f"session: {session_path}",
        )
        if not value.endswith(": None") and not value.endswith(": ")
    ]

    lines = [error or "Provider returned an error before completing the response."]
    if details:
        lines.extend(["", "Details:", *[f"- {detail}" for detail in details]])
    lines.extend(["", "The session should still be usable; you can continue in it if you want."])
    return "\n".join(lines)
