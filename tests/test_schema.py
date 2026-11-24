import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import db as cli
from jobomatic import store

DB_PY = ROOT / "src" / "db.py"
QUESTIONS = [
    "Tell me about yourself / Walk me through your resume.",
    "What do you know about our company and why do you want to work here?",
    "Why are you leaving your current job and what are you looking for in your next role?",
    "What is your greatest strength and what are your weaknesses?",
    "What motivates you in your professional life?",
    "What are your career goals and where do you see yourself in 5 years?",
    "Tell me about a time you failed or made a mistake. How did you handle it?",
    "Describe a time you had a conflict with a coworker or difficult customer and how you resolved it.",
    "Give an example of when you had to adapt to change, manage stress, or lead a project under pressure.",
    "How do you prioritize tasks, stay organized, and handle remote or hybrid work?",
]


class DbCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "my_data" / "t.db"
        store.new_database(self.path)
        self.conn = store.connect(self.path)
        self.addCleanup(self.conn.close)

    def person(self, by="user"):
        self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Pat', ?)", (by,))
        return self.conn.execute("SELECT id FROM people").fetchone()[0]

    def employer(self, name="E", by="user"):
        return self.conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (1, ?, ?)", (name, by)).lastrowid

    def position(self, employer_id=1, title="T", by="user", **cols):
        names = ", ".join(["person_id", "employer_id", "title", *cols, "updated_by"])
        marks = ", ".join("?" * (4 + len(cols)))
        return self.conn.execute(f"INSERT INTO positions ({names}) VALUES ({marks})", (1, employer_id, title, *cols.values(), by)).lastrowid

    def item(self, title="I", position_id=None, parent_item_id=None, kind="Achievement", by="user", **cols):
        names = ", ".join(["person_id", "position_id", "parent_item_id", "kind", "title", *cols, "updated_by"])
        marks = ", ".join("?" * (6 + len(cols)))
        return self.conn.execute(f"INSERT INTO items ({names}) VALUES ({marks})",
                                 (1, position_id, parent_item_id, kind, title, *cols.values(), by)).lastrowid

    def metric(self, item_id, value, by="user", **cols):
        names = ", ".join(["item_id", "value", *cols, "updated_by"])
        marks = ", ".join("?" * (3 + len(cols)))
        return self.conn.execute(f"INSERT INTO item_metrics ({names}) VALUES ({marks})", (item_id, value, *cols.values(), by)).lastrowid


class TestRules(DbCase):
    def populate(self):
        pid = self.person()
        by = "'ai'"
        for sql in (
            f"INSERT INTO links (person_id, kind, url, updated_by) VALUES ({pid},'Other','u',{by})",
            f"INSERT INTO images (person_id, mime, bytes, sha256, image, updated_by) VALUES ({pid},'image/png',1,'s',x'01',{by})",
            f"INSERT INTO employers (person_id, name, updated_by) VALUES ({pid},'E',{by})",
            f"INSERT INTO positions (person_id, employer_id, title, updated_by) VALUES ({pid},1,'T',{by})",
            f"INSERT INTO originals (person_id, kind, path, sha256, bytes, updated_by) VALUES ({pid},'Resume','originals/a.pdf','s',1,{by})",
            f"INSERT INTO items (person_id, kind, title, updated_by) VALUES ({pid},'Award','T',{by})",
            f"INSERT INTO item_metrics (item_id, value, updated_by) VALUES (1,'3x',{by})",
            f"INSERT INTO item_originals (item_id, original_id, updated_by) VALUES (1,1,{by})",
            f"INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (1,'w',{by})",
            f"INSERT INTO skills (person_id, name, updated_by) VALUES ({pid},'n',{by})",
            f"INSERT INTO skill_links (skill_id, item_type, item_id, updated_by) VALUES (1,'item',1,{by})",
            f"INSERT INTO education (person_id, kind, name, updated_by) VALUES ({pid},'Course','n',{by})",
        ):
            self.conn.execute(sql)

    def test_delete_aborts_on_every_table(self):
        self.populate()
        tables = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'search_index%'")]  # derived index
        self.assertEqual(len(tables), 18)  # 17 data tables plus schema_guide
        for t in tables:
            self.assertGreater(self.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0], 0, t)
            with self.subTest(table=t), self.assertRaisesRegex(sqlite3.IntegrityError, "Do not delete"):
                self.conn.execute(f"DELETE FROM {t}")

    def test_insert_and_update_need_updated_by(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "updated_by is required"):
            self.conn.execute("INSERT INTO people (name) VALUES ('Pat')")
        self.person()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "updated_by is required"):
            self.conn.execute("UPDATE people SET headline='x'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "updated_by is required"):
            self.conn.execute("UPDATE people SET headline='x', updated_by=NULL")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE people SET updated_by='someone'")

    def test_audit_actor_stamp_and_clear(self):
        pid = self.person("user")
        row = self.conn.execute("SELECT updated_by, updated_at FROM people").fetchone()
        self.assertIsNone(row["updated_by"])
        self.assertRegex(row["updated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.conn.execute("UPDATE people SET headline='Cook', updated_by='ai' WHERE id=?", (pid,))
        self.assertIsNone(self.conn.execute("SELECT updated_by FROM people").fetchone()[0])
        rows = self.conn.execute("SELECT * FROM audit WHERE table_name='people' ORDER BY id").fetchall()
        self.assertEqual([(r["op"], r["actor"], r["row_id"]) for r in rows], [("insert", "user", pid), ("update", "ai", pid)])
        self.assertIsNone(rows[0]["old_json"])
        self.assertEqual(json.loads(rows[1]["old_json"])["headline"], None)
        new = json.loads(rows[1]["new_json"])
        self.assertEqual((new["headline"], new["updated_by"]), ("Cook", "ai"))
        self.assertIsNotNone(new["updated_at"])

    def test_audit_actor_each_write_independent(self):
        pid = self.person("app")
        for by in ("ai", "user", "ai"):
            self.conn.execute("UPDATE people SET summary=?, updated_by=? WHERE id=?", (by, by, pid))
        actors = [r[0] for r in self.conn.execute("SELECT actor FROM audit WHERE table_name='people' ORDER BY id")]
        self.assertEqual(actors, ["app", "ai", "user", "ai"])

    def test_explicit_updated_at_is_kept(self):
        self.conn.execute("INSERT INTO people (name, updated_by, updated_at) VALUES ('Pat','user','2020-01-01T00:00:00.000Z')")
        self.assertEqual(self.conn.execute("SELECT updated_at FROM people").fetchone()[0], "2020-01-01T00:00:00.000Z")

    def test_multi_row_update_audits_each_row(self):
        pid = self.person()
        for n in ("a", "b", "c"):
            self.conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (?,?,'ai')", (pid, n))
        self.conn.execute("UPDATE skills SET category='Skill', updated_by='user'")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM skills WHERE updated_by IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM audit WHERE table_name='skills' AND op='update' AND actor='user'").fetchone()[0], 3)

    def test_audit_is_append_only(self):
        self.person()
        for sql in ("UPDATE audit SET actor='ai'", "DELETE FROM audit"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(sql)

    def test_images_blob_audit_and_one_active(self):
        pid = self.person()
        ins = "INSERT INTO images (person_id, mime, bytes, sha256, image, updated_by) VALUES (?, 'image/png', 3, ?, x'010203', 'user')"
        self.conn.execute(ins, (pid, "a"))
        self.assertNotIn("image", json.loads(self.conn.execute("SELECT new_json FROM audit WHERE table_name='images'").fetchone()[0]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(ins, (pid, "b"))

    def test_seed(self):
        rows = self.conn.execute("SELECT * FROM qa ORDER BY sort").fetchall()
        self.assertEqual([r["question"] for r in rows], QUESTIONS)
        self.assertEqual([r["sort"] for r in rows], list(range(1, 11)))
        self.assertTrue(all(r["seeded"] == 1 and r["status"] == "Needs answer" and r["person_id"] is None for r in rows))
        self.assertEqual([r["category"] for r in rows][:3], ["About you", "Motivation", "Motivation"])
        self.assertEqual(self.conn.execute("SELECT group_concat(key||'='||value) FROM settings ORDER BY id").fetchone()[0], "recent_years=10,older_years=15")
        self.assertEqual(self.conn.execute("SELECT name FROM tracks").fetchone()[0], "Original")
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)

    def test_backup_daily(self):
        first = store.backup_daily(self.path)
        self.assertTrue(first.exists())
        self.assertEqual(store.backup_daily(self.path), first)  # one per day
        for day in range(1, 5):
            (first.parent / f"jobomatic_2000-01-0{day}.db").write_bytes(b"")
        store.backup_daily(self.path, keep=2)
        self.assertEqual(len(list(first.parent.glob("jobomatic_*.db"))), 2)
        self.assertTrue(first.exists())

    def test_first_person_claims_seeded_questions(self):
        self.person()
        rows = self.conn.execute("SELECT count(*) FROM qa WHERE person_id IS NULL").fetchone()[0]
        self.assertEqual(rows, 0)

    def test_blank_text_refused(self):
        pid = self.person()
        self.employer()
        self.position()
        self.item()
        self.metric(1, "3x")
        pos = f"INSERT INTO positions (person_id, employer_id, title, updated_by) VALUES ({pid}, 1, %s, 'user')"
        emp = f"INSERT INTO employers (person_id, name, updated_by) VALUES ({pid}, %s, 'user')"
        for sql, msg in (
            ("INSERT INTO people (name, updated_by) VALUES ('  ', 'user')", "Name cannot be empty"),
            (pos % "' '", "Job title cannot be empty"),
            (emp % "''", "Employer cannot be empty"),
            ("UPDATE positions SET title = ' ', updated_by = 'user' WHERE id = 1", "Job title cannot be empty"),
            ("UPDATE employers SET name = '', updated_by = 'user' WHERE id = 1", "Employer cannot be empty"),
            ("UPDATE items SET title = NULL, detail = ' ', updated_by = 'user' WHERE id = 1", "Give the item a title or say what was done"),
            ("UPDATE item_metrics SET value = ' ', updated_by = 'user' WHERE id = 1", "The metric value cannot be empty"),
            (f"INSERT INTO items (person_id, kind, title, updated_by) VALUES ({pid}, 'Award', ' ', 'user')", "Give the item a title or say what was done"),
            (f"INSERT INTO items (person_id, kind, title, detail, updated_by) VALUES ({pid}, 'Award', '', ' ', 'user')", "Give the item a title or say what was done"),
            ("INSERT INTO item_metrics (item_id, value, updated_by) VALUES (1, ' ', 'user')", "The metric value cannot be empty"),
            ("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (1, '', 'user')", "The wording cannot be empty"),
            ("INSERT INTO qa (person_id, question, updated_by) VALUES (1, '   ', 'user')", "The question cannot be empty"),
            ("UPDATE qa SET question = ' ', updated_by = 'user' WHERE id = 1", "The question cannot be empty"),
        ):
            with self.assertRaisesRegex(sqlite3.DatabaseError, msg):
                self.conn.execute(sql)

    def test_dates_are_year_or_month(self):
        pid = self.person()
        self.employer()
        ok = ("2021", "2021-06", None)
        bad = ("Jun 2025", "2021-13", "2021-00", "2021-6", "2021-06-01", "Present", "")
        for table, extra, vals in (
            ("positions", "employer_id, title", "1, 'T'"),
            ("items", "kind, title", "'Award', 'T'"),
            ("education", "kind, name", "'Course', 'N'"),
        ):
            for col in ("start_date", "end_date"):
                for v in ok:
                    self.conn.execute(f"INSERT INTO {table} (person_id, {extra}, {col}, updated_by) VALUES (?, {vals}, ?, 'user')", (pid, v))
                for v in bad:
                    with self.assertRaisesRegex(sqlite3.DatabaseError, "Dates are YYYY or YYYY-MM, like 2021 or 2021-06"):
                        self.conn.execute(f"INSERT INTO {table} (person_id, {extra}, {col}, updated_by) VALUES (?, {vals}, ?, 'user')", (pid, v))
                    with self.assertRaisesRegex(sqlite3.DatabaseError, "Dates are YYYY"):
                        self.conn.execute(f"UPDATE {table} SET {col} = ?, updated_by = 'user' WHERE id = 1", (v,))

    def test_extracted_states(self):
        self.person()
        self.conn.execute("INSERT INTO originals (kind, path, sha256, bytes, updated_by) VALUES ('Other','originals/a.txt','s',1,'app')")
        for state in ("Not yet", "Text read", "Partly", "Done"):
            self.conn.execute("UPDATE originals SET extracted = ?, updated_by = 'ai' WHERE id = 1", (state,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE originals SET extracted = 'Read', updated_by = 'ai' WHERE id = 1")

    def test_insert_or_replace_cannot_delete(self):
        self.person()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT OR REPLACE INTO people (id, name, updated_by) VALUES (1, 'Pat', 'ai')")

    def test_one_active_person(self):
        pid = self.person()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "One person per install"):
            self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Sam','user')")
        self.conn.execute("UPDATE people SET status='Archived', updated_by='user' WHERE id=?", (pid,))
        self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Sam','user')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "One person per install"):
            self.conn.execute("UPDATE people SET status='Active', updated_by='user' WHERE id=?", (pid,))

    def test_tracks(self):
        pid = self.person()
        self.item(by="ai")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Unknown track"):
            self.conn.execute("INSERT INTO bullet_variants (item_id, wording, track, updated_by) VALUES (1,'w','Nope','ai')")
        self.conn.execute("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (1,'w','ai')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Unknown track"):
            self.conn.execute("UPDATE bullet_variants SET track='Nope', updated_by='ai'")
        self.conn.execute("UPDATE tracks SET name='Leadership', updated_by='user'")
        self.assertEqual(self.conn.execute("SELECT track FROM bullet_variants").fetchone()[0], "Leadership")
        last = self.conn.execute("SELECT actor, table_name FROM audit WHERE table_name='bullet_variants' ORDER BY id DESC").fetchone()
        self.assertEqual(tuple(last), ("user", "bullet_variants"))

    def test_views(self):
        pid = self.person()
        for name, order, status in (("B", 2, "Verified"), ("A", 1, "Verified"), ("C", 0, "Deprecated")):
            emp = self.employer(name, "ai")
            self.position(emp, "t", "ai", sort_order=order, status=status)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT employer FROM experience")], ["A", "B"])
        item = self.item("did it", 1, by="ai", detail="Did it")
        self.conn.execute("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (?,'Did it well','ai')", (item,))
        r = self.conn.execute("SELECT item_id, kind, title, detail, person_id, position_id, wording FROM resume_lines").fetchone()
        self.assertEqual(tuple(r), (item, "Achievement", "did it", "Did it", pid, 1, "Did it well"))
        ranked = self.conn.execute("SELECT item_id, position_id, line_rank FROM resume_lines_ranked").fetchone()
        self.assertEqual(tuple(ranked), (item, 1, 1))
        self.conn.execute("UPDATE people SET headline='x', updated_by='user' WHERE id=?", (pid,))
        last = self.conn.execute("SELECT actor FROM last_change WHERE table_name='people' AND row_id=?", (pid,)).fetchone()[0]
        self.assertEqual(last, "user")

    def test_resume_json_lists_items_without_lines(self):
        self.person()
        self.position(self.employer("A", "ai"), "t", "ai")
        for title, status in (("lined", "Verified"), ("bare", "Needs review"), ("gone", "Deprecated")):
            self.item(title, 1, by="ai", status=status)
        self.metric(2, "12%", "ai")
        self.conn.execute("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (1, 'Lined it', 'ai')")
        self.conn.execute("INSERT INTO tracks (name, updated_by) VALUES ('Lead', 'user')")
        docs = {t: json.loads(r) for t, r in self.conn.execute("SELECT track, resume FROM resume_json")}
        position = docs["Original"]["employers"][0]["positions"][0]
        self.assertEqual(position["items_without_lines"],
                         [{"id": 2, "kind": "Achievement", "parent_item_id": None, "title": "bare", "detail": None, "outputs": None,
                           "status": "Needs review",
                           "metrics": [{"id": 1, "label": None, "value": "12%", "unit": None, "as_of": None}]}])
        self.assertEqual([line["item"]["title"] for line in position["lines"]], ["lined"])
        lead = docs["Lead"]["employers"][0]["positions"][0]
        self.assertEqual([a["title"] for a in lead["items_without_lines"]], ["lined", "bare"])

    def test_item_without_a_position(self):
        pid = self.person()
        loose = self.item("Food bank", None, kind="Volunteer", by="user", status="Verified")
        self.assertIsNone(self.conn.execute("SELECT position_id FROM items WHERE id = ?", (loose,)).fetchone()[0])
        self.conn.execute("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (?, 'Sorted donations', 'user')", (loose,))
        self.assertEqual(self.conn.execute("SELECT position_id FROM resume_lines").fetchone()[0], None)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM resume_lines_ranked").fetchone()[0], 1)
        doc = json.loads(self.conn.execute("SELECT resume FROM resume_json WHERE track = 'Original'").fetchone()[0])
        self.assertEqual(doc["employers"], [])  # an item with no position hangs under no job...
        self.assertEqual([(i["id"], i["kind"], i["position_id"]) for i in doc["items"]], [(loose, "Volunteer", None)])  # ...but is listed
        prof = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual([(i["id"], i["employer"], i["job_title"]) for i in prof["items"]], [(loose, None, None)])
        self.assertEqual(self.conn.execute("SELECT person_id FROM items WHERE id = ?", (loose,)).fetchone()[0], pid)

    def test_parent_item_and_loop_refusal(self):
        self.person()
        self.position(self.employer())
        project = self.item("Project", 1, kind="Project")
        child = self.item("Achievement inside", 1, parent_item_id=project)
        grandchild = self.item("Deeper", 1, parent_item_id=child)
        self.assertEqual(self.conn.execute("SELECT parent_item_id FROM items WHERE id = ?", (child,)).fetchone()[0], project)
        prof = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual({i["id"]: i["parent_item_id"] for i in prof["items"]}, {project: None, child: project, grandchild: child})
        for target, parent in ((project, project), (project, child), (project, grandchild), (child, grandchild)):
            with self.subTest(item=target, parent=parent), self.assertRaisesRegex(sqlite3.IntegrityError, "An item cannot sit inside itself"):
                self.conn.execute("UPDATE items SET parent_item_id = ?, updated_by = 'user' WHERE id = ?", (parent, target))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "An item cannot sit inside itself"):
            self.conn.execute("INSERT INTO items (id, person_id, kind, title, parent_item_id, updated_by) VALUES (50, 1, 'Award', 'x', 50, 'user')")
        with self.assertRaises(sqlite3.IntegrityError):  # a parent that does not exist
            self.conn.execute("UPDATE items SET parent_item_id = 99, updated_by = 'user' WHERE id = ?", (child,))
        self.conn.execute("UPDATE items SET parent_item_id = NULL, updated_by = 'user' WHERE id = ?", (child,))  # moving out is fine
        self.conn.execute("UPDATE items SET parent_item_id = ?, updated_by = 'user' WHERE id = ?", (grandchild, project))  # no loop now

    def test_several_metrics_on_one_item(self):
        self.person()
        self.position(self.employer())
        item = self.item("Carrier review", 1)
        self.metric(item, "$86,000", label="Saved per year", unit="USD", sort=2)
        self.metric(item, "6", label="Carriers", sort=1)
        self.metric(item, "40%", label="Errors down", sort=3)
        self.metric(item, "old", label="Dropped", sort=4, status="Deprecated")
        self.conn.execute("INSERT INTO bullet_variants (item_id, wording, updated_by) VALUES (?, 'Reviewed carriers', 'user')", (item,))
        values = lambda ms: [m["value"] for m in ms]
        doc = json.loads(self.conn.execute("SELECT resume FROM resume_json WHERE track = 'Original'").fetchone()[0])
        line = doc["employers"][0]["positions"][0]["lines"][0]
        self.assertEqual(values(line["item"]["metrics"]), ["6", "$86,000", "40%"])  # by sort, retired one left out
        self.assertEqual(line["item"]["metrics"][1], {"id": 1, "label": "Saved per year", "value": "$86,000", "unit": "USD", "as_of": None})
        self.conn.execute("UPDATE bullet_variants SET status = 'Deprecated', updated_by = 'user'")
        doc = json.loads(self.conn.execute("SELECT resume FROM resume_json WHERE track = 'Original'").fetchone()[0])
        self.assertEqual(values(doc["employers"][0]["positions"][0]["items_without_lines"][0]["metrics"]), ["6", "$86,000", "40%"])
        prof = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual(values(prof["items"][0]["metrics"]), ["6", "$86,000", "40%"])
        self.assertEqual(prof["items"][0]["metrics"][1]["status"], "Needs review")  # metrics start unreviewed

    def test_one_original_on_two_items(self):
        self.person()
        self.position(self.employer())
        a, b = self.item("A", 1), self.item("B", 1)
        self.conn.execute("INSERT INTO originals (kind, path, sha256, bytes, updated_by) VALUES ('Review','originals/r.pdf','s',1,'app')")
        for item in (a, b):
            self.conn.execute("INSERT INTO item_originals (item_id, original_id, note, updated_by) VALUES (?, 1, 'quoted', 'user')", (item,))
        with self.assertRaises(sqlite3.IntegrityError):  # the pair is the key
            self.conn.execute("INSERT INTO item_originals (item_id, original_id, updated_by) VALUES (?, 1, 'user')", (a,))
        with self.assertRaises(sqlite3.IntegrityError):  # both ends must exist
            self.conn.execute("INSERT INTO item_originals (item_id, original_id, updated_by) VALUES (?, 99, 'user')", (a,))
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT item_id, original_id, status FROM item_originals ORDER BY item_id")],
                         [(a, 1, "Active"), (b, 1, "Active")])
        prof = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual({i["id"]: i["original_ids"] for i in prof["items"]}, {a: [1], b: [1]})
        self.conn.execute("UPDATE item_originals SET status = 'Deprecated', updated_by = 'user' WHERE item_id = ?", (a,))
        prof = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual({i["id"]: i["original_ids"] for i in prof["items"]}, {a: [], b: [1]})

    def test_item_needs_title_or_detail(self):
        self.person()
        ins = "INSERT INTO items (person_id, kind, title, detail, updated_by) VALUES (1, 'Award', ?, ?, 'user')"
        self.conn.execute(ins, ("Title only", None))
        self.conn.execute(ins, (None, "Detail only"))
        self.conn.execute(ins, ("", "Detail wins over a blank title"))
        for title, detail in ((None, None), ("", ""), ("  ", None), (" ", " ")):
            with self.subTest(title=title, detail=detail), self.assertRaisesRegex(sqlite3.IntegrityError, "Give the item a title or say what was done"):
                self.conn.execute(ins, (title, detail))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Give the item a title or say what was done"):
            self.conn.execute("UPDATE items SET title = NULL, updated_by = 'user' WHERE id = 1")  # 1 has no detail
        self.conn.execute("UPDATE items SET title = NULL, updated_by = 'user' WHERE id = 2")  # 2 keeps its detail
        self.assertEqual(self.conn.execute("SELECT count(*) FROM items").fetchone()[0], 3)
        # the table CHECK is the backstop behind the trigger: it is what a write with triggers bypassed would hit
        sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'items'").fetchone()[0]
        self.assertIn("CHECK (title IS NOT NULL OR detail IS NOT NULL)", sql)

    def test_every_new_table_refuses_delete(self):
        self.person()
        self.position(self.employer())
        item = self.item("A", 1)
        self.metric(item, "3x")
        self.conn.execute("INSERT INTO originals (kind, path, sha256, bytes, updated_by) VALUES ('Other','originals/a.txt','s',1,'app')")
        self.conn.execute("INSERT INTO item_originals (item_id, original_id, updated_by) VALUES (?, 1, 'user')", (item,))
        for table in ("employers", "positions", "items", "item_metrics", "item_originals"):
            with self.subTest(table=table), self.assertRaisesRegex(sqlite3.IntegrityError, "Do not delete"):
                self.conn.execute(f"DELETE FROM {table}")
            with self.subTest(table=table, how="replace"), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM items").fetchone()[0], 1)

    def test_employer_name_unique_ignoring_case(self):
        self.person()
        self.employer("Acme Co.")
        for name in ("Acme Co.", "ACME CO.", "acme co."):
            with self.subTest(name=name), self.assertRaises(sqlite3.IntegrityError):
                self.employer(name)
        self.employer("Acme Co")  # a different name is a different employer
        self.conn.execute("UPDATE people SET status = 'Archived', updated_by = 'user'")
        self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Sam', 'user')")
        self.conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (2, 'acme co.', 'user')")  # unique per person
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE employers SET name = 'ACME CO' , updated_by = 'user' WHERE id = 1")

    def test_ai_employer_and_position_need_review(self):
        self.person()
        ai_emp, user_emp = self.employer("AiCo", "ai"), self.employer("UserCo", "user")
        ai_pos, user_pos = self.position(user_emp, "AI title", "ai"), self.position(user_emp, "User title", "user")
        status = lambda t, i: self.conn.execute(f"SELECT status FROM {t} WHERE id = ?", (i,)).fetchone()[0]
        self.assertEqual((status("employers", ai_emp), status("employers", user_emp)), ("Needs review", "Verified"))
        self.assertEqual((status("positions", ai_pos), status("positions", user_pos)), ("Needs review", "Verified"))
        ops = [r[0] for r in self.conn.execute("SELECT op FROM audit WHERE table_name = 'employers' AND row_id = ? ORDER BY id", (ai_emp,))]
        self.assertEqual(ops, ["insert", "update"])
        e2 = self.conn.execute("INSERT INTO employers (person_id, name, status, updated_by) VALUES (1, 'Gone', 'Deprecated', 'ai')").lastrowid
        self.assertEqual(status("employers", e2), "Deprecated")  # a status the AI chose is kept

    def test_profile_json(self):
        self.assertEqual(self.conn.execute("SELECT count(*) FROM profile_json").fetchone()[0], 0)
        pid = self.person()
        self.conn.execute("UPDATE people SET headline='x', updated_by='user'")
        a, old = self.employer("A", "ai"), self.employer("Old", "ai")
        self.position(a, "t", "ai")
        self.position(old, "t", "ai", status="Deprecated")
        self.conn.execute("UPDATE employers SET status = 'Deprecated', updated_by = 'ai' WHERE id = ?", (old,))
        item = self.item("Did it", 1, by="ai")
        self.metric(item, "3x", "ai")
        self.conn.execute("INSERT INTO skills (person_id, name, status, updated_by) VALUES (?, 'SQL', 'Needs review', 'ai')", (pid,))
        self.conn.execute("INSERT INTO education (person_id, kind, name, updated_by) VALUES (?, 'Course', 'Forklift', 'ai')", (pid,))
        self.item("Star", None, kind="Award", by="ai")
        rows = self.conn.execute("SELECT profile FROM profile_json").fetchall()
        self.assertEqual(len(rows), 1)
        doc = json.loads(rows[0][0])
        self.assertEqual(set(doc), {"person", "links", "employers", "positions", "items", "skills", "education"})
        self.assertEqual(doc["person"]["name"], "Pat")
        self.assertEqual([(e["name"], e["status"]) for e in doc["employers"]], [("A", "Needs review")])
        self.assertEqual([(p["employer"], p["title"], p["status"]) for p in doc["positions"]], [("A", "t", "Needs review")])
        self.assertEqual([(i["title"], i["position_id"], i["employer"], i["job_title"]) for i in doc["items"]],
                         [("Did it", 1, "A", "t"), ("Star", None, None, None)])  # a position's items first, the person's own last
        self.assertEqual([m["value"] for m in doc["items"][0]["metrics"]], ["3x"])
        self.assertEqual(doc["items"][0]["original_ids"], [])
        self.assertEqual([(s["name"], s["status"]) for s in doc["skills"]], [("SQL", "Needs review")])
        self.assertEqual([e["name"] for e in doc["education"]], ["Forklift"])

    def test_foreign_keys_on(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO links (person_id, kind, url, updated_by) VALUES (99,'Other','u','ai')")

    def test_years_order(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fewer than"):
            self.conn.execute("UPDATE settings SET value='20', updated_by='user' WHERE key='recent_years'")


class TestStore(DbCase):
    def test_new_database_refuses_existing(self):
        with self.assertRaises(FileExistsError):
            store.new_database(self.path)

    def test_connect_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            store.connect(self.path.with_name("none.db"))
        self.assertFalse(self.path.with_name("none.db").exists())

    def test_connect_refuses_an_old_database(self):
        self.conn.execute("PRAGMA user_version = 3")
        self.conn.close()
        with self.assertRaises(RuntimeError) as ctx:
            store.connect(self.path)
        self.assertIn("older", str(ctx.exception))
        raw = sqlite3.connect(self.path)  # refused, and left exactly as it was
        self.addCleanup(raw.close)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 3)
        raw.close()

    def test_connection_settings(self):
        q = lambda p: self.conn.execute(f"PRAGMA {p}").fetchone()[0]
        self.assertEqual((q("foreign_keys"), q("journal_mode"), q("busy_timeout")), (1, "wal", 30000))

    def test_read_returns_rows_and_cannot_write(self):
        res = store.run_sql(self.conn, "SELECT id, question FROM qa WHERE sort <= 2 ORDER BY sort;")
        self.assertEqual((res.columns, len(res.rows), res.changes), (["id", "question"], 2, None))
        res = store.run_sql(self.conn, "SELECT * FROM qa WHERE 0")
        self.assertEqual((res.columns[0], res.rows), ("id", []))
        with self.assertRaises(sqlite3.Error):
            store.run_sql(self.conn, "WITH x AS (SELECT 1) INSERT INTO tracks (name, updated_by) VALUES ('T','ai')")
        self.assertEqual(store.run_sql(self.conn, "SELECT count(*) c FROM tracks").rows[0]["c"], 1)
        self.assertEqual(store.run_sql(self.conn, "PRAGMA user_version").rows[0][0], store.SCHEMA_VERSION)

    def test_write_counts_and_is_atomic(self):
        res = store.run_sql(self.conn, "INSERT INTO tracks (name, updated_by) VALUES ('A','ai'); INSERT INTO tracks (name, updated_by) VALUES ('B','ai');")
        self.assertEqual(res.changes, 2)
        with self.assertRaises(sqlite3.IntegrityError):
            store.run_sql(self.conn, "INSERT INTO tracks (name, updated_by) VALUES ('C','ai'); INSERT INTO tracks (name) VALUES ('D');")
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(store.run_sql(self.conn, "SELECT count(*) FROM tracks").rows[0][0], 3)

    def test_select_followed_by_write_is_a_write(self):
        res = store.run_sql(self.conn, "SELECT 1; INSERT INTO tracks (name, updated_by) VALUES ('A','ai')")
        self.assertEqual(res.changes, 1)

    def test_transaction_control_refused(self):
        for sql in ("BEGIN", "COMMIT", "rollback;", "SAVEPOINT x", "UPDATE tracks SET sort=1, updated_by='ai'; COMMIT;", "-- hi\nEND TRANSACTION"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                store.run_sql(self.conn, sql)

    def test_trigger_script_not_mistaken_for_txn_control(self):
        res = store.run_sql(self.conn, "CREATE TABLE z (a); CREATE TRIGGER z_t AFTER INSERT ON z BEGIN SELECT 1; END;")
        self.assertEqual(res.changes, 0)


class TestCli(unittest.TestCase):
    def run_cli(self, *args, ok=True):
        p = subprocess.run([sys.executable, str(DB_PY), *args], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return p

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "x" / "j.db")
            self.assertIn("ok, created", self.run_cli("--db", db, "--init").stdout)
            self.run_cli("--db", db, "--init", ok=False)
            w = self.run_cli("--db", db, "INSERT INTO people (name, updated_by) VALUES ('Pat','user')")
            self.assertEqual(w.stdout.strip(), "ok, 11 changes")  # the person plus the 10 seeded questions it claims
            r = self.run_cli("--db", db, "SELECT id, name, updated_by FROM people")
            self.assertEqual(r.stdout.splitlines(), ["id\tname\tupdated_by", "1\tPat\t"])
            sqlfile = Path(tmp) / "c.sql"
            sqlfile.write_text("UPDATE people SET headline='Cook', updated_by='ai';")
            self.assertEqual(self.run_cli("--db", db, "--file", str(sqlfile)).stdout.strip(), "ok, 1 changes")
            self.assertIn("ai", self.run_cli("--db", db, "SELECT actor FROM audit ORDER BY id DESC LIMIT 1").stdout)
            bad = self.run_cli("--db", db, "UPDATE people SET headline='x'", ok=False)
            self.assertIn("updated_by is required", bad.stderr)
            self.run_cli("--db", db, "COMMIT", ok=False)

    def test_missing_db_is_an_error_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "none.db"
            self.run_cli("--db", str(db), "SELECT 1", ok=False)
            self.assertFalse(db.exists())

    def test_default_path_is_beside_app(self):
        self.assertEqual(cli.DEFAULT_DB, ROOT.parent / "my_data" / "jobomatic.db")


if __name__ == "__main__":
    unittest.main()
