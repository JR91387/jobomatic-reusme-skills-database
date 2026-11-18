import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, resume, store

NAME = "Odalys Brannigan-Voss"
ORIGINAL_ONLY = "Tracked 120 print jobs a week from quote to delivery."


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        demo.new_demo_database(self.dir / "demo.db")
        self.conn = store.connect(self.dir / "demo.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def build(self, template, track="Original"):
        path = resume.build_resume(self.conn, self.dir, template, track)
        return path, path.read_text(encoding="utf-8")

    def test_all_templates_render(self):
        for template in resume.TEMPLATES:
            for track in ("Original", "Leadership"):
                path, html = self.build(template, track)
                self.assertEqual(path.parent, self.dir / "resumes")
                self.assertRegex(path.name, rf"^\d{{4}}-\d\d-\d\d_{template}_{track}_\d{{6}}(_\d+)?\.html$")
                self.assertIsNone(re.search(r"\$[a-z_]+", html), template)
                self.assertIn(NAME, html)
            path, html = self.build(template)
            self.assertIn(ORIGINAL_ONLY, html)
            self.assertIn("Brightwater Appliance Co.", html)
            self.assertIn("Mar 2023 - Present", html)

    def test_promotion_shows_two_titles_under_one_employer(self):
        _, html = self.build("executive")
        self.assertEqual(html.count("Lantern Row Logistics"), 1)
        lantern = html.split("Lantern Row Logistics", 1)[1].split("Cobblestone", 1)[0]
        self.assertIn("Dispatch Scheduler", lantern)
        self.assertIn("Dispatch Assistant", lantern)
        self.assertIn("Jun 2019 - Dec 2020", lantern)

    def test_one_off_items_show_one_date(self):
        self.conn.execute("UPDATE items SET start_date = '2022-05', end_date = NULL, updated_by = 'user' WHERE kind = 'Award'")
        _, html = self.build("genz")
        awards = html.split("<h2>Awards</h2>", 1)[1].split("</section>", 1)[0]
        self.assertIn("May 2022", awards)
        self.assertNotIn("Present", awards)

    def test_html_special_chars_escaped(self):
        self.conn.execute("UPDATE people SET summary = ?, updated_by = 'user'", ("Ops <b>&</b> more",))
        _, html = self.build("executive")
        self.assertIn("Ops &lt;b&gt;&amp;&lt;/b&gt; more", html)
        self.assertNotIn("<b>&</b>", html)
        self.assertIn("Cobblestone Print &amp; Pack", html)

    def test_empty_sections_dropped(self):
        for template in resume.TEMPLATES:
            _, html = self.build(template)
            self.assertNotIn("<h2></h2>", html)
            self.assertEqual(html.count("<h2>Summary</h2>"), 1)

    def test_unknown_template(self):
        with self.assertRaises(ValueError):
            resume.build_resume(self.conn, self.dir, "fancy")

    def test_unknown_track(self):
        with self.assertRaises(ValueError):
            resume.build_resume(self.conn, self.dir, "executive", "Nope")

    def test_track_filters_lines(self):
        _, original = self.build("structured")
        _, leadership = self.build("structured", "Leadership")
        self.assertIn(ORIGINAL_ONLY, original)
        self.assertNotIn(ORIGINAL_ONLY, leadership)
        self.assertIn("Led a six-carrier rate review", leadership)
        self.assertNotIn("Led a six-carrier rate review", original)

    def test_deprecated_lines_dropped(self):
        self.conn.execute("UPDATE bullet_variants SET status = 'Deprecated', updated_by = 'user' WHERE wording = ?", (ORIGINAL_ONLY,))
        _, html = self.build("executive")
        self.assertNotIn(ORIGINAL_ONLY, html)


if __name__ == "__main__":
    unittest.main()
