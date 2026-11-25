import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import resume, store

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INDEXES = {"positions_employer", "items_position", "items_parent",
           "item_metrics_item", "bullet_variants_item", "item_originals_original",
           "originals_position", "originals_sha256", "skill_links_target"}


def make_old(path, version, skills=0):
    """A file built from the fixture schema of that version, with one person, one line on track 'original'
    (lower case, which v5 accepted and the views then missed) and `skills` extra skills."""
    conn = sqlite3.connect(path, isolation_level=None)
    for name in (f"schema_v{version}.sql", f"schema_guide_v{version}.sql", f"seed_blank_v{version}.sql"):
        conn.executescript((FIXTURES / name).read_text(encoding="utf-8"))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO people (name, full_name, updated_by) VALUES ('Ann Lee', 'Ann Lee', 'user')")
    conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (1, 'Acme', 'user')")
    conn.execute("INSERT INTO positions (person_id, employer_id, title, updated_by) VALUES (1, 1, 'Eng', 'user')")
    conn.execute("INSERT INTO items (person_id, position_id, kind, title, updated_by) VALUES (1, 1, 'Achievement', 'Did X', 'user')")
    conn.execute("INSERT INTO bullet_variants (item_id, wording, length, track, status, updated_by)"
                 " VALUES (1, 'Cut cost 30%', 'Short', 'original', 'Verified', 'user')")
    for i in range(skills):
        conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (1, ?, 'user')", (f"skill{i}",))
    conn.close()


def counts(path):
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                                             " AND name NOT LIKE 'search_index_%' AND name <> 'schema_guide'")]
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def lines(conn, track):
    data = resume.resume_data(conn, track)
    return [line["wording"] for e in data["employers"] for p in e["positions"] for line in p["lines"]]


class UpgradeToV6(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "jobomatic.db"

    def check_upgraded(self, version):
        before = counts(self.db)
        conn = store.connect(self.db)
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        after = counts(self.db)
        for table, n in before.items():
            self.assertEqual(after[table], n + (1 if table == "audit" else 0), table)  # one audited track fix
        backups = list((self.dir / "backups").glob(f"jobomatic_v{version}_*.db"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(counts(backups[0]), before)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertLessEqual(INDEXES, names)
        self.assertEqual([r[0] for r in conn.execute("SELECT track FROM bullet_variants")], ["Original"])
        self.assertEqual(conn.execute("SELECT actor FROM audit ORDER BY id DESC LIMIT 1").fetchone()[0], "app")
        self.assertTrue(conn.execute("SELECT count(*) FROM schema_guide WHERE description LIKE '%stored as tracks spells it%'")
                        .fetchone()[0])
        self.assertEqual(lines(conn, "Original"), ["Cut cost 30%"])
        self.assertFalse([p for p in self.dir.iterdir() if ".upgrade" in p.name or p.name.endswith(".tmp")])
        return conn

    def test_v5_to_v6(self):
        make_old(self.db, 5)
        conn = self.check_upgraded(5)
        n = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
        store.save_row(conn, "people", {"id": 1, "headline": "Engineer"}, "user")  # rules still live
        self.assertEqual(conn.execute("SELECT count(*) FROM audit").fetchone()[0], n + 1)

    def test_v4_to_v6_in_one_start(self):
        make_old(self.db, 4)
        self.check_upgraded(4)

    def test_current_file_is_left_alone(self):
        store.new_database(self.db)
        self.assertIsNone(store.upgrade(self.db, 5))
        self.assertFalse((self.dir / "backups").exists())

    def test_failed_second_step_says_where_the_file_is(self):
        make_old(self.db, 4)
        with mock.patch.dict(store.UPGRADES, {5: mock.Mock(side_effect=RuntimeError("boom"))}), \
                self.assertRaisesRegex(RuntimeError, "from version 5 to 6 failed.*now version 5.*before the upgrade"):
            store.connect(self.db)
        raw = sqlite3.connect(self.db)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 5)
        raw.close()
        store.connect(self.db).close()  # the next start finishes the job
        self.assertEqual(len(list((self.dir / "backups").glob("jobomatic_v5_*.db"))), 1)

    def test_plans_search_the_new_indexes(self):
        store.new_database(self.db)
        conn = store.connect(self.db)
        self.addCleanup(conn.close)
        for sql in store_index_queries():
            with self.subTest(sql=sql):
                plan = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, (1,) * sql.count("?")))
                self.assertIn("SEARCH", plan)
                self.assertNotIn("SCAN", plan)


def store_indexes():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript((store.SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL")]
    finally:
        conn.close()


def store_index_queries():
    """One lookup per kept index, as the app runs it."""
    queries = {
        "positions_employer": "SELECT * FROM positions WHERE employer_id = ?",
        "items_position": "SELECT * FROM items WHERE position_id = ?",
        "items_parent": "SELECT * FROM items WHERE parent_item_id = ?",
        "item_metrics_item": "SELECT * FROM item_metrics WHERE item_id = ?",
        "bullet_variants_item": "SELECT * FROM bullet_variants WHERE item_id = ?",
        "item_originals_original": "SELECT * FROM item_originals WHERE original_id = ?",
        "originals_position": "SELECT * FROM originals WHERE position_id = ?",
        "originals_sha256": "SELECT * FROM originals WHERE sha256 = ?",
        "skill_links_target": "SELECT * FROM skill_links WHERE item_type = ? AND item_id = ?",
    }
    return [q for name, q in queries.items() if name in store_indexes()]


class TrackCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "t.db"
        store.new_database(db)
        self.conn = store.connect(db)
        self.addCleanup(self.conn.close)
        pid = store.save_row(self.conn, "people", {"first_name": "Ann", "last_name": "Lee"}, "user")
        eid = store.save_row(self.conn, "employers", {"person_id": pid, "name": "Acme"}, "user")
        pos = store.save_row(self.conn, "positions", {"person_id": pid, "employer_id": eid, "title": "Eng"}, "user")
        self.item = store.save_row(self.conn, "items", {"person_id": pid, "position_id": pos, "kind": "Achievement",
                                                        "title": "Did X"}, "user")

    def track(self, vid):
        return self.conn.execute("SELECT track FROM bullet_variants WHERE id = ?", (vid,)).fetchone()[0]

    def test_lower_case_track_prints_and_renames(self):
        vid = store.save_row(self.conn, "bullet_variants", {"item_id": self.item, "wording": "Cut cost 30%", "length": "Short",
                                                            "track": "original", "status": "Verified"}, "user")
        self.assertEqual(self.track(vid), "Original")
        self.assertEqual(lines(self.conn, "Original"), ["Cut cost 30%"])
        self.assertIsNone(self.conn.execute("SELECT updated_by FROM bullet_variants WHERE id = ?", (vid,)).fetchone()[0])
        tid = self.conn.execute("SELECT id FROM tracks WHERE name = 'Original'").fetchone()[0]
        store.save_row(self.conn, "tracks", {"id": tid, "name": "Main"}, "user")
        self.assertEqual(self.track(vid), "Main")
        self.assertEqual(lines(self.conn, "Main"), ["Cut cost 30%"])

    def test_update_to_other_case(self):
        vid = store.save_row(self.conn, "bullet_variants", {"item_id": self.item, "wording": "Led a team", "track": "Original"}, "ai")
        store.save_row(self.conn, "tracks", {"name": "Leadership"}, "user")
        store.save_row(self.conn, "bullet_variants", {"id": vid, "track": "LEADERSHIP"}, "ai")
        self.assertEqual(self.track(vid), "Leadership")
        actors = [r[0] for r in self.conn.execute("SELECT actor FROM audit WHERE table_name = 'bullet_variants'"
                                                  " AND row_id = ? ORDER BY id", (vid,))]
        self.assertEqual(actors, ["ai", "ai", "ai"])  # insert, the update, the case fix
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Unknown track"):
            store.save_row(self.conn, "bullet_variants", {"id": vid, "track": "Nope"}, "ai")


class CopySafety(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "jobomatic.db"

    def test_after_copy_runs_with_foreign_keys_before_the_checks(self):
        make_old(self.db, 5)
        store._take_sole_access(self.db)
        before = counts(self.db)
        order = []

        def after_copy(conn):
            order.append(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            conn.execute("INSERT INTO links (person_id, kind, url, updated_by) VALUES (999, 'Other', 'x', 'app')")

        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            store._rebuild(self.db, after_copy=after_copy)
        self.assertEqual(order, [1])
        self.assertEqual(counts(self.db), before)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["jobomatic.db"])

    @unittest.skipIf(sys.platform == "win32", "Windows ends the hold before the swap")
    def test_old_file_takes_no_writes_from_copy_to_swap(self):
        make_old(self.db, 5)
        store._take_sole_access(self.db)
        refused = []

        def try_write(*_):
            other = sqlite3.connect(self.db, timeout=0)
            try:
                other.execute("UPDATE people SET headline = 'raced', updated_by = 'user'")
                other.commit()
            except sqlite3.OperationalError as exc:
                refused.append(str(exc))
            finally:
                other.close()

        def fill(table, cols, rows):
            if table == "people":
                try_write()
            return cols, rows

        store._rebuild(self.db, fill, after_copy=try_write)
        self.assertEqual(refused, ["database is locked"] * 2)

    def test_checked_copy_removes_its_temp_file_when_the_check_raises(self):
        store.new_database(self.db)
        real = sqlite3.connect
        calls = []

        def connect(path, *a, **k):
            calls.append(path)
            if len(calls) == 2:  # the integrity check of the copy
                raise sqlite3.DatabaseError("file is not a database")
            return real(path, *a, **k)

        target = self.dir / "copy.db"
        with mock.patch.object(store.sqlite3, "connect", connect), self.assertRaises(sqlite3.DatabaseError):
            store.checked_copy(self.db, target)
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.startswith("copy")], [])



RACE = """
import sys, time
sys.path.insert(0, sys.argv[1])
from jobomatic import store
db, start, tag, mode = sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]
while time.time() < start:
    pass
try:
    if mode == "new":
        try:
            store.new_database(db)
            print(tag, "made")
        except FileExistsError:
            print(tag, "exists")
    conn = store.connect(db)
    if mode == "upgrade":
        store.save_row(conn, "skills", {"person_id": 1, "name": "raced " + tag}, "user")
    print(tag, "ok", conn.execute("PRAGMA user_version").fetchone()[0])
    conn.close()
except Exception as exc:
    print(tag, "ERR", type(exc).__name__, exc)
"""


class Races(unittest.TestCase):
    """Several programs start at once on the same file (helper + MCP server after an update, or first run)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def race(self, db, mode, n=3):
        start = time.time() + 1.0
        procs = [subprocess.Popen([sys.executable, "-c", RACE, str(ROOT / "src"), str(db), str(start), f"p{i}", mode],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for i in range(n)]
        out = [p.communicate(timeout=120)[0].strip() for p in procs]
        for text in out:
            self.assertNotIn("ERR", text, out)
            self.assertIn("ok 6", text, out)
        return out

    def test_upgrade_race(self):
        for version in (4, 5):
            for rnd in range(3):
                with self.subTest(version=version, round=rnd):
                    db = self.dir / f"v{version}_{rnd}" / "jobomatic.db"
                    db.parent.mkdir()
                    make_old(db, version, skills=3000)
                    self.race(db, "upgrade")
                    conn = store.connect(db)
                    names = {r[0] for r in conn.execute("SELECT name FROM skills")}
                    conn.close()
                    self.assertEqual(len(names), 3003)  # every program's write is there
                    self.assertEqual(len(list((db.parent / "backups").glob("jobomatic_v*.db"))), 1)  # the pre-upgrade copy
                    self.assertFalse([p for p in db.parent.iterdir() if ".upgrade" in p.name or ".new." in p.name])

    def test_first_run_race(self):
        for rnd in range(5):
            with self.subTest(round=rnd):
                db = self.dir / f"r{rnd}" / "jobomatic.db"
                out = self.race(db, "new")
                self.assertEqual(sum("made" in t for t in out), 1, out)
                self.assertEqual(sorted(p.name for p in db.parent.iterdir() if not p.name.endswith(("-wal", "-shm"))),
                                 ["jobomatic.db", "jobomatic.db.lock"])


if __name__ == "__main__":
    unittest.main()
