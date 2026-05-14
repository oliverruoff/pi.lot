---
name: gmail-access
description: Search, read, and download attachments from Gmail messages using Gmail IMAP with an app password. Use when the user asks to find emails, inspect Gmail message contents, check unread mail, or save mail attachments.
compatibility: Self-contained skill. Requires Python 3, network access to Gmail IMAP, and Gmail IMAP enabled with an app password.
---

# Gmail Access

Use this skill to search and read Gmail through IMAP. It is standalone and does not depend on project code.

## Configuration

**Important:** The skill reads credentials from **environment variables first**. If a variable is not set, it falls back to an optional `.env` file in the skill directory or current working directory.

### Environment Variables (Primary)

Set these in your environment or container configuration:

```env
GMAIL_EMAIL=your.address@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
GMAIL_IMAP_HOST=imap.gmail.com
GMAIL_IMAP_PORT=993
```

Only `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` are required. Do not print or log the app password.

**Priority:** Environment variables take precedence over `.env` file values. If `GMAIL_EMAIL` is already set in your environment, the `.env` file will be ignored for that variable.

### .env File (Optional Fallback)

If environment variables are not set, create a `.env` file in this skill directory (`.env`, next to `SKILL.md`) or current working directory:

```env
GMAIL_EMAIL=your.address@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
GMAIL_IMAP_HOST=imap.gmail.com
GMAIL_IMAP_PORT=993
```

## CLI

From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/gmail_imap.py <command> ...
```

All commands print JSON.

## Search mail

```bash
python scripts/gmail_imap.py search --from alice@example.com --subject invoice --since 2026-05-01 --limit 10
```

Search options:

- `--from TEXT`
- `--to TEXT`
- `--subject TEXT`
- `--text TEXT` searches message text
- `--since YYYY-MM-DD`
- `--before YYYY-MM-DD`
- `--unread`
- `--limit N` defaults to `10`
- global `--folder FOLDER` defaults to `INBOX`

Search returns matching message UIDs plus subject, from, to, date, message id, and attachment metadata.

## Read mail

Use a UID returned by search:

```bash
python scripts/gmail_imap.py read 12345
```

Read returns subject, from, to, date, message id, plain text body, HTML body if present, and attachment metadata.

## Download attachments

```bash
python scripts/gmail_imap.py download-attachments 12345 --output-dir /tmp/gmail-attachments
```

This saves all attachments for the message UID and returns saved file paths.

## Notes

- Gmail accounts must have IMAP enabled and use a Google app password, not the normal account password.
- Prefer `search` first, then `read` or `download-attachments` with the returned UID.
- If a user asks for another mailbox, pass `--folder`, for example `--folder "[Gmail]/Sent Mail"`.
