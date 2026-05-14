---
name: memory
description: Read and save persistent assistant memories in markdown files under /workspace/memory. Use when the user asks to remember something, asks whether something is remembered, asks about previous remembered information, or when missing context may be recoverable from memory.
compatibility: Requires filesystem read/write access to /workspace/memory and Python 3.
allowed-tools: Bash(python3:*)
metadata:
  version: "1.0"
---

# Memory

Use this skill to persist and retrieve concise memories for the user.

The skill has exactly two logical tools:

1. `read-memory`
2. `save-memory`

Do not expose, document, or depend on any other memory tool.

## Storage

All memory files are stored under:

```text
/workspace/memory/
```

The skill uses two kinds of markdown files:

- `/workspace/memory/memory.md` — standard rolling memory file.
- `/workspace/memory/YYYY-MM-DD.md` — daily memory files, one file per calendar day.

Each memory is stored as exactly one markdown bullet point on exactly one line, prefixed with a timestamp in system/container local time.

Timestamp format:

```text
YYYY-MM-DDTHH:MM
```

Memory text must be as short as possible and straight to the point, without wasting characters and without omitting important information.

Example:

```markdown
- 2026-05-10T13:47 | The user has a dog named Jacky.
- 2026-05-10T13:49 | The user prefers concise answers.
```

## Tool: `save-memory`

Use `save-memory` when:

- The user explicitly asks to remember, save, store, note, or keep something for later.
- The assistant determines that newly provided information is useful durable context.
- The user corrects or clarifies durable personal/project preferences.

### Parameters

```yaml
memory:
  type: string
  required: true
  description: The concise memory text to save. Must be stored as one single-line bullet point.
date:
  type: string
  required: false
  default: current system/container local date
  description: ISO date YYYY-MM-DD for the daily memory file. Defaults to today's date in system/container local time.
```

### Behavior

1. Ensure `/workspace/memory/` exists.
2. Determine the effective date and timestamp using system/container local time.
3. Ensure the effective daily markdown file and `/workspace/memory/memory.md` exist.
4. Normalize the memory text by trimming whitespace and replacing internal newlines with spaces.
5. Store it as one bullet line: `- <YYYY-MM-DDTHH:MM> | <memory>`.
6. Avoid duplicates by comparing memory text without timestamp prefix against existing bullet entries in the effective daily file and in `/workspace/memory/memory.md`.
7. Append the bullet line to the daily file and to `/workspace/memory/memory.md`.
8. Keep `/workspace/memory/memory.md` at or below `60000` characters by removing oldest memories first before appending.
9. Never trim daily files.
10. Return a short success message including the written daily file path.

## Tool: `read-memory`

Use `read-memory` when:

- The user asks whether the assistant remembers something.
- The user asks about previous remembered facts or preferences.
- The assistant cannot complete a prompt because it may be missing remembered context.
- The assistant should double-check whether relevant information exists in memory.

### Parameters

```yaml
target:
  type: string
  required: false
  default: memory.md
  description: Which memory markdown file to read. Use `memory.md` by default, or `YYYY-MM-DD.md` for a specific day.
start_date:
  type: string
  required: false
  description: ISO date YYYY-MM-DD. Used for date ranges such as last week.
end_date:
  type: string
  required: false
  description: ISO date YYYY-MM-DD. Used with start_date for inclusive date ranges.
```

### Behavior

1. By default, read `/workspace/memory/memory.md`.
2. If the user asks about memories for a specific date, read `/workspace/memory/YYYY-MM-DD.md` for that date.
3. If the user asks about a date range, read every existing `/workspace/memory/YYYY-MM-DD.md` file in the inclusive range and skip missing daily files.
4. Return raw relevant markdown bullet lines with file/date context where useful.
5. If the requested file does not exist, return an empty memory result rather than inventing content.

## Invocation policy

- If the user says something like "remember that...", "save this", "note that...", or "keep in mind...", call `save-memory`.
- If newly provided information appears durable and useful for future interactions, call `save-memory` unless the user clearly does not want it saved.
- If the user asks "do you remember...", "what did I tell you about...", "what was my preference...", or similar, call `read-memory` first.
- If missing context may be in memory, call `read-memory` before asking the user to repeat themselves.
- Prefer reading `memory.md` unless the user explicitly refers to a specific day or date range.

## Minimal implementation contract

From this skill directory (the directory containing `SKILL.md`):

```text
python scripts/memory_tool.py read-memory --target memory.md
python scripts/memory_tool.py read-memory --start-date 2026-05-03 --end-date 2026-05-09
python scripts/memory_tool.py save-memory --memory "The user prefers concise answers."
```

The implementation preserves the logical two-tool surface: `read-memory` and `save-memory`.
