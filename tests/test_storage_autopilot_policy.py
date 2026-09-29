from copy import deepcopy

import pytest

from storage.storage_policy import DEFAULT_POLICY, DEFAULT_VOLUME, GIB, validate_policy, validate_volume, volume_policy
from storage.storage_score import score_target, storage_pressure


def root(**changes):
    return {"key": "movies", "available": True, "writable": True,
            "location_mode": "media", "free_bytes": 600 * GIB,
            "total_bytes": 1000 * GIB, "volume_id": "one", **changes}


def test_autonomy_never_grants_delete():
    for mode in ("monitor", "advisor", "automatic", "full"):
        assert validate_policy({"mode": mode})["auto_delete"] is False
    old = validate_policy({"auto_delete": True, "delete_categories": ["royal_partials"]})
    assert validate_policy({"mode": "monitor"}, old)["auto_delete"] is True


@pytest.mark.parametrize("raw", [
    {"mode": "god"}, {"auto_delete": "false"}, {"delete_categories": ["media"]},
    {"window_start": "25:00"}, {"max_moves": 1000}, {"interval_hours": float("nan")},
    {"unknown_download_gib": 0}, {"extra": True},
])
def test_invalid_global_policy_rejected(raw):
    with pytest.raises(ValueError):
        validate_policy(raw)


@pytest.mark.parametrize("raw", [
    {"target_percent": 90}, {"reserve_gib": -1}, {"media_types": ["backup"]},
    {"allow_moves_in": "true"}, {"role": "fast"}, {"critical_percent": 101},
])
def test_invalid_volume_policy_rejected(raw):
    with pytest.raises(ValueError):
        validate_volume(raw)


def test_monitor_permission_cannot_be_overridden():
    policy = volume_policy(root(location_mode="monitor"), {"movies": {"role": "primary"}})
    assert policy["role"] == "monitor"
    assert policy["allow_moves_in"] is policy["allow_moves_out"] is False


@pytest.mark.parametrize("changes,policy", [
    ({"available": False}, {}), ({"writable": False}, {}),
    ({"location_mode": "monitor"}, {}), ({}, {"media_types": ["anime"]}),
    ({"free_bytes": 10 * GIB}, {}), ({"free_bytes": 70 * GIB}, {}),
])
def test_hard_limits_defeat_high_affinity_score(changes, policy):
    result = score_target(root(**changes), validate_volume(policy), media_type="movies", size=8 * GIB, affinity=True)
    assert result["eligible"] is False
    assert result["score"] is None


def test_primary_wins_without_pressure_and_overflow_wins_at_target():
    primary = validate_volume({})
    overflow = validate_volume({"role": "overflow"})
    score = lambda data, policy, **kw: score_target(data, policy, media_type="movies", size=8 * GIB, **kw)["score"]
    assert score(root(), primary) > score(root(), overflow)
    assert score(root(free_bytes=180 * GIB), primary) < score(root(), overflow, overflow=True)


def test_affinity_is_stronger_than_slight_capacity_advantage():
    affinity = score_target(root(free_bytes=400 * GIB), DEFAULT_VOLUME, media_type="series", size=8 * GIB, affinity=True)
    other = score_target(root(free_bytes=450 * GIB), DEFAULT_VOLUME, media_type="series", size=8 * GIB)
    assert affinity["score"] > other["score"]
    assert any("Serie" in reason for reason in affinity["reasons"])


def test_reserved_capacity_prevents_overcommit_and_predicts_pressure():
    data = root(free_bytes=120 * GIB)
    policy = deepcopy(DEFAULT_VOLUME)
    result = score_target(data, policy, media_type="series", size=50 * GIB, reserved=80 * GIB)
    assert not result["eligible"]
    assert storage_pressure(data, policy, 80 * GIB) == "critical"
    assert storage_pressure(data, policy, 120 * GIB) == "emergency"
