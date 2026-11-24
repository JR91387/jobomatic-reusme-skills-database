"""Builds the offline viewer: my_data/viewer_data.js and one self-contained "Job-o-Matic (view only).html"."""
import base64
import json
import os
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from jobomatic import paths, resume, store

WEB_DIR = paths.resource("web")
GUIDE = paths.resource("AI_GUIDE.md")
HTML_NAME = paths.HTML_NAME
TEXT_CAP = 12000  # characters of one original's extracted text shipped to the page
# Only the view-only file gets this line; the app serves page.html as it is (edit mode).
VIEW_BANNER = ('<p class="view-banner">View only: to change anything, ask your AI or open the Job-o-Matic app.</p>'
               '<header class="top">')


def _write_atomic(path, text):
    tmp = path.with_name(f".tmp_{os.getpid()}_{threading.get_ident()}{path.suffix}")  # plain open keeps umask perms
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def snapshot_bytes(db_path):
    """A compact copy of the database; image BLOBs are kept only for the Active headshot."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "snapshot.db"
        src = sqlite3.connect(db_path)
        try:
            src.execute("VACUUM INTO ?", (str(snap),))
        finally:
            src.close()
        conn = sqlite3.connect(snap)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")  # sql.js cannot open a WAL-flagged file
            # sql.js has no FTS5: drop the full-text index and every trigger that feeds it (the viewer never searches)
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%search_index%'").fetchall():
                conn.execute(f'DROP TRIGGER "{name}"')
            conn.execute("DROP TABLE IF EXISTS search_index")
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='images'").fetchall():
                conn.execute(f'DROP TRIGGER "{name}"')
            conn.execute("UPDATE images SET image = X'' WHERE status <> 'Active'")
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
        return snap.read_bytes()


def _script(js):
    return "<script>" + js.replace("</script", "<\\/script") + "</script>"


def _js_string(text):
    return json.dumps(text).replace("</", "<\\/")


def guide_script():
    text = GUIDE.read_text(encoding="utf-8") if GUIDE.is_file() else ""
    text = "\n".join(line for line in text.split("\n") if not line.startswith("!["))  # header image: not shown as text
    return _script(f"window.AI_GUIDE={_js_string(text)};")


def thumbs_script():
    """Style pictures for the Create Resume preview when there is no profile yet (scripts/make_style_thumbs.mjs)."""
    thumbs = {p.stem: f"data:image/webp;base64,{_b64(p)}" for p in sorted((WEB_DIR / "thumbs").glob("*.webp"))}
    return _script(f"window.JOM_THUMBS={json.dumps(thumbs)};")


def _b64(path):
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _inline_fonts(css):
    def font(m):
        return f'url("data:font/woff2;base64,{_b64(WEB_DIR / m[1])}")'
    return re.sub(r'url\("(fonts/[^"]+\.woff2)"\)', font, css)


def _replace_once(html, old, new):
    if html.count(old) != 1:
        raise ValueError(f"page.html must contain {old!r} exactly once")
    return html.replace(old, new)


def render_html(data_js):
    html = (WEB_DIR / "page.html").read_text(encoding="utf-8")
    tokens = _inline_fonts((WEB_DIR / "tokens.css").read_text(encoding="utf-8"))
    styles = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    html = _replace_once(html, '<header class="top">', VIEW_BANNER)
    html = _replace_once(html, '<link rel="stylesheet" href="tokens.css">', f"<style>{tokens}</style>")
    html = _replace_once(html, '<link rel="stylesheet" href="styles.css">', f"<style>{styles}</style>")
    for svg in ("wordmark-light.svg", "wordmark-dark.svg"):
        html = _replace_once(html, f'src="{svg}"', f'src="data:image/svg+xml;base64,{_b64(WEB_DIR / svg)}"')
    html = _replace_once(html, 'href="favicon.svg"', f'href="data:image/svg+xml;base64,{_b64(WEB_DIR / "favicon.svg")}"')
    data = (_script(data_js) + guide_script() + thumbs_script()
            + _script(f'window.SQL_WASM_B64="{_b64(WEB_DIR / "vendor" / "sql-wasm.wasm")}";')
            + _script((WEB_DIR / "vendor" / "sql-wasm.js").read_text(encoding="utf-8")))
    html = _replace_once(html, '<script src="vendor/sql-wasm.js"></script>', data)
    html = _replace_once(html, '<script src="resume_render.js"></script>',
                         _script((WEB_DIR / "resume_render.js").read_text(encoding="utf-8")))
    html = _replace_once(html, '<script src="updates.js"></script>', "")  # update notices need the running app
    return _replace_once(html, '<script src="app.js"></script>', _script((WEB_DIR / "app.js").read_text(encoding="utf-8")))


def original_texts(db_path, data_dir):
    """Extracted text of each original (my_data/<path>.txt) for the prompts and the job-ad picker, cut at TEXT_CAP."""
    conn = store.connect(db_path)
    try:
        rows = store.read(conn, "SELECT id, path FROM originals ORDER BY id")
    finally:
        conn.close()
    texts = {}
    for r in rows:
        txt = data_dir / (r["path"] + ".txt")
        if txt.is_file():
            text = txt.read_text(encoding="utf-8", errors="replace")
            texts[r["id"]] = text if len(text) <= TEXT_CAP else text[:TEXT_CAP] + "\n(truncated)"
    return texts


def templates_js():
    """The resume styles for the in-browser quick draft (src/web/resume_render.js)."""
    templates = {t: (resume.TEMPLATES_DIR / f"resume_{t}_v1.html").read_text(encoding="utf-8") for t in resume.TEMPLATES}
    return f"window.JOBOMATIC_TEMPLATES = {json.dumps(templates).replace('<', '\\u003c')};\n"  # no </head> etc. inside the page


def build(db_path, data_dir=None, backup=True):
    """backup=False only at app start: the day's backup is taken after its first change, so it holds that change."""
    db_path = Path(db_path)
    data_dir = Path(data_dir) if data_dir else db_path.parent
    store.connect(db_path).close()  # upgrades an older database before it is copied into the page
    if backup:
        store.backup_daily(db_path)
    updated = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    b64 = base64.b64encode(snapshot_bytes(db_path)).decode("ascii")
    texts = json.dumps(original_texts(db_path, data_dir)).replace("<", "\\u003c")
    data_js = f'window.JOBOMATIC_DB = {{updated: "{updated}", b64: "{b64}", texts: {texts}}};\n' + templates_js()
    _write_atomic(data_dir / "viewer_data.js", data_js)
    html_path = paths.view_html_path(data_dir)
    _write_atomic(html_path, render_html(data_js))
    return html_path
