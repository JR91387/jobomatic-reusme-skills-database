"""The update mechanism (C5): hardening of the check, the button for pip / uv / pipx and zip,
the launcher swap with rollback, and the single version source of the build."""
import hashlib
import importlib.util
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import helper, store, updates, version
from tests.test_helper import HelperCase

BASE = "http://127.0.0.1:9"  # never contacted: urlopen is replaced below


def load_build():
    spec = importlib.util.spec_from_file_location("build_bundles", ROOT / "scripts" / "build_bundles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_web(pages):
    """urlopen stand-in serving {url: bytes}; records the requests."""
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req.full_url)
        if req.full_url not in pages:
            raise OSError(f"404 {req.full_url}")
        return io.BytesIO(pages[req.full_url])

    return urlopen, seen


class TempDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def patch(self, *args, **kw):
        p = mock.patch.object(*args, **kw)
        p.start()
        self.addCleanup(p.stop)


class CheckHardening(TempDir):
    def setUp(self):
        super().setUp()
        self.patch(updates, "get_version", return_value="1.2.0")
        self.patch(updates, "install_type", return_value="pip")

    def test_corrupt_cache_never_raises(self):
        for bad in ({"checked": "x"}, {"checked": [1]}, {"checked": {"a": 1}}, {"latest": ["1.9"]}, {"url": 5}):
            cache = {"install_type": "pip", "current": "1.2.0", "checked": time.time(), **bad}
            (self.tmp / updates.CACHE).write_text(json.dumps(cache), encoding="utf-8")
            with mock.patch.object(updates, "urlopen", side_effect=OSError("offline")):
                st = updates.check(self.tmp)
            self.assertIn("newer", st, bad)
            self.assertTrue(st["latest"] is None or isinstance(st["latest"], str), bad)
            self.assertEqual(st["url"], updates.DOWNLOAD_URL, bad)

    def test_prerelease_forms(self):
        for v in ("1.3.0rc1", "1.3.0-rc1", "1.3.0-beta", "1.3.0.beta2", "1.3.1.dev0", "1.3.0a1", "v2.0.0-alpha"):
            self.assertTrue(updates.is_prerelease(v), v)
            self.assertFalse(updates.is_newer(v, "1.2.0"), v)
        for v in ("1.3.0", "v1.3.0", "1.10.2"):
            self.assertFalse(updates.is_prerelease(v), v)

    def test_only_github_links(self):
        self.patch(updates, "install_type", return_value="zip")
        for url, expect in (("https://github.com/x/releases/tag/v1.3.0", "https://github.com/x/releases/tag/v1.3.0"),
                            ("javascript:alert(1)", updates.DOWNLOAD_URL),
                            ("https://github.com.evil.example/x", updates.DOWNLOAD_URL),
                            ("http://github.com/x", updates.DOWNLOAD_URL)):
            body = json.dumps({"tag_name": "v1.3.0", "html_url": url}).encode()
            with mock.patch.object(updates, "urlopen", return_value=io.BytesIO(body)):
                st = updates.check(self.tmp, force=True)
            self.assertEqual(st["url"], expect, url)

    def test_env_overrides_are_used(self):
        web, seen = fake_web({f"{BASE}/pypi.json": json.dumps({"info": {"version": "1.4.0"}}).encode()})
        with mock.patch.dict(os.environ, {updates.PYPI_ENV: f"{BASE}/pypi.json"}), \
                mock.patch.object(updates, "urlopen", web):
            st = updates.check(self.tmp)
        self.assertEqual(seen, [f"{BASE}/pypi.json"])
        self.assertEqual(st["latest"], "1.4.0")
        with mock.patch.dict(os.environ, {updates.RELEASES_ENV: f"{BASE}/rel.json"}):
            self.assertEqual(updates.releases_url(), f"{BASE}/rel.json")
            self.assertTrue(updates.trusted(f"{BASE}/a.zip"))
            self.assertFalse(updates.trusted("http://127.0.0.1:10/a.zip"))
        self.assertFalse(updates.trusted(f"{BASE}/a.zip"))


class PackageUpdate(TempDir):
    def setUp(self):
        super().setUp()
        self.db = self.tmp / "jobomatic.db"
        store.new_database(self.db)
        self.patch(updates, "get_version", return_value="1.3.0")

    def run_kind(self, kind, returncode=0, program="/opt/bin/tool"):
        self.patch(updates, "install_type", return_value=kind)
        backups_when_run = []

        def fake_run(argv, **kw):
            backups_when_run.append(sorted(p.name for p in (self.tmp / "backups").glob("*_pre-update.db")))
            return mock.Mock(returncode=returncode, stdout="done\n", stderr="")

        with mock.patch.object(updates, "_find_program", return_value=program), \
                mock.patch.object(updates.subprocess, "run", side_effect=fake_run) as run:
            out = updates.run_update(self.db)
        return out, run, backups_when_run

    def test_each_kind_backs_up_then_runs_its_command(self):
        for kind, argv in (("pip", [sys.executable, "-m", "pip", "install", "--upgrade"]),
                           ("uv-tool", ["/opt/bin/tool", "tool", "install", "--upgrade", "job-o-matic"]),
                           ("pipx", ["/opt/bin/tool", "upgrade", "job-o-matic"])):
            with self.subTest(kind=kind):
                out, run, backups = self.run_kind(kind)
                self.assertEqual(run.call_args[0][0][:len(argv)], argv)
                self.assertIsInstance(run.call_args[0][0], list)
                self.assertNotIn("shell", run.call_args[1])
                self.assertEqual(run.call_args[1]["timeout"], 300)
                self.assertTrue(backups[0], "a backup exists before the command runs")
                self.assertEqual((out["ok"], out["restart"]), (True, "exec"))
                self.assertTrue(out["backup"].endswith("_pre-update.db"))
                self.assertTrue((self.tmp / updates.PENDING).exists())

    def test_failure_keeps_running_version(self):
        out, _, _ = self.run_kind("pipx", returncode=1)
        self.assertFalse(out["ok"])
        self.assertNotIn("restart", out)
        self.assertFalse((self.tmp / updates.PENDING).exists())

    def test_missing_program_shows_the_command(self):
        out, run, _ = self.run_kind("uv-tool", program=None)
        run.assert_not_called()
        self.assertFalse(out["ok"])
        self.assertEqual(out["command"], "uv tool install --upgrade job-o-matic")

    def test_backup_failure_changes_nothing(self):
        self.patch(updates, "install_type", return_value="pip")
        with mock.patch.object(updates.store, "checked_copy", side_effect=OSError("disk full")), \
                mock.patch.object(updates.subprocess, "run") as run:
            out = updates.run_update(self.db)
        run.assert_not_called()
        self.assertFalse(out["ok"])
        self.assertIn("backup", out["message"])

    def test_notice_after_restart_once(self):
        self.patch(updates, "install_type", return_value="pip")
        (self.tmp / updates.PENDING).write_text(json.dumps({"from": "1.3.0", "at": 1000}), encoding="utf-8")
        self.assertEqual(updates.notice(self.tmp, current="1.3.0", now=1001), {})
        n = updates.notice(self.tmp, current="1.3.1", now=1002)
        self.assertEqual(n["updated_to"], "1.3.1")
        self.assertEqual(n["message"], "Updated to 1.3.1. Restart your AI app so it picks up the new MCP server.")
        self.assertEqual(updates.notice(self.tmp, current="1.3.1", now=1003), {})

    def test_notice_rides_on_update_status(self):
        self.patch(updates, "install_type", return_value="pip")
        self.patch(updates, "get_version", return_value="1.3.1")
        (self.tmp / updates.PENDING).write_text(json.dumps({"from": "1.3.0", "at": time.time()}), encoding="utf-8")
        updates.save_settings(self.tmp, check_updates=False)
        self.assertEqual(updates.check(self.tmp)["updated_to"], "1.3.1")


def release_zip(path, files, links=(), modes=None):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100000 | (modes or {}).get(name, 0o644)) << 16
            z.writestr(info, data)
        for name, target in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, target)
    return path.read_bytes()


class ZipUpdate(TempDir):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "Job-o-Matic"
        (self.root / "app" / "src" / "jobomatic").mkdir(parents=True)
        (self.root / "app" / "old.txt").write_text("old")
        (self.root / "python" / "bin").mkdir(parents=True)
        self.db = self.root / "my_data" / "jobomatic.db"
        self.db.parent.mkdir()
        store.new_database(self.db)
        self.patch(updates, "bundle_root", return_value=self.root)
        self.patch(updates, "install_type", return_value="zip")
        self.patch(updates, "platform_name", return_value="linux-x64")
        self.patch(updates, "get_version", return_value="1.3.0")
        env = mock.patch.dict(os.environ, {updates.RELEASES_ENV: f"{BASE}/rel.json"})
        env.start()
        self.addCleanup(env.stop)

    def serve(self, zip_bytes, digest=None, asset_base=BASE, tag="v1.3.1"):
        name = f"Job-o-Matic_v{tag.lstrip('v')}_linux-x64.zip"
        digest = digest or hashlib.sha256(zip_bytes).hexdigest()
        release = {"tag_name": tag, "assets": [
            {"name": name, "browser_download_url": f"{asset_base}/{name}"},
            {"name": "SHA256SUMS", "browser_download_url": f"{asset_base}/SHA256SUMS"}]}
        return fake_web({f"{BASE}/rel.json": json.dumps(release).encode(),
                         f"{asset_base}/{name}": zip_bytes,
                         f"{asset_base}/SHA256SUMS": f"{digest}  {name}\n".encode()})

    def good_zip(self):
        return release_zip(self.tmp / "r.zip", {
            "Job-o-Matic/app/new.txt": "new",
            "Job-o-Matic/python/bin/python3.13": "#!/bin/sh\n",
            "Job-o-Matic/my_data/jobomatic.db": "not yours",
            "Job-o-Matic/job-o-matic.sh": "#!/bin/sh\n",
        }, links=[("Job-o-Matic/python/bin/python3", "python3.13")],
            modes={"Job-o-Matic/python/bin/python3.13": 0o755})

    def db_digest(self):
        return hashlib.sha256(self.db.read_bytes()).hexdigest()

    def leftovers(self):
        return sorted(p.name for p in self.root.iterdir() if p.name.startswith(".update"))

    def test_stages_update_and_keeps_my_data(self):
        before = self.db_digest()
        web, _ = self.serve(self.good_zip())
        with mock.patch.object(updates, "urlopen", web):
            out = updates.run_update(self.db)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["restart"], out["latest"]), ("launcher", "1.3.1"))
        stage = self.root / ".update"
        self.assertEqual((stage / "READY").read_text().strip(), "1.3.1")
        self.assertEqual((stage / "app" / "new.txt").read_text(), "new")
        self.assertEqual(os.readlink(stage / "python" / "bin" / "python3"), "python3.13")
        self.assertTrue(os.stat(stage / "python" / "bin" / "python3.13").st_mode & 0o100)
        self.assertFalse((stage / "my_data").exists())
        self.assertEqual((self.root / "app" / "old.txt").read_text(), "old")
        self.assertEqual(self.db_digest(), before)
        self.assertEqual(len(list((self.db.parent / "backups").glob("*_pre-update.db"))), 1)
        self.assertEqual(self.leftovers(), [".update"])

    def test_hash_mismatch_changes_nothing(self):
        web, _ = self.serve(self.good_zip(), digest="0" * 64)
        with mock.patch.object(updates, "urlopen", web):
            out = updates.run_update(self.db)
        self.assertFalse(out["ok"])
        self.assertIn("checksum", out["message"])
        self.assertEqual(self.leftovers(), [])
        self.assertEqual((self.root / "app" / "old.txt").read_text(), "old")

    def test_download_outside_github_refused(self):
        web, seen = self.serve(self.good_zip(), asset_base="https://evil.example")
        with mock.patch.object(updates, "urlopen", web):
            out = updates.run_update(self.db)
        self.assertFalse(out["ok"])
        self.assertIn("outside GitHub", out["message"])
        self.assertEqual(seen, [f"{BASE}/rel.json"])
        self.assertEqual(self.leftovers(), [])

    def test_unsafe_names_refused(self):
        for files, links in (({"Job-o-Matic/app/../../evil.txt": "x", "Job-o-Matic/python/x": "x"}, ()),
                             ({"Job-o-Matic/app/a": "x", "Job-o-Matic/python/x": "x"},
                              [("Job-o-Matic/python/bin/sneaky", "../../../../etc/passwd")])):
            web, _ = self.serve(release_zip(self.tmp / "bad.zip", files, links))
            with mock.patch.object(updates, "urlopen", web):
                out = updates.run_update(self.db)
            self.assertFalse(out["ok"], files)
            self.assertEqual(self.leftovers(), [])
            self.assertFalse((self.tmp / "evil.txt").exists())

    def test_not_newer_does_nothing(self):
        web, seen = self.serve(self.good_zip(), tag="v1.3.0")
        with mock.patch.object(updates, "urlopen", web):
            out = updates.run_update(self.db)
        self.assertFalse(out["ok"])
        self.assertEqual(seen, [f"{BASE}/rel.json"])

    def test_mark_started_and_failed_notice(self):
        stage = self.root / ".update"
        stage.mkdir()
        (stage / "TRIAL").touch()
        updates.mark_started()
        self.assertFalse(stage.exists())
        stage.mkdir()
        (stage / "FAILED").touch()
        updates.mark_started()  # FAILED stays until the page has said so
        n = updates.notice(self.db.parent, current="1.3.0")
        self.assertTrue(n["update_failed"])
        self.assertFalse(stage.exists())

    def test_relaunch_command(self):
        self.assertIsNone(updates.relaunch_command())
        (self.root / "job-o-matic.sh").write_text("#!/bin/sh\n")
        self.assertEqual(updates.relaunch_command(), ["/bin/sh", str(self.root / "job-o-matic.sh")])


FAKE_PYTHON = """#!/bin/sh
# Stands in for python: logs which app/python ran, fails when app/fail exists,
# otherwise does what the helper's mark_started does.
echo "$(cat app/id) $(cat python/id) $*" >> ran.log
[ -f app/fail ] && exit 3
[ -f .update/TRIAL ] && rm -rf .update
exit 0
"""


@unittest.skipIf(sys.platform == "win32", "runs the POSIX launcher")
class Launcher(TempDir):
    def setUp(self):
        super().setUp()
        self.build = load_build()
        self.root = self.tmp / "Job-o-Matic"
        self.make(self.root, "old")
        (self.root / "my_data").mkdir()
        (self.root / "my_data" / "jobomatic.db").write_bytes(b"precious")
        (self.root / "job-o-matic.sh").write_text(self.build.LAUNCHERS["job-o-matic.sh"])

    def make(self, base, ident, fail=False):
        for folder in ("app", "python/bin"):
            (base / folder).mkdir(parents=True, exist_ok=True)
        (base / "app" / "id").write_text(ident)
        (base / "python" / "id").write_text(ident)
        py = base / "python" / "bin" / "python3"
        py.write_text(FAKE_PYTHON)
        py.chmod(0o755)
        if fail:
            (base / "app" / "fail").touch()

    def stage(self, ident, fail=False, ready=True):
        stage = self.root / ".update"
        self.make(stage, ident, fail)
        if ready:
            (stage / "READY").write_text("1.3.1\n")

    def launch(self, **env):
        r = subprocess.run(["/bin/sh", str(self.root / "job-o-matic.sh")], capture_output=True, text=True,
                           check=False, timeout=60, env={**os.environ, "JOBOMATIC_TRIAL_SECONDS": "10", **env})
        return r, (self.root / "ran.log").read_text().splitlines()

    def ident(self, folder):
        return (self.root / folder / "id").read_text()

    def test_plain_start(self):
        r, ran = self.launch()
        self.assertEqual((r.returncode, ran), (0, ["old old app/src/jobomatic/helper.py --open"]))

    def test_good_update_swaps_and_keeps_prev(self):
        self.stage("new")
        r, ran = self.launch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(ran, ["new new app/src/jobomatic/helper.py --open"])
        self.assertEqual((self.ident("app"), self.ident("python")), ("new", "new"))
        self.assertEqual((self.ident("app.prev"), self.ident("python.prev")), ("old", "old"))
        self.assertFalse((self.root / ".update").exists())
        self.assertEqual((self.root / "my_data" / "jobomatic.db").read_bytes(), b"precious")
        r, ran = self.launch()  # the next start is a plain one
        self.assertEqual(ran[-1].split()[:2], ["new", "new"])

    def test_failed_start_restores_prev(self):
        self.stage("new", fail=True)
        r, ran = self.launch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([line.split()[:2] for line in ran], [["new", "new"], ["old", "old"]])
        self.assertIn("putting the previous version back", r.stderr)
        self.assertEqual((self.ident("app"), self.ident("python")), ("old", "old"))
        self.assertFalse((self.root / "app.prev").exists())
        self.assertTrue((self.root / ".update" / "FAILED").exists())
        self.assertEqual((self.root / "my_data" / "jobomatic.db").read_bytes(), b"precious")

    def test_stale_exit_from_earlier_run_does_not_block_rollback(self):
        # Second update in one session: the helper from the previous trial quits to install the next
        # update, and its launcher subshell leaves a "0" exit file in the newly staged .update/.
        self.stage("new", fail=True)
        for name in ("EXIT", "EXIT.1"):
            (self.root / ".update" / name).write_text("0\n")
        r, ran = self.launch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([line.split()[:2] for line in ran], [["new", "new"], ["old", "old"]])
        self.assertEqual((self.ident("app"), self.ident("python")), ("old", "old"))
        self.assertTrue((self.root / ".update" / "FAILED").exists())

    def test_incomplete_stage_is_dropped(self):
        self.stage("new")
        subprocess.run(["rm", "-rf", str(self.root / ".update" / "python")], check=True)
        _, ran = self.launch()
        self.assertEqual(ran, ["old old app/src/jobomatic/helper.py --open"])
        self.assertTrue((self.root / ".update" / "FAILED").exists())
        self.assertFalse((self.root / "app.prev").exists())

    def test_waits_for_the_old_helper(self):
        old = subprocess.Popen(["sleep", "2"])
        self.addCleanup(old.wait)
        start = time.monotonic()
        self.launch(JOBOMATIC_WAIT_PID=str(old.pid))
        self.assertGreaterEqual(time.monotonic() - start, 1.5)


class LauncherText(unittest.TestCase):
    def setUp(self):
        self.build = load_build()

    def test_names_match_updates(self):
        self.assertEqual(set(self.build.LAUNCHERS), set(updates.LAUNCHERS.values()))

    def test_command_matches_sh(self):
        sh, command = self.build.LAUNCHERS["job-o-matic.sh"], self.build.LAUNCHERS["Job-o-Matic.command"]
        self.assertEqual(sh.split("\n", 3)[3], command.split("\n", 3)[3])
        self.assertIn('cd "$(dirname "$0")"', command)

    def test_bat_has_the_same_steps(self):
        bat = self.build.LAUNCHERS["Job-o-Matic.bat"]
        self.assertNotIn("\r\r", bat)
        self.assertEqual(bat.count("\n"), bat.count("\r\n"))
        for step in ('if not exist ".update\\READY" goto trial', "move app app.prev", "move python python.prev",
                     "move .update\\app app", "move .update\\python python", "type nul > .update\\TRIAL",
                     "$p.HasExited) { exit $p.ExitCode }", "if errorlevel 1 goto restore",
                     "move app.prev app", "move python.prev python", "type nul > .update\\FAILED",
                     "Wait-Process -Id %JOBOMATIC_WAIT_PID%", 'start "" python\\pythonw.exe'):
            self.assertIn(step, bat, step)
        self.assertNotIn("my_data", bat)

    @unittest.skipUnless(Path("/usr/bin/shellcheck").exists(), "shellcheck not installed")
    def test_shellcheck(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("job-o-matic.sh", "Job-o-Matic.command"):
                (Path(d) / name).write_text(self.build.LAUNCHERS[name])
                r = subprocess.run(["shellcheck", "-s", "sh", str(Path(d) / name)], capture_output=True, text=True,
                                   check=False)
                self.assertEqual(r.returncode, 0, r.stdout)


class BuildSources(unittest.TestCase):
    def setUp(self):
        self.build = load_build()

    def test_one_version(self):
        self.assertEqual(self.build.VERSION, version.VERSION)
        with open(ROOT / "pyproject.toml", "rb") as f:
            self.assertEqual(tomllib.load(f)["project"]["version"], version.VERSION)
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(server["version"], version.VERSION)
        self.assertEqual({p["version"] for p in server["packages"]}, {version.VERSION})
        self.assertEqual(self.build.NOTES.name, f"v{version.VERSION}")

    def test_pinned_python_digests(self):
        self.assertEqual(set(self.build.PBS_SHA256), set(self.build.PLATFORMS.values()))
        for digest in self.build.PBS_SHA256.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("SHA256SUMS", self.build.verified_tarballs.__code__.co_consts)

    def test_hash_locked_wheels(self):
        args = self.build.wheel_install_args("x86_64-unknown-linux-gnu", Path("/t"))
        self.assertIn("--require-hashes", args)
        self.assertEqual(Path(args[args.index("-r") + 1]).name, "requirements-bundle.txt")
        locked = (ROOT / "requirements-bundle.txt").read_text(encoding="utf-8")
        blocks = [b for b in locked.replace("\\\n", " ").splitlines() if b and not b.lstrip().startswith("#")]
        self.assertTrue(blocks)
        for line in blocks:
            self.assertIn("--hash=sha256:", line, line)
        for pin in (ROOT / "requirements.txt").read_text(encoding="utf-8").split():
            self.assertIn(pin + " ", locked)

    def test_release_notes_per_version(self):
        self.assertTrue(self.build.WHATS_NEW.exists())
        notes = self.build.release_notes()
        self.assertIn(f"# Job-o-Matic v{version.VERSION}", notes)
        self.assertIn("## What's new", notes)
        self.assertIn("`phonenumbers` 9.0.44", notes)
        self.assertNotIn("{", notes.split("## What's new")[0].replace("{PBS", ""))


class HelperRestart(HelperCase):
    def test_health_names_each_start(self):
        status, resp, payload = self.request("GET", "/health")
        self.assertEqual((status, json.loads(payload)), (200, {"ok": True}))
        boot = resp.getheader("X-JobOMatic-Boot")
        self.assertEqual(boot, self.server.boot)
        other = helper.HelperServer(self.db, port=0, hook=lambda: None, web_dir=self.data_dir)
        self.addCleanup(other.server_close)
        self.assertNotEqual(other.boot, boot)

    def test_update_success_stops_server_for_restart(self):
        reply = {"ok": True, "restart": "exec", "message": "Updated."}
        with mock.patch.object(helper.updates, "run_update", return_value=dict(reply)) as run:
            status, out = self.post("/update", {})
        run.assert_called_once_with(self.server.db_path)
        self.assertEqual((status, out["boot"]), (200, self.server.boot))
        self.assertEqual(self.server.restart, "exec")
        self.thread.join(timeout=10)
        self.assertFalse(self.thread.is_alive(), "serve_forever returns so main() can restart")

    def test_failed_update_keeps_serving(self):
        with mock.patch.object(helper.updates, "run_update", return_value={"ok": False, "message": "no"}):
            status, out = self.post("/update", {})
        self.assertEqual((status, out["ok"]), (200, False))
        self.assertIsNone(self.server.restart)
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_one_update_at_a_time(self):
        self.server.update_lock.acquire()
        self.addCleanup(self.server.update_lock.release)
        with mock.patch.object(helper.updates, "run_update") as run:
            status, _ = self.post("/update", {})
        run.assert_not_called()
        self.assertEqual(status, 409)


class RestartProcess(unittest.TestCase):
    def test_exec_same_command_line(self):
        order = []
        with mock.patch.object(helper.os, "execve", side_effect=lambda *a: order.append("exec")) as execve, \
                mock.patch.object(helper.viewer, "flush_html", side_effect=lambda: order.append("flush")), \
                mock.patch.object(helper.sys, "argv", ["job-o-matic", "--open"]):
            helper.restart("exec", 8766)
        self.assertEqual(order, ["flush", "exec"])
        exe, argv, env = execve.call_args[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv, [sys.executable, str(Path(helper.__file__).resolve()), "--open"])
        self.assertEqual((env[helper.RESTART_ENV], env[helper.PORT_ENV]), ("1", "8766"))

    def test_launcher_waits_for_this_process(self):
        with mock.patch.object(helper.updates, "relaunch_command", return_value=["/bin/sh", "/x/job-o-matic.sh"]), \
                mock.patch.object(helper.updates, "bundle_root", return_value=Path("/x")), \
                mock.patch.object(helper.subprocess, "Popen") as popen:
            helper.restart("launcher", 8765)
        cmd, kw = popen.call_args[0][0], popen.call_args[1]
        self.assertEqual(cmd, ["/bin/sh", "/x/job-o-matic.sh"])
        self.assertEqual(kw["env"][helper.WAIT_ENV], str(os.getpid()))
        self.assertEqual(kw["env"][helper.PORT_ENV], "8765")

    def test_start_server_reuses_port_or_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "jobomatic.db"
            store.new_database(db)
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                free = s.getsockname()[1]
            with mock.patch.dict(os.environ, {helper.PORT_ENV: str(free)}):
                server = helper.start_server(db)
                self.assertNotIn(helper.PORT_ENV, os.environ)
            try:
                self.assertEqual(server.port, free)
                with mock.patch.dict(os.environ, {helper.PORT_ENV: str(free)}):
                    other = helper.start_server(db)  # taken: any other port
                try:
                    self.assertNotEqual(other.port, free)
                finally:
                    other.server_close()
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
