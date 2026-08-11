"""Telegram bridge application.

This module contains the orchestration code that connects Telegram, the pi RPC
process, and the small file-based inboxes used by bundled skills.  The package
entry point lives in ``pilot.__main__`` so this file can focus on the app itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .assistant_messages import extract_error, extract_text, extract_thinking, strip_thinking_blocks
from .config import Config, load_config, persist_config
from .models import ReplyHandle, WorkItem
from .pi_rpc import PiRPC
from .session_info import read_session_info
from .telegram_format import format_for_telegram

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HELP_TEXT = """pi.lot commands:
/help (alias /?) - Show slash-commands
/new - New pi session
/sessions - List known sessions
/session <id> - Switch to session
/behavior - Show current behavior prompt
/behavior_change <string> - Change behavior prompt
/stop - Abort current pi run and clear queued prompts

Unknown slash commands are forwarded to pi (for example /login, /model, /skill:name)."""

# Seconds between typing indicator updates.
_TYPING_INTERVAL = 4.0

# Minimum seconds between Telegram message edits.
_MIN_UPDATE_INTERVAL = 1.0

# How long to wait for pi abort/responsiveness check before restart.
_ABORT_TIMEOUT = 2.0

# Number of session entries to show in /sessions.
_MAX_SESSION_LIST = 20

# Slash commands that take no argument and are exposed as buttons in /help.
_BUTTON_COMMANDS = [("help", "/?"), "new", "sessions", "behavior", "stop"]

# Slash commands shown in Telegram's "/" suggestion menu.
# /? is an alias for /help but Telegram only accepts [a-z0-9_] for command names.
_MY_COMMANDS = [
    BotCommand("help", "Show slash-commands (alias: /?)"),
    BotCommand("new", "Start a new pi session"),
    BotCommand("sessions", "List known sessions"),
    BotCommand("session", "Switch to a session: /session <id>"),
    BotCommand("behavior", "Show the current behavior prompt"),
    BotCommand("behavior_change", "Change the behavior prompt: /behavior_change <text>"),
    BotCommand("stop", "Abort the current run and clear the queue"),
]

# Max length for cronjob status strings.
_MAX_STATUS_LEN = 1000

# Polling intervals for the small file-based skill interfaces.
_FILE_OUTBOX_INTERVAL = 1.0
_PROMPT_INBOX_INTERVAL = 2.0

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class PilotApp:
    """Bridge one authorized Telegram user to one pi RPC process.

    Telegram updates add work to ``queue``. The single worker consumes that
    queue in order, while pi events update the current Telegram reply. Keeping
    one worker makes prompts and session commands deterministic.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.main_user_id: int | None = cfg.main_user_id
        self.main_chat_id: int | None = cfg.main_chat_id

        self.pi = PiRPC(cfg.pi_command, cfg.pi_args, cfg.workdir, self.on_pi_event)
        self.app: Application | None = None

        self.queue: asyncio.Queue[WorkItem] = asyncio.Queue()
        self.busy = False
        self.typing_task: asyncio.Task[None] | None = None

        self.current_reply: ReplyHandle | None = None
        self.current_text = ""
        self.current_thinking = ""
        self.current_status = ""

        self.behavior_prompt = cfg.behavior_prompt
        self.inject_behavior_next = True

        self.sessions: dict[int, str] = {}
        self.active_session_no: int | None = None
        self.pending_ui: dict[str, Any] | None = None

        # All mutable files live below the configured persistent data folder.
        data_dir = Path(cfg.data_dir)
        self.auth_file = data_dir / "auth.json"
        self.prompt_inbox_dir = data_dir / "prompt_inbox"
        self.telegram_file_outbox_dir = data_dir / "telegram_file_outbox"
        self.files_received_dir = data_dir / "files_received"

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start pi, Telegram polling, and the two file inbox watchers."""
        self._load_auth()
        self._load_sessions_at_startup()
        os.environ["PILOT_TELEGRAM_FILE_OUTBOX"] = str(self.telegram_file_outbox_dir)

        await self.pi.start()
        await self._remember_current_session()

        # Process Telegram updates concurrently so one stuck command handler
        # cannot make /stop (or any later message) unreachable.
        self.app = (
            ApplicationBuilder()
            .token(self.cfg.telegram_bot_token)
            .concurrent_updates(True)
            .build()
        )
        self.app.add_handler(MessageHandler(filters.ALL, self.on_update))
        self.app.add_handler(CallbackQueryHandler(self.on_callback_query))

        asyncio.create_task(self.worker())
        asyncio.create_task(self.prompt_inbox_watcher())
        asyncio.create_task(self.telegram_file_outbox_watcher())

        await self.app.initialize()
        await self.app.start()
        # Register the "/" suggestion menu. Failures must not block startup.
        try:
            await self.app.bot.set_my_commands(_MY_COMMANDS)
        except Exception:
            log.exception("failed to register Telegram command suggestions")
        await self.app.updater.start_polling()  # type: ignore[union-attr]

        if self.main_chat_id is not None:
            await self.app.bot.send_message(
                self.main_chat_id,
                self._session_message("pi.lot started.", self.active_session_no),
            )

        log.info("pi.lot started; waiting for first Telegram user")
        await asyncio.Event().wait()

    # ------------------------------------------------------------------
    # Telegram update handler
    # ------------------------------------------------------------------

    async def on_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_chat:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        if self.main_user_id is None:
            self.main_user_id = user_id
            self.main_chat_id = chat_id
            self._save_auth()
            await context.bot.send_message(
                chat_id,
                self._session_message(
                    "pi.lot started. You are now the authorized user.",
                    self.active_session_no,
                ),
            )
            return

        if user_id != self.main_user_id:
            await context.bot.send_message(chat_id, "This pi.lot instance is already bound to another user.")
            return

        msg = update.effective_message
        text = (msg.text or msg.caption) if msg else None

        # Handle file downloads first.
        received_file = await self._download_incoming_file(msg, context) if msg else None
        if received_file:
            await self._enqueue_file_prompt(msg, context, received_file)
            return

        if not text:
            await context.bot.send_message(chat_id, "Only text messages and file attachments are supported.")
            return

        # Rescue commands must preempt extension UI prompts.
        if text.startswith("/") and await self._handle_pilot_command(text, context):
            return

        if self.pending_ui:
            await self._answer_pending_ui(text, context)
            return

        await self._enqueue_text_prompt(text, context)

    # ------------------------------------------------------------------
    # Enqueuing helpers
    # ------------------------------------------------------------------

    async def _enqueue_file_prompt(self, msg: Any, context: ContextTypes.DEFAULT_TYPE, received_file: str) -> None:
        prompt_text = msg.caption or "User sent a Telegram file."
        was_busy = self.busy
        await self.queue.put(
            WorkItem(f"{prompt_text}\n\nReceived Telegram file saved at: {received_file}")
        )
        await self._send_typing_action()
        await context.bot.send_message(self.main_chat_id, f"Downloaded file to {received_file}")
        pending = self.queue.qsize()
        if was_busy and pending:
            await context.bot.send_message(self.main_chat_id, f"Queued ({pending} pending).")

    async def _enqueue_text_prompt(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._enqueue_work(WorkItem(text), context)

    async def _enqueue_work(
        self,
        item: WorkItem,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Queue work and tell the user when it waits behind another item."""
        was_busy = self.busy
        await self.queue.put(item)
        await self._send_typing_action()
        pending = self.queue.qsize()
        if was_busy and pending:
            await context.bot.send_message(self.main_chat_id, f"Queued ({pending} pending).")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_pilot_command(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
        chat_id = self.main_chat_id
        if chat_id is None:
            return True

        cmd, _, arg = text.partition(" ")

        if cmd in {"/help", "/?"}:
            await self._send_help(context)
            return True

        if cmd == "/new":
            await self._cancel_pending_ui()
            await self._enqueue_command("/new", context)
            return True

        if cmd == "/sessions":
            await self._list_sessions(context)
            return True

        if cmd == "/session":
            await self._switch_session(arg, context)
            return True

        if cmd == "/behavior":
            await context.bot.send_message(chat_id, self.behavior_prompt)
            return True

        if cmd == "/behavior_change":
            await self._change_behavior(arg, context)
            return True

        if cmd == "/stop":
            await self._stop_bot(context)
            return True

        # Unknown slash command – forward to pi.
        return False

    async def _send_help(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the help text plus a button row for the no-arg slash commands."""
        buttons = [
            [InlineKeyboardButton(f"/{c}", callback_data=f"cmd:{c}")]
            for entry in _BUTTON_COMMANDS
            for c in (entry if isinstance(entry, tuple) else (entry,))
        ]
        await context.bot.send_message(
            self.main_chat_id,
            HELP_TEXT,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def on_callback_query(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle a button press from a help or extension keyboard."""
        query = update.callback_query
        if query is None:
            return
        await query.answer()

        data = (query.data or "").strip()
        if data.startswith("ui:"):
            await self._answer_pending_ui_callback(update, context, data)
            return
        if not data.startswith("cmd:"):
            return
        cmd = "/" + data[4:].strip()

        # Hide the buttons after a click so they don't linger forever.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            log.debug("could not clear help keyboard", exc_info=True)

        # Reuse the existing slash-command dispatcher. A trailing space mimics
        # the message-format used by MessageHandler updates.
        await self._handle_pilot_command(cmd + " ", context)

    async def _enqueue_command(self, command: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._enqueue_work(WorkItem("", command=command), context)

    async def _list_sessions(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._remember_current_session()
        lines = ["Known sessions:"]
        items = sorted(self.sessions.items(), reverse=True)

        if len(items) > _MAX_SESSION_LIST:
            lines.append(f"  (showing last {_MAX_SESSION_LIST} of {len(items)} sessions)")
            items = items[:_MAX_SESSION_LIST]

        for i, (no, path) in enumerate(items):
            mark = "*" if no == self.active_session_no else " "
            title, last_time = self._get_session_info(path)
            time_str = f" ({last_time})" if last_time else ""
            lines.append(f"{mark} {no}: {title}{time_str}")
            if i < len(items) - 1:
                lines.append("")

        await context.bot.send_message(self.main_chat_id, "\n".join(lines))

    async def _switch_session(self, arg: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        no_str = arg.strip()
        if not no_str.isdigit() or int(no_str) not in self.sessions:
            await context.bot.send_message(self.main_chat_id, "Usage: /session <id>")
            return

        item = WorkItem("", command="/session", session_no=int(no_str))
        await self._cancel_pending_ui()
        await self._enqueue_work(item, context)

    async def _change_behavior(self, arg: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not arg:
            await context.bot.send_message(self.main_chat_id, "Usage: /behavior_change <string>")
            return

        self.behavior_prompt = arg
        self.inject_behavior_next = True
        self._save_config()
        await context.bot.send_message(
            self.main_chat_id,
            "Behavior prompt changed. It will be applied to the next new session/first prompt.",
        )

    async def _stop_bot(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        cleared = self._clear_queue()
        restarted = False
        await self._cancel_pending_ui()

        try:
            await self.pi.abort(timeout=_ABORT_TIMEOUT)
            # Verify the RPC loop is responsive.
            await asyncio.wait_for(self.pi.get_state(), timeout=_ABORT_TIMEOUT)
        except Exception:
            log.exception("pi abort/responsiveness check failed; restarting pi RPC")
            await self.pi.restart()
            await self._remember_current_session()
            restarted = True

        self.current_text = "Stopped."
        self.current_thinking = ""
        self.current_status = ""
        await self.update_reply("Stopped.", force=True)

        suffix = f" Cleared {cleared} queued prompt(s)." if cleared else ""
        restart_note = " pi was unresponsive and was restarted." if restarted else ""
        await context.bot.send_message(self.main_chat_id, f"Stopped.{suffix}{restart_note}")

    def _clear_queue(self) -> int:
        cleared = 0
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self.queue.task_done()
                cleared += 1
        return cleared

    # ------------------------------------------------------------------
    # File download
    # ------------------------------------------------------------------

    async def _download_incoming_file(self, msg: Any, context: ContextTypes.DEFAULT_TYPE) -> str | None:
        attachment = msg.document or (msg.photo[-1] if msg.photo else None) or msg.effective_attachment
        if isinstance(attachment, (list, tuple)):
            attachment = attachment[-1] if attachment else None

        if not attachment or not getattr(attachment, "file_id", None):
            return None

        name = (
            getattr(attachment, "file_name", None)
            or f"telegram-photo-{getattr(attachment, 'file_unique_id', uuid.uuid4().hex)}.jpg"
        )
        safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name).strip("._") or "telegram-file"
        dest = self.files_received_dir / f"{uuid.uuid4().hex}-{safe}"
        self.files_received_dir.mkdir(parents=True, exist_ok=True)

        tg_file = await context.bot.get_file(attachment.file_id)
        await tg_file.download_to_drive(custom_path=str(dest))
        return str(dest)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def worker(self) -> None:
        """Process prompts and local commands one at a time, in queue order."""
        while True:
            item = await self.queue.get()
            self.busy = True
            self.typing_task = asyncio.create_task(self._typing_loop())

            self.current_text = ""
            self.current_thinking = ""
            self.current_status = ""
            previous_active = self.active_session_no
            restored_active = False

            try:
                restored_active = await self._process_work_item(item, previous_active)
            except Exception as e:
                log.exception("prompt failed")
                if item.cronjob_id:
                    self._mark_prompt_status(item.cronjob_id, f"error: {e}")
                await self.update_reply(f"Error: {e}", force=True)
            finally:
                if item.cronjob_id and not restored_active and previous_active and previous_active in self.sessions:
                    try:
                        await self.pi.switch_session(self.sessions[previous_active])
                        self.active_session_no = previous_active
                    except Exception:
                        log.exception("failed to restore active session after cronjob")

                if self.typing_task:
                    self.typing_task.cancel()
                    self.typing_task = None
                self.current_reply = None
                self.busy = False
                self.queue.task_done()

    async def _process_work_item(
        self,
        item: WorkItem,
        previous_active: int | None,
    ) -> bool:
        if item.command == "/new":
            await self._do_new_session()
            return False

        if item.command == "/session":
            await self._do_switch_session(item.session_no)
            return False

        return await self._do_prompt(item, previous_active)

    async def _do_new_session(self) -> None:
        await self.pi.new_session()
        await self._remember_current_session()
        self.inject_behavior_next = True
        if self.main_chat_id and self.app:
            await self.app.bot.send_message(
                self.main_chat_id,
                self._session_message("Started a new pi session.", self.active_session_no),
            )

    async def _do_switch_session(self, session_no: int | None) -> None:
        if session_no is None:
            return
        await self.pi.switch_session(self.sessions[session_no])
        self.active_session_no = session_no
        self.inject_behavior_next = False
        if self.main_chat_id and self.app:
            await self.app.bot.send_message(self.main_chat_id, f"Switched to session {session_no}.")

    async def _do_prompt(
        self,
        item: WorkItem,
        previous_active: int | None,
    ) -> bool:
        if item.cronjob_id:
            await self.pi.new_session()
            await self._remember_current_session(make_active=False)

        prompt = self._build_prompt(item)

        if self.main_chat_id and self.app:
            msg = await self.app.bot.send_message(self.main_chat_id, "Thinking…")
            self.current_reply = ReplyHandle(self.main_chat_id, msg.message_id)

        await self.pi.prompt_and_wait(prompt, streaming_behavior="followUp")
        session_no = await self._remember_current_session(make_active=not bool(item.cronjob_id))

        final = self.current_text.strip() or self.current_status.strip() or "No assistant output was returned."
        if item.cronjob_id:
            final = self._session_message(final, session_no)
        await self.send_final_reply(final)

        if item.cronjob_id:
            self._mark_prompt_status(item.cronjob_id, "success")
            if previous_active and previous_active in self.sessions:
                await self.pi.switch_session(self.sessions[previous_active])
                self.active_session_no = previous_active
                return True

        return False

    def _build_prompt(self, item: WorkItem) -> str:
        prompt = item.prompt
        if item.cronjob_id:
            prompt = f"{self.behavior_prompt}\n\nUser prompt:\n{prompt}"
        elif self.inject_behavior_next:
            prompt = f"{self.behavior_prompt}\n\nUser prompt:\n{prompt}"
            self.inject_behavior_next = False
        return prompt

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    async def _send_typing_action(self) -> None:
        if self.main_chat_id and self.app:
            try:
                await self.app.bot.send_chat_action(self.main_chat_id, ChatAction.TYPING)
            except Exception:
                log.debug("failed to send typing action", exc_info=True)

    async def _typing_loop(self) -> None:
        try:
            while True:
                await self._send_typing_action()
                await asyncio.sleep(_TYPING_INTERVAL)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # pi event handler
    # ------------------------------------------------------------------

    async def on_pi_event(self, event: dict[str, Any]) -> None:
        typ = event.get("type")

        if typ == "message_update":
            await self._handle_message_update(event)
        elif typ == "message_end":
            await self._handle_message_end(event)
        elif typ == "agent_end":
            await self._handle_agent_end(event)
        elif typ == "agent_start":
            await self._handle_agent_start()
        elif typ == "turn_start":
            await self._handle_turn_start()
        elif typ == "tool_execution_start":
            await self._handle_tool_execution_start(event)
        elif typ == "tool_execution_end":
            await self._handle_tool_execution_end(event)
        elif typ == "auto_retry_start":
            await self._handle_auto_retry_start(event)
        elif typ == "auto_retry_end":
            await self._handle_auto_retry_end(event)
        elif typ == "queue_update":
            await self._handle_queue_update(event)
        elif typ == "extension_ui_request":
            await self._handle_extension_ui_request(event)
        elif typ in {"extension_error", "compaction_end"}:
            log.info("pi event: %s", event)

    async def _handle_message_update(self, event: dict[str, Any]) -> None:
        delta = event.get("assistantMessageEvent") or {}
        dtyp = delta.get("type")

        if dtyp == "text_delta":
            self.current_text += delta.get("delta", "")
        elif dtyp == "thinking_delta":
            self.current_thinking += delta.get("delta", "")
        elif dtyp == "error":
            session_path = self._active_session_path()
            err = extract_error(delta.get("error"), session_path) or str(delta.get("reason") or "error")
            self.current_text = f"Error: {err}"

        await self.update_reply(self._compose_display())

    async def _handle_message_end(self, event: dict[str, Any]) -> None:
        self._capture_message(event.get("message"))
        await self.update_reply(self._compose_display(), force=True)

    async def _handle_agent_end(self, event: dict[str, Any]) -> None:
        for message in event.get("messages") or []:
            self._capture_message(message)
        await self.update_reply(self._compose_display(), force=True)

    async def _handle_agent_start(self) -> None:
        self.current_status = "Agent started…"
        await self.update_reply(self._compose_display(), force=True)

    async def _handle_turn_start(self) -> None:
        self.current_status = "Thinking…"
        await self.update_reply(self._compose_display())

    async def _handle_tool_execution_start(self, event: dict[str, Any]) -> None:
        self.current_status = f"Running tool: {event.get('toolName')}…"
        await self.update_reply(self._compose_display())

    async def _handle_tool_execution_end(self, event: dict[str, Any]) -> None:
        self.current_status = f"Finished tool: {event.get('toolName')}"
        await self.update_reply(self._compose_display())

    async def _handle_auto_retry_start(self, event: dict[str, Any]) -> None:
        attempt = event.get("attempt")
        max_attempts = event.get("maxAttempts")
        delay_ms = event.get("delayMs") or 0
        seconds = max(1, round(float(delay_ms) / 1000))
        err = str(event.get("errorMessage") or "provider error")
        self.current_status = f"Provider error; retrying {attempt}/{max_attempts} in {seconds}s…\n{err[-1200:]}"
        await self.update_reply(self._compose_display(), force=True)

    async def _handle_auto_retry_end(self, event: dict[str, Any]) -> None:
        if event.get("success") is False:
            self.current_text = f"Error: {event.get('finalError') or 'provider retry failed'}"
            self.current_status = ""
            await self.update_reply(self._compose_display(), force=True)
        else:
            self.current_status = "Retry succeeded; continuing…"
            await self.update_reply(self._compose_display(), force=True)

    async def _handle_queue_update(self, event: dict[str, Any]) -> None:
        steering = len(event.get("steering") or [])
        follow_up = len(event.get("followUp") or [])
        if steering or follow_up:
            self.current_status = f"Queued in pi: {steering} steering, {follow_up} follow-up"
            await self.update_reply(self._compose_display())

    # ------------------------------------------------------------------
    # Message extraction helpers
    # ------------------------------------------------------------------

    def _capture_message(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return

        session_path = self._active_session_path()
        text = extract_text(message)
        thinking = extract_thinking(message)
        error = extract_error(message, session_path)

        if thinking and not self.current_thinking:
            self.current_thinking = thinking
        if error:
            self.current_text = f"Error: {error}"
            self.current_status = ""
        elif text:
            self.current_text = text
            self.current_status = ""

    def _active_session_path(self) -> str | None:
        """Return the path of the active session, if one is known."""
        sessions = getattr(self, "sessions", {})
        active_session_no = getattr(self, "active_session_no", None)
        return sessions.get(active_session_no or -1)

    def _compose_display(self) -> str:
        body = strip_thinking_blocks(self.current_text.strip())
        if not body:
            body = "Thinking…"
            if self.current_thinking:
                body += "\n\n" + self.current_thinking[-3000:]
        if self.current_status and self.current_status.strip() != body.strip():
            body += "\n\n" + self.current_status
        return body

    # ------------------------------------------------------------------
    # Telegram reply helpers
    # ------------------------------------------------------------------

    def _is_markdown_v2(self) -> bool:
        return self.cfg.telegram_parse_mode.lower() == "markdownv2"

    def _format_parts(self, text: str) -> tuple[list[str], ParseMode | None]:
        markdown = self._is_markdown_v2()
        parts = format_for_telegram(text, markdown_v2=markdown)
        parse_mode = ParseMode.MARKDOWN_V2 if markdown else None
        return parts, parse_mode

    async def send_final_reply(self, text: str) -> None:
        if not self.current_reply or not self.app:
            return

        parts, parse_mode = self._format_parts(text)
        bot = self.app.bot
        sent_message_ids: list[int] = []

        async def _send() -> None:
            for part in parts:
                message = await bot.send_message(
                    self.current_reply.chat_id,
                    part or " ",
                    parse_mode=parse_mode,
                    disable_notification=False,
                )
                sent_message_ids.append(message.message_id)

        success = await self._send_with_retry(_send, is_final=True, final_text=text)
        if not success:
            return

        log.info("telegram final sent: chat_id=%s message_ids=%s", self.current_reply.chat_id, sent_message_ids)

        # Delete the old "Thinking…" message and any extra split messages.
        for mid in [self.current_reply.main_message_id, *self.current_reply.extra_message_ids]:
            if mid is None:
                continue
            try:
                await bot.delete_message(self.current_reply.chat_id, mid)
            except Exception:
                pass
        self.current_reply.extra_message_ids.clear()

    async def update_reply(self, text: str, force: bool = False) -> None:
        if not self.current_reply or not self.app:
            return

        now = asyncio.get_running_loop().time()
        if not force and now - self.current_reply.last_update < _MIN_UPDATE_INTERVAL:
            return
        if text == self.current_reply.last_text and not force:
            return

        self.current_reply.last_text = text
        self.current_reply.last_update = now

        parts, parse_mode = self._format_parts(text)
        bot = self.app.bot

        async def _edit() -> None:
            await bot.edit_message_text(
                chat_id=self.current_reply.chat_id,
                message_id=self.current_reply.main_message_id,
                text=parts[0] or " ",
                parse_mode=parse_mode,
            )
            # Replace extra split messages.
            for mid in self.current_reply.extra_message_ids:
                try:
                    await bot.delete_message(self.current_reply.chat_id, mid)
                except Exception:
                    pass
            self.current_reply.extra_message_ids.clear()
            for part in parts[1:]:
                m = await bot.send_message(self.current_reply.chat_id, part, parse_mode=parse_mode)
                self.current_reply.extra_message_ids.append(m.message_id)

        await self._send_with_retry(_edit, is_final=False)

    async def _send_with_retry(self, sender: Any, is_final: bool, final_text: str | None = None) -> bool:
        """Run a Telegram sender coroutine with retry logic. Returns True on success."""
        bot = self.app.bot if self.app else None
        if bot is None:
            return False

        try:
            try:
                await sender()
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after))
                await sender()
            return True
        except BadRequest as e:
            if is_final:
                log.warning("telegram final markdown send failed; retrying plain text: %s", e)
                return await self._send_final_plain_text(final_text or self.current_reply.last_text)
            log.warning("telegram update failed: %s", e)
        except (NetworkError, TimedOut) as e:
            if is_final:
                log.warning("telegram final send failed; retrying once: %s", e)
                try:
                    await sender()
                    return True
                except Exception:
                    log.exception("telegram final send retry failed; keeping thinking message")
                    return False
            log.warning("telegram update failed: %s", e)
        except Exception:
            if is_final:
                log.exception("telegram final send failed; keeping thinking message")
            else:
                log.exception("telegram update failed")
        return False

    async def _send_final_plain_text(self, text: str) -> bool:
        if not self.current_reply or not self.app:
            return False

        parts = format_for_telegram(text, markdown_v2=False)
        bot = self.app.bot

        try:
            try:
                for part in parts:
                    await bot.send_message(
                        self.current_reply.chat_id,
                        part or " ",
                        disable_notification=False,
                    )
            except RetryAfter as retry:
                await asyncio.sleep(float(retry.retry_after))
                for part in parts:
                    await bot.send_message(
                        self.current_reply.chat_id,
                        part or " ",
                        disable_notification=False,
                    )
            return True
        except Exception:
            log.exception("telegram final plain-text send failed; keeping thinking message")
            return False

    # ------------------------------------------------------------------
    # File outbox watcher
    # ------------------------------------------------------------------

    async def telegram_file_outbox_watcher(self) -> None:
        self.telegram_file_outbox_dir.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                await self._process_telegram_file_outbox()
            except Exception:
                log.exception("telegram file outbox watcher failed")
            await asyncio.sleep(_FILE_OUTBOX_INTERVAL)

    async def _process_telegram_file_outbox(self) -> None:
        for path in sorted(self.telegram_file_outbox_dir.glob("*.json")):
            if self.main_chat_id is None or not self.app:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                file_path = Path(str(data.get("path") or ""))
                if not file_path.is_file():
                    raise ValueError(f"not a file: {file_path}")

                caption = str(data.get("caption") or "")[:1024] or None
                with file_path.open("rb") as f:
                    await self.app.bot.send_document(
                        self.main_chat_id,
                        document=f,
                        filename=file_path.name,
                        caption=caption,
                    )
                path.unlink(missing_ok=True)
            except Exception as e:
                log.exception("failed to send Telegram file request %s", path)
                try:
                    path.rename(path.with_suffix(".error"))
                except Exception:
                    pass
                if self.main_chat_id and self.app:
                    await self.app.bot.send_message(self.main_chat_id, f"Telegram file send error: {e}")

    # ------------------------------------------------------------------
    # Prompt inbox watcher
    # ------------------------------------------------------------------

    async def prompt_inbox_watcher(self) -> None:
        self.prompt_inbox_dir.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                await self._process_prompt_inbox()
            except Exception:
                log.exception("prompt inbox watcher failed")
            await asyncio.sleep(_PROMPT_INBOX_INTERVAL)

    async def _process_prompt_inbox(self) -> None:
        for path in sorted(self.prompt_inbox_dir.glob("*.json")):
            if self.main_chat_id is None:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                prompt = str(data.get("prompt") or "")
                if not prompt.strip():
                    raise ValueError("prompt inbox item has no prompt")

                source_id = str(data.get("id") or "") or None
                is_cronjob = data.get("source") == "cronjobs-skill"
                await self.queue.put(WorkItem(prompt, cronjob_id=source_id if is_cronjob else None))
                path.unlink(missing_ok=True)

                if self.app and data.get("title"):
                    await self.app.bot.send_message(self.main_chat_id, str(data["title"]))
            except Exception as e:
                log.exception("failed to process prompt inbox item %s", path)
                try:
                    path.rename(path.with_suffix(".error"))
                except Exception:
                    pass
                if self.main_chat_id and self.app:
                    await self.app.bot.send_message(self.main_chat_id, f"Prompt inbox error: {e}")

    # ------------------------------------------------------------------
    # Cronjob status helpers
    # ------------------------------------------------------------------

    def _mark_prompt_status(self, item_id: str, status: str) -> None:
        # Generic best-effort status update for prompt inbox producers that use
        # /data/cronjobs.json-like records. Kept generic so skills stay
        # self-contained and pilot does not import skill code.
        try:
            path = Path(self.cfg.data_dir) / "cronjobs.json"
            if not path.exists():
                return

            data = json.loads(path.read_text(encoding="utf-8"))
            jobs = data if isinstance(data, list) else data.get("cronjobs", [])

            for job in jobs:
                if job.get("id") == item_id:
                    job["last_status"] = status[:_MAX_STATUS_LEN]
                    now = datetime.now(timezone.utc).isoformat()
                    job["last_run_at"] = now
                    job["updated_at"] = now

                    tmp = path.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    tmp.replace(path)
                    return
        except Exception:
            log.exception("failed to update prompt status")

    # ------------------------------------------------------------------
    # Auth & session persistence
    # ------------------------------------------------------------------

    def _load_auth(self) -> None:
        if self.main_user_id is not None and self.main_chat_id is not None:
            return
        try:
            if self.auth_file.exists():
                data = json.loads(self.auth_file.read_text(encoding="utf-8"))
                self.main_user_id = int(data["user_id"])
                self.main_chat_id = int(data["chat_id"])
                self._save_config()
        except Exception:
            log.exception("failed to load auth file")

    def _save_auth(self) -> None:
        self._save_config()
        try:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            self.auth_file.write_text(
                json.dumps({"user_id": self.main_user_id, "chat_id": self.main_chat_id}) + "\n",
                encoding="utf-8",
            )
        except Exception:
            log.exception("failed to save auth file")

    def _save_config(self) -> None:
        try:
            self.cfg = replace(
                self.cfg,
                behavior_prompt=self.behavior_prompt,
                main_user_id=self.main_user_id,
                main_chat_id=self.main_chat_id,
            )
            persist_config(self.cfg)
        except Exception:
            log.exception("failed to save config file")

    def _load_sessions_at_startup(self) -> None:
        try:
            session_dir = Path(self.cfg.data_dir) / "pi-sessions"
            if not session_dir.exists():
                return
            for path in sorted(session_dir.glob("*.jsonl")):
                no = max(self.sessions.keys(), default=0) + 1
                self.sessions[no] = str(path)
        except Exception:
            log.exception("failed to load sessions at startup")

    # ------------------------------------------------------------------
    # Session info helpers
    # ------------------------------------------------------------------

    async def _remember_current_session(self, make_active: bool = True) -> int | None:
        try:
            state = await self.pi.get_state()
        except Exception:
            return None

        path = state.get("sessionFile")
        if not path:
            return None

        for no, existing in self.sessions.items():
            if existing == path:
                if make_active:
                    self.active_session_no = no
                return no

        no = max(self.sessions.keys(), default=0) + 1
        self.sessions[no] = path
        if make_active:
            self.active_session_no = no
        return no

    def _session_message(self, text: str, session_no: int | None) -> str:
        no = session_no if session_no is not None else "unknown"
        return f"Session ID: {no}\n\n{text}"

    def _get_session_info(self, path: str) -> tuple[str, str]:
        return read_session_info(path)

    # ------------------------------------------------------------------
    # Extension UI helpers
    # ------------------------------------------------------------------

    async def _handle_extension_ui_request(self, event: dict[str, Any]) -> None:
        if not self.main_chat_id or not self.app:
            return

        method = event.get("method")
        if method in {"notify", "setStatus", "setWidget", "setTitle", "set_editor_text"}:
            msg = event.get("message") or event.get("title") or event.get("statusText")
            if msg:
                await self.app.bot.send_message(self.main_chat_id, str(msg))
            return

        await self._cancel_pending_ui()
        await self._pause_for_ui()
        if method == "select":
            opts = event.get("options") or []
            body = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts))
            prompt = str(event.get("title") or "Select an option")
            markup = None
            if 1 <= len(opts) <= 8:
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(str(option), callback_data=f"ui:{event.get('id')}:{i}")]
                     for i, option in enumerate(opts)]
                )
            elif body:
                prompt = f"{prompt}:\n{body}"
        elif method == "confirm":
            prompt = f"{event.get('title', 'Confirm')}\n{event.get('message', '')}\nReply yes or no."
            markup = None
        else:
            prompt = event.get("title") or f"pi requests {method} input"
            markup = None

        message = await self.app.bot.send_message(self.main_chat_id, prompt, reply_markup=markup)
        self.pending_ui = {
            **event,
            "message_id": message.message_id,
        }

    async def _pause_for_ui(self) -> None:
        """Stop transient output while pi waits for a Telegram answer."""
        if self.typing_task:
            self.typing_task.cancel()
            self.typing_task = None

        if self.current_reply and self.app:
            for message_id in [
                self.current_reply.main_message_id,
                *self.current_reply.extra_message_ids,
            ]:
                if message_id is None:
                    continue
                try:
                    await self.app.bot.delete_message(self.current_reply.chat_id, message_id)
                except Exception:
                    log.debug("could not clear pre-question reply", exc_info=True)
        self.current_reply = None
        self.current_text = ""
        self.current_thinking = ""
        self.current_status = ""

    async def _resume_after_ui(self) -> None:
        """Start a fresh reply below the user's UI answer."""
        if not self.main_chat_id or not self.app:
            return
        message = await self.app.bot.send_message(self.main_chat_id, "Thinking…")
        self.current_reply = ReplyHandle(self.main_chat_id, message.message_id)
        self.typing_task = asyncio.create_task(self._typing_loop())

    async def _answer_pending_ui(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        event = await self._take_pending_ui()
        await self._clear_ui_keyboard(event)
        method = event.get("method")

        data: dict[str, Any] = {"id": event.get("id")}
        lowered = text.strip().lower()

        if lowered in {"/cancel", "cancel"}:
            data["cancelled"] = True
        elif method == "confirm":
            data["confirmed"] = lowered in {"y", "yes", "true", "1", "ok"}
        elif method == "select":
            opts = event.get("options") or []
            value = text.strip()
            if value.isdigit() and 1 <= int(value) <= len(opts):
                value = opts[int(value) - 1]
            data["value"] = value
        else:
            data["value"] = text

        await self._resume_after_ui()
        await self.pi.extension_ui_response(data)

    async def _answer_pending_ui_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        callback_data: str,
    ) -> None:
        """Resolve a pending select request from an inline button."""
        if not update.effective_user or update.effective_user.id != self.main_user_id:
            return

        parts = callback_data.split(":", 2)
        event = self.pending_ui
        if len(parts) != 3 or not event or parts[1] != str(event.get("id")):
            return

        options = event.get("options") or []
        try:
            value = options[int(parts[2])]
        except (ValueError, IndexError):
            return

        event = await self._take_pending_ui()
        await self._clear_ui_keyboard(event)
        await self.app.bot.send_message(self.main_chat_id, f"User answered: {value}")
        await self._resume_after_ui()
        await self.pi.extension_ui_response({"id": event.get("id"), "value": value})

    async def _take_pending_ui(self) -> dict[str, Any]:
        event = self.pending_ui or {}
        self.pending_ui = None
        return event

    async def _cancel_pending_ui(self) -> None:
        if not getattr(self, "pending_ui", None):
            return
        event = await self._take_pending_ui()
        await self._clear_ui_keyboard(event)
        await self.pi.extension_ui_response({"id": event.get("id"), "cancelled": True})

    async def _clear_ui_keyboard(self, event: dict[str, Any]) -> None:
        message_id = event.get("message_id")
        if not message_id or not self.main_chat_id or not self.app:
            return
        try:
            await self.app.bot.edit_message_reply_markup(
                chat_id=self.main_chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except Exception:
            log.debug("could not clear extension keyboard", exc_info=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx INFO logs include full Telegram Bot API URLs, which contain the bot
    # token. Keep them out of container logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(PilotApp(cfg).run())
