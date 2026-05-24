---
name: browser-control
description: Automate browser actions using Playwright. Open websites, interact with UI elements, take screenshots, execute JavaScript, and browse with persistent sessions.
compatibility: Self-contained skill. Requires Python 3, playwright, and a Chromium browser installation.
metadata:
  author: oliverruoff
  version: "1.0"
---

# Browser Control

Use this skill to automate browser interactions via Playwright.
It is standalone and does not depend on host project code.

Supported capabilities:
- Navigate to URLs and wait for load states
- Click, fill, select, hover, and scroll
- Take screenshots (viewport, full page, or element)
- Execute JavaScript in page context
- Wait for elements to appear / disappear
- Go back, forward, reload
- Extract page text or HTML
- Persistent browser sessions (cookies, localStorage, etc.)

## Configuration

Optional environment variables:

```env
BROWSER_SESSION_DIR=/workspace/data/browser-sessions
BROWSER_SCREENSHOT_DIR=/workspace/data/screenshots
```

Sessions are stored per profile name under `BROWSER_SESSION_DIR/<session>/`.
If not set, defaults are used.

## First-time setup

From this skill directory (the directory containing `SKILL.md`):

```bash
python -m pip install -r requirements.txt
playwright install chromium
# Optional: install system dependencies if running in a minimal container
playwright install-deps chromium
```

## CLI

From this skill directory (the directory containing `SKILL.md`):

```bash
python scripts/browser_control.py <command> [options]
```

All commands print JSON.

### Global options

- `--session`: Session / profile name. Defaults to `default`.
- `--viewport`: Viewport size, e.g. `1280x720`.
- `--timeout`: Default timeout in seconds. Default: `30`.
- `--no-headless`: Show browser window (not useful in containers).

### Navigate

```bash
python scripts/browser_control.py navigate --url https://example.com --wait-until networkidle
```

Wait options: `load`, `domcontentloaded`, `networkidle`, `commit`.

### Click

```bash
python scripts/browser_control.py click --selector "#submit"
```

### Fill

```bash
python scripts/browser_control.py fill --selector "#search" --text "hello world"
```

### Select

```bash
python scripts/browser_control.py select --selector "#country" --value "de"
python scripts/browser_control.py select --selector "#country" --label "Germany"
python scripts/browser_control.py select --selector "#country" --index 0
```

### Hover

```bash
python scripts/browser_control.py hover --selector "#menu"
```

### Scroll

```bash
python scripts/browser_control.py scroll --direction down --amount 500
python scripts/browser_control.py scroll --direction bottom
python scripts/browser_control.py scroll --direction top
```

### Screenshot

```bash
python scripts/browser_control.py screenshot
python scripts/browser_control.py screenshot --full-page
python scripts/browser_control.py screenshot --selector "#hero" --output hero.png
```

### Evaluate JavaScript

```bash
python scripts/browser_control.py evaluate --script "document.title"
```

### Wait

```bash
python scripts/browser_control.py wait --selector "#results" --state visible
```

States: `attached`, `detached`, `visible`, `hidden`.

### Navigation

```bash
python scripts/browser_control.py back
python scripts/browser_control.py forward
python scripts/browser_control.py reload
```

### Get content

```bash
python scripts/browser_control.py get-text
python scripts/browser_control.py get-text --selector "#content"
python scripts/browser_control.py get-html
python scripts/browser_control.py get-html --selector "#content"
```

## Usage guidelines

- Always use persistent sessions (`--session`) when you need to stay logged in or preserve state across actions.
- Screenshots are saved to `BROWSER_SCREENSHOT_DIR` (default `/workspace/data/screenshots/`).
- Use `--wait-until networkidle` when pages load content dynamically.
- Return concise summaries. Include screenshot paths when screenshots were taken.
- Handle timeouts gracefully; if an element is not found, report the error clearly.
- In minimal Docker containers you may need to run `playwright install-deps chromium` once.
