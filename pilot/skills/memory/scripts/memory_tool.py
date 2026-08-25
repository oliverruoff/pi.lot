#!/usr/bin/env python3
"""Human-readable, lossless persistent memory storage."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_MEMORY_DIR = Path("/workspace/memory")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def memory_dir() -> Path:
    """Allow isolated tests without changing the documented storage path."""
    return Path(os.environ.get("MEMORY_DIR", DEFAULT_MEMORY_DIR))


def fail(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def validate_date(value: str) -> str:
    if not DATE_RE.fullmatch(value):
        fail(f"invalid date {value!r}; expected YYYY-MM-DD")
    try:
        date_type.fromisoformat(value)
    except ValueError:
        fail(f"invalid date {value!r}; expected a real ISO date")
    return value


def validate_slug(value: str, label: str) -> str:
    value = value.strip().lower()
    if not SLUG_RE.fullmatch(value):
        fail(f"invalid {label} {value!r}; use lowercase letters, digits, and hyphens")
    return value


def normalize_line(text: str, label: str) -> str:
    normalized = re.sub(r"\s+", " ", " ".join(text.strip().splitlines())).strip()
    if not normalized:
        fail(f"{label} must not be empty")
    return normalized


def normalize_block(text: str, label: str) -> str:
    normalized = text.strip()
    if not normalized:
        fail(f"{label} must not be empty")
    if "<!-- memory-subject:" in normalized or "<!-- /memory-subject -->" in normalized:
        fail(f"{label} must not contain reserved memory subject markers")
    return normalized


def title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def append_line(path: Path, line: str) -> None:
    existing = read_text(path)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    write_text(path, f"{existing}{separator}{line}\n")


def archive_path(day: str) -> Path:
    root = memory_dir()
    return root / "archive" / day[:4] / day[5:7] / f"{day}.md"


def relative_path(path: Path) -> str:
    return path.relative_to(memory_dir()).as_posix()


def ensure_overview() -> Path:
    path = memory_dir() / "memory.md"
    if not path.exists() or not read_text(path).strip():
        write_text(path, "# Memory\n\n## Topics\n\n## Journal\n")
    return path


def add_topic_to_overview(topic: str) -> None:
    overview = ensure_overview()
    content = read_text(overview)
    link = f"- [{title_from_slug(topic)}](topics/{topic}.md)"
    if link in content.splitlines():
        return

    marker = "## Topics\n"
    if marker not in content:
        content = f"{content.rstrip()}\n\n## Topics\n\n## Journal\n"
    position = content.index(marker) + len(marker)
    content = f"{content[:position]}\n{link}{content[position:]}"
    write_text(overview, content)


def append_journal(timestamp: str, topic: str, journal: str) -> None:
    overview = ensure_overview()
    content = read_text(overview)
    marker = "## Journal\n"
    if marker not in content:
        content = f"{content.rstrip()}\n\n## Journal\n"
    link = f"[{title_from_slug(topic)}](topics/{topic}.md)"
    line = f"- {timestamp} | {link} | {journal}"
    position = content.index(marker) + len(marker)
    content = f"{content[:position]}\n{line}{content[position:]}"
    write_text(overview, content)


def subject_bounds(content: str, subject_slug: str) -> tuple[int, int] | None:
    start_marker = f"<!-- memory-subject: {subject_slug} -->"
    end_marker = "<!-- /memory-subject -->"
    start = content.find(start_marker)
    if start < 0:
        return None
    end = content.find(end_marker, start)
    if end < 0:
        fail(f"topic file contains an unterminated subject block for {subject_slug!r}")
    return start, end + len(end_marker)


def existing_sources(block: str) -> list[str]:
    sources: list[str] = []
    for line in block.splitlines():
        match = re.fullmatch(r"- `([^`]+)`", line.strip())
        if match:
            sources.append(match.group(1))
    return sources


def update_topic(topic: str, subject: str, current: str, source: str) -> None:
    topic_path = memory_dir() / "topics" / f"{topic}.md"
    content = read_text(topic_path)
    if not content.strip():
        content = f"# {title_from_slug(topic)}\n"

    subject_slug = validate_slug(subject, "subject")
    bounds = subject_bounds(content, subject_slug)
    sources = [source]
    if bounds:
        sources = [*existing_sources(content[bounds[0] : bounds[1]]), source]
    sources = list(dict.fromkeys(sources))

    source_lines = "\n".join(f"- `{item}`" for item in sources)
    block = (
        f"<!-- memory-subject: {subject_slug} -->\n"
        f"## {title_from_slug(subject_slug)}\n\n"
        f"{current}\n\nSources:\n\n{source_lines}\n"
        f"<!-- /memory-subject -->"
    )
    if bounds:
        content = f"{content[:bounds[0]]}{block}{content[bounds[1]:]}"
    else:
        content = f"{content.rstrip()}\n\n{block}\n"
    write_text(topic_path, content if content.endswith("\n") else f"{content}\n")
    add_topic_to_overview(topic)


def save_memory(args: argparse.Namespace) -> None:
    try:
        root = memory_dir()
        root.mkdir(parents=True, exist_ok=True)
        effective_date = validate_date(args.date) if args.date else datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
        memory = normalize_line(args.memory, "memory")
        daily_file = archive_path(effective_date)
        line = f"- {timestamp} | {memory}"

        if line not in read_text(daily_file).splitlines():
            append_line(daily_file, line)

        topic = validate_slug(args.topic or "inbox", "topic")
        subject = args.subject or timestamp.replace(":", "-").lower()
        current = normalize_block(args.current or memory, "current topic text")
        journal = normalize_line(args.journal or memory, "journal")
        update_topic(topic, subject, current, relative_path(daily_file))
        append_journal(timestamp, topic, journal)
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


def target_path(target: str) -> Path:
    if target == "memory.md":
        return memory_dir() / target
    stem = target[:-3] if target.endswith(".md") else target
    validate_date(stem)
    current = archive_path(stem)
    legacy = memory_dir() / f"{stem}.md"
    return current if current.exists() or not legacy.exists() else legacy


def read_memory(args: argparse.Namespace) -> None:
    try:
        if args.topic:
            topic = validate_slug(args.topic, "topic")
            path = memory_dir() / "topics" / f"{topic}.md"
            if not print_file(path, f"topic: {topic}"):
                print("empty memory")
            return

        if args.start_date or args.end_date:
            if not (args.start_date and args.end_date):
                fail("start_date and end_date must be used together")
            found = False
            for day in date_range(args.start_date, args.end_date):
                current = archive_path(day)
                legacy = memory_dir() / f"{day}.md"
                path = current if current.exists() else legacy
                if print_file(path, day):
                    found = True
            if not found:
                print("empty memory")
            return

        path = target_path(args.target or "memory.md")
        if not print_file(path, path.name):
            print("empty memory")
    except OSError as exc:
        fail(str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read and save persistent assistant memories.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save-memory", help="archive a memory and update its topic")
    save.add_argument("--memory", required=True, help="complete single-line journal memory")
    save.add_argument("--topic", help="lowercase topic slug; defaults to inbox")
    save.add_argument("--subject", help="stable lowercase subject slug within the topic")
    save.add_argument("--current", help="current LLM-authored subject text")
    save.add_argument("--journal", help="short description for the memory.md journal")
    save.add_argument("--date", help="archive date, YYYY-MM-DD")
    save.set_defaults(func=save_memory)

    read = subparsers.add_parser("read-memory", help="read the overview, a topic, or dated memories")
    read.add_argument("--target", default="memory.md", help="memory.md or YYYY-MM-DD.md")
    read.add_argument("--topic", help="lowercase topic slug")
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
