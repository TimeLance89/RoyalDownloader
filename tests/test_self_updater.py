import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from self_updater import SelfUpdater


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo(f"SerienDownloader-test/{name}")
            info.size = len(content)
            info.mode = 0o644
            bundle.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class SelfUpdaterTests(unittest.TestCase):
    def test_update_replaces_source_and_preserves_runtime_data(self):
        commit = "a" * 40
        requirements = b"requests>=2.32,<3\n"
        payload = _archive({
            "server.py": b"print('new')\n",
            "requirements.txt": requirements,
            "web/app.js": b"console.log('new');\n",
            "update_checker.py": b"# updater\n",
        })
        response = Mock()
        response.headers = {"Content-Length": str(len(payload))}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [payload]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "data").mkdir()
            (root / "downloads").mkdir()
            (root / "server.py").write_text("print('old')\n", encoding="utf-8")
            (root / "requirements.txt").write_bytes(requirements)
            (root / "web" / "app.js").write_text("old\n", encoding="utf-8")
            (root / "data" / "settings.ini").write_text("secret=true\n", encoding="utf-8")
            (root / "downloads" / "movie.mp4").write_bytes(b"movie")
            updater = SelfUpdater("owner/repo", root, persistent_override=True)

            with (
                patch("self_updater.requests.get", return_value=response),
                patch.object(updater, "_repair_nodriver"),
            ):
                updater._install(commit)

            self.assertEqual((root / "server.py").read_text(encoding="utf-8"), "print('new')\n")
            self.assertEqual((root / ".app_commit_sha").read_text(encoding="utf-8").strip(), commit)
            self.assertEqual((root / "data" / "settings.ini").read_text(encoding="utf-8"), "secret=true\n")
            self.assertEqual((root / "downloads" / "movie.mp4").read_bytes(), b"movie")

    def test_update_rejects_path_traversal_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, mode="w:gz") as bundle:
                info = tarfile.TarInfo("../escape.py")
                info.size = 1
                bundle.addfile(info, io.BytesIO(b"x"))
            destination = root / "extract"
            destination.mkdir()
            updater = SelfUpdater("owner/repo", root, persistent_override=True)

            with self.assertRaisesRegex(RuntimeError, "Unsicherer Pfad"):
                updater._extract_archive(archive, destination)

    def test_failed_file_transaction_restores_previous_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            source = root / "source"
            backup = root / "backup"
            (app / "web").mkdir(parents=True)
            (source / "web").mkdir(parents=True)
            backup.mkdir()
            (app / "server.py").write_text("old server\n", encoding="utf-8")
            (app / "web" / "app.js").write_text("old app\n", encoding="utf-8")
            (source / "server.py").write_text("new server\n", encoding="utf-8")
            (source / "web" / "app.js").write_text("new app\n", encoding="utf-8")
            updater = SelfUpdater("owner/repo", app, persistent_override=True)
            atomic_copy = updater._atomic_copy
            failed = False

            def flaky_copy(source_file, destination):
                nonlocal failed
                if source_file == source / "web" / "app.js" and not failed:
                    failed = True
                    raise OSError("disk full")
                atomic_copy(source_file, destination)

            with (
                patch.object(updater, "_atomic_copy", side_effect=flaky_copy),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                updater._apply_source(source, "c" * 40, backup)

            self.assertEqual((app / "server.py").read_text(encoding="utf-8"), "old server\n")
            self.assertEqual((app / "web" / "app.js").read_text(encoding="utf-8"), "old app\n")
            self.assertFalse((app / ".app_commit_sha").exists())

    def test_nonpersistent_container_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            updater = SelfUpdater("owner/repo", Path(tmp), persistent_override=False)

            with self.assertRaisesRegex(RuntimeError, "nicht persistent"):
                updater.start("b" * 40)


if __name__ == "__main__":
    unittest.main()
