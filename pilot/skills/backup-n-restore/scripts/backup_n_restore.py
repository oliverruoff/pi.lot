#!/usr/bin/env python3
"""Create and safely restore portable pi.lot backup archives."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = "pi.lot-backup"
VERSION = 1
KEEP_BACKUPS = 3
WORKSPACE = Path(os.getenv("PILOT_WORKSPACE_DIR", "/workspace"))
DATA_DIR = Path(os.getenv("PILOT_DATA_DIR", str(WORKSPACE / "data")))
BACKUP_DIR = Path(os.getenv("PILOT_BACKUP_DIR", str(WORKSPACE / "backups")))
BUNDLED_SKILLS_DIR = Path(os.getenv("PILOT_BUNDLED_SKILLS_DIR", "/root/.pi/agent/skills"))
RESTART_REQUEST = DATA_DIR / "restart_requested.json"

COMPONENTS: dict[str, tuple[Path, str]] = {
    "workspace_skills": (WORKSPACE / "skills", "workspace/skills"),
    "bundled_skills": (BUNDLED_SKILLS_DIR, "bundled-skills"),
    "behavior": (WORKSPACE / "BEHAVIOR.md", "workspace/BEHAVIOR.md"),
    "memory": (WORKSPACE / "memory", "workspace/memory"),
    "cronjobs": (DATA_DIR / "cronjobs.json", "workspace/data/cronjobs.json"),
    "pi_sessions": (DATA_DIR / "pi-sessions", "workspace/data/pi-sessions"),
}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def emit(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def rotate_backups() -> list[str]:
    files = sorted(BACKUP_DIR.glob("pi-lot-backup-*.tar.gz"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    removed = []
    for path in files[KEEP_BACKUPS:]:
        path.unlink()
        removed.append(str(path))
    return removed


def create_backup(reason: str = "manual") -> dict[str, Any]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    present = [name for name, (path, _) in COMPONENTS.items() if path.exists()]
    manifest = {"format": FORMAT, "version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "reason": reason, "components": present}
    stem = f"pi-lot-backup-{timestamp()}"
    target = BACKUP_DIR / f"{stem}.tar.gz"
    counter = 1
    while target.exists():
        target = BACKUP_DIR / f"{stem}-{counter}.tar.gz"
        counter += 1
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=BACKUP_DIR)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tarfile.open(tmp, "w:gz") as archive:
            encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            info.mtime = int(datetime.now().timestamp())
            archive.addfile(info, io.BytesIO(encoded))
            for name in present:
                source, arcname = COMPONENTS[name]
                archive.add(
                    source,
                    arcname=arcname,
                    recursive=True,
                    filter=lambda item: None if item.issym() or item.islnk() else item,
                )
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "archive": str(target), "components": present, "removed": rotate_backups()}


def validate_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsupported archive member: {member.name}")


def load_manifest(root: Path) -> None:
    path = root / "manifest.json"
    if not path.is_file():
        raise ValueError("archive has no manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or data.get("version") != VERSION:
        raise ValueError("unsupported pi.lot backup format or version")


def remove_path(path: Path) -> None:
    shutil.rmtree(path) if path.is_dir() else path.unlink()


def replace_component(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.parent / f".{destination.name}.restore-new"
    old = destination.parent / f".{destination.name}.restore-old"
    for path in (incoming, old):
        if path.exists():
            remove_path(path)
    shutil.copytree(source, incoming) if source.is_dir() else shutil.copy2(source, incoming)
    try:
        if destination.exists():
            destination.replace(old)
        incoming.replace(destination)
        if old.exists():
            remove_path(old)
    except Exception:
        if not destination.exists() and old.exists():
            old.replace(destination)
        raise


def request_restart(restored: list[str], safety_backup: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = RESTART_REQUEST.with_suffix(".json.tmp")
    payload = {"reason": "restore", "restored": restored, "safety_backup": safety_backup, "requested_at": datetime.now(timezone.utc).isoformat()}
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(RESTART_REQUEST)


def restore_backup(archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError(f"backup file not found: {archive_path}")
    if not archive_path.name.endswith(".tar.gz"):
        raise ValueError("backup must be a .tar.gz file")
    with tempfile.TemporaryDirectory(prefix="pilot-restore-") as temp_name:
        root = Path(temp_name)
        with tarfile.open(archive_path, "r:gz") as archive:
            validate_members(archive)
            archive.extractall(root, filter="data")
        load_manifest(root)
        safety = create_backup(reason="pre-restore")
        restored, skipped, errors = [], [], {}
        for name, (destination, relative) in COMPONENTS.items():
            source = root / relative
            if not source.exists():
                skipped.append(name)
                continue
            try:
                replace_component(source, destination)
                restored.append(name)
            except Exception as exc:
                errors[name] = str(exc)
    if not restored:
        raise RuntimeError(f"no components restored; errors={errors}")
    request_restart(restored, safety["archive"])
    return {"ok": not errors, "restored": restored, "skipped": skipped, "errors": errors, "safety_backup": safety["archive"], "restart_requested": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup")
    restore = sub.add_parser("restore")
    restore.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        emit(create_backup() if args.command == "backup" else restore_backup(args.archive))
    except Exception as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
