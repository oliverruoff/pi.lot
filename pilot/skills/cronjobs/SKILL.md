---
name: cronjobs
description: Create, list, edit, delete, enable, disable, and manually run pi.lot scheduled prompt cronjobs. Use when the user asks for recurring/scheduled pi.lot tasks, reminders, reports, or cronjobs.
compatibility: Self-contained skill for pi.lot containers. Requires Python 3 and Linux crontab/cron.
---

# pi.lot Cronjobs

Use this skill for scheduled pi.lot prompts.

Cronjobs are managed through one CLI interface. From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/cron_cli.py <command> ...
```

## Important scheduling rule

The user may describe schedules in natural language. Convert the user's schedule to explicit cron syntax before calling the CLI.

Persist only one of:

- five-field cron: `minute hour day-of-month month day-of-week`
- shortcuts: `@hourly`, `@daily`, `@weekly`, `@monthly`

Do not use `@reboot`.

Schedules use the Docker host/container timezone.

Examples:

- "every day at 8" -> `0 8 * * *`
- "every weekday at 8:30" -> `30 8 * * 1-5`
- "every Monday at 9" -> `0 9 * * 1`
- "every 15 minutes" -> `*/15 * * * *`

## Commands

Create:

```bash
python scripts/cron_cli.py create --schedule "0 8 * * 1-5" --name "weekday report" --prompt "Summarize my todos and priorities for today."
```

List:

```bash
python scripts/cron_cli.py list
```

Show:

```bash
python scripts/cron_cli.py show <id>
```

Partial update only; pass only fields that should change:

```bash
python scripts/cron_cli.py update <id> --schedule "0 18 * * *"
python scripts/cron_cli.py update <id> --prompt "New prompt text"
python scripts/cron_cli.py update <id> --name "new name"
```

Enable/disable:

```bash
python scripts/cron_cli.py enable <id>
python scripts/cron_cli.py disable <id>
```

Delete:

```bash
python scripts/cron_cli.py delete <id>
```

Run now:

```bash
python scripts/cron_cli.py run <id>
```

## Behavior

When a cronjob runs, pi.lot creates a new pi session, submits the stored prompt with the normal behavior prompt, and sends all output to Telegram. Cron-created sessions appear in `/sessions` but do not become the active Telegram session unless the user switches to them manually.

After using the CLI, explain the result concisely. Include the cronjob id for created or modified jobs.
