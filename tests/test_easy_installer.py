"""Offline regression and safety tests for Easy Install. No live NAS required."""
import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from installer.core import (
    InstallError, NasConfig, WindowsConfig, SourcePackage,
    _archive_entry, extract_source_zip, generate_setup_token,
    install_nas, key_fingerprint, nas_env, preflight_nas, render_env,
    sha256_file, validate_nas, validate_windows, verify_source_tar, windows_env,
)


class FakeSession:
    def __init__(self, digest):
        self.digest = digest
        self.commands = []
        self.uploads = []

    def exec(self, command, timeout=60, sensitive=False):
        self.commands.append((command, sensitive))
        if "uname -m" in command:
            return "Docker Compose version v2.30.1\nx86_64\n1000\n1000\nFilesystem 1024 512 512 50% /"
        if "df -Pk" in command:
            return "filesystem 100000000 5000000 4000000 20% /volume1"
        if command.startswith("sha256sum"):
            return self.digest
        if "curl -fsS" in command:
            return '{"status":"ok"}'
        return ""

    def put(self, path, remote, mode=0o600):
        self.uploads.append((remote, mode, Path(path).read_bytes()))


class InstallerTests(unittest.TestCase):
    def nas(self, **changes):
        values = dict(host="192.168.178.40", port=22, username="normaluser",
                      project_path="/volume1/docker/royal-easy", movies_path="/volume1/Filme",
                      series_path="/volume1/Serien", password="example-password")
        values.update(changes)
        return NasConfig(**values)

    def test_nas_input_validation_blocks_exploit_paths(self):
        validate_nas(self.nas())
        for bad in ("/", "/volume1/../etc", "/volume1/what\nrm -rf /", "/volume1/$HOME",
                    "/volume1/path#x", "/volume1//double", "/volume1/docker/royal-easy/media"):
            with self.subTest(bad=bad), self.assertRaises(InstallError):
                validate_nas(self.nas(movies_path=bad))
        with self.assertRaises(InstallError):
            validate_nas(self.nas(project_path="/volume1/Filme"))
        with self.assertRaises(InstallError):
            validate_nas(self.nas(host="NAS.local;touch /tmp/x"))
        with self.assertRaises(InstallError):
            validate_nas(self.nas(password="", private_key_path=""))

    def test_cannot_install_inside_existing_windows_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            folder=base/"royal"
            folder.mkdir()
            (folder/"keep.txt").write_text("keep")
            cfg=WindowsConfig(folder,base/"movies",base/"series")
            with self.assertRaises(InstallError):
                validate_windows(cfg)
            self.assertEqual((folder/"keep.txt").read_text(),"keep")

    def test_zip_slip_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for filename in ("../escape", "/tmp/escape", "C:/evil", "hello\\..\\evil"):
                with self.assertRaises(InstallError):
                    _archive_entry(filename)
            archive=root/"attack.zip"
            with zipfile.ZipFile(archive,"w") as f:
                f.writestr("../outside.txt", "attack")
            with self.assertRaises(InstallError):
                extract_source_zip(archive,root/"dest")
            self.assertFalse((root/"outside.txt").exists())

    def test_tar_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/"attack.tar.gz"
            with tarfile.open(archive,"w:gz") as tar:
                info=tarfile.TarInfo("a-link")
                info.type=tarfile.SYMTYPE
                info.linkname="/etc/passwd"
                tar.addfile(info)
            with self.assertRaises(InstallError):
                verify_source_tar(archive)

    def test_render_env_preserves_defaults_and_rejects_injection(self):
        source="PUID=1000\nMOVIES_HOST_DIR=old\nMY_UNKNOWN=preserved\n"
        generated=render_env(source,{"PUID":"1001","MOVIES_HOST_DIR":"/volume1/Movies"})
        self.assertIn("PUID=1001",generated)
        self.assertIn("MY_UNKNOWN=preserved",generated)
        self.assertNotIn("old",generated)
        for val in ("hello\nBAD=1", "foo$HOME", "x#comment", "y'quote"):
            with self.assertRaises(InstallError):
                render_env(source,{"MOVIES_HOST_DIR":val})

    def test_environment_is_separate_for_desktop_and_nas(self):
        template="ROYAL_DEPLOYMENT_MODE=nas\nHOST=0.0.0.0\nDOWNLOAD_DIR=/movies\nSEERR_ENABLED=true\n"
        cfg=self.nas()
        result=nas_env(template,cfg,"RD-token",1000,1000)
        self.assertIn("MOVIES_HOST_DIR=/volume1/Filme",result)
        self.assertIn("DOWNLOAD_DIR=/movies",result)
        self.assertIn("ROYAL_SETUP_TOKEN=RD-token",result)
        self.assertIn("SEERR_ENABLED=false",result)
        local=windows_env(template,WindowsConfig(Path("C:/Royal"),Path("C:/Videos/Filme"),Path("C:/Videos/Serien")),"RD-token")
        self.assertIn("ROYAL_DEPLOYMENT_MODE=desktop",local)
        self.assertIn("HOST=127.0.0.1",local)

    def test_setup_tokens_unique(self):
        a,b=generate_setup_token(),generate_setup_token()
        self.assertNotEqual(a,b)
        self.assertTrue(a.startswith("RD-"))

    def test_preflight_is_read_only_and_reports_identity(self):
        session=FakeSession("a"*64)
        data=preflight_nas(self.nas(),session)
        self.assertEqual(data["uid"],1000)
        self.assertEqual(data["architecture"],"x86_64")
        commands="\n".join(cmd for cmd,_ in session.commands)
        self.assertNotIn("chown",commands)
        self.assertNotIn("chmod",commands)
        self.assertNotIn("mkdir",commands)
        self.assertNotIn("compose up",commands)
        self.assertIn("test ! -e",commands)

    def test_nas_install_only_creates_fresh_project_and_hides_token(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/"royal-source.tar.gz"
            with tarfile.open(archive,"w:gz") as tar:
                for name, payload in ((".env.example",b"ROYAL_DEPLOYMENT_MODE=nas\nPUID=1000\n"),
                                      ("docker-compose.yml",b"services:\n  seriendownloader:\n    image: hello\n")):
                    info=tarfile.TarInfo(name)
                    info.size=len(payload)
                    tar.addfile(info,io.BytesIO(payload))
            digest=sha256_file(archive)
            session=FakeSession(digest)
            events=[]
            info=install_nas(self.nas(),session,SourcePackage(archive,digest,"overnight","a"*40),events.append)
            self.assertEqual(info["url"],"http://192.168.178.40:8765")
            self.assertIn("token",info)
            commands="\n".join(cmd for cmd,_ in session.commands)
            self.assertIn("--build seriendownloader",commands)
            self.assertNotIn("chown -R",commands)
            self.assertNotIn("docker compose down",commands)
            self.assertNotIn(info["token"],commands)
            self.assertNotIn(info["token"]," ".join(events))
            self.assertTrue(any(item[0].endswith("/.env") and item[1]==0o600 for item in session.uploads))
            self.assertTrue(any(info["token"].encode() in item[2] for item in session.uploads))


if __name__=="__main__":
    unittest.main()
