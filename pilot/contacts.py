"""Small persistent address book with single-use, 24-hour invitations."""

import json
import secrets
import time
from pathlib import Path


class Contacts:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.entries, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def invite(self, name: str) -> str:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Usage: /adduser <name> (up to 80 characters)")
        if name in self.entries:
            raise ValueError("Name already exists. Remove it with /removeuser first.")
        token = secrets.token_urlsafe(24)
        self.entries[name] = {"token": token, "expires": time.time() + 86400}
        self.save()
        return token

    def accept(self, token: str, chat_id: int) -> str:
        for name, entry in self.entries.items():
            if entry.get("token") == token and entry["expires"] > time.time():
                self.entries[name] = {"chat_id": chat_id}
                self.save()
                return name
        raise ValueError("This invitation is invalid or expired.")

    def unsubscribe(self, chat_id: int) -> None:
        self.entries = {name: entry for name, entry in self.entries.items() if entry.get("chat_id") != chat_id}
        self.save()

    def remove(self, name: str) -> None:
        if name not in self.entries:
            raise ValueError("Unknown contact.")
        del self.entries[name]
        self.save()

    def chat_id(self, name: str) -> int:
        entry = self.entries.get(name, {})
        if "chat_id" not in entry:
            raise ValueError(f"Contact is not registered: {name}")
        return entry["chat_id"]
