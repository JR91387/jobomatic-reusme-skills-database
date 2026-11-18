"""Job-O-Matic MCP server (stdio). Database: argv[1], else env JOBOMATIC_DB, else the bundle's my_data/jobomatic.db."""
import functools
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # runs as a file path, not a package

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from jobomatic import originals, paths, resume, store, viewer

DEFAULT_DB = paths.default_db()  # zip: my_data/ beside app/; pip install: the user data folder
DB_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JOBOMATIC_DB") or DEFAULT_DB)
DATA_DIR = DB_PATH.parent
MAX_ROWS = 500
SEARCH_CAP = 50
EXTRACT_STATES = ("Not yet", "Text read", "Partly", "Done")
READ_ONLY = {"audit": "id", "last_change": "at"}  # list/get may read them (column to order by); nothing writes them
ORIGINAL_COLS = "id, kind, path, title, doc_date, weight, position_id, extracted, notes"

server = MCPServer(
    name="job-o-matic",
    instructions=(
        "Job-O-Matic is the user's career repository: facts about them, kept in one SQLite file.\n"
        "Read from it to write resumes, cover letters and interview answers; save new facts back as you learn them.\n"
        "Never delete: retire a row instead. Every write you make is recorded as 'ai' and can be reviewed:\n"
        "get returns created_by and last_changed_by, and list reads the audit and last_change tables.\n"
        "Ask the person before saving many rows at once, and keep wording close to the stored fact.\n"
        "save_many writes many rows of one table in one go, all or nothing (e.g. marking rows Verified).\n"
        "Original documents are kept unedited; read them with read_original and put the facts in the tables.\n"
        "add_original stores a file from this computer: one the person points you to, or kind 'AI output' for a file you wrote.\n"
        "build_resume prints Short and Long lines only; tell the person about any warnings it returns.\n"
        "Start with schema_guide: it explains every table, column and rule in plain words.\n"
        "To build a resume, call resume_data once: it returns the whole resume for a track as one JSON document.\n"
        "To tailor to a job, paste the job description into search: it returns the best-matching lines and facts first."
    ),
)


def tool(name=None):
    """Register a tool whose failures reach the AI with their real message (the SDK hides all but ToolError)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (ValueError, sqlite3.Error, OSError, NotImplementedError) as exc:
                raise ToolError(f"{type(exc).__name__}: {exc}") from exc
        return server.tool(name=name)(wrapper)
    return deco


def _conn():
    return store.connect(DB_PATH)


def _rows(sql, params=()):
    conn = _conn()
    try:
        return store.read(conn, sql, params)
    finally:
        conn.close()


def _refresh():
    """Rebuild the offline viewer (and its page) so the app shows what was just written."""
    try:
        viewer.build(DB_PATH)
    except Exception as exc:
        raise OSError(f"The change was written, but refreshing the app file failed: {exc}") from exc


def _table(table):
    if table not in store.EDITABLE_TABLES and table not in READ_ONLY:
        raise ValueError(f"Unknown table {table!r}; choose from {sorted(store.EDITABLE_TABLES)}"
                         f" (or read only: {sorted(READ_ONLY)})")
    return table


@tool()
def get_profile() -> dict:
    """The whole profile in one call: person, links, employers, positions, items (each with its metrics and attached
    original ids), resume lines, skills, education. Items hold every kind: responsibilities, achievements, awards, projects, reviews ..."""
    people = _rows("SELECT * FROM people WHERE status='Active' ORDER BY id LIMIT 1")
    live = "status <> 'Deprecated'"
    profile = json.loads(_rows("SELECT profile FROM profile_json")[0]["profile"]) if people else {}
    return {
        "person": people[0] if people else None,
        "links": _rows(f"SELECT * FROM links WHERE {live} ORDER BY sort, id"),
        "employers": profile.get("employers", []),
        "positions": profile.get("positions", []),
        "items": profile.get("items", []),
        "resume_lines": _rows(f"SELECT * FROM resume_lines WHERE {live} ORDER BY item_id, id"),
        "skills": profile.get("skills", []),
        "education": profile.get("education", []),
    }


@tool()
def search(text: str, limit: int = 20, include_unanswered: bool = False) -> list[dict]:
    """Ranked full-text search over facts, resume lines, employers, positions, items, item metrics, skills and Q&A; best match first.
    Paste a whole job description to find the lines that fit it (common words are ignored). Seeded interview
    questions with no answer yet are left out unless include_unanswered. Returns source_table, source_id, snippet, rank (max 50)."""
    conn = _conn()
    try:
        return store.search(conn, text, max(1, min(limit, SEARCH_CAP)), include_unanswered)
    finally:
        conn.close()


@tool()
def resume_data(track: str = "Original") -> dict:
    """The whole resume for a track in one JSON document: person, links, employers (each with its positions, and each position with its ranked lines, the
    item and metrics behind each line), items (awards, projects, reviews ... with metrics), Verified skills and education. Use it to write a resume or cover letter."""
    conn = _conn()
    try:
        return resume.resume_data(conn, track)
    finally:
        conn.close()


@tool()
def schema_guide() -> list[dict]:
    """Plain-language description of every table, view, column and rule. Read this first."""
    return _rows("SELECT * FROM schema_guide ORDER BY kind = 'rule', object, column_name IS NOT NULL, column_name")


@tool(name="list")
def list_rows(table: str, status: str | None = None, limit: int = 100) -> list[dict]:
    """List rows of a table (optionally only one status), newest ids last. Max 500 rows. Images omit the picture bytes.
    Also reads audit (every write: who, when, the row before and after) and last_change (who last changed each row);
    for those two you get the most recent rows, newest last."""
    _table(table)
    if table in READ_ONLY:
        if status is not None:
            raise ValueError(f"{table} has no status column")
        order = READ_ONLY[table]
        return _rows(f"SELECT * FROM (SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?) ORDER BY {order}",
                     [max(1, min(limit, MAX_ROWS))])
    cols = store.IMAGE_COLUMNS if table == "images" else "*"
    sql, params = f"SELECT {cols} FROM {table}", []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    return _rows(sql + " ORDER BY rowid LIMIT ?", params + [max(1, min(limit, MAX_ROWS))])


@tool()
def get(table: str, id: int) -> dict:
    """Fetch one row by id, with created_by and last_changed_by (user, ai or app, from audit); images omit the
    picture bytes. updated_by is always empty once a write is recorded: read these two instead. Also gets one audit entry."""
    _table(table)
    if table == "last_change":
        raise ValueError("last_change has no id: get the row from its own table, which returns created_by and last_changed_by")
    conn = _conn()
    try:
        row = store.read(conn, "SELECT * FROM audit WHERE id = ?", (id,))[:1] if table == "audit" else [store.get_row(conn, table, id)]
    finally:
        conn.close()
    if not row or row[0] is None:
        raise ValueError(f"No {table} row with id {id}")
    return row[0]


@tool()
def save(table: str, row: dict, expected_updated_at: str | None = None) -> dict:
    """Insert a row (no 'id' key) or update one (with 'id'); only editable columns are accepted. Recorded as 'ai'.
    New rows you add start as 'Needs review' unless you set a status. Returns the full saved row.
    When updating, pass the row's updated_at from when you read it: if the person changed it since, nothing is
    written and the error carries the current row, so merge into that instead of overwriting their edit."""
    conn = _conn()
    try:
        saved = store.get_row(conn, table, store.save_row(conn, table, row, "ai", expected_updated_at))
    finally:
        conn.close()
    _refresh()
    return saved


@tool()
def save_many(table: str, rows: list[dict]) -> list[dict]:
    """Save many rows of one table in one transaction: all are written or none, and the error names the failing row.
    Each row is like save's row (no 'id' inserts, 'id' updates) and may carry its own 'expected_updated_at'.
    Use it for bulk changes such as setting status 'Verified'; every write is recorded as 'ai'. Max 500 rows.
    Returns the saved rows in order."""
    if len(rows) > MAX_ROWS:
        raise ValueError(f"{len(rows)} rows; send at most {MAX_ROWS} per call")
    conn = _conn()
    try:
        saved = [store.get_row(conn, table, i) for i in store.save_rows(conn, table, rows, "ai")]
    finally:
        conn.close()
    _refresh()
    return saved


@tool()
def retire(table: str, id: int) -> dict:
    """Retire a row (status Deprecated / Archived / Retired). Rows are never deleted. Recorded as 'ai'."""
    conn = _conn()
    try:
        retired = {"table": table, "id": store.retire_row(conn, table, id, "ai")}
    finally:
        conn.close()
    _refresh()
    return retired


@tool()
def list_originals() -> list[dict]:
    """List the unedited source documents (resumes, reviews, ...) with their extraction state. Waiting for you = extracted <> 'Done' ('Text read' means the text is ready but no facts were taken yet)."""
    return _rows(f"SELECT {ORIGINAL_COLS} FROM originals ORDER BY id")


@tool()
def add_original(path: str, kind: str, title: str | None = None) -> dict:
    """Store a file from this computer (give its full path) as an original: copied into my_data/originals/, never
    changed, and its text extracted, the same as Upload in the app. kind: Resume, Job description, Review,
    Recommendation, Other, or 'AI output' for a file you wrote. PDF, DOCX, TXT, MD, PNG or JPEG, up to 25 MB.
    A file already stored is refused with its original id. Returns the new original; read its text with read_original."""
    conn = _conn()
    try:
        new_id = originals.add_original(conn, DATA_DIR, Path(path).expanduser(), kind, actor="ai", title=title)
    finally:
        conn.close()
    _refresh()
    return _rows(f"SELECT {ORIGINAL_COLS} FROM originals WHERE id = ?", [new_id])[0]


@tool()
def read_original(id: int) -> dict:
    """Return an original's metadata and its extracted text. If not extracted yet, says so instead of text."""
    rows = _rows(f"SELECT {ORIGINAL_COLS} FROM originals WHERE id = ?", [id])
    if not rows:
        raise ValueError(f"No original with id {id}")
    meta = rows[0]
    txt = DATA_DIR / (meta["path"] + ".txt")
    if not txt.is_file():
        return {**meta, "text": None, "message": f"Text has not been extracted yet (no {meta['path']}.txt); the original is at {meta['path']}"}
    return {**meta, "text": txt.read_text(encoding="utf-8")}


@tool()
def mark_extracted(id: int, state: str) -> dict:
    """Record how far facts have been pulled from an original into the tables: 'Not yet', 'Text read', 'Partly' or 'Done'. Set 'Done' only when you have taken everything useful."""
    if state not in EXTRACT_STATES:
        raise ValueError(f"state must be one of {EXTRACT_STATES}")
    conn = _conn()
    try:
        marked = {"id": store.save_row(conn, "originals", {"id": id, "extracted": state}, "ai"), "extracted": state}
    finally:
        conn.close()
    _refresh()
    return marked


@tool()
def qa_open() -> list[dict]:
    """Interview questions still waiting for an answer or a review, in order."""
    return _rows("SELECT * FROM qa WHERE status IN ('Needs answer','Needs review') ORDER BY sort IS NULL, sort, id")


@tool()
def build_resume(template: str, track: str = "Original") -> dict:
    """Fill a resume template (executive, navy_bar, two_column, structured or genz) with the profile's Short and Long
    lines for a version (track); Story lines are for cover letters and interviews and are never printed.
    Writes a new HTML file the person can print to PDF (an earlier one is never overwritten). Returns its path and
    warnings: how many printed rows are still Needs review and how many skills are hidden because not Verified."""
    conn = _conn()
    try:
        path = resume.build_resume(conn, DATA_DIR, template, track)
        built = {"path": str(path), "warnings": resume.resume_data(conn, track)["warnings"]}
    finally:
        conn.close()
    _refresh()
    return built


def main():
    """Entry point for `job-o-matic-mcp` (stdio)."""
    paths.ensure_db(DB_PATH)
    server.run()


if __name__ == "__main__":
    main()
