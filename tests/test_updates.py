import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import paths, updates
from tests.test_helper import HelperCase

DAY = 24 * 3600


def pypi(version):
    return io.BytesIO(json.dumps({"info": {"version": version}}).encode())


def github(tag):
    return io.BytesIO(json.dumps({"tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}"}).encode())


class InstallType(unittest.TestCase):
    def kind(self, prefix, installed=True, env=None):
        with mock.patch.object(paths, "installed", return_value=installed), \
                mock.patch.object(updates.sys, "prefix", prefix), mock.patch.dict(updates.os.environ, env or {}):
            for k in ("UV_TOOL_DIR", "PIPX_HOME"):
                if k not in (env or {}):
                    updates.os.environ.pop(k, None)
            return updates.install_type()

    def test_kinds(self):
        self.assertEqual(self.kind("/home/a/.local/share/uv/tools/job-o-matic"), "uv-tool")
        self.assertEqual(self.kind("/home/a/.local/share/pipx/venvs/job-o-matic"), "pipx")
        self.assertEqual(self.kind("/home/a/.local/pipx/venvs/job-o-matic"), "pipx")
        self.assertEqual(self.kind("/usr"), "pip")
        self.assertEqual(self.kind("/srv/tools/job-o-matic", env={"UV_TOOL_DIR": "/srv/tools"}), "uv-tool")

    def test_repo_checkout(self):
        self.assertEqual(self.kind("/usr", installed=False), "repo")  # this tree: no bundled python/ beside app/

    def test_zip_layout(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "Job-o-Matic" / "app" / "src" / "jobomatic"
            pkg.mkdir(parents=True)
            (Path(d) / "Job-o-Matic" / "python").mkdir()
            with mock.patch.object(paths, "PKG", pkg):
                self.assertEqual(self.kind("/x", installed=False), "zip")


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updates.is_newer("1.10.0", "1.9.3"))
        self.assertTrue(updates.is_newer("v1.2.1", "1.2"))
        self.assertFalse(updates.is_newer("1.2.0", "1.2"))
        self.assertFalse(updates.is_newer("1.1.9", "1.2.0"))
        self.assertFalse(updates.is_newer("1.3.0rc1", "1.2.0"))
        self.assertFalse(updates.is_newer(None, "1.2.0"))
        self.assertFalse(updates.is_newer("1.3.0", None))

    def test_version_found_here(self):
        from jobomatic.version import get_version

        self.assertRegex(get_version() or "", r"^\d+\.\d+")


class Check(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        for p in (mock.patch.object(updates, "get_version", return_value="1.2.0"),
                  mock.patch.object(updates, "install_type", return_value="pip")):
            p.start()
            self.addCleanup(p.stop)

    def test_newer(self):
        with mock.patch.object(updates, "urlopen", return_value=pypi("1.3.0")) as op:
            st = updates.check(self.data_dir)
        self.assertEqual((st["latest"], st["newer"], st["action"], st["enabled"]), ("1.3.0", True, "button", True))
        req = op.call_args[0][0]
        self.assertEqual(req.full_url, updates.PYPI_URL)
        self.assertEqual(req.header_items(), [("User-agent", "job-o-matic/1.2.0")])
        self.assertIsNone(req.data)
        self.assertEqual(op.call_args[1]["timeout"], 3)

    def test_same(self):
        with mock.patch.object(updates, "urlopen", return_value=pypi("1.2.0")):
            st = updates.check(self.data_dir)
        self.assertFalse(st["newer"])

    def test_offline_no_exception(self):
        with mock.patch.object(updates, "urlopen", side_effect=OSError("network down")):
            st = updates.check(self.data_dir)
        self.assertIsNone(st["latest"])
        self.assertFalse(st["newer"])

    def test_disabled_sends_nothing(self):
        updates.save_settings(self.data_dir, check_updates=False)
        with mock.patch.object(updates, "urlopen") as op:
            st = updates.check(self.data_dir)
        op.assert_not_called()
        self.assertFalse(st["enabled"])
        self.assertTrue(updates.load_settings(self.data_dir) == {"check_updates": False})

    def test_cached_within_a_day(self):
        with mock.patch.object(updates, "urlopen", return_value=pypi("1.3.0")) as op:
            updates.check(self.data_dir, now=1000)
            st = updates.check(self.data_dir, now=1000 + DAY - 1)
            self.assertEqual(op.call_count, 1)
            self.assertTrue(st["newer"])
        with mock.patch.object(updates, "urlopen", return_value=pypi("1.4.0")) as op:
            st = updates.check(self.data_dir, now=1000 + DAY + 1)
        self.assertEqual(op.call_count, 1)
        self.assertEqual(st["latest"], "1.4.0")

    def test_zip_asks_github_and_links_download(self):
        with mock.patch.object(updates, "install_type", return_value="zip"), \
                mock.patch.object(updates, "urlopen", return_value=github("v1.3.0")) as op:
            st = updates.check(self.data_dir)
        self.assertEqual(op.call_args[0][0].full_url, updates.GITHUB_API)
        self.assertEqual((st["latest"], st["newer"], st["action"]), ("1.3.0", True, "download"))
        self.assertTrue(st["url"].endswith("/v1.3.0"))

    def test_uv_tool_and_pipx_get_a_command(self):
        for kind, cmd in (("uv-tool", "uv tool install --upgrade job-o-matic"), ("pipx", "pipx upgrade job-o-matic")):
            with mock.patch.object(updates, "install_type", return_value=kind):
                self.assertEqual(updates.action_for(kind), ("command", cmd))
                with mock.patch.object(updates.subprocess, "run") as run:
                    out = updates.run_update()
                run.assert_not_called()
                self.assertEqual(out["command"], cmd)
                self.assertFalse(out["ok"])

    def test_pip_update_runs_pip(self):
        with mock.patch.object(updates.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="Successfully installed job-o-matic-1.3.0\n", stderr="")
            out = updates.run_update()
        argv = run.call_args[0][0]
        self.assertEqual(argv[:5], [sys.executable, "-m", "pip", "install", "--upgrade"])
        self.assertEqual(argv[-1], "job-o-matic")
        self.assertEqual(run.call_args[1]["timeout"], 300)
        self.assertTrue(out["ok"])
        self.assertIn("Restart Job-o-Matic to finish", out["message"])
        self.assertIn("Successfully installed", out["output"])


class Routes(HelperCase):
    def test_update_status(self):
        with mock.patch.object(updates, "urlopen", return_value=pypi("99.0.0")):
            status, _, payload = self.request("GET", "/update-status")
        self.assertEqual(status, 200)
        st = json.loads(payload)
        self.assertEqual(st["latest"], "99.0.0")
        self.assertTrue(st["newer"])
        for key in ("current", "install_type", "action", "command", "url", "enabled"):
            self.assertIn(key, st)

    def test_update_settings(self):
        status, out = self.post("/update-settings", {"check_updates": False})
        self.assertEqual((status, out), (200, {"ok": True, "check_updates": False}))
        with mock.patch.object(updates, "urlopen") as op:
            _, _, payload = self.request("GET", "/update-status")
        op.assert_not_called()
        self.assertFalse(json.loads(payload)["enabled"])
        status, out = self.post("/update-settings", {"check_updates": "yes"})
        self.assertEqual(status, 400)

    def test_update_needs_token(self):
        status, _ = self.post("/update", {}, token=False)
        self.assertEqual(status, 403)
        status, _ = self.post("/update-settings", {"check_updates": True}, token="wrong")
        self.assertEqual(status, 403)

    def test_update_route_on_repo_returns_command(self):
        with mock.patch.object(updates.subprocess, "run") as run:
            status, out = self.post("/update", {})
        run.assert_not_called()  # this checkout is not a pip install
        self.assertEqual(status, 200)
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
