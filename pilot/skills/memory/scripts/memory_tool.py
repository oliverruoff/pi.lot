#!/usr/bin/env python3
"""Minimal persistent memory tool for the memory Agent Skill."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path

MEMORY_DIR = Path("/workspace/memory")
ROLLING_FILE = MEMORY_DIR / "memory.md"
MAX_ROLLING_CHARS = 60_000
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BULLET_RE = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\s+\|\s*(.*)$")


def fail(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def validate_date(value: str) -> str:
    if not DATE_RE.match(value):
        fail(f"invalid date {value!r}; expected YYYY-MM-DD")
    try:
        date_type.fromisoformat(value)
    except ValueError:
        fail(f"invalid date {value!r}; expected a real ISO date")
    return value


def normalize_memory(text: str) -> str:
    normalized = " ".join(text.strip().splitlines())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        fail("memory must not be empty")
    return normalized


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def append_line(path: Path, line: str) -> None:
    existing = read_text(path)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    write_text(path, f"{existing}{separator}{line}\n")


def existing_memory_texts(*paths: Path) -> set[str]:
    texts: set[str] = set()
    for path in paths:
        for line in read_text(path).splitlines():
            match = BULLET_RE.match(line.strip())
            if match:
                texts.add(match.group(1).strip())
    return texts


def trim_and_append_rolling(line: str) -> None:
    line_with_newline = f"{line}\n"
    if len(line_with_newline) > MAX_ROLLING_CHARS:
        fail("single memory bullet exceeds 60000 characters; not writing")

    existing = read_text(ROLLING_FILE)
    lines = existing.splitlines()

    while True:
        candidate_lines = [*lines, line]
        candidate = "\n".join(candidate_lines) + "\n" if candidate_lines else ""
        if len(candidate) <= MAX_ROLLING_CHARS:
            write_text(ROLLING_FILE, candidate)
            return
        if not lines:
            fail("unable to keep memory.md within 60000 characters")
        lines.pop(0)


def save_memory(args: argparse.Namespace) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        ROLLING_FILE.touch(exist_ok=True)

        effective_date = validate_date(args.date) if args.date else datetime.now().strftime("%Y-%m-%d")
        daily_file = MEMORY_DIR / f"{effective_date}.md"
        daily_file.touch(exist_ok=True)

        memory = normalize_memory(args.memory)
        if memory in existing_memory_texts(daily_file, ROLLING_FILE):
            print(f"already exists: {daily_file}")
            return

        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
        line = f"- {timestamp} | {memory}"
        if len(f"{line}\n") > MAX_ROLLING_CHARS:
            fail("single memory bullet exceeds 60000 characters; not writing")

        append_line(daily_file, line)
        trim_and_append_rolling(line)
        print(f"saved: {daily_file}")
    except OSError as exc:
        fail(str(exc))


def date_range(start: str, end: str):
    current = date_type.fromisoformat(validate_date(start))
    final = date_type.fromisoformat(validate_date(end))
    if current > final:
        fail("start_date must be before or equal to end_date")
    while current <= final:
        yield current.isoformat()
        current += timedelta(days=1)


def safe_target(name: str) -> Path:
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        fail("target must be a file name such as memory.md or YYYY-MM-DD.md")
    if name != "memory.md":
        stem = name[:-3] if name.endswith(".md") else name
        validate_date(stem)
        name = f"{stem}.md"
    return MEMORY_DIR / name


def print_file(path: Path, label: str | None = None) -> bool:
    if not path.exists():
        return False
    content = read_text(path)
    if not content:
        return True
    if label:
        print(f"# {label}")
    print(content, end="" if content.endswith("\n") else "\n")
    return True


def read_memory(args: argparse.Namespace) -> None:
    try:
        if args.start_date or args.end_date:
            if not (args.start_date and args.end_date):
                fail("start_date and end_date must be used together")
            found = False
            for day in date_range(args.start_date, args.end_date):
                path = MEMORY_DIR / f"{day}.md"
                if print_file(path, day):
                    found = True
            if not found:
                print("empty memory")
            return

        target = args.target or "memory.md"
        path = safe_target(target)
        if not print_file(path, path.name):
            print("empty memory")
    except OSError as exc:
        fail(str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read and save persistent assistant memories.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save-memory", help="save one concise memory")
    save.add_argument("--memory", required=True, help="single concise memory text")
    save.add_argument("--date", help="daily file date, YYYY-MM-DD")
    save.set_defaults(func=save_memory)

    read = subparsers.add_parser("read-memory", help="read memories")
    read.add_argument("--target", default="memory.md", help="memory.md or YYYY-MM-DD.md")
    read.add_argument("--start-date", dest="start_date", help="range start date, YYYY-MM-DD")
    read.add_argument("--end-date", dest="end_date", help="range end date, YYYY-MM-DD")
    read.set_defaults(func=read_memory)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
