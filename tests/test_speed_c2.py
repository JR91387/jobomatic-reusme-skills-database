"""C2: backup before the day's first write, deferred view-only page, MCP wording, one-connection get_profile."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("JOBOMATIC_DB", str(Path(tempfile.gettempdir()) / "c2_unused" / "jobomatic.db"))
from jobomatic import demo, mcp_server, store, viewer


class BackupBeforeWrite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "my_data" / "jobomatic.db"
        demo.new_demo_database(self.db)

    def headline(self, path):
        c = sqlite3.connect(path)
        try:
            return c.execute("SELECT headline FROM people WHERE status='Active'").fetchone()[0]
        finally:
            c.close()

    def test_first_write_of_the_day_is_backed_up_before_it(self):
        before = self.headline(self.db)
        conn = store.connect(self.db)
        try:
            self.assertFalse(list((self.db.parent / "backups").glob("*.db")))
            store.save_row(conn, "people", {"id": 1, "headline": "Changed today"}, "user")
        finally:
            conn.close()
        (backup,) = (self.db.parent / "backups").glob("jobomatic_2*.db")
        self.assertEqual(self.headline(backup), before)
        self.assertEqual(self.headline(self.db), "Changed today")

    def test_second_write_keeps_the_first_backup(self):
        conn = store.connect(self.db)
        try:
            store.save_row(conn, "people", {"id": 1, "headline": "One"}, "user")
            (backup,) = (self.db.parent / "backups").glob("jobomatic_2*.db")
            stamp = backup.stat().st_mtime_ns
            store.save_row(conn, "people", {"id": 1, "headline": "Two"}, "user")
        finally:
            conn.close()
        self.assertEqual(backup.stat().st_mtime_ns, stamp)

    def test_sql_write_is_backed_up_first(self):
        before = self.headline(self.db)
        conn = store.connect(self.db)
        try:
            store.run_sql(conn, "UPDATE people SET headline='Via SQL', updated_by='user' WHERE id=1")
        finally:
            conn.close()
        (backup,) = (self.db.parent / "backups").glob("jobomatic_2*.db")
        self.assertEqual(self.headline(backup), before)


class DeferredHtml(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "my_data" / "jobomatic.db"
        demo.new_demo_database(self.db)
        self.addCleanup(viewer.flush_html)

    def test_deferred_build_writes_data_now_and_page_on_flush(self):
        html = viewer.build(self.db)  # full build
        stale = html.read_text(encoding="utf-8")
        conn = store.connect(self.db)
        store.save_row(conn, "people", {"id": 1, "headline": "Deferred headline"}, "user")
        conn.close()
        viewer.build(self.db, defer_html=True)
        self.assertIn("window.JOBOMATIC_DB", (self.db.parent / "viewer_data.js").read_text(encoding="utf-8"))
        self.assertEqual(html.read_text(encoding="utf-8"), stale)  # page not rewritten yet
        viewer.flush_html()
        fresh = html.read_text(encoding="utf-8")
        self.assertNotEqual(fresh, stale)
        updated = (self.db.parent / "viewer_data.js").read_text(encoding="utf-8").split('"')[1]
        self.assertIn(updated, fresh)  # the page carries the newest data
        viewer.flush_html()  # nothing pending: no-op

    def test_quiet_timer_writes_the_page(self):
        html = viewer.build(self.db)
        old = viewer.HTML_QUIET
        viewer.HTML_QUIET = 0.05
        self.addCleanup(setattr, viewer, "HTML_QUIET", old)
        viewer.build(self.db, defer_html=True)
        updated = (self.db.parent / "viewer_data.js").read_text(encoding="utf-8").split('"')[1]
        for _ in range(100):
            if updated in html.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        self.assertIn(updated, html.read_text(encoding="utf-8"))

    def test_full_build_clears_pending(self):
        viewer.build(self.db, defer_html=True)
        viewer.build(self.db)
        self.assertFalse(viewer._pending)


class McpWording(unittest.TestCase):
    def test_wording_says_version(self):
        w = mcp_server._wording
        self.assertEqual(w(ValueError("Unknown version (track) 'x'; use one of A")), "Unknown version 'x'; use one of A")
        self.assertEqual(w(sqlite3.IntegrityError("Unknown track: add it under Settings first")),
                         "Unknown version: add it under Settings first")
        self.assertNotIn("track", w(ValueError("Unknown version (track) 'x'")).lower())

    def test_tool_error_text(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "my_data" / "jobomatic.db"
        demo.new_demo_database(db)
        self.addCleanup(setattr, mcp_server, "DB_PATH", mcp_server.DB_PATH)
        mcp_server.DB_PATH = db
        with self.assertRaises(Exception) as cm:
            mcp_server.resume_data("Bogus")
        self.assertIn("Unknown version", str(cm.exception))
        self.assertNotIn("(track)", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
