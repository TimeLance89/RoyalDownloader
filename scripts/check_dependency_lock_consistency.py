#!/usr/bin/env python3
"""Prevent Dependabot PRs from passing CI without upgrading installed runtime locks."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = re.compile(
    r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(==|>=)\s*([0-9][A-Za-z0-9.+_-]*)"
)


def read_requirements(name: str) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for number, raw in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-r ", "--requirement ")):
            continue
        match = REQUIREMENT.match(line)
        if match is None:
            raise ValueError(f"{name}:{number}: unsupported requirement: {line}")
        package, operator, version = match.groups()
        result[package.lower().replace("_", "-").replace(".", "-")] = (operator, version)
    return result


def numbers(version: str) -> tuple[int, ...]:
    release = version.split("+", 1)[0].split("-", 1)[0]
    return tuple(int(part) for part in release.split(".") if part.isdecimal())


def main() -> None:
    runtime = read_requirements("requirements.in")
    dev = read_requirements("requirements-dev.in")
    for lockfile, declarations in (
        ("requirements.lock", runtime),
        ("requirements-dev.lock", {**runtime, **dev}),
    ):
        locked = read_requirements(lockfile)
        for package, (op, wanted) in declarations.items():
            actual = locked.get(package)
            if actual is None:
                raise ValueError(f"{lockfile}: missing required dependency {package} {op}{wanted}")
            if actual[0] != "==":
                raise ValueError(f"{lockfile}: {package} must be pinned exactly, got {actual}")
            if op == "==" and actual[1] != wanted:
                raise ValueError(f"{lockfile}: {package} expected {wanted}, found {actual[1]}")
            if op == ">=" and numbers(actual[1]) < numbers(wanted):
                raise ValueError(f"{lockfile}: {package} expected >= {wanted}, found {actual[1]}")
        print(f"{lockfile}: {len(declarations)} declared pins consistent")


if __name__ == "__main__":
    main()
