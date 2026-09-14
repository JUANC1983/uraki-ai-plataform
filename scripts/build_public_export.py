"""Build a deterministic, history-free public portfolio candidate.

The allowlist limits root files to canonical entrypoints and excludes local
audit records. It never creates a Git repository or publishes anything.
"""

import argparse
import hashlib
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "uraki-ai-platform"

PUBLIC_ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "SECURITY.md",
    "alembic.ini",
    "demo.py",
    "docker-compose.yml",
    "docker-entrypoint.sh",
    "executive.py",
    "main.py",
    "requirements.txt",
    "validate.py",
    "validate_critical.py",
}
PUBLIC_DIRECTORIES = {
    ".github",
    "agents",
    "alembic",
    "api",
    "automation",
    "config",
    "connectors",
    "core",
    "dashboard",
    "database",
    "docs",
    "memory",
    "scripts",
    "tests",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def collect_public_files() -> list[Path]:
    files = [ROOT / name for name in sorted(PUBLIC_ROOT_FILES)]
    for directory in sorted(PUBLIC_DIRECTORIES):
        base = ROOT / directory
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if "docs/audit" in relative.as_posix():
                continue
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in {".pyc", ".pyo", ".zip"}:
                continue
            files.append(path)
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Public export allowlist entries missing: {missing}")
    return sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix())


def _validated_output(path: Path) -> Path:
    output = path.resolve()
    export_root = (ROOT / "dist").resolve()
    if output == export_root:
        raise ValueError("Output must be a child of dist, not dist itself")
    try:
        output.relative_to(export_root)
    except ValueError as exc:
        raise ValueError("Public export output must stay inside repository dist") from exc
    return output


def build(output_path: Path = DEFAULT_OUTPUT) -> tuple[Path, int]:
    output = _validated_output(output_path)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    sources = collect_public_files()
    for source in sources:
        if source.is_symlink():
            raise ValueError(f"Symlinks are not allowed in public export: {source}")
        relative = source.relative_to(ROOT)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest_lines = []
    for source in sources:
        relative = source.relative_to(ROOT)
        digest = hashlib.sha256((output / relative).read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {relative.as_posix()}")
    (output / "EXPORT_MANIFEST.sha256").write_text(
        "\n".join(manifest_lines) + "\n", encoding="utf-8", newline="\n"
    )
    return output, len(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, count = build(args.output)
    print(f"PUBLIC_EXPORT_OK files={count} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
