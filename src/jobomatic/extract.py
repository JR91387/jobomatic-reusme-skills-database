import hashlib
import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def sniff_type(data):
    """Return 'pdf', 'docx', 'text', 'png', 'jpeg', or None. Judged from the bytes, not the file name."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return "docx" if "word/document.xml" in z.namelist() else None
        except zipfile.BadZipFile:
            return None
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text"
    return None


def _docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == W + "t":
                parts.append(el.text or "")
            elif el.tag == W + "tab":
                parts.append("\t")
            elif el.tag in (W + "br", W + "cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def _pdf_text(data):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text(path):
    data = Path(path).read_bytes()
    kind = sniff_type(data)
    if kind == "docx":
        return _docx_text(data)
    if kind == "pdf":
        return _pdf_text(data)
    if kind == "text":
        return data.decode("utf-8")
    if kind in ("png", "jpeg"):
        return None
    raise ValueError(f"Cannot extract text from {path}: unsupported file type")


def _sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_unchanged(path, expected, original_id, when):
    if _sha256_of(path) != expected:
        raise RuntimeError(f"Original {original_id} changed {when} extraction: {path}")


def extract_for(conn, data_dir, original_id, actor):
    row = conn.execute("SELECT path, sha256, notes FROM originals WHERE id = ?", (original_id,)).fetchone()
    if row is None:
        raise ValueError(f"No original with id {original_id}")
    file = Path(data_dir) / row["path"]
    _check_unchanged(file, row["sha256"], original_id, "before")
    text = extract_text(file)
    _check_unchanged(file, row["sha256"], original_id, "after")
    if text and text.strip():
        Path(str(file) + ".txt").write_text(text, encoding="utf-8")
        conn.execute("UPDATE originals SET extracted = 'Text read', updated_by = ? WHERE id = ?", (actor, original_id))
        return
    note = "no text layer"
    notes = row["notes"]
    if notes and note not in notes:
        note = f"{notes}\n{note}"
    elif notes:
        note = notes
    conn.execute(
        "UPDATE originals SET extracted = 'Not yet', notes = ?, updated_by = ? WHERE id = ?",
        (note, actor, original_id),
    )
