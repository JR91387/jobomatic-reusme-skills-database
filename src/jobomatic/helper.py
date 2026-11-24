#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local helper server for edit mode: python3 src/jobomatic/helper.py [--db PATH] [--open]
(or `job-o-matic`; also --add-shortcut, --remove-shortcut, --no-shortcut)

Listens on 127.0.0.1 only. Every request needs a local Host header; every POST also needs a
local Origin and the per-start token (injected into the page, never written to disk)."""
import argparse
import base64
import binascii
import hashlib
import json
import mimetypes
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # runs as a file path, not a package

from jobomatic import info, paths, shortcuts, store, updates, viewer
from jobomatic.extract import sniff_type
from jobomatic.originals import MAX_BYTES, add_original_bytes

DEFAULT_DB = paths.default_db()  # zip: my_data/ beside app/; pip install: the user data folder
WEB_DIR = paths.resource("web")
APP_PATH = "/jobomatic/"
PORTS = range(8765, 8770)
IDLE_SECONDS = 20 * 60
JSON_LIMIT = 1024 * 1024
UPLOAD_LIMIT = MAX_BYTES * 4 // 3 + 64 * 1024  # base64 inflates by 4/3
DEBOUNCE = 0.2
ACTOR = "user"
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text": "text/plain; charset=utf-8",
    "png": "image/png",
    "jpeg": "image/jpeg",
}


def on_change(db_path):
    """Runs (coalesced, on a background thread) after every successful write."""
    viewer.build(db_path)


def backup_now(db_path):
    """A checked copy in <data_dir>/backups/ named for this second; counts toward the daily backups' keep limit."""
    folder = db_path.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"jobomatic_{datetime.now().astimezone():%Y-%m-%d_%H%M%S}.db"
    store.checked_copy(db_path, target)
    return target


def open_folder(path):
    """Shows the folder in the computer's file manager."""
    opener = {"win32": "explorer", "darwin": "open"}.get(sys.platform, "xdg-open")
    try:
        subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        raise HttpError(500, f"Couldn't open the folder ({e}). It is at {path}") from None


class HttpError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.body = status, {"error": message, **extra}


class Coalescer:
    """Runs fn on one worker thread; writes arriving within DEBOUNCE of each other share one run."""

    def __init__(self, fn):
        self.fn = fn
        self.pending = threading.Event()
        self.stopped = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def trigger(self):
        self.pending.set()

    def stop(self):
        self.stopped = True
        self.pending.set()
        self.thread.join(timeout=5)

    def _loop(self):
        while True:
            self.pending.wait()
            if self.stopped:
                return
            time.sleep(DEBOUNCE)
            self.pending.clear()
            try:
                self.fn()
            except Exception:  # noqa: BLE001 - logged, worker must survive
                traceback.print_exc(file=sys.stderr)


class HelperServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, db_path, port=None, idle_seconds=IDLE_SECONDS, hook=None, web_dir=WEB_DIR):
        self.db_path = Path(db_path)
        self.data_dir = self.db_path.parent
        self.web_dir = Path(web_dir)
        self.token = secrets.token_urlsafe(32)
        self.idle_seconds = idle_seconds
        self.last_request = time.monotonic()
        self.changes = Coalescer(hook or (lambda: on_change(self.db_path)))
        super().__init__(("127.0.0.1", self._pick_port(port)), Handler)
        self.port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.port_file = self.data_dir / "app_port.json"
        self.port_file.write_text(json.dumps({"port": self.port, "pid": os.getpid()}), encoding="utf-8")
        threading.Thread(target=self._idle_watch, daemon=True).start()

    def _pick_port(self, port):
        if port is not None:
            return port
        for p in PORTS:
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", p))
                except OSError:
                    continue
            return p
        return 0

    def _idle_watch(self):
        while True:
            time.sleep(min(5, self.idle_seconds / 2))
            if time.monotonic() - self.last_request > self.idle_seconds:
                print("Idle: shutting down", file=sys.stderr)
                self.shutdown()
                return

    def server_close(self):
        super().server_close()
        self.changes.stop()
        try:
            if json.loads(self.port_file.read_text(encoding="utf-8")).get("pid") == os.getpid():
                self.port_file.unlink()
        except FileNotFoundError:
            pass


class Handler(BaseHTTPRequestHandler):
    server: HelperServer

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._run(self._get)

    def do_POST(self):
        self._run(self._post)

    def _run(self, fn):
        self.server.last_request = time.monotonic()
        try:
            if self.headers.get("Host") not in self.server.allowed_hosts:
                raise HttpError(403, "Bad Host header")
            fn()
        except HttpError as e:
            self._json(e.status, e.body)
        except (ValueError, sqlite3.Error) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - logged, reported as 500
            traceback.print_exc(file=sys.stderr)
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _send(self, status, body, ctype, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _get(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(302, b"", "text/plain", [("Location", APP_PATH)])
        if path == "/app" or path.startswith("/app/"):  # the address before v1.2.0
            return self._send(302, b"", "text/plain", [("Location", APP_PATH + path[len("/app/"):])])
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/update-status":
            return self._json(200, updates.check(self.server.data_dir))
        if path == "/data.js":
            return self._file(self.server.data_dir / "viewer_data.js", "text/javascript; charset=utf-8")
        if path.startswith("/original/"):
            return self._original(path[len("/original/"):])
        if path.startswith(APP_PATH):
            return self._app(path[len(APP_PATH):])
        raise HttpError(404, "Not found")

    def _file(self, file, ctype):
        if not file.is_file():
            raise HttpError(404, f"{file.name} not found")
        self._send(200, file.read_bytes(), ctype)

    def _app(self, rel):
        web = self.server.web_dir.resolve()
        if rel == "":
            page = web / "page.html"
            if not page.is_file():
                raise HttpError(503, "The viewer page (src/web/page.html) has not been built yet")
            tag = viewer.guide_script() + f'<script>window.HELPER_TOKEN="{self.server.token}";window.JOBOMATIC_FOLDER={json.dumps(str(self.server.data_dir.resolve()))};window.JOBOMATIC_INFO={json.dumps(info.app_info(self.server.db_path)).replace("</", "<\\/")}</script>'  # the folder only reaches the page when the app serves it, never the shipped view-only file
            html = page.read_text(encoding="utf-8").replace("</head>", tag + "</head>", 1)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        target = (web / rel).resolve()
        if not target.is_relative_to(web) or not target.is_file():
            raise HttpError(404, "Not found")
        self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def _original(self, raw_id):
        if not raw_id.isdigit():
            raise HttpError(404, "Not found")
        conn = store.connect(self.server.db_path)
        try:
            rows = store.read(conn, "SELECT path FROM originals WHERE id=?", (int(raw_id),))
        finally:
            conn.close()
        if not rows:
            raise HttpError(404, f"No original {raw_id}")
        data_dir = self.server.data_dir.resolve()
        file = (data_dir / rows[0]["path"]).resolve()
        if not file.is_relative_to(data_dir) or not file.is_file():
            raise HttpError(404, f"File for original {raw_id} is missing")
        data = file.read_bytes()
        ctype = CONTENT_TYPES.get(sniff_type(data), "application/octet-stream")
        name = file.name.replace('"', "")
        self._send(200, data, ctype, [("Content-Disposition", f'attachment; filename="{name}"')])

    def _body(self, limit):
        if self.headers.get("Origin") not in self.server.allowed_origins:
            raise HttpError(403, "Bad Origin header")
        if not secrets.compare_digest(self.headers.get("X-JobOMatic", ""), self.server.token):
            raise HttpError(403, "Bad or missing token")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise HttpError(415, "Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise HttpError(411, "Content-Length required") from None
        if length > limit:
            raise HttpError(413, f"Body is {length} bytes; the limit is {limit}")
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            raise HttpError(400, "Body is not valid JSON") from None
        if not isinstance(body, dict):
            raise HttpError(400, "Body must be a JSON object")
        return body

    def _post(self):
        path = self.path.split("?", 1)[0]
        routes = {"/save": self._save, "/retire": self._retire, "/upload": self._upload, "/quit": self._quit,
                  "/backup": self._backup, "/open-folder": self._open_folder,
                  "/update-settings": self._update_settings, "/update": self._update}
        if path not in routes:
            raise HttpError(404, "Not found")
        body = self._body(UPLOAD_LIMIT if path == "/upload" else JSON_LIMIT)
        result = routes[path](body)
        if path in ("/save", "/retire", "/upload"):
            self.server.changes.trigger()
        self._json(200, result)
        if path == "/quit":  # only after the reply is sent: handler threads are daemons and die with the server
            threading.Thread(target=self.server.shutdown).start()

    def _db(self):
        return store.connect(self.server.db_path)

    def _save(self, body):
        row, expected = body.get("row"), body.get("expected_updated_at")
        if not isinstance(row, dict):
            raise HttpError(400, "row must be an object")
        conn = self._db()
        try:
            return {"ok": True, "id": store.save_row(conn, body.get("table"), row, ACTOR, expected)}
        except store.Changed as e:
            raise HttpError(409, "changed", current=e.current) from None
        finally:
            conn.close()

    def _retire(self, body):
        conn = self._db()
        try:
            return {"ok": True, "id": store.retire_row(conn, body.get("table"), body.get("id"), ACTOR)}
        finally:
            conn.close()

    def _upload(self, body):
        try:
            data = base64.b64decode(body.get("data_b64") or "", validate=True)
        except (binascii.Error, ValueError):
            raise HttpError(400, "data_b64 is not valid base64") from None
        if not data:
            raise HttpError(400, "data_b64 is empty")
        if not body.get("filename") or not body.get("kind"):
            raise HttpError(400, "filename and kind are required")
        conn = self._db()
        try:
            dup = conn.execute("SELECT id FROM originals WHERE sha256=?", (hashlib.sha256(data).hexdigest(),)).fetchone()
            if dup:
                raise HttpError(409, f"Already stored as original {dup['id']}", id=dup["id"])
            original_id = add_original_bytes(
                conn, self.server.data_dir, body["filename"], data, body["kind"], actor=ACTOR,
                title=body.get("title"), doc_date=body.get("doc_date"),
                weight=body.get("weight"),
            )
            return {"ok": True, "id": original_id}
        finally:
            conn.close()

    def _quit(self, body):
        return {"ok": True}

    def _backup(self, body):
        target = backup_now(self.server.db_path)
        return {"ok": True, "path": target.relative_to(self.server.data_dir).as_posix()}

    def _open_folder(self, body):
        open_folder(self.server.data_dir.resolve())
        return {"ok": True}

    def _update_settings(self, body):
        value = body.get("check_updates")
        if not isinstance(value, bool):
            raise HttpError(400, "check_updates must be true or false")
        settings = updates.save_settings(self.server.data_dir, check_updates=value)
        return {"ok": True, "check_updates": settings["check_updates"]}

    def _update(self, body):
        return updates.run_update()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--open", action="store_true", help="open the browser (always on for a pip install)")
    ap.add_argument("--add-shortcut", action="store_true", help="add Job-o-Matic to the app menu, then exit")
    ap.add_argument("--remove-shortcut", action="store_true", help="remove it from the app menu, then exit")
    ap.add_argument("--no-shortcut", action="store_true",
                    help=f"don't add the app-menu entry on first run (or set {shortcuts.SKIP_ENV}=1)")
    args = ap.parse_args()
    data_dir = args.db.parent
    if args.add_shortcut or args.remove_shortcut:
        data_dir.mkdir(parents=True, exist_ok=True)
        if args.add_shortcut:
            done = shortcuts.add_shortcut(data_dir)
            print(f"Added {shortcuts.APP_NAME} to the app menu: {done}" if done else "No app-menu entry was added.")
        else:
            done = shortcuts.remove_shortcut(data_dir)
            print(f"Removed {done}" if done else "There was no app-menu entry to remove.")
        sys.exit(0)
    if paths.ensure_db(args.db):
        print(f"Created a blank database at {args.db}", flush=True)
    if not args.db.exists():
        ap.error(f"No database at {args.db}; create it with src/db.py --init")
    viewer.build(args.db, backup=False)  # the day's backup waits for its first change
    if not args.no_shortcut:
        shortcuts.ensure_first_run(data_dir)
    server = HelperServer(args.db)
    url = f"http://127.0.0.1:{server.port}{APP_PATH}"
    print(f"Job-O-Matic helper on {url}", flush=True)
    if args.open or paths.installed():
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
