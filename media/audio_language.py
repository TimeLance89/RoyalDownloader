"""Confirm the language of an audio track using local speech samples."""

import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


_DETECTION = re.compile(r"auto-detected language: ([a-z]+) \(p = (\d+(?:\.\d+)?)\)")


def audio_language_runtime() -> tuple[Path, Path] | None:
    data = Path(os.environ.get("SERIENDL_DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
    executable_name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    for runtime in (data / "audio-language", Path("/opt/royal-audio-language")):
        executable = runtime / executable_name
        model = runtime / "ggml-tiny.bin"
        if executable.is_file() and model.is_file():
            return executable, model
    return None


def confirm_audio_language(path: Path, index: int, duration: float, language: str) -> bool:
    runtime = audio_language_runtime()
    if runtime is None:
        return False
    executable, model = runtime

    confirmed = 0
    try:
        with TemporaryDirectory(prefix="rd-audio-") as temp:
            sample = Path(temp) / "sample.wav"
            for fraction in (0.15, 0.4, 0.7):
                extract = subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-y",
                     "-ss", str(round(duration * fraction)), "-i", str(path),
                     "-map", f"0:{index}", "-t", "25", "-ac", "1", "-ar", "16000", str(sample)],
                    capture_output=True, timeout=15,
                )
                if extract.returncode:
                    continue
                result = subprocess.run(
                    [str(executable.resolve()), "-m", str(model.resolve()), "-f", str(sample),
                     "--detect-language", "--no-gpu", "--threads", "2"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
                )
                match = _DETECTION.search(result.stderr) if result.returncode == 0 else None
                if match is None or float(match[2]) < 0.9:
                    continue
                if match[1] != language:
                    return False
                confirmed += 1
    except (OSError, subprocess.TimeoutExpired):
        return False
    return confirmed >= 2
