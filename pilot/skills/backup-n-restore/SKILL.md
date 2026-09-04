---
name: backup-n-restore
description: Create and send a complete pi.lot backup, or safely restore an uploaded pi.lot backup archive. Use when the user asks to back up, export, restore, or recover pi.lot skills, cronjobs, behavior, memory, or sessions.
---

# pi.lot Backup and Restore

Use the deterministic script in this skill directory:

```bash
python scripts/backup_n_restore.py backup
python scripts/backup_n_restore.py restore /path/to/pi-lot-backup.tar.gz
```

For a backup, run `backup`, then send the returned `archive` path with `send_telegram_file`. The file remains in `/workspace/backups`; only the three newest backups are retained. Backups contain bundled and workspace-created skills, cronjob definitions, `BEHAVIOR.md`, memory, and pi sessions. Secrets, Telegram authorization, received files, browser state, logs, and general configuration are excluded. If Telegram cannot send it, report the retained local path.

Restore only when the user explicitly asks to restore a specific `.tar.gz`. The script rejects unsafe archives, creates a safety backup first, restores each present component while leaving missing components unchanged, and requests an automatic pi restart. Cronjobs are synchronized during restart.

After restore, report restored and skipped components. The current response may be interrupted by the restart. Never extract an archive manually or bypass validation.
