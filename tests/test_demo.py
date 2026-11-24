import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, store


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        demo.new_demo_database(self.dir / "demo.db")
        self.conn = store.connect(self.dir / "demo.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def count(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def test_counts(self):
        expected = {
            "people": 1, "links": 3, "employers": 3, "positions": 4, "items": 17, "item_metrics": 17,
            "bullet_variants": 20, "tracks": 2, "skills": 7, "education": 2, "qa": 11, "originals": 2,
        }
        for table, n in expected.items():
            self.assertEqual(self.count(f"SELECT count(*) FROM {table}"), n, table)
        self.assertGreaterEqual(self.count("SELECT count(*) FROM skill_links"), 6)

    def test_originals_extracted(self):
        rows = self.conn.execute("SELECT path, extracted FROM originals").fetchall()
        self.assertEqual({r["extracted"] for r in rows}, {"Done"})
        for r in rows:
            text = (self.dir / (r["path"] + ".txt")).read_text(encoding="utf-8")
            self.assertTrue(text.strip(), r["path"])
        self.assertEqual(self.count("SELECT count(*) FROM item_originals"), 3)
        self.assertEqual(self.count("SELECT count(*) FROM items WHERE kind = 'Achievement'"), 12)

    def test_qa(self):
        self.assertEqual(self.count("SELECT count(*) FROM qa WHERE status = 'Verified' AND answer IS NOT NULL"), 5)
        self.assertEqual(self.count("SELECT count(*) FROM qa WHERE person_id IS NOT 1"), 0)
        self.assertEqual(self.count("SELECT count(*) FROM qa WHERE seeded = 0"), 1)
        self.assertEqual(self.count("SELECT count(*) FROM qa WHERE seeded = 1"), 10)

    def test_audit_actors_are_not_people(self):
        self.assertEqual(self.count("SELECT count(*) FROM audit WHERE actor NOT IN ('app','user')"), 0)


if __name__ == "__main__":
    unittest.main()
