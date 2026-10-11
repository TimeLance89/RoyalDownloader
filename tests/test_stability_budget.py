"""Incomplete/invalid measurements must never produce a green budget."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stability_budget', ROOT / 'scripts/stability/budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def valid():
    rows = []
    for size in budget.SIZES:
        for repeat in (1, 2, 3):
            row = dict(size=size, repeat=repeat, peak_rss_mib=100,
                       python_allocated_peak_mib=5, blocked_additional_scans=0,
                       durable_writes=1, volatile_skips=100, thread_count_before=1,
                       thread_count_after=1, peak_observed_threads=3,
                       persist_operations_per_save={'fsync_calls': 4, 'replacements': 2})
            row.update({key: 1 for key in budget.TIMINGS})
            rows.append(row)
    return dict(rows=rows, repeats=3, python='fixture', platform='fixture', cpu_count=2)


def test_identical_complete_measurements_pass():
    assert budget.compare(valid(), valid())['passed']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 'fast', True])
def test_invalid_numbers_fail_closed(value):
    candidate = valid(); candidate['rows'][0]['cpu_seconds'] = value
    with pytest.raises(ValueError):
        budget.compare(valid(), candidate)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'python', 'samples'])
def test_incomplete_or_incomparable_rows_are_rejected(mutation):
    candidate = valid()
    if mutation == 'missing':
        candidate['rows'].pop()
    elif mutation == 'duplicate':
        candidate['rows'][1] = copy.deepcopy(candidate['rows'][0])
    elif mutation == 'python':
        candidate['python'] = 'different'
    else:
        candidate['repeats'] = 1
    with pytest.raises(ValueError):
        budget.compare(valid(), candidate)


def test_missing_responses_cannot_hide_latency_regression():
    responses = {'baseline': [], 'candidate': []}
    with pytest.raises(ValueError):
        budget.compare(valid(), valid(), responses)


@pytest.mark.parametrize('kind', ['cpu', 'fsync', 'threads'])
def test_real_budget_regressions_are_red(kind):
    candidate = valid()
    for row in candidate['rows']:
        if kind == 'cpu':
            row['cpu_seconds'] = 10
        elif kind == 'fsync':
            row['persist_operations_per_save']['fsync_calls'] = 3
        else:
            row['thread_count_after'] = 2
    assert not budget.compare(valid(), candidate)['passed']
