# pi.lot

Version 1 of the AI assistant pi.lot, basically a Telegram bridge for the pi coding agent using `pi --mode rpc`.

![img](pi.lot_icon.png)

## Features

- Python Telegram bot with long polling
- Starts and controls a `pi --mode rpc` subprocess over JSONL stdin/stdout
- First Telegram user becomes the only authorized user and is persisted in `/workspace/data/config.json`
- FIFO prompt queue while pi is busy
- Thinking/final Telegram message updates
- In-memory pi.lot commands: `/help`, `/new`, `/sessions`, `/session <id>`, `/behavior`, `/behavior_change <text>`
- Unknown slash commands are forwarded to pi
- Cronjob skill for scheduled prompts backed by Linux cron and `/workspace/data/cronjobs.json`

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and provider API key env vars
python -m pilot
```

## Docker

```bash
docker build -t pi-lot .
docker run --env-file .env -v "$PWD/workspace:/workspace" pi-lot
```

Or use the deployment script, which pulls/clones the repo, backs up `workspace`, rebuilds the image, replaces the old container, and starts the new one:

```bash
cp .env.example .env
# edit .env
./deploy.sh
```

The Docker image installs bash, cron, ssh client/server tooling, Node/npm, and the latest `@earendil-works/pi-coding-agent` package during build. It also includes a small pi `models.json` provider-header override for `kimi-coding` to avoid Kimi's misleading 429 "engine overloaded" response to the default Anthropic SDK User-Agent.

## Cronjobs

Ask pi naturally to create/list/edit/delete/run cronjobs. The cronjobs skill converts natural-language schedules to cron syntax and uses:

```bash
cd /root/.agents/skills/cronjobs && python scripts/cron_cli.py list
```

Cronjobs are stored in `/workspace/data/cronjobs.json`; Linux crontab is regenerated from that file on startup and after changes. The cronjob implementation is self-contained in `pilot/skills/cronjobs/`; pi.lot only watches the generic `/workspace/data/prompt_inbox` for prompts to execute.

## Skills

pi.lot includes self-contained skills in `pilot/skills/`. Each skill is standalone and can be invoked by pi when relevant.

- **youtube-summarizer**: Fetches YouTube transcripts for agent-side summarization.
- **memory**: Persists and retrieves assistant memories in markdown files under `/workspace/memory`.
- **gmail-access**: Searches and reads Gmail via IMAP using an app password.
- **cronjobs**: Scheduled natural-language prompts backed by Linux cron and `/workspace/data/cronjobs.json`.
- **brave-search**: Web and news search via the Brave Search API.
- **home-assistant**: Read and control Home Assistant entities, call services, and manage automations via the Home Assistant REST API.

## Environment

Required:

- `TELEGRAM_BOT_TOKEN`

Common optional values:

- `PILOT_WORKDIR` (default `/workspace`)
- `PILOT_DATA_DIR` (default `/workspace/data`; mount `/workspace` for persisted config/auth, cronjobs, and pi sessions)
- `PILOT_BEHAVIOR_PROMPT` or `PILOT_BEHAVIOR_PROMPT_PATH`
- `PI_ARGS` for non-secret pi CLI flags
- pi provider secrets such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `LOG_LEVEL`

Skill-specific optional values:

- `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD`, `GMAIL_IMAP_HOST`, `GMAIL_IMAP_PORT`
- `BRAVE_SEARCH_API_KEY`
- `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN`
