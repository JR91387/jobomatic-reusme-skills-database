import base64
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import paths, shortcuts


class TempHome(unittest.TestCase):
    """A temporary HOME / APPDATA / XDG_DATA_HOME so nothing touches the real ones."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        self.data_dir = Path(tmp.name) / "data"
        self.data_dir.mkdir()
        env = {"HOME": str(self.home), "APPDATA": str(self.home / "AppData" / "Roaming"),
               "USERPROFILE": str(self.home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_DATA_HOME", None)
        os.environ.pop(shortcuts.SKIP_ENV, None)
        self.addCleanup(os.environ.__setitem__, shortcuts.SKIP_ENV, "1")
        refresh = mock.patch.object(shortcuts, "_refresh_menu")
        refresh.start()
        self.addCleanup(refresh.stop)

    def use(self, os_name, installed=True, exe="/opt/py/bin/python3"):
        for p in (mock.patch.object(shortcuts, "_os", return_value=os_name),
                  mock.patch.object(paths, "installed", return_value=installed),
                  mock.patch.object(shortcuts.sys, "executable", exe)):
            p.start()
            self.addCleanup(p.stop)


class Linux(TempHome):
    def test_real_desktop_file_create_and_remove(self):
        self.use("freedesktop")
        target = shortcuts.add_shortcut(self.data_dir)
        expected = self.home / ".local" / "share" / "applications" / "job-o-matic.desktop"
        self.assertEqual(target, expected)
        text = expected.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]\n", text)
        self.assertIn("Name=Job-o-Matic\n", text)
        self.assertIn("Exec=/opt/py/bin/python3 -m jobomatic.helper --open\n", text)
        self.assertIn("Categories=Office;\n", text)
        icon_line = next(line for line in text.splitlines() if line.startswith("Icon="))
        self.assertTrue(Path(icon_line[5:]).is_absolute())
        self.assertTrue(icon_line.endswith("icon-256.png"))
        self.assertEqual(shortcuts.remove_shortcut(self.data_dir), expected)
        self.assertFalse(expected.exists())
        self.assertTrue(json.loads((self.data_dir / "shortcut.json").read_text())["removed"])
        self.assertIsNone(shortcuts.remove_shortcut(self.data_dir))

    def test_respects_xdg_data_home(self):
        self.use("freedesktop")
        os.environ["XDG_DATA_HOME"] = str(self.home / "xdg")
        self.assertEqual(shortcuts.add_shortcut(), self.home / "xdg" / "applications" / "job-o-matic.desktop")

    def test_exec_quoting_for_spaces(self):
        self.use("freedesktop", exe="/opt/my py/bin/python3")
        text = shortcuts.add_shortcut().read_text(encoding="utf-8")
        self.assertIn('Exec="/opt/my py/bin/python3" -m jobomatic.helper --open\n', text)

    def test_zip_uses_bundle_python_and_helper(self):
        self.use("freedesktop", installed=False, exe="/z/Job-o-Matic/python/bin/python3")
        with mock.patch.object(shortcuts, "_install_type", return_value="repo"):
            program, args = shortcuts.launch_command()
        self.assertEqual(program, "/z/Job-o-Matic/python/bin/python3")
        self.assertEqual(args, [str(paths.PKG / "helper.py"), "--open"])

    def test_failure_is_a_note_not_an_exception(self):
        self.use("freedesktop")
        with mock.patch.object(Path, "write_text", side_effect=PermissionError("denied")), \
                mock.patch("builtins.print") as printed:
            self.assertIsNone(shortcuts.add_shortcut())
        self.assertIn("could not add", printed.call_args[0][0])


class Windows(TempHome):
    def test_powershell_command_built_not_run(self):
        self.use("windows", exe=r"C:\Py\python.exe")
        with mock.patch.object(shortcuts.subprocess, "run") as run, \
                mock.patch.object(Path, "exists", return_value=False):
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch("builtins.print"):
                shortcuts.add_shortcut()
        argv = run.call_args[0][0]
        self.assertEqual(argv[:6], ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-EncodedCommand"])
        script = base64.b64decode(argv[6]).decode("utf-16-le")
        lnk = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Job-o-Matic.lnk"
        self.assertIn(f"CreateShortcut('{lnk}')", script)
        self.assertIn("(New-Object -ComObject WScript.Shell)", script)
        self.assertIn(r"$s.TargetPath='C:\Py\python.exe'", script)  # pythonw.exe absent here: python.exe fallback
        self.assertIn("$s.Arguments='-m jobomatic.helper --open'", script)
        self.assertIn("icon.ico,0'", script)
        self.assertTrue(script.endswith("$s.Save()"))

    def test_prefers_pythonw(self):
        self.use("windows", exe=str(self.home / "python.exe"))
        (self.home / "pythonw.exe").write_bytes(b"")
        program, args = shortcuts.launch_command()
        self.assertEqual(program, str(self.home / "pythonw.exe"))
        self.assertEqual(args, ["-m", "jobomatic.helper", "--open"])

    def test_quotes_survive(self):
        script = shortcuts.windows_script(r"C:\Users\O'Neil\x.lnk", r"C:\p\pythonw.exe",
                                          [r"C:\My Apps\helper.py", "--open"], r"C:\p", r"C:\i.ico")
        self.assertIn(r"CreateShortcut('C:\Users\O''Neil\x.lnk')", script)
        self.assertIn(r"""$s.Arguments='"C:\My Apps\helper.py" --open'""", script)


class Mac(TempHome):
    def test_app_bundle(self):
        self.use("mac")
        icons = mock.patch.object(shortcuts, "icon", side_effect=lambda name: ROOT / "assets" / name)
        icons.start()
        self.addCleanup(icons.stop)
        app = shortcuts.add_shortcut()
        self.assertEqual(app, self.home / "Applications" / "Job-o-Matic.app")
        with open(app / "Contents" / "Info.plist", "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["CFBundleIdentifier"], "com.reinitz.jobomatic")
        self.assertEqual(plist["CFBundleName"], "Job-o-Matic")
        self.assertEqual(plist["CFBundleIconFile"], "icon")
        exe = app / "Contents" / "MacOS" / plist["CFBundleExecutable"]
        self.assertEqual(exe.read_text(), "#!/bin/sh\nexec /opt/py/bin/python3 -m jobomatic.helper --open\n")
        self.assertEqual(exe.stat().st_mode & 0o777, 0o755)
        icns = (app / "Contents" / "Resources" / "icon.icns").read_bytes()
        self.assertEqual(icns[:4], b"icns")
        self.assertEqual(shortcuts.remove_shortcut(), app)
        self.assertFalse(app.exists())

    def test_remove_leaves_foreign_app_alone(self):
        self.use("mac")
        other = self.home / "Applications" / "Job-o-Matic.app" / "Contents"
        other.mkdir(parents=True)
        with open(other / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleIdentifier": "com.example.other"}, f)
        self.assertIsNone(shortcuts.remove_shortcut())
        self.assertTrue(other.exists())


class FirstRun(TempHome):
    def test_marker_makes_it_once(self):
        self.use("freedesktop")
        with mock.patch.object(shortcuts, "_install_type", return_value="pip"), mock.patch("builtins.print"):
            first = shortcuts.ensure_first_run(self.data_dir)
            self.assertIsNotNone(first)
            first.unlink()  # the person deleted it: don't bring it back
            self.assertIsNone(shortcuts.ensure_first_run(self.data_dir))
        self.assertFalse(first.exists())
        self.assertTrue(json.loads((self.data_dir / "shortcut.json").read_text())["ok"])

    def test_never_after_remove(self):
        self.use("freedesktop")
        with mock.patch.object(shortcuts, "_install_type", return_value="pip"), mock.patch("builtins.print"):
            shortcuts.add_shortcut(self.data_dir)
            shortcuts.remove_shortcut(self.data_dir)
            self.assertIsNone(shortcuts.ensure_first_run(self.data_dir))

    def test_remade_when_target_moves(self):
        self.use("freedesktop")
        with mock.patch.object(shortcuts, "_install_type", return_value="pip"), mock.patch("builtins.print"):
            shortcuts.ensure_first_run(self.data_dir)
            with mock.patch.object(shortcuts.sys, "executable", "/new/python3"):
                target = shortcuts.ensure_first_run(self.data_dir)
        self.assertIn("Exec=/new/python3 ", target.read_text())

    def test_skips_repo_and_env(self):
        self.use("freedesktop")
        with mock.patch.object(shortcuts, "_install_type", return_value="repo"):
            self.assertIsNone(shortcuts.ensure_first_run(self.data_dir))
        os.environ[shortcuts.SKIP_ENV] = "1"
        with mock.patch.object(shortcuts, "_install_type", return_value="pip"):
            self.assertIsNone(shortcuts.ensure_first_run(self.data_dir))
        self.assertFalse((self.data_dir / "shortcut.json").exists())
        self.assertFalse((self.home / ".local").exists())


class Icns(unittest.TestCase):
    def test_committed_icns_matches_png(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("make_icns", ROOT / "scripts" / "make_icns.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        png = (ROOT / "assets" / "icon-256.png").read_bytes()
        self.assertEqual((ROOT / "assets" / "icon.icns").read_bytes(), mod.icns_from_png(png))


class HelperFlags(TempHome):
    def test_add_and_remove_flags_exit_zero(self):
        from jobomatic import helper

        self.use("freedesktop")
        db = self.data_dir / "jobomatic.db"
        for flag, exists in (("--add-shortcut", True), ("--remove-shortcut", False)):
            with mock.patch.object(sys, "argv", ["job-o-matic", "--db", str(db), flag]), \
                    mock.patch("builtins.print"), self.assertRaises(SystemExit) as cm:
                helper.main()
            self.assertEqual(cm.exception.code, 0)
            self.assertEqual((self.home / ".local/share/applications/job-o-matic.desktop").exists(), exists)
        self.assertFalse(db.exists())  # the flags don't start the app or make a database


if __name__ == "__main__":
    unittest.main()
