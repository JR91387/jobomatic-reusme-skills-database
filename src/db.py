#!/usr/bin/env python3
"""Read or change the Job-O-Matic database.

    python3 src/db.py "SELECT id, name FROM people"
    python3 src/db.py "UPDATE people SET headline='x', updated_by='ai' WHERE id=1"
    python3 src/db.py --file changes.sql     (all statements saved together, or none)
    python3 src/db.py --init                 (create a blank database)

Every write must set updated_by to user, ai or app."""
import argparse
import sqlite3
import sys
from pathlib import Path

from jobomatic import store, viewer

# Bundle layout: Job-o-Matic/app/src/db.py with Job-o-Matic/my_data/ beside app/.
DEFAULT_DB = Path(__file__).resolve().parents[2] / "my_data" / "jobomatic.db"


def after_write(db_path):
    """Runs after every successful write: rebuilds the offline viewer."""
    viewer.build(db_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--init", action="store_true")
    args = ap.parse_args()
    if args.init:
        if args.sql or args.file:
            ap.error("--init takes no SQL")
        store.new_database(args.db)
        after_write(args.db)
        print(f"ok, created {args.db}")
        return
    if bool(args.sql) == bool(args.file):
        ap.error("give either SQL or --file")
    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql
    conn = store.connect(args.db)
    result = store.run_sql(conn, sql)
    conn.close()
    if result.changes is None:
        print("\t".join(result.columns))
        for row in result.rows:
            print("\t".join("" if v is None else str(v) for v in row))
    else:
        print(f"ok, {result.changes} changes")
        try:
            after_write(args.db)
        except Exception as e:  # noqa: BLE001 - the write already succeeded; say so
            sys.exit(f"Saved, but the viewer was not rebuilt: {e}")


if __name__ == "__main__":
    try:
        main()
    except (sqlite3.Error, ValueError, OSError) as e:
        sys.exit(f"Nothing changed: {e}")
