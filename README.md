<p align="center">
  <img alt="pi.lot icon" src="pi.lot_icon.png" width="128">
</p>

<h1 align="center">pi.lot</h1>

<p align="center">
  Your personal AI assistant inside Telegram.
</p>

---

**pi.lot** connects the powerful [pi Coding Agent](https://github.com/earendil-works/pi/tree/main/packages/coding-agent) to Telegram. Instead of working in a terminal, you simply chat with your bot — from anywhere, on any device. pi remains the same intelligent AI that writes code, researches, manages files, and handles complex tasks.

## Contents

- [What does pi.lot do?](#what-does-pilot-do)
- [Quick Start](#quick-start)
- [Important Settings](#important-settings)
- [Bundled Skills](#bundled-skills)
- [Adding Custom Skills](#adding-custom-skills)
- [Telegram Commands](#telegram-commands)
- [Sessions](#sessions)
- [Cronjobs — Reminders & Automation](#cronjobs)
- [Acknowledgements](#acknowledgements)

---

## What does pi.lot do?

- **Chat with pi** — Ask questions, have code written, analyze files, or research topics. All via Telegram.
- **Send & receive files** — Send files to the bot (e.g. logs, images, documents) for pi to analyze. Ask "send me the log file back" — pi can return local files via Telegram.
- **Sessions** — pi remembers the context of your conversation. You can switch between different projects or start fresh anytime.
- **Automation** — Create reminders or recurring tasks, e.g. "Every morning at 8 AM, summarize my emails".
- **Skills extend pi** — Add extra capabilities like YouTube summaries, web search, Gmail access, or smart-home control.

---

## Quick Start

> **Prerequisite:** You need a [Telegram bot token](https://core.telegram.org/bots/tutorial#obtain-your-bot-token). Message [@BotFather](https://t.me/botfather) in Telegram to create one.

### Option 1: Using `deploy.sh` (recommended)

```bash
# 1. Clone the repo
git clone https://github.com/oliverruoff/pi.lot.git
cd pi.lot

# 2. Edit environment variables
cp .env.example .env
# Open .env in an editor and fill in at least TELEGRAM_BOT_TOKEN

# 3. Start
./deploy.sh
```

The script builds the Docker image, starts the container, and makes sure your data is preserved.

### Option 2: Manual Docker

```bash
# 1. Clone repo and edit .env (see above)
git clone https://github.com/oliverruoff/pi.lot.git
cd pi.lot
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN and API keys

# 2. Build and start
docker build -t pi-lot .
docker run -d \
  --name pi-lot \
  --env-file .env \
  -v "$PWD/workspace:/workspace" \
  --restart unless-stopped \
  pi-lot
```

Your bot is now live. Message it on Telegram — you are automatically the first and only authorized user.

### Important: Persist Your Data

Make sure to mount the `/workspace` directory as a volume (see examples above). It contains:

- Your pi sessions (conversation history)
- Your personal skills
- Saved memories
- Cronjobs and received files

Without this volume, all data is lost when the container restarts.

---

## Important Settings

All settings are configured via environment variables — either in the `.env` file or passed directly at Docker startup.

### Required (nothing works without these)

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |

### Model & AI Provider (at least one required)

pi needs access to an AI model to respond. You can use any model supported by the pi Coding Agent. Check the [pi documentation](https://github.com/earendil-works/pi/tree/main/packages/coding-agent) from Earendil Works for the list of supported providers and their required environment variables.

> **Tip:** You can also set `PI_ARGS=--model <provider>/<model>` to choose a specific model. If omitted, pi picks a sensible default.

### Optional Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PILOT_BEHAVIOR_PROMPT` | *built-in default* | How should pi behave? E.g. "You are a friendly helper who answers briefly." |
| `LOG_LEVEL` | `INFO` | Log detail level (`DEBUG`, `INFO`, `WARNING`) |
| `GITHUB_PAT` | — | GitHub Personal Access Token, if pi should create pull requests or access repos |

---

## Bundled Skills

Skills are extensions that give pi additional capabilities. The following skills are included in the image by default:

| Skill | What it does | Required Settings |
|-------|-------------|-------------------|
| **memory** | Saves memories and information for you in `/workspace/memory` | None |
| **youtube-summarizer** | Summarizes YouTube videos (if captions are available) | None |
| **brave-search** | Searches the web and news | `BRAVE_SEARCH_API_KEY` |
| **gmail-access** | Reads and searches your Gmail emails | `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD` |
| **home-assistant** | Controls your smart home (devices, automations) | `HOME_ASSISTANT_TOKEN` (optional `HOME_ASSISTANT_URL`) |
| **cronjobs** | Creates scheduled tasks and reminders | None |
| **browser-control** | Controls a browser (open pages, screenshots, clicks) | None |

> **How to activate a skill:** Just ask pi — e.g. "Search the web for..." or "Read my unread emails". pi automatically detects which skill fits and uses it. If a skill needs an API key and it is missing, pi will tell you.

---

## Adding Custom Skills

There are two ways to extend pi with your own capabilities:

### 1. Let pi create the skill for you (recommended)

Simply tell pi what capability you need — e.g.:

> "Create a skill that fetches Apple's stock price for me every day."

pi handles the rest: it writes the skill files, places them in the correct directory, and activates them. The skill is saved under **`/workspace/skills`** and persists across container restarts (as long as you have mounted `/workspace` as a volume).

### 2. Create a skill manually

If you prefer to do it yourself:

1. Create a folder under **`/workspace/skills/my-skill/`**
2. Add a **`SKILL.md`** inside it. Describe what the skill does and how it works.
3. Optional: Add scripts, configuration files, or templates.
4. Restart the container or tell pi: *`/reload`* — pi will discover the new skill automatically.

**Important:** Always use `/workspace/skills`, not `/root/.pi/agent/skills`. Only `/workspace` survives a container restart.

---

## Telegram Commands

pi.lot understands a few direct commands. Just type them in the chat:

| Command | Function |
|---------|----------|
| `/new` | Starts a new conversation (new session) |
| `/sessions` | Shows all saved sessions |
| `/session <number>` | Switches to a specific session |
| `/behavior` | Shows the current behavior prompt |
| `/behavior_change <text>` | Changes how pi behaves in future sessions |
| `/stop` | Aborts the current response and clears the queue |
| `/help` | Shows this help |

All other commands (e.g. `/login`, `/model`, `/settings`, `/skill:name`) are forwarded directly to pi.

---

## Sessions

A session is a single conversation with pi. You can run multiple sessions in parallel — for example one for a Python project, one for research, and one for personal organization.

- Sessions are stored under **`/workspace/data/pi-sessions`**.
- Cronjobs automatically start their own session and report the result to you.
- Afterwards, your previously active session is restored.

---

## Cronjobs

Want pi to remind you regularly or handle recurring tasks? Just ask:

> "Create a cronjob: every weekday at 8 AM, summarize my todo list."
> "Run the weekly report now."
> "Show my cronjobs."

pi creates the task, saves it in **`/workspace/data/cronjobs.json`**, and handles execution. No manual setup needed.

---

## Acknowledgements

pi.lot is built on top of the excellent [pi Coding Agent](https://github.com/earendil-works/pi/tree/main/packages/coding-agent). A huge **thank you** to **Earendil Works** for developing this impressive AI coding harness!
