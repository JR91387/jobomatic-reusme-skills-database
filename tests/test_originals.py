import hashlib
import io
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import originals, store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make_docx(*paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def make_text_pdf(text):
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def make_blank_pdf():
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


class OriginalsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "my_data"
        self.src = Path(tmp.name) / "src"
        self.src.mkdir()
        store.new_database(self.data_dir / "jobomatic.db")
        self.conn = store.connect(self.data_dir / "jobomatic.db")
        self.addCleanup(self.conn.close)
        self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Pat', 'user')")

    def source(self, name, data):
        p = self.src / name
        p.write_bytes(data)
        return p

    def add(self, name, data, kind="Review", **kw):
        kw.setdefault("actor", "app")
        return originals.add_original(self.conn, self.data_dir, self.source(name, data), kind, **kw)

    def row(self, original_id):
        return self.conn.execute("SELECT * FROM originals WHERE id = ?", (original_id,)).fetchone()

    def test_docx_copied_and_extracted(self):
        data = make_docx("Led a team of five", "Cut costs 20 percent")
        oid = self.add("review.docx", data)
        row = self.row(oid)
        self.assertEqual(row["path"], "originals/reviews/review.docx")
        stored = self.data_dir / row["path"]
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), hashlib.sha256(data).hexdigest())
        self.assertEqual(row["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(row["extracted"], "Text read")
        text = Path(str(stored) + ".txt").read_text(encoding="utf-8")
        self.assertEqual(text, "Led a team of five\nCut costs 20 percent")
        self.assertEqual((self.src / "review.docx").read_bytes(), data)

    def test_text_pdf(self):
        oid = self.add("r.pdf", make_text_pdf("Quarterly Excellence Award"), kind="Recommendation")
        row = self.row(oid)
        self.assertTrue(row["path"].startswith("originals/recommendations/"))
        self.assertEqual(row["extracted"], "Text read")
        self.assertIn("Quarterly Excellence Award", (self.data_dir / (row["path"] + ".txt")).read_text())

    def test_blank_pdf_has_no_text_layer(self):
        oid = self.add("scan.pdf", make_blank_pdf(), kind="Other")
        self.conn.execute("UPDATE originals SET notes = 'from scanner', updated_by = 'user' WHERE id = ?", (oid,))
        from jobomatic import extract
        extract.extract_for(self.conn, self.data_dir, oid, "app")
        row = self.row(oid)
        self.assertEqual(row["extracted"], "Not yet")
        self.assertEqual(row["notes"], "from scanner\nno text layer")
        self.assertFalse((self.data_dir / (row["path"] + ".txt")).exists())

    def test_blank_pdf_without_notes(self):
        row = self.row(self.add("scan.pdf", make_blank_pdf()))
        self.assertEqual(row["notes"], "no text layer")

    def test_text_and_image(self):
        t = self.row(self.add("n.md", "# Notes\ncafé".encode(), kind="Resume"))
        self.assertTrue(t["path"].startswith("originals/resumes/"))
        self.assertEqual((self.data_dir / (t["path"] + ".txt")).read_text(encoding="utf-8"), "# Notes\ncafé")
        i = self.row(self.add("p.png", PNG, kind="Job description"))
        self.assertTrue(i["path"].startswith("originals/job_descriptions/"))
        self.assertEqual(i["extracted"], "Not yet")

    def test_duplicate_refused(self):
        first = self.add("a.docx", make_docx("same"))
        with self.assertRaisesRegex(ValueError, f"original {first}"):
            self.add("b.docx", make_docx("same"))
        self.assertFalse((self.data_dir / "originals" / "reviews" / "b.docx").exists())

    def test_collision_naming(self):
        paths = [self.row(self.add("x.txt", f"v{n}".encode()))["path"] for n in range(3)]
        self.assertEqual(
            paths, ["originals/reviews/x.txt", "originals/reviews/x_2.txt", "originals/reviews/x_3.txt"]
        )

    def test_unsupported_refused(self):
        for name, data in [("a.exe", b"MZ\x00\x01"), ("b.bin", b"\xff\xfe\x00\x00"), ("c.docx", b"PK\x03\x04junk")]:
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                self.add(name, data)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM originals").fetchone()[0], 0)

    def test_sniffed_not_named(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            self.add("fake.pdf", b"\x00\x01\x02")

    def test_too_big(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            originals.add_original_bytes(
                self.conn, self.data_dir, "big.txt", b"a" * (originals.MAX_BYTES + 1), "Other", actor="app"
            )

    def test_audit_actor(self):
        oid = self.add("a.docx", make_docx("hello"), actor="ai")
        actors = [
            r[0] for r in self.conn.execute(
                "SELECT actor FROM audit WHERE table_name = 'originals' AND row_id = ? ORDER BY id", (oid,))
        ]
        self.assertEqual(actors, ["ai", "ai"])

    def test_bad_actor_leaves_nothing(self):
        with self.assertRaises(sqlite3.Error):
            self.add("a.docx", make_docx("hello"), actor="someone")
        self.assertFalse((self.data_dir / "originals" / "reviews" / "a.docx").exists())

    def test_changed_file_detected(self):
        oid = self.add("a.txt", b"hello")
        (self.data_dir / self.row(oid)["path"]).write_bytes(b"edited")
        from jobomatic import extract
        with self.assertRaisesRegex(RuntimeError, "changed before"):
            extract.extract_for(self.conn, self.data_dir, oid, "app")

    def test_original_before_person_is_claimed_by_first_person(self):
        self.conn.execute("UPDATE people SET status = 'Archived', updated_by = 'user'")
        oid = self.add("a.txt", b"hello")
        self.assertIsNone(self.row(oid)["person_id"])
        self.conn.execute("INSERT INTO people (name, updated_by) VALUES ('Sam', 'user')")
        self.assertEqual(self.row(oid)["person_id"], 2)


if __name__ == "__main__":
    unittest.main()
