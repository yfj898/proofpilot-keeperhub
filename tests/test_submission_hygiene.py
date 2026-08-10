from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_submission_hygiene import check_tree  # noqa: E402
from create_submission_export import create_export  # noqa: E402


class SubmissionHygieneTests(unittest.TestCase):
    def test_strict_export_rejects_secret_files_without_exposing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "kh_" + "S" * 32
            (root / ".env").write_text(f"KH_API_KEY={secret}\n", encoding="utf-8")

            findings = check_tree(root, strict_export=True)

            self.assertTrue(any(item.reason == "forbidden .env file" for item in findings))
            self.assertFalse(any(secret in item.reason for item in findings))

    def test_source_tree_allows_only_ignored_private_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text(
                ".env\n.proofpilot/\nkeeperhub-backup-codes.txt\n",
                encoding="utf-8",
            )
            env = root / ".env"
            env.write_text("local-only\n", encoding="utf-8")
            env.chmod(0o600)
            journal_dir = root / ".proofpilot"
            journal_dir.mkdir(mode=0o700)
            journal = journal_dir / "operations.sqlite3"
            journal.write_bytes(b"sqlite-placeholder")
            journal.chmod(0o600)

            self.assertEqual(check_tree(root, strict_export=False), [])

    def test_secret_shaped_value_reports_only_path_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "nvapi-" + "A" * 32
            path = root / "config.txt"
            path.write_text(secret, encoding="utf-8")

            findings = check_tree(root, strict_export=True)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].path, "config.txt")
            self.assertEqual(findings[0].reason, "NVIDIA API-key-shaped value")
            self.assertNotIn(secret, findings[0].reason)

    def test_export_uses_allowlist_and_passes_strict_hygiene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            output = Path(tmp) / "export"
            (root / "src").mkdir(parents=True)
            (root / "src" / "app.py").write_text("print('safe')\n", encoding="utf-8")
            (root / "README.md").write_text("# Safe\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                ".env\n.proofpilot/\nkeeperhub-backup-codes.txt\n",
                encoding="utf-8",
            )
            env = root / ".env"
            env.write_text("local-only\n", encoding="utf-8")
            env.chmod(0o600)

            create_export(root, output)

            self.assertTrue((output / "src" / "app.py").is_file())
            self.assertTrue((output / "README.md").is_file())
            self.assertFalse((output / ".env").exists())
            self.assertEqual(check_tree(output, strict_export=True), [])


if __name__ == "__main__":
    unittest.main()
