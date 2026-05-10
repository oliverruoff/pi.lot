# Memory Skill Specification

Self-contained minimal Agent Skill specification for a plugin skill named `memory`, based on the Agent Skills `SKILL.md` format from https://agentskills.io/specification.

This document is a specification only. It does not require changes to the project code.

## Agent Skill package layout

```text
memory/
├── SKILL.md
└── scripts/
    └── memory_tool.py
```

The skill directory name and the `name` frontmatter field must both be exactly `memory`.

## `SKILL.md`

```markdown
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
2. Determine the effective date and timestamp using system/container local time:
   - If `date` is provided, use that date for the daily file.
   - Otherwise use the current system/container local date.
   - Generate the timestamp as `YYYY-MM-DDTHH:MM` in system/container local time.
3. Ensure the daily markdown file exists:
   - `/workspace/memory/YYYY-MM-DD.md`
4. Ensure the standard memory file exists:
   - `/workspace/memory/memory.md`
5. Normalize the memory text:
   - Make it concise: as short as possible, straight to the point, no wasted characters, no important information omitted.
   - Trim leading/trailing whitespace.
   - Replace internal newlines with spaces.
   - Store it as one bullet line: `- <YYYY-MM-DDTHH:MM> | <memory>`.
6. Check for duplicates before writing:
   - Compare the normalized memory text without the timestamp prefix against existing bullet entries in the effective daily file and in `/workspace/memory/memory.md`.
   - If the same memory already exists in either file, do not append a duplicate.
   - Return a short "already exists" result instead.
7. Append the bullet line to the effective daily markdown file.
8. Append the same bullet line to `/workspace/memory/memory.md`, but enforce the rolling size limit:
   - Before writing, calculate whether adding the new bullet line would make `memory.md` exceed `60000` characters.
   - If it would exceed the limit, remove the oldest memories from the beginning of `memory.md` until the new bullet can be added while keeping the file at or below `60000` characters.
   - Then append the new bullet line.
9. The daily file is never trimmed by this skill.
10. Return a short success message including the written daily file path.

### Error behavior

- If the new single memory bullet itself is longer than `60000` characters, fail with an explicit error instead of writing to `memory.md`.
- If filesystem access fails, return the filesystem error clearly.

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
3. If the user asks about a date range, such as last week:
   - Resolve the date range.
   - Iteratively read every existing `/workspace/memory/YYYY-MM-DD.md` file in that inclusive range.
   - Missing daily files should be skipped, not treated as fatal errors.
4. Return the raw relevant markdown bullet lines with file/date context where useful.
5. If the requested file does not exist, return an empty memory result rather than inventing content.

## Invocation policy

The assistant should proactively use this skill as follows:

- If the user says something like "remember that...", "save this", "note that...", or "keep in mind...", call `save-memory`.
- If the assistant receives information that appears to be durable and useful for future interactions, call `save-memory` before or after answering, unless the user clearly does not want it saved.
- If the user asks "do you remember...", "what did I tell you about...", "what was my preference...", or similar, call `read-memory` first.
- If the assistant lacks context and the missing context may be in memory, call `read-memory` before asking the user to repeat themselves.
- Prefer reading `memory.md` unless the user explicitly refers to a specific day or date range.

## Minimal implementation contract

The executable implementation may be a single script, for example:

```text
scripts/memory_tool.py read-memory --target memory.md
scripts/memory_tool.py read-memory --start-date 2026-05-03 --end-date 2026-05-09
scripts/memory_tool.py save-memory --memory "The user prefers concise answers."  # writes e.g. "- 2026-05-10T13:47 | The user prefers concise answers."
```

The implementation must preserve the logical two-tool surface: `read-memory` and `save-memory`.
```

## Acceptance criteria

- Skill name is `memory`.
- Skill is self-contained and can be installed as a plugin skill.
- Skill exposes exactly two logical tools: `read-memory` and `save-memory`.
- No project application code changes are required.
- Memories are stored under `/workspace/memory/`.
- `save-memory` creates `/workspace/memory/`, today's daily file, and `memory.md` if missing.
- Every saved memory is concise and stores only important information.
- Every saved memory is timestamped in system/container local time using `YYYY-MM-DDTHH:MM`.
- Every saved memory is appended to today's daily markdown file as one bullet line, unless it is a duplicate.
- Every saved memory is also added to `memory.md` as one bullet line, unless it is a duplicate.
- Duplicate memory entries are avoided by comparing memory text without the timestamp prefix.
- `memory.md` never exceeds `60000` characters after saving.
- Oldest memories are removed from `memory.md` first when trimming is required.
- Daily files are not trimmed.
- `read-memory` defaults to `memory.md`.
- `read-memory` can read one specific daily file or an inclusive range of daily files.
