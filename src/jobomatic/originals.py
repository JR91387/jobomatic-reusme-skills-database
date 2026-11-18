import hashlib
from pathlib import Path

from .extract import extract_for, sniff_type

FOLDERS = {
    "Resume": "resumes",
    "Job description": "job_descriptions",
    "Review": "reviews",
    "Recommendation": "recommendations",
    "Other": "other",
    "AI output": "ai_output",
}
WEIGHTS = {"Review": 3, "AI output": 1}  # trust when the caller gives none; any other kind is 2
MAX_BYTES = 25 * 1024 * 1024


def _free_name(folder, filename):
    name = Path(filename).name
    if name in ("", ".", ".."):
        raise ValueError(f"Bad file name: {filename!r}")
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = folder / name, 1
    while candidate.exists():
        n += 1
        candidate = folder / f"{stem}_{n}{suffix}"
    return candidate


def add_original_bytes(
    conn, data_dir, filename, data, kind, *, actor, title=None, doc_date=None, weight=None,
    position_id=None, person_id=None,
):
    if kind not in FOLDERS:
        raise ValueError(f"Unknown kind {kind!r}; use one of {', '.join(FOLDERS)}")
    if weight is None:
        weight = WEIGHTS.get(kind, 2)
    if len(data) > MAX_BYTES:
        raise ValueError(f"File is {len(data)} bytes; the limit is {MAX_BYTES}")
    if sniff_type(data) is None:
        raise ValueError("Unsupported file type: use PDF, DOCX, TXT, MD, PNG or JPEG")
    sha = hashlib.sha256(data).hexdigest()
    dup = conn.execute("SELECT id FROM originals WHERE sha256 = ?", (sha,)).fetchone()
    if dup:
        raise ValueError(f"Already stored as original {dup['id']}")
    if person_id is None:
        row = conn.execute("SELECT id FROM people WHERE status = 'Active'").fetchone()
        person_id = row["id"] if row else None
    data_dir = Path(data_dir)
    folder = data_dir / "originals" / FOLDERS[kind]
    folder.mkdir(parents=True, exist_ok=True)
    dest = _free_name(folder, filename)
    dest.write_bytes(data)
    try:
        cur = conn.execute(
            "INSERT INTO originals (person_id, kind, path, title, doc_date, weight, position_id,"
            " sha256, bytes, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (person_id, kind, dest.relative_to(data_dir).as_posix(), title, doc_date, weight,
             position_id, sha, len(data), actor),
        )
    except Exception:
        dest.unlink()
        raise
    original_id = cur.lastrowid
    extract_for(conn, data_dir, original_id, actor)
    return original_id


def add_original(conn, data_dir, source_path, kind, **kwargs):
    source = Path(source_path)
    if not source.is_file():
        raise ValueError(f"No file at {source}")
    if source.stat().st_size > MAX_BYTES:
        raise ValueError(f"File is {source.stat().st_size} bytes; the limit is {MAX_BYTES}")
    return add_original_bytes(conn, data_dir, source.name, source.read_bytes(), kind, **kwargs)
