#!/usr/bin/env python3
"""High-confidence repository security regression checks.

This complements Bandit/pip-audit/CodeQL with project-specific invariants that
must remain true even when dependencies or application architecture change.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".html", ".css", ".yml", ".yaml", ".toml",
    ".ini", ".json", ".md", ".txt", ".sh", ".ps1",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Telegram bot token": re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),
}
ACTION_SHA_RE = re.compile(r"^\s*uses:\s*([^#\s]+)(?:\s*#.*)?$", re.MULTILINE)
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", re.IGNORECASE)
SHELL_TRUE_RE = re.compile(r"\bshell\s*=\s*" + "True" + r"\b")
SANDBOX_BYPASS = "--no-" + "sandbox"


def tracked_files() -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        names = [item for item in completed.stdout.decode().split("\0") if item]
        return [ROOT / name for name in names]
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return [
            path for path in ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and not any(part in {"data", "runtime", ".venv", "venv"} for part in path.parts)
        ]


def text_files() -> list[Path]:
    result = []
    for path in tracked_files():
        if path.suffix.casefold() in TEXT_SUFFIXES or path.name in {"Dockerfile", ".gitignore"}:
            result.append(path)
    return result


def scan() -> list[str]:
    failures: list[str] = []
    texts: dict[Path, str] = {}
    for path in text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        texts[path] = text
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("tests/") or path.resolve() == SELF:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{relative}: possible committed {label}")
        if path.suffix == ".py" and SHELL_TRUE_RE.search(text):
            failures.append(f"{relative}: subprocess shell=True is forbidden")

    for path, text in texts.items():
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix in {".yml", ".yaml"} and relative.startswith(".github/workflows/"):
            for match in ACTION_SHA_RE.finditer(text):
                target = match.group(1)
                if target.startswith("./"):
                    continue
                if "@" not in target:
                    failures.append(f"{relative}: GitHub Action is not pinned: {target}")
                    continue
                _action, revision = target.rsplit("@", 1)
                if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
                    failures.append(
                        f"{relative}: GitHub Action must use a full commit SHA: {target}"
                    )
        if path.suffix == ".html" and INLINE_SCRIPT_RE.search(text):
            failures.append(f"{relative}: inline script conflicts with strict CSP")

    # The provider modules and isolated-container launchers legitimately retain
    # the legacy flag as a compatibility seam. security_runtime.py is also
    # allowed to reference it because that module removes the flag for every
    # non-sidecar Chromium launch; its enforcement seam is asserted separately.
    allowed_browser_bypass_files = {
        "serienstream_shared_session.py",
        "serienstream_verification.py",
        "security_runtime.py",
        "docker-compose.yml",
        ".github/workflows/quality.yml",
    }
    for path, text in texts.items():
        relative = path.relative_to(ROOT).as_posix()
        if (
            SANDBOX_BYPASS in text
            and relative not in allowed_browser_bypass_files
            and not relative.startswith("tests/")
            and path.resolve() != SELF
        ):
            failures.append(f"{relative}: Chromium sandbox bypass outside approved isolation boundary")

    runtime_text = texts.get(ROOT / "security_runtime.py", "")
    compose_text = texts.get(ROOT / "docker-compose.yml", "")
    if "ROYAL_BROWSER_CDP_URL" not in runtime_text or "_ChromiumSubprocessProxy" not in runtime_text:
        failures.append("security_runtime.py: browser isolation/native sandbox enforcement missing")
    if "royal-browser:" not in compose_text or "ROYAL_BROWSER_CDP_URL: http://royal-browser:9222" not in compose_text:
        failures.append("docker-compose.yml: isolated provider browser boundary missing")

    return failures


def main() -> int:
    failures = scan()
    if failures:
        print("Security regression scan failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("Security regression scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
