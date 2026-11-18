import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, store, viewer

SERVER = ROOT / "src" / "jobomatic" / "mcp_server.py"
CONNECT = ROOT / "scripts" / "connect_claude_desktop.py"
TOOLS = {"get_profile", "search", "list", "get", "save", "retire", "list_originals", "read_original",
         "mark_extracted", "qa_open", "build_resume", "resume_data", "schema_guide", "save_many", "add_original"}


def make_db(tmp):
    path = Path(tmp) / "my_data" / "jobomatic.db"  # the bundle layout: the viewer writes its page beside my_data/
    store.new_database(path)
    conn = store.connect(path)
    conn.execute("INSERT INTO people (name, headline, updated_by) VALUES ('Pat', 'Old', 'app')")
    conn.close()
    return path


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        self.conn = store.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_insert_update_and_actor(self):
        new_id = store.save_row(self.conn, "skills", {"person_id": 1, "name": "SQL"}, "ai")
        store.save_row(self.conn, "skills", {"id": new_id, "name": "Python"}, "user")
        actors = [r[0] for r in self.conn.execute("SELECT actor FROM audit WHERE table_name='skills' ORDER BY id")]
        self.assertEqual(actors, ["ai", "ai", "user"])  # the AI insert, its flip to Needs review, then the user edit

    def test_rejects_bad_table_and_column(self):
        with self.assertRaises(ValueError):
            store.save_row(self.conn, "audit", {"actor": "x"}, "ai")
        with self.assertRaises(ValueError):
            store.save_row(self.conn, "originals", {"id": 1, "path": "x"}, "ai")
        with self.assertRaises(ValueError):
            store.save_row(self.conn, "people", {"id": 1, "updated_by": "user"}, "ai")

    def test_update_missing_row_errors(self):
        with self.assertRaises(ValueError):
            store.save_row(self.conn, "people", {"id": 99, "headline": "x"}, "ai")

    def test_stale_version_is_refused_and_nothing_written(self):
        read_at = self.conn.execute("SELECT updated_at FROM people WHERE id=1").fetchone()[0]
        store.save_row(self.conn, "people", {"id": 1, "headline": "user edit"}, "user", read_at)
        with self.assertRaises(store.Changed) as caught:
            store.save_row(self.conn, "people", {"id": 1, "headline": "ai edit"}, "ai", read_at)
        self.assertEqual(caught.exception.current["headline"], "user edit")
        self.assertEqual(self.conn.execute("SELECT headline FROM people WHERE id=1").fetchone()[0], "user edit")

    def test_db_error_rolls_back(self):
        import sqlite3
        with self.assertRaises(sqlite3.Error):
            store.save_row(self.conn, "people", {"id": 1, "status": "Bogus"}, "ai")
        self.assertFalse(self.conn.in_transaction)

    def test_retire(self):
        store.retire_row(self.conn, "people", 1, "ai")
        self.assertEqual(self.conn.execute("SELECT status FROM people").fetchone()[0], "Archived")
        with self.assertRaises(ValueError):
            store.retire_row(self.conn, "settings", 1, "ai")
        with self.assertRaises(ValueError):
            store.retire_row(self.conn, "people", 99, "ai")

    def test_stopwords_dropped(self):
        store.save_row(self.conn, "skills", {"person_id": 1, "name": "Forklift safety"}, "user")
        self.assertEqual([h["source_table"] for h in store.search(self.conn, "the and of a forklift is")], ["skills"])
        with self.assertRaises(ValueError):
            store.search(self.conn, "the and of a is to")

    def test_unanswered_seeded_questions_excluded_unless_asked(self):
        self.assertEqual(store.search(self.conn, "greatest strength weaknesses"), [])
        asked = store.search(self.conn, "greatest strength weaknesses", include_unanswered=True)
        self.assertEqual([h["source_table"] for h in asked], ["qa"])
        self.conn.execute("UPDATE qa SET answer = 'Patience', status = 'Needs review', updated_by = 'user' WHERE sort = 4")
        self.assertEqual([h["source_table"] for h in store.search(self.conn, "greatest strength weaknesses")], ["qa"])

    def test_ai_insert_needs_review_unless_chosen(self):
        ai = store.save_row(self.conn, "skills", {"person_id": 1, "name": "SQL"}, "ai")
        chosen = store.save_row(self.conn, "skills", {"person_id": 1, "name": "Go", "status": "Deprecated"}, "ai")
        user = store.save_row(self.conn, "skills", {"person_id": 1, "name": "C"}, "user")
        status = dict(self.conn.execute("SELECT id, status FROM skills"))
        self.assertEqual((status[ai], status[chosen], status[user]), ("Needs review", "Deprecated", "Verified"))

    def test_editable_columns_exist(self):
        for table, cols in store.EDITABLE_TABLES.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            self.assertLessEqual(cols, have, table)


class McpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = make_db(self.tmp.name)

    def call(self, session, name, args=None):
        return session.call_tool(name, args or {})

    async def run_session(self, fn):
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env={"JOBOMATIC_DB": str(self.db)})
        async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
            await session.initialize()
            return await asyncio.wait_for(fn(session), 60)

    @staticmethod
    def data(result):
        out = result.structured_content
        if out is None:
            return json.loads(result.content[0].text)
        return out["result"] if list(out) == ["result"] else out

    async def test_tools_listed(self):
        async def go(s):
            return {t.name for t in (await s.list_tools()).tools}
        self.assertEqual(await self.run_session(go), TOOLS)

    async def test_save_get_audit_retire(self):
        async def go(s):
            saved = await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "New"}})
            self.assertFalse(saved.is_error)
            got = self.data(await self.call(s, "get", {"table": "people", "id": 1}))
            self.assertEqual(got["headline"], "New")
            bad = await self.call(s, "save", {"table": "originals", "row": {"id": 1, "path": "x"}})
            self.assertTrue(bad.is_error)
            self.assertIn("Not editable", bad.content[0].text)
            await self.call(s, "save", {"table": "skills", "row": {"person_id": 1, "name": "Forklift safety"}})
            found = self.data(await self.call(s, "search", {"text": "We need forklift experience."}))
            self.assertEqual((found[0]["source_table"], found[0]["source_id"]), ("skills", 1))
            self.assertTrue((await self.call(s, "search", {"text": " ... "})).is_error)
            guide = self.data(await self.call(s, "schema_guide"))
            self.assertIn("rule", {r["kind"] for r in guide})
            doc = self.data(await self.call(s, "resume_data", {}))
            self.assertEqual((doc["track"], doc["person"]["headline"], doc["employers"]), ("Original", "New", []))
            await self.call(s, "retire", {"table": "people", "id": 1})
            self.assertEqual(self.data(await self.call(s, "get", {"table": "people", "id": 1}))["status"], "Archived")
            profile = self.data(await self.call(s, "get_profile"))
            self.assertIsNone(profile["person"])  # the only person is archived
            nope = await self.call(s, "build_resume", {"template": "x"})
            self.assertTrue(nope.is_error)
            self.assertIn("ValueError", nope.content[0].text)  # unknown template
        await self.run_session(go)
        conn = store.connect(self.db)
        actors = [r[0] for r in conn.execute("SELECT actor FROM audit WHERE table_name='people' AND op='update' ORDER BY id")]
        conn.close()
        self.assertEqual(actors, ["ai", "ai"])

    async def test_demo_profile_and_v4_tables(self):
        demo_db = Path(self.tmp.name) / "demo" / "my_data" / "jobomatic.db"
        demo_db.parent.mkdir(parents=True)
        demo.new_demo_database(demo_db)
        self.db = demo_db

        async def go(s):
            profile = self.data(await self.call(s, "get_profile"))
            for key in ("employers", "positions", "items", "resume_lines", "skills", "education"):
                self.assertTrue(profile[key], key)
            for old in ("experience", "accomplishments", "records"):
                self.assertNotIn(old, profile)
            self.assertTrue(any(i["metrics"] for i in profile["items"]))
            emp = self.data(await self.call(s, "save", {"table": "employers", "row": {"person_id": 1, "name": "Acme"}}))
            pos = self.data(await self.call(s, "save", {"table": "positions", "row": {
                "person_id": 1, "employer_id": emp["id"], "title": "Lead", "start_date": "2025-01"}}))
            item = self.data(await self.call(s, "save", {"table": "items", "row": {
                "person_id": 1, "position_id": pos["id"], "kind": "Achievement", "detail": "Cut waste."}}))
            metric = self.data(await self.call(s, "save_many", {"table": "item_metrics", "rows": [
                {"item_id": item["id"], "label": "Waste cut", "value": "12", "unit": "%"}]}))
            self.assertEqual(len(metric), 1)
            orig = self.data(await self.call(s, "list", {"table": "originals", "limit": 1}))[0]
            link = await self.call(s, "save", {"table": "item_originals", "row": {"item_id": item["id"], "original_id": orig["id"]}})
            self.assertFalse(link.is_error)
            doc = self.data(await self.call(s, "resume_data", {}))
            acme = [m for m in doc["employers"] if m["name"] == "Acme"][0]
            self.assertEqual(acme["positions"][0]["items_without_lines"][0]["metrics"][0]["label"], "Waste cut")
            for table, row_id in (("item_originals", self.data(link)["id"]), ("item_metrics", metric[0]["id"]),
                                  ("items", item["id"]), ("positions", pos["id"]), ("employers", emp["id"])):
                self.assertFalse((await self.call(s, "retire", {"table": table, "id": row_id})).is_error, table)
        await self.run_session(go)

    async def test_qa_open(self):
        async def go(s):
            return self.data(await self.call(s, "qa_open"))
        rows = await self.run_session(go)
        self.assertEqual([r["sort"] for r in rows], list(range(1, 11)))

    async def test_save_rebuilds_the_viewer(self):
        viewer.build(self.db)
        data_js = self.db.parent / "viewer_data.js"
        os.utime(data_js, ns=(10**9, 10**9))

        async def go(s):
            await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "Fresh"}})
            first = data_js.stat().st_mtime_ns
            os.utime(data_js, ns=(10**9, 10**9))
            await self.call(s, "retire", {"table": "people", "id": 1})
            return first, data_js.stat().st_mtime_ns
        first, second = await self.run_session(go)
        self.assertGreater(first, 10**9)
        self.assertGreater(second, 10**9)

    async def test_save_returns_the_full_row_and_ai_rows_need_review(self):
        async def go(s):
            return self.data(await self.call(s, "save", {"table": "skills", "row": {"person_id": 1, "name": "SQL"}}))
        row = await self.run_session(go)
        self.assertEqual((row["id"], row["name"], row["status"], row["person_id"]), (1, "SQL", "Needs review", 1))
        self.assertTrue(row["updated_at"])

    async def test_conflict_error_carries_the_current_row(self):
        async def go(s):
            row = self.data(await self.call(s, "get", {"table": "people", "id": 1}))
            await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "first"},
                                        "expected_updated_at": row["updated_at"]})
            return await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "second"},
                                               "expected_updated_at": row["updated_at"]})
        result = await self.run_session(go)
        self.assertTrue(result.is_error)
        self.assertIn('"headline": "first"', result.content[0].text)

    async def test_save_with_stale_version_errors(self):
        async def go(s):
            row = self.data(await self.call(s, "get", {"table": "people", "id": 1}))
            await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "first"},
                                        "expected_updated_at": row["updated_at"]})
            return await self.call(s, "save", {"table": "people", "row": {"id": 1, "headline": "second"},
                                               "expected_updated_at": row["updated_at"]})
        result = await self.run_session(go)
        self.assertTrue(result.is_error)
        self.assertIn("changed since you read it", result.content[0].text)

    async def test_read_original_not_extracted(self):
        conn = store.connect(self.db)
        conn.execute("INSERT INTO originals (person_id, kind, path, sha256, bytes, updated_by) VALUES (1, 'Resume', 'originals/resumes/a.pdf', 'abc', 3, 'app')")
        conn.close()

        async def go(s):
            first = self.data(await self.call(s, "read_original", {"id": 1}))
            self.assertIsNone(first["text"])
            self.assertIn("not been extracted", first["message"])
            bad = await self.call(s, "mark_extracted", {"id": 1, "state": "Finished"})
            self.assertTrue(bad.is_error)
            await self.call(s, "mark_extracted", {"id": 1, "state": "Partly"})
            await self.call(s, "mark_extracted", {"id": 1, "state": "Text read"})
            await self.call(s, "mark_extracted", {"id": 1, "state": "Partly"})
            return self.data(await self.call(s, "list_originals"))
        self.assertEqual((await self.run_session(go))[0]["extracted"], "Partly")


class ConnectTest(unittest.TestCase):
    def test_write_merges_and_backs_up(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "APPDATA": home}
            cfg = (Path(home) / "AppData" / "Claude" if sys.platform == "win32" else
                   Path(home) / ("Library/Application Support/Claude" if sys.platform == "darwin" else ".config/Claude"))
            if sys.platform == "win32":
                cfg = Path(home) / "Claude"
            cfg.mkdir(parents=True)
            file = cfg / "claude_desktop_config.json"
            file.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
            out = subprocess.run([sys.executable, str(CONNECT), "--write"], env=env, capture_output=True, text=True, check=True)
            self.assertIn("job-o-matic", out.stdout)
            merged = json.loads(file.read_text())
            self.assertEqual(set(merged["mcpServers"]), {"other", "job-o-matic"})
            self.assertEqual(merged["theme"], "dark")
            entry = merged["mcpServers"]["job-o-matic"]
            self.assertTrue(entry["args"][0].endswith("mcp_server.py"))
            self.assertTrue(entry["env"]["JOBOMATIC_DB"].endswith("jobomatic.db"))
            self.assertEqual(len(list(cfg.glob("claude_desktop_config.json.*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
