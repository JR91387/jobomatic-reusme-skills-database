import base64
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import __version__, helper, store, viewer
from tests.test_originals import make_blank_pdf


class HelperCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        self.db = self.data_dir / "jobomatic.db"
        store.new_database(self.db)
        conn = store.connect(self.db)
        conn.execute("INSERT INTO people (name, updated_by) VALUES ('Pat', 'user')")
        conn.close()
        self.calls = []
        self.fired = threading.Event()
        self.server = helper.HelperServer(self.db, port=0, hook=self.hook, web_dir=self.data_dir / "no_web")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.port
        self.origin = f"http://127.0.0.1:{self.port}"

    def hook(self):
        self.calls.append(1)
        self.fired.set()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, host=None, origin=None, token=True, raw=None):
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
        if method == "POST":
            headers["Content-Type"] = "application/json"
            headers["Origin"] = origin or self.origin
            if token:
                headers["X-JobOMatic"] = token if isinstance(token, str) else self.server.token
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            if data is not None:
                conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            resp = conn.getresponse()
            payload = resp.read()
            return resp.status, resp, payload
        finally:
            conn.close()

    def post(self, path, body, **kw):
        status, _, payload = self.request("POST", path, body, **kw)
        return status, json.loads(payload)

    def query(self, sql, params=()):
        conn = store.connect(self.db)
        try:
            return store.read(conn, sql, params)
        finally:
            conn.close()

    def upload(self, data, **kw):
        body = {"filename": "doc.pdf", "kind": "Review", "data_b64": base64.b64encode(data).decode(), **kw}
        return self.post("/upload", body)


class SecurityTests(HelperCase):
    def test_bad_host(self):
        self.assertEqual(self.request("GET", "/health", host="evil.example:80")[0], 403)
        self.assertEqual(self.request("GET", "/health", host="127.0.0.1:1")[0], 403)

    def test_localhost_host_ok(self):
        self.assertEqual(self.request("GET", "/health", host=f"localhost:{self.port}")[0], 200)

    def test_post_token(self):
        body = {"table": "people", "row": {"id": 1, "headline": "x"}}
        self.assertEqual(self.post("/save", body, token=False)[0], 403)
        self.assertEqual(self.post("/save", body, token="wrong")[0], 403)
        self.assertIsNone(self.query("SELECT headline FROM people")[0]["headline"])

    def test_bad_origin(self):
        body = {"table": "people", "row": {"id": 1, "headline": "x"}}
        self.assertEqual(self.post("/save", body, origin="http://evil.example")[0], 403)
        self.assertEqual(self.post("/save", body, origin=f"http://127.0.0.1:{self.port + 1}")[0], 403)

    def test_path_traversal(self):
        (self.data_dir / "secret.txt").write_text("s")
        web = self.data_dir / "web"
        web.mkdir()
        self.server.web_dir = web
        (web / "ok.txt").write_text("fine")
        self.assertEqual(self.request("GET", "/jobomatic/ok.txt")[0], 200)
        for path in ("/jobomatic/../secret.txt", "/jobomatic/../../etc/passwd", "/jobomatic/%2e%2e/secret.txt"):
            self.assertIn(self.request("GET", path)[0], (403, 404), path)


class RouteTests(HelperCase):
    def test_health_and_redirect(self):
        status, _, payload = self.request("GET", "/health")
        self.assertEqual((status, json.loads(payload)), (200, {"ok": True}))
        status, resp, _ = self.request("GET", "/")
        self.assertEqual((status, resp.getheader("Location")), (302, "/jobomatic/"))

    def test_old_addresses_redirect(self):
        for old, new in (("/app/", "/jobomatic/"), ("/app", "/jobomatic/"), ("/app/styles.css", "/jobomatic/styles.css")):
            status, resp, _ = self.request("GET", old)
            self.assertEqual((status, resp.getheader("Location")), (302, new), old)

    def test_page_gets_info(self):
        web = self.data_dir / "web"
        web.mkdir()
        (web / "page.html").write_text("<html><head></head><body>x</body></html>")
        self.server.web_dir = web
        page = self.request("GET", "/jobomatic/")[2].decode()
        raw = page.split("window.JOBOMATIC_INFO=", 1)[1].split("</script>", 1)[0]
        info = json.loads(raw)
        self.assertEqual(info["version"], __version__)
        self.assertEqual(info["db_path"], str(self.server.db_path.resolve()))
        self.assertEqual(info["data_folder"], str(self.server.data_dir.resolve()))
        self.assertIn(info["install_type"], ("pip", "zip", "repo"))
        self.assertEqual(info["mcp"]["name"], "job-o-matic")
        self.assertEqual(info["mcp"]["transport"], "stdio")
        self.assertEqual(info["mcp"]["env"], {"JOBOMATIC_DB": info["db_path"]})

    def test_app_503_without_page(self):
        self.assertEqual(self.request("GET", "/jobomatic/")[0], 503)

    def test_page_gets_token(self):
        web = self.data_dir / "web"
        web.mkdir()
        (web / "page.html").write_text("<html><head></head><body>x</body></html>")
        self.server.web_dir = web
        status, _, payload = self.request("GET", "/jobomatic/")
        self.assertEqual(status, 200)
        page = payload.decode()
        self.assertIn(f'window.HELPER_TOKEN="{self.server.token}";window.JOBOMATIC_FOLDER=', page)
        self.assertIn(json.dumps(str(self.server.data_dir.resolve())) + ";window.JOBOMATIC_INFO=", page)
        self.assertNotIn(self.server.token, "".join(p.read_text(errors="ignore") for p in self.data_dir.rglob("*.json")))

    def test_data_js_route_is_gone(self):
        self.assertEqual(self.request("GET", "/data.js")[0], 404)

    def test_port_file(self):
        info = json.loads((self.data_dir / "app_port.json").read_text())
        self.assertEqual(info["port"], self.port)

    def test_unknown_post_route(self):
        self.assertEqual(self.post("/nope", {})[0], 404)


class WriteTests(HelperCase):
    def test_save_update_audit_actor(self):
        status, out = self.post("/save", {"table": "people", "row": {"id": 1, "headline": "Hi"}})
        self.assertEqual((status, out["ok"]), (200, True))
        self.assertEqual(self.query("SELECT headline FROM people")[0]["headline"], "Hi")
        audit = self.query("SELECT actor FROM audit WHERE table_name='people' ORDER BY id DESC LIMIT 1")
        self.assertEqual(audit[0]["actor"], "user")

    def test_stale_update_409(self):
        self.post("/save", {"table": "people", "row": {"id": 1, "headline": "A"}})
        current = self.query("SELECT updated_at FROM people")[0]["updated_at"]
        status, out = self.post(
            "/save", {"table": "people", "row": {"id": 1, "headline": "B"}, "expected_updated_at": "1999-01-01"})
        self.assertEqual(status, 409)
        self.assertEqual(out["current"]["headline"], "A")
        self.assertEqual(self.query("SELECT headline FROM people")[0]["headline"], "A")
        status, _ = self.post(
            "/save", {"table": "people", "row": {"id": 1, "headline": "B"}, "expected_updated_at": current})
        self.assertEqual(status, 200)

    def test_non_editable_column_400(self):
        status, out = self.post("/save", {"table": "people", "row": {"id": 1, "updated_by": "ai"}})
        self.assertEqual(status, 400)
        self.assertIn("updated_by", out["error"])

    def test_retire_keeps_row(self):
        status, _ = self.post("/retire", {"table": "people", "id": 1})
        self.assertEqual(status, 200)
        rows = self.query("SELECT status FROM people")
        self.assertEqual(rows, [{"status": "Archived"}])

    def test_items_numbers_and_attachments_through_save(self):
        """What the Items screen sends: an employer, two positions (a promotion), an item with a number, an attachment."""
        save = lambda table, row, **kw: self.post("/save", {"table": table, "row": row, **kw})
        _, emp = save("employers", {"person_id": 1, "name": "Acme"})
        _, a = save("positions", {"person_id": 1, "employer_id": emp["id"], "title": "Clerk", "start_date": "2020-01", "end_date": "2021-06"})
        _, b = save("positions", {"person_id": 1, "employer_id": emp["id"], "title": "Lead", "start_date": "2021-07"})
        self.assertEqual(self.query("SELECT count(*) AS n FROM positions WHERE employer_id=?", (emp["id"],))[0]["n"], 2)
        # dates outside the position are only a warning in the page: the save works
        status, item = save("items", {"person_id": 1, "position_id": a["id"], "kind": "Achievement",
                                      "detail": "Cut errors", "start_date": "2018", "end_date": "2022"})
        self.assertEqual(status, 200)
        status, child = save("items", {"person_id": 1, "kind": "Award", "title": "Star", "parent_item_id": item["id"]})
        self.assertEqual(status, 200)
        status, num = save("item_metrics", {"item_id": item["id"], "value": "30%", "label": "Errors", "status": "Verified"})
        self.assertEqual(status, 200)
        status, _ = save("item_metrics", {"item_id": item["id"], "value": "  "})
        self.assertEqual(status, 400)
        _, orig = self.upload(make_blank_pdf(), title="Review")
        status, link = save("item_originals", {"item_id": item["id"], "original_id": orig["id"], "status": "Active"})
        self.assertEqual(status, 200)
        self.assertEqual(self.query("SELECT rowid AS id, status FROM item_originals")[0], {"id": link["id"], "status": "Active"})
        self.assertEqual(self.post("/retire", {"table": "item_originals", "id": link["id"]})[0], 200)
        self.assertEqual(self.query("SELECT status FROM item_originals")[0]["status"], "Deprecated")
        self.assertEqual(self.post("/retire", {"table": "item_metrics", "id": num["id"]})[0], 200)
        stale = self.query("SELECT updated_at FROM item_originals")[0]["updated_at"]
        status, _ = save("item_originals", {"id": link["id"], "status": "Active"}, expected_updated_at="1999-01-01")
        self.assertEqual(status, 409)  # the 409 flow works for links too
        status, _ = save("item_originals", {"id": link["id"], "status": "Active"}, expected_updated_at=stale)
        self.assertEqual(status, 200)
        self.assertEqual(self.query("SELECT status FROM item_originals")[0]["status"], "Active")
        self.assertEqual(child["id"], item["id"] + 1)

    def test_upload_and_duplicate(self):
        pdf = make_blank_pdf()
        status, out = self.upload(pdf, title="T")
        self.assertEqual(status, 200)
        row = self.query("SELECT * FROM originals WHERE id=?", (out["id"],))[0]
        self.assertEqual(row["title"], "T")
        actors = {a["actor"] for a in self.query("SELECT actor FROM audit WHERE table_name='originals'")}
        self.assertEqual(actors, {"user"})
        self.assertTrue((self.data_dir / row["path"]).is_file())
        self.assertTrue(row["path"].startswith("originals/reviews/"))
        status, dup = self.upload(pdf)
        self.assertEqual((status, dup["id"]), (409, out["id"]))

    def test_upload_weight_review_official(self):
        _, review = self.upload(make_blank_pdf())
        _, other = self.upload(b"Notes.\n", filename="n.txt", kind="Other")
        self.assertEqual(self.query("SELECT weight FROM originals WHERE id=?", (review["id"],))[0]["weight"], 3)
        self.assertEqual(self.query("SELECT weight FROM originals WHERE id=?", (other["id"],))[0]["weight"], 2)

    def test_upload_text_makes_sidecar(self):
        status, out = self.upload(b"Led a team of five.\n", filename="note.txt", kind="Other")
        self.assertEqual(status, 200)
        path = self.query("SELECT path FROM originals WHERE id=?", (out["id"],))[0]["path"]
        self.assertTrue((self.data_dir / (path + ".txt")).is_file())
        status, resp, payload = self.request("GET", f"/original/{out['id']}?k={self.server.token}")
        self.assertEqual((status, payload), (200, b"Led a team of five.\n"))
        self.assertTrue(resp.getheader("Content-Type").startswith("text/plain"))

    def test_upload_bad_input_400(self):
        self.assertEqual(self.upload(b"\x00\x01binary")[0], 400)
        self.assertEqual(self.post("/upload", {"filename": "a.txt", "kind": "Other", "data_b64": "!!"})[0], 400)

    def test_on_change_coalesces_burst(self):
        for i in range(5):
            self.post("/save", {"table": "people", "row": {"id": 1, "headline": f"h{i}"}})
        self.assertTrue(self.fired.wait(5))
        self.fired.clear()
        self.assertFalse(self.fired.wait(helper.DEBOUNCE * 3))
        self.assertEqual(len(self.calls), 1)

    def test_failed_write_does_not_fire_hook(self):
        self.post("/save", {"table": "people", "row": {"id": 1, "updated_by": "ai"}})
        self.assertFalse(self.fired.wait(helper.DEBOUNCE * 3))

    def test_quit(self):
        self.assertEqual(self.post("/quit", {})[0], 200)
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())


class FolderTests(HelperCase):
    def backups(self):
        return sorted(p.name for p in (self.data_dir / "backups").glob("*.db"))

    def test_backup_now(self):
        status, out = self.post("/backup", {})
        self.assertEqual(status, 200)
        copy = self.data_dir / out["path"]
        self.assertRegex(out["path"], r"^backups/jobomatic_\d{4}-\d\d-\d\d_\d{6}\.db$")
        conn = store.connect(copy)
        try:
            self.assertEqual(store.read(conn, "SELECT name FROM people"), [{"name": "Pat"}])
        finally:
            conn.close()
        self.assertEqual(self.backups(), [copy.name])
        self.assertFalse(self.fired.wait(helper.DEBOUNCE * 3))  # not a change: no rebuild

    def test_open_folder_uses_os_file_manager(self):
        with mock.patch.object(helper.subprocess, "Popen") as popen:
            status, _ = self.post("/open-folder", {})
        self.assertEqual(status, 200)
        args = popen.call_args[0][0]
        self.assertIn(args[0], ("xdg-open", "open", "explorer"))
        self.assertEqual(args[1], str(self.data_dir.resolve()))

    def test_open_folder_failure_is_visible(self):
        with mock.patch.object(helper.subprocess, "Popen", side_effect=FileNotFoundError("xdg-open")):
            status, out = self.post("/open-folder", {})
        self.assertEqual(status, 500)
        self.assertIn(str(self.data_dir.resolve()), out["error"])

    def test_daily_backup_after_first_change_not_at_start(self):
        argv = ["helper.py", "--db", str(self.db)]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(helper, "HelperServer"), \
                mock.patch.object(helper.viewer, "build") as build, mock.patch("builtins.print"):
            helper.main()
        build.assert_called_once_with(self.db, backup=False)
        viewer.build(self.db, backup=False)
        self.assertEqual(self.backups(), [])
        helper.on_change(self.db)  # what a successful write runs
        self.assertEqual(len(self.backups()), 1)
        self.assertRegex(self.backups()[0], r"^jobomatic_\d{4}-\d\d-\d\d\.db$")


if __name__ == "__main__":
    unittest.main()
