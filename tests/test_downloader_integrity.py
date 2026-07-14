import errno
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import downloader
from downloader import (
    DownloadJob, DownloadQueue, MIN_MEDIA_BYTES, cleanup_stale_staging,
    validate_media_file,
)


class ProbeResult:
    def __init__(self, streams, duration="120"):
        self.returncode = 0
        self.stdout = json.dumps({
            "streams": [{"codec_type": stream} for stream in streams],
            "format": {"duration": duration},
        })
        self.stderr = ""


class DirectResponse:
    def __init__(self, declared, chunks):
        self.headers = {"Content-Type": "video/mp4", "Content-Length": str(declared)}
        self._chunks = chunks

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        return iter(self._chunks)


class DownloaderIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def media_file(self, name="media.mp4"):
        path = self.root / name
        with path.open("wb") as handle:
            handle.truncate(MIN_MEDIA_BYTES + 1)
        return path

    @patch("downloader.subprocess.run")
    def test_validation_requires_video_and_audio(self, run):
        path = self.media_file()
        run.return_value = ProbeResult(["video", "audio"])
        valid, _ = validate_media_file(path)
        self.assertTrue(valid)

        run.return_value = ProbeResult(["video"])
        valid, detail = validate_media_file(path)
        self.assertFalse(valid)
        self.assertIn("Audiostream", detail)

    @patch("downloader.subprocess.run")
    def test_validation_rejects_short_media(self, run):
        path = self.media_file()
        run.return_value = ProbeResult(["video", "audio"], duration="12.5")
        valid, detail = validate_media_file(path)
        self.assertFalse(valid)
        self.assertIn("Videodauer", detail)

    @patch("downloader.subprocess.run")
    def test_validation_uses_stream_duration_when_format_duration_is_na(self, run):
        path = self.media_file()
        run.return_value = ProbeResult(["video", "audio"], duration="N/A")
        payload = json.loads(run.return_value.stdout)
        payload["streams"][0]["duration"] = "180"
        run.return_value.stdout = json.dumps(payload)

        valid, detail = validate_media_file(path)

        self.assertTrue(valid, detail)

    def test_validation_rejects_small_file_before_probe(self):
        path = self.root / "tiny.mp4"
        path.write_bytes(b"not-a-movie")
        valid, detail = validate_media_file(path)
        self.assertFalse(valid)
        self.assertIn("zu klein", detail)

    @patch("curl_cffi.requests.get")
    def test_direct_download_rejects_truncated_content_length(self, get):
        declared = MIN_MEDIA_BYTES + 4096
        get.return_value = DirectResponse(declared, [b"x" * (MIN_MEDIA_BYTES + 1)])
        job = DownloadJob("https://cdn/movie.mp4", "mp4", self.root / "movie.mp4")

        valid, detail = job._download_direct()

        self.assertFalse(valid)
        self.assertIn("vorzeitig", detail)

    @patch("downloader.subprocess.Popen")
    def test_pre_cancelled_job_does_not_start_ytdlp(self, popen):
        job = DownloadJob("https://cdn/movie.m3u8", "hls", self.root / "movie.mp4")
        job.cancel()

        valid, detail = job._download_ytdlp()

        self.assertFalse(valid)
        self.assertEqual(detail, "Abgebrochen")
        popen.assert_not_called()

    def test_jobs_with_same_target_have_isolated_staging(self):
        target = self.root / "movies" / "Same.Name.mp4"
        first = DownloadJob("https://one", "mp4", target)
        second = DownloadJob("https://two", "mp4", target)

        self.assertTrue(first._prepare_staging()[0])
        self.assertTrue(second._prepare_staging()[0])
        self.assertNotEqual(first.staging_dir, second.staging_dir)
        first.staging_path.write_bytes(b"first")
        second.staging_path.write_bytes(b"second")

        first._cleanup_staging()
        self.assertFalse(first.staging_dir.exists())
        self.assertEqual(second.staging_path.read_bytes(), b"second")

    def test_cleanup_finds_staging_inside_series_season(self):
        job_id = "a" * 32
        staging = self.root / "Series" / "Season 01" / ".downloading" / job_id
        staging.mkdir(parents=True)
        (staging / ".royal-downloader-job").write_text(job_id, encoding="ascii")
        artifact = staging / "download.mp4"
        artifact.write_bytes(b"partial")
        old = time.time() - 3600
        os.utime(artifact, (old, old))
        os.utime(staging, (old, old))

        removed = cleanup_stale_staging([self.root], older_than_seconds=60)

        self.assertEqual(removed, 1)
        self.assertFalse(staging.exists())

    def test_cleanup_preserves_unowned_staging_content(self):
        foreign = self.root / ".downloading" / "other-application-data"
        foreign.mkdir(parents=True)
        (foreign / "partial.bin").write_bytes(b"foreign")
        old = time.time() - 3600
        os.utime(foreign, (old, old))

        removed = cleanup_stale_staging([self.root], older_than_seconds=60)

        self.assertEqual(removed, 0)
        self.assertTrue(foreign.exists())

    def test_finalize_uses_only_own_job_files(self):
        target = self.root / "movies" / "Same.Name.mp4"
        first = DownloadJob("https://one", "mp4", target)
        second = DownloadJob("https://two", "mp4", target)
        self.assertTrue(first._prepare_staging()[0])
        self.assertTrue(second._prepare_staging()[0])
        first.staging_path.write_bytes(b"first-complete")
        second.staging_path.write_bytes(b"second-still-running")

        with patch.object(first, "_validate_media", return_value=(True, "ok")):
            success, _ = first._finalize()

        self.assertTrue(success)
        self.assertEqual(target.read_bytes(), b"first-complete")
        self.assertEqual(second.staging_path.read_bytes(), b"second-still-running")

    def test_cross_device_finalize_copies_then_atomically_replaces(self):
        target = self.root / "movies" / "Movie.mp4"
        job = DownloadJob("https://one", "mp4", target)
        self.assertTrue(job._prepare_staging()[0])
        job.staging_path.write_bytes(b"complete-media")
        real_replace = downloader.os.replace
        calls = []

        def replace(source, destination):
            calls.append((Path(source), Path(destination)))
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "cross-device link")
            return real_replace(source, destination)

        with patch.object(job, "_validate_media", return_value=(True, "ok")), \
                patch("downloader.os.replace", side_effect=replace):
            success, _ = job._finalize()

        self.assertTrue(success)
        self.assertEqual(target.read_bytes(), b"complete-media")
        self.assertEqual(len(calls), 2)
        self.assertFalse(job.staging_dir.exists())

    def test_failed_replace_preserves_existing_target(self):
        target = self.root / "movies" / "Movie.mp4"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"known-good")
        job = DownloadJob("https://one", "mp4", target)
        self.assertTrue(job._prepare_staging()[0])
        job.staging_path.write_bytes(b"replacement")

        with patch.object(job, "_validate_media", return_value=(True, "ok")), \
                patch("downloader.os.replace", side_effect=PermissionError("locked")):
            success, detail = job._finalize()

        self.assertFalse(success)
        self.assertIn("Finalize-Fehler", detail)
        self.assertEqual(target.read_bytes(), b"known-good")

    def test_queue_can_prioritize_and_remove_pending_by_slug(self):
        queue = DownloadQueue(max_parallel=1)
        first = DownloadJob("https://one", "mp4", self.root / "one.mp4", queue_slug="s1e1")
        second = DownloadJob("https://two", "mp4", self.root / "two.mp4", queue_slug="s1e2")
        priority = DownloadJob("https://three", "mp4", self.root / "three.mp4", queue_slug="fallback")
        queue.add(first)
        queue.add(second)
        queue.add_front(priority)

        removed = queue.remove_pending(lambda job: job.queue_slug == "s1e2")

        self.assertEqual(removed, [second])
        self.assertEqual(queue.pending_count(), 2)
        self.assertIs(queue._jobs[0][1], priority)

    def test_cancel_all_returns_and_reaps_active_jobs(self):
        stopped = threading.Event()

        class BlockingJob:
            def start(self):
                thread = threading.Thread(target=stopped.wait, daemon=True)
                thread.start()
                return thread

            def cancel(self):
                stopped.set()

        queue = DownloadQueue(max_parallel=1)
        job = BlockingJob()
        queue.add(job)
        queue.start()
        deadline = time.monotonic() + 2
        while queue.active_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.01)

        cancelled = queue.cancel_all()

        self.assertEqual(cancelled, [job])
        deadline = time.monotonic() + 2
        while queue.active_count() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(queue.active_count(), 0)
        self.assertEqual(queue.pending_count(), 0)


if __name__ == "__main__":
    unittest.main()
