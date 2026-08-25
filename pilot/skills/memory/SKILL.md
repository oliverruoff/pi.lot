---
name: memory
description: Read and save durable user memories in a lossless, human-readable Markdown archive with current topic files. Use when the user asks to remember something, asks about previous information, or missing context may exist in memory.
compatibility: Requires filesystem read/write access to /workspace/memory and Python 3.
allowed-tools: Bash(python3:*)
metadata:
  version: "2.0"
---

# Memory

Persist complete memories without imposing a total size limit. Keep the historical archive separate from the smaller files used to navigate and understand current knowledge.

The skill has two normal operations:

1. `read-memory`
2. `save-memory`

## Storage

```text
/workspace/memory/
├── memory.md                         # Topic directory and chronological journal
├── topics/<topic>.md                 # Current knowledge grouped by topic and subject
└── archive/YYYY/MM/YYYY-MM-DD.md     # Complete append-only daily memories
```

All files are ordinary, human-readable Markdown.

### Archive

The archive is the lossless source of truth. Store every memory as one complete line:

```markdown
- 2026-08-25T14:30 | The user's dog is named Rocky, correcting the previous name Jacky.
```

Never shorten, rewrite, delete, or replace an archived memory automatically. Corrections are new archive entries. There is no archive size limit.

### Topics

Topic files contain the current understanding, not the complete history. Each topic has stable subject sections and source links:

```markdown
# Personal

<!-- memory-subject: dog -->
## Dog

The user's dog is named Rocky.

Sources:

- `archive/2026/05/2026-05-10.md`
- `archive/2026/08/2026-08-25.md`
<!-- /memory-subject -->
```

Prefer an existing topic. Create a short lowercase topic slug only when no existing topic fits. Avoid overlapping topics. Good broad topics include `personal`, `people`, `preferences`, `projects`, `decisions`, and `technical`.

Use a stable subject slug for the same fact over time. Updating a subject replaces only its current topic text and retains all source links. The archived memories remain unchanged.

### Overview

`memory.md` is allowed to grow. It contains links to every topic and a newest-first journal with date, topic, and short description. It is a navigation aid, not a duplicate archive.

## Save Memory

Use `save-memory` when:

- The user explicitly asks to remember or save something.
- New information is clearly durable and useful in future interactions.
- The user corrects durable information already held in memory.

Before saving, read `memory.md` and the relevant existing topic when needed to choose the correct topic, stable subject, and current wording. The LLM, not the script, is responsible for understanding meaning and resolving corrections.

Provide:

- `memory`: Complete historical statement for the daily archive.
- `topic`: Existing or carefully chosen lowercase topic slug.
- `subject`: Stable lowercase subject slug within that topic.
- `current`: Concise current understanding of that subject. It may contain Markdown and should incorporate still-valid prior information.
- `journal`: Short description of what was stored or changed.
- `date`: Optional archive date in `YYYY-MM-DD` format.

```text
python scripts/memory_tool.py save-memory \
  --memory "The user corrected that their dog's name is Rocky, not Jacky." \
  --topic personal \
  --subject dog \
  --current "The user's dog is named Rocky." \
  --journal "Updated the name of the user's dog."
```

If only `--memory` is supplied, the tool still preserves it safely under the `inbox` topic. Prefer the full form for useful retrieval.

## Read Memory

For general or missing context:

1. Read `memory.md`.
2. Follow the most relevant topic link and read that topic.
3. Follow archive sources when history, wording, or chronology matters.
4. Ask the user to repeat information only after checking relevant memory.

Commands:

```text
python scripts/memory_tool.py read-memory
python scripts/memory_tool.py read-memory --topic personal
python scripts/memory_tool.py read-memory --target 2026-08-25.md
python scripts/memory_tool.py read-memory --start-date 2026-08-01 --end-date 2026-08-25
```

Return only the memory content relevant to the user's request. Do not invent missing memories. Reading a legacy daily file remains supported until migration.

## Migration

Only migrate existing memories when the user explicitly asks for migration to the current structure. Before doing so, read and follow `references/migration.md`.

Never start, suggest, or perform a migration merely because an older memory structure exists.
