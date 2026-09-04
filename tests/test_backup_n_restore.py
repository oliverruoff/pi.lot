import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "pilot/skills/backup-n-restore/scripts/backup_n_restore.py"


class BackupNRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.data = self.workspace / "data"
        self.bundled = self.root / "bundled"
        self.backups = self.workspace / "backups"
        (self.workspace / "skills/custom").mkdir(parents=True)
        (self.workspace / "skills/custom/SKILL.md").write_text("custom\n")
        (self.bundled / "memory").mkdir(parents=True)
        (self.bundled / "memory/SKILL.md").write_text("bundled\n")
        (self.workspace / "memory").mkdir()
        (self.workspace / "memory/memory.md").write_text("remembered\n")
        (self.data / "pi-sessions").mkdir(parents=True)
        (self.data / "pi-sessions/one.jsonl").write_text("session\n")
        (self.data / "cronjobs.json").write_text("[]\n")
        (self.workspace / "BEHAVIOR.md").write_text("original\n")

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, *args, check=True):
        env = {
            **os.environ,
            "PILOT_WORKSPACE_DIR": str(self.workspace),
            "PILOT_DATA_DIR": str(self.data),
            "PILOT_BACKUP_DIR": str(self.backups),
            "PILOT_BUNDLED_SKILLS_DIR": str(self.bundled),
        }
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, text=True, capture_output=True)
        if check and result.returncode:
            self.fail(result.stdout + result.stderr)
        return result, json.loads(result.stdout)

    def test_backup_restore_and_rotation(self):
        archives = []
        for _ in range(4):
            _, output = self.run_script("backup")
            archives.append(Path(output["archive"]))
        self.assertEqual(3, len(list(self.backups.glob("*.tar.gz"))))
        archive = archives[-1]
        (self.workspace / "BEHAVIOR.md").write_text("changed\n")
        _, output = self.run_script("restore", str(archive))
        self.assertIn("behavior", output["restored"])
        self.assertEqual("original\n", (self.workspace / "BEHAVIOR.md").read_text())
        self.assertTrue((self.data / "restart_requested.json").is_file())
        self.assertLessEqual(len(list(self.backups.glob("*.tar.gz"))), 3)

    def test_partial_restore_leaves_missing_components_unchanged(self):
        archive = self.root / "partial.tar.gz"
        manifest = json.dumps({"format": "pi.lot-backup", "version": 1}).encode()
        behavior = b"restored\n"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("manifest.json"); info.size = len(manifest); tar.addfile(info, io.BytesIO(manifest))
            info = tarfile.TarInfo("workspace/BEHAVIOR.md"); info.size = len(behavior); tar.addfile(info, io.BytesIO(behavior))
        _, output = self.run_script("restore", str(archive))
        self.assertEqual(["behavior"], output["restored"])
        self.assertIn("memory", output["skipped"])
        self.assertEqual("remembered\n", (self.workspace / "memory/memory.md").read_text())

    def test_rejects_path_traversal(self):
        archive = self.root / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            payload = b"bad"
            info = tarfile.TarInfo("../escape"); info.size = len(payload); tar.addfile(info, io.BytesIO(payload))
        result, output = self.run_script("restore", str(archive), check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unsafe archive path", output["error"])


if __name__ == "__main__":
    unittest.main()
