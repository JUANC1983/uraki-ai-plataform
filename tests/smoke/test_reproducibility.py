import re
import unittest
from pathlib import Path

from scripts.build_public_export import ROOT as EXPORT_ROOT, build, collect_public_files


ROOT = Path(__file__).resolve().parents[2]


class ReproducibilityContractTests(unittest.TestCase):
    def test_public_export_allowlist_excludes_private_and_legacy_root_modules(self):
        relative = {
            path.relative_to(EXPORT_ROOT).as_posix() for path in collect_public_files()
        }
        self.assertIn("main.py", relative)
        self.assertIn("api/routes/cases.py", relative)
        self.assertIn("tests/integration/test_synthetic_golden_path.py", relative)
        self.assertNotIn("cases.py", relative)
        self.assertNotIn("decision_repository.py", relative)
        self.assertFalse(any(path.startswith("docs/audit/") for path in relative))
        self.assertFalse(any(path.endswith((".pyc", ".zip")) for path in relative))

    def test_public_export_builds_manifest_inside_dist(self):
        output = ROOT / "dist" / "synthetic-export-test"
        try:
            built, count = build(output)
            manifest = (built / "EXPORT_MANIFEST.sha256").read_text(encoding="utf-8")
            self.assertGreater(count, 50)
            self.assertEqual(len(manifest.splitlines()), count)
            self.assertTrue((built / "main.py").is_file())
        finally:
            if output.exists():
                import shutil
                shutil.rmtree(output)

    def test_runtime_dependencies_are_exactly_pinned(self):
        active = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        unpinned = [line for line in active if "==" not in line]
        names = [re.split(r"\[|==", line, maxsplit=1)[0].lower() for line in active]
        self.assertEqual(unpinned, [])
        self.assertEqual(len(names), len(set(names)))

    def test_ci_runs_local_checks_and_live_postgres_contract(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        for expected in (
            "python-version: \"3.12\"",
            "python -m pip check",
            "python -B validate_critical.py",
            "python -B validate.py",
            "python -B -m unittest discover",
            "python -B demo.py",
            "python -B scripts/scan_public_safety.py",
            "postgres:16-alpine",
            "python -m alembic upgrade head",
            "python -B -m scripts.verify_postgres_constraints",
            "python -m alembic downgrade base",
        ):
            self.assertIn(expected, workflow)

    def test_container_and_ci_share_the_python_312_contract(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("python-version: \"3.12\"", workflow)


if __name__ == "__main__":
    unittest.main()
