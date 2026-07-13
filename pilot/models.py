"""Small data objects shared by the Telegram bridge."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplyHandle:
    """Telegram messages that currently display one in-progress reply."""

    chat_id: int
    main_message_id: int | None = None
    extra_message_ids: list[int] = field(default_factory=list)
    last_text: str = ""
    last_update: float = 0.0


@dataclass
class WorkItem:
    """One prompt or local command waiting for sequential processing."""

    prompt: str
    cronjob_id: str | None = None
    command: str | None = None
    session_no: int | None = None
