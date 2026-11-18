"""Read or change the Job-O-Matic database.

    job-o-matic-db "SELECT id, name FROM people"          (or: python3 src/db.py ...)
    job-o-matic-db "UPDATE people SET headline='x', updated_by='ai' WHERE id=1"
    job-o-matic-db --file changes.sql     (all statements saved together, or none)
    job-o-matic-db --init                 (create a blank database)

Every write must set updated_by to user, ai or app."""
import argparse
import sqlite3
import sys
from pathlib import Path

from jobomatic import paths, store, viewer


def after_write(db_path):
    """Runs after every successful write: rebuilds the offline viewer."""
    viewer.build(db_path)


def main(default_db=None):
    """Entry point for `job-o-matic-db`; src/db.py passes the zip's my_data path."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--db", type=Path, default=default_db or paths.default_db())
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
    paths.ensure_db(args.db)
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


def run(default_db=None):
    try:
        main(default_db)
    except (sqlite3.Error, ValueError, OSError) as e:
        sys.exit(f"Nothing changed: {e}")


if __name__ == "__main__":
    run()
