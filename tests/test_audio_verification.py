import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from media import audio_verification as audio


@pytest.mark.parametrize(("detections", "reserve", "fourth", "expected"), [
    ("de 0.98,de 0.96", None, None, "confirmed"),
    ("en 0.98,en 0.96", None, None, "mismatch"),
    ("de 0.98,en 0.96", None, None, "unclear"),
    ("de 0.85,de 0.83", None, None, "unclear"),
    ("de 0.97,de 0.85", "de 0.94", None, "confirmed"),
    ("nn 0.30,de 0.93", "de 0.91", None, "confirmed"),
    ("en 0.98,en 0.42", "en 0.92", None, "mismatch"),
    ("de 0.97,de 0.85", "en 0.94", None, "unclear"),
    ("en 0.98", "", "", "unclear"),
    ("de 0.97,de 0.85", "de 0.88", "de 0.94", "confirmed"),
    ("en 0.97,de 0.85", "en 0.88", "en 0.94", "mismatch"),
])
def test_whisper_only_runs_reserve_probes_when_decisive(monkeypatch, detections, reserve, fourth, expected):
    monkeypatch.setattr(audio, "_runtime", lambda: (Path("whisper-cli"), Path("model.bin")))
    calls = []
    batches = iter([detections, reserve, fourth])

    def run(args, timeout):
        calls.append((args, timeout))
        responses = next(batches) if args[0] == "whisper-cli" else ""
        stderr = "\n".join(
            f"whisper_full: auto-detected language: {lang} (p = {score})"
            for lang, score in map(str.split, filter(None, (responses or "").split(",")))
        )
        return SimpleNamespace(
            stdout=json.dumps({"streams": [{"index": 1}], "format": {"duration": 400}}),
            stderr=stderr,
        )

    monkeypatch.setattr(audio, "_run", run)
    statuses = []
    state, _ = audio.verify_german_audio(Path("episode.mp4"), lambda: False, lambda *event: statuses.append(event))
    assert state == expected
    assert [args[0] for args, _ in calls[:4]] == ["ffprobe", "ffmpeg", "ffmpeg", "whisper-cli"]
    assert calls[3][0].count("-f") == 2
    assert statuses[0][0] == "checking"
    reserve_count = sum(value is not None for value in (reserve, fourth))
    assert [args[0] for args, _ in calls[4:]] == ["ffmpeg", "whisper-cli"] * reserve_count
    assert len(statuses) == 1 + reserve_count
    if fourth is not None:
        assert statuses[-1] == ("checking", "Prüft eine vierte Tonprobe")


def test_missing_runtime_is_visible_without_running_a_process(monkeypatch):
    monkeypatch.setattr(audio, "_runtime", lambda: None)
    assert audio.verify_german_audio(Path("episode.mp4"), lambda: False, lambda *_: None)[0] == "unavailable"


def test_confirmed_foreign_audio_is_not_published(monkeypatch, tmp_path):
    from media import downloader

    events = []
    job = downloader.DownloadJob(
        "https://fixture.invalid/video.mp4", "mp4", tmp_path / "episode.mp4",
        on_audio_verification=lambda *event: events.append(event),
    )
    job.staging_path.parent.mkdir(parents=True)
    job.staging_path.write_bytes(b"video")
    monkeypatch.setattr(job, "_validate_media", lambda _candidate: (True, "OK"))
    monkeypatch.setattr(downloader, "verify_german_audio", lambda *_args: ("mismatch", "EN"))

    assert job._finalize() == (False, "Deutsche Tonspur nicht bestätigt. EN")
    assert job.failure_kind == "audio_language_mismatch"
    assert events == [("mismatch", "EN")]
    assert not job.out_path.exists()


@pytest.mark.parametrize('first', ['missing_tracks', 'missing_duration', 'invalid_json', 'timeout', 'error'])
def test_incomplete_fast_metadata_probe_retries_normal_analysis_once(monkeypatch, first):
    import subprocess
    calls = []
    valid = {'streams': [{'index': 1}], 'format': {'duration': '400'}}
    def run(args, timeout):
        calls.append((args, timeout))
        if len(calls) == 1:
            if first == 'timeout':
                raise subprocess.TimeoutExpired(args, timeout)
            if first == 'error':
                raise subprocess.CalledProcessError(1, args)
            value = {'streams': []} if first == 'missing_tracks' else {'streams': [{'index': 1}]}
            return SimpleNamespace(stdout='invalid' if first == 'invalid_json' else json.dumps(value))
        return SimpleNamespace(stdout=json.dumps(valid))
    monkeypatch.setattr(audio, '_run', run)
    assert audio._probe_audio(Path('transport.mp4'), lambda: False) == valid
    assert [timeout for _, timeout in calls] == [8, 20]
    assert '-probesize' in calls[0][0] and '-probesize' not in calls[1][0]


def test_fast_probe_success_does_not_repeat_metadata_scan(monkeypatch):
    calls = []
    valid = {'streams': [{'index': 1}], 'format': {'duration': '400'}}
    monkeypatch.setattr(audio, '_run', lambda args, timeout: calls.append(args) or SimpleNamespace(stdout=json.dumps(valid)))
    assert audio._probe_audio(Path('episode.mp4'), lambda: False) == valid
    assert len(calls) == 1


def test_cancelled_fast_probe_never_starts_full_scan(monkeypatch):
    cancelled = [False]
    calls = []
    def run(args, timeout):
        calls.append(args)
        cancelled[0] = True
        return SimpleNamespace(stdout='{}')
    monkeypatch.setattr(audio, '_run', run)
    assert audio._probe_audio(Path('episode.mp4'), lambda: cancelled[0]) == {}
    assert len(calls) == 1


def test_audio_probe_timeouts_are_bounded_and_worker_is_released(monkeypatch):
    import subprocess
    calls = []
    monkeypatch.setattr(audio, '_runtime', lambda: (Path('whisper-cli'), Path('model.bin')))
    def run(args, timeout):
        calls.append(timeout)
        raise subprocess.TimeoutExpired(args, timeout)
    monkeypatch.setattr(audio, '_run', run)
    assert audio.verify_german_audio(Path('episode.mp4'), lambda: False, lambda *_: None)[0] == 'unavailable'
    assert calls == [8, 20]
    assert audio._worker.acquire(blocking=False)
    audio._worker.release()


def test_sample_extraction_retries_without_short_analysis(monkeypatch, tmp_path):
    import subprocess
    calls = []
    def run(args, timeout):
        calls.append((args, timeout))
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stderr='auto-detected language: de (p = 0.99)')
    monkeypatch.setattr(audio, '_run', run)
    assert audio._sample_languages(Path('episode.mp4'), 1, 400, tmp_path,
                                   (Path('whisper-cli'), Path('model.bin')), (0.23,), lambda: False) == [('de', 0.99)]
    assert [timeout for _, timeout in calls] == [8, 15, 30]
    assert '-probesize' in calls[0][0] and '-probesize' not in calls[1][0]
    assert all('-y' in args for args, _ in calls[:2])
