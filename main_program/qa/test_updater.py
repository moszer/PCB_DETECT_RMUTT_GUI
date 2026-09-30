"""Real temporary Git repositories exercise update and data preservation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.updater import GitUpdater, UpdateError


class UpdaterTests(unittest.TestCase):
    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.clone = self.root / "clone"
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.seed))
        self.configure(self.seed)
        self.commit({"app.py": "version 1\n", ".gitignore": "captures/\nsettings.json\n", "Refs.json": "[]\n"})
        self.git(self.seed, "tag", "v1.0.0")
        self.git(self.seed, "push", "--tags", "origin", "main")
        self.git(self.root, "clone", str(self.remote), str(self.clone))
        self.configure(self.clone)
        self.updater = GitUpdater(self.clone)
        self.allow = patch("app.updater.ALLOWED_REMOTES", {str(self.remote)})
        self.allow.start()

    def tearDown(self):
        self.allow.stop()
        self.temp.cleanup()

    def configure(self, path):
        self.git(path, "config", "user.email", "qa@example.test")
        self.git(path, "config", "user.name", "Update QA")
        self.git(path, "config", "commit.gpgsign", "false")

    def commit(self, files):
        for name, content in files.items():
            dest = self.seed / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        self.git(self.seed, "add", ".")
        self.git(self.seed, "commit", "-m", "Update fixture")
        self.git(self.seed, "push", "origin", "main")

    def test_latest_check_does_not_mutate_worktree(self):
        info = self.updater.check()
        self.assertFalse(info.available)
        self.assertEqual(info.version, "v1.0.0")
        self.assertEqual(self.git(self.clone, "status", "--porcelain"), "")

    def test_fast_forward_preserves_local_files_and_backs_up_refs(self):
        (self.clone / "exp.pt").write_bytes(b"personal model")
        (self.clone / "settings.json").write_text('{"theme":"dark"}')
        (self.clone / "captures").mkdir()
        (self.clone / "captures" / "photo.png").write_bytes(b"capture")
        self.commit({"app.py": "version 2\n", "Refs.json": '[{"x":1}]\n'})
        info = self.updater.check()
        self.assertTrue(info.available)
        backup = self.updater.install(info)
        self.assertEqual((Path(backup) / "Refs.json").read_text(), "[]\n")
        self.assertEqual((self.clone / "exp.pt").read_bytes(), b"personal model")
        self.assertEqual((self.clone / "captures" / "photo.png").read_bytes(), b"capture")
        self.assertEqual((self.clone / "settings.json").read_text(), '{"theme":"dark"}')
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), info.target)

    def test_dirty_tracked_files_block_check_and_install(self):
        self.commit({"app.py": "version 2\n"})
        info = self.updater.check()
        (self.clone / "Refs.json").write_text("local references")
        self.assertFalse(self.updater.check().available)
        with self.assertRaises(UpdateError):
            self.updater.install(info)
        self.assertEqual((self.clone / "Refs.json").read_text(), "local references")
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), info.current)

    def test_untracked_collision_is_not_overwritten(self):
        self.commit({"exp.pt": "upstream model"})
        info = self.updater.check()
        (self.clone / "exp.pt").write_text("personal model")
        with self.assertRaises(UpdateError):
            self.updater.install(info)
        self.assertEqual((self.clone / "exp.pt").read_text(), "personal model")
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), info.current)

    def test_ignored_collision_is_not_overwritten(self):
        (self.seed / "settings.json").write_text("upstream settings")
        self.git(self.seed, "add", "-f", "settings.json")
        self.git(self.seed, "commit", "-m", "Add settings")
        self.git(self.seed, "push", "origin", "main")
        info = self.updater.check()
        (self.clone / "settings.json").write_text("user settings")
        with self.assertRaises(UpdateError):
            self.updater.install(info)
        self.assertEqual((self.clone / "settings.json").read_text(), "user settings")
        self.assertEqual(self.git(self.clone, "rev-parse", "HEAD"), info.current)

    def test_diverged_history_is_blocked(self):
        self.commit({"app.py": "upstream version\n"})
        (self.clone / "app.py").write_text("local version\n")
        self.git(self.clone, "add", "app.py")
        self.git(self.clone, "commit", "-m", "Local work")
        info = self.updater.check()
        self.assertFalse(info.available)
        self.assertIn("diverged", info.blocker)

    def test_detached_head_is_blocked(self):
        self.commit({"app.py": "v2\n"})
        self.git(self.clone, "checkout", "--detach")
        self.assertIn("main branch", self.updater.check().blocker)

    def test_changed_target_requires_new_review(self):
        self.commit({"app.py": "v2\n"})
        info = self.updater.check()
        self.commit({"app.py": "v3\n"})
        self.updater.check()
        with self.assertRaisesRegex(UpdateError, "fetched version changed"):
            self.updater.install(info)

    def test_other_remote_is_rejected(self):
        self.git(self.clone, "remote", "set-url", "origin", "https://example.test/other.git")
        with self.assertRaisesRegex(UpdateError, "official"):
            self.updater.check()

    def test_network_failure_is_reported(self):
        with patch("app.updater.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 20)):
            with self.assertRaisesRegex(UpdateError, "timed out"):
                self.updater.git("fetch", "origin")


if __name__ == "__main__":
    unittest.main()
