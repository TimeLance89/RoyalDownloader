import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import docker_bootstrap


class DockerBootstrapTests(unittest.TestCase):
    def test_initial_runtime_is_created_from_image_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            runtime = root / "runtime"
            (bundle / "web").mkdir(parents=True)
            (bundle / "server.py").write_text("print('server')\n", encoding="utf-8")
            (bundle / "web" / "app.js").write_text("app\n", encoding="utf-8")

            docker_bootstrap._copy_initial_runtime(bundle, runtime)

            self.assertTrue((runtime / "server.py").is_file())
            self.assertTrue((runtime / "web" / "app.js").is_file())

    def test_changed_runtime_requirements_are_installed_once_per_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            runtime = root / "runtime"
            temp_dir = root / "container-temp"
            bundle.mkdir()
            runtime.mkdir()
            temp_dir.mkdir()
            (bundle / "requirements.txt").write_text("requests==1\n", encoding="utf-8")
            (runtime / "requirements.txt").write_text("requests==2\n", encoding="utf-8")

            with (
                patch("docker_bootstrap.tempfile.gettempdir", return_value=str(temp_dir)),
                patch("docker_bootstrap.subprocess.run") as run,
            ):
                docker_bootstrap._install_runtime_requirements(bundle, runtime)
                docker_bootstrap._install_runtime_requirements(bundle, runtime)

            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
