from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".md", ".txt", ".env", ".sh", ".html", ".css"}
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "data/generated"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "generic bearer token": re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._-]{24,}"),
    "personal absolute path": re.compile(r"(?:/home/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"),
}


def candidate_files() -> list[Path]:
    try:
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True, stderr=subprocess.DEVNULL).splitlines()
        if tracked:
            return [ROOT / item for item in tracked]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and not any(part in EXCLUDED or "/".join(path.relative_to(ROOT).parts[:2]) in EXCLUDED for part in path.relative_to(ROOT).parts)
    ]


def main() -> None:
    findings: list[str] = []
    for path in candidate_files():
        if not path.exists() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(ROOT)
        if relative == Path("scripts/secret_scan.py"):
            continue
        if relative.name == ".env":
            findings.append(f"committed environment file: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")
    if findings:
        print("Potential repository hygiene findings:")
        print("\n".join(f"- {item}" for item in sorted(set(findings))))
        sys.exit(1)
    print("Secret and private-path scan passed for repository text files.")


if __name__ == "__main__":
    main()
