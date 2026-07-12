"""Read the human-friendly title and time shown by ``/sessions``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


DEFAULT_SESSION_TITLE = "Untitled"


def read_session_info(path: str) -> tuple[str, str]:
    """Return ``(title, last_message_time)`` for one pi session file."""
    title = DEFAULT_SESSION_TITLE
    last_time = ""

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return title, last_time

    # The first user text becomes the short label in /sessions.
    for line in lines:
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if message.get("role") != "user" or title != DEFAULT_SESSION_TITLE:
            continue

        for item in message.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            if "User prompt:" in text:
                text = text.split("User prompt:", 1)[1].strip()
            first_line = text.split("\n", 1)[0]
            title = first_line[:57] + "..." if len(first_line) > 60 else first_line
            break
        if title != DEFAULT_SESSION_TITLE:
            break

    # The timestamp from the last message is displayed next to the title.
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("type") == "message":
            timestamp = entry.get("timestamp", "")
            if timestamp:
                try:
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    last_time = parsed.strftime("%d.%m. %H:%M")
                except ValueError:
                    pass
            break

    return title, last_time
