import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from update_checker import (
    UpdateChecker,
    _git_blob_sha,
    detect_local_commit,
    write_build_commit_marker,
)


class UpdateCheckerTests(unittest.TestCase):
    def test_local_commit_is_read_from_git_ref(self):
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git" / "refs" / "heads").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text(
                "ref: refs/heads/main\n", encoding="utf-8",
            )
            (root / ".git" / "refs" / "heads" / "main").write_text(
                commit, encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "APP_COMMIT_SHA": "", "GIT_COMMIT": "", "SOURCE_COMMIT": "",
            }):
                self.assertEqual(detect_local_commit(root), commit)

    def test_build_marker_is_written_without_data_directory(self):
        commit = "9" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"APP_COMMIT_SHA": commit}):
                detected = write_build_commit_marker(root)

            self.assertEqual(detected, commit)
            self.assertEqual(
                (root / ".app_commit_sha").read_text(encoding="utf-8").strip(),
                commit,
            )

    def test_updated_build_marker_overrides_baked_image_revision(self):
        baked = "8" * 40
        installed = "9" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".app_commit_sha").write_text(installed + "\n", encoding="utf-8")
            with patch.dict(os.environ, {"APP_COMMIT_SHA": baked}):
                self.assertEqual(detect_local_commit(root), installed)

    def test_image_build_prefers_git_head_over_stale_runtime_marker(self):
        stale = "1" * 40
        head = "2" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".app_commit_sha").write_text(stale + "\n", encoding="utf-8")
            (root / ".git" / "refs" / "heads").mkdir(parents=True)
            (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (root / ".git" / "refs" / "heads" / "main").write_text(head + "\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "APP_COMMIT_SHA": "", "GIT_COMMIT": "", "SOURCE_COMMIT": "",
            }):
                detected = write_build_commit_marker(root)

            self.assertEqual(detected, head)
            self.assertEqual((root / ".app_commit_sha").read_text(encoding="utf-8").strip(), head)

    def test_identical_revision_is_current(self):
        commit = "b" * 40
        checker = UpdateChecker(app_dir=Path("."), cache_seconds=0)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "sha": commit,
            "html_url": "https://github.com/example/commit/current",
            "commit": {"message": "Aktueller Stand"},
        }
        with (
            patch("update_checker.detect_local_commit", return_value=commit),
            patch("update_checker.requests.get", return_value=response) as get,
        ):
            result = checker.check(force=True)

        self.assertFalse(result["update_available"])
        self.assertEqual(result["comparison"], "identical")
        self.assertEqual(get.call_count, 1)

    def test_newer_main_revision_is_reported(self):
        current = "c" * 40
        latest = "d" * 40
        latest_response = Mock()
        latest_response.raise_for_status.return_value = None
        latest_response.json.return_value = {
            "sha": latest,
            "html_url": "https://github.com/example/commit/latest",
            "commit": {"message": "Neuer Stand\n\nDetails"},
        }
        compare_response = Mock()
        compare_response.raise_for_status.return_value = None
        compare_response.json.return_value = {
            "status": "ahead", "ahead_by": 3, "behind_by": 0,
        }
        checker = UpdateChecker(app_dir=Path("."), cache_seconds=0)
        with (
            patch("update_checker.detect_local_commit", return_value=current),
            patch(
                "update_checker.requests.get",
                side_effect=[latest_response, compare_response],
            ),
        ):
            result = checker.check(force=True)

        self.assertTrue(result["update_available"])
        self.assertEqual(result["ahead_by"], 3)
        self.assertEqual(result["latest_message"], "Neuer Stand")

    def test_missing_local_revision_still_reports_repository(self):
        latest = "e" * 40
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"sha": latest, "commit": {"message": "Main"}}
        checker = UpdateChecker(app_dir=Path("."), cache_seconds=0)
        with (
            patch("update_checker.detect_local_commit", return_value=""),
            patch("update_checker.requests.get", return_value=response),
        ):
            result = checker.check(force=True)

        self.assertIsNone(result["update_available"])
        self.assertEqual(result["latest_sha"], latest)
        self.assertEqual(result["comparison"], "unknown")

    def test_source_tree_identifies_nas_copy_without_git_metadata(self):
        latest = "f" * 40
        tree_sha = "1" * 40
        content = b"print('Royal Downloader')\n"
        latest_response = Mock()
        latest_response.raise_for_status.return_value = None
        latest_response.json.return_value = {
            "sha": latest,
            "commit": {
                "message": "Main",
                "tree": {"sha": tree_sha},
            },
        }
        tree_response = Mock()
        tree_response.raise_for_status.return_value = None
        tree_response.json.return_value = {
            "truncated": False,
            "tree": [{
                "path": "server.py",
                "type": "blob",
                "sha": _git_blob_sha(content),
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_bytes(content)
            data_dir = root / "data"
            with (
                patch.dict(os.environ, {
                    "SERIENDL_DATA_DIR": str(data_dir),
                    "APP_COMMIT_SHA": "",
                    "GIT_COMMIT": "",
                    "SOURCE_COMMIT": "",
                }),
                patch(
                    "update_checker.requests.get",
                    side_effect=[latest_response, tree_response],
                ),
            ):
                checker = UpdateChecker(app_dir=root, cache_seconds=0)
                result = checker.check(force=True)

            self.assertEqual(result["current_sha"], latest)
            self.assertEqual(result["comparison"], "identical")
            self.assertFalse(result["update_available"])
            self.assertEqual(
                (data_dir / "FilmeDownloader" / "installed_commit").read_text(
                    encoding="utf-8",
                ).strip(),
                latest,
            )

    def test_persisted_nas_revision_detects_later_update(self):
        installed = "a" * 40
        latest = "b" * 40
        latest_tree = "2" * 40
        installed_tree = "3" * 40
        old_content = b"old source\n"
        new_content = b"new source\n"

        def response(payload):
            item = Mock()
            item.raise_for_status.return_value = None
            item.json.return_value = payload
            return item

        responses = [
            response({
                "sha": latest,
                "commit": {"message": "Update", "tree": {"sha": latest_tree}},
            }),
            response({
                "truncated": False,
                "tree": [{"path": "server.py", "type": "blob", "sha": _git_blob_sha(new_content)}],
            }),
            response({
                "sha": installed,
                "commit": {"message": "Alt", "tree": {"sha": installed_tree}},
            }),
            response({
                "truncated": False,
                "tree": [{"path": "server.py", "type": "blob", "sha": _git_blob_sha(old_content)}],
            }),
            response({"status": "ahead", "ahead_by": 2, "behind_by": 0}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_bytes(old_content)
            data_dir = root / "data"
            marker = data_dir / "FilmeDownloader" / "installed_commit"
            marker.parent.mkdir(parents=True)
            marker.write_text(installed + "\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {
                    "SERIENDL_DATA_DIR": str(data_dir),
                    "APP_COMMIT_SHA": "",
                    "GIT_COMMIT": "",
                    "SOURCE_COMMIT": "",
                }),
                patch("update_checker.requests.get", side_effect=responses),
            ):
                result = UpdateChecker(app_dir=root, cache_seconds=0).check(force=True)

        self.assertEqual(result["current_sha"], installed)
        self.assertEqual(result["latest_sha"], latest)
        self.assertTrue(result["update_available"])
        self.assertEqual(result["ahead_by"], 2)

    def test_recent_main_revision_identifies_older_nas_copy(self):
        installed = "4" * 40
        latest = "5" * 40
        latest_tree = "6" * 40
        installed_tree = "7" * 40
        old_content = b"old source\n"
        new_content = b"new source\n"

        def response(payload):
            item = Mock()
            item.raise_for_status.return_value = None
            item.json.return_value = payload
            return item

        installed_payload = {
            "sha": installed,
            "commit": {"message": "Alt", "tree": {"sha": installed_tree}},
        }
        responses = [
            response({
                "sha": latest,
                "commit": {"message": "Neu", "tree": {"sha": latest_tree}},
            }),
            response({
                "truncated": False,
                "tree": [{"path": "server.py", "type": "blob", "sha": _git_blob_sha(new_content)}],
            }),
            response([
                {"sha": latest, "commit": {"tree": {"sha": latest_tree}}},
                installed_payload,
            ]),
            response({
                "truncated": False,
                "tree": [{"path": "server.py", "type": "blob", "sha": _git_blob_sha(old_content)}],
            }),
            response({"status": "ahead", "ahead_by": 1, "behind_by": 0}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_bytes(old_content)
            data_dir = root / "missing-data"
            with (
                patch.dict(os.environ, {
                    "SERIENDL_DATA_DIR": str(data_dir),
                    "APP_COMMIT_SHA": "",
                    "GIT_COMMIT": "",
                    "SOURCE_COMMIT": "",
                }),
                patch("update_checker.requests.get", side_effect=responses),
            ):
                result = UpdateChecker(app_dir=root, cache_seconds=0).check(force=True)

            self.assertEqual(result["current_sha"], installed)
            self.assertTrue(result["update_available"])
            self.assertEqual(
                (data_dir / "FilmeDownloader" / "installed_commit").read_text(
                    encoding="utf-8",
                ).strip(),
                installed,
            )

if __name__ == "__main__":
    unittest.main()
