from pathlib import Path

import pytest

from scripts import release_readiness_gate as gate


def test_release_gate_resolves_the_project_root():
    assert (gate.PROJECT_ROOT / "app_version.py").is_file()
    assert gate.PROJECT_ROOT == Path(__file__).resolve().parents[1]


def test_upgrade_mapping_allows_only_additive_candidate_defaults():
    gate._expect_persisted_mapping(
        {"window_start": 1, "window_end": 6, "new_limit": 2},
        {"window_start": 1, "window_end": 6},
        "automation",
    )

    with pytest.raises(AssertionError, match="persisted values changed"):
        gate._expect_persisted_mapping(
            {"window_start": 2, "new_limit": 2},
            {"window_start": 1, "window_end": 6},
            "automation",
        )
