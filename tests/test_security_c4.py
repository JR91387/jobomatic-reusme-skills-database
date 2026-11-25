"""v1.3.0 C4: token-gated data and originals, frame headers, safe add_original, shortcut and config guards."""
import base64
import http.client
import importlib.util
import json
import os
import plistlib
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import originals, shortcuts, viewer
from tests.test_helper import HelperCase
from tests.test_originals import OriginalsCase, make_blank_pdf
from tests.test_shortcuts import TempHome


class GatedGets(HelperCase):
    def get(self, path, headers=None):
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            c.request("GET", path, headers=h)
            r = c.getresponse()
            return r.status, r, r.read()
        finally:
            c.close()

    def upload_text(self, name="Resume – 2024.txt"):
        data = base64.b64encode(b"hello original " + name.encode()).decode()
        status, out = self.post("/upload", {"filename": name, "kind": "Resume", "data_b64": data})
        self.assertEqual(status, 200)
        return out["id"]

    def test_data_json_needs_token(self):
        viewer.build(self.db, backup=False)
        tok = {"X-JobOMatic": self.server.token}
        self.assertEqual(self.get("/data.json")[0], 403)
        self.assertEqual(self.get("/data.json", {"X-JobOMatic": "wrong"})[0], 403)
        self.assertEqual(self.get("/data.json?k=" + self.server.token)[0], 403)  # header only
        self.assertEqual(self.get("/data.json", {**tok, "Sec-Fetch-Site": "cross-site"})[0], 403)
        status, _, body = self.get("/data.json", {**tok, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200)
        db = json.loads(body)["db"]
        self.assertEqual(set(db) - {"templates"}, {"updated", "b64", "texts"})
        js = (self.data_dir / "viewer_data.js").read_text(encoding="utf-8")
        self.assertEqual(db["b64"], re.search(r'b64: "([^"]*)"', js).group(1))
        self.assertTrue(db["templates"])

    def test_data_json_missing_file_404_and_no_cross_site_data_js(self):
        self.assertEqual(self.get("/data.json", {"X-JobOMatic": self.server.token})[0], 404)
        self.assertEqual(self.get("/data.js", {"X-JobOMatic": self.server.token})[0], 404)

    def test_original_gate(self):
        oid = self.upload_text("plain.txt")
        path = f"/original/{oid}"
        self.assertEqual(self.get(path)[0], 403)
        self.assertEqual(self.get(path, {"X-JobOMatic": "nope"})[0], 403)
        self.assertEqual(self.get(path + "?k=nope")[0], 403)
        self.assertEqual(self.get(path, {"X-JobOMatic": self.server.token, "Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.get(path + "?k=" + self.server.token, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.get(path, {"X-JobOMatic": self.server.token})[2], b"hello original plain.txt")
        self.assertEqual(self.get(path + "?k=" + self.server.token)[0], 200)

    def test_content_disposition_unicode(self):
        for name in ("Resume – 2024.txt", "履歴書.txt", "say \"hi\".txt"):
            oid = self.upload_text(name)
            _, resp, _ = self.get(f"/original/{oid}?k={self.server.token}")
            cd = resp.getheader("Content-Disposition")
            cd.encode("latin-1")  # a header must survive latin-1; the old code crashed the client here
            self.assertTrue(cd.isascii(), cd)
            self.assertRegex(cd, r"^attachment; filename=\"[A-Za-z0-9._ -]+\"; filename\*=UTF-8''[A-Za-z0-9%._-]+$")
            from urllib.parse import unquote
            self.assertEqual(unquote(cd.split("filename*=UTF-8''")[1]), name)

    def test_frame_headers_on_every_response(self):
        for path in ("/health", "/nope", "/data.json", "/original/1"):
            _, resp, _ = self.get(path)
            self.assertEqual(resp.getheader("X-Frame-Options"), "DENY", path)
            self.assertEqual(resp.getheader("Content-Security-Policy"), "frame-ancestors 'none'", path)


class AddOriginalGuards(OriginalsCase):
    def test_valid_pdf(self):
        self.assertTrue(self.add("ok.pdf", make_blank_pdf()))

    def test_hidden_file_and_folder_refused(self):
        hidden = self.src / ".ssh"
        hidden.mkdir()
        key = hidden / "id_rsa"
        key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        env = self.src / ".env"
        env.write_text("SECRET=1\n")
        for p in (key, env):
            with self.assertRaisesRegex(ValueError, "hidden"):
                originals.add_original(self.conn, self.data_dir, p, "Other", actor="ai")

    def test_symlink_and_directory_refused(self):
        real = self.source("real.txt", b"plain text")
        link = self.src / "link.txt"
        link.symlink_to(real)
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            originals.add_original(self.conn, self.data_dir, link, "Other", actor="ai")
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            originals.add_original(self.conn, self.data_dir, self.src, "Other", actor="ai")

    def test_wrong_extension_and_missing(self):
        with self.assertRaisesRegex(ValueError, "Unsupported file type"):
            self.add("notes.sh", b"echo hi")
        with self.assertRaisesRegex(ValueError, "No file"):
            originals.add_original(self.conn, self.data_dir, self.src / "gone.pdf", "Other", actor="ai")


class MacGuard(TempHome):
    def test_add_mac_refuses_foreign_app(self):
        self.use("mac")
        target = self.home / "Applications" / "Job-o-Matic.app"
        (target / "Contents").mkdir(parents=True)
        with open(target / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleIdentifier": "com.example.other"}, f)
        with self.assertRaisesRegex(OSError, "not Job-o-Matic"):
            shortcuts._add_mac(target)
        self.assertFalse((target / "Contents" / "MacOS").exists())

    def test_windows_blank_output_keeps_real_error(self):
        self.use("windows")
        fake = mock.Mock(returncode=1, stderr="\n", stdout="")
        with mock.patch.object(shortcuts.subprocess, "run", return_value=fake), \
                self.assertRaisesRegex(OSError, "PowerShell exit 1"):
            shortcuts._add_windows(self.home / "x.lnk")


def load_connect():
    spec = importlib.util.spec_from_file_location("connect_claude_desktop", ROOT / "scripts" / "connect_claude_desktop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ConnectDesktop(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Path(tmp.name) / "Claude" / "claude_desktop_config.json"
        self.cfg.parent.mkdir()
        self.mod = load_connect()
        p = mock.patch.object(self.mod, "config_path", return_value=self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def run_write(self):
        with mock.patch.object(sys, "argv", ["x", "--write"]), mock.patch("builtins.print"):
            self.mod.main()

    def test_bom_and_atomic_write(self):
        self.cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"other": 1}).encode())
        with mock.patch.object(os, "replace", wraps=os.replace) as rep:
            self.run_write()
        self.assertEqual(rep.call_count, 1)
        out = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(out["other"], 1)
        self.assertIn("job-o-matic", out["mcpServers"])
        self.assertEqual([p.name for p in self.cfg.parent.glob("*.tmp")], [])

    def test_null_mcpservers_is_fixed(self):
        self.cfg.write_text('{"mcpServers": null}', encoding="utf-8")
        self.run_write()
        self.assertIn("job-o-matic", json.loads(self.cfg.read_text())["mcpServers"])

    def test_bad_json_clear_error_and_untouched(self):
        self.cfg.write_text("{oops", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.run_write()
        self.assertIn("not valid JSON", str(cm.exception))
        self.assertEqual(self.cfg.read_text(), "{oops")

    def test_mcpservers_wrong_type(self):
        self.cfg.write_text('{"mcpServers": []}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_write()


if __name__ == "__main__":
    unittest.main()
