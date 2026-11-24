import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, store

LENGTH_ORDER = {"Short": 1, "Long": 2, None: 3}


class DemoCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        demo.new_demo_database(Path(tmp.name) / "demo.db")
        self.conn = store.connect(Path(tmp.name) / "demo.db")
        self.addCleanup(self.conn.close)

    def resume(self, track):
        return json.loads(self.conn.execute("SELECT resume FROM resume_json WHERE track = ?", (track,)).fetchone()[0])

    def hits(self, text):
        return [(h["source_table"], h["source_id"]) for h in store.search(self.conn, text, 50)]


class TestResumeJson(DemoCase):
    def positions(self, doc):
        return [(m["name"], p) for m in doc["employers"] for p in m["positions"]]

    def test_shape_both_tracks(self):
        self.assertEqual({r[0] for r in self.conn.execute("SELECT track FROM resume_json")}, {"Original", "Leadership"})
        # printed lines per position: Brightwater, Lantern Row (Scheduler, Assistant), Cobblestone; Original's two Story lines are left out
        for track, counts in (("Original", [4, 4, 0, 2]), ("Leadership", [4, 3, 0, 1])):
            with self.subTest(track=track):
                doc = self.resume(track)
                self.assertEqual(set(doc), {"track", "person", "links", "employers", "skills", "education", "items", "warnings"})
                self.assertEqual(doc["person"]["name"], "Odalys Brannigan-Voss")
                self.assertEqual([m["name"] for m in doc["employers"]],
                                 ["Brightwater Appliance Co.", "Lantern Row Logistics", "Cobblestone Print & Pack"])
                self.assertEqual([[p["title"] for p in m["positions"]] for m in doc["employers"]],
                                 [["Operations Coordinator"], ["Dispatch Scheduler", "Dispatch Assistant"], ["Production Assistant"]])
                self.assertEqual([len(p["lines"]) for _, p in self.positions(doc)], counts)
                for _, pos in self.positions(doc):
                    keys = [(line["status"] != "Verified", LENGTH_ORDER[line["length"]], line["id"]) for line in pos["lines"]]
                    self.assertEqual(keys, sorted(keys))
                line = doc["employers"][0]["positions"][0]["lines"][0]
                self.assertEqual(set(line), {"id", "wording", "length", "angle", "status", "item"})
                self.assertEqual(set(line["item"]), {"id", "kind", "title", "detail", "metrics"})
                self.assertEqual(set(line["item"]["metrics"][0]), {"id", "label", "value", "unit", "as_of"})
                self.assertEqual(len(doc["skills"]), 7)
                self.assertEqual([e["year"] for e in doc["education"]], ["2020", "2016"])
                self.assertEqual(len(doc["links"]), 3)  # LinkedIn, website, portfolio
                # the person's own items (not Responsibility/Achievement), newest first: Award, Review, Project, unattached Volunteer
                self.assertEqual([(i["id"], i["kind"]) for i in doc["items"]],
                                 [(14, "Award"), (13, "Review"), (15, "Project"), (17, "Volunteer")])
                self.assertIsNone(doc["items"][-1]["position_id"])

    def test_items_without_lines_and_metrics(self):
        orig, lead = self.resume("Original"), self.resume("Leadership")
        without = lambda doc: [[a["id"] for a in p["items_without_lines"]] for _, p in self.positions(doc)]
        self.assertEqual(without(orig), [[5, 13, 14, 15], [], [16], [12]])  # 5 and 12 have only Story lines
        self.assertEqual(without(lead), [[2, 13, 14, 15], [7], [16], [10, 11]])
        three = orig["employers"][0]["positions"][0]["lines"][2]["item"]  # item 4 carries two metrics
        self.assertEqual((three["id"], [m["value"] for m in three["metrics"]]), (4, ["9 hires", "30-day error rate down 40%"]))

    def test_needs_review_line_ranks_after_verified(self):
        scheduler = self.resume("Original")["employers"][1]["positions"][0]["lines"]
        self.assertEqual(scheduler[-1]["status"], "Needs review")
        self.assertEqual(self.resume("Original")["warnings"],
                         ["1 printed row is Needs review (employers, positions, lines, education or items): check them with the person before sending."])

    def test_track_without_lines_still_has_a_row(self):
        self.conn.execute("INSERT INTO tracks (name, updated_by) VALUES ('Empty', 'user')")
        doc = self.resume("Empty")
        self.assertEqual([p["lines"] for _, p in self.positions(doc)], [[], [], [], []])

    def test_deprecated_rows_drop_out(self):
        self.conn.execute("UPDATE items SET status = 'Deprecated', updated_by = 'user' WHERE id = 10")
        self.conn.execute("UPDATE skills SET status = 'Deprecated', updated_by = 'user' WHERE id = 1")
        doc = self.resume("Original")
        self.assertEqual(len(doc["employers"][2]["positions"][0]["lines"]), 1)
        self.assertEqual(len(doc["skills"]), 6)
        self.conn.execute("UPDATE positions SET status = 'Deprecated', updated_by = 'user' WHERE id = 3")
        self.assertEqual([m["name"] for m in self.resume("Original")["employers"]], ["Brightwater Appliance Co.", "Lantern Row Logistics"])

    def test_originals_attach_to_items(self):
        profile = json.loads(self.conn.execute("SELECT profile FROM profile_json").fetchone()[0])
        self.assertEqual({i["id"]: i["original_ids"] for i in profile["items"] if i["original_ids"]}, {1: [1], 4: [1], 13: [1]})
        self.assertEqual((len(profile["employers"]), len(profile["positions"]), len(profile["items"])), (3, 4, 17))
        self.assertEqual(self.conn.execute("SELECT position_id FROM originals ORDER BY id").fetchall()[0][0], 1)


class TestSearch(DemoCase):
    def test_job_description_finds_demo_line(self):
        jd = "Seeking a logistics coordinator who has negotiated carrier contracts and cut freight costs."
        self.assertEqual(self.hits(jd)[0], ("bullet_variants", 14))
        self.assertIn(("items", 3), self.hits(jd)[:3])

    def test_punctuation_is_plain_words(self):
        self.assertIsInstance(self.hits('C++ / 40% "AND" NOT (x) * ^ -'), list)
        self.assertIn(("bullet_variants", 4), self.hits("C++ / 40%"))
        self.assertIn(("item_metrics", 6), self.hits("C++ / 40%"))
        for empty in ("", "  ", "/ - ++ %"):
            with self.subTest(text=empty), self.assertRaises(ValueError):
                store.search(self.conn, empty)

    def test_insert_update_retire_keep_index(self):
        self.conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (1, 'Kubernetes', 'ai')")
        sid = self.conn.execute("SELECT id FROM skills WHERE name = 'Kubernetes'").fetchone()[0]
        self.assertEqual(self.hits("kubernetes"), [("skills", sid)])
        self.conn.execute("UPDATE skills SET name = 'Terraform', updated_by = 'ai' WHERE id = ?", (sid,))
        self.assertEqual(self.hits("kubernetes"), [])
        self.assertEqual(self.hits("terraform"), [("skills", sid)])
        self.conn.execute("UPDATE skills SET status = 'Deprecated', updated_by = 'ai' WHERE id = ?", (sid,))
        self.assertEqual(self.hits("terraform"), [])
        self.conn.execute("UPDATE skills SET status = 'Verified', updated_by = 'ai' WHERE id = ?", (sid,))
        self.assertEqual(self.hits("terraform"), [("skills", sid)])

    def test_new_sources_are_indexed_and_kept_current(self):
        self.conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (1, 'Zephyrine Freight', 'user')")
        eid = self.conn.execute("SELECT id FROM employers WHERE name = 'Zephyrine Freight'").fetchone()[0]
        self.conn.execute("INSERT INTO positions (person_id, employer_id, title, department, updated_by) VALUES (1, ?, 'Yardmaster', 'Quokka Yard', 'user')", (eid,))
        pid = self.conn.execute("SELECT id FROM positions WHERE title = 'Yardmaster'").fetchone()[0]
        self.conn.execute("INSERT INTO items (person_id, position_id, kind, title, updated_by) VALUES (1, ?, 'Project', 'Wombat relocation', 'user')", (pid,))
        iid = self.conn.execute("SELECT id FROM items WHERE title = 'Wombat relocation'").fetchone()[0]
        self.conn.execute("INSERT INTO item_metrics (item_id, label, value, updated_by) VALUES (?, 'Pangolin count', '7777', 'user')", (iid,))
        mid = self.conn.execute("SELECT id FROM item_metrics WHERE value = '7777'").fetchone()[0]
        for word, want in (("zephyrine", ("employers", eid)), ("yardmaster", ("positions", pid)), ("quokka", ("positions", pid)),
                           ("wombat", ("items", iid)), ("pangolin", ("item_metrics", mid)), ("7777", ("item_metrics", mid))):
            with self.subTest(word=word):
                self.assertEqual(self.hits(word), [want])
        self.conn.execute("UPDATE employers SET name = 'Yellowfin Freight', updated_by = 'user' WHERE id = ?", (eid,))
        self.conn.execute("UPDATE item_metrics SET value = '8888', updated_by = 'user' WHERE id = ?", (mid,))
        self.assertEqual((self.hits("zephyrine"), self.hits("7777")), ([], []))
        self.assertEqual((self.hits("yellowfin"), self.hits("8888")), ([("employers", eid)], [("item_metrics", mid)]))
        for table, row, word in (("employers", eid, "yellowfin"), ("positions", pid, "yardmaster"), ("items", iid, "wombat"), ("item_metrics", mid, "8888")):
            self.conn.execute(f"UPDATE {table} SET status = 'Deprecated', updated_by = 'user' WHERE id = ?", (row,))
            self.assertEqual(self.hits(word), [], table)

    def test_one_index_row_per_live_source_row(self):
        counts = dict(self.conn.execute("SELECT source_table, count(*) FROM search_index GROUP BY source_table"))
        self.assertEqual(counts, {"employers": 3, "positions": 4, "items": 17, "item_metrics": 17, "bullet_variants": 20, "skills": 7, "qa": 11})
        self.conn.execute("UPDATE bullet_variants SET angle = 'x', updated_by = 'user'")
        self.conn.execute("UPDATE qa SET notes = 'x', updated_by = 'user'")
        self.conn.execute("UPDATE items SET notes = 'x', updated_by = 'user'")
        self.assertEqual(dict(self.conn.execute("SELECT source_table, count(*) FROM search_index GROUP BY source_table")), counts)
        live = {t: self.conn.execute(f"SELECT count(*) FROM {t} WHERE status <> 'Deprecated'").fetchone()[0] for t in counts}
        self.assertEqual(counts, live)


class TestAiReview(DemoCase):
    def test_ai_insert_is_needs_review_in_every_status_table(self):
        self.conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (1, 'Welding', 'ai')")
        self.conn.execute("INSERT INTO education (person_id, kind, name, updated_by) VALUES (1, 'Course', 'Safety', 'ai')")
        self.conn.execute("INSERT INTO employers (person_id, name, updated_by) VALUES (1, 'X', 'ai')")
        self.conn.execute("INSERT INTO positions (person_id, employer_id, title, updated_by) VALUES (1, 1, 'Y', 'ai')")
        self.conn.execute("INSERT INTO qa (person_id, question, answer, updated_by) VALUES (1, 'Why?', 'Because', 'ai')")
        self.conn.execute("INSERT INTO qa (person_id, question, updated_by) VALUES (1, 'Where?', 'ai')")
        self.conn.execute("INSERT INTO items (person_id, position_id, kind, title, updated_by) VALUES (1, 1, 'Achievement', 'Did a thing', 'ai')")
        for table, name_col, name, want in (("skills", "name", "Welding", "Needs review"), ("education", "name", "Safety", "Needs review"),
                                            ("employers", "name", "X", "Needs review"), ("positions", "title", "Y", "Needs review"),
                                            ("qa", "question", "Why?", "Needs review"), ("qa", "question", "Where?", "Needs answer"),
                                            ("items", "title", "Did a thing", "Needs review")):
            with self.subTest(table=table, row=name):
                got = self.conn.execute(f"SELECT status FROM {table} WHERE {name_col} = ?", (name,)).fetchone()[0]
                self.assertEqual(got, want)

    def test_user_and_explicit_status_are_kept_and_audit_has_both_writes(self):
        self.conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (1, 'Welding', 'user')")
        self.conn.execute("INSERT INTO skills (person_id, name, status, updated_by) VALUES (1, 'Brazing', 'Deprecated', 'ai')")
        self.conn.execute("INSERT INTO skills (person_id, name, updated_by) VALUES (1, 'Rigging', 'ai')")
        status = dict(self.conn.execute("SELECT name, status FROM skills WHERE name IN ('Welding', 'Brazing', 'Rigging')"))
        self.assertEqual(status, {"Welding": "Verified", "Brazing": "Deprecated", "Rigging": "Needs review"})
        sid = self.conn.execute("SELECT id FROM skills WHERE name = 'Rigging'").fetchone()[0]
        ops = [r[0] for r in self.conn.execute("SELECT op FROM audit WHERE table_name = 'skills' AND row_id = ? ORDER BY id", (sid,))]
        self.assertEqual(ops, ["insert", "update"])


class TestSchemaGuide(DemoCase):
    def test_every_object_and_column_described(self):
        guide = {(r[0], r[1]) for r in self.conn.execute("SELECT object, column_name FROM schema_guide")}
        objects = self.conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
            " AND name NOT IN ('search_index_data','search_index_idx','search_index_content','search_index_docsize','search_index_config')"
        ).fetchall()
        missing = []
        for name, kind in objects:
            missing += [(name, None)] if (name, None) not in guide else []
            if kind == "table":
                missing += [(name, c[1]) for c in self.conn.execute(f"PRAGMA table_info({name})") if (name, c[1]) not in guide]
        self.assertEqual(missing, [])
        rules = {r[0] for r in self.conn.execute("SELECT object FROM schema_guide WHERE kind = 'rule'")}
        self.assertLessEqual({"rule:author", "rule:never_delete", "rule:one_person", "rule:version_check",
                              "rule:tracks", "rule:weights"}, rules)

    def test_read_only(self):
        for sql in ("INSERT INTO schema_guide (object, kind, description) VALUES ('x', 'rule', 'y')",
                    "UPDATE schema_guide SET description = 'x'", "DELETE FROM schema_guide"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(sql)


if __name__ == "__main__":
    unittest.main()
