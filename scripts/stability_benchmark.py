#!/usr/bin/env python3
"""Deterministic, offline throughput/memory checks against the same-host baseline.

Usage:
  python scripts/stability_benchmark.py run --root . --output candidate.json
  python scripts/stability_benchmark.py compare --baseline base.json --candidate candidate.json

Benchmark cases exercise real queue normalization, durable NAS-style writes,
recovery, and simultaneous queue producers. No media or provider calls.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gc
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path


def _workloads():
    import server  # noqa: F401 - install the actual optimized queue lifecycle
    from core.queue_jobs import (
        SCHEMA_VERSION, atomic_save, load_document, new_job, normalize_document,
    )
    from media.downloader import DownloadQueue

    jobs = []
    for index in range(650):
        j = new_job(f"fixture:show-s01e{index + 1:04d}", job_id=f"job-{index:05d}")
        j["status"] = ["queued", "downloading", "waiting_provider"][index % 3]
        jobs.append(j)
    history = []
    for index in range(500):
        j = new_job(f"fixture:history-{index}", job_id=f"done-{index:05d}")
        j["status"] = "completed"
        j["completed_at"] = float(index + 1)
        history.append(j)
    record_650 = {
        "schema_version": SCHEMA_VERSION, "revision": 7,
        "jobs": jobs, "history": history,
    }
    record_4000 = {
        **record_650,
        "jobs": [
            new_job(f"fixture:scale-s01e{i + 1:05d}", job_id=f"scale-{i}")
            for i in range(4000)
        ],
        "history": [],
    }

    def normalize_650():
        doc, changed = normalize_document(record_650)
        assert not changed and len(doc["jobs"]) == 650 and len(doc["history"]) == 500

    def normalize_4000():
        doc, changed = normalize_document(record_4000)
        assert not changed and len(doc["jobs"]) == 4000

    def durable_save_recover_650():
        with tempfile.TemporaryDirectory(prefix="royal-stability-") as td:
            path = Path(td) / "download_queue.json"
            atomic_save(path, record_650)
            recovered, changed = load_document(path)
            assert not changed and len(recovered["jobs"]) == 650
            updated = {**record_650, "revision": 8}
            atomic_save(path, updated)
            recovered, changed = load_document(path)
            assert not changed and recovered["revision"] == 8
            assert path.with_name("download_queue.json.bak").exists()

    class Pending:
        is_preparation_job = False
        host_group = "fixture.invalid"
        queue_priority = 100

        def __init__(self, i):
            self.i = i

        def cancel(self):
            pass

    def concurrent_producers_800():
        queue = DownloadQueue(max_parallel=3, per_host_limit=1)
        def add_range(start):
            for i in range(start, start + 100):
                queue.add(Pending(i))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_range, range(0, 800, 100)))
        assert queue.pending_count() == 800
        assert {job.i for job in queue.pending_jobs()} == set(range(800))
        queue.cancel_all()
        assert queue.pending_count() == 0

    return {
        "normalize_650_jobs_500_history": normalize_650,
        "normalize_4000_jobs": normalize_4000,
        "atomic_save_restore_650_jobs": durable_save_recover_650,
        "parallel_queue_insert_800": concurrent_producers_800,
    }


def run_bench(root: Path, output: Path, samples: int) -> int:
    root = root.resolve()
    if not (root / "core/queue_jobs.py").exists():
        raise ValueError("Not a RoyalDownloader source tree: " + str(root))
    # Imports, configuration and any relative paths resolve to the tested
    # checkout rather than the location of this benchmark script.
    os.chdir(root)
    sys.path.insert(0, str(root))
    cases = _workloads()
    results = {}
    for name, execute in cases.items():
        print(f"Benchmark {name}...", flush=True)
        execute()  # warm up imports, caches and temp file paths
        durations = []
        peaks = []
        for _ in range(samples):
            gc.collect()
            tracemalloc.start()
            try:
                began = time.perf_counter()
                execute()
                durations.append((time.perf_counter() - began) * 1000)
                peaks.append(tracemalloc.get_traced_memory()[1] / (1024 * 1024))
            finally:
                tracemalloc.stop()
        results[name] = {
            "median_ms": round(statistics.median(durations), 3),
            "max_ms": round(max(durations), 3),
            "median_peak_mib": round(statistics.median(peaks), 3),
            "samples": samples,
        }
        print(f"  {results[name]}", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema": 1,
        "python": sys.version.split()[0],
        "cases": results,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


def compare_bench(base_path: Path, candidate_path: Path, summary: Path) -> int:
    baseline = json.loads(base_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if baseline.get("schema") != 1 or candidate.get("schema") != 1:
        raise ValueError("Unknown benchmark schema")
    if set(baseline["cases"]) != set(candidate["cases"]):
        raise ValueError("Benchmark cases differ; refusing incomparable data")
    problems = []
    rows = []
    for name, old in baseline["cases"].items():
        new = candidate["cases"][name]
        base_ms = float(old["median_ms"])
        curr_ms = float(new["median_ms"])
        base_mib = float(old["median_peak_mib"])
        curr_mib = float(new["median_peak_mib"])
        factor = curr_ms / max(0.001, base_ms)
        memory_factor = curr_mib / max(0.001, base_mib)
        # Pessimistic gates deliberately require both relative AND absolute
        # degradation; VM noise should not make a 2ms -> 4ms change fatal.
        severe = (factor > 1.60 and curr_ms - base_ms > 50) or (
            memory_factor > 1.60 and curr_mib - base_mib > 12
        )
        warn = (factor > 1.30 and curr_ms - base_ms > 10) or (
            memory_factor > 1.30 and curr_mib - base_mib > 5
        )
        verdict = "REGRESSION" if severe else ("WARNING" if warn else "OK")
        if severe:
            problems.append(name)
        rows.append(
            f"| {name} | {base_ms:.2f} | {curr_ms:.2f} | "
            f"{factor:.2f}x | {base_mib:.2f} | {curr_mib:.2f} | {verdict} |"
        )
    report = (
        "## RoyalDownloader Stability Lab – paired offline performance\n\n"
        "Same runner, same Python, fixed workloads, median of repeated samples.\n\n"
        "| Workload | Baseline ms | Candidate ms | Time | Baseline MiB | Candidate MiB | Gate |\n"
        "|---|---:|---:|---:|---:|---:|---|\n"
        + "\n".join(rows)
        + "\n\nOnly severe, absolute **and** relative regressions fail this lab. "
        "GitHub-hosted CPU/disk timings are noisy; use multiple runs before "
        "interpreting marginal differences. These offline benchmarks do not "
        "measure real NAS disk latency, external hoster throughput or network "
        "conditions.\n"
    )
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(report, encoding="utf-8")
    print(report)
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run")
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--samples", type=int, default=5)
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "run":
        if not 3 <= args.samples <= 11:
            raise SystemExit("samples must be between 3 and 11")
        return run_bench(args.root, args.output, args.samples)
    return compare_bench(args.baseline, args.candidate, args.summary)


if __name__ == "__main__":
    raise SystemExit(main())
