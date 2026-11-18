"""Where files and data live: the zip/repo layout stays as it was; a pip install uses the user data folder."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobomatic import paths, store


class RepoLayout(unittest.TestCase):
    def test_resources(self):
        self.assertFalse(paths.installed())
        self.assertEqual(paths.resource("db"), ROOT / "src" / "db")
        self.assertEqual(paths.resource("web"), ROOT / "src" / "web")
        self.assertEqual(paths.resource("templates"), ROOT / "templates")
        self.assertEqual(paths.resource("AI_GUIDE.md"), ROOT / "docs" / "AI_GUIDE.md")
        for name in ("db", "web", "templates", "AI_GUIDE.md"):
            self.assertTrue(paths.resource(name).exists(), name)

    def test_data_beside_app(self):
        self.assertEqual(paths.default_db(), ROOT.parent / "my_data" / "jobomatic.db")
        self.assertEqual(paths.view_html_path(ROOT.parent / "my_data"), ROOT.parent / paths.HTML_NAME)

    def test_no_auto_create(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(paths.ensure_db(Path(d) / "x.db"))
            self.assertFalse((Path(d) / "x.db").exists())


class PipInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.patches = [mock.patch.object(paths, "installed", return_value=True),
                        mock.patch.dict(os.environ, {"JOBOMATIC_HOME": str(self.home)})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_user_data_folder(self):
        self.assertEqual(paths.default_db(), self.home / "jobomatic.db")
        self.assertEqual(paths.view_html_path(self.home), self.home / paths.HTML_NAME)

    def test_first_run_creates_blank_db(self):
        db = paths.default_db()
        self.assertTrue(paths.ensure_db(db))
        conn = store.connect(db)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM qa").fetchone()[0], 10)
        finally:
            conn.close()
        self.assertFalse(paths.ensure_db(db))  # second run leaves it alone

    def test_platform_defaults(self):
        with mock.patch.dict(os.environ, {"JOBOMATIC_HOME": ""}):
            with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/x"}):
                self.assertEqual(paths.user_data_dir(), Path("/x/job-o-matic"))
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertEqual(paths.user_data_dir(), Path.home() / "Library" / "Application Support" / "Job-o-Matic")
            with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(os.environ, {"APPDATA": "C:/AppData"}):
                self.assertEqual(paths.user_data_dir(), Path("C:/AppData") / "Job-o-Matic")


if __name__ == "__main__":
    unittest.main()
