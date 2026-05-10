#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("PILOT_DATA_DIR", "/workspace/data"))
CRONJOBS_FILE = DATA_DIR / "cronjobs.json"
PROMPT_INBOX_DIR = DATA_DIR / "prompt_inbox"
LOG_FILE = DATA_DIR / "pilot-cron.log"
CRON_MARK_BEGIN = "# BEGIN pi.lot cronjobs"
CRON_MARK_END = "# END pi.lot cronjobs"
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SHORTCUTS = {"@hourly", "@daily", "@weekly", "@monthly"}
SCRIPT = Path(__file__).resolve()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_INBOX_DIR.mkdir(parents=True, exist_ok=True)


def load_jobs() -> list[dict[str, Any]]:
    ensure_dirs()
    if not CRONJOBS_FILE.exists():
        return []
    data = json.loads(CRONJOBS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("cronjobs", [])


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    ensure_dirs()
    tmp = CRONJOBS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CRONJOBS_FILE)


def validate_id(job_id: str) -> None:
    if not ID_RE.match(job_id):
        raise ValueError("invalid cronjob id")


def validate_schedule(schedule: str) -> str:
    schedule = schedule.strip()
    if schedule == "@reboot":
        raise ValueError("@reboot is not supported")
    if schedule in SHORTCUTS:
        return schedule
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("schedule must be a 5-field cron expression or @hourly/@daily/@weekly/@monthly")
    allowed = re.compile(r"^[0-9*,/\-]+$")
    if not all(allowed.match(p) for p in parts):
        raise ValueError("cron fields may only contain numbers, *, commas, dashes and slashes")
    return schedule


def find_job(jobs: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
    for job in jobs:
        if job.get("id") == job_id:
            return job
    raise KeyError(f"cronjob not found: {job_id}")


def create_job(schedule: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    if not prompt.strip():
        raise ValueError("prompt is required")
    jobs = load_jobs()
    ts = now_iso()
    job = {
        "id": uuid.uuid4().hex[:8],
        "name": name or "",
        "schedule": validate_schedule(schedule),
        "timezone": "container",
        "prompt": prompt,
        "enabled": True,
        "created_at": ts,
        "updated_at": ts,
        "last_run_at": None,
        "last_status": None,
    }
    jobs.append(job)
    save_jobs(jobs)
    regenerate_crontab(jobs)
    return job


def update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    validate_id(job_id)
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    if updates.get("schedule") is not None:
        job["schedule"] = validate_schedule(str(updates["schedule"]))
    if updates.get("prompt") is not None:
        prompt = str(updates["prompt"])
        if not prompt.strip():
            raise ValueError("prompt is required")
        job["prompt"] = prompt
    if updates.get("name") is not None:
        job["name"] = str(updates["name"])
    if updates.get("enabled") is not None:
        job["enabled"] = bool(updates["enabled"])
    job["updated_at"] = now_iso()
    save_jobs(jobs)
    regenerate_crontab(jobs)
    return job


def delete_job(job_id: str) -> dict[str, Any]:
    validate_id(job_id)
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    jobs = [j for j in jobs if j.get("id") != job_id]
    save_jobs(jobs)
    regenerate_crontab(jobs)
    return job


def mark_run(job_id: str, status: str) -> None:
    jobs = load_jobs()
    try:
        job = find_job(jobs, job_id)
    except KeyError:
        return
    job["last_run_at"] = now_iso()
    job["last_status"] = status[:1000]
    job["updated_at"] = now_iso()
    save_jobs(jobs)


def run_job(job_id: str) -> Path:
    validate_id(job_id)
    job = find_job(load_jobs(), job_id)
    ensure_dirs()
    path = PROMPT_INBOX_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-cron-{job_id}.json"
    payload = {
        "source": "cronjobs-skill",
        "id": job_id,
        "title": f"Cronjob triggered: {job.get('name') or job_id}",
        "prompt": job.get("prompt") or "",
        "new_session": True,
        "restore_active_session": True,
        "status_file": str(CRONJOBS_FILE),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    mark_run(job_id, "queued")
    return path


def _existing_crontab() -> str:
    try:
        res = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("crontab command not found; install/start cron in the container")
    if res.returncode != 0:
        return ""
    return res.stdout


def regenerate_crontab(jobs: list[dict[str, Any]] | None = None) -> None:
    jobs = load_jobs() if jobs is None else jobs
    existing = _existing_crontab()
    before = existing.split(CRON_MARK_BEGIN)[0].rstrip()
    after = ""
    if CRON_MARK_END in existing:
        after = existing.split(CRON_MARK_END, 1)[1].strip()
    lines = [CRON_MARK_BEGIN]
    for job in jobs:
        if not job.get("enabled", True):
            continue
        job_id = str(job.get("id"))
        validate_id(job_id)
        schedule = validate_schedule(str(job.get("schedule", "")))
        lines.append(f"# pi.lot cronjob: {job_id} {job.get('name','')}")
        lines.append(f"{schedule} {sys.executable} {SCRIPT} run {job_id} >> {LOG_FILE} 2>&1")
    lines.append(CRON_MARK_END)
    new_text = "\n".join(x for x in [before, "\n".join(lines), after] if x).strip() + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(new_text)
        tmp = f.name
    try:
        res = subprocess.run(["crontab", tmp], check=False, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or "failed to install crontab")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def emit(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Manage pi.lot cronjobs")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--schedule", required=True); c.add_argument("--prompt", required=True); c.add_argument("--name")
    sub.add_parser("list")
    s = sub.add_parser("show"); s.add_argument("id")
    u = sub.add_parser("update"); u.add_argument("id"); u.add_argument("--schedule"); u.add_argument("--prompt"); u.add_argument("--name"); u.add_argument("--enabled", choices=["true", "false"])
    d = sub.add_parser("delete"); d.add_argument("id")
    r = sub.add_parser("run"); r.add_argument("id")
    e = sub.add_parser("enable"); e.add_argument("id")
    dis = sub.add_parser("disable"); dis.add_argument("id")
    sub.add_parser("sync")
    args = p.parse_args()
    try:
        if args.cmd == "create": emit(create_job(args.schedule, args.prompt, args.name))
        elif args.cmd == "list": emit(load_jobs())
        elif args.cmd == "show": emit(find_job(load_jobs(), args.id))
        elif args.cmd == "update":
            updates: dict[str, Any] = {"schedule": args.schedule, "prompt": args.prompt, "name": args.name}
            if args.enabled is not None: updates["enabled"] = args.enabled == "true"
            emit(update_job(args.id, **updates))
        elif args.cmd == "delete": emit(delete_job(args.id))
        elif args.cmd == "run": emit({"trigger_file": str(run_job(args.id))})
        elif args.cmd == "enable": emit(update_job(args.id, enabled=True))
        elif args.cmd == "disable": emit(update_job(args.id, enabled=False))
        elif args.cmd == "sync": regenerate_crontab(); emit({"ok": True})
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
