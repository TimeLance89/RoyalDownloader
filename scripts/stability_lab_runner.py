#!/usr/bin/env python3
"""Isolated pytest-file runner for GitHub's non-blocking Stability Lab.

Each test module gets its own Python process and a hard deadline. A poisoned
global state, deadlock or leaked daemon thread cannot stall the other modules.
No production API calls or credentials are needed by the runner itself.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def _safe_name(path: Path) -> str:
    return path.stem.replace("/", "_").replace("\\", "_")


def main() -> int:
    args = _parse_args()
    if not 0 <= args.shard < args.shards:
        raise SystemExit("Invalid shard index")
    if not 10 <= args.timeout <= 300:
        raise SystemExit("Per-file timeout must be between 10 and 300 seconds")
    modules = sorted(Path("tests").glob("test_*.py"))
    if not modules:
        raise SystemExit("No Python tests discovered; refusing a false green result")
    selected = [p for index, p in enumerate(modules) if index % args.shards == args.shard]
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    started = time.monotonic()
    for ordinal, path in enumerate(selected, 1):
        print(f"[{ordinal}/{len(selected)}] Testing {path} (hard limit {args.timeout}s)", flush=True)
        began = time.monotonic()
        command = [
            sys.executable, "-m", "pytest", "-q", "--tb=short",
            "--disable-warnings", str(path),
        ]
        status = "passed"
        code = 0
        output = ""
        try:
            run = subprocess.run(
                command, capture_output=True, text=True, errors="replace",
                timeout=args.timeout, check=False,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            code = run.returncode
            output = (run.stdout or "") + "\n" + (run.stderr or "")
            if code != 0:
                status = "failed"
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            code = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            output = (
                (stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else stdout)
                + "\n"
                + (stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr)
            )
        elapsed = round(time.monotonic() - began, 3)
        record = {
            "file": str(path), "status": status,
            "exit_code": code, "seconds": elapsed,
        }
        records.append(record)
        if status != "passed":
            # Full failed logs as artifacts; console remains reasonably short.
            (args.output / f"{_safe_name(path)}.log").write_text(
                output[-150_000:], encoding="utf-8",
            )
            print(f"  {status.upper()} ({elapsed}s): {output[-3000:]}", flush=True)
        else:
            print(f"  PASSED ({elapsed}s)", flush=True)

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "shard": args.shard, "shards": args.shards,
        "modules_discovered": len(modules),
        "modules_selected": len(selected),
        "seconds_total": round(time.monotonic() - started, 3),
        "passed": sum(x["status"] == "passed" for x in records),
        "failed": sum(x["status"] == "failed" for x in records),
        "timeouts": sum(x["status"] == "timeout" for x in records),
        "results": records,
    }
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8",
    )
    summary = (
        f"### Stability Lab – Python shard {args.shard + 1}/{args.shards}\n"
        f"- Discovered: {len(modules)} Python test files\n"
        f"- Tested in this shard: {len(selected)}\n"
        f"- Passed: {report['passed']}, failed: {report['failed']}, "
        f"timeouts: {report['timeouts']}\n"
        f"- Total: {report['seconds_total']} seconds\n"
        "\n| Module | Result | Seconds |\n|---|---|---:|\n"
        + "".join(
            f"| \\u0060{r['file']}\\u0060 | {r['status']} | {r['seconds']:.2f} |\n"
            for r in records
        )
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(summary, encoding="utf-8")
    print(summary, flush=True)
    return 1 if report["failed"] or report["timeouts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
