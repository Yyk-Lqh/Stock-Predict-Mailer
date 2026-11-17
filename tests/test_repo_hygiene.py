"""Local delivery must inspect new files without including ignored private workspaces."""
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_repo_hygiene.py"


@unittest.skipUnless(shutil.which("git"), "git required")
class LocalHygieneTests(unittest.TestCase):
    def check_repo(self, root, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, capture_output=True, text=True, check=False)

    def test_new_secret_is_rejected_but_ignored_private_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("private/\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
            (root / "private").mkdir()
            (root / "private" / "fixture.pem").write_text("ignored synthetic marker", encoding="utf-8")
            (root / "untracked.pem").write_text("synthetic marker, not a real key", encoding="utf-8")
            self.assertEqual(self.check_repo(root).returncode, 0)
            rejected = self.check_repo(root, "--include-untracked")
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("untracked.pem", rejected.stderr)
            self.assertNotIn("private/fixture.pem", rejected.stderr)
            (root / "untracked.pem").unlink()
            (root / "new.py").write_text("value = 1\n", encoding="utf-8")
            accepted = self.check_repo(root, "--include-untracked")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("2 local candidate files", accepted.stdout)

    def test_candidate_check_cannot_succeed_without_a_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.check_repo(folder, "--include-untracked")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("git is required", result.stderr)

    def test_delivery_whitespace_step_rejects_staged_errors(self):
        spec = importlib.util.spec_from_file_location("desktop_delivery_check", SCRIPT.with_name("check_desktop_delivery.py"))
        delivery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(delivery)
        commands = next(commands for name, commands in delivery.checks(False) if name == "whitespace")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "staged.txt").write_text("staged whitespace error  \n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.txt"], cwd=root, check=True)
            self.assertEqual(subprocess.run(["git", "diff", "--check"], cwd=root, capture_output=True, check=False).returncode, 0)
            results = [subprocess.run(command, cwd=root, capture_output=True, check=False).returncode for command in commands]
            self.assertTrue(any(results), "The delivery gate accepted whitespace errors already staged for commit")
