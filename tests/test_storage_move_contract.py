from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_move_engine_keeps_cross_volume_operation_guarded():
    source = (ROOT / "storage_move.py").read_text(encoding="utf-8")
    for marker in (
        "same_volume",
        "collision",
        "required_bytes",
        ".royal-move-",
        "shutil.move",
        "os.replace",
        "source.source.exists()",
        "Zielgröße stimmt",
    ):
        assert marker in source


def test_series_move_is_promoted_to_top_level_series_folder():
    source = (ROOT / "storage_move.py").read_text(encoding="utf-8")
    assert 'if root.role == "series"' in source
    assert "pure.parts[0]" in source
    assert 'return top.resolve(strict=True), "series"' in source


def test_movie_move_requires_single_top_level_file():
    source = (ROOT / "storage_move.py").read_text(encoding="utf-8")
    assert 'if root.role == "movies"' in source
    assert 'candidate_kind != "file" or len(pure.parts) != 1' in source
