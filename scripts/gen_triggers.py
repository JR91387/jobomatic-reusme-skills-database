"""Regenerates the house triggers in src/db/schema.sql from its CREATE TABLE statements.

Every table except audit gets: no_delete, need_by_ins, need_by_upd, after_ins, after_upd (audit JSON of
every non-BLOB column). The generated block runs from the first table's *_no_delete trigger to the line
before audit_no_delete.

  python scripts/gen_triggers.py           # check: exit 1 if schema.sql differs from the generated block
  python scripts/gen_triggers.py --write   # rewrite the block in place
"""
import re
import sys
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "src" / "db" / "schema.sql"
SKIP = {"audit"}
CONSTRAINT = re.compile(r"^(UNIQUE|CHECK|PRIMARY|FOREIGN|CONSTRAINT)$", re.IGNORECASE)
COLUMN = re.compile(r"^(\w+)\s+(INTEGER|TEXT|BLOB|REAL|NUMERIC)\b", re.IGNORECASE)
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


def tables(sql):
    for name, body in re.findall(r"^CREATE TABLE (\w+) \((.*?)^\);", sql, re.MULTILINE | re.DOTALL):
        if name in SKIP:
            continue
        cols = []
        for line in body.splitlines():
            m = COLUMN.match(line.split("--")[0].strip())
            if m and not CONSTRAINT.match(m.group(1)) and m.group(2).upper() != "BLOB":
                cols.append(m.group(1))
        yield name, cols


def block(name, cols):
    def obj(alias):
        return "json_object(" + ", ".join(f"'{c}', {alias}.{c}" for c in cols) + ")"

    new = f"json_set({obj('x')}, '$.updated_by', NEW.updated_by)"
    return f"""CREATE TRIGGER {name}_no_delete BEFORE DELETE ON {name}
  BEGIN SELECT RAISE(ABORT, 'Do not delete: retire it by setting status'); END;

CREATE TRIGGER {name}_need_by_ins BEFORE INSERT ON {name} WHEN NEW.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

-- skips the clear step, which is the only write that goes from a set updated_by to NULL
CREATE TRIGGER {name}_need_by_upd BEFORE UPDATE ON {name} WHEN NEW.updated_by IS NULL AND OLD.updated_by IS NULL
  BEGIN SELECT RAISE(ABORT, 'updated_by is required: user, ai or app'); END;

CREATE TRIGGER {name}_after_ins AFTER INSERT ON {name}
  BEGIN
    UPDATE {name} SET updated_at = coalesce(NEW.updated_at, {NOW}), updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT '{name}', NEW.rowid, 'insert', NULL, {new}, NEW.updated_by
      FROM {name} x WHERE x.rowid = NEW.rowid;
  END;

CREATE TRIGGER {name}_after_upd AFTER UPDATE ON {name} WHEN NEW.updated_by IS NOT NULL
  BEGIN
    UPDATE {name} SET updated_at = CASE WHEN NEW.updated_at IS OLD.updated_at THEN {NOW} ELSE NEW.updated_at END,
      updated_by = NULL WHERE rowid = NEW.rowid;
    INSERT INTO audit (table_name, row_id, op, old_json, new_json, actor)
      SELECT '{name}', NEW.rowid, 'update', {obj('OLD')}, {new}, NEW.updated_by
      FROM {name} x WHERE x.rowid = NEW.rowid;
  END;

"""


def main():
    sql = SCHEMA.read_text(encoding="utf-8")
    found = list(tables(sql))
    start = sql.index(f"CREATE TRIGGER {found[0][0]}_no_delete ")
    end = sql.index("CREATE TRIGGER audit_no_delete ")
    generated = "".join(block(n, c) for n, c in found)
    if sql[start:end] == generated:
        print(f"✅ triggers current ({len(found)} tables)")
        return 0
    if "--write" in sys.argv:
        SCHEMA.write_text(sql[:start] + generated + sql[end:], encoding="utf-8")
        print(f"✅ triggers rewritten ({len(found)} tables)")
        return 0
    print("❌ triggers differ from generated; run with --write")
    return 1


if __name__ == "__main__":
    sys.exit(main())
