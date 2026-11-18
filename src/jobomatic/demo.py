from pathlib import Path

from . import originals, store

DEMO_DIR = store.SQL_DIR / "demo_originals"


def new_demo_database(db_path):
    db_path = Path(db_path)
    store.new_database(db_path)
    conn = store.connect(db_path)
    try:
        conn.executescript((store.SQL_DIR / "seed_demo.sql").read_text(encoding="utf-8"))
        data_dir = db_path.parent
        for filename, kind, title, doc_date, weight, position in [
            ("performance_review_2024.pdf", "Review", "2024 annual performance review", "2024-12-15", 3, 1),
            ("job_description_coordinator.txt", "Job description", "Coordinator, Distribution Operations", "2023-02-01", 3, 1),
        ]:
            original_id = originals.add_original_bytes(
                conn, data_dir, filename, (DEMO_DIR / filename).read_bytes(), kind,
                actor="app", title=title, doc_date=doc_date, weight=weight, position_id=position,
            )
            conn.execute("UPDATE originals SET extracted = 'Done', updated_by = 'app' WHERE id = ?", (original_id,))
            if kind == "Review":  # the review backs the review item and the two facts quoted from it
                conn.executemany("INSERT INTO item_originals (item_id, original_id, updated_by) VALUES (?, ?, 'app')",
                                 [(item_id, original_id) for item_id in (13, 1, 4)])
    except Exception:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        raise
    conn.close()
