import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import store

FIXTURES = Path(__file__).resolve().parent / "fixtures"
COUNTED = ("people", "employers", "positions", "items", "item_metrics", "bullet_variants", "tracks", "skills",
           "skill_links", "education", "settings", "qa", "images", "search_index")


def make_v4(path):
    """A version-4 file built from the v4 schema exactly as 1.1.0 shipped it."""
    conn = sqlite3.connect(path, isolation_level=None)
    for name in ("schema_v4.sql", "schema_guide_v4.sql", "seed_blank_v4.sql"):
        conn.executescript((FIXTURES / name).read_text(encoding="utf-8"))
    conn.execute("PRAGMA journal_mode=WAL")
    people = [
        ("Jane", "Jane Q Public", "(918) 555-0100", "Jane@Example.COM", "https://www.linkedin.com/in/janeqpublic",
         "Authorized to work in the U.S."),
        ("Solo", None, "555-0142", "not an email", "https://www.linkedin.com/in/solo", "Will require H-1B sponsorship"),
        ("Alex Smith", "", None, None, None, "Citizen of Canada"),
        ("Kim Lee", "Kim Lee", "", "", "  ", "Authorized to work in Canada without sponsorship"),
    ]
    for i, row in enumerate(people):  # one Active person per install; the rest are Archived
        conn.execute("INSERT INTO people (name, full_name, phone, email, linkedin, work_authorization, status, updated_by)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, 'user')", row + ("Archived" if i else "Active",))
    conn.execute("INSERT INTO links (person_id, kind, url, updated_by)"
                 " VALUES (1, 'LinkedIn', 'HTTPS://www.LinkedIn.com/in/janeqpublic/', 'user')")
    conn.execute("INSERT INTO links (person_id, kind, url, updated_by) VALUES (1, 'GitHub', 'https://github.com/jqp', 'user')")
    conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (1, 'Acme', 'user')")
    conn.execute("INSERT INTO positions (person_id, employer_id, title, start_date, updated_by)"
                 " VALUES (1, 1, 'Dispatcher', '2019-01', 'user')")
    conn.execute("INSERT INTO items (person_id, position_id, kind, title, updated_by)"
                 " VALUES (1, 1, 'Achievement', 'Cut late loads', 'user')")
    conn.execute("INSERT INTO item_metrics (item_id, label, value, unit, updated_by) VALUES (1, 'late loads', '30', '%', 'user')")
    conn.execute("INSERT INTO bullet_variants (item_id, wording, length, updated_by)"
                 " VALUES (1, 'Cut late loads 30%', 'Short', 'user')")
    for skill in ("Routing", "Excel"):
        conn.execute("INSERT INTO skills (person_id, name, category, updated_by) VALUES (1, ?, 'Skill', 'user')", (skill,))
    conn.execute("INSERT INTO skill_links (skill_id, item_type, item_id, updated_by) VALUES (2, 'item', 1, 'user')")
    conn.execute("INSERT INTO images (person_id, mime, bytes, sha256, image, updated_by)"
                 " VALUES (1, 'image/png', 4, 'abc', x'89504e47', 'user')")
    conn.execute("UPDATE qa SET answer = 'I fix routes.', updated_by = 'user' WHERE id = 1")
    conn.close()


def counts(path, tables=COUNTED + ("links", "audit")):
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


class UpgradeV4(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "jobomatic.db"
        make_v4(self.db)
        self.before = counts(self.db)
        conn = sqlite3.connect(self.db)
        self.audit_before = conn.execute("SELECT * FROM audit ORDER BY id").fetchall()
        conn.close()

    def upgraded(self):
        conn = store.connect(self.db)
        self.addCleanup(conn.close)
        return conn

    def test_backup_version_and_counts(self):
        conn = self.upgraded()
        backups = list((self.dir / "backups").glob("jobomatic_v4_*.db"))
        self.assertEqual(len(backups), 1)
        old = sqlite3.connect(backups[0])
        self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 4)
        old.close()
        self.assertEqual(counts(backups[0]), self.before)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 5)
        after = counts(self.db)
        for table in COUNTED:
            self.assertEqual(after[table], self.before[table], table)
        self.assertEqual(after["links"], self.before["links"] + 1)  # Solo's LinkedIn; Jane's was already there
        self.assertEqual(after["audit"], self.before["audit"] + 1)  # the one moved link, recorded as app
        self.assertEqual([tuple(r) for r in conn.execute("SELECT * FROM audit ORDER BY id LIMIT ?", (len(self.audit_before),))],
                         self.audit_before)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertFalse(list(self.dir.glob("*.upgrade*")))

    def test_names_split(self):
        conn = self.upgraded()
        got = conn.execute("SELECT name, full_name, first_name, last_name FROM people ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in got], [
            ("Jane", "Jane Q Public", "Jane Q", "Public"),
            ("Solo", None, "Solo", ""),
            ("Alex Smith", "", "Alex", "Smith"),
            ("Kim Lee", "Kim Lee", "Kim", "Lee"),
        ])

    def test_linkedin_moved_once(self):
        conn = self.upgraded()
        self.assertNotIn("linkedin", [r[1] for r in conn.execute("PRAGMA table_info(people)")])
        jane = conn.execute("SELECT url FROM links WHERE person_id = 1 AND kind = 'LinkedIn'").fetchall()
        self.assertEqual([r[0] for r in jane], ["HTTPS://www.LinkedIn.com/in/janeqpublic/"])
        solo = conn.execute("SELECT url, status FROM links WHERE person_id = 2").fetchall()
        self.assertEqual([tuple(r) for r in solo], [("https://www.linkedin.com/in/solo", "Active")])
        self.assertEqual(conn.execute("SELECT count(*) FROM links WHERE person_id IN (3, 4)").fetchone()[0], 0)
        doc = json.loads(conn.execute("SELECT resume FROM resume_json WHERE track = 'Original'").fetchone()[0])
        self.assertNotIn("linkedin", doc["person"])
        self.assertIn("LinkedIn", [link["kind"] for link in doc["links"]])
        self.assertEqual(doc["person"]["first_name"], "Jane Q")

    def test_contacts_normalized_where_readable(self):
        conn = self.upgraded()
        got = conn.execute("SELECT phone, email FROM people ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in got], [("+19185550100", "Jane@example.com"), ("555-0142", "not an email"),
                                                    (None, None), ("", "")])  # unreadable old values are kept as typed

    def test_work_auth_mapped_and_text_kept(self):
        conn = self.upgraded()
        got = conn.execute("SELECT work_auth_status, work_auth_country, work_authorization FROM people ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in got], [
            ("Authorized", "United States", "Authorized to work in the U.S."),
            ("Needs sponsorship", None, "Will require H-1B sponsorship"),
            ("Other", None, "Citizen of Canada"),
            ("Authorized", "Canada", "Authorized to work in Canada without sponsorship"),
        ])

    def test_v5_rules_live_after_upgrade(self):
        conn = self.upgraded()
        store.save_row(conn, "skills", {"person_id": 1, "name": "SAP", "category": "Application/Software"}, "user")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM skills WHERE id = 1")
        n = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
        store.save_row(conn, "people", {"id": 1, "headline": "Dispatcher"}, "user")
        self.assertEqual(conn.execute("SELECT count(*) FROM audit").fetchone()[0], n + 1)
        self.assertEqual(store.search(conn, "late loads")[0]["source_table"], "items")
        self.assertTrue(conn.execute("SELECT count(*) FROM schema_guide WHERE column_name = 'first_name'").fetchone()[0])
        self.assertFalse(conn.execute("SELECT count(*) FROM schema_guide WHERE column_name = 'linkedin'").fetchone()[0])

    def test_refused_while_open_elsewhere(self):
        other = sqlite3.connect(self.db)
        other.execute("SELECT count(*) FROM people").fetchone()
        try:
            with self.assertRaisesRegex(RuntimeError, "another program has it open"):
                store.connect(self.db)
        finally:
            other.close()
        check = sqlite3.connect(self.db)
        self.assertEqual(check.execute("PRAGMA user_version").fetchone()[0], 4)
        check.close()
        store.connect(self.db).close()  # works once the other program lets go

    def test_failed_step_leaves_file_and_backup(self):
        real = store.UPGRADES[4]
        store.UPGRADES[4] = lambda path: store._rebuild(path, lambda t, c, r: (c + ["nope"], [list(x) + [1] for x in r]))
        try:
            with self.assertRaisesRegex(RuntimeError, "not changed.*before the upgrade"):
                store.connect(self.db)
        finally:
            store.UPGRADES[4] = real
        self.assertEqual(counts(self.db), self.before)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
        conn.close()
        self.assertFalse(list(self.dir.glob("*.upgrade*")))
        self.assertEqual(len(list((self.dir / "backups").glob("jobomatic_v4_*.db"))), 1)

    def test_backup_failure_aborts(self):
        (self.dir / "backups").write_text("not a folder")
        with self.assertRaisesRegex(RuntimeError, "backup copy failed.*nothing was changed"):
            store.connect(self.db)
        self.assertEqual(counts(self.db), self.before)

    def test_older_than_4_refused(self):
        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA user_version = 3")
        conn.close()
        with self.assertRaisesRegex(RuntimeError, "not supported"):
            store.connect(self.db)


class WorkAuthText(unittest.TestCase):
    def test_cases(self):
        for text, want in [
            ("Authorized to work in the United States", ("Authorized", "United States")),
            ("authorised to work in the UK", ("Authorized", "UK")),
            ("Authorized to work in US", ("Authorized", "United States")),
            ("US citizen, authorized", ("Authorized", None)),
            ("Not authorized; need sponsorship", ("Needs sponsorship", None)),
            ("Not authorized", ("Other", None)),
            ("Green card holder", ("Other", None)),
            ("", (None, None)),
            (None, (None, None)),
        ]:
            with self.subTest(text=text):
                self.assertEqual(store.work_auth_fields(text), want)


class ContactNormalizing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "t.db"
        store.new_database(db)
        self.conn = store.connect(db)
        self.addCleanup(self.conn.close)
        self.pid = store.save_row(self.conn, "people", {"first_name": "Pat", "last_name": "Doe"}, "user")

    def person(self):
        return store.get_row(self.conn, "people", self.pid)

    def test_phone_formats(self):
        for text, want in [("(555) 123-4567", "+15551234567"), ("555.123.4567", "+15551234567"),
                           ("5551234567", "+15551234567"), ("555-123-4567", "+15551234567"),
                           ("1 555 123 4567", "+15551234567"), ("+44 20 7946 0958", "+442079460958"),
                           ("", ""), (None, None)]:
            with self.subTest(text=text):
                store.save_row(self.conn, "people", {"id": self.pid, "phone": text}, "user")
                self.assertEqual(self.person()["phone"], want)

    def test_phone_rejected(self):
        for text in ("abc", "555-0142", "12", "+44 20"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Phone number not recognized.*country code"):
                    store.save_row(self.conn, "people", {"id": self.pid, "phone": text}, "user")

    def test_email(self):
        store.save_row(self.conn, "people", {"id": self.pid, "email": "  Pat.Doe@Example.COM "}, "user")
        self.assertEqual(self.person()["email"], "Pat.Doe@example.com")
        for text in ("pat", "pat@example", "a@b@example.com", "pat @example.com", "@example.com", "pat@.com"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Email address not recognized"):
                store.save_row(self.conn, "people", {"id": self.pid, "email": text}, "user")

    def test_many_rows_message(self):
        with self.assertRaisesRegex(ValueError, r"rows\[0\]: Phone number not recognized"):
            store.save_rows(self.conn, "people", [{"id": self.pid, "phone": "abc"}], "user")


class PeopleNames(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "t.db"
        store.new_database(db)
        self.conn = store.connect(db)
        self.addCleanup(self.conn.close)

    def names(self, pid):
        row = store.get_row(self.conn, "people", pid)
        return row["name"], row["full_name"], row["first_name"], row["last_name"]

    def test_new_person_needs_both(self):
        for row in ({"name": "Pat"}, {"first_name": "Pat"}, {"first_name": "Pat", "last_name": " "}):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "first_name and last_name"):
                store.save_row(self.conn, "people", row, "user")

    def test_names_follow_first_last(self):
        pid = store.save_row(self.conn, "people", {"first_name": " Jane Q ", "last_name": "Public"}, "user")
        self.assertEqual(self.names(pid), ("Jane Q Public", "Jane Q Public", "Jane Q", "Public"))
        store.save_row(self.conn, "people", {"id": pid, "last_name": "Doe"}, "user")
        self.assertEqual(self.names(pid), ("Jane Q Doe", "Jane Q Doe", "Jane Q", "Doe"))
        store.save_row(self.conn, "people", {"id": pid, "name": "JQ"}, "user")
        store.save_row(self.conn, "people", {"id": pid, "first_name": "Janet"}, "user")
        self.assertEqual(self.names(pid), ("JQ", "Janet Doe", "Janet", "Doe"))  # a chosen short name stays

    def test_name_collision(self):
        store.save_row(self.conn, "people", {"first_name": "Sam", "last_name": "Lee"}, "user")
        with self.assertRaisesRegex(ValueError, "already has the name 'Sam Lee'"):
            store.save_row(self.conn, "people", {"first_name": "Sam", "last_name": "Lee"}, "user")


if __name__ == "__main__":
    unittest.main()
