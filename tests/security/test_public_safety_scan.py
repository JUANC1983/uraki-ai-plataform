import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.scan_public_safety import inspect_blob, run, scan_bytes


class PublicSafetyScanTests(unittest.TestCase):
    def test_clean_example(self):
        self.assertEqual(scan_bytes(b"OPENAI_API_KEY=\nSECRET_KEY=<generated_value>", "example"), [])

    def test_token_report_never_contains_token(self):
        token = b"sk-" + b"z" * 40
        findings = scan_bytes(b"config\n" + token, "synthetic")
        self.assertEqual(findings[0]["line"], 2)
        self.assertNotIn(token.decode(), repr(findings))

    def test_archive_members_are_scanned_without_extracting(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("../.env", b"token=" + b"sk-" + b"z" * 40)
        categories = {item["category"] for item in inspect_blob(stream.getvalue(), "fixture.zip")}
        self.assertIn("provider_token", categories)
        self.assertIn("private_config_artifact", categories)

    def test_standalone_export_is_scanned_without_git_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clean.py").write_text("value = 'synthetic'\n", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "config.txt").write_text("SECRET_KEY=<generated>\n", encoding="utf-8")

            result = run(root=root)

        self.assertEqual(result["scope"], "standalone directory contents")
        self.assertEqual(result["files_scanned"], 2)
        self.assertEqual(result["findings"], [])
