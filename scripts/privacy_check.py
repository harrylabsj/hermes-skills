#!/usr/bin/env python3
"""Fail a publish if local paths, private config, or personal data are present."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}

SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
}

ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}

MAC_HOME_PREFIX = "/" + "Users" + "/"


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int | None
    rule: str
    detail: str


CONTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "absolute macOS home path",
        re.compile(re.escape(MAC_HOME_PREFIX) + r"[A-Za-z0-9._-]+(?:/|$)"),
    ),
    (
        "absolute Linux home path",
        re.compile(r"/home/[A-Za-z0-9._-]+(?:/|$)"),
    ),
    (
        "absolute Windows user path",
        re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\|$)"),
    ),
    (
        "private key material",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    ),
    (
        "likely secret assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|secret[_-]?key|password)\b\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_./+=-]{16,}"
        ),
    ),
    (
        "OpenAI-style secret",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "GitHub-style token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    ),
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return True
    return b"\0" in chunk


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in paths:
        if root.is_file():
            files.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            base = Path(dirpath)
            for name in filenames:
                files.append(base / name)
    return files


def load_denylist(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            values.append(line)
    return values


def check_file(path: Path, denylist: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    if path.name in SENSITIVE_FILE_NAMES:
        findings.append(Finding(path, None, "sensitive file name", path.name))
        return findings
    if is_binary(path):
        return findings

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings
    except OSError as exc:
        findings.append(Finding(path, None, "read error", str(exc)))
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in CONTENT_RULES:
            if pattern.search(line):
                findings.append(Finding(path, line_no, rule, line.strip()))

        for match in EMAIL_RE.finditer(line):
            domain = match.group(1).lower()
            if domain not in ALLOWED_EMAIL_DOMAINS:
                findings.append(Finding(path, line_no, "email address", match.group(0)))

        for value in denylist:
            if value in line:
                findings.append(Finding(path, line_no, "custom denylist", value))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan files before publishing to block local config and personal data."
    )
    parser.add_argument("paths", nargs="*", default=["."], help="Files or folders to scan")
    parser.add_argument(
        "--denylist",
        type=Path,
        default=Path(".privacy-denylist"),
        help="Optional newline-delimited private strings to block",
    )
    args = parser.parse_args()

    roots = [Path(path).resolve() for path in args.paths]
    denylist = load_denylist(args.denylist)
    findings: list[Finding] = []

    for path in iter_files(roots):
        findings.extend(check_file(path, denylist))

    if findings:
        print("Privacy check failed. Remove or generalize these values before publishing:")
        for finding in findings:
            location = str(finding.path)
            if finding.line_no is not None:
                location = f"{location}:{finding.line_no}"
            print(f"- {location}: {finding.rule}: {finding.detail}")
        return 1

    print("Privacy check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
