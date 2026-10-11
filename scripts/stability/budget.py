"""One fail-closed comparison policy for all paired stability workloads."""
import argparse
import json
import math
from pathlib import Path
import statistics

SIZES = (650, 1000, 5000)
TIMINGS = ('queue_payload', 'durable_signature', 'snapshot', 'atomic_persist',
           'recovery', 'normalize_with_history', 'volatile_persist_100',
           'scheduler_lock_response', 'enqueue_ms', 'first_dispatch_ms', 'cancel_ms',
           'cpu_seconds')


def number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError('Metric must be numeric')
    if not math.isfinite(value) or value < 0:
        raise ValueError('Metric must be finite and non-negative')
    return value


def validate(doc):
    repeats = doc['repeats']
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 3:
        raise ValueError('Need at least three fresh-process repeats')
    expected = {(size, repeat) for size in SIZES for repeat in range(1, repeats + 1)}
    actual = [(r['size'], r['repeat']) for r in doc['rows']]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Missing, duplicated or unexpected benchmark rows')
    for row in doc['rows']:
        for key in (*TIMINGS, 'peak_rss_mib', 'python_allocated_peak_mib'):
            value = row[key]
            number(value['median_ms'] if isinstance(value, dict) else value)


def compare(baseline, candidate, responses=None):
    validate(baseline); validate(candidate)
    for key in ('python', 'platform', 'cpu_count', 'repeats'):
        if baseline[key] != candidate[key]:
            raise ValueError('Incomparable benchmark environment: ' + key)
    failures, comparisons = [], []
    def median(doc, n, key):
        return statistics.median([r[key]['median_ms'] if isinstance(r[key], dict) else r[key]
                                  for r in doc['rows'] if r['size'] == n])
    for n in SIZES:
        for key in TIMINGS:
            b, c = median(baseline, n, key), median(candidate, n, key)
            limit = b * 1.25 + (0.02 if key == 'cpu_seconds' else 2.0)
            comparisons.append({'size': n, 'metric': key, 'baseline': b, 'candidate': c, 'limit': limit})
            if c > limit:
                failures.append(f'{n} {key}: {c:.3f} > {limit:.3f}')
        for key, slack in [('peak_rss_mib', 8), ('python_allocated_peak_mib', 2)]:
            b, c = median(baseline, n, key), median(candidate, n, key)
            limit = b * 1.15 + slack
            comparisons.append({'size': n, 'metric': key, 'baseline': b, 'candidate': c, 'limit': limit})
            if c > limit:
                failures.append(f'{n}: {key} regression')
    for label, doc in [('baseline', baseline), ('candidate', candidate)]:
        for row in doc['rows']:
            for key, expected in [('blocked_additional_scans', 0), ('durable_writes', 1), ('volatile_skips', 100)]:
                if row[key] != expected:
                    failures.append(f"{label} {row['size']} {key}: {row[key]} != {expected}")
            if row['thread_count_after'] != row['thread_count_before']:
                failures.append(f"{label} {row['size']}: leaked thread")
            if row['peak_observed_threads'] > row['thread_count_before'] + 2:
                failures.append(f"{label} {row['size']}: unbounded blocked-host threads")
            if row['persist_operations_per_save'] != {'fsync_calls': 4, 'replacements': 2}:
                failures.append(f"{label} {row['size']}: durable save operation count changed")
    if responses is not None:
        for label in ('baseline', 'candidate'):
            rows = responses[label]
            if len(rows) != len(SIZES) or {r['size'] for r in rows} != set(SIZES):
                raise ValueError('Missing or duplicated response sizes')
            for r in rows:
                number(r['queue_median_ms']); number(r['health_median_ms'])
                for key in ('burst_health_median_ms', 'burst_wall_median_ms', 'cpu_seconds', 'peak_rss_mib'):
                    number(r[key])
                if r['burst_concurrency'] != 8:
                    raise ValueError('Changed concurrent request workload')
                for key in ('queue_ms', 'health_ms', 'burst_health_ms', 'burst_wall_ms'):
                    if len(r[key]) < 3:
                        raise ValueError('Insufficient response samples')
                    for sample in r[key]:
                        number(sample)
        bases = {r['size']: r for r in responses['baseline']}
        for c in responses['candidate']:
            b = bases[c['size']]
            if c['queue_median_ms'] > b['queue_median_ms'] * 1.25 + 5:
                failures.append(f"{c['size']}: queue response regression")
            if c['burst_health_median_ms'] > 30:
                failures.append(f"{c['size']}: concurrent burst health stalled")
            if c['burst_wall_median_ms'] > b['burst_wall_median_ms'] * 1.25 + 10:
                failures.append(f"{c['size']}: concurrent burst throughput regression")
            if c['health_median_ms'] > 30:
                failures.append(f"{c['size']}: concurrent health stalled")
    return {'passed': not failures, 'failures': failures, 'comparisons': comparisons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--responses', type=Path)
    args = parser.parse_args()
    try:
        result = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()),
                         json.loads(args.responses.read_text()) if args.responses else None)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        result = {'passed': False, 'failures': ['Invalid comparison: ' + str(exc)], 'comparisons': []}
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(not result['passed'])


if __name__ == '__main__':
    main()
