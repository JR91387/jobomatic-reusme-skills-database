import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, resume, store, viewer

TRACKS = ("Original", "Leadership")
NODE_RENDER = """
const fs = require("fs");
require(process.argv[1]);
const job = JSON.parse(fs.readFileSync(0, "utf8"));
const out = job.runs.map(r => globalThis.JOM.renderResume(job.docs[r[1]], r[0], job.templates));
process.stdout.write(JSON.stringify(out));
"""


def visible_text(page):
    body = re.sub(r"<style.*?</style>|<title>.*?</title>", " ", page, flags=re.DOTALL)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


@unittest.skipUnless(shutil.which("node"), "node is not installed: the browser renderer parity check needs it")
class ResumeParityTest(unittest.TestCase):
    def test_browser_renderer_matches_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "demo.db"
            demo.new_demo_database(db)
            conn = store.connect(db)
            try:
                docs = {t: resume.resume_data(conn, t) for t in TRACKS}
                runs = [(tpl, t) for tpl in resume.TEMPLATES for t in TRACKS]
                py = [resume.build_resume(conn, tmp, tpl, t).read_text(encoding="utf-8") for tpl, t in runs]
            finally:
                conn.close()
        templates = json.loads(viewer.templates_js().split(" = ", 1)[1].rstrip().rstrip(";"))
        done = subprocess.run(["node", "-e", NODE_RENDER, str(ROOT / "src" / "web" / "resume_render.js")],
                              input=json.dumps({"docs": docs, "runs": runs, "templates": templates}),
                              capture_output=True, text=True, timeout=60, check=True)
        js = json.loads(done.stdout)
        self.assertEqual(len(js), 10)
        for (tpl, track), p, j in zip(runs, py, js):
            with self.subTest(template=tpl, track=track):
                self.assertIn("Odalys Brannigan-Voss", visible_text(j))
                self.assertEqual(visible_text(j), visible_text(p))
                self.assertEqual(j, p)
                if tpl == "genz":  # Awards only: the demo's Review record stays off the resume
                    self.assertIn("Awards Operations Excellence Award", visible_text(j))
                    self.assertNotIn("2024 annual performance review", visible_text(j))


if __name__ == "__main__":
    unittest.main()
