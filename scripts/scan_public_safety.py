"""Offline heuristic scan. Reports locations/categories, never matched values.

This is a credential/artifact gate, not a certification that all PII is absent.
Use --history to include every blob reachable from local refs, including ZIP members.
"""
import argparse
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})"),
}


def scan_bytes(data, location):
    findings = []
    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            findings.append({"location": location, "line": data[:match.start()].count(b"\n") + 1, "category": category})
    return findings


def inspect_blob(data, location):
    findings = scan_bytes(data, location)
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                total = 0
                for member in archive.infolist():
                    total += member.file_size
                    if total > 50_000_000:
                        findings.append({"location": location, "category": "archive_scan_limit"})
                        break
                    if not member.is_dir():
                        findings.extend(scan_bytes(archive.read(member), location + "!" + member.filename))
                        if Path(member.filename).name == ".env":
                            findings.append({"location": location + "!" + member.filename, "category": "private_config_artifact"})
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            findings.append({"location": location, "category": "unreadable_archive"})
    return findings


def git(*args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)


def _is_git_root(root):
    try:
        discovered = Path(
            git("rev-parse", "--show-toplevel", root=root).decode().strip()
        ).resolve()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return discovered == root.resolve()


def _filesystem_paths(root):
    excluded = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not any(part in excluded for part in path.relative_to(root).parts)
    }


def run(history=False, root=ROOT):
    root = root.resolve()
    findings = []
    repository_root = _is_git_root(root)
    if history and not repository_root:
        raise RuntimeError("History scan requires the scan directory to be a Git repository root")
    if repository_root:
        paths = set(
            git(
                "ls-files", "-z", "--cached", "--others", "--exclude-standard", root=root
            ).decode().split("\0")
        ) - {""}
        scope = "tracked + nonignored untracked"
    else:
        paths = _filesystem_paths(root)
        scope = "standalone directory contents"
    scanned = 0
    artifacts = []
    for name in sorted(paths):
        path = root / name
        if not path.is_file():
            continue
        scanned += 1
        findings.extend(inspect_blob(path.read_bytes(), name))
        if path.suffix in {".pyc", ".zip", ".db", ".sqlite"} or name.startswith(("logs/", "storage/")) or path.name == ".env":
            artifacts.append(name)
    history_blobs = 0
    if history:
        for row in git("rev-list", "--objects", "--all", root=root).decode().splitlines():
            oid, _, name = row.partition(" ")
            if git("cat-file", "-t", oid, root=root).strip() != b"blob":
                continue
            history_blobs += 1
            findings.extend(
                inspect_blob(
                    git("cat-file", "blob", oid, root=root),
                    "history:" + oid[:12] + ":" + name,
                )
            )
    return {"scope": scope + (" + local reachable history" if history else ""), "files_scanned": scanned, "history_blobs_scanned": history_blobs, "findings": findings, "current_artifacts": artifacts, "limitations": "Heuristic credential signatures only; manual private-data review and publication allowlist still required. Ignored runtime files excluded when Git metadata is available."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    result = run(args.history)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["findings"] or result["current_artifacts"]))
