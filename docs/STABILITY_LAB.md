# RoyalDownloader Stability Lab (experimental)

The lab runs the current branch in a fresh Linux GitHub Actions VM. It does
**not** connect to the owner's NAS, use production queue data or touch private
media volumes. It is intended to make reliability and throughput measurable
before adding major functionality.

## What the lab actually tests

1. Discover every `tests/test_*.py` module (176 modules in the initial
   Overnight baseline). Distribute them consistently over eight parallel
   GitHub Actions jobs.
2. Run **each Python test file in its own subprocess**, with a 90-second
   deadline. Capture per-file pass/fail/timeout, duration and full failed
   output as downloadable artifacts. One deadlock cannot block the other
   175 modules. Failures are not silently ignored.
3. Benchmark real 650-job queue + 500-record history normalization, 4,000
   logical jobs, atomic write/recovery across 650 jobs, and 800 concurrent
   queue insertions. No live provider download is involved.
4. Run identical candidate/base workloads sequentially on the **same runner
   and Python**. This controls some VM noise but is not a substitute for
   repeated measurements on real hardware. Report median wall time and
   Python-traced memory, and flag meaningful regressions.
5. Existing `Quality checks` continues to cover WebKit/mobile, browser
   functional tests, frontend performance, container build, security scan,
   application boot/login, queue persistence/restart and Docker E2E flows.
   The Stability Lab is additional diagnostic coverage, not a replacement.

The initial lab workflow is **not a required branch check**. It must first
establish its own reliable baseline: there may be real, previously unnoticed
test failures, tests needing missing optional tools, or flaky fixtures. Do not
relabel such results green. Fix/quarantine with a documented reason after
diagnosis, then make the lab required in a separate reviewed change.

## Run and results

- PR changes to the testing/workflow/backend areas automatically trigger
  `Royal Stability Lab` for pull requests targeting `overnight`.
- Once the workflow is merged into the default branch, its
  `workflow_dispatch` action can be used manually.
- Open Actions → Royal Stability Lab → the relevant run.
- The eight `Python isolation` jobs show module-level outcomes and exact
  duration in the job summary. Download `stability-python-shard-*` artifacts
  for the full JSON report and failure traces.
- `Paired queue performance baseline` reports baseline vs candidate time
  and memory. Download `stability-queue-performance` for raw measurements.
- Manual invocation:
  `python scripts/stability_lab_runner.py --shard 0 --shards 8 --timeout 90 --output artifacts/stability-lab/shard-0 --summary artifacts/stability-lab/summary-0.md`
- Performance:
  `python scripts/stability_benchmark.py run --root . --samples 5 --output metrics.json`.

### Performance gates

A red regression requires at least **60% slower** *and* 50 ms absolute
slowdown, or at least **60% more traced Python memory** *and* 12 MiB higher
memory consumption in a measured scenario. Smaller anomalies are warnings.
The reports include actual numbers; a green result does not mean zero
regression. These are initial conservative lab gates, to be calibrated only
after repeatable measured runs and not weakened to silence a known regression.

Timing includes Python execution and local filesystem fsync where applicable.
Benchmarks are synthetic and cannot represent the network bottlenecks,
Jellyfin load, SMB/NAS drive latency, file fragmentation or thermal throttling
of the Ugreen device. Real download speed cannot be guaranteed by unit
benchmarks.

## Reliability roadmap and production promotion gates

| Stage | Goal | Minimum evidence |
|---|---|---|
| A – Static/deterministic | Queue persistence, recovery, provider retry and code invariants | Isolated Python regression corpus and GitHub Quality checks |
| B – Controlled E2E | Restart during active MP4, storage full, bad range replies, out-of-date auth cookies and durable checkpoint ownership | Deterministic local HTTP fixtures + Docker restart integration |
| C – Soak | 650–1,000 queued jobs, sustained progress floods, thread/FD leak checks, recovery after interruptions | 6–24 hour isolated run with logged p50/p95, RSS, open handles, queue size, errors |
| D – Hardware | Real NAS permissions, two physical volumes, Jellyfin scans, update/rollback, storage pressure | Backed-up NAS pilot and verified media output |
| E – Stable | Release to `main` | All gates green + manual recovery drill + documented rollback plan |

Only mark a stage completed when actual evidence exists. As of the first lab
PR, stages B through E are plans, **not completed validations**.

### Safety principles

- No real media paths or real API keys in CI; use synthetic media and fixtures.
- Avoid public hosters for stress testing. Network/hoster availability is
  external and nondeterministic.
- Never relax the protected `overnight` branch to force a green badge.
- Keep existing UX, REST/WebSocket contracts and provider choices stable.
- A failed media validation must never publish a partial file.
- Never destroy or corrupt the owner's real queue to simulate a crash.
