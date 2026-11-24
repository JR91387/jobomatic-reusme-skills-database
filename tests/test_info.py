import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import jobomatic
from jobomatic import info, paths


class VersionTests(unittest.TestCase):
    def test_version_is_set(self):
        self.assertRegex(jobomatic.__version__, r"^\d+\.\d+")

    def test_falls_back_to_pyproject_then_unknown(self):
        from importlib.metadata import PackageNotFoundError
        from jobomatic import version

        repo = Path(jobomatic.__file__).resolve().parents[2]
        expected = next(l for l in (repo / "pyproject.toml").read_text().splitlines() if l.startswith("version")).split('"')[1]
        with mock.patch.object(paths, "installed", return_value=True), \
                mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError):
            self.assertEqual(version.get_version(), expected)
        with mock.patch.object(version, "get_version", return_value=None):
            self.assertEqual(jobomatic.__version__, "0+unknown")


class InfoTests(unittest.TestCase):
    def test_pip_command(self):
        with mock.patch.object(paths, "installed", return_value=True), mock.patch.object(info, "_console_script", return_value="/x/bin/job-o-matic-mcp"):
            data = info.app_info(Path(tempfile.gettempdir()) / "jobomatic.db")
        self.assertEqual(data["install_type"], "pip")
        self.assertEqual(data["mcp"]["command"], "job-o-matic-mcp")
        self.assertEqual(data["mcp"]["display"], "job-o-matic-mcp")
        self.assertEqual(data["mcp"]["command_path"], "/x/bin/job-o-matic-mcp")

    def test_zip_command_is_the_bundled_python(self):
        command, args, _ = info.mcp_command("zip")
        self.assertRegex(command, r"python[/\\](bin[/\\]python3|python\.exe)$")
        self.assertTrue(args[0].endswith("mcp_server.py"))


class ZipLayoutTests(unittest.TestCase):
    def test_zip_command_points_inside_the_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "Job-o-Matic" / "app" / "src" / "jobomatic"
            with mock.patch.object(paths, "PKG", pkg):
                command, args, _ = info.mcp_command("zip")
            bundle = Path(d) / "Job-o-Matic"
            self.assertTrue(command.startswith(str(bundle / "python")))
            self.assertEqual(args, [str(pkg / "mcp_server.py")])
