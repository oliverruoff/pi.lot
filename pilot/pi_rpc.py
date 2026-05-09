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


class PiRPC:
    def __init__(self, command: str, args: list[str], cwd: str, on_event: EventHandler):
        self.command = command
        self.args = args
        self.cwd = cwd
        self.on_event = on_event
        self.proc: Process | None = None
        self._responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._agent_done: asyncio.Event | None = None
        self._agent_started = False
        self._agent_activity = False
        self._retrying = False
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

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
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        log.info("started pi RPC: %s %s", self.command, " ".join(self.args))

    async def stop(self) -> None:
        if self.proc and self.proc.stdin and not self.proc.stdin.is_closing():
            self.proc.stdin.close()
            try:
                await self.proc.stdin.wait_closed()
            except Exception:
                pass
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()

    async def send(self, cmd: dict[str, Any], wait_response: bool = True) -> dict[str, Any] | None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("pi RPC process is not running")
        req_id = cmd.get("id") or str(uuid.uuid4())
        cmd = {**cmd, "id": req_id}
        fut: asyncio.Future[dict[str, Any]] | None = None
        if wait_response:
            fut = asyncio.get_running_loop().create_future()
            self._responses[req_id] = fut
        line = json.dumps(cmd, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()
        if fut:
            return await fut
        return None

    async def prompt_and_wait(self, message: str, streaming_behavior: str | None = None) -> None:
        self._agent_done = asyncio.Event()
        self._agent_started = False
        self._agent_activity = False
        self._retrying = False
        cmd: dict[str, Any] = {"type": "prompt", "message": message}
        if streaming_behavior:
            cmd["streamingBehavior"] = streaming_behavior
        resp = await self.send(cmd)
        if resp and not resp.get("success", False):
            self._agent_done = None
            raise RuntimeError(resp.get("error", "pi prompt failed"))

        # Normal prompts finish with agent_end. Some slash/extension commands may be
        # handled synchronously without producing an agent run; only use the state
        # fallback if pi emitted no agent/retry/message activity at all. During
        # provider retry backoff, get_state().isStreaming can be false even though
        # the accepted prompt is still owned by pi.
        idle_checks = 0
        while True:
            try:
                await asyncio.wait_for(self._agent_done.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                if not self._agent_started and not self._agent_activity and not self._retrying:
                    idle_checks += 1
                    # Give pi a few seconds to emit agent_start/message events before
                    # deciding this was a synchronously handled command. This avoids
                    # replacing Telegram output with a false "Done." for normal prompts.
                    if idle_checks < 5:
                        continue
                    try:
                        state = await self.get_state()
                        if not state.get("isStreaming", False) and not state.get("pendingMessageCount", 0):
                            break
                    except Exception:
                        pass
        self._agent_done = None

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

    async def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
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
            if msg.get("type") == "response" and msg.get("id") in self._responses:
                fut = self._responses.pop(msg["id"])
                if not fut.done():
                    fut.set_result(msg)
                continue
            typ = msg.get("type")
            if typ != "response":
                self._agent_activity = True
            if typ == "agent_start":
                self._agent_started = True
            if typ == "auto_retry_start":
                self._retrying = True
            if typ == "auto_retry_end":
                self._retrying = False
                if msg.get("success") is False and self._agent_done:
                    self._agent_done.set()
            if typ == "agent_end" and self._agent_done:
                self._agent_done.set()
            await self.on_event(msg)

    async def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            raw = await self.proc.stderr.readline()
            if not raw:
                break
            log.error("pi stderr: %s", raw.decode("utf-8", errors="replace").rstrip())
