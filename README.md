<p align="center">
  <img alt="pi.lot icon" src="pi.lot_icon.png" width="128">
</p>

<h1 align="center">pi.lot</h1>

<p align="center">
  A Telegram bridge for the <a href="https://github.com/earendil-works/pi/tree/main/packages/coding-agent">pi coding agent</a>.
</p>

---

pi.lot runs the pi coding agent as a long-lived `pi --mode rpc` subprocess and exposes it through a private Telegram bot. Telegram is the interface; pi remains the agent runtime, session manager, model/provider layer, command system, and skill host.

The goal of this repo is a small self-contained Docker service that lets one authorized Telegram user talk to pi from anywhere, keep pi sessions persisted under a mounted workspace, and add agent-side capabilities through pi skills.

## Table of Contents

- [What pi.lot does](#what-pilot-does)
- [How it works](#how-it-works)
- [Quick Start](#quick-start)
- [Docker](#docker)
- [Telegram commands](#telegram-commands)
- [Sessions](#sessions)
- [Skills](#skills)
- [Cronjobs](#cronjobs)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)

---

## What pi.lot does

- Starts `pi --mode rpc` and talks to it over JSONL stdin/stdout.
- Runs a Python Telegram bot using long polling.
- Binds itself to the first Telegram user who messages the bot; all other users are rejected.
- Persists authorization, behavior prompt, pi sessions, cronjobs, and skill data under `/workspace` when mounted.
- Injects a configurable behavior prompt at the beginning of new sessions.
- Streams pi thinking/status/final output into Telegram by editing the active response message.
- Queues prompts while pi is busy and executes them FIFO.
- Intercepts pi.lot-specific slash commands and forwards unknown slash commands to pi, so `/login`, `/model`, `/skill:name`, prompt templates, and extension commands can still work.
- Installs a set of self-contained pi skills into the Docker image.

## How it works

```text
Telegram user
    │
    ▼
python-telegram-bot long polling
    │
    ▼
pi.lot Python app
    │  ├─ auth + config in /workspace/data
    │  ├─ FIFO prompt queue
    │  ├─ prompt inbox watcher for scheduled jobs
    │  └─ Telegram message formatting/updating
    │
    ▼
pi --mode rpc subprocess
    │
    ▼
pi sessions, providers, models, tools, slash commands, skills
```

A normal prompt flow is:

1. The authorized user sends a Telegram message.
2. pi.lot queues the prompt.
3. If this is the first prompt of a new session, pi.lot prefixes the behavior prompt.
4. pi receives the prompt through RPC.
5. pi.lot updates one Telegram response message with thinking/status updates.
6. When pi finishes, that message is replaced with the final answer.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: add TELEGRAM_BOT_TOKEN and provider API keys or pi auth config
python -m pilot
```

You also need `pi` available on `PATH`. The Docker image installs the latest `@earendil-works/pi-coding-agent` automatically.

## Docker

Build and run locally:

```bash
docker build -t pi-lot .
docker run --env-file .env -v "$PWD/workspace:/workspace" pi-lot
```

Or use the deployment script:

```bash
cp .env.example .env
# edit .env
./deploy.sh
```

`deploy.sh` updates/clones the repo, backs up `workspace`, rebuilds the image, replaces the old container, preserves timezone settings, mounts `workspace` to `/workspace`, and starts the container with a restart policy.

The Docker image includes Python, bash, cron, SSH client/server tooling, Node/npm, the latest pi package, and the bundled skills. It also writes a small pi `models.json` provider-header override for `kimi-coding` to avoid Kimi's misleading 429 response to the default Anthropic SDK User-Agent.

## Telegram commands

pi.lot handles these commands itself:

| Command | Description |
|---------|-------------|
| `/help` | Show pi.lot commands |
| `/new` | Start a new pi session |
| `/sessions` | List known sessions by numeric id |
| `/session <id>` | Switch to a known session |
| `/behavior` | Show the current behavior prompt |
| `/behavior_change <text>` | Change the behavior prompt for future new sessions |
| `/stop` | Abort the current pi run and clear queued prompts |

Unknown slash commands are forwarded to pi. Use pi commands such as `/login`, `/model`, `/settings`, `/session`, `/tree`, `/compact`, or `/skill:name` as supported by the installed pi version.

## Sessions

pi.lot uses pi's native session handling. In this container, `PI_CODING_AGENT_SESSION_DIR` defaults to:

```text
/workspace/data/pi-sessions
```

Mount `/workspace` to persist sessions and pi.lot state across container rebuilds. Cronjob-created sessions are added to the session list but do not replace the currently active Telegram session.

## Skills

Bundled skills are copied into `/root/.agents/skills` in the Docker image. Each skill is self-contained and is invoked by pi when relevant.

- **youtube-summarizer** — fetch YouTube transcripts for agent-side summarization.
- **memory** — persist and retrieve assistant memories in markdown files under `/workspace/memory`.
- **gmail-access** — search and read Gmail via IMAP using an app password.
- **cronjobs** — create, manage, and run scheduled prompts backed by Linux cron.
- **brave-search** — web and news search via the Brave Search API.
- **home-assistant** — read/control Home Assistant entities, call services, and manage automations through the REST API.

## Cronjobs

The cronjobs skill lets you ask pi naturally to create, list, edit, delete, enable/disable, or run scheduled prompts, for example:

```text
Create a cronjob every weekday at 8:00 that summarizes my todos.
List my cronjobs.
Run the weekly report cronjob now.
```

Cronjobs are stored in:

```text
/workspace/data/cronjobs.json
```

Linux crontab is generated from that file on container startup and after cronjob changes. When a scheduled job fires, the skill writes a prompt request into:

```text
/workspace/data/prompt_inbox
```

pi.lot watches that inbox, starts a fresh pi session for the scheduled prompt, sends progress/final output to Telegram, and then restores the previously active session.

Manual inspection inside the container:

```bash
cd /root/.agents/skills/cronjobs
python scripts/cron_cli.py list
python scripts/cron_cli.py sync
```

## Configuration

Required:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |

Common optional values:

| Variable | Default | Description |
|----------|---------|-------------|
| `PILOT_WORKDIR` | `/workspace` | Working directory passed to pi |
| `PILOT_DATA_DIR` | `/workspace/data` | Persistent pi.lot state directory |
| `PILOT_BEHAVIOR_PROMPT` | built-in default | Behavior prompt injected into new sessions |
| `PILOT_BEHAVIOR_PROMPT_PATH` | unset | Read behavior prompt from a file |
| `PI_COMMAND` | `pi` | pi executable |
| `PI_ARGS` | `--mode rpc` | Extra pi CLI args; `--mode rpc` is prepended when set |
| `TELEGRAM_PARSE_MODE` | `MarkdownV2` | Telegram parse mode; set differently to disable MarkdownV2 formatting |
| `LOG_LEVEL` | `INFO` | Python log level |

Provider/model configuration is handled by pi. Pass provider secrets and model choices through environment variables, for example:

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
PI_ARGS=--model anthropic/claude-sonnet-4-20250514
```

Skill-specific optional values:

| Variable | Used by |
|----------|---------|
| `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD`, `GMAIL_IMAP_HOST`, `GMAIL_IMAP_PORT` | gmail-access |
| `BRAVE_SEARCH_API_KEY` | brave-search |
| `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN` | home-assistant |
| `GITHUB_PAT` | pi/GitHub workflows |

## Repository layout

```text
pilot/                 Python Telegram bridge application
pilot/pi_rpc.py        JSON-RPC process wrapper for pi --mode rpc
pilot/config.py        environment + persisted config loading
pilot/telegram_format.py
                       Telegram-safe formatting/splitting
pilot/skills/          bundled self-contained pi skills
markdowns/             implementation/specification notes
workspace/             local persistent workspace mount target
Dockerfile             self-contained runtime image
deploy.sh              update/build/replace-container deployment script
```
