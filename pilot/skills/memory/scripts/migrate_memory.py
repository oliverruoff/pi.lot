#!/usr/bin/env python3
"""Explicit, lossless migration from the legacy flat memory layout."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DATE_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
MEMORY_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2})T\d{2}:\d{2}\s+\|")
DEFAULT_MEMORY_DIR = Path("/workspace/memory")


def memory_dir() -> Path:
    return Path(os.environ.get("MEMORY_DIR", DEFAULT_MEMORY_DIR))


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def legacy_daily_files(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("????-??-??.md") if DATE_FILE_RE.fullmatch(path.name))


def destination(root: Path, source: Path) -> Path:
    match = DATE_FILE_RE.fullmatch(source.name)
    if not match:
        fail(f"not a legacy daily file: {source}")
    return root / "archive" / match.group(1) / match.group(2) / source.name


def rolling_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if MEMORY_LINE_RE.match(line)]


def inspect(root: Path) -> tuple[list[Path], list[str]]:
    daily = legacy_daily_files(root)
    rolling = rolling_lines(root / "memory.md")
    return daily, rolling


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_unique(path: Path, lines: list[str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    combined = [*existing]
    known = set(existing)
    for line in lines:
        if line not in known:
            combined.append(line)
            known.add(line)
    write(path, "\n".join(combined) + ("\n" if combined else ""))


def migrate(root: Path) -> None:
    daily, rolling = inspect(root)
    if not daily and not rolling:
        print("nothing to migrate")
        return

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = root / "backup" / f"legacy-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)

    old_overview = root / "memory.md"
    if old_overview.exists():
        shutil.copy2(old_overview, backup / "memory.md")
    for source in daily:
        shutil.copy2(source, backup / source.name)

    for source in daily:
        target = destination(root, source)
        append_unique(target, source.read_text(encoding="utf-8").splitlines())

    by_date: dict[str, list[str]] = {}
    for line in rolling:
        match = MEMORY_LINE_RE.match(line)
        if match:
            by_date.setdefault(match.group(1), []).append(line)
    for day, lines in by_date.items():
        year, month = day[:4], day[5:7]
        append_unique(root / "archive" / year / month / f"{day}.md", lines)

    archive_files = sorted((root / "archive").glob("????/??/????-??-??.md"))
    imported_lines = ["# Imported Memories", "", "Legacy memories migrated without changing their text.", ""]
    imported_lines.extend(
        f"- [{path.stem}](../{path.relative_to(root).as_posix()})" for path in archive_files
    )
    write(root / "topics" / "imported.md", "\n".join(imported_lines) + "\n")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    overview = (
        "# Memory\n\n"
        "## Topics\n\n"
        "- [Imported Memories](topics/imported.md)\n\n"
        "## Journal\n\n"
        f"- {timestamp} | [Imported Memories](topics/imported.md) | Migrated legacy memories into the archive structure.\n"
    )
    write(old_overview, overview)

    for source in daily:
        source.unlink()

    print(f"migrated daily files: {len(daily)}")
    print(f"preserved rolling entries: {len(rolling)}")
    print(f"backup: {backup}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy memories after explicit user approval.")
    parser.add_argument("--apply", action="store_true", help="perform the migration; otherwise only inspect")
    args = parser.parse_args(argv)
    root = memory_dir()
    daily, rolling = inspect(root)
    print(f"legacy daily files: {len(daily)}")
    print(f"rolling memory entries: {len(rolling)}")
    if args.apply:
        migrate(root)
    else:
        print("dry run only; use --apply after explicit user confirmation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
