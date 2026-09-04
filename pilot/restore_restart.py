"""Apply deferred state reloads requested by the backup/restore skill."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import PilotApp


log = logging.getLogger(__name__)
POLL_INTERVAL = 1.0
CRON_CLI = Path("/root/.pi/agent/skills/cronjobs/scripts/cron_cli.py")


async def watch_restore_requests(pilot: PilotApp) -> None:
    """Restart pi and reload restored state after the active turn finishes."""
    request_file = Path(pilot.cfg.data_dir) / "restart_requested.json"
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        if pilot.busy or not request_file.is_file():
            continue
        try:
            request = json.loads(request_file.read_text(encoding="utf-8"))
            request_file.unlink()
            await pilot.pi.restart()
            pilot.sessions.clear()
            pilot.active_session_no = None
            pilot._load_sessions_at_startup()
            await pilot._remember_current_session()
            pilot._load_behavior()
            pilot.inject_behavior_next = True
            _sync_cronjobs()
            if pilot.main_chat_id is not None and pilot.app:
                restored = ", ".join(request.get("restored", [])) or "available components"
                await pilot.app.bot.send_message(
                    pilot.main_chat_id,
                    f"Restore applied and pi restarted. Restored: {restored}.",
                )
        except Exception as exc:
            log.exception("deferred pi restart after restore failed")
            if pilot.main_chat_id is not None and pilot.app:
                await pilot.app.bot.send_message(pilot.main_chat_id, f"Restore restart error: {exc}")


def _sync_cronjobs() -> None:
    if not CRON_CLI.is_file():
        return
    result = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(CRON_CLI), "sync"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        log.error("cron sync after restore failed: %s", result.stderr.strip())
