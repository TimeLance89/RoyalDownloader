"""Bounded spoken-language verification for completed series downloads."""

import json
import math
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from tempfile import TemporaryDirectory


_worker = threading.Lock()
_detection = re.compile(r"auto-detected language: ([a-z]+) \(p\s*=\s*(\d+(?:\.\d+)?)\)")
_confidence_threshold = 0.90


def _runtime():
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    data = Path(os.environ.get("SERIENDL_DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
    for root in (data / "audio-language", Path("/opt/royal-audio-language")):
        executable, model = root / name, root / "ggml-tiny.bin"
        if executable.is_file() and os.access(executable, os.X_OK) and model.is_file():
            return executable.resolve(), model.resolve()
    return None


def _run(args, timeout):
    nice = shutil.which("nice") if os.name != "nt" else None
    return subprocess.run(
        ([nice, "-n", "10"] if nice else []) + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=True,
    )


def _sample_languages(path, index, duration, directory, runtime, fractions, cancelled):
    samples = []
    for fraction in fractions:
        if cancelled():
            return []
        sample = str(Path(directory) / f"sample-{fraction}.wav")
        _run([
            "ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-ss", str(duration * fraction),
            "-i", str(path), "-map", f"0:{index}", "-t", "10",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", sample,
        ], 8)
        samples.extend(("-f", sample))
    if cancelled():
        return []
    executable, model = runtime
    result = _run([
        str(executable), "-m", str(model), "--detect-language",
        "--no-gpu", "--threads", "1", *samples,
    ], 30)
    return [(lang, float(score)) for lang, score in _detection.findall(result.stderr)][:len(fractions)]


def verify_german_audio(path: Path, cancelled, report) -> tuple[str, str]:
    runtime = _runtime()
    if runtime is None:
        return "unavailable", "Whisper-Modell oder Programm fehlt"
    if not _worker.acquire(blocking=False):
        report("waiting", "Wartet auf die laufende Tonprüfung")
        while not cancelled():
            if _worker.acquire(timeout=0.25):
                break
        else:
            return "cancelled", "Abgebrochen"
    try:
        if cancelled():
            return "cancelled", "Abgebrochen"
        report("checking", "Prüft zwei Tonproben")
        probe = _run([
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index:stream_tags=language:format=duration",
            "-of", "json", str(path),
        ], 8)
        info = json.loads(probe.stdout)
        tracks = info.get("streams") or []
        german = [track for track in tracks if str((track.get("tags") or {}).get("language")).lower()
                  in {"de", "deu", "ger", "de-de"}]
        selected = tracks if len(tracks) == 1 else german
        duration = float((info.get("format") or {}).get("duration") or 0)
        if len(selected) != 1 or not math.isfinite(duration) or duration < 30:
            return "unclear", "Tonspur oder Laufzeit nicht eindeutig"
        with TemporaryDirectory(prefix="royal-audio-") as directory:
            index = int(selected[0]["index"])
            matches = _sample_languages(path, index, duration, directory, runtime, (0.23, 0.64), cancelled)
            if cancelled():
                return "cancelled", "Abgebrochen"
            confident = [lang for lang, score in matches if score >= _confidence_threshold]
            for fraction, label in ((0.44, "dritte"), (0.82, "vierte")):
                if len(confident) != 1:
                    break
                report("checking", f"Prüft eine {label} Tonprobe")
                try:
                    reserve = _sample_languages(path, index, duration, directory, runtime, (fraction,), cancelled)
                except (OSError, subprocess.SubprocessError):
                    if cancelled():
                        return "cancelled", "Abgebrochen"
                    break
                if cancelled():
                    return "cancelled", "Abgebrochen"
                matches.extend(reserve)
                confident.extend(lang for lang, score in reserve if score >= _confidence_threshold)
        evidence = " · ".join(f"{lang.upper()} {score:.0%}" for lang, score in matches)
        if len(set(confident)) > 1:
            return "unclear", f"Widersprüchliche Tonproben · {evidence}"
        if len(confident) < 2:
            detail = "Weniger als zwei Tonproben ab 90 %"
            return "unclear", f"{detail} · {evidence}" if evidence else detail
        language = confident[0]
        if language == "de":
            return "confirmed", f"Deutsch in zwei Tonproben erkannt · {evidence}"
        return "mismatch", f"Zwei Tonproben melden {language.upper()} · {evidence}"
    except subprocess.TimeoutExpired:
        return "unavailable", "Zeitlimit der Tonprüfung erreicht"
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return "unavailable", "Tonprüfung fehlgeschlagen oder Zeitlimit erreicht"
    finally:
        _worker.release()
