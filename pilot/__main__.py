from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters

from .config import Config, load_config
from .pi_rpc import PiRPC
from .telegram_format import format_for_telegram

log = logging.getLogger(__name__)

HELP = """pi.lot commands:
/help - Show slash-commands
/new - New pi session
/sessions - List known sessions
/session <id> - Switch to session
/behavior - Show current behavior prompt
/behavior_change <string> - Change behavior prompt
/stop - Abort current pi run and clear queued prompts

Unknown slash commands are forwarded to pi (for example /login, /model, /skill:name)."""


@dataclass
class ReplyHandle:
    chat_id: int
    main_message_id: int | None = None
    extra_message_ids: list[int] = field(default_factory=list)
    last_text: str = ""
    last_update: float = 0.0


class PilotApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.main_user_id: int | None = None
        self.main_chat_id: int | None = None
        self.pi = PiRPC(cfg.pi_command, cfg.pi_args, cfg.workdir, self.on_pi_event)
        self.app: Application | None = None
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.busy = False
        self.current_reply: ReplyHandle | None = None
        self.current_text = ""
        self.current_thinking = ""
        self.current_status = ""
        self.behavior_prompt = cfg.behavior_prompt
        self.inject_behavior_next = True
        self.sessions: dict[int, str] = {}
        self.active_session_no: int | None = None
        self.pending_ui: dict[str, Any] | None = None

    async def run(self) -> None:
        await self.pi.start()
        await self._remember_current_session()
        self.app = ApplicationBuilder().token(self.cfg.telegram_bot_token).build()
        self.app.add_handler(MessageHandler(filters.ALL, self.on_update))
        asyncio.create_task(self.worker())
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()  # type: ignore[union-attr]
        log.info("pi.lot started; waiting for first Telegram user")
        await asyncio.Event().wait()

    async def on_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if self.main_user_id is None:
            self.main_user_id = user_id
            self.main_chat_id = chat_id
            await context.bot.send_message(chat_id, "pi.lot started. You are now the authorized user.")
        elif user_id != self.main_user_id:
            await context.bot.send_message(chat_id, "This pi.lot instance is already bound to another user.")
            return

        text = update.effective_message.text if update.effective_message else None
        if not text:
            await context.bot.send_message(chat_id, "Only text messages are supported in version 1.")
            return

        if self.pending_ui:
            await self._answer_pending_ui(text, context)
            return

        if text.startswith("/") and await self._handle_pilot_command(text, context):
            return

        await self.queue.put(text)
        if self.busy:
            await context.bot.send_message(chat_id, f"Queued ({self.queue.qsize()} pending).")

    async def _handle_pilot_command(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
        chat_id = self.main_chat_id
        if chat_id is None:
            return True
        cmd, _, arg = text.partition(" ")
        if cmd == "/help":
            await context.bot.send_message(chat_id, HELP)
        elif cmd == "/new":
            await self.pi.new_session()
            await self._remember_current_session()
            self.inject_behavior_next = True
            await context.bot.send_message(chat_id, "Started a new pi session.")
        elif cmd == "/sessions":
            await self._remember_current_session()
            lines = ["Known sessions:"]
            for no, path in sorted(self.sessions.items()):
                mark = "*" if no == self.active_session_no else " "
                lines.append(f"{mark} {no}: {path}")
            await context.bot.send_message(chat_id, "\n".join(lines))
        elif cmd == "/session":
            if not arg.strip().isdigit() or int(arg.strip()) not in self.sessions:
                await context.bot.send_message(chat_id, "Usage: /session <id>")
            else:
                no = int(arg.strip())
                await self.pi.switch_session(self.sessions[no])
                self.active_session_no = no
                self.inject_behavior_next = False
                await context.bot.send_message(chat_id, f"Switched to session {no}.")
        elif cmd == "/behavior":
            await context.bot.send_message(chat_id, self.behavior_prompt)
        elif cmd == "/behavior_change":
            if not arg:
                await context.bot.send_message(chat_id, "Usage: /behavior_change <string>")
            else:
                self.behavior_prompt = arg
                self.inject_behavior_next = True
                await context.bot.send_message(chat_id, "Behavior prompt changed. It will be applied to the next new session/first prompt.")
        elif cmd == "/stop":
            cleared = self._clear_queue()
            await self.pi.abort()
            self.current_text = "Stopped."
            self.current_thinking = ""
            self.current_status = ""
            await self.update_reply("Stopped.", force=True)
            suffix = f" Cleared {cleared} queued prompt(s)." if cleared else ""
            await context.bot.send_message(chat_id, f"Stopped.{suffix}")
        else:
            return False
        return True

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

    async def worker(self) -> None:
        while True:
            prompt = await self.queue.get()
            self.busy = True
            self.current_text = ""
            self.current_thinking = ""
            self.current_status = ""
            try:
                if self.inject_behavior_next:
                    prompt = f"{self.behavior_prompt}\n\nUser prompt:\n{prompt}"
                    self.inject_behavior_next = False
                if self.main_chat_id and self.app:
                    msg = await self.app.bot.send_message(self.main_chat_id, "Thinking…")
                    self.current_reply = ReplyHandle(self.main_chat_id, msg.message_id)
                await self.pi.prompt_and_wait(prompt, streaming_behavior="followUp")
                await self._remember_current_session()
                final = self.current_text.strip() or self.current_status.strip() or "No assistant output was returned."
                await self.update_reply(final, force=True)
            except Exception as e:
                log.exception("prompt failed")
                await self.update_reply(f"Error: {e}", force=True)
            finally:
                self.current_reply = None
                self.busy = False
                self.queue.task_done()

    async def on_pi_event(self, event: dict[str, Any]) -> None:
        typ = event.get("type")
        if typ == "message_update":
            delta = event.get("assistantMessageEvent") or {}
            dtyp = delta.get("type")
            if dtyp == "text_delta":
                self.current_text += delta.get("delta", "")
            elif dtyp == "thinking_delta":
                self.current_thinking += delta.get("delta", "")
            elif dtyp == "error":
                err = self._extract_assistant_error(delta.get("error")) or str(delta.get("reason") or "error")
                self.current_text = f"Error: {err}"
            await self.update_reply(self._compose_display())
        elif typ == "message_end":
            self._capture_message(event.get("message"))
            await self.update_reply(self._compose_display(), force=True)
        elif typ == "agent_end":
            for message in event.get("messages") or []:
                self._capture_message(message)
            await self.update_reply(self._compose_display(), force=True)
        elif typ == "agent_start":
            self.current_status = "Agent started…"
            await self.update_reply(self._compose_display(), force=True)
        elif typ == "turn_start":
            self.current_status = "Thinking…"
            await self.update_reply(self._compose_display())
        elif typ == "tool_execution_start":
            self.current_status = f"Running tool: {event.get('toolName')}…"
            await self.update_reply(self._compose_display())
        elif typ == "tool_execution_end":
            self.current_status = f"Finished tool: {event.get('toolName')}"
            await self.update_reply(self._compose_display())
        elif typ == "auto_retry_start":
            attempt = event.get("attempt")
            max_attempts = event.get("maxAttempts")
            delay_ms = event.get("delayMs") or 0
            seconds = max(1, round(float(delay_ms) / 1000))
            err = str(event.get("errorMessage") or "provider error")
            self.current_status = f"Provider error; retrying {attempt}/{max_attempts} in {seconds}s…\n{err[-1200:]}"
            await self.update_reply(self._compose_display(), force=True)
        elif typ == "auto_retry_end":
            if event.get("success") is False:
                self.current_text = f"Error: {event.get('finalError') or 'provider retry failed'}"
                self.current_status = ""
                await self.update_reply(self._compose_display(), force=True)
            else:
                self.current_status = "Retry succeeded; continuing…"
                await self.update_reply(self._compose_display(), force=True)
        elif typ == "queue_update":
            steering = len(event.get("steering") or [])
            follow_up = len(event.get("followUp") or [])
            if steering or follow_up:
                self.current_status = f"Queued in pi: {steering} steering, {follow_up} follow-up"
                await self.update_reply(self._compose_display())
        elif typ == "extension_ui_request":
            await self._handle_extension_ui_request(event)
        elif typ in {"extension_error", "compaction_end"}:
            log.info("pi event: %s", event)

    def _capture_message(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return
        text = self._extract_assistant_text(message)
        thinking = self._extract_assistant_thinking(message)
        error = self._extract_assistant_error(message)
        if thinking and not self.current_thinking:
            self.current_thinking = thinking
        if error:
            self.current_text = f"Error: {error}"
            self.current_status = ""
        elif text:
            self.current_text = text
            self.current_status = ""

    def _extract_assistant_text(self, message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        chunks: list[str] = []
        for item in message.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        return "".join(chunks).strip()

    def _extract_assistant_thinking(self, message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        chunks: list[str] = []
        for item in message.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "thinking":
                chunks.append(str(item.get("thinking") or ""))
        return "".join(chunks).strip()

    def _extract_assistant_error(self, message: Any) -> str:
        if isinstance(message, str):
            return message
        if not isinstance(message, dict):
            return ""
        return str(message.get("errorMessage") or message.get("message") or "").strip()

    def _compose_display(self) -> str:
        body = self.current_text.strip()
        if not body:
            body = "Thinking…"
            if self.current_thinking:
                body += "\n\n" + self.current_thinking[-3000:]
        if self.current_status and self.current_status.strip() != body.strip():
            body += "\n\n" + self.current_status
        return body

    async def update_reply(self, text: str, force: bool = False) -> None:
        if not self.current_reply or not self.app:
            return
        now = asyncio.get_running_loop().time()
        if not force and now - self.current_reply.last_update < 1.0:
            return
        if text == self.current_reply.last_text and not force:
            return
        self.current_reply.last_text = text
        self.current_reply.last_update = now
        markdown = self.cfg.telegram_parse_mode.lower() == "markdownv2"
        parts = format_for_telegram(text, markdown_v2=markdown)
        parse_mode = ParseMode.MARKDOWN_V2 if markdown else None
        bot = self.app.bot
        try:
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
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after))
        except (BadRequest, TimedOut) as e:
            log.warning("telegram update failed: %s", e)

    async def _remember_current_session(self) -> None:
        try:
            state = await self.pi.get_state()
        except Exception:
            return
        path = state.get("sessionFile")
        if not path:
            return
        for no, existing in self.sessions.items():
            if existing == path:
                self.active_session_no = no
                return
        no = max(self.sessions.keys(), default=0) + 1
        self.sessions[no] = path
        self.active_session_no = no

    async def _handle_extension_ui_request(self, event: dict[str, Any]) -> None:
        if not self.main_chat_id or not self.app:
            return
        method = event.get("method")
        if method in {"notify", "setStatus", "setWidget", "setTitle", "set_editor_text"}:
            msg = event.get("message") or event.get("title") or event.get("statusText")
            if msg:
                await self.app.bot.send_message(self.main_chat_id, str(msg))
            return
        self.pending_ui = event
        if method == "select":
            opts = event.get("options") or []
            body = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts))
            prompt = f"{event.get('title', 'Select an option')}:\n{body}"
        elif method == "confirm":
            prompt = f"{event.get('title', 'Confirm')}\n{event.get('message', '')}\nReply yes or no."
        else:
            prompt = event.get("title") or f"pi requests {method} input"
        await self.app.bot.send_message(self.main_chat_id, prompt)

    async def _answer_pending_ui(self, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        event = self.pending_ui or {}
        self.pending_ui = None
        method = event.get("method")
        data: dict[str, Any] = {"id": event.get("id")}
        if text.strip().lower() in {"/cancel", "cancel"}:
            data["cancelled"] = True
        elif method == "confirm":
            data["confirmed"] = text.strip().lower() in {"y", "yes", "true", "1", "ok"}
        elif method == "select":
            opts = event.get("options") or []
            value = text.strip()
            if value.isdigit() and 1 <= int(value) <= len(opts):
                value = opts[int(value) - 1]
            data["value"] = value
        else:
            data["value"] = text
        await self.pi.extension_ui_response(data)
        await context.bot.send_message(self.main_chat_id, "Sent response to pi.")


def main() -> None:
    cfg = load_config()
    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(PilotApp(cfg).run())


if __name__ == "__main__":
    main()
