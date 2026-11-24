# SPDX-License-Identifier: MIT
# Built by Jerry Reinitz, Reinitz Industries. Tulsa software development: bespoke, effective applications. https://jerryreinitz.com
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import phonenumbers

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
    """Opens the database. A file from an older supported version (4 and up) is backed up to
    <data_dir>/backups/ and upgraded first; older files are refused."""
    if not Path(path).exists():
        raise FileNotFoundError(f"No database at {path}; create it with --init")
    conn = _open(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        _check_version(version)
        if version >= SCHEMA_VERSION:
            return conn
        conn.close()
        upgrade(path, version)
        conn = _open(path)
        _check_version(conn.execute("PRAGMA user_version").fetchone()[0])
    except Exception:
        conn.close()
        raise
    return conn


SCHEMA_VERSION = 5
OLDEST_UPGRADABLE = 4


def _check_version(version):
    """Refuses a database made by an older test version; there is no upgrade path before version 4."""
    if version < OLDEST_UPGRADABLE:
        raise RuntimeError(f"This file was made by an older test version of Job-o-Matic (schema {version}); "
                           f"it is not supported. Create a new file.")


def _build_schema(conn, seed=True):
    names = ("schema.sql", "schema_guide.sql", "seed_blank.sql") if seed else ("schema.sql", "schema_guide.sql")
    for name in names:
        conn.executescript((SQL_DIR / name).read_text(encoding="utf-8"))


def new_database(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(path)
    try:
        _build_schema(conn)
    except Exception:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        raise
    conn.close()


# ---- Upgrades ---------------------------------------------------------------------------------------------
# One step per version: UPGRADES[n] turns a version-n file into version n+1 in place. A new version adds a step.

def upgrade(path, version):
    """Backs the file up, then runs every step from `version` to SCHEMA_VERSION. Returns the backup path."""
    path = Path(path)
    if version < OLDEST_UPGRADABLE or version >= SCHEMA_VERSION:
        raise RuntimeError(f"Cannot upgrade schema {version} to {SCHEMA_VERSION}")
    _take_sole_access(path)
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    backup = path.parent / "backups" / f"jobomatic_v{version}_{stamp}.db"
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        checked_copy(path, backup)
    except Exception as exc:
        raise RuntimeError(f"This file needs an upgrade to version {SCHEMA_VERSION}, but the backup copy failed "
                           f"({exc}); nothing was changed. Free some disk space or check the folder "
                           f"{backup.parent} can be written, then open it again.") from exc
    while version < SCHEMA_VERSION:
        try:
            UPGRADES[version](path)
        except Exception as exc:
            raise RuntimeError(f"Upgrading from version {version} failed ({exc}). The file was not changed; "
                               f"a copy from before the upgrade is at {backup}.") from exc
        version += 1
    return backup


def _take_sole_access(path):
    """Leaves WAL mode, which folds the -wal file in and only works when no other program has the file open."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    except sqlite3.OperationalError:  # locked: someone else is reading or writing it
        mode = "busy"
    finally:
        conn.close()
    if mode.lower() != "delete":
        raise RuntimeError("This file needs an upgrade, but another program has it open. Close the other "
                           "Job-o-Matic windows and your AI app, then open it again.")


def _rebuild(path, fill=None, after_copy=None):
    """Rebuild step: build a fresh file from the current schema (no seed rows; schema_guide comes from the new
    schema), copy every row across with its rowid (columns matched by name; `fill(table, cols, rows)` may
    rewrite a table's columns and rows), check the row counts per table, run `after_copy(conn)` on the new file
    with the triggers back on, then swap the files. Triggers are off while copying, so audit history and
    updated_at are copied exactly and the copy itself adds no audit rows."""
    path = Path(path)
    tmp = path.with_name(path.name + ".upgrade")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    try:
        new = sqlite3.connect(tmp, isolation_level=None)
        try:
            _build_schema(new, seed=False)
            triggers = new.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY rowid").fetchall()
            for name, _ in triggers:
                new.execute(f'DROP TRIGGER "{name}"')
            new_tables = [r[0] for r in new.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'search_index_%' AND name <> 'schema_guide' ORDER BY rowid")]
            new_cols = {t: [r[1] for r in new.execute(f'PRAGMA table_info("{t}")')] for t in new_tables}
        finally:
            new.close()
        old = sqlite3.connect(path, isolation_level=None)
        try:
            old.execute("PRAGMA busy_timeout=5000")
            old.execute("ATTACH DATABASE ? AS new", (str(tmp),))
            old.execute("BEGIN EXCLUSIVE")
            old_tables = {r[0] for r in old.execute(
                "SELECT name FROM main.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'search_index_%' AND name <> 'schema_guide'")}
            lost = old_tables - set(new_tables)
            if lost:
                raise RuntimeError(f"tables missing from the new schema: {sorted(lost)}")
            for table in new_tables:
                if table not in old_tables:
                    continue
                cols = [r[1] for r in old.execute(f'PRAGMA main.table_info("{table}")')]
                cols = ([] if "id" in cols else ["rowid"]) + cols  # id is the rowid where there is one
                rows = old.execute(f'SELECT {", ".join(_quote(c) for c in cols)} FROM main."{table}"').fetchall()
                out_cols, rows = fill(table, cols, rows) if fill else (cols, rows)
                missing = set(out_cols) - set(new_cols[table]) - {"rowid"}
                if missing:
                    raise RuntimeError(f"{table} columns missing from the new schema: {sorted(missing)}")
                quoted = ", ".join(_quote(c) for c in out_cols)
                old.executemany(f'INSERT INTO new."{table}" ({quoted}) VALUES ({", ".join("?" * len(out_cols))})', rows)
                before = old.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0]
                after = old.execute(f'SELECT count(*) FROM new."{table}"').fetchone()[0]
                if before != after:
                    raise RuntimeError(f"{table}: {before} rows before, {after} after")
            old.execute("COMMIT")
            old.execute("DETACH DATABASE new")
        except BaseException:
            if old.in_transaction:
                old.execute("ROLLBACK")
            raise
        finally:
            old.close()
        new = sqlite3.connect(tmp, isolation_level=None)
        try:
            new.executescript("BEGIN;\n" + ";\n".join(sql for _, sql in triggers) + ";\nCOMMIT;")
            bad = new.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise RuntimeError(f"broken references after copying: {bad[:5]}")
            check = new.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"integrity check: {check}")
            if after_copy:
                after_copy(new)
        finally:
            new.close()
        os.replace(tmp, path)
    except BaseException:
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(tmp) + suffix).unlink(missing_ok=True)
        raise
    for suffix in ("-journal", "-wal", "-shm"):  # stale companions of the old file must not touch the new one
        Path(str(path) + suffix).unlink(missing_ok=True)


def _quote(col):
    return col if col == "rowid" else f'"{col}"'


def split_name(text):
    """'Jane Q Public' -> ('Jane Q', 'Public'): split on the last space. One word -> (word, '')."""
    parts = (text or "").strip().rsplit(None, 1)
    if not parts:
        return "", ""
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


US_NAMES = {"us", "u.s", "usa", "u.s.a", "united states", "united states of america"}
NO_SPONSOR = re.compile(r"\b(without|no|not\s+requir\w*|not\s+need\w*|never\s+need\w*|do(?:es)?\s*n[o']?t\s+(?:need|require))"
                        r"\b[\w\s]{0,20}?sponsor", re.IGNORECASE)
COUNTRY = re.compile(r"\bin\s+(?:the\s+)?([A-Z][\w.]*(?:\s+(?:of\s+)?[A-Z][\w.]*)*)")


def work_auth_fields(text):
    """Old free-text work authorization -> (work_auth_status, work_auth_country). 'Authorized ... without
    sponsorship' counts as Authorized; any other mention of sponsorship as Needs sponsorship."""
    text = (text or "").strip()
    if not text:
        return None, None
    authorized = re.search(r"authori[sz]ed", text, re.IGNORECASE)
    if authorized and (NO_SPONSOR.search(text) or not re.search(r"sponsor|\bnot\b", text, re.IGNORECASE)):
        m = COUNTRY.search(text)
        country = m.group(1).rstrip(".") if m else None
        if country and country.lower().rstrip(".") in US_NAMES:
            country = "United States"
        return "Authorized", country
    if re.search(r"sponsor", text, re.IGNORECASE):
        return "Needs sponsorship", None
    return "Other", None


def _norm_url(url):
    return (url or "").strip().rstrip("/").lower()


def _v4_to_v5(path):
    """people gains first_name/last_name (split from full_name, else name) and work_auth_status/country (read
    from the old text, which is kept); people.linkedin moves to links as kind LinkedIn; phone and email are
    normalized where they can be read."""
    moved = []

    def fill(table, cols, rows):
        if table != "people":
            return cols, rows
        keep = [c for c in cols if c != "linkedin"]
        out = []
        for row in rows:
            r = dict(zip(cols, row))
            status, country = work_auth_fields(r["work_authorization"])
            for key, normalize in (("phone", normalize_phone), ("email", normalize_email)):
                try:
                    r[key] = normalize(r[key])
                except ValueError:
                    pass  # an old value the checks cannot read is kept as typed
            out.append([r[c] for c in keep] + [*split_name(r["full_name"] or r["name"]), status, country])
            if (r.get("linkedin") or "").strip():
                moved.append((r["id"], r["linkedin"].strip()))
        return keep + ["first_name", "last_name", "work_auth_status", "work_auth_country"], out

    def after_copy(conn):
        conn.execute("BEGIN")
        for person_id, url in moved:
            have = {_norm_url(u) for (u,) in conn.execute("SELECT url FROM links WHERE person_id = ?", (person_id,))}
            if _norm_url(url) not in have:
                conn.execute("INSERT INTO links (person_id, kind, label, url, sort, updated_by)"
                             " VALUES (?, 'LinkedIn', NULL, ?, 0, 'app')", (person_id, url))
        conn.execute("COMMIT")

    _rebuild(path, fill, after_copy)


UPGRADES = {4: _v4_to_v5}


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
    "people": {"name", "full_name", "first_name", "last_name", "other_names", "headline", "location", "phone",
               "email", "summary", "work_authorization", "work_auth_status", "work_auth_country", "status"},
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
    _normalize_contact(row)
    if table == "people":
        _people_names(conn, row, row_id)
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


PHONE_HELP = "Include the country code for non-US numbers, e.g. +44 20 7946 0958."


def normalize_phone(value, region="US"):
    """Any common way of writing a phone number -> E.164 ('+15551234567'); empty stays empty.
    Accepts numbers whose length fits a full number for that country (phonenumbers' is_possible, not is_valid),
    so made-up or newly issued numbers such as 555 ones are kept; junk and too short or too long are refused."""
    if value is None or not str(value).strip():
        return value if value is None else ""
    text = str(value).strip()
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        number = None
    if number is None or phonenumbers.is_possible_number_with_reason(number) != phonenumbers.ValidationResult.IS_POSSIBLE:
        raise ValueError(f"Phone number not recognized: {text!r}. {PHONE_HELP}")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(value):
    """Trimmed, the domain in lower case; needs one @ and a dot in the domain. Empty stays empty."""
    if value is None or not str(value).strip():
        return value if value is None else ""
    text = str(value).strip()
    local, at, domain = text.rpartition("@")
    if (not at or not local or "@" in local or any(c.isspace() for c in text)
            or "." not in domain.strip(".") or domain.startswith(".") or domain.endswith(".") or ".." in domain):
        raise ValueError(f"Email address not recognized: {text!r}. Use the form name@example.com.")
    return f"{local}@{domain.lower()}"


def _normalize_contact(row):
    if "phone" in row:
        row["phone"] = normalize_phone(row["phone"])
    if "email" in row:
        row["email"] = normalize_email(row["email"])


def _people_names(conn, row, row_id):
    """first_name/last_name drive full_name, and name when name was empty or simply the old full name.
    A new person needs both (the web and MCP forms ask for them)."""
    for key in ("first_name", "last_name"):
        if isinstance(row.get(key), str):
            row[key] = row[key].strip()
    old = {} if row_id is None else (get_row(conn, "people", row_id) or {})
    if row_id is None and not (row.get("first_name") and row.get("last_name")):
        raise ValueError("A new person needs first_name and last_name")
    if "first_name" not in row and "last_name" not in row:
        return
    first = row.get("first_name", old.get("first_name")) or ""
    last = row.get("last_name", old.get("last_name")) or ""
    full = f"{first} {last}".strip()
    if not full:
        return
    row["full_name"] = full
    if not (row.get("name") or "").strip() and ("name" in row or not old.get("name")
                                                  or old.get("name") == old.get("full_name")):
        row["name"] = full
    if "name" in row:
        taken = conn.execute("SELECT 1 FROM people WHERE name = ? AND rowid IS NOT ?", (row["name"], row_id)).fetchone()
        if taken:
            raise ValueError(f"Another person already has the name {row['name']!r}. Set name to something "
                             f"different (for example add a middle initial) and save again.")


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
