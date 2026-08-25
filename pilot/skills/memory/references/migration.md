# Legacy Memory Migration

Use this procedure only after the user explicitly asks to migrate existing memories.

## Safety Rules

1. Do not reinterpret, summarize, or discard legacy memories during structural migration.
2. Inspect first and explain the planned changes to the user.
3. Run the applying command only after explicit confirmation.
4. Keep the generated backup. Do not delete it automatically.
5. Treat semantic topic organization as a separate, optional task after structural migration.

## Procedure

From the memory skill directory, inspect the legacy structure:

```text
python scripts/migrate_memory.py
```

The command reports legacy daily files and recognized rolling entries without changing files. Tell the user the counts and ask for confirmation to apply the migration.

After confirmation:

```text
python scripts/migrate_memory.py --apply
```

The migration:

- Copies the legacy `memory.md` and flat daily files to `/workspace/memory/backup/legacy-<timestamp>/`.
- Moves flat `YYYY-MM-DD.md` content into `archive/YYYY/MM/YYYY-MM-DD.md` without changing memory lines.
- Preserves recognized entries from the old rolling `memory.md` in the corresponding archive days, avoiding exact duplicate lines.
- Creates `topics/imported.md` with links to migrated archive files.
- Replaces the old rolling `memory.md` with the new overview and migration journal entry.
- Removes flat daily originals only after their backup and archive copies have been written.

## Verification

After applying, verify:

1. The reported backup directory exists and contains the old files.
2. Migrated daily files exist below `archive/YYYY/MM/`.
3. `topics/imported.md` links to the archive files.
4. `memory.md` links to `topics/imported.md`.
5. A sample of old memory lines is identical in backup and archive.

Report the results and backup path to the user.

## Optional Topic Organization

Do not organize imported memories semantically unless the user asks. If requested, work in small batches:

1. Read a limited set of archive files.
2. Update appropriate current topic subjects with concise, still-valid knowledge.
3. Preserve links to every source archive file.
4. Add concise journal entries to `memory.md`.
5. Never modify the archived source lines.

`topics/imported.md` may remain permanently as a complete navigation fallback.
