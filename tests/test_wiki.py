"""The generated wiki pages (docs/wiki/) must match the code: rerun scripts/gen_wiki.py after a schema or tool change."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("gen_wiki", ROOT / "scripts" / "gen_wiki.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GeneratedWiki(unittest.TestCase):
    def test_pages_current(self):
        mod = load()
        for name, fn in mod.PAGES.items():
            with self.subTest(page=name):
                self.assertEqual((mod.WIKI / name).read_text(encoding="utf-8"), fn(),
                                 f"{name} is stale: run python3 scripts/gen_wiki.py")

    def test_links(self):
        self.assertEqual(load().broken_links(), [])


if __name__ == "__main__":
    unittest.main()
