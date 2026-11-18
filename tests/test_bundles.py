import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("build_bundles", ROOT / "scripts" / "build_bundles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TopLevelDocs(unittest.TestCase):
    def test_docs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            load().add_top_level_docs(root)
            start = (root / "START HERE.txt").read_text(encoding="utf-8")
            self.assertLessEqual(len(start.splitlines()), 15)
            self.assertTrue((root / "PRIVACY.md").exists())
            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertNotIn("<!--", readme)
            self.assertIn("8765 (or the next free number shown)", readme)
            self.assertIn("Licence", readme)

    def test_names_and_images(self):
        import re

        mod = load()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mod.add_top_level_docs(root)
            readme = (root / "README.md").read_text(encoding="utf-8")
            for plat in mod.PLATFORMS:
                self.assertIn(f"Job-o-Matic_v{mod.VERSION}_{plat}.zip", readme)
            self.assertNotIn("<version>", readme)
            for name in ("README.md", "PRIVACY.md"):
                text = (root / name).read_text(encoding="utf-8")
                for ref in re.findall(r"!\[[^\]]*\]\(([^)]+)\)|src=\"([^\"]+)\"", text):
                    path = ref[0] or ref[1]
                    if not path.startswith("http"):
                        self.assertTrue((root / path).exists(), f"{name}: {path}")

    def test_start_here(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            load().add_top_level_docs(root)
            lines = (root / "START HERE.txt").read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(len(lines), 15)
            self.assertIn("Job-o-Matic keeps your career data for your AI to use.", " ".join(lines[:4]))


if __name__ == "__main__":
    unittest.main()
