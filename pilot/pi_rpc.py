"""Asynchronous JSON-lines client for pi's RPC mode."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from asyncio.subprocess import PIPE, Process
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]

# StreamReader default limit is 64 KiB. RPC events (agent_end/message_end) can
# contain full assistant messages plus large tool outputs, easily exceeding it.
# If the limit is hit, readline() raises and the reader task dies.
_STDOUT_LIMIT = 16 * 1024 * 1024

# Seconds to wait for graceful process termination before kill.
_STOP_TIMEOUT = 5.0

# Default timeout for RPC commands.
_DEFAULT_CMD_TIMEOUT = 30.0

# Default timeout for prompt commands.
_PROMPT_TIMEOUT = 120.0

# How long to wait between idle checks during prompt_and_wait.
_IDLE_CHECK_INTERVAL = 1.0

# How many idle checks to perform before falling back to get_state().
_MAX_IDLE_CHECKS = 5


class PiRPC:
    def __init__(
        self,
        command: str,
        args: list[str],
        cwd: str,
        on_event: EventHandler,
    ):
        self.command = command
        self.args = args
        self.cwd = cwd
        self.on_event = on_event

        self.proc: Process | None = None
        self._responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._agent_done: asyncio.Event | None = None

        # Activity tracking flags for prompt_and_wait.
        self._agent_started = False
        self._agent_activity = False
        self._agent_finished = False
        self._retrying = False

        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._event_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        os.makedirs(self.cwd, exist_ok=True)

        executable = shutil.which(self.command) or self.command
        self.proc = await asyncio.create_subprocess_exec(
            executable,
            *self.args,
            cwd=self.cwd,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            limit=_STDOUT_LIMIT,
        )

        self._event_queue = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        self._event_task = asyncio.create_task(self._dispatch_events())

        self._reader_task.add_done_callback(self._log_task_failure)
        self._stderr_task.add_done_callback(self._log_task_failure)
        self._event_task.add_done_callback(self._log_task_failure)

        log.info("started pi RPC: %s %s", self.command, " ".join(self.args))

    async def stop(self) -> None:
        self._fail_pending(RuntimeError("pi RPC process stopped"))

        if self._agent_done:
            self._agent_done.set()

        if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
            self.proc.stdin.close()
            try:
                await self.proc.stdin.wait_closed()
            except Exception:
                pass

        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=_STOP_TIMEOUT)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

        for task in (self._reader_task, self._stderr_task, self._event_task):
            if task and not task.done():
                task.cancel()

        self._event_queue = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(
        self,
        cmd: dict[str, Any],
        wait_response: bool = True,
        timeout: float = _DEFAULT_CMD_TIMEOUT,
    ) -> dict[str, Any] | None:
        if not self._is_proc_running():
            log.warning("pi RPC process is not running; restarting")
            await self.restart()

        if not self._is_proc_running():
            raise RuntimeError("pi RPC process is not running")

        req_id = cmd.get("id") or str(uuid.uuid4())
        cmd = {**cmd, "id": req_id}

        fut: asyncio.Future[dict[str, Any]] | None = None
        if wait_response:
            fut = asyncio.get_running_loop().create_future()
            self._responses[req_id] = fut

        try:
            line = json.dumps(cmd, ensure_ascii=False) + "\n"
            self.proc.stdin.write(line.encode("utf-8"))  # type: ignore[union-attr]
            await asyncio.wait_for(self.proc.stdin.drain(), timeout=timeout)  # type: ignore[union-attr]

            if fut:
                return await asyncio.wait_for(fut, timeout=timeout)
            return None
        except Exception:
            if fut and self._responses.get(req_id) is fut:
                self._responses.pop(req_id, None)
                if not fut.done():
                    fut.cancel()
            raise

    async def prompt_and_wait(
        self,
        message: str,
        streaming_behavior: str | None = None,
    ) -> None:
        self._reset_agent_tracking()

        cmd: dict[str, Any] = {"type": "prompt", "message": message}
        if streaming_behavior:
            cmd["streamingBehavior"] = streaming_behavior

        resp = await self.send(cmd, timeout=_PROMPT_TIMEOUT)
        if resp and not resp.get("success", False):
            self._agent_done = None
            raise RuntimeError(resp.get("error", "pi prompt failed"))

        await self._wait_for_agent_done()

        failed = bool(self.proc and self.proc.returncode is not None and not self._agent_finished)
        self._agent_done = None

        if failed:
            raise RuntimeError("pi RPC process exited before finishing prompt")

    async def new_session(self) -> dict[str, Any]:
        resp = await self.send({"type": "new_session"})
        if not resp or not resp.get("success"):
            raise RuntimeError((resp or {}).get("error", "new_session failed"))
        return await self.get_state()

    async def switch_session(self, session_path: str) -> dict[str, Any]:
        resp = await self.send({"type": "switch_session", "sessionPath": session_path})
        if not resp or not resp.get("success"):
            raise RuntimeError((resp or {}).get("error", "switch_session failed"))
        return await self.get_state()

    async def get_state(self) -> dict[str, Any]:
        resp = await self.send({"type": "get_state"})
        if not resp or not resp.get("success"):
            raise RuntimeError((resp or {}).get("error", "get_state failed"))
        return resp.get("data") or {}

    async def extension_ui_response(self, data: dict[str, Any]) -> None:
        await self.send({"type": "extension_ui_response", **data}, wait_response=False)

    async def abort(self, timeout: float = 2.0) -> None:
        # Unblock pi.lot immediately. Abort is a rescue path and must never wait
        # forever for a wedged pi process to acknowledge the command.
        if self._agent_done:
            self._agent_done.set()
        await self.send({"type": "abort"}, wait_response=False, timeout=timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_proc_running(self) -> bool:
        return self.proc is not None and self.proc.stdin is not None and self.proc.returncode is None

    def _reset_agent_tracking(self) -> None:
        self._agent_done = asyncio.Event()
        self._agent_started = False
        self._agent_activity = False
        self._agent_finished = False
        self._retrying = False

    async def _wait_for_agent_done(self) -> None:
        """Wait until the agent signals completion or idle fallback triggers."""
        idle_checks = 0
        while True:
            try:
                await asyncio.wait_for(self._agent_done.wait(), timeout=_IDLE_CHECK_INTERVAL)
                break
            except asyncio.TimeoutError:
                if not self._agent_started and not self._agent_activity and not self._retrying:
                    idle_checks += 1
                    if idle_checks < _MAX_IDLE_CHECKS:
                        continue
                    try:
                        state = await self.get_state()
                        if not state.get("isStreaming", False) and not state.get("pendingMessageCount", 0):
                            break
                    except Exception:
                        pass

    def _fail_pending(self, exc: Exception) -> None:
        for fut in list(self._responses.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._responses.clear()

    def _log_task_failure(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.exception("pi RPC background task failed", exc_info=exc)
            self._fail_pending(exc)
            if self._agent_done:
                self._agent_done.set()

    # ------------------------------------------------------------------
    # I/O loops
    # ------------------------------------------------------------------

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout

        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                self._fail_pending(RuntimeError("pi RPC stdout closed"))
                if self._agent_done:
                    self._agent_done.set()
                break

            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            if not line:
                continue

            try:
                msg = json.loads(line)
            except Exception:
                log.error("non-JSON from pi stdout: %s", line)
                continue

            self._handle_stdout_message(msg)

    def _handle_stdout_message(self, msg: dict[str, Any]) -> None:
        if msg.get("type") == "response" and msg.get("id") in self._responses:
            fut = self._responses.pop(msg["id"])
            if not fut.done():
                fut.set_result(msg)
            return

        typ = msg.get("type")
        if typ != "response":
            self._agent_activity = True
        if typ == "agent_start":
            self._agent_started = True
        if typ == "auto_retry_start":
            self._retrying = True
        if typ == "auto_retry_end":
            self._retrying = False

        if self._event_queue is not None:
            self._event_queue.put_nowait(msg)

    async def _dispatch_events(self) -> None:
        assert self._event_queue is not None

        while True:
            msg = await self._event_queue.get()
            try:
                await self.on_event(msg)
            except Exception:
                log.exception("pi event handler failed")
            finally:
                typ = msg.get("type")
                if typ == "agent_end":
                    self._agent_finished = True
                    if self._agent_done:
                        self._agent_done.set()
                if typ == "auto_retry_end" and msg.get("success") is False and self._agent_done:
                    self._agent_done.set()
                self._event_queue.task_done()

    async def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr

        while True:
            raw = await self.proc.stderr.readline()
            if not raw:
                break
            log.error("pi stderr: %s", raw.decode("utf-8", errors="replace").rstrip())
