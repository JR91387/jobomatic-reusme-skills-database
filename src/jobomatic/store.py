# SPDX-License-Identifier: MIT
# Built by Jerry Reinitz, Reinitz Industries. Tulsa software development: bespoke, effective applications. https://jerryreinitz.com
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from jobomatic import paths

SQL_DIR = paths.resource("db")
READ_WORDS = {"SELECT", "WITH", "PRAGMA"}
TXN_WORDS = {"BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE"}
STOPWORDS = frozenset({
    "a", "about", "all", "also", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can", "for",
    "from", "has", "have", "if", "in", "into", "is", "it", "its", "may", "more", "most", "no", "not", "of",
    "on", "one", "or", "our", "out", "so", "such", "than", "that", "the", "their", "then", "there", "these",
    "they", "this", "to", "us", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with",
    "within", "would", "you", "your",
})
IMAGE_COLUMNS = "id, person_id, caption, mime, bytes, sha256, source, status, updated_by, updated_at"  # no picture bytes


class Result(NamedTuple):
    columns: list
    rows: list
    changes: int | None  # None for reads


def _open(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA recursive_triggers=ON")  # makes INSERT OR REPLACE fire the no-delete triggers
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def connect(path):
    if not Path(path).exists():
        raise FileNotFoundError(f"No database at {path}; create it with --init")
    conn = _open(path)
    try:
        _check_version(conn)
    except Exception:
        conn.close()
        raise
    return conn


SCHEMA_VERSION = 4


def _check_version(conn):
    """Refuses a database made by an older test version; there is no upgrade path before version 4."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        raise RuntimeError(f"This file was made by an older test version of Job-o-Matic (schema {version}); "
                           f"it is not supported. Create a new file.")


def new_database(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(path)
    try:
        for name in ("schema.sql", "schema_guide.sql", "seed_blank.sql"):
            conn.executescript((SQL_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        raise
    conn.close()


def _statements(sql):
    parts, buf = [], ""
    for piece in re.split(r"(;)", sql):
        buf += piece
        if piece == ";" and sqlite3.complete_statement(buf):
            parts.append(buf)
            buf = ""
    if buf.strip():
        parts.append(buf)
    return parts


def _bare(statement):
    """The statement without comments or surrounding space."""
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", statement, flags=re.DOTALL).strip()


def _first_word(statement):
    bare = _bare(statement).split(None, 1)
    return bare[0].upper().rstrip(";") if bare else ""


def run_sql(conn, sql):
    statements = _statements(sql)
    words = [_first_word(s) for s in statements]
    if any(w in TXN_WORDS for w in words):
        raise ValueError("Leave out BEGIN / COMMIT / ROLLBACK: all statements are saved together or none")
    is_pragma_set = words[0:1] == ["PRAGMA"] and "=" in statements[0]
    if len(statements) == 1 and words[0] in READ_WORDS and not is_pragma_set:
        conn.execute("PRAGMA query_only=ON")
        try:
            cur = conn.execute(sql)
            return Result([d[0] for d in cur.description or []], cur.fetchall(), None)
        finally:
            conn.execute("PRAGMA query_only=OFF")
    before = conn.execute("SELECT coalesce(max(id), 0) FROM audit").fetchone()[0]
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + sql + "\n;\nCOMMIT;")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    after = conn.execute("SELECT coalesce(max(id), 0) FROM audit").fetchone()[0]
    return Result([], [], after - before)  # audit rows = rows written, including trigger cascades


EDITABLE_TABLES = {
    "people": {"name", "full_name", "other_names", "headline", "location", "phone", "email", "linkedin",
               "summary", "work_authorization", "status"},
    "links": {"person_id", "kind", "label", "url", "sort", "status"},
    "images": {"caption", "status"},
    "employers": {"person_id", "name", "location", "website", "notes", "status"},
    "positions": {"person_id", "employer_id", "title", "department", "start_date", "end_date",
                  "sort_order", "notes", "status"},
    "items": {"person_id", "position_id", "parent_item_id", "kind", "title", "detail", "outputs", "organization",
              "from_whom", "start_date", "end_date", "source", "notes", "status"},
    "item_metrics": {"item_id", "label", "value", "unit", "as_of", "sort", "status"},
    "item_originals": {"item_id", "original_id", "note", "status"},
    "bullet_variants": {"item_id", "wording", "angle", "length", "track", "source", "status"},
    "tracks": {"name", "color", "sort", "status"},
    "skills": {"person_id", "name", "category", "status"},
    "skill_links": {"skill_id", "item_type", "item_id", "status"},
    "education": {"person_id", "kind", "name", "institution", "location", "year", "start_date", "end_date",
                  "expires", "credential_url", "status"},
    "settings": {"value"},
    "qa": {"person_id", "question", "category", "common_wordings", "answer", "status", "sort", "notes"},
    "originals": {"title", "doc_date", "weight", "position_id", "extracted", "notes"},
}
RETIRED_STATUS = {"people": "Archived", "tracks": "Retired", "links": "Deprecated", "images": "Deprecated",
                  "employers": "Deprecated", "positions": "Deprecated", "items": "Deprecated",
                  "item_metrics": "Deprecated", "item_originals": "Deprecated", "bullet_variants": "Deprecated",
                  "skills": "Deprecated", "skill_links": "Deprecated", "education": "Deprecated",
                  "qa": "Deprecated"}


def _check_table(table):
    if table not in EDITABLE_TABLES:
        raise ValueError(f"Unknown table {table!r}; choose from {sorted(EDITABLE_TABLES)}")


@contextmanager
def _transaction(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _change_one(conn, sql, params):
    cur = conn.execute(sql, params)
    if cur.rowcount != 1:
        raise ValueError("No row changed")
    return cur.lastrowid


def _write(conn, sql, params):
    with _transaction(conn):
        return _change_one(conn, sql, params)


class Changed(ValueError):
    """The row changed after the caller read it; nothing was written."""

    def __init__(self, table, current):
        super().__init__(f"{table} row {current['id']} changed since you read it (updated_at is now {current['updated_at']}). "
                         f"Current row: {json.dumps(current)}")
        self.current = current


def save_row(conn, table, row, actor, expected_updated_at=None):
    """Insert (no id) or update (id given) one row; returns its id (rowid for skill_links).
    With expected_updated_at, the update only happens if the row still carries that version."""
    with _transaction(conn):
        return _save(conn, table, row, actor, expected_updated_at)


def save_rows(conn, table, rows, actor):
    """save_row for many rows in one transaction: all are written or none. Each row may carry its own
    expected_updated_at key. Returns the ids in order."""
    if not rows:
        raise ValueError("Nothing to save: rows is empty")
    ids = []
    with _transaction(conn):
        for i, row in enumerate(rows):
            row = dict(row)
            expected = row.pop("expected_updated_at", None)
            try:
                ids.append(_save(conn, table, row, actor, expected))
            except (ValueError, sqlite3.Error) as exc:
                exc.args = (f"rows[{i}]: {exc} (nothing was saved)",)
                raise
    return ids


def _save(conn, table, row, actor, expected_updated_at):
    _check_table(table)
    row = dict(row)
    row_id = row.pop("id", None)
    bad = sorted(set(row) - EDITABLE_TABLES[table])
    if bad:
        raise ValueError(f"Not editable in {table}: {bad}; editable: {sorted(EDITABLE_TABLES[table])}")
    if not row:
        raise ValueError("Nothing to save: give at least one column")
    row["updated_by"] = actor
    cols = list(row)
    if row_id is None:
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        return _change_one(conn, sql, [row[c] for c in cols])
    sql = f"UPDATE {table} SET {', '.join(c + '=?' for c in cols)} WHERE rowid=?"
    params = [row[c] for c in cols] + [row_id]
    if expected_updated_at is None:
        _change_one(conn, sql, params)
        return row_id
    try:
        _change_one(conn, sql + " AND updated_at IS ?", params + [expected_updated_at])
    except ValueError:
        current = get_row(conn, table, row_id)
        if current is None:
            raise ValueError(f"No {table} row {row_id}") from None
        raise Changed(table, current) from None
    return row_id


def get_row(conn, table, rowid):
    """One row as a dict (images without the picture bytes) with created_by and last_changed_by from audit, or None."""
    _check_table(table)
    cols = IMAGE_COLUMNS if table == "images" else "rowid AS id, *"
    rows = read(
        conn,
        f"SELECT {cols},"
        " (SELECT actor FROM audit WHERE table_name = ? AND row_id = t.rowid ORDER BY id LIMIT 1) AS created_by,"
        " (SELECT actor FROM last_change WHERE table_name = ? AND row_id = t.rowid) AS last_changed_by"
        f" FROM {table} t WHERE t.rowid = ?",
        (table, table, rowid),
    )
    return rows[0] if rows else None


def retire_row(conn, table, row_id, actor):
    _check_table(table)
    if table not in RETIRED_STATUS:
        raise ValueError(f"{table} has no status column to retire")
    _write(conn, f"UPDATE {table} SET status=?, updated_by=? WHERE rowid=?", [RETIRED_STATUS[table], actor, row_id])
    return row_id


def read(conn, sql, params=()):
    conn.execute("PRAGMA query_only=ON")
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.execute("PRAGMA query_only=OFF")


def search(conn, text, limit=20, include_unanswered=False):
    """Best matches first (bm25). The text is treated as plain words (common words dropped), so a pasted job
    description works. Seeded questions nobody has answered yet are left out unless include_unanswered."""
    words = list(dict.fromkeys(w for w in (w.lower() for w in re.findall(r"\w+", text)) if w not in STOPWORDS))
    if not words:
        raise ValueError("Give some words to search for (common words like 'the' and 'and' are ignored)")
    skip = "" if include_unanswered else (
        " AND NOT (source_table = 'qa' AND source_id IN (SELECT id FROM qa WHERE seeded = 1 AND answer IS NULL))")
    return read(
        conn,
        "SELECT source_table, source_id, snippet(search_index, 2, '[', ']', '...', 16) AS snippet, rank"
        f" FROM search_index WHERE search_index MATCH ?{skip} ORDER BY rank LIMIT ?",
        (" OR ".join(f'"{w}"' for w in words), limit),
    )


def checked_copy(db_path, target):
    """VACUUM INTO a temp file, integrity-check it, then move it to `target`."""
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        conn.close()
    check = sqlite3.connect(tmp)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        tmp.unlink()
        raise sqlite3.DatabaseError(f"Backup failed its integrity check: {result}")
    tmp.replace(target)


def backup_daily(db_path, keep=30):
    """One checked copy per local day in <data_dir>/backups/; only the newest `keep` are kept."""
    db_path = Path(db_path)
    folder = db_path.parent / "backups"
    folder.mkdir(exist_ok=True)
    today = folder / f"jobomatic_{datetime.now(timezone.utc).astimezone().date().isoformat()}.db"
    if not today.exists():
        checked_copy(db_path, today)
    for old in sorted(folder.glob("jobomatic_*.db"))[:-keep]:
        old.unlink()
    return today
