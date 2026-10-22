#!/usr/bin/env python3
"""Kompakter News-Helfer: 3 sequentielle Brave-News-Suchen, kompaktes JSON-Output."""
import json
import os
import subprocess
import sys
import time
from datetime import date

SKILL_DIR = "/root/.pi/agent/skills/brave-search"
BRAVE = os.path.join(SKILL_DIR, "scripts", "brave_search.py")

QUERIES = [
    ("de", "Deutschland Nachrichten heute", "de", "DE", "pd"),
    ("world", "World news today", "en", "US", "pd"),
    ("ai", "AI OR kuenstliche Intelligenz OR GenAI news today", "en", "US", "pd"),
]

def run_news(query: str, count: int, lang: str, country: str, freshness: str):
    cmd = [
        "python3", BRAVE, "news",
        "--query", query,
        "--count", str(count),
        "--language", lang,
        "--country", country,
        "--freshness", freshness,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Brave lieferte kein gültiges JSON") from exc
    if result.returncode != 0 or (isinstance(payload, dict) and payload.get("ok") is False):
        error = payload.get("error", "Brave-Aufruf fehlgeschlagen") if isinstance(payload, dict) else "Brave-Aufruf fehlgeschlagen"
        raise RuntimeError(error)
    if isinstance(payload, dict):
        data = payload.get("results", payload.get("data"))
    else:
        data = payload
    if not isinstance(data, list):
        raise RuntimeError("Unerwartetes Brave-Antwortformat: Ergebnisliste fehlt")
    compact = []
    for item in data:
        compact.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("description") or "")[:240],
            "age": item.get("age", ""),
        })
    return compact

def main():
    out = {"date": date.today().isoformat(), "categories": {}, "errors": {}}
    for i, (key, q, lang, country, fresh) in enumerate(QUERIES):
        if i > 0:
            time.sleep(1.1)  # Brave Free Limit: 1 req/sec
        try:
            out["categories"][key] = run_news(q, 6, lang, country, fresh)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            out["categories"][key] = []
            out["errors"][key] = str(exc)
    out["ok"] = not out["errors"]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out["errors"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
