import base64
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from jobomatic import demo, originals, store, viewer

LOCAL_OK = ("#", "data:", "http://", "https://", "mailto:")
TAGLINE = ("Your career data, for your AI to use. Connect an MCP app (Claude Desktop, for example) or copy a prompt; "
           "the screens here are for checking and fixing.")
NEVER_INVENT = "Use only the facts below; never invent anything."


def contrast(a, b):
    """WCAG 2 contrast ratio of two #RRGGBB colors."""
    def lum(c):
        ch = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        ch = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ViewerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data_dir = self.root / "my_data"
        self.db = self.data_dir / "jobomatic.db"
        demo.new_demo_database(self.db)
        self.html_path = viewer.build(self.db)
        self.html = self.html_path.read_text(encoding="utf-8")

    def test_both_files_written(self):
        self.assertEqual(self.html_path, self.root / viewer.HTML_NAME)
        self.assertTrue((self.data_dir / "viewer_data.js").is_file())
        self.assertEqual([p.name for p in self.data_dir.glob(".tmp_*")], [])

    def test_no_local_references(self):
        refs = re.findall(r'(?:src|href)\s*=\s*"([^"]*)"', self.html)
        self.assertTrue(refs)
        self.assertEqual([r for r in refs if not r.startswith(LOCAL_OK)], [])
        self.assertNotIn("url(\"fonts/", self.html)
        self.assertNotRegex(self.html, r'<link(?![^>]*href="data:)')  # only the inlined favicon link may remain
        self.assertNotRegex(self.html, r"<script[^>]+src=")

    def test_fetch_only_in_edit_mode(self):
        app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertEqual(app.count("fetch("), 1)
        guarded = app.index('if (!EDIT) return Promise.reject(')
        self.assertLess(guarded, app.index("fetch("))
        self.assertLess(0, guarded - app.index("function http("))
        self.assertLess(guarded - app.index("function http("), 80)  # the guard is the first line of http()
        self.assertIn("window.SQL_WASM_B64=", self.html)  # sql.js gets wasmBinary, so it never fetches the .wasm

    def test_one_h1_and_one_status_region(self):
        self.assertEqual(self.html.count("<h1"), 1)
        self.assertRegex(self.html, r'<h1 class="brand"><img class="wordmark wm-light"')
        self.assertEqual(len(re.findall(r'role(?:=|: )"status"', self.html)), 1)  # page.html and the inlined app.js
        self.assertIn('<div id="status" class="sr-only" role="status">', self.html)

    def test_every_dialog_opens_through_one_routine(self):
        app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertEqual(app.count("showModal("), 1)
        self.assertEqual(app.count('h("dialog"'), 1)
        opener = app[app.index("function openDialog("):]
        self.assertIn("showModal(", opener[:opener.index("\n  }")])
        self.assertEqual(app.count("makeDialog("), 5)  # its definition + prompt, Create Resume, details, Remove
        self.assertEqual(app.count("openDialog("), 5)

    def test_header_says_it_is_for_an_ai_in_both_modes(self):
        page = (viewer.WEB_DIR / "page.html").read_text(encoding="utf-8")  # edit mode serves page.html as it is
        for text in (page, self.html):
            header = text[text.index('<header class="top">'):text.index("</header>")]
            self.assertIn(f'<p class="tagline">{TAGLINE} <a href="#how" id="how-link">How it works</a></p>', header)

    def test_tagline_and_link_pass_aa_in_light_and_dark(self):
        css = (viewer.WEB_DIR / "tokens.css").read_text(encoding="utf-8")
        light = re.search(r":root\{([^}]*)\}", css)[1]
        dark = re.search(r':root\[data-theme="dark"\]\{([^}]*)\}', css)[1]
        for name, block in (("light", light), ("dark", dark)):
            tok = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", block))
            for fg in ("text-muted", "accent", "text"):
                with self.subTest(theme=name, fg=fg):
                    self.assertGreaterEqual(contrast(tok[fg], tok["surface-raised"]), 4.5)
        styles = (viewer.WEB_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".tagline{grid-column:1/-1;margin:0;font-size:15px;line-height:1.4;color:var(--text-muted)}", styles)

    def test_how_it_works_is_a_header_link_not_a_tab(self):
        app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
        tabs = re.search(r"var TABS = \[(.*?)\];", app, re.DOTALL)[1]
        self.assertNotIn("How it works", tabs)
        self.assertNotIn('"how"', tabs)
        self.assertIn('["ai", "For the AI"]', tabs)
        self.assertIn('var PAGES = ["how"];', app)  # #how still opens it
        self.assertIn('getElementById("how-link").addEventListener("click"', app)

    def test_ai_output_kind_offered(self):
        app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('var ORIGINAL_KINDS = ["Resume", "Job description", "Review", "Recommendation", "AI output", "Other"];', app)
        self.assertIn("choices(\"select\", ORIGINAL_KINDS, upload.kind, true)", app)

    def test_quick_draft_ships_renderer_and_all_styles(self):
        js = (self.data_dir / "viewer_data.js").read_text(encoding="utf-8")  # edit mode loads the same file as /data.js
        self.assertIn("window.JOBOMATIC_TEMPLATES = ", js)
        for name in ("executive", "navy_bar", "two_column", "structured", "genz"):
            self.assertIn(f'"{name}": "\\u003c!DOCTYPE html>', js)
        self.assertIn("root.JOM.renderResume = renderResume;", self.html)
        self.assertIn('id="create-resume"', self.html)
        self.assertNotIn(str(self.data_dir.resolve()), js)  # no build-machine path in shipped files
        self.assertNotIn(str(self.data_dir.resolve()), self.html)

    def test_view_banner_only_in_view_only_file(self):
        self.assertEqual(self.html.count('<p class="view-banner">View only: '), 1)
        self.assertNotIn("view-banner", (viewer.WEB_DIR / "page.html").read_text(encoding="utf-8"))  # edit mode serves page.html

    def test_ai_helpers_toggle_stored_like_the_theme(self):
        page = (viewer.WEB_DIR / "page.html").read_text(encoding="utf-8")
        head = page[:page.index("</head>")]
        self.assertIn('localStorage.setItem("jobomatic.ai"', head)
        self.assertIn("  jomAi();\n", head)  # before first paint, like jomTheme()
        self.assertIn(".no-ai .ai-btn{display:none}", (viewer.WEB_DIR / "styles.css").read_text(encoding="utf-8"))
        self.assertIn('id: "show-ai", checked: window.jomAi(),', (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8"))

    def test_narrow_cards_stack_and_tab_arrows_have_room(self):
        css = (viewer.WEB_DIR / "styles.css").read_text(encoding="utf-8")
        narrow = re.search(r"@media \(max-width:800px\)\{(.*?)\n\}", css, re.DOTALL)[1]
        self.assertIn(".row-top{flex-direction:column", narrow)
        self.assertIn(".line-item>.card{flex-direction:column", narrow)
        pad = re.search(r"\.tabs-wrap\.overflow\{padding:0 (\d+)px\}", css)[1]
        self.assertIn(f"var TAB_ARROW = {pad};", (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8"))
        self.assertIn(f".tabs-arrow{{display:none;position:absolute;top:0;bottom:0;z-index:1;width:{pad}px", css)

    def test_no_user_facing_track_word(self):
        """The UI says "version"; "track" stays only in SQL, ids and column names."""
        app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
        strings = re.findall(r'"((?:[^"\\\n]|\\.)*)"', app)
        prose = [x for x in strings if " " in x and not re.search(r"\b(SELECT|FROM|WHERE|ORDER BY)\b", x)]
        self.assertTrue(any("version" in x for x in prose))
        self.assertEqual([x for x in prose if re.search(r"(?i)\btracks?\b", x)], [])
        page = (viewer.WEB_DIR / "page.html").read_text(encoding="utf-8")
        self.assertNotRegex(re.sub(r"<script.*?</script>|<[^>]+>", " ", page, flags=re.DOTALL), r"(?i)\btracks?\b")

    def test_size_sane(self):
        self.assertLess(self.html_path.stat().st_size, 15 * 1024 * 1024)

    def test_data_is_a_database_with_the_demo_person(self):
        js = (self.data_dir / "viewer_data.js").read_text(encoding="utf-8")
        b64 = re.search(r'b64: "([A-Za-z0-9+/=]+)"', js)[1]
        snap = self.root / "snap.db"
        snap.write_bytes(base64.b64decode(b64))
        self.assertEqual(snap.read_bytes()[18:20], b"\x01\x01")  # rollback journal, not WAL
        conn = sqlite3.connect(snap)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT name FROM people").fetchone()[0], "Odalys Brannigan-Voss")
        finally:
            conn.close()
        self.assertIn(js.strip(), self.html.replace("<\\/", "</"))

    def test_snapshot_has_no_fts5_search_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snap.db"
            snap.write_bytes(viewer.snapshot_bytes(self.db))
            conn = sqlite3.connect(snap)
            try:
                rows = conn.execute(
                    "SELECT type, name FROM sqlite_master WHERE name LIKE '%search_index%' OR sql LIKE '%search_index%'"
                ).fetchall()
            finally:
                conn.close()
        self.assertEqual(rows, [])

    def test_only_active_headshot_keeps_its_image(self):
        conn = store.connect(self.db)
        for i, status in enumerate(("Deprecated", "Active")):
            conn.execute("INSERT INTO images (person_id, mime, bytes, sha256, image, status, updated_by)"
                         " VALUES (1, 'image/png', 4, ?, X'89504E47', ?, 'app')", (f"sha{i}", status))
        conn.close()
        snap = self.root / "snap.db"
        snap.write_bytes(viewer.snapshot_bytes(self.db))
        conn = sqlite3.connect(snap)
        try:
            rows = dict(conn.execute("SELECT status, length(image) FROM images").fetchall())
        finally:
            conn.close()
        self.assertEqual(rows, {"Deprecated": 0, "Active": 4})
        conn = store.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM images WHERE length(image) = 4").fetchone()[0], 2)
        finally:
            conn.close()


# Loads app.js without a page (window.JOM_TEST) and the demo data; each script then prints its JSON.
NODE_HEAD = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const [web, dataJs] = process.argv.slice(1);
globalThis.window = globalThis;
window.addEventListener = () => {};
window.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.location = { protocol: "http:" };
window.JOM_TEST = {};
vm.runInThisContext(fs.readFileSync(dataJs, "utf8"));
const initSqlJs = require(path.join(web, "vendor", "sql-wasm.js"));
require(path.join(web, "app.js"));
initSqlJs({ wasmBinary: fs.readFileSync(path.join(web, "vendor", "sql-wasm.wasm")) }).then((SQL) => {
  const T = window.JOM_TEST;
  T.load(SQL, window.JOBOMATIC_DB);
"""
NODE_PROMPTS = NODE_HEAD + r"""
  const P = T.prompts;
  const out = { qa: P.qa(1), lines: P.lines(1), create: P.create("executive", "Original", "Forklift lead, nights") };
  Object.keys(P.sections).forEach((k) => { out["fill_" + k] = P.fill(k); });
  process.stdout.write(JSON.stringify(out));
});
"""
# Every prompt ends with the "Check your connection" block: from JOBOMATIC_INFO when the app serves the page.
NODE_CONN = NODE_HEAD + r"""
  const P = T.prompts, kinds = {
    pip: { version: "1.2.0", data_folder: "/home/u/.local/share/job-o-matic", db_path: "/home/u/.local/share/job-o-matic/jobomatic.db",
      install_type: "pip", mcp: { name: "job-o-matic", command: "job-o-matic-mcp", args: [], display: "job-o-matic-mcp", transport: "stdio" } },
    zip: { version: "1.2.0", data_folder: "C:\\Jobs\\Job-o-Matic\\my_data", db_path: "C:\\Jobs\\Job-o-Matic\\my_data\\jobomatic.db",
      install_type: "zip", mcp: { name: "job-o-matic", command: "C:\\Jobs\\Job-o-Matic\\python\\python.exe", args: ["C:\\Jobs\\Job-o-Matic\\app\\src\\jobomatic\\mcp_server.py"],
        display: "C:\\Jobs\\Job-o-Matic\\python\\python.exe C:\\Jobs\\Job-o-Matic\\app\\src\\jobomatic\\mcp_server.py", transport: "stdio" } }
  };
  const out = {};
  Object.keys(kinds).concat(["none"]).forEach((k) => {
    window.JOBOMATIC_INFO = kinds[k];
    out[k] = { qa: P.qa(1), lines: P.lines(1), create: P.create("executive", "Original", "Forklift lead"), fill: P.fill("skills") };
  });
  process.stdout.write(JSON.stringify(out));
});
"""
# Quick draft: only the ticked lines (skip = unticked ids) reach the resume; job-ad words are marked.
NODE_DRAFT = NODE_HEAD + r"""
  require(path.join(web, "resume_render.js"));
  globalThis.document = { createElement: (t) => ({ tagName: t, children: [], appendChild(c) { this.children.push(c); return c; } }),
    createTextNode: (s) => ({ text: s }) };
  const D = T.draft, skip = JSON.parse(process.env.SKIP);
  const words = D.words("Reduce costs, with fewer docks");
  process.stdout.write(JSON.stringify({
    all: D.html("genz", "Original", {}), some: D.html("genz", "Original", skip), words: Object.keys(words),
    marks: D.marked("Cut costs on 3 Docks", words).filter((p) => typeof p === "object").map((p) => p.children[0].text)
  }));
});
"""
# Select defaults and the "Discard your changes?" guard (window.confirm is stubbed; asks are counted).
NODE_FORMS = NODE_HEAD + r"""
  const F = T.forms, out = { asks: 0 };
  let answer = false;
  window.confirm = (text) => { out.asks += 1; out.text = text; return answer; };
  out.single = F.choices("select", ["Active", "Deprecated"], "", true);
  out.many = F.choices("select", ["Verified", "Needs review", "Deprecated"], "", true);
  out.existing = F.choices("select", ["Verified", "Needs review", "Deprecated"], "Deprecated", false);
  out.job_new = F.choices("position", [], "", true)[1];
  out.job_edit = F.choices("position", [], "", false)[1];
  out.job_labels = F.choices("position", [], "", true)[0].map((o) => o[1]);
  out.parent_default = F.choices("parent", [1], "", true)[1];
  F.edit("qa:1");
  F.drafts["qa:1"] = { base: { answer: "" }, typed: { answer: "" } };
  out.clean_leaves = F.leave();
  F.drafts["qa:1"] = { base: { answer: "" }, typed: { answer: "Half typed" } };
  out.dirty_kept = !F.leave() && F.drafts["qa:1"].typed.answer === "Half typed";
  answer = true;
  out.dirty_discarded = F.leave() && !("qa:1" in F.drafts);
  process.stdout.write(JSON.stringify(out));
});
"""
# Renders every tab in edit mode into a stand-in DOM (node has none) and reports what a screen reader would meet.
NODE_DOM = 'globalThis.HELPER_TOKEN = "t";' + NODE_HEAD + r"""
  window.jomAi = () => true;
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.className = ""; }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    appendChild(c) { this.children.push(c); return c; }
    addEventListener() {}
    get lastChild() { return this.children[this.children.length - 1]; }
    get rows() { return this.children; }  // table rows (the guide); a textarea's rows is set below
    set rows(v) { this.attrs.rows = String(v); }
    get value() { return this.attrs.value === undefined ? "" : this.attrs.value; }  // inputs keep their value like a page's
    set value(v) { this.attrs.value = String(v); }
  }
  globalThis.document = { createElement: (t) => new El(t), createTextNode: (s) => ({ text: s }) };
  window.AI_GUIDE = "# Guide\n## Part\nSome text.";
  const all = [], walk = (n) => { if (n instanceof El) { all.push(n); n.children.forEach(walk); } };
  const text = (n) => n instanceof El ? n.children.map(text).join("") : n && n.text !== undefined ? n.text : "";
"""
# Footer: data folder and MCP command each get a Copy button; version shown; nothing without the app's info.
NODE_FOOTER = NODE_DOM + r"""
  const box = new El("div");
  globalThis.document.getElementById = () => box;
  const run = () => { box.children = []; T.footer(); return box; };
  window.JOBOMATIC_INFO = undefined;
  const none = run().children.length;
  window.JOBOMATIC_INFO = { version: "1.2.0", data_folder: "/d", db_path: "/d/jobomatic.db", install_type: "pip",
    mcp: { name: "job-o-matic", display: "job-o-matic-mcp" } };
  const b = run();
  all.length = 0;
  walk(b);
  process.stdout.write(JSON.stringify({ none, text: text(b), buttons: all.filter((n) => n.tagName === "BUTTON").map((n) => n.attrs["aria-label"]) }));
});
"""
# The profile and skills forms (edit mode, stand-in DOM): field order = Tab order, names, work authorization, phone styles.
NODE_PROFILE = NODE_DOM + r"""
  require(path.join(web, "resume_render.js"));
  const sub = (n, pred) => !(n instanceof El) ? [] : [].concat(pred(n) ? [n] : [], ...n.children.map((c) => sub(c, pred)));
  const roots = (view) => [].concat(T.views[view]());
  const person = roots("profile").flatMap((n) => sub(n, (x) => /^people:/.test(x.attrs["data-key"] || "")))[0].attrs["data-key"];
  T.forms.edit(person);
  const profile = roots("profile").flatMap((n) => sub(n, (x) => x.tagName === "FORM"))[0];
  const controls = sub(profile, (x) => /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(x.tagName));
  const byName = (nm) => controls.find((x) => x.attrs.name === nm);
  const select = (nm) => sub(byName(nm), (x) => x.tagName === "OPTION").map((o) => o.attrs.value);
  const phones = {};
  ["paren", "dash", "dot", "intl"].forEach((st) => { phones[st] = window.JOM.formatPhone("+15551234567", st); });
  const wrapOf = (nm) => sub(profile, (x) => x.tagName === "DIV" && x.children.some((c) => c === byName(nm)))[0];
  T.forms.edit("new:skills");
  const skillsNew = roots("profile").flatMap((n) => sub(n, (x) => x.tagName === "FORM"))[0];
  const cat = sub(skillsNew, (x) => x.tagName === "SELECT" && x.attrs.name === "category")[0];
  process.stdout.write(JSON.stringify({
    order: controls.map((x) => x.attrs.name || text(x)),
    required: controls.filter((x) => x.attrs.required !== undefined).map((x) => x.attrs.name),
    tag: { work_auth_status: byName("work_auth_status").tagName, first_name: byName("first_name").tagName },
    status_options: select("work_auth_status"),
    help: text(wrapOf("work_auth_status")),
    note_label: text(wrapOf("work_authorization").children[0]),
    note_hidden: wrapOf("work_authorization").hidden === true,
    skill_options: sub(cat, (x) => x.tagName === "OPTION").map((o) => o.attrs.value),
    phones,
    other: [window.JOM.formatPhone("+442079460958", "paren"), window.JOM.formatPhone("5551234567", "dash"),
      window.JOM.formatPhone("(555) 123-4567", "intl"), window.JOM.formatPhone("+353 1 234 5678", "dot"), window.JOM.formatPhone("n/a", "paren"),
      window.JOM.formatPhone("", "paren")],
    card_phone: T.phone.format("+15551234567"),
    name: T.phone.name({ first_name: "Ada", last_name: "Lovelace", full_name: "Ada Lovelace" }),
    work_auth: [T.phone.workAuth({ work_auth_status: "Authorized", work_auth_country: "United States" }),
      T.phone.workAuth({ work_auth_status: "Other", work_authorization: "Student visa", work_auth_country: "Canada" })]
  }));
});
"""
NODE_A11Y = NODE_DOM + r"""
  Object.keys(T.views).forEach((k) => {  // "how" is prose: its sample You/AI/App markers are words, not row markers
    if (k !== "how") [].concat(T.views[k]()).forEach(walk);
  });
  const tag = (t) => all.filter((n) => n.tagName === t);
  const shown = all.length;
  T.forms.edit("qa:1");  // an open form: its Remove button is named after the item
  [].concat(T.views.qa()).forEach(walk);
  const formRemove = all.slice(shown).filter((n) => n.tagName === "FORM").map((f) => {
    const found = [], dig = (n) => { if (n instanceof El) { found.push(n); n.children.forEach(dig); } };
    dig(f);
    return found.filter((n) => /^Remove /.test(n.attrs["aria-label"] || "")).map((n) => n.attrs["aria-label"]);
  });
  process.stdout.write(JSON.stringify({
    form_remove: formRemove,
    show_ai: tag("INPUT").filter((n) => n.attrs.id === "show-ai").length,
    labels: all.map((n) => n.attrs["aria-label"]).filter((x) => x),
    h1: tag("H1").length,
    who: all.filter((n) => /^who /.test(n.className)).map((n) => [n.attrs.role, n.attrs["aria-label"], n.attrs.title]),
    line_lists: tag("UL").filter((n) => /sub-lines/.test(n.className)).map((n) => n.children.map((c) => c.tagName)),
    open_links: tag("A").filter((n) => n.attrs.download).map((n) => n.attrs["aria-label"]),
    filter_label: tag("LABEL").filter((n) => n.attrs.for === "track-filter").map((n) => n.children[0].children[0].text)
  }));
});
"""
# v0.2.1: Remove asks first, removed rows get Restore, one-off items show one date,
# an original's text lines can be added, "Facts taken out" has each label once, the upload offers "AI output".
NODE_V021 = NODE_DOM + r"""
  T.state.showRetired = true;
  T.state.textOpen = {};
  ["items", "originals"].forEach((k) => [].concat(T.views[k]()).forEach(walk));
  const labels = all.map((n) => n.attrs["aria-label"]).filter((x) => x);
  const tag = (t) => all.filter((n) => n.tagName === t);
  const D = T.dates, F = T.forms;
  const extracted = (v) => F.choices("select", F.extracted({ extracted: v }), v, false)[0].map((o) => o[1]);
  process.stdout.write(JSON.stringify({
    restore: labels.filter((x) => /^Restore /.test(x)),
    remove: labels.filter((x) => /^Remove /.test(x)),
    question: T.remove.question("Branch of the Year"),
    live: T.remove.live("items", { id: Number(process.env.GONE), status: "Deprecated" }),
    live_qa: T.remove.live("qa", { id: 999, status: "Deprecated", answer: "" }),
    dates: [D.record("2016-03", null), D.record("2016-03", "2016-03"), D.record("2024-01", "2024-12"), D.record(null, "2019"),
      D.job("2023-03", null)],
    record_meta: tag("ARTICLE").filter((n) => /^items:/.test(n.attrs["data-key"] || "")).map(text),
    kinds: tag("SELECT").filter((n) => n.attrs.id === "up-kind").map((s) => s.children.map(text)),
    add_acc: labels.filter((x) => /^Add as item: /.test(x)).length,
    add_line: labels.filter((x) => /^Add as resume line: /.test(x)).length,
    job_pick: tag("SELECT").filter((n) => /^text-job-/.test(n.attrs.id || "")).length,
    extracted_text_read: extracted("Text read"), extracted_not_yet: extracted("Not yet"), extracted_done: extracted("Done"),
    tabs: T.tabs.map((t) => t[1]),
    never: T.neverInvent
  }));
});
"""


# Schema v4 screens: employers with their positions, one Items view (children indented, "Not tied to a job"),
# numbers, attachments, the used-by list on an original, and the date warning (row and form).
NODE_V4 = NODE_DOM + r"""
  T.state.showRetired = true;
  const sub = (n, pred) => { const out = []; const dig = (x) => { if (x instanceof El) { if (pred(x)) out.push(x); x.children.forEach(dig); } }; dig(n); return out; };
  const cls = (n, c) => new RegExp("(^| )" + c + "( |$)").test(n.className);
  const render = (view) => { const nodes = [].concat(T.views[view]()); return { nodes, find: (pred) => nodes.flatMap((n) => sub(n, pred)) }; };
  const exp = render("experience");
  const employers = exp.find((n) => n.attrs["data-employer"]).map((sec) => ({
    text: text(sec).slice(0, 40),
    positions: sub(sec, (n) => /^positions:/.test(n.attrs["data-key"] || "")).length,
    add: sub(sec, (n) => /^Add a position at /.test(n.attrs["aria-label"] || "")).map((n) => n.attrs["aria-label"])
  }));
  const items = render("items");
  const groups = items.find((n) => n.attrs["data-position"]).map((g) => g.attrs["data-position"]);
  const nodeOf = (id) => items.find((n) => cls(n, "item-node") && n.children[0].attrs["data-key"] === "items:" + id)[0];
  const insideOf = (id) => { const li = nodeOf(id); return li ? sub(li, (n) => cls(n, "item-children")).flatMap((u) => u.children.map((c) => c.children[0].attrs["data-key"])) : null; };
  const loose = items.find((n) => n.attrs["data-position"] === "none").flatMap((g) => sub(g, (n) => /^items:/.test(n.attrs["data-key"] || "")).map((n) => n.attrs["data-key"]));
  const W = Number(process.env.WARN);
  const rowWarn = sub(nodeOf(W), (n) => cls(n, "date-warn") && !n.attrs["aria-live"]).map(text);
  const okWarn = sub(nodeOf(15).children[0], (n) => cls(n, "date-warn") && !n.attrs["aria-live"]).map(text);
  T.forms.edit("items:" + W);
  const editing = render("items");
  const formWarn = editing.find((n) => cls(n, "date-warn") && n.attrs["aria-live"]).map((n) => n.textContent);  // set after build, not a child
  const formFields = editing.find((n) => n.tagName === "FORM").flatMap((f) => sub(f, (n) => n.attrs.name)).map((n) => n.attrs.name);
  const selectOpts = (name) => editing.find((n) => n.tagName === "SELECT" && n.attrs.name === name).flatMap((s) => s.children.map(text));
  T.forms.edit("new:positions");
  T.state.newDefaults = { employer_id: String(process.env.EMP), status: "Verified" };
  const adding = render("experience").find((n) => n.tagName === "FORM").length;
  T.forms.edit("test");
  const labels = items.find((n) => n.attrs["aria-label"]).map((n) => n.attrs["aria-label"]);
  const orig = render("originals");
  const D = T.dates;
  process.stdout.write(JSON.stringify({
    employers, groups, in15: insideOf(15), in1: insideOf(1), loose, rowWarn, okWarn, formWarn, formFields,
    parents: selectOpts("parent_item_id"), kinds: selectOpts("kind"), jobs: selectOpts("position_id"), adding,
    numbers: items.find((n) => /^item_metrics:/.test(n.attrs["data-key"] || "")).length,
    files: items.find((n) => /^item_originals:/.test(n.attrs["data-key"] || "")).length,
    add_number: labels.filter((x) => /^Add a number to /.test(x)).length,
    attach: labels.filter((x) => /^Attach the chosen original to /.test(x)).length,
    used_by: orig.find((n) => cls(n, "used-by-list")).length,
    warn: [D.warning({ start_date: "2019", end_date: null }, { start_date: "2020-03", end_date: "2022-05" }),
      D.warning({ start_date: "2021-06", end_date: "2023" }, { start_date: "2020-03", end_date: "2022-05" }),
      D.warning({ start_date: "2022-06", end_date: null }, { start_date: "2020-03", end_date: "2022-05" }),
      D.warning({ start_date: "2020", end_date: "2022" }, { start_date: "2020-03", end_date: "2022-05" }),
      D.warning({ start_date: null, end_date: null }, { start_date: "2020-03", end_date: "2022-05" }),
      D.warning({ start_date: "1990", end_date: null }, null)]
  }));
});
"""


def viewer_js_const(name):
    app = (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8")
    return json.loads(re.search(rf'var {name} = ("[^"]*");', app)[1])


PROFILE_KEYS = {"person", "links", "employers", "positions", "items", "skills", "education"}


@unittest.skipUnless(shutil.which("node"), "node is not installed: the prompt checks run app.js in node")
class PromptCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.data_dir = Path(tmp.name) / "my_data"
        db = cls.data_dir / "jobomatic.db"
        demo.new_demo_database(db)
        conn = store.connect(db)
        try:
            cls.big_id = originals.add_original_bytes(conn, cls.data_dir, "notes.txt", ("Ran the dock. " * 2000).encode(),
                                                      "Other", actor="app", title="Long notes")
            # An item dated before its job began: saving works (the app only warns).
            cls.warn_id = conn.execute("SELECT min(id) FROM items WHERE position_id = 2").fetchone()[0]
            store.save_row(conn, "items", {"id": cls.warn_id, "start_date": "2015"}, "user")
            kind, title, detail = conn.execute("SELECT kind, title, detail FROM items WHERE id = ?", (cls.warn_id,)).fetchone()
            cls.warned_label = f"{kind}: {title or detail}"[:60]
            cls.two_jobs = conn.execute("SELECT employer_id FROM positions GROUP BY employer_id HAVING count(*) > 1").fetchone()[0]
            cls.gone = conn.execute("SELECT id, title, status FROM items WHERE kind = 'Review'").fetchone()
            store.retire_row(conn, "items", cls.gone["id"], "user")  # a removed row, for Restore
            cls.employers = [r[0] for r in conn.execute(
                "SELECT DISTINCT e.name FROM employers e JOIN positions p ON p.employer_id = e.id WHERE p.status <> 'Deprecated'")]
        finally:
            conn.close()
        viewer.build(db)
        cls.db = db
        cls.prompts = cls.run_node()

    @classmethod
    def run_node(cls, script=NODE_PROMPTS, env=None):
        done = subprocess.run(["node", "-e", script, str(viewer.WEB_DIR), str(cls.data_dir / "viewer_data.js")],
                              capture_output=True, text=True, timeout=60, check=True, env=env)
        return json.loads(done.stdout)

    def test_every_prompt_type_built(self):
        self.assertEqual(len(self.prompts), 3 + 10)

    def test_no_save_outside_for_tools(self):
        for name, text in self.prompts.items():
            with self.subTest(prompt=name):
                chat, tools = text.split("for_tools:")
                fields = chat.split("```yaml\n")[1]  # the user's own data is left out: only our words are checked
                words = [chat.split("\n\n")[0], re.search(r"^outcome: .*", fields, re.MULTILINE)[0]]
                words += re.findall(r"^(\w+):", fields, re.MULTILINE) + re.findall(r"   #.*", fields)
                self.assertNotRegex(" ".join(words), r"(?i)\bsav")
                self.assertIn("give me the text", chat)
                self.assertIn("save", tools)

    def test_prompts_open_with_never_invent_and_name_employers(self):
        self.assertTrue(self.employers)
        for name, text in self.prompts.items():
            with self.subTest(prompt=name):
                self.assertTrue(text.startswith(NEVER_INVENT + "\n"))
                chat = text.split("for_tools:")[0]
                self.assertTrue(any(e in chat for e in self.employers))
        self.assertIn(" from my job as ", self.prompts["lines"].split("\n")[1])
        self.assertRegex(self.prompts["fill_experience"], r"\nhave: \{count: \d+, jobs: \[[^\]]* at ")
        for name in ["qa"] + [n for n in self.prompts if n.startswith("fill_")]:
            with self.subTest(profile=name):
                doc = json.loads(re.search(r"profile_json\):\n```json\n(.*?)\n```", self.prompts[name], re.DOTALL)[1])
                tied = [r for r in doc["items"] if r["position_id"]]
                self.assertTrue(tied)
                self.assertEqual([r for r in tied if r.get("employer") not in self.employers], [])

    def test_remove_restore_dates_and_originals(self):
        out = self.run_node(NODE_V021, env={**os.environ, "GONE": str(self.gone["id"])})
        self.assertEqual(out["question"], "Remove “Branch of the Year”? You can restore it later.")
        self.assertEqual(out["restore"], ["Restore " + self.gone["title"]])  # the removed row (Show removed) only
        self.assertNotIn("Remove " + self.gone["title"], out["remove"])
        self.assertEqual(out["live"], self.gone["status"])  # back to the status it had before Remove
        self.assertEqual(out["live_qa"], "Needs answer")
        self.assertEqual(out["dates"], ["Mar 2016", "Mar 2016", "Jan 2024 – Dec 2024", "2019", "Mar 2023 – Present"])
        self.assertTrue(out["record_meta"])
        self.assertEqual([m for m in out["record_meta"] if "Present" in m], [])
        self.assertEqual(out["kinds"], [["Choose…", "Resume", "Job description", "Review", "Recommendation", "AI output", "Other"]])
        self.assertGreater(out["add_acc"], 0)
        self.assertEqual(out["add_acc"], out["add_line"])
        self.assertGreater(out["job_pick"], 0)
        for key in ("extracted_text_read", "extracted_not_yet", "extracted_done"):
            with self.subTest(extracted=key):
                self.assertEqual(out[key].count("Waiting for your AI"), 1)
                self.assertEqual(out[key].count("Typed in by you"), 1)
        self.assertNotIn("How it works", out["tabs"])
        self.assertIn("For the AI", out["tabs"])
        self.assertEqual(out["never"], NEVER_INVENT)

    def test_schema_v4_screens(self):
        out = self.run_node(NODE_V4, env={**os.environ, "EMP": str(self.two_jobs), "WARN": str(self.warn_id)})
        by_count = sorted(e["positions"] for e in out["employers"])
        self.assertEqual(by_count[-1], 2)  # a promotion: two positions under one employer
        self.assertEqual(len(out["employers"]), 3)
        for e in out["employers"]:
            self.assertEqual(len(e["add"]), 1)  # "Add a position at <employer>" in each group
        self.assertIn("none", out["groups"])  # "Not tied to a job"
        self.assertIn("items:1", out["in15"])  # item 1 sits indented inside project 15
        self.assertEqual(out["in1"], [])
        self.assertIn("items:17", out["loose"])
        self.assertTrue(out["rowWarn"] and "outside this job" in out["rowWarn"][0])  # warning on the item row
        self.assertEqual(out["okWarn"], [])
        self.assertTrue(out["formWarn"] and out["formWarn"][0] and "still save" in out["formWarn"][0])  # and on the form
        for col in ("kind", "position_id", "parent_item_id", "title", "detail", "outputs", "organization", "from_whom",
                    "start_date", "end_date"):
            self.assertIn(col, out["formFields"])
        self.assertEqual(out["kinds"][:3], ["Project", "Responsibility", "Achievement"])
        self.assertEqual(out["jobs"][0], "Not tied to a job")
        self.assertEqual(out["parents"][0], "Not inside another item")
        self.assertEqual([o for o in out["parents"] if o.startswith(self.warned_label)], [])  # not offered as its own parent
        self.assertTrue(any(o.startswith("Project: ") for o in out["parents"]))
        self.assertEqual(out["adding"], 1)
        self.assertGreater(out["numbers"], 0)
        self.assertGreater(out["files"], 0)
        self.assertGreater(out["add_number"], 0)
        self.assertGreater(out["attach"], 0)
        self.assertGreater(out["used_by"], 0)
        self.assertTrue(out["warn"][0] and out["warn"][1] and out["warn"][2])
        self.assertEqual(out["warn"][3:], ["", "", ""])  # a bare year that may fit, no dates, or no job: no warning

    def test_prompts_end_with_connection_block(self):
        out = self.run_node(NODE_CONN)
        for kind, prompts in out.items():
            for name, prompt in prompts.items():
                with self.subTest(install=kind, prompt=name):
                    tail = prompt.split("Check your connection", 1)[1]
                    self.assertTrue(prompt.rstrip().endswith("tell me."))
                    self.assertIn("confirm your Job-o-Matic MCP server reports this database path; if it doesn't, stop and tell me.", tail)
                    self.assertIn("- MCP server: job-o-matic", tail)
                    if kind != "none":
                        self.assertIn("- Data folder: " + {"pip": "/home/u/.local/share/job-o-matic", "zip": "C:\\Jobs\\Job-o-Matic\\my_data"}[kind], tail)
                        self.assertIn("- Database file: ", tail)
                        self.assertIn("(Job-o-Matic v1.2.0)", tail)
                    if kind == "pip":
                        self.assertNotIn("python\\python.exe", prompt)
                        self.assertNotIn("app/docs/AI_GUIDE.md", prompt)
                        self.assertIn("job-o-matic-mcp", tail)

    def test_footer_shows_folder_command_version_and_copy_buttons(self):
        out = self.run_node(NODE_FOOTER)
        self.assertEqual(out["none"], 0)  # the view-only file has no info: nothing shown
        self.assertIn("Data folder: /d", out["text"])
        self.assertIn("job-o-matic-mcp", out["text"])
        self.assertIn("v1.2.0", out["text"])
        self.assertEqual(out["buttons"], ["Copy data folder", "Copy MCP start command"])

    def test_profile_block_in_qa_and_fill_prompts(self):
        for name in ["qa"] + [n for n in self.prompts if n.startswith("fill_")]:
            with self.subTest(prompt=name):
                block = re.search(r"profile_json\):\n```json\n(.*?)\n```", self.prompts[name], re.DOTALL)[1]
                doc = json.loads(block)
                self.assertEqual(set(doc), PROFILE_KEYS)
                self.assertEqual(doc["person"]["name"], "Odalys Brannigan-Voss")

    def test_create_prompt_has_lineless_items(self):
        block = re.search(r"resume_json, Original version\):\n```json\n(.*?)\n```", self.prompts["create"], re.DOTALL)[1]
        self.assertIn("items_without_lines", json.loads(block)["employers"][0]["positions"][0])
        self.assertIn("Forklift lead, nights", self.prompts["create"])

    def test_fill_prompts_carry_document_text_capped(self):
        text = self.prompts["fill_items"]
        docs = re.search(r"Text of my original documents:(.*?)\n\n```yaml", text, re.DOTALL)[1]
        self.assertIn(f"--- original {self.big_id}: Long notes (Other) ---", docs)
        self.assertTrue(docs.endswith("\n(truncated)"))
        self.assertLessEqual(len(docs), 12000 + len("\n(truncated)"))

    def test_texts_shipped_for_the_job_ad_picker(self):
        js = (self.data_dir / "viewer_data.js").read_text(encoding="utf-8")
        texts = json.loads(re.search(r", texts: (\{.*?\})\};\n", js)[1])
        conn = store.connect(self.data_dir / "jobomatic.db")
        try:
            jd = conn.execute("SELECT id, path FROM originals WHERE kind = 'Job description'").fetchone()
        finally:
            conn.close()
        self.assertEqual(texts[str(jd["id"])], (self.data_dir / (jd["path"] + ".txt")).read_text(encoding="utf-8"))
        self.assertEqual(len(texts[str(self.big_id)]), viewer.TEXT_CAP + len("\n(truncated)"))

    def test_profile_form_names_work_auth_skills_and_phone(self):
        out = self.run_node(NODE_PROFILE)
        # Field order is Tab order: names first, Save last, nothing for LinkedIn or the old "what should we call you".
        self.assertEqual(out["order"], ["first_name", "last_name", "headline", "location", "email", "phone", "work_auth_status",
                                        "work_auth_country", "work_authorization", "summary", "Save", "Cancel"])
        self.assertEqual(out["required"], ["first_name", "last_name"])
        for gone in ("name", "full_name", "linkedin"):
            self.assertNotIn(gone, out["order"])
        self.assertEqual(out["tag"], {"work_auth_status": "SELECT", "first_name": "INPUT"})
        self.assertEqual(out["status_options"], ["", "Authorized", "Needs sponsorship", "Other"])
        self.assertIn("Can you legally work in this country without the employer sponsoring a visa?", out["help"])
        self.assertEqual(out["note_label"], "Details")
        self.assertTrue(out["note_hidden"])  # no status and no note: the note field stays out of the Tab order
        self.assertEqual([o for o in out["skill_options"] if o],
                         ["Skill", "System", "Application/Software", "Method", "Standard"])
        self.assertEqual(out["phones"], {"paren": "(555) 123-4567", "dash": "555-123-4567", "dot": "555.123.4567",
                                         "intl": "+1 555 123 4567"})
        self.assertEqual(out["other"], ["+44 20 7946 0958", "555-123-4567", "+1 555 123 4567", "+353 1234 5678", "n/a", ""])
        self.assertEqual(out["card_phone"], "(555) 123-4567")
        self.assertEqual(out["name"], "Ada Lovelace")
        self.assertEqual(out["work_auth"], ["Authorized \u00b7 United States", "Student visa \u00b7 Canada"])

    def test_python_resume_phone_matches_the_browser_default(self):
        from jobomatic import resume
        self.assertEqual([resume._phone(v) for v in ("+15551234567", "+442079460958", "5551234567", "+353 1 234 5678", "n/a", "", None)],
                         ["(555) 123-4567", "+44 20 7946 0958", "(555) 123-4567", "+353 1234 5678", "n/a", "", ""])

    def test_accessible_names_and_structure(self):
        out = self.run_node(NODE_A11Y)
        self.assertEqual([x for x in out["labels"] if "\u2026" in x], [])
        self.assertTrue(any(x.startswith("Write resume lines with your AI: ") and len(x) > 100 for x in out["labels"]))
        self.assertEqual(out["h1"], 0)  # the page's only h1 is the wordmark; the guide's "#" becomes h3
        self.assertTrue(out["who"])
        for role, name, tip in out["who"]:
            self.assertEqual((role, tip), ("img", name))
            self.assertRegex(name, r"^Added by: (You|Your AI|The app \(starter data\))$")
        self.assertTrue(out["line_lists"])
        self.assertTrue(all(kids and set(kids) == {"LI"} for kids in out["line_lists"]))
        self.assertTrue(out["open_links"])
        self.assertTrue(all(x and x.startswith("Open ") and len(x) > 5 for x in out["open_links"]))
        self.assertEqual(out["filter_label"], ["Show version"])
        self.assertEqual(out["show_ai"], 1)
        self.assertTrue(any(x.startswith("More: ") for x in out["labels"]))  # Q&A: Remove sits under More
        conn = store.connect(self.db)
        try:
            question = conn.execute("SELECT question FROM qa WHERE id = 1").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(out["form_remove"], [["Remove " + question]])
        self.assertIn('["track", "Line\'s version", "track"]', (viewer.WEB_DIR / "app.js").read_text(encoding="utf-8"))

    def test_quick_draft_renders_only_ticked_lines(self):
        conn = store.connect(self.db)
        try:
            lines = conn.execute("SELECT id, wording FROM resume_lines_ranked WHERE track = 'Original' ORDER BY id").fetchall()
        finally:
            conn.close()
        dropped, kept = lines[0], lines[1]
        out = self.run_node(NODE_DRAFT, env={**os.environ, "SKIP": json.dumps({str(dropped["id"]): True})})
        esc = html.escape  # the renderer escapes ' and " the same way
        self.assertIn(esc(dropped["wording"]), out["all"])
        self.assertNotIn(esc(dropped["wording"]), out["some"])
        self.assertIn(esc(kept["wording"]), out["some"])
        self.assertEqual(sorted(out["words"]), ["costs", "docks", "fewer", "reduce"])
        self.assertEqual(out["marks"], ["costs", "Docks"])

    def test_form_select_defaults_and_discard_prompt(self):
        out = self.run_node(NODE_FORMS)
        self.assertEqual(out["single"], [[["Active", "Active"]], "Active"])  # only option: preselected, no Removed
        self.assertEqual(out["many"], [[["", "Choose\u2026"], ["Verified", "Verified"], ["Needs review", "Needs review"]], ""])
        self.assertIn(["Deprecated", "Removed"], out["existing"][0])
        conn = store.connect(self.db)
        try:
            recent = conn.execute(viewer_js_const("MOST_RECENT_JOB")).fetchone()["id"]
        finally:
            conn.close()
        self.assertTrue(recent)  # a new item starts under this job (the view passes it as the default)
        self.assertEqual((out["job_new"], out["job_edit"]), ("", ""))  # "Not tied to a job" stays choosable
        self.assertEqual(out["job_labels"][0], "Not tied to a job")
        self.assertEqual(out["parent_default"], "")
        self.assertTrue(out["clean_leaves"])
        self.assertTrue(out["dirty_kept"])
        self.assertTrue(out["dirty_discarded"])
        self.assertEqual((out["asks"], out["text"]), (2, "Discard your changes?"))


class ThemeTokensCase(unittest.TestCase):
    def test_dark_blocks_match(self):
        css = (viewer.WEB_DIR / "tokens.css").read_text(encoding="utf-8")
        follow = re.search(r'@media \(prefers-color-scheme: dark\)\{\s*:root:not\(\[data-theme="light"\]\)\{([^}]*)\}', css)[1]
        picked = re.search(r':root\[data-theme="dark"\]\{([^}]*)\}', css)[1]
        self.assertEqual(follow.split(), picked.split())
        self.assertIn("--bg:", picked)

    def test_page_shows_both_wordmarks_and_thumbs(self):
        html = viewer.render_html("")
        self.assertEqual(html.count('class="wordmark wm-'), 2)
        self.assertEqual(sorted(re.findall(r'"(\w+)": "data:image/webp;base64,', html)),
                         ["executive", "genz", "navy_bar", "structured", "two_column"])


if __name__ == "__main__":
    unittest.main()
