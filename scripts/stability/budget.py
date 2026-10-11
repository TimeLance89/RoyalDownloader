"""Paired, noise-tolerant budgets plus deterministic workload invariants."""
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--responses', type=Path)
    args = parser.parse_args()
    baseline, candidate = (json.loads(p.read_text()) for p in (args.baseline, args.candidate))
    failures, comparisons = [], []
    def median(doc, n, key):
        values = [r[key]['median_ms'] if isinstance(r[key], dict) else r[key]
                  for r in doc['rows'] if r['size'] == n]
        if len(values) < 3:
            raise ValueError('Need at least three fresh-process repeats per size')
        return statistics.median(values)
    for n in (650, 1000, 5000):
        for key in ('queue_payload', 'durable_signature', 'snapshot', 'atomic_persist', 'recovery', 'cpu_seconds'):
            b, c = median(baseline, n, key), median(candidate, n, key)
            # Shared CI runners need headroom; exact structural budgets below
            # catch extra fsyncs/threads/scans without depending on wall time.
            limit = b * 1.25 + (0.02 if key == 'cpu_seconds' else 2.0)
            comparisons.append({'size': n, 'metric': key, 'baseline': b, 'candidate': c, 'limit': limit})
            if c > limit:
                failures.append(f'{n} {key}: {c:.3f} > {limit:.3f}')
        b, c = median(baseline, n, 'peak_rss_mib'), median(candidate, n, 'peak_rss_mib')
        if c > b * 1.15 + 8:
            failures.append(f'{n}: RSS regression')
    for row in candidate['rows']:
        for key, expected in [('blocked_additional_scans', 0), ('durable_writes', 1), ('volatile_skips', 100)]:
            if row[key] != expected:
                failures.append(f"{row['size']} {key}: {row[key]} != {expected}")
        if row['thread_count_after'] != row['thread_count_before']:
            failures.append(f"{row['size']}: leaked thread")
        if row['peak_observed_threads'] > row['thread_count_before'] + 2:
            failures.append(f"{row['size']}: unbounded blocked-host threads")
        if row['persist_operations_per_save'] != {'fsync_calls': 4, 'replacements': 2}:
            failures.append(f"{row['size']}: durable save operation count changed")
    if args.responses:
        responses = json.loads(args.responses.read_text())
        for b, c in zip(responses['baseline'], responses['candidate']):
            if b['size'] != c['size']:
                raise ValueError('Mismatched response sizes')
            if c['queue_median_ms'] > b['queue_median_ms'] * 1.25 + 5:
                failures.append(f"{c['size']}: queue response regression")
            if c['health_median_ms'] > 30:
                failures.append(f"{c['size']}: concurrent health stalled")
    print(json.dumps({'passed': not failures, 'failures': failures, 'comparisons': comparisons}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
