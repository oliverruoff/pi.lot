#!/usr/bin/env python3
"""Standalone browser automation with Playwright.

Prints JSON to stdout so any coding agent can consume results.
Supports persistent sessions: cookies/localStorage are kept, and the last
visited URL is restored automatically so the agent can continue browsing.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except Exception as exc:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]
    PlaywrightTimeoutError = Exception  # type: ignore[misc,assignment]
    PLAYWRIGHT_IMPORT_ERROR = str(exc)
else:
    PLAYWRIGHT_IMPORT_ERROR = ""

DEFAULT_SESSION_DIR = os.path.join("/workspace", "data", "browser-sessions")
DEFAULT_SCREENSHOT_DIR = os.path.join("/workspace", "data", "screenshots")


def env_path(key: str, default: str) -> str:
    return os.getenv(key, default)


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def out(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def die(msg: str, code: int = 1) -> None:
    out({"ok": False, "error": msg})
    sys.exit(code)


def get_browser_args() -> list[str]:
    """Docker-friendly Chromium flags."""
    return ["--no-sandbox", "--disable-setuid-sandbox"]


class BrowserSkill:
    def __init__(
        self,
        session_dir: str,
        headless: bool = True,
        viewport: str | None = None,
        timeout: int = 30,
    ):
        if sync_playwright is None:
            die(f"playwright is required but not installed: {PLAYWRIGHT_IMPORT_ERROR}")
        self.session_dir = session_dir
        self.headless = headless
        self.timeout = timeout * 1000  # playwright uses ms
        self.viewport = self._parse_viewport(viewport)
        self.session_state_path = os.path.join(session_dir, "session_state.json")
        ensure_dir(session_dir)

    def _parse_viewport(self, v: str | None) -> dict[str, int] | None:
        if not v:
            return None
        try:
            w, h = v.lower().split("x")
            return {"width": int(w), "height": int(h)}
        except Exception:
            die(f"Invalid viewport format: {v}. Use WIDTHxHEIGHT, e.g. 1280x720")

    def _load_session_state(self) -> dict[str, Any]:
        if os.path.exists(self.session_state_path):
            try:
                with open(self.session_state_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def _save_session_state(self, url: str, storage_state: dict[str, Any]) -> None:
        try:
            data = {"url": url, "storage_state": storage_state}
            with open(self.session_state_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _run(self, action_fn, restore_url: bool = True):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=get_browser_args(),
            )
            context_opts: dict[str, Any] = {}
            if self.viewport:
                context_opts["viewport"] = self.viewport

            session_data = self._load_session_state()
            if session_data.get("storage_state"):
                context_opts["storage_state"] = session_data["storage_state"]

            context = browser.new_context(**context_opts)
            page = context.new_page()
            page.set_default_timeout(self.timeout)

            # Restore previous URL unless this is a fresh navigation
            saved_url = session_data.get("url", "")
            if restore_url and saved_url and saved_url not in ("about:blank", ""):
                try:
                    page.goto(saved_url, wait_until="domcontentloaded")
                except Exception:
                    pass  # Best-effort restore

            try:
                result = action_fn(page)
                self._save_session_state(page.url, context.storage_state())
                context.close()
                browser.close()
                return result
            except PlaywrightTimeoutError as exc:
                self._save_session_state(page.url, context.storage_state())
                context.close()
                browser.close()
                die(f"Timeout: {exc}")
            except Exception as exc:
                self._save_session_state(page.url, context.storage_state())
                context.close()
                browser.close()
                die(f"Browser error: {exc}")

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def navigate(self, url: str, wait_until: str = "load") -> dict[str, Any]:
        def action(page):
            page.goto(url, wait_until=wait_until)
            return {
                "ok": True,
                "action": "navigate",
                "url": page.url,
                "title": page.title(),
            }

        return self._run(action, restore_url=False)

    def click(self, selector: str) -> dict[str, Any]:
        def action(page):
            page.locator(selector).click()
            return {
                "ok": True,
                "action": "click",
                "selector": selector,
                "url": page.url,
            }

        return self._run(action)

    def fill(self, selector: str, text: str) -> dict[str, Any]:
        def action(page):
            page.locator(selector).fill(text)
            return {
                "ok": True,
                "action": "fill",
                "selector": selector,
                "url": page.url,
            }

        return self._run(action)

    def select(
        self,
        selector: str,
        value: str | None = None,
        label: str | None = None,
        index: int | None = None,
    ) -> dict[str, Any]:
        def action(page):
            el = page.locator(selector)
            if value is not None:
                el.select_option(value=value)
            elif label is not None:
                el.select_option(label=label)
            elif index is not None:
                el.select_option(index=index)
            else:
                die("Provide --value, --label, or --index for select")
            return {
                "ok": True,
                "action": "select",
                "selector": selector,
                "url": page.url,
            }

        return self._run(action)

    def hover(self, selector: str) -> dict[str, Any]:
        def action(page):
            page.locator(selector).hover()
            return {
                "ok": True,
                "action": "hover",
                "selector": selector,
                "url": page.url,
            }

        return self._run(action)

    def scroll(self, direction: str, amount: int | None = None) -> dict[str, Any]:
        def action(page):
            if direction == "bottom":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "top":
                page.evaluate("window.scrollTo(0, 0)")
            elif direction in ("down", "up"):
                amt = amount or 500
                sign = 1 if direction == "down" else -1
                page.evaluate(f"window.scrollBy(0, {sign * amt})")
            else:
                die(f"Unknown scroll direction: {direction}")
            return {
                "ok": True,
                "action": "scroll",
                "direction": direction,
                "url": page.url,
            }

        return self._run(action)

    def screenshot(
        self,
        selector: str | None = None,
        full_page: bool = False,
        output: str | None = None,
    ) -> dict[str, Any]:
        screenshot_dir = env_path("BROWSER_SCREENSHOT_DIR", DEFAULT_SCREENSHOT_DIR)
        ensure_dir(screenshot_dir)

        if output and os.path.isabs(output):
            path = output
        else:
            filename = output or f"screenshot_{int(time.time())}.png"
            path = os.path.join(screenshot_dir, filename)

        def action(page):
            if selector:
                page.locator(selector).screenshot(path=path)
            else:
                page.screenshot(path=path, full_page=full_page)
            return {
                "ok": True,
                "action": "screenshot",
                "path": path,
                "url": page.url,
            }

        return self._run(action)

    def evaluate(self, script: str) -> dict[str, Any]:
        def action(page):
            result = page.evaluate(script)
            return {
                "ok": True,
                "action": "evaluate",
                "result": result,
                "url": page.url,
            }

        return self._run(action)

    def wait(
        self,
        selector: str,
        state: str = "visible",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        def action(page):
            ms = (timeout or self.timeout // 1000) * 1000
            page.locator(selector).wait_for(state=state, timeout=ms)
            return {
                "ok": True,
                "action": "wait",
                "selector": selector,
                "state": state,
                "url": page.url,
            }

        return self._run(action)

    def back(self) -> dict[str, Any]:
        def action(page):
            page.go_back()
            return {
                "ok": True,
                "action": "back",
                "url": page.url,
                "title": page.title(),
            }

        return self._run(action)

    def forward(self) -> dict[str, Any]:
        def action(page):
            page.go_forward()
            return {
                "ok": True,
                "action": "forward",
                "url": page.url,
                "title": page.title(),
            }

        return self._run(action)

    def reload(self) -> dict[str, Any]:
        def action(page):
            page.reload()
            return {
                "ok": True,
                "action": "reload",
                "url": page.url,
                "title": page.title(),
            }

        return self._run(action)

    def get_text(self, selector: str | None = None) -> dict[str, Any]:
        def action(page):
            if selector:
                text = page.locator(selector).inner_text()
            else:
                text = page.inner_text("body")
            return {
                "ok": True,
                "action": "get_text",
                "text": text,
                "url": page.url,
            }

        return self._run(action)

    def get_html(self, selector: str | None = None) -> dict[str, Any]:
        def action(page):
            if selector:
                html = page.locator(selector).inner_html()
            else:
                html = page.content()
            return {
                "ok": True,
                "action": "get_html",
                "html": html,
                "url": page.url,
            }

        return self._run(action)


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser control with Playwright")
    parser.add_argument("--session", default="default", help="Session / profile name")
    parser.add_argument(
        "--headless", action="store_true", default=True, help="Run headless (default)"
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Show browser window",
    )
    parser.add_argument(
        "--viewport", default=None, help="Viewport size, e.g. 1280x720"
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="Default timeout in seconds"
    )

    sub = parser.add_subparsers(dest="command")

    # navigate
    nav = sub.add_parser("navigate", help="Open a URL")
    nav.add_argument("--url", "-u", required=True)
    nav.add_argument(
        "--wait-until",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        default="load",
    )

    # click
    clk = sub.add_parser("click", help="Click an element")
    clk.add_argument("--selector", "-s", required=True)

    # fill
    fl = sub.add_parser("fill", help="Fill an input field")
    fl.add_argument("--selector", "-s", required=True)
    fl.add_argument("--text", "-t", required=True)

    # select
    sel = sub.add_parser("select", help="Select an option")
    sel.add_argument("--selector", "-s", required=True)
    sel.add_argument("--value", "-v")
    sel.add_argument("--label", "-l")
    sel.add_argument("--index", "-i", type=int)

    # hover
    hov = sub.add_parser("hover", help="Hover over an element")
    hov.add_argument("--selector", "-s", required=True)

    # scroll
    scr = sub.add_parser("scroll", help="Scroll the page")
    scr.add_argument(
        "--direction",
        "-d",
        choices=["down", "up", "bottom", "top"],
        required=True,
    )
    scr.add_argument(
        "--amount", "-a", type=int, help="Pixels to scroll (for down/up)"
    )

    # screenshot
    sshot = sub.add_parser("screenshot", help="Take a screenshot")
    sshot.add_argument("--selector", "-s", help="Screenshot a specific element")
    sshot.add_argument("--full-page", action="store_true", help="Screenshot full page")
    sshot.add_argument("--output", "-o", help="Filename or absolute path")

    # evaluate
    ev = sub.add_parser("evaluate", help="Run JavaScript")
    ev.add_argument("--script", required=True)

    # wait
    wt = sub.add_parser("wait", help="Wait for an element")
    wt.add_argument("--selector", "-s", required=True)
    wt.add_argument(
        "--state",
        choices=["attached", "detached", "visible", "hidden"],
        default="visible",
    )
    wt.add_argument("--timeout", type=int, help="Override timeout in seconds")

    # navigation shortcuts
    sub.add_parser("back", help="Go back")
    sub.add_parser("forward", help="Go forward")
    sub.add_parser("reload", help="Reload page")

    # content
    gt = sub.add_parser("get-text", help="Get visible text")
    gt.add_argument("--selector", "-s")

    gh = sub.add_parser("get-html", help="Get HTML content")
    gh.add_argument("--selector", "-s")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    session_dir = env_path(
        "BROWSER_SESSION_DIR",
        os.path.join(DEFAULT_SESSION_DIR, args.session),
    )

    skill = BrowserSkill(
        session_dir=session_dir,
        headless=args.headless,
        viewport=args.viewport,
        timeout=args.timeout,
    )

    result = None
    if args.command == "navigate":
        result = skill.navigate(args.url, args.wait_until)
    elif args.command == "click":
        result = skill.click(args.selector)
    elif args.command == "fill":
        result = skill.fill(args.selector, args.text)
    elif args.command == "select":
        result = skill.select(args.selector, args.value, args.label, args.index)
    elif args.command == "hover":
        result = skill.hover(args.selector)
    elif args.command == "scroll":
        result = skill.scroll(args.direction, args.amount)
    elif args.command == "screenshot":
        result = skill.screenshot(args.selector, args.full_page, args.output)
    elif args.command == "evaluate":
        result = skill.evaluate(args.script)
    elif args.command == "wait":
        result = skill.wait(args.selector, args.state, args.timeout)
    elif args.command == "back":
        result = skill.back()
    elif args.command == "forward":
        result = skill.forward()
    elif args.command == "reload":
        result = skill.reload()
    elif args.command == "get-text":
        result = skill.get_text(args.selector)
    elif args.command == "get-html":
        result = skill.get_html(args.selector)

    if result:
        out(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
