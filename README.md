# pi.lot

Version 1 of the AI assistant pi.lot, basically a Telegram bridge for the pi coding agent using `pi --mode rpc`.

![img](pi.lot_icon.png)

## Features

- Python Telegram bot with long polling
- Starts and controls a `pi --mode rpc` subprocess over JSONL stdin/stdout
- First Telegram user becomes the only authorized user until restart
- FIFO prompt queue while pi is busy
- Thinking/final Telegram message updates
- In-memory pi.lot commands: `/help`, `/new`, `/sessions`, `/session <id>`, `/behavior`, `/behavior_change <text>`
- Unknown slash commands are forwarded to pi
- No persistence required for v1

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

The Docker image installs bash, ssh client/server tooling, Node/npm, and the latest `@earendil-works/pi-coding-agent` package during build.

## Environment

Required:

- `TELEGRAM_BOT_TOKEN`

Common optional values:

- `PILOT_WORKDIR` (default `/workspace`)
- `PILOT_BEHAVIOR_PROMPT` or `PILOT_BEHAVIOR_PROMPT_PATH`
- `PI_ARGS` for non-secret pi CLI flags
- pi provider secrets such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `LOG_LEVEL`
