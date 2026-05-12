#!/usr/bin/env python3
"""Standalone Brave Search API client for web and news search.

Prints JSON to stdout so any coding agent can consume results.
Reads BRAVE_SEARCH_API_KEY from environment (preferred) or a .env file.
"""

import argparse
import json
import os
import sys
from typing import Any

try:
    import requests
except Exception as exc:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    REQUESTS_IMPORT_ERROR = str(exc)
else:
    REQUESTS_IMPORT_ERROR = ""

ROOT = os.path.dirname(os.path.dirname(__file__))

API_BASE = "https://api.search.brave.com/res/v1"


def load_env() -> None:
    """Load optional .env from skill directory or cwd; env vars take precedence."""
    for p in (os.path.join(ROOT, ".env"), ".env"):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)


def out(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def die(msg: str, code: int = 1) -> None:
    out({"ok": False, "error": msg})
    sys.exit(code)


def api_key() -> str:
    load_env()
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        die("Set BRAVE_SEARCH_API_KEY in environment or .env file.")
    return key


def headers(key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }


def search_web(query: str, count: int, offset: int, country: str | None, language: str | None, freshness: str | None) -> dict[str, Any]:
    if not requests:
        die(f"requests is required but not installed: {REQUESTS_IMPORT_ERROR}")
    key = api_key()
    params: dict[str, str | int] = {"q": query, "count": count, "offset": offset}
    if country:
        params["country"] = country
    if language:
        params["search_lang"] = language
    if freshness:
        params["freshness"] = freshness

    resp = requests.get(f"{API_BASE}/web/search", headers=headers(key), params=params, timeout=30)
    if resp.status_code != 200:
        die(f"Brave API error {resp.status_code}: {resp.text}")
    data = resp.json()
    results = []
    for r in data.get("web", {}).get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "age": r.get("age", ""),
            "extra_snippets": r.get("extra_snippets", []),
        })
    return {
        "ok": True,
        "type": "web",
        "query": query,
        "results": results,
        "total_returned": len(results),
    }


def search_news(query: str, count: int, offset: int, country: str | None, language: str | None, freshness: str | None) -> dict[str, Any]:
    if not requests:
        die(f"requests is required but not installed: {REQUESTS_IMPORT_ERROR}")
    key = api_key()
    params: dict[str, str | int] = {"q": query, "count": count, "offset": offset}
    if country:
        params["country"] = country
    if language:
        params["search_lang"] = language
    if freshness:
        params["freshness"] = freshness

    resp = requests.get(f"{API_BASE}/news/search", headers=headers(key), params=params, timeout=30)
    if resp.status_code != 200:
        die(f"Brave API error {resp.status_code}: {resp.text}")
    data = resp.json()
    results = []
    for r in data.get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", ""),
            "age": r.get("age", ""),
        })
    return {
        "ok": True,
        "type": "news",
        "query": query,
        "results": results,
        "total_returned": len(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Brave Search API client")
    parser.add_argument("command", choices=["search", "news"], help="Search type: web search or news search")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--count", "-c", type=int, default=10, help="Number of results (1-20, default 10)")
    parser.add_argument("--offset", "-o", type=int, default=0, help="Result offset (default 0)")
    parser.add_argument("--country", help="Country code, e.g. DE, US")
    parser.add_argument("--language", help="Search language code, e.g. de, en")
    parser.add_argument("--freshness", choices=["pd", "pw", "pm", "py"], help="Time filter: pd=past day, pw=past week, pm=past month, py=past year")
    args = parser.parse_args()

    if args.count < 1 or args.count > 20:
        die("--count must be between 1 and 20")
    if args.offset < 0 or args.offset > 9:
        die("--offset must be between 0 and 9")

    if args.command == "search":
        out(search_web(args.query, args.count, args.offset, args.country, args.language, args.freshness))
    elif args.command == "news":
        out(search_news(args.query, args.count, args.offset, args.country, args.language, args.freshness))
    return 0


if __name__ == "__main__":
    sys.exit(main())
