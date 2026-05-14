---
name: brave-search
description: Search the web and news using the Brave Search API. Use when the user asks to search the internet, find current news, look up facts, or research topics online.
compatibility: Self-contained skill. Requires Python 3, internet access, and a Brave Search API key.
---

# Brave Search

Use this skill to perform web or news searches via the Brave Search API. It is standalone and does not depend on project code.

## Configuration

**Important:** The skill reads the API key from **environment variables first**. If not set, it falls back to an optional `.env` file in the skill directory or current working directory.

### Environment Variable (Primary)

Set this in your environment or container configuration:

```env
BRAVE_SEARCH_API_KEY=YOUR_BRAVE_API_KEY
```

**Priority:** Environment variables take precedence over `.env` file values.

### .env File (Optional Fallback)

If the environment variable is not set, create a `.env` file in this skill directory (`.env`, next to `SKILL.md`) or current working directory:

```env
BRAVE_SEARCH_API_KEY=YOUR_BRAVE_API_KEY
```

Get a free API key at: https://api.search.brave.com/app/

## First-time setup

This skill is standalone and has no dependency on the host project. From this skill directory (the directory containing `SKILL.md`), install local requirements if they are not already available:

```bash
python -m pip install -r requirements.txt
```

## CLI

From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/brave_search.py <command> --query "..."
```

All commands print JSON.

## Web search

```bash
python scripts/brave_search.py search --query "Python async best practices" --count 10 --language en
```

Options:

- `--query` / `-q` (required): Search query string
- `--count` / `-c`: Number of results, 1-20. Defaults to `10`.
- `--offset` / `-o`: Result offset, 0-9. Defaults to `0`.
- `--country`: Country code, e.g. `DE`, `US`.
- `--language`: Search language code, e.g. `de`, `en`.
- `--freshness`: Time filter — `pd` (past day), `pw` (past week), `pm` (past month), `py` (past year).

Returns a JSON array of results with `title`, `url`, `description`, `age`, and `extra_snippets`.

## News search

```bash
python scripts/brave_search.py news --query "AI regulation" --count 5 --freshness pw
```

Options are the same as web search. Returns a JSON array of news results with `title`, `url`, `description`, and `age`.

## Usage guidelines

- If the user asks for current news or recent events, prefer the `news` command with `--freshness pw` or `pd`.
- If the user asks to research a topic or look up facts, use the `search` command.
- Do not run Brave Search requests in parallel. Free API keys have strict rate limits, so run queries sequentially and wait briefly between multiple searches.
- Summarize results concisely. Always include source URLs when referencing information.
- Do not invent facts; only use what is returned by the API.
