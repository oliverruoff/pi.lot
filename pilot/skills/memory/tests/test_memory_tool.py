from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
MEMORY_TOOL = SKILL_DIR / "scripts" / "memory_tool.py"
MIGRATION_TOOL = SKILL_DIR / "scripts" / "migrate_memory.py"


class MemoryToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.env = {**os.environ, "MEMORY_DIR": str(self.root)}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(MEMORY_TOOL), *args],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_save_creates_archive_topic_and_journal(self) -> None:
        self.run_tool(
            "save-memory",
            "--memory",
            "The user's dog is named Jacky.",
            "--topic",
            "personal",
            "--subject",
            "dog",
            "--current",
            "The user's dog is named Jacky.",
            "--journal",
            "Saved the user's dog's name.",
            "--date",
            "2026-08-24",
        )

        archive = (self.root / "archive/2026/08/2026-08-24.md").read_text(encoding="utf-8")
        topic = (self.root / "topics/personal.md").read_text(encoding="utf-8")
        overview = (self.root / "memory.md").read_text(encoding="utf-8")
        self.assertIn("The user's dog is named Jacky.", archive)
        self.assertIn("<!-- memory-subject: dog -->", topic)
        self.assertIn("`archive/2026/08/2026-08-24.md`", topic)
        self.assertIn("[Personal](topics/personal.md)", overview)
        self.assertIn("Saved the user's dog's name.", overview)

    def test_topic_update_keeps_archive_history_and_sources(self) -> None:
        common = ["save-memory", "--topic", "personal", "--subject", "dog"]
        self.run_tool(
            *common,
            "--memory",
            "The user's dog is named Jacky.",
            "--current",
            "The user's dog is named Jacky.",
            "--date",
            "2026-08-24",
        )
        self.run_tool(
            *common,
            "--memory",
            "The user corrected the dog's name to Rocky.",
            "--current",
            "The user's dog is named Rocky.",
            "--date",
            "2026-08-25",
        )

        topic = (self.root / "topics/personal.md").read_text(encoding="utf-8")
        first_archive = (self.root / "archive/2026/08/2026-08-24.md").read_text(encoding="utf-8")
        second_archive = (self.root / "archive/2026/08/2026-08-25.md").read_text(encoding="utf-8")
        self.assertNotIn("named Jacky", topic)
        self.assertIn("named Rocky", topic)
        self.assertIn("archive/2026/08/2026-08-24.md", topic)
        self.assertIn("archive/2026/08/2026-08-25.md", topic)
        self.assertIn("named Jacky", first_archive)
        self.assertIn("corrected", second_archive)

    def test_minimal_save_uses_inbox(self) -> None:
        self.run_tool("save-memory", "--memory", "A durable fact.", "--date", "2026-08-25")
        self.assertTrue((self.root / "topics/inbox.md").exists())
        self.assertIn("A durable fact.", (self.root / "topics/inbox.md").read_text(encoding="utf-8"))

    def test_read_supports_legacy_daily_file(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "2026-08-20.md").write_text("- legacy memory\n", encoding="utf-8")
        result = self.run_tool("read-memory", "--target", "2026-08-20.md")
        self.assertIn("legacy memory", result.stdout)

    def test_migration_is_dry_run_by_default_and_lossless_when_applied(self) -> None:
        self.root.mkdir(parents=True)
        legacy_line = "- 2026-08-20T10:00 | Legacy fact.\n"
        (self.root / "2026-08-20.md").write_text(legacy_line, encoding="utf-8")
        (self.root / "memory.md").write_text(legacy_line, encoding="utf-8")

        dry_run = subprocess.run(
            [sys.executable, str(MIGRATION_TOOL)],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("dry run only", dry_run.stdout)
        self.assertTrue((self.root / "2026-08-20.md").exists())

        subprocess.run(
            [sys.executable, str(MIGRATION_TOOL), "--apply"],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        archive = (self.root / "archive/2026/08/2026-08-20.md").read_text(encoding="utf-8")
        self.assertEqual(legacy_line, archive)
        self.assertFalse((self.root / "2026-08-20.md").exists())
        self.assertEqual(1, len(list((self.root / "backup").glob("legacy-*"))))
        self.assertIn("2026-08-20", (self.root / "topics/imported.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
