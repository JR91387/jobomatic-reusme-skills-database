#!/usr/bin/env python3
"""Write demo/Job-o-Matic demo (view only).html: the fictional demo person in the view-only page.

The view-only page has no way to edit (no helper, no database file beside it), so the demo
stays read-only; the file itself is also marked read-only."""
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobomatic import demo, viewer

OUT = ROOT / "demo" / "Job-o-Matic demo (view only).html"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "my_data" / "jobomatic.db"
        demo.new_demo_database(db)
        built = viewer.build(db)
        OUT.parent.mkdir(exist_ok=True)
        if OUT.exists():
            OUT.chmod(OUT.stat().st_mode | stat.S_IWUSR)
        html = built.read_text(encoding="utf-8")
        marker = "</head>"
        if html.count(marker) != 1:
            sys.exit("ABORT: expected one </head> in the view-only page")
        OUT.write_text(html.replace(marker, "<script>window.JOBOMATIC_DEMO = true;</script></head>"), encoding="utf-8")
    OUT.chmod(0o444)
    print(f"✅ wrote {OUT} ({OUT.stat().st_size:,} bytes, read-only)")


if __name__ == "__main__":
    main()
