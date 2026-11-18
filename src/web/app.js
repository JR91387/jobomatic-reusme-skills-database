/* Job-o-Matic viewer. View only as a plain file; edit mode when the helper serves it (window.HELPER_TOKEN). */
(function () {
  "use strict";

  var EDIT = typeof window.HELPER_TOKEN === "string";
  var DATA_URL = "/data.js?t=";
  var RETIRED = ["Deprecated", "Archived", "Retired"];
  var TABS = [
    ["profile", "Profile"], ["experience", "Experience"], ["items", "Items"],
    ["lines", "Resume Lines"], ["qa", "Q&A"], ["originals", "Originals"],
    ["ai", "For the AI"], ["settings", "Settings"]
  ];
  // Reached from a header link, not a tab (#how still opens it).
  var PAGES = ["how"];
  var WHO = { user: "You", ai: "AI", app: "App" };
  var WHO_FULL = { user: "You", ai: "Your AI", app: "The app (starter data)" };
  var WEIGHT = { 3: "Official", 2: "Your own", 1: "Loose notes" };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var REVIEW = ["Verified", "Needs review", "Deprecated"];

  var SQL = null;
  var db = null;
  var updated = "";
  var texts = {};  // original id -> its extracted text (viewer.original_texts)
  var changes = {};
  var offline = false;
  // textOpen / textJob / textAdded: an original's text panel (open, picked job, lines added), kept across re-renders.
  var state = { tab: "profile", showRetired: false, track: "", editing: null, textOpen: {}, textJob: {}, textAdded: {} };
  // Open form key -> { base: values shown before typing, typed: what the user typed }. Kept until Save or Cancel,
  // so re-renders (data reloads, filters, a 409) never lose typing.
  var drafts = {};
  var upload = { kind: "", title: "" };

  // Edit-form fields per table: [column, label, kind, options]. kind: text | area | select | number | date
  var ITEM_KINDS = ["Project", "Responsibility", "Achievement", "Award", "Publication", "Volunteer", "Speaking",
    "Recommendation", "Review", "Kudos"];
  var FORMS = {
    people: [["name", "What should we call you? (required)"], ["full_name", "Full name"], ["headline", "Headline"],
      ["location", "Location"], ["email", "Email"], ["phone", "Phone"], ["linkedin", "LinkedIn URL"],
      ["work_authorization", "Work authorization"], ["summary", "Summary", "area"]],
    links: [["kind", "Kind", "select", ["LinkedIn", "GitHub", "Website", "Portfolio", "Other"]],
      ["label", "Label"], ["url", "Web address"], ["status", "Status", "select", ["Active", "Deprecated"]]],
    employers: [["name", "Employer"], ["location", "Location"], ["website", "Website"],
      ["notes", "Notes", "area"], ["status", "Status", "select", REVIEW]],
    positions: [["title", "Job title"], ["employer_id", "Employer", "employer"], ["department", "Department"],
      ["start_date", "Start", "date"], ["end_date", "End (blank = still there)", "date"],
      ["notes", "Notes", "area"], ["status", "Status", "select", REVIEW]],
    items: [["kind", "Kind", "select", ITEM_KINDS], ["position_id", "Job (optional)", "position"],
      ["parent_item_id", "Inside another item (optional)", "parent", function (row) { return [row ? row.id : null]; }],
      ["title", "Title"], ["detail", "What you did or received", "area"], ["outputs", "Outputs (what it produced)", "area"],
      ["organization", "Organization"], ["from_whom", "From whom"],
      ["start_date", "Start", "date"], ["end_date", "End", "date"],
      ["source", "Source (optional)"], ["notes", "Notes", "area"], ["status", "Status", "select", REVIEW]],
    item_metrics: [["label", "What it measures"], ["value", "Number or result"], ["unit", "Unit"],
      ["as_of", "As of"], ["sort", "Order", "number"], ["status", "Status", "select", REVIEW]],
    item_originals: [["note", "Note"], ["status", "Status", "select", ["Active", "Deprecated"]]],
    bullet_variants: [["wording", "Resume line", "area"], ["item_id", "Item", "item"],
      ["track", "Line's version", "track"], ["angle", "Focus"], ["length", "Length", "select", ["", "Short", "Long", "Story"]],
      ["status", "Status", "select", REVIEW]],
    skills: [["name", "Skill"], ["category", "Category", "select", ["", "Skill", "System", "Method", "Standard"]],
      ["status", "Status", "select", REVIEW]],
    education: [["name", "Name"], ["kind", "Kind", "select", ["Degree", "Course", "Certification", "Training", "Self-study"]],
      ["institution", "School or provider"], ["year", "Year"], ["status", "Status", "select", REVIEW]],
    qa: [["question", "Question"], ["answer", "Your answer", "area"], ["category", "Category", "select",
      ["", "About you", "Behavioral", "Strengths", "Motivation", "Situational", "Logistics", "Other"]],
      ["status", "Status", "select", ["Needs answer", "Needs review", "Verified", "Deprecated"]]],
    originals: [["title", "Title"], ["doc_date", "Document date"], ["weight", "How official is it?", "select", ["3", "2", "1"]],
      ["extracted", "Facts taken out", "select", extractedOptions], ["notes", "Notes", "area"]],
    settings: [["value", "Value"]],
    tracks: [["name", "Name"], ["sort", "Order", "number"], ["status", "Status", "select", ["Active", "Retired"]]]
  };
  // "Facts taken out": "Not yet" and "Text read" both read "Waiting for your AI", so only the row's own one is offered.
  // "Typed in by you" is stored as Done (the change log records that you made it).
  function extractedOptions(row) {
    var waiting = row && row.extracted === "Not yet" ? "Not yet" : "Text read";
    return [waiting, "Partly", "Done", TYPED_IN];
  }
  var TYPED_IN = "Typed in";
  var PERSON_TABLES = ["links", "employers", "positions", "items", "skills", "education", "qa"];
  var REMOVABLE = ["links", "employers", "positions", "items", "item_metrics", "item_originals", "bullet_variants", "skills",
    "education", "qa", "tracks"];
  // Fields that may not be blank, with the database's own wording (src/db/schema.sql) where it has one.
  var REQUIRED = {
    people: { name: "Name cannot be empty" }, links: { url: "Web address cannot be empty" },
    employers: { name: "Employer cannot be empty" },
    positions: { title: "Job title cannot be empty", employer_id: "Choose an employer" },
    item_metrics: { value: "The number or result cannot be empty" },
    skills: { name: "Skill cannot be empty" }, education: { name: "Name cannot be empty" },
    bullet_variants: { wording: "The wording cannot be empty", item_id: "Choose an item" },
    qa: { question: "The question cannot be empty" }, tracks: { name: "Name cannot be empty" }, settings: { value: "Value cannot be empty" }
  };
  var DATE_RULE = "Dates are YYYY or YYYY-MM, like 2021 or 2021-06";
  var MOST_RECENT_JOB = "SELECT id FROM positions WHERE status <> 'Deprecated' ORDER BY end_date IS NULL DESC, end_date DESC, start_date DESC, id DESC LIMIT 1";
  // Words shown for stored values; the database keeps its own values.
  var SHOWN = { Deprecated: "Removed", Archived: "Removed", Retired: "Removed", "Text read": "Waiting for your AI", "Not yet": "Waiting for your AI",
    "Typed in": "Typed in by you", Story: "Story (interview)" };
  // Hints under form fields and placeholders.
  var PLACEHOLDER = { work_authorization: "e.g. Authorized to work in the US", track: null };
  var HINTS = { angle: "What this wording stresses, e.g. leadership or cost savings" };
  var HASH_ALIAS = { awards: "items", reviews: "items" };
  // Database and network errors in plain words. Unknown ones: "Couldn't save: <message>".
  var PLAIN_ERRORS = [
    [/cannot be empty$|^Dates are YYYY|^Give the item|^An item cannot/, null],
    [/^NOT NULL constraint failed: (\w+)\.(\w+)/, function (m) { return fieldLabel(m[1], m[2]) + " cannot be empty"; }],
    [/^UNIQUE constraint failed: qa\./, "You already have this question"],
    [/^UNIQUE constraint failed: employers\./, "You already have an employer with that name"],
    [/^UNIQUE constraint failed: (tracks|people)\.name/, "That name is already used"],
    [/^UNIQUE constraint failed/, "This is already saved"],
    [/^CHECK constraint failed/, "That value isn't allowed here"],
    [/^Unknown track/, "That version doesn't exist yet: add it under Settings first"],
    [/^FOREIGN KEY constraint failed/, "That points to something that is no longer there"],
    [/Expected exactly one Active person/, "Add your profile first (Profile tab)"],
    [/Failed to fetch|NetworkError|Load failed/, "The Job-o-Matic app isn't running. Start it again, then try once more."]
  ];

  // ---------- small helpers ----------
  function h(tag, props) {
    var el = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else if (k in el && k !== "list" && k !== "for") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { add(el, k); }); return; }
    el.appendChild(typeof kid === "object" ? kid : document.createTextNode(String(kid)));
  }
  function q(sql, params) {
    var stmt = db.prepare(sql);
    var out = [];
    try {
      if (params) stmt.bind(params);
      while (stmt.step()) out.push(stmt.getAsObject());
    } finally {
      stmt.free();
    }
    return out;
  }
  function month(v) {
    var m = /^(\d{4})-(\d{2})/.exec(v || "");
    return m ? MONTHS[parseInt(m[2], 10) - 1] + " " + m[1] : (v || "");
  }
  function span(a, b) {
    if (!a && !b) return "";
    return (month(a) || "?") + " – " + (month(b) || "Present");
  }
  // Awards, reviews, talks: a blank End (or End = Start) is one date, never "– Present". Jobs use span().
  function recordDate(a, b) {
    return !b || !a || a === b ? month(a || b) : span(a, b);
  }
  function isRetired(row) { return RETIRED.indexOf(row.status) >= 0; }
  function shown(v) { return SHOWN[v] || v; }
  function fieldLabel(table, col) {
    var f = (FORMS[table] || []).filter(function (x) { return x[0] === col; })[0];
    return f ? f[1].replace(/ \(.*\)$/, "") : col.replace(/_/g, " ");
  }
  function plainError(msg, failed) {
    msg = String(msg || "");
    for (var i = 0; i < PLAIN_ERRORS.length; i++) {
      var m = PLAIN_ERRORS[i][0].exec(msg), say = PLAIN_ERRORS[i][1];
      if (m) return say === null ? msg : typeof say === "function" ? say(m) : say;
    }
    return (failed || "Couldn't save") + ": " + (msg.length > 120 ? msg.slice(0, 119) + "\u2026" : msg);
  }
  // "Jun 2025", "June 2025", "06/2025", "2025-6" -> "2025-06"; "Present" -> ""; null when it is not a date.
  function normDate(v) {
    var s = String(v || "").trim(), m, mon = 0, year;
    if (!s || /^(present|now|current|today)$/i.test(s)) return "";
    if ((m = /^(\d{4})(?:[-/.](\d{1,2}))?$/.exec(s))) { year = m[1]; mon = m[2] ? +m[2] : -1; }
    else if ((m = /^(\d{1,2})[-/.](\d{4})$/.exec(s))) { year = m[2]; mon = +m[1]; }
    else if ((m = /^([A-Za-z]{3,9})\.?,?\s+(\d{4})$/.exec(s))) {
      year = m[2];
      mon = MONTHS.map(function (x) { return x.toLowerCase(); }).indexOf(m[1].slice(0, 3).toLowerCase()) + 1 || 13;
    } else return null;
    if (mon === -1) return year;
    return mon >= 1 && mon <= 12 ? year + "-" + (mon < 10 ? "0" : "") + mon : null;
  }
  // With table given, a row just removed stays in the list: its card becomes the Undo spot.
  function visible(rows, table) {
    return state.showRetired ? rows : rows.filter(function (r) {
      return !isRetired(r) || (!!table && !!state.removed && state.removed.key === table + ":" + r.id);
    });
  }
  function joinNonEmpty(parts, sep) { return parts.filter(function (p) { return p; }).join(sep || " · "); }
  function bytesToB64(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function b64ToBytes(b64) {
    var s = atob(b64);
    var out = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }
  function activePerson() { return q("SELECT * FROM people WHERE status = 'Active'")[0] || null; }

  // ---------- errors ----------
  function showError(msg) {
    var box = document.getElementById("errors");
    var row = h("div", { class: "error" }, h("span", null, msg),
      h("button", { type: "button", onclick: function () { row.remove(); } }, "Dismiss"));
    box.appendChild(row);
  }
  // ---------- focus and announcements ----------
  // The page's one status message for screen readers. Emptied first, so the same words are read again.
  function announce(text) {
    var box = document.getElementById("status");
    box.textContent = "";
    setTimeout(function () { box.textContent = text; }, 50);
  }
  // Focus the row with this key (its Undo button when just removed), else the tab's heading.
  function focusItem(key) {
    var el = (key && document.querySelector('[data-key="' + key + '"]')) || document.getElementById("panel-title");
    if (!el) return;
    el = el.querySelector(".undo") || el;
    if (!el.hasAttribute("tabindex") && !/^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) el.setAttribute("tabindex", "-1");
    el.focus();
  }
  // The same control after a re-render (matched by its name), so focus can go back to it.
  function stillThere(el) {
    if (!el || el.isConnected) return el;
    var name = el.getAttribute("aria-label");
    return name ? Array.prototype.filter.call(document.querySelectorAll("[aria-label]"), function (x) {
      return x.getAttribute("aria-label") === name;
    })[0] : null;
  }

  window.addEventListener("error", function (e) { showError("Something went wrong: " + e.message); });
  window.addEventListener("unhandledrejection", function (e) {
    showError("Something went wrong: " + (e.reason && e.reason.message ? e.reason.message : e.reason));
  });

  // ---------- helper connection (edit mode only) ----------
  function http(method, path, body) {
    if (!EDIT) return Promise.reject(new Error("Saving needs the Job-o-Matic app running"));
    var opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-JobOMatic"] = window.HELPER_TOKEN;
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) {
          var err = new Error(j.error || "The app answered " + r.status);
          err.status = r.status;
          err.body = j;
          throw err;
        }
        return j;
      });
    });
  }

  function loadDataScript() {
    return new Promise(function (resolve, reject) {
      var old = document.getElementById("data-js");
      if (old) old.remove();
      var s = document.createElement("script");
      s.id = "data-js";
      s.src = DATA_URL + Date.now();
      s.onload = function () { resolve(window.JOBOMATIC_DB); };
      s.onerror = function () { reject(new Error("Could not load your data from the app (/data.js)")); };
      document.head.appendChild(s);
    });
  }

  // One load at a time: focus, visibility and the 15 s check can all ask at once.
  var loading = null;
  function refresh() {
    if (!loading) {
      loading = loadDataScript().then(function (data) {
        loading = null;
        if (data && data.updated !== updated) useData(data);
        return data;
      }, function (err) { loading = null; throw err; });
    }
    return loading;
  }

  function waitForRebuild(before, tries) {
    return refresh().then(function (data) {
      if (data.updated !== before) return;
      if (tries <= 0) throw new Error("Saved, but the screen did not refresh. Reload the page to see the change.");
      return new Promise(function (r) { setTimeout(r, 300); }).then(function () { return waitForRebuild(before, tries - 1); });
    });
  }

  function setOffline(down) {
    if (down === offline) return;
    offline = down;
    renderMode();
  }

  // ---------- data ----------
  function useData(data) {
    if (!data || !data.b64) throw new Error("No data found in this file");
    if (db) db.close();
    db = new SQL.Database(b64ToBytes(data.b64));
    updated = data.updated;
    texts = data.texts || {};
    changes = {};
    q("SELECT table_name, row_id, actor FROM last_change").forEach(function (r) {
      changes[r.table_name + ":" + r.row_id] = r.actor;
    });
    if (!state.editing) render();
  }

  // ---------- chrome around the content ----------
  function renderMode() {
    var badge = document.getElementById("mode");
    var note = document.getElementById("mode-note");
    document.body.classList.toggle("editing", EDIT && !offline);
    if (!EDIT) {
      badge.className = "mode view";
      badge.textContent = "View only";
      note.textContent = "To change anything, ask your AI or open the Job-o-Matic app.";
    } else if (offline) {
      badge.className = "mode offline";
      badge.textContent = "App stopped";
      note.textContent = "Changes can't be saved. Start the Job-o-Matic app again to keep editing.";
    } else {
      badge.className = "mode edit";
      badge.textContent = "Editing";
      note.textContent = "Changes save to your file. Or ask your AI.";
    }
    var when = updated ? new Date(updated).toLocaleString() : "";
    document.getElementById("updated").textContent = when ? (EDIT ? "Data loaded " : "Snapshot from ") + when : "";
  }

  // ARIA tabs: one Tab stop (the selected tab), arrow keys / Home / End move between tabs. Built once, so focus stays put.
  function renderTabs() {
    var bar = document.getElementById("tabs");
    if (!bar.children.length) {
      TABS.forEach(function (t) {
        bar.appendChild(h("button", { type: "button", class: "tab", role: "tab", id: "tab-" + t[0], "aria-controls": "main",
          onclick: function () { go(t[0]); } }, t[1]));
      });
      bar.addEventListener("keydown", function (e) {
        var i = TABS.map(function (t) { return t[0]; }).indexOf(state.tab), n = TABS.length;
        if (i < 0) i = e.key === "ArrowLeft" ? 0 : -1;  // on How it works: Right goes to the first tab, Left to the last
        var to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: n - 1 }[e.key];
        if (to === undefined) return;
        e.preventDefault();
        go(TABS[(to + n) % n][0]);
        document.getElementById("tab-" + state.tab).focus();
      });
    }
    // On a header-link page no tab is selected; the first tab keeps the list's one Tab stop.
    var page = PAGES.indexOf(state.tab) >= 0;
    TABS.forEach(function (t, i) {
      var b = document.getElementById("tab-" + t[0]), on = state.tab === t[0];
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on || (page && i === 0) ? 0 : -1;
      if (on) b.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
    var how = document.getElementById("how-link");
    if (how) {
      if (state.tab === "how") how.setAttribute("aria-current", "page");
      else how.removeAttribute("aria-current");
    }
    tabEdges();
  }
  var TAB_ARROW = 36;  // px, .tabs-wrap.overflow padding in styles.css
  function scrollTabs(dir) {
    var bar = document.getElementById("tabs");
    bar.scrollBy({ left: dir * bar.clientWidth * 0.6, behavior: "smooth" });
  }
  // "overflow": the tabs are wider than the bar at any width, so the arrows get room of their own beside it (the
  // padding they take is added back before comparing). more-left / more-right: which arrow and edge fade show.
  function tabEdges() {
    var bar = document.getElementById("tabs"), wrap = bar.parentNode;
    var room = bar.clientWidth + (wrap.classList.contains("overflow") ? 2 * TAB_ARROW : 0);
    wrap.classList.toggle("overflow", bar.scrollWidth > room + 4);
    wrap.classList.toggle("more-left", bar.scrollLeft > 4);
    wrap.classList.toggle("more-right", bar.scrollLeft + bar.clientWidth < bar.scrollWidth - 4);
  }

  // False when the user kept an open form.
  function go(tab) {
    if (!leaveForm()) return false;
    state.tab = tab;
    state.editing = null;
    state.conflict = null;
    state.saved = null;
    state.removed = null;
    state.qaOrder = null;
    if (location.hash !== "#" + tab) location.replace("#" + tab);
    render();
    window.scrollTo(0, 0);
    tabEdges();
    return true;
  }

  function render() {
    renderMode();
    renderTabs();
    var main = document.getElementById("main");
    main.textContent = "";
    main.setAttribute("aria-labelledby", PAGES.indexOf(state.tab) >= 0 ? "panel-title" : "tab-" + state.tab);
    var content = VIEWS[state.tab]();
    if (CHAIN.some(function (c) { return c.tab === state.tab; })) {
      if (NARROW.matches) { content.splice(2, 0, chainSide()); add(main, content); }  // phones: right under the heading
      else add(main, h("div", { class: "with-side" }, h("div", null, content), chainSide()));
    } else {
      add(main, content);
    }
  }

  var NARROW = window.matchMedia("(max-width: 720px)");
  // One position has many items; one item has many resume lines (wordings).
  var CHAIN = [
    { tab: "experience", noun: ["position", "positions"], sql: "SELECT count(*) AS n FROM positions WHERE status <> 'Deprecated'", link: "has many" },
    { tab: "items", noun: ["item", "items"], sql: "SELECT count(*) AS n FROM items WHERE status <> 'Deprecated'", link: "each has many" },
    { tab: "lines", noun: ["resume line", "resume lines"], sql: "SELECT count(*) AS n FROM bullet_variants WHERE status <> 'Deprecated'" }
  ];
  function chainSide() {
    var tracks = q("SELECT name FROM tracks WHERE status = 'Active' ORDER BY sort, name").map(function (r) { return r.name; });
    var items = [];
    CHAIN.forEach(function (c, i) {
      var n = q(c.sql)[0].n;
      var here = c.tab === state.tab;
      items.push(h("button", { type: "button", class: "chain-box" + (here ? " here" : ""), "aria-current": here ? "page" : null,
        onclick: function () { if (go(c.tab)) focusItem(null); } }, h("strong", null, String(n)), " " + c.noun[n === 1 ? 0 : 1]));
      if (c.link) items.push(h("span", { class: "chain-link", "aria-hidden": "true" }, "\u2193 " + c.link));
    });
    items.push(h("p", { class: "chain-note" }, "A resume line is one way of wording an item, written for a version" +
      (tracks.length ? " (" + tracks.join(", ") + ")" : "") + " and a length (Short, Long, Story)."));
    return h("aside", { class: "chain", "aria-label": "How positions, items and resume lines connect" },
      h("p", { class: "chain-title" }, "How these connect"), items);
  }

  // ---------- shared pieces ----------
  function who(table, id) {
    var actor = changes[table + ":" + id];
    if (!actor) return null;
    var name = "Added by: " + WHO_FULL[actor];
    return h("span", { class: "who " + actor, role: "img", "aria-label": name, title: name }, WHO[actor]);
  }
  function statusEl(s) {
    if (!s) return null;
    var cls = s === "Verified" || s === "Active" || s === "Done" ? "st-ok"
      : RETIRED.indexOf(s) >= 0 ? "st-retired" : "st-warn";
    return h("span", { class: "status " + cls }, shown(s));
  }
  function reviewFlag(s) { return s && s !== "Verified" ? h("span", { class: "flag" + (RETIRED.indexOf(s) >= 0 ? " removed" : "") }, shown(s)) : null; }
  function sectionHead(title, hint, tools) {
    var ai = HEAD_AI[state.tab] ? HEAD_AI[state.tab]() : null;
    return [h("div", { class: "section-head" }, h("div", { class: "head-line" }, h("h2", { id: "panel-title", tabindex: "-1" }, title), ai),
      h("div", { class: "head-tools" }, tools)),
      hint ? h("p", { class: "section-hint" }, hint) : null];
  }
  function subHead(title, tools, ai) {
    return h("div", { class: "section-head" }, h("div", { class: "head-line" }, h("h3", null, title), ai),
      h("div", { class: "head-tools" }, tools));
  }

  // ---------- "ask your AI" prompts ----------
  var ROBOT_SVG = '<svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false">' +
    '<g fill="none" stroke="currentColor" stroke-linejoin="round" stroke-linecap="round" stroke-width="1.5">' +
    '<path d="M16 7V4.8"/><circle cx="16" cy="3.4" r="1.6"/>' +
    '<rect x="4" y="12.2" width="2.6" height="5.6" rx="1"/><rect x="25.4" y="12.2" width="2.6" height="5.6" rx="1"/>' +
    '<rect x="6.6" y="7" width="18.8" height="16.2" rx="4.2"/>' +
    '<rect x="9.2" y="10" width="13.6" height="10.6" rx="2.8" stroke-width="1.1"/>' +
    '<circle cx="12.9" cy="14" r="2.3" stroke-width="1.1"/><circle cx="19.1" cy="14" r="2.3" stroke-width="1.1"/>' +
    '<rect x="12.8" y="17.6" width="6.4" height="1.9" rx=".7" stroke-width="1"/><path d="M15 17.7v1.7M17 17.7v1.7" stroke-width=".8"/>' +
    '<rect x="10.6" y="23.2" width="10.8" height="6.4" rx="2"/></g>' +
    '<g fill="currentColor"><circle cx="13.2" cy="14.3" r="1.1"/><circle cx="19.4" cy="14.3" r="1.1"/>' +
    '<circle cx="8.7" cy="9" r=".65"/><circle cx="23.3" cy="9" r=".65"/><circle cx="16" cy="26.4" r="1.2"/></g></svg>';

  // section key: [title, table, what to ask for]
  var SECTIONS = {
    people: ["Profile", "people", "full name, headline, location, email, phone, LinkedIn, work authorization, short summary in my words"],
    links: ["Links", "links", "LinkedIn, GitHub, portfolio, website (kind, label, url)"],
    skills: ["Skills", "skills", "skills, systems, methods, standards I really used; link each to its positions or items via skill_links"],
    education: ["Education and training", "education", "degrees, courses, certifications, training (kind, name, institution, year)"],
    experience: ["Experience", "positions", "employers (name, location, website), then the positions held at each: title, department, start/end month (YYYY-MM); a promotion is a second position at the same employer"],
    items: ["Items", "items", "one item per row: kind (Project, Responsibility, Achievement, Award, Publication, Volunteer, Speaking, Recommendation, Review, Kudos), title, detail, outputs, organization, from_whom, dates; position_id when it belongs to a job, parent_item_id when it sits inside another item; link each to its originals via item_originals"],
    metrics: ["Numbers", "item_metrics", "the numbers that prove an item (label, value as quoted, unit, as_of), many per item; never a number the sources do not give"],
    bullet_variants: ["Resume Lines", "bullet_variants", "lines for items that have few or none, for each version and length (Short, Long, Story)"],
    qa: ["Interview questions", "qa", "questions I keep meeting (seeded = 0) and answers to the open ones"],
    originals: ["Originals", "originals", "index unlisted files in my_data/originals/, then take the facts out (list_originals, read_original, mark_extracted)"]
  };
  var CHAT_ONLY = "If you can't open files on this computer, that's fine: just give me the text and I'll paste it in myself. " +
    "The for_tools part at the end is only for AIs that can open my files.";

  function dataFolder() {
    if (location.protocol !== "file:") return null;
    var p = decodeURIComponent(location.pathname);
    var win = true;
    if (location.host) p = "\\\\" + location.host + p.replace(/\//g, "\\");
    else if (/^\/{2,}[^/]/.test(p)) p = "\\\\" + p.replace(/^\/+/, "").replace(/\//g, "\\");
    else if (/^\/[A-Za-z]:\//.test(p)) p = p.slice(1).replace(/\//g, "\\");
    else win = false;
    var sep = win ? "\\" : "/";
    return { path: p.slice(0, p.lastIndexOf(sep)), win: win };
  }

  // YAML scalar: plain when safe, else single-quoted (double-quoted JSON when it has line breaks).
  function ys(v, inFlow) {
    if (v === null || v === undefined || v === "") return "null";
    if (typeof v === "number") return String(v);
    if (Array.isArray(v)) return "[" + v.map(function (x) { return ys(x, true); }).join(", ") + "]";
    if (typeof v === "object") return "{" + Object.keys(v).map(function (k) { return k + ": " + ys(v[k], true); }).join(", ") + "}";
    var s = String(v);
    if (/[\r\n]/.test(s)) return JSON.stringify(s);
    var unsafe = /^[\s\-?:,\[\]{}#&*!|>'"%@`]|\s$|: |:$| #/.test(s) || (inFlow && /[,\[\]{}]/.test(s)) ||
      /^(true|false|yes|no|on|off|null|~|[-+.\d][\d.eE+-]*)$/i.test(s);
    return unsafe ? "'" + s.replace(/'/g, "''") + "'" : s;
  }
  function yamlBlock(fields) {
    var out = [];
    fields.forEach(function (f) {
      if (f === null) return;
      var k = f[0], v = f[1], note = f[2] ? "   # " + f[2] : "";
      if (Array.isArray(v) && v.length && typeof v[0] === "object" && v.length > 2) {
        out.push(k + ":" + note);
        v.forEach(function (x) { out.push("  - " + ys(x, true)); });
      } else out.push(k + ": " + ys(v) + note);
    });
    return out;
  }

  // Chat-facing text asks for the text only; how to store it lives in for_tools (tools: extra fields there).
  function buildPrompt(intro, fields, middle, tools) {
    var f = dataFolder();
    var win = 'python\\python.exe app\\src\\db.py "SQL"', nix = 'python/bin/python3 app/src/db.py "SQL"';
    var demo = !!window.JOBOMATIC_DEMO;
    var cmd = f && !demo ? (f.win ? win : nix) : "Windows " + win + "; macOS/Linux " + nix;
    var forTools = yamlBlock((tools || []).concat([
      ["root", demo ? "(demo: no database — example only)" : f ? f.path : "(your Job-o-Matic folder)",
        demo ? "from the Job-o-Matic DEMO page (a made-up person)" : "paths below are relative to root"],
      ["db", "my_data/jobomatic.db"],
      ["originals", "my_data/originals/"],
      ["guide", "app/docs/AI_GUIDE.md", "read first"],
      ["access", "MCP job-o-matic (call schema_guide first), else from root: " + cmd],
      ["updated_by", "ai", "on every write"],
      ["expected_updated_at", "argument of the MCP save tool (the row's current updated_at), not a database column"],
      ["rules", "never delete (retire via status); never invent facts or numbers; new facts go to items before lines"]
    ]));
    var body = yamlBlock(fields.concat([["outcome", "the final text, after I approve it"]]))
      .concat(["for_tools:   # only if you can open my files; chat-only AIs skip this"], forTools.map(function (l) { return "  " + l; }));
    return NEVER_INVENT + "\n" + intro.concat(CHAT_ONLY).join(" ").replace(/ \n/g, "\n") + (middle || "") +
      "\n\n```yaml\n" + body.join("\n") + "\n```";
  }
  // First line of every prompt: chat AIs read the top; the rules in for_tools come too late for them.
  var NEVER_INVENT = "Use only the facts below; never invent anything.";

  // A job as people say it: "Title at Employer". Chat AIs got facts wrong when jobs were only numbers.
  function jobName(title, employer) { return joinNonEmpty([title, employer], " at "); }
  // What the career file holds now (profile_json view), so the AI starts there instead of asking for basics.
  // profile_json already names each item's employer and job title.
  function profileBlock() {
    var row = q("SELECT profile FROM profile_json")[0];
    if (!row) return "\n\nMy career file is empty so far.";
    var doc = JSON.parse(row.profile);
    return "\n\nWhat my career file holds now (Job-o-Matic profile_json):\n```json\n" + JSON.stringify(doc, null, 2) + "\n```";
  }

  var DOC_CAP = 12000;  // characters of original-document text in one prompt
  function documentsBlock(originals) {
    var out = "", cut = false;
    originals.forEach(function (o) {
      if (cut || !texts[o.id]) return;
      var part = "\n\n--- original " + o.id + ": " + (o.title || o.path.split("/").pop()) + " (" + o.kind + ") ---\n" + texts[o.id];
      if (out.length + part.length > DOC_CAP) { part = part.slice(0, DOC_CAP - out.length); cut = true; }
      out += part;
    });
    return out ? "\n\nText of my original documents:" + out + (cut ? "\n(truncated)" : "") : "";
  }

  function fillPrompt(key) {
    var s = SECTIONS[key];
    var jobsTab = key === "experience";
    var rows = jobsTab
      ? q("SELECT p.id, p.title, e.name AS employer FROM positions p JOIN employers e ON e.id = p.employer_id" +
        " WHERE p.status <> 'Deprecated' ORDER BY p.id")
      : q("SELECT id FROM " + s[1] + (s[1] === "originals" ? "" : " WHERE status NOT IN ('Deprecated','Archived')") + " ORDER BY id");
    var originals = q("SELECT id, title, path, kind, extracted FROM originals ORDER BY extracted = 'Done', weight DESC, doc_date DESC, id");
    return buildPrompt([
      "Please help me fill in the " + s[0] + " section of my Job-o-Matic career file.",
      originals.length ? "Start from what my career file holds and my original documents below, then ask me questions one at a time for anything missing."
        : "Start from what my career file holds below. I have no original documents yet, so ask me for an old resume or a review first, then ask me questions one at a time.",
      "Keep each fact with the employer it is listed under.",
      "When I approve, give me the final text."
    ], [
      ["task", "fill_section"],
      ["target", { table: s[1], section: s[0] }],
      ["want", s[2]],
      ["have", jobsTab ? { count: rows.length, jobs: rows.slice(0, 30).map(function (r) { return jobName(r.title, r.employer); }) }
        : { count: rows.length, ids: rows.slice(0, 30).map(function (r) { return r.id; }) }, rows.length > 30 ? "first 30" : ""],
      key === "bullet_variants" ? ["version", state.track || "Original"] : null,
      ["originals", originals.slice(0, 15).map(function (o) {
        return { id: o.id, title: o.title || o.path.split("/").pop(), kind: o.kind, extracted: o.extracted };
      }), originals.length > 15 ? "first 15; list_originals for the rest" : ""]
    ], profileBlock() + documentsBlock(originals), [
      ["new_rows", { status: "Needs review" }, "save each approved item as a row with this status"]
    ]);
  }

  function linesPrompt(itemId) {
    var a = q("SELECT i.*, p.title AS job_title, e.name AS employer FROM items i LEFT JOIN positions p ON p.id = i.position_id" +
      " LEFT JOIN employers e ON e.id = p.employer_id WHERE i.id = ?", [itemId])[0];
    var track = state.track || "Original";
    var have = q("SELECT id, track, length FROM bullet_variants WHERE item_id = ? AND status <> 'Deprecated' ORDER BY track, id", [itemId]);
    var metrics = q("SELECT label, value, unit, as_of FROM item_metrics WHERE item_id = ? AND status <> 'Deprecated' ORDER BY sort, id", [itemId]);
    var missing = ["Short", "Long", "Story"].filter(function (len) {
      return !have.some(function (l) { return l.track === track && l.length === len; });
    });
    return buildPrompt([
      "Please write resume lines for one of my items (" + a.kind.toLowerCase() + ")" +
        (a.position_id ? " from my job as " + jobName(a.job_title, a.employer) : "") +
        ", for the " + track + " version, using only the facts and numbers below.",
      "Show me the drafts, then give me the text of the ones I approve."
    ], [
      ["task", "write_lines"],
      ["target", { table: "items", id: a.id, status: a.status }],
      ["kind", a.kind],
      ["title", a.title],
      ["detail", a.detail],
      ["outputs", a.outputs],
      ["metrics", metrics.map(function (m) { return { label: m.label, value: m.value, unit: m.unit, as_of: m.as_of }; }), "table item_metrics"],
      ["job", a.position_id ? { table: "positions", id: a.position_id, title: a.job_title, employer: a.employer } : null],
      ["have", have.map(function (l) { return { id: l.id, track: l.track, length: l.length }; }), "table bullet_variants"],
      ["version", track],
      ["missing", missing.length ? missing : "none (offer a fresh angle instead)"]
    ], "", [
      ["save_as", { table: "bullet_variants", item_id: a.id, track: track, status: "Needs review" }]
    ]);
  }

  function qaPrompt(qaId) {
    var r = q("SELECT * FROM qa WHERE id = ?", [qaId])[0];
    return buildPrompt([
      "Please help me answer this interview question from my own experience.",
      "Use what my career file holds below first; ask me only for what it doesn't cover, one question at a time.",
      "Keep each fact with the employer it is listed under.",
      "Then draft an answer in my words and give me the text."
    ], [
      ["task", "answer_question"],
      ["target", { table: "qa", id: r.id, status: r.status }],
      ["question", r.question],
      ["category", r.category],
      r.common_wordings ? ["also_asked_as", r.common_wordings] : null,
      ["answer", r.answer && r.answer.trim() ? r.answer : null]
    ], profileBlock(), [
      ["search", ["items", "item_metrics"], "for more detail"],
      ["save_as", { table: "qa", id: r.id, column: "answer", status: "Needs review" }]
    ]);
  }

  // name: the button's accessible name (starts with its visible text). onclick: opens a prompt unless given.
  function aiButton(name, make, text, onclick) {
    return h("button", { type: "button", class: "ai-btn" + (text ? " wide" : ""), title: name, "aria-label": name,
      onclick: onclick || function () { openPrompt(this, name, make()); } },
      h("span", { class: "ai-icon", innerHTML: ROBOT_SVG }), text ? h("span", null, text) : null);
  }
  function fillButton(key) {
    return aiButton("Fill this section with your AI: " + SECTIONS[key][0], function () { return fillPrompt(key); });
  }
  // Only once there is something to tailor: a profile and, on this tab, rows (sql counts them).
  function tailorButton(sql) {
    if (!activePerson() || !q(sql)[0].n) return null;
    return aiButton("Tailor with your AI", null, "Tailor with your AI", function () { openCreate(this); });
  }

  // ---------- dialogs ----------
  // Every dialog: focus moves in, Tab stays inside, Escape or Close shuts it, focus goes back to what opened it.
  var TABBABLE = "a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex='0']";
  function makeDialog(cls, titleId, kids) {
    var el = h("dialog", { class: "ai-dialog" + (cls ? " " + cls : ""), "aria-labelledby": titleId }, kids);
    el.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var stops = Array.prototype.filter.call(el.querySelectorAll(TABBABLE), function (x) {
        return x.offsetParent !== null && !(x.type === "radio" && !x.checked);
      });
      var at = stops.indexOf(document.activeElement);
      if (e.shiftKey ? at <= 0 : at === stops.length - 1) {
        e.preventDefault();
        stops[e.shiftKey ? stops.length - 1 : 0].focus();
      }
    });
    el.addEventListener("close", function () {
      var back = stillThere(el.opener);
      if (back) back.focus();
      else focusItem(null);
    });
    document.body.appendChild(el);
    return el;
  }
  function openDialog(el, opener, first) {
    el.opener = opener;
    el.showModal();
    first.focus();
  }

  var dlg = null;
  function promptDialog() {
    if (dlg) return dlg;
    var title = h("h2", { id: "ai-dialog-title" });
    var text = h("textarea", { class: "ai-text", readOnly: true, rows: 12, "aria-label": "Prompt text", spellcheck: "false" });
    var msg = h("span", { class: "ai-msg", "aria-live": "polite" });
    var copy = h("button", { type: "button", class: "btn", onclick: function () {
      var fallback = function () {
        text.focus();
        text.select();
        msg.className = "ai-msg";
        msg.textContent = "Press Ctrl+C (Cmd+C on Mac) to copy";
      };
      if (!navigator.clipboard || !navigator.clipboard.writeText) { fallback(); return; }
      navigator.clipboard.writeText(text.value).then(function () {
        msg.className = "ai-msg ok-msg";
        msg.textContent = "Copied";
      }, fallback);
    } }, "Copy prompt");
    var el = makeDialog("", "ai-dialog-title", [
      title, h("p", { class: "small muted" }, "Paste this into any AI chat. It says where your data is and how to change it safely."),
      text, h("div", { class: "form-actions" }, copy,
        h("button", { type: "button", class: "btn ghost", onclick: function () { el.close(); } }, "Close"), msg)]);
    dlg = { el: el, title: title, text: text, msg: msg, copy: copy };
    return dlg;
  }
  function openPrompt(opener, title, prompt) {
    var d = promptDialog();
    d.title.textContent = title;
    d.text.value = prompt;
    d.msg.textContent = "";
    d.text.setSelectionRange(0, 0);
    openDialog(d.el, opener, d.copy);
    d.text.scrollTop = 0;
  }
  // ---------- Create Resume ----------
  var STYLES = [
    ["executive", "Executive", "classic serif, name centered; formal and traditional"],
    ["navy_bar", "Navy bar", "navy band across the top; clean and modern"],
    ["two_column", "Two column", "contact and skills in a side column; fits more on one page"],
    ["structured", "Structured", "skills in a tidy table; good for technical jobs"],
    ["genz", "Gen Z", "soft color header and skill tags; friendly and fresh"]
  ];

  function resumeDoc(track) {
    var row = q("SELECT resume FROM resume_json WHERE track = ?", [track])[0];
    if (!row) throw new Error("Add your profile first: a resume needs a name.");
    return JSON.parse(row.resume);
  }

  function createPrompt(style, track, ad) {
    var s = STYLES.filter(function (x) { return x[0] === style; })[0];
    return buildPrompt([
      "Please write a resume tailored to the job ad below, in the " + s[1] + " style (" + s[2] + "), using my " + track + " version.",
      "Never invent numbers, employers, dates or skills; keep each fact under the employer it is listed with.",
      "Items without a line for this version are listed under each position (items_without_lines); use them when they fit the job.",
      "Show me the resume first and wait for my changes, then give me the final text."
    ], [
      ["task", "tailor_resume"],
      ["version", track],
      ["template", style]
    ], "\n\nMy career data (Job-o-Matic resume_json, " + track + " version):\n```json\n" +
      JSON.stringify(resumeDoc(track), null, 2) + "\n```\n\nJob ad:\n" + (ad.trim() || "<<paste it here>>"), [
      ["new_lines", { table: "bullet_variants", status: "Needs review" }, "save new or changed resume lines as rows with this status"],
      ["output", "my_data/resumes/"]
    ]);
  }

  // A resume_json document with only the lines not in skip (line id -> true: unticked in Create Resume).
  function pickLines(doc, skip) {
    doc.employers.forEach(function (m) {
      m.positions.forEach(function (j) { j.lines = j.lines.filter(function (l) { return !skip[l.id]; }); });
    });
    return doc;
  }
  function draftHtml(style, track, skip) {
    return window.JOM.renderResume(pickLines(resumeDoc(track), skip), style, window.JOBOMATIC_TEMPLATES);
  }
  // Words of 4+ letters in the job ad (common ones left out), to mark in each line.
  var COMMON = ["that", "this", "with", "from", "your", "will", "have", "they", "their", "them", "about", "what", "when",
    "were", "been", "into", "more", "than", "which", "also", "each", "other", "over", "such", "must", "should", "would"];
  function adWords(text) {
    var words = {};
    String(text || "").toLowerCase().split(/[^a-z0-9+#]+/).forEach(function (w) {
      if (w.length >= 4 && COMMON.indexOf(w) < 0) words[w] = true;
    });
    return words;
  }
  function marked(text, words) {
    return text.split(/([A-Za-z0-9+#]+)/).map(function (part) { return words[part.toLowerCase()] ? h("mark", null, part) : part; });
  }

  function quickDraft(style, track, skip) {
    var html = draftHtml(style, track, skip);
    var bar = "<style>.jom-bar{font:15px/1.4 system-ui,sans-serif;background:#17695A;color:#fff;padding:10px 16px;display:flex;" +
      "flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}.jom-bar button{font:700 15px system-ui,sans-serif;" +
      "padding:8px 14px;border:0;border-radius:8px;background:#fff;color:#17695A;cursor:pointer}@media print{.jom-bar{display:none}}</style>" +
      '<div class="jom-bar"><span>Quick draft \u2014 ask your AI to tailor it</span>' +
      '<button type="button" onclick="window.print()">Print / Save as PDF</button></div>';
    if (html.indexOf("<body>") < 0) throw new Error("This resume style has no <body>");
    var url = URL.createObjectURL(new Blob([html.replace("<body>", "<body>" + bar)], { type: "text/html" }));
    if (!window.open(url, "_blank")) throw new Error("Your browser blocked the new tab. Allow pop-ups for this page and try again.");
  }

  var create = null;
  function createDialog() {
    if (create) return create;
    var tracks = h("select", { id: "create-track" });
    var styles = h("fieldset", { class: "create-styles" }, h("legend", null, "Style"), STYLES.map(function (s, i) {
      return h("label", { class: "create-style" }, h("input", { type: "radio", name: "create-style", value: s[0], checked: i === 0 }),
        h("span", null, h("b", null, s[1]), h("span", { class: "sr-only" }, ", "), h("span", { class: "muted" }, s[2])));
    }));
    var ad = h("textarea", { id: "create-ad", class: "ai-text", rows: 5, placeholder: "Paste the job ad here" });
    var jd = h("select", { id: "create-jd", onchange: function () { if (jd.value) { ad.value = texts[jd.value]; showLines(); } } });
    var jdField = h("div", { class: "field" }, h("label", { for: "create-jd", class: "small" }, "Use a job description from Originals"), jd);
    var msg = h("p", { class: "ai-msg create-msg", role: "alert" });
    function picked() { return [styles.querySelector("input:checked").value, tracks.value]; }
    var box = h("div", { class: "preview-box", "aria-hidden": "true" });
    var skip = {};
    var lines = h("div", { class: "draft-lines" });
    // Every job's lines for the picked version (the ranking's order), ticked unless unticked; job-ad words marked.
    function showLines() {
      var row = db && tracks.value ? q("SELECT resume FROM resume_json WHERE track = ?", [tracks.value])[0] : null;
      var jobs = [];
      if (row) JSON.parse(row.resume).employers.forEach(function (m) {
        m.positions.forEach(function (j) { if (j.lines.length) jobs.push({ title: j.title, employer: m.name, lines: j.lines }); });
      });
      var words = adWords(ad.value);
      lines.textContent = "";
      if (!jobs.length) lines.appendChild(h("p", { class: "small muted" }, "No resume lines for this version yet."));
      jobs.forEach(function (j) {
        lines.appendChild(h("fieldset", { class: "draft-job" }, h("legend", null, joinNonEmpty([j.title, j.employer], " — ")),
          j.lines.map(function (l) {
            return h("label", { class: "draft-line" }, h("input", { type: "checkbox", checked: !skip[l.id], onchange: function () {
              if (this.checked) delete skip[l.id]; else skip[l.id] = true;
              showPreview();
            } }), h("span", null, marked(l.wording, words)));
          })));
      });
    }
    var caption = h("figcaption");
    // A live picture of the picked style from the saved resume; before there is a profile, a sample person's picture.
    function showPreview() {
      var p = picked();
      var row = db && p[1] ? q("SELECT resume FROM resume_json WHERE track = ?", [p[1]])[0] : null;
      var doc = row ? pickLines(JSON.parse(row.resume), skip) : null;
      var live = doc && doc.person && (doc.person.full_name || doc.person.name);
      caption.textContent = "Preview: " + STYLES.filter(function (x) { return x[0] === p[0]; })[0][1] + (live ? "" : " (sample person)");
      box.textContent = "";
      box.appendChild(live
        ? h("iframe", { title: "Resume preview", tabindex: "-1", sandbox: "", srcdoc: window.JOM.renderResume(doc, p[0], window.JOBOMATIC_TEMPLATES) })
        : h("img", { alt: "", src: (window.JOM_THUMBS || {})[p[0]] || "thumbs/" + p[0] + ".webp" }));
    }
    styles.addEventListener("change", showPreview);
    tracks.addEventListener("change", function () { showLines(); showPreview(); });
    ad.addEventListener("input", showLines);
    function run(fn) {
      msg.textContent = "";
      try { fn(); } catch (e) { msg.textContent = e.message; }
    }
    var copy = h("button", { type: "button", class: "btn", onclick: function () {
      var btn = this;
      run(function () {
        var p = picked();
        openPrompt(btn, "Prompt for your AI: a resume for this job", createPrompt(p[0], p[1], ad.value));
        dlg.copy.click();
      });
    } }, "Copy prompt");
    var draft = h("button", { type: "button", class: "btn ghost", onclick: function () {
      run(function () { var p = picked(); quickDraft(p[0], p[1], skip); });
    } }, "Open quick draft");
    var heading = h("h2", { id: "create-title", tabindex: "-1" }, "Create Resume");
    var el = makeDialog("create-dialog", "create-title", [
      heading,
      window.JOBOMATIC_DEMO ? h("p", { class: "small muted" }, "Demo: everything here uses a made-up person.") : null,
      h("div", { class: "create-pick" }, styles, h("div", { class: "create-side" },
        h("div", { class: "field" }, h("label", { for: "create-track" }, "Version"), tracks),
        h("figure", { class: "create-preview" }, box, caption))),
      h("section", { class: "create-path main-path", "aria-labelledby": "create-ai" },
        h("h3", { id: "create-ai" }, "With my AI (recommended)"),
        h("p", { class: "small" }, "Your AI writes a resume for this job from your saved facts. Paste the job ad, copy the prompt, paste it into your AI chat."),
        jdField, h("label", { for: "create-ad", class: "small" }, h("b", null, "Job ad")), ad, copy),
      h("section", { class: "create-path", "aria-labelledby": "create-quick" },
        h("h3", { id: "create-quick" }, "Quick draft (no AI)"),
        h("p", { class: "small" }, "Tick the lines to use. Words that are also in the job ad above are marked. " +
          "Opens a print-ready resume in a new tab."),
        lines, draft),
      msg,
      h("div", { class: "form-actions" }, h("button", { type: "button", class: "btn ghost", onclick: function () { el.close(); } }, "Close"))]);
    create = { el: el, heading: heading, tracks: tracks, msg: msg, ad: ad, jd: jd, jdField: jdField, showPreview: showPreview, showLines: showLines };
    return create;
  }
  function openCreate(opener) {
    var c = createDialog();
    var names = db ? q("SELECT name FROM tracks WHERE status = 'Active' ORDER BY sort, name").map(function (t) { return t.name; }) : [];
    var keep = c.tracks.value || state.track || "Original";
    c.tracks.textContent = "";
    names.forEach(function (n) { c.tracks.appendChild(h("option", { value: n, selected: n === keep }, n)); });
    c.msg.textContent = db ? "" : "Your career file is still loading.";
    var jds = db ? q("SELECT id, title, path, doc_date FROM originals WHERE kind = 'Job description' ORDER BY doc_date DESC, id DESC")
      .filter(function (o) { return texts[o.id]; }) : [];
    c.jd.textContent = "";
    c.jd.appendChild(h("option", { value: "" }, "Choose\u2026"));
    jds.forEach(function (o) {
      c.jd.appendChild(h("option", { value: String(o.id) }, joinNonEmpty([o.title || o.path.split("/").pop(), o.doc_date])));
    });
    c.jdField.hidden = !jds.length;
    c.showLines();
    c.showPreview();
    openDialog(c.el, opener && opener.nodeType ? opener : document.getElementById("create-resume"), c.heading);
  }

  // ---------- detail pop-up (read-only) ----------
  function changedBy(table, row) {
    var actor = changes[table + ":" + row.id];
    var when = row.updated_at ? new Date(row.updated_at) : null;
    return joinNonEmpty([actor ? WHO[actor] : "", when && !isNaN(when) ? when.toLocaleString() : row.updated_at], ", ");
  }
  function jobText(r) { return r.position_id ? joinNonEmpty([r.job_title, r.employer], " — ") : ""; }
  // An item as people say it: its title, else what was done, else its kind. Never cut short (it names buttons).
  function itemName(r) { return r.title || r.detail || r.kind; }
  function shortText(text, n) { return text.length > n ? text.slice(0, n - 1) + "\u2026" : text; }
  // [Item, original] pairs and metrics are read live, so a detail pop-up and a card always agree.
  function itemMetrics(id) {
    return q("SELECT * FROM item_metrics WHERE item_id = ? ORDER BY sort, id", [id]);
  }
  function itemAttachments(id) {
    return q("SELECT l.rowid AS id, l.*, o.title AS original_title, o.path AS original_path, o.kind AS original_kind" +
      " FROM item_originals l JOIN originals o ON o.id = l.original_id WHERE l.item_id = ? ORDER BY l.rowid", [id]);
  }
  function originalName(o) { return o.original_title || (o.original_path || "").split("/").pop(); }
  function metricText(m) { return joinNonEmpty([m.value, m.unit], " "); }

  // ---------- dates outside the job (a warning, never a block; the browser only) ----------
  // A year alone ("2021") stands for any month of it: dateKey(v, false) is its first month, dateKey(v, true) its last.
  // Only dates that are surely outside the job count, so "2020" for a job that began 2020-03 draws no warning.
  function dateKey(v, last) {
    var d = normDate(v);
    if (!d) return null;
    return d.length === 4 ? d + (last ? "-12" : "-01") : d;
  }
  // "" when the item's dates fit the position's (or there is nothing to compare); else a sentence.
  function dateWarning(item, pos) {
    if (!pos) return "";
    var sLo = dateKey(item.start_date, false), sHi = dateKey(item.start_date, true);
    var eLo = dateKey(item.end_date, false), eHi = dateKey(item.end_date, true);
    var ps = dateKey(pos.start_date, false), pe = dateKey(pos.end_date, true);
    var out = (sHi && ps && sHi < ps) || (eHi && ps && eHi < ps) || (sLo && pe && sLo > pe) || (eLo && pe && eLo > pe);
    if (!out) return "";
    return "Check the dates: they fall outside this job's dates (" + (span(pos.start_date, pos.end_date) || "no dates saved") +
      "). You can still save.";
  }
  function positionDates(id) {
    return id ? q("SELECT start_date, end_date FROM positions WHERE id = ?", [id])[0] || null : null;
  }
  function itemWarning(item) { return dateWarning(item, positionDates(item.position_id)); }

  function factList(pairs) {
    return h("dl", { class: "facts detail-facts" }, pairs.map(function (f) {
      var v = f[1] === null || f[1] === undefined || f[1] === "" ? null : f[1];
      return [h("dt", null, f[0]), h("dd", { class: v === null ? "muted" : null }, v === null ? "(none)" : String(v))];
    }));
  }
  function detailBody(table, id) {
    if (table === "items") {
      var a = q("SELECT i.*, p.title AS job_title, e.name AS employer, par.title AS parent_title, par.detail AS parent_detail," +
        " par.kind AS parent_kind FROM items i LEFT JOIN positions p ON p.id = i.position_id" +
        " LEFT JOIN employers e ON e.id = p.employer_id LEFT JOIN items par ON par.id = i.parent_item_id WHERE i.id = ?", [id])[0];
      var lines = visible(q("SELECT * FROM bullet_variants WHERE item_id = ? ORDER BY track, id", [id]));
      var nums = visible(itemMetrics(id));
      var files = visible(itemAttachments(id));
      var warn = itemWarning(a);
      return ["Item", [factList([["Kind", a.kind], ["Title", a.title], ["What was done", a.detail], ["Outputs", a.outputs],
        ["Job", jobText(a) || "Not tied to a job"], ["Inside", a.parent_item_id ? itemName({ title: a.parent_title, detail: a.parent_detail, kind: a.parent_kind }) : null],
        ["Organization", a.organization], ["From whom", a.from_whom], ["Dates", recordDate(a.start_date, a.end_date)],
        ["Source", a.source], ["Notes", a.notes], ["Status", shown(a.status)], ["Last changed", changedBy("items", a)]]),
        warn ? h("p", { class: "date-warn" }, warn) : null,
        h("h3", null, "Numbers (" + nums.length + ")"),
        nums.length ? h("ul", { class: "detail-lines" }, nums.map(function (m) {
          return h("li", null, h("p", null, metricText(m)), h("p", { class: "small muted" }, joinNonEmpty([m.label, m.as_of ? "As of " + m.as_of : "", "Status: " + shown(m.status)])));
        })) : h("p", { class: "muted" }, "No numbers yet."),
        h("h3", null, "Attached originals (" + files.length + ")"),
        files.length ? h("ul", { class: "detail-lines" }, files.map(function (f) {
          return h("li", null, h("p", null, originalName(f)), f.note ? h("p", { class: "small muted" }, f.note) : null);
        })) : h("p", { class: "muted" }, "No originals attached."),
        h("h3", null, "Resume lines (" + lines.length + ")"),
        lines.length ? h("ul", { class: "detail-lines" }, lines.map(function (l) {
          return h("li", null, h("p", null, l.wording), h("p", { class: "small muted" }, joinNonEmpty([
            "Version: " + l.track, l.length ? "Length: " + shown(l.length) : "", l.angle ? "Focus: " + l.angle : "",
            "Status: " + shown(l.status)])));
        })) : h("p", { class: "muted" }, "No resume lines yet.")]];
    }
    var b = q("SELECT b.*, i.title AS item_title, i.detail AS item_detail, i.kind AS item_kind, i.position_id, p.title AS job_title," +
      " e.name AS employer FROM bullet_variants b JOIN items i ON i.id = b.item_id LEFT JOIN positions p ON p.id = i.position_id" +
      " LEFT JOIN employers e ON e.id = p.employer_id WHERE b.id = ?", [id])[0];
    return ["Resume line", [factList([["Wording", b.wording], ["Item", itemName({ title: b.item_title, detail: b.item_detail, kind: b.item_kind })],
      ["Job", jobText(b)], ["Version", b.track], ["Focus", b.angle], ["Length", shown(b.length)], ["Status", shown(b.status)],
      ["Source", b.source], ["Last changed", changedBy("bullet_variants", b)]])]];
  }
  var detail = null;
  function openDetail(table, row, opener) {
    if (!detail) {
      var title = h("h2", { id: "detail-title" });
      var body = h("div", { class: "detail-body" });
      var close = h("button", { type: "button", class: "btn ghost", onclick: function () { el.close(); } }, "Close");
      var el = makeDialog("detail-dialog", "detail-title", [title, body, h("div", { class: "form-actions" }, close)]);
      detail = { el: el, title: title, body: body, close: close };
    }
    var d = detailBody(table, row.id);
    detail.title.textContent = d[0];
    detail.body.textContent = "";
    add(detail.body, d[1]);
    openDialog(detail.el, opener, detail.close);
    detail.body.scrollTop = 0;
  }

  function empty(title, text, addBtn) {
    return h("div", { class: "empty" }, h("strong", null, title), h("span", null, text),
      addBtn ? h("div", { style: "margin-top:14px" }, addBtn) : null);
  }
  function editButton(key, label, text) {
    if (!EDIT) return null;
    return h("button", { type: "button", class: "btn quiet", "aria-label": label, onclick: function () { startEdit(key); } }, text || "Edit");
  }
  // Rarely used buttons behind one "More" toggle (Q&A: Remove), so each card has fewer Tab stops.
  function moreMenu(btn, label) {
    if (!btn) return null;
    return h("details", { class: "more" }, h("summary", { class: "btn quiet", "aria-label": "More: " + label }, "More"),
      h("div", { class: "more-menu" }, btn));
  }
  function addButton(table, label, defaults, name) {
    if (!EDIT) return null;
    return h("button", { type: "button", class: "btn ghost", "aria-label": name || null, onclick: function () { startEdit("new:" + table, defaults || {}); } }, label);
  }
  function removeButton(table, row, label) {
    if (!EDIT || REMOVABLE.indexOf(table) < 0 || isRetired(row)) return null;
    return h("button", { type: "button", class: "btn quiet", "aria-label": "Remove " + label,
      onclick: function () { confirmRemove(table, row, label, this); } }, "Remove");
  }
  function removeQuestion(label) { return "Remove “" + label + "”? You can restore it later."; }
  // Asks first. Cancel has focus, so Enter or Escape keeps the row.
  var ask = null;
  function confirmRemove(table, row, label, opener) {
    if (!ask) {
      var title = h("h2", { id: "remove-title" });
      var cancel = h("button", { type: "button", class: "btn ghost", onclick: function () { el.close(); } }, "Cancel");
      var yes = h("button", { type: "button", class: "btn", onclick: function () {
        var remove = ask.remove;
        el.close();
        remove();
      } }, "Remove");
      var el = makeDialog("remove-dialog", "remove-title", [title, h("div", { class: "form-actions" }, yes, cancel)]);
      ask = { el: el, title: title, cancel: cancel };
    }
    ask.title.textContent = removeQuestion(label);
    ask.remove = function () { removeRow(table, row, label); };
    openDialog(ask.el, opener, ask.cancel);
  }
  // The status a removed row goes back to: the one it had before it was removed (change log), else the table's live one.
  function liveStatus(table, row) {
    var was = q("SELECT json_extract(old_json, '$.status') AS s FROM audit WHERE table_name = ? AND row_id = ? AND op = 'update'" +
      " AND json_extract(new_json, '$.status') = ? ORDER BY id DESC LIMIT 1", [table, row.id, row.status])[0];
    if (was && was.s && RETIRED.indexOf(was.s) < 0) return was.s;
    if (table === "links" || table === "tracks" || table === "item_originals") return "Active";
    if (table === "qa") return row.answer && row.answer.trim() ? "Needs review" : "Needs answer";
    return "Needs review";
  }
  function restoreButton(table, row, label) {
    if (!EDIT || REMOVABLE.indexOf(table) < 0 || !isRetired(row)) return null;
    return h("button", { type: "button", class: "btn quiet", "aria-label": "Restore " + label, onclick: function () {
      var before = updated, key = table + ":" + row.id;
      http("POST", "/save", { table: table, row: { id: row.id, status: liveStatus(table, row) }, expected_updated_at: row.updated_at })
        .then(function () { return waitForRebuild(before, 25); }).then(function () {
          render();
          announce("Restored");
          focusItem(key);
        }).catch(function (err) { showError(plainError(err.message, "Couldn't restore")); });
    } }, "Restore");
  }
  // The removed row's card turns into an Undo spot (state.removed) until the user moves on.
  function removeRow(table, row, label) {
    if (!leaveForm()) return Promise.resolve();
    var before = updated, key = table + ":" + row.id;
    state.editing = null;
    return http("POST", "/retire", { table: table, id: row.id }).then(function () { return waitForRebuild(before, 25); }).then(function () {
      state.removed = { key: key, table: table, id: row.id, status: row.status, label: label };
      render();
      announce("Removed \u2014 kept in history");
      focusItem(key);
    }).catch(function (err) { showError(plainError(err.message)); });
  }
  function undoRemove() {
    var r = state.removed, at = updated;
    return http("POST", "/save", { table: r.table, row: { id: r.id, status: r.status }, expected_updated_at: null })
      .then(function () { return waitForRebuild(at, 25); }).then(function () {
        state.removed = null;
        render();
        announce("Back again");
        focusItem(r.key);
      }).catch(function (err) { showError(plainError(err.message)); });
  }
  function undoSpot(key, label) {
    return h("div", { class: "card undo-spot", "data-key": key }, h("span", null, "Removed \u2014 kept in history"),
      h("button", { type: "button", class: "btn quiet undo", "aria-label": "Undo removing " + label, onclick: undoRemove }, "Undo"));
  }
  function dirty() {
    var d = state.editing && drafts[state.editing];
    return !!d && Object.keys(d.typed).some(function (c) { return d.typed[c] !== d.base[c]; });
  }
  // Before closing the open form some other way than Save/Cancel. False: the user kept it open.
  function leaveForm() {
    if (dirty() && !window.confirm("Discard your changes?")) return false;
    delete drafts[state.editing];
    return true;
  }
  // The same form again (e.g. "Add" clicked twice) keeps its draft; another one asks first when there is typing.
  function startEdit(key, defaults) {
    var other = state.editing === key && !!defaults && JSON.stringify(defaults) !== JSON.stringify(state.newDefaults);  // e.g. "Add a position" under another employer
    if (state.editing !== key || other) {
      if (!leaveForm()) return;
      state.conflict = null;
    }
    if (defaults) state.newDefaults = defaults;
    state.editing = key;
    state.saved = null;
    state.removed = null;
    render();
    var form = document.querySelector(".card.editing input, .card.editing textarea, .card.editing select");
    if (form) form.focus();
  }
  function stopEdit() {
    var key = state.editing;
    delete drafts[key];
    state.editing = null;
    state.conflict = null;
    render();
    focusItem(key);
  }

  // A row card: title, subtitle, body nodes, meta nodes. Turns into a form while being edited.
  // With detail set, clicking the card (or Enter/Space on it) opens the detail pop-up.
  function card(table, row, title, sub, body, meta, ai, detail) {
    var key = table + ":" + row.id;
    var editing = state.editing === key;
    var label = typeof title === "string" ? title : detail || tableNoun(table);
    if (state.removed && state.removed.key === key) return undoSpot(key, label);
    var remove = editing ? null : removeButton(table, row, label);
    var edit = editing ? null : table !== "qa" ? editButton(key, "Edit " + label)
      : row.answer && row.answer.trim() ? editButton(key, "Edit answer: " + label) : editButton(key, "Answer: " + label, "Answer");
    var restore = editing ? null : restoreButton(table, row, label);
    var tools = h("div", { class: "row-tools" }, who(table, row.id), edit, table === "qa" ? moreMenu(remove, label) : remove, restore);
    var items = (meta || []).concat(state.saved === key ? h("span", { class: "ok-msg" }, "Saved") : null).filter(function (m) { return m; }).map(function (m) {
      return typeof m === "object" ? m : h("span", null, m);
    });
    if (!title && !editing) items.push(tools);
    var open = detail && !editing ? function (e) {
      if (e.type === "keydown" && (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " "))) return;
      if (e.type === "click" && e.target.closest("button,a,input,textarea,select,form,dialog")) return;
      e.preventDefault();
      openDetail(table, row, e.currentTarget);
    } : null;
    return h("article", { class: "card" + (editing ? " editing" : "") + (isRetired(row) ? " retired" : "") + (open ? " opens" : ""),
      "data-key": key, role: open ? "button" : null, tabindex: open ? "0" : null, "aria-label": open ? "Details: " + detail : null,
      onclick: open, onkeydown: open },
      title || editing ? h("div", { class: "row-top" },
        h("div", null, title ? h("p", { class: "row-title" }, title, editing ? null : ai) : null, sub ? h("p", { class: "row-sub" }, sub) : null),
        tools) : null,
      editing ? form(table, row, label) : [body, items.length ? h("div", { class: "row-meta" }, items) : null]);
  }
  function tableNoun(table) { return { bullet_variants: "resume line", skills: "skill", tracks: "version",
      item_metrics: "number", item_originals: "attachment" }[table] || table.replace(/_/g, " "); }
  function newForm(table, title) {
    if (state.editing !== "new:" + table) return null;
    return h("article", { class: "card editing" }, h("p", { class: "row-title" }, title), form(table, null));
  }

  // Removed employers, positions, items and versions are offered only when the row already points at them (val).
  // "parent": opts = [the item being edited], which (with everything inside it) cannot be its own parent.
  function optionsFor(kind, opts, val) {
    if (kind === "job" || kind === "position") {
      return [["", "Not tied to a job"]].concat(q("SELECT p.id, p.title, e.name AS employer FROM positions p" +
        " JOIN employers e ON e.id = p.employer_id WHERE p.status <> 'Deprecated' OR p.id = ?" +
        " ORDER BY p.sort_order IS NULL, p.sort_order, p.start_date DESC", [val || null])
        .map(function (j) { return [String(j.id), j.title + " — " + j.employer]; }));
    }
    if (kind === "employer") {
      return q("SELECT id, name FROM employers WHERE status <> 'Deprecated' OR id = ? ORDER BY name", [val || null])
        .map(function (m) { return [String(m.id), m.name]; });
    }
    if (kind === "parent") {
      var self = opts && opts[0] ? opts[0] : null;
      return [["", "Not inside another item"]].concat(q("WITH RECURSIVE inside(id) AS (SELECT ? UNION SELECT i.id FROM items i JOIN inside ON i.parent_item_id = inside.id)" +
        " SELECT id, kind, title, detail FROM items WHERE (status <> 'Deprecated' OR id = ?) AND id NOT IN (SELECT id FROM inside) ORDER BY id",
        [self, val || null]).map(function (a) { return [String(a.id), shortText(a.kind + ": " + itemName(a), 70)]; }));
    }
    if (kind === "item") {
      return q("SELECT id, kind, title, detail FROM items WHERE status <> 'Deprecated' OR id = ? ORDER BY id", [val || null]).map(function (a) {
        return [String(a.id), shortText(itemName(a), 70)];
      });
    }
    if (kind === "track") {
      return q("SELECT name FROM tracks WHERE status = 'Active' OR name = ? ORDER BY sort, name", [val || null])
        .map(function (t) { return [t.name, t.name]; });
    }
    return opts.map(function (o) { return [o, kind === "select" && WEIGHT[o] ? o + " – " + WEIGHT[o] : (shown(o) || "(none)")]; });
  }
  // [options, value] for a select. New rows: no "Removed" status (a new item starts under the most recent job: recentJob). An empty value with no empty
  // option: the only option is picked, otherwise a "Choose…" placeholder leads.
  function choices(kind, opts, val, isNew) {
    var list = optionsFor(kind, opts, val);
    if (isNew) list = list.filter(function (o) { return RETIRED.indexOf(o[0]) < 0; });
    if (val === "" && !list.some(function (o) { return o[0] === ""; })) {
      if (list.length === 1) val = list[0][0];
      else list = [["", "Choose\u2026"]].concat(list);
    }
    return [list, val];
  }

  // After a 409 (state.conflict) the form shows what the user typed, the latest saved value under each field that
  // differs, and saves against that latest version.
  // label: the item's name, for the Remove button inside the form.
  function form(table, row, label) {
    var fields = FORMS[table];
    var key = row ? table + ":" + row.id : "new:" + table;
    var conflict = row && state.conflict && state.conflict.key === key ? state.conflict : null;
    if (conflict && conflict.latest) row = conflict.latest;
    var start = row || state.newDefaults || {};
    var draft = drafts[key] = { base: {}, typed: drafts[key] ? drafts[key].typed : {} };
    var inputs = {};
    var uid = "f-" + table + "-" + (row ? row.id : "new");
    var els = fields.map(function (f) {
      var col = f[0], kind = f[2] || "text", id = uid + "-" + col, options = null;
      var val = start[col] === null || start[col] === undefined ? "" : String(start[col]);
      if (kind === "select" || kind === "job" || kind === "position" || kind === "employer" || kind === "parent" || kind === "item" || kind === "track") {
        var c = choices(kind, typeof f[3] === "function" ? f[3](row) : f[3] || [], val, !row);
        options = c[0];
        val = c[1];
      }
      draft.base[col] = val;
      var saved = val;
      if (col in draft.typed) val = draft.typed[col];
      var latest = !conflict || saved === val ? null : h("p", { class: "small muted", id: id + "-latest" }, "Latest saved: " +
        (options ? (options.filter(function (o) { return o[0] === saved; })[0] || [0, saved || "(empty)"])[1] : saved || "(empty)"));
      var hintText = kind === "date" ? "YYYY or YYYY-MM" : HINTS[col];
      var hint = hintText ? h("p", { class: "small muted", id: id + "-hint" }, hintText) : null;
      var input;
      if (kind === "area") input = h("textarea", { id: id, name: col, value: val, rows: col === "answer" ? 6 : 3 });
      else if (options) {
        input = h("select", { id: id, name: col }, options.map(function (o) {
          return h("option", { value: o[0], selected: o[0] === val }, o[1]);
        }));
        input.value = val;
      } else input = h("input", { id: id, name: col, type: kind === "number" ? "number" : "text", value: val,
        placeholder: kind === "date" ? "e.g. 2021 or 2021-06" : PLACEHOLDER[col] || null, required: REQUIRED[table] && REQUIRED[table][col] ? true : null });
      inputs[col] = input;
      var described = joinNonEmpty([hint && hint.id, latest && latest.id], " ");
      if (described) input.setAttribute("aria-describedby", described);
      return h("div", { class: kind === "area" ? "field wide" : "field" }, h("label", { for: id }, f[1]), input, hint, latest);
    });
    // Items: a visible, non-blocking note while the dates sit outside the job's. Saving still works.
    var showWarn = null;
    if (table === "items") {
      var warnEl = h("p", { class: "date-warn field wide", id: uid + "-datewarn", "aria-live": "polite" });
      showWarn = function () {
        var pid = parseInt(inputs.position_id.value, 10);
        warnEl.textContent = dateWarning({ start_date: inputs.start_date.value, end_date: inputs.end_date.value },
          isNaN(pid) ? null : positionDates(pid));
      };
      els.splice(fields.map(function (f) { return f[0]; }).indexOf("end_date") + 1, 0, warnEl);
      showWarn();
    }
    var saveBtn = h("button", { type: "submit", class: "btn" }, "Save");
    var msg = h("p", { class: "form-msg", role: "alert" }, conflict ? "Not saved: this was changed elsewhere (maybe by your AI). " +
      "Your typing is kept; the latest saved value is under each field that differs. Save again to keep yours." : null);
    var el = h("form", { class: "form", noValidate: true, onsubmit: function (e) {
      e.preventDefault();
      msg.textContent = "";
      var bad = checkForm(table, fields, inputs);
      if (bad) {
        msg.textContent = bad[1];
        bad[0].setAttribute("aria-invalid", "true");
        bad[0].focus();
        return;
      }
      saveBtn.disabled = true;
      save(table, row, inputs).catch(function (err) {
        saveBtn.disabled = false;
        if (err.status !== 409) msg.textContent = plainError(err.message);
      });
    } }, els, h("div", { class: "form-actions" }, saveBtn,
      h("button", { type: "button", class: "btn ghost", onclick: stopEdit }, "Cancel"),
      row ? removeButton(table, row, label) : null,
      h("span", { class: "hint" }, "or ask your AI to do it")), msg);
    el.addEventListener("input", function (e) { if (e.target.name) draft.typed[e.target.name] = e.target.value; });
    if (showWarn) { el.addEventListener("input", showWarn); el.addEventListener("change", showWarn); }
    el.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && leaveForm()) stopEdit();
    });
    return el;
  }

  // First problem as [input, message], dates tidied in place; null when the form can be saved.
  function checkForm(table, fields, inputs) {
    var req = REQUIRED[table] || {}, bad = null;
    fields.forEach(function (f) {
      var input = inputs[f[0]];
      input.removeAttribute("aria-invalid");
      if (bad) return;
      if (req[f[0]] && !input.value.trim()) bad = [input, req[f[0]]];
      else if (f[2] === "date") {
        var d = normDate(input.value);
        if (d === null) bad = [input, DATE_RULE];
        else input.value = d;
      }
    });
    if (!bad && table === "items" && !inputs.title.value.trim() && !inputs.detail.value.trim()) {
      bad = [inputs.title, "Give the item a title or say what was done"];
    }
    return bad;
  }

  // Columns a new row needs that the form does not show: the item a number belongs to.
  var HIDDEN_NEW = { item_metrics: ["item_id"] };
  function save(table, row, inputs) {
    var out = {};
    Object.keys(inputs).forEach(function (col) {
      var v = inputs[col].value.trim();
      var old = row && row[col] !== null && row[col] !== undefined ? String(row[col]) : "";
      if (row && v === old) return;
      if (!row && v === "") return;
      out[col] = v === "" ? null : (/_id$|^weight$|^sort$|^sort_order$/.test(col) ? parseInt(v, 10) : v);
    });
    if (out.extracted === TYPED_IN) out.extracted = "Done";
    if (!row && HIDDEN_NEW[table] && Object.keys(out).length) {
      HIDDEN_NEW[table].forEach(function (col) { out[col] = parseInt(state.newDefaults[col], 10); });
    }
    var key = row ? table + ":" + row.id : "new:" + table, draft = drafts[key];
    // An answer the user typed is theirs: Verified, unless they picked a status in this form. AI answers stay Needs review.
    if (table === "qa" && out.answer && !(draft && "status" in draft.typed && draft.typed.status !== draft.base.status)) out.status = "Verified";
    if (!Object.keys(out).length) { stopEdit(); return Promise.resolve(); }
    if (!row && PERSON_TABLES.indexOf(table) >= 0) {
      var p = activePerson();
      if (p) out.person_id = p.id;
      else if (table !== "qa") return Promise.reject(new Error("Add your profile first (Profile tab)"));
    }
    if (row) out.id = row.id;
    var before = updated;
    return http("POST", "/save", { table: table, row: out, expected_updated_at: row ? row.updated_at : null })
      .then(function (res) {
        delete drafts[key];
        state.editing = null;
        state.conflict = null;
        state.saved = table + ":" + (row ? row.id : res.id);
        return waitForRebuild(before, 25);
      }, function (err) {
        if (err.status === 409) {
          return refresh().then(function () {
            state.conflict = { key: key, latest: err.body && err.body.current };
            render();
            var first = document.querySelector(".card.editing [aria-describedby*=\"-latest\"], .card.editing input, .card.editing textarea, .card.editing select");
            if (first) first.focus();
          });
        }
        throw err;
      }).then(function () {
        if (state.editing) return;
        render();
        announce(row ? "Saved" : "Added");
        focusItem(state.saved);
      });
  }

  // ---------- views ----------
  var VIEWS = {};
  // Section-level AI prompts, shown at the bottom right of the tab.
  // AI prompt robots shown right after each tab's heading.
  var HEAD_AI = {
    profile: function () { return fillButton("people"); },
    experience: function () { return [fillButton("experience"), tailorButton(CHAIN[0].sql)]; },
    items: function () { return [fillButton("items"), fillButton("metrics")]; },
    lines: function () { return [fillButton("bullet_variants"), tailorButton(CHAIN[2].sql)]; },
    qa: function () { return fillButton("qa"); },
    originals: function () { return fillButton("originals"); }
  };

  VIEWS.profile = function () {
    var people = visible(q("SELECT * FROM people ORDER BY status = 'Active' DESC, id"));
    var out = sectionHead("Profile", "Who you are, how to reach you, what you know.");
    if (!people.length) {
      out.push(newForm("people", "New profile") || empty("No profile yet",
        "Ask your AI to start from your resume, or add it here.", addButton("people", "Add your profile")));
      return out;
    }
    people.forEach(function (p) {
      var img = q("SELECT mime, image FROM images WHERE person_id = ? AND status = 'Active'", [p.id])[0];
      var facts = [["Location", p.location], ["Email", p.email], ["Phone", p.phone], ["LinkedIn", p.linkedin],
        ["Work authorization", p.work_authorization]].filter(function (f) { return f[1]; });
      var body = h("div", { class: "profile" },
        img && img.image && img.image.length ? h("img", { class: "headshot", alt: "Headshot of " + (p.full_name || p.name),
          src: "data:" + img.mime + ";base64," + bytesToB64(img.image) }) : null,
        h("div", null,
          p.headline ? h("p", { class: "headline" }, p.headline) : h("p", { class: "muted" }, "No headline yet."),
          p.summary ? h("p", null, p.summary) : null,
          facts.length ? h("dl", { class: "facts" }, facts.map(function (f) { return [h("dt", null, f[0]), h("dd", null, f[1])]; })) : null));
      out.push(card("people", p, p.full_name || p.name, isRetired(p) ? p.status : null, body, []));
    });
    var pid = people[0].id;

    var links = visible(q("SELECT * FROM links WHERE person_id = ? ORDER BY sort, id", [pid]), "links");
    out.push(h("section", { class: "group" }, subHead("Links", addButton("links", "Add a link", { kind: "Website" }), fillButton("links")),
      h("div", { class: "grid" }, newForm("links", "New link"), links.map(function (l) {
        return card("links", l, l.label || l.kind, null, h("p", { class: "row-body" }, h("a", { href: l.url, target: "_blank", rel: "noopener" }, l.url)),
          [l.kind, isRetired(l) ? statusEl(l.status) : null]);
      })), links.length || state.editing === "new:links" ? null : h("p", { class: "muted" }, "No links yet.")));

    var skills = visible(q("SELECT * FROM skills WHERE person_id = ? ORDER BY category, name", [pid]), "skills");
    var gone = state.removed && state.removed.table === "skills" ? state.removed.id : null;
    var byCat = {};
    skills.forEach(function (s) { if (s.id !== gone) (byCat[s.category || "Other"] = byCat[s.category || "Other"] || []).push(s); });
    var editingSkill = skills.filter(function (s) { return state.editing === "skills:" + s.id || s.id === gone; })[0];
    out.push(h("section", { class: "group" }, subHead("Skills", addButton("skills", "Add a skill", { category: "Skill", status: "Verified" }), fillButton("skills")),
      newForm("skills", "New skill"),
      editingSkill ? card("skills", editingSkill, editingSkill.name) : null,
      Object.keys(byCat).length ? h("div", { class: "card" }, Object.keys(byCat).map(function (cat) {
        return h("div", { style: "margin-bottom:10px" }, h("p", { class: "row-sub", style: "margin-bottom:6px" }, cat),
          h("ul", { class: "chips" }, byCat[cat].map(function (s) {
            var label = s.name + (s.status === "Needs review" ? " (needs review)" : "");
            return h("li", { class: "chip" + (isRetired(s) ? " retired" : ""), "data-key": "skills:" + s.id }, EDIT
              ? h("button", { type: "button", style: "all:unset;cursor:pointer", "aria-label": "Edit skill " + s.name,
                onclick: function () { startEdit("skills:" + s.id); } }, label) : label, restoreButton("skills", s, s.name));
          })));
      })) : editingSkill ? null : h("p", { class: "muted" }, "No skills yet.")));

    var edu = visible(q("SELECT * FROM education WHERE person_id = ? ORDER BY year DESC, id", [pid]), "education");
    out.push(h("section", { class: "group" }, subHead("Education and training", addButton("education", "Add education", { kind: "Course", status: "Verified" }), fillButton("education")),
      h("div", { class: "grid" }, newForm("education", "New education"), edu.map(function (e) {
        return card("education", e, e.name, joinNonEmpty([e.kind, e.institution, e.year]), null,
          [e.status !== "Verified" ? statusEl(e.status) : null]);
      })), edu.length || state.editing === "new:education" ? null : h("p", { class: "muted" }, "No education yet.")));
    return out;
  };

  // Employers, each with the positions held there (a promotion is a second position under the same employer).
  VIEWS.experience = function () {
    var employers = visible(q("SELECT m.*," +
      " (SELECT min(coalesce(x.sort_order, 1000000)) FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated') AS first_order," +
      " (SELECT max(coalesce(x.end_date, '9999')) FROM positions x WHERE x.employer_id = m.id AND x.status <> 'Deprecated') AS last_end" +
      " FROM employers m ORDER BY first_order IS NULL, first_order, last_end DESC, m.id"), "employers");
    var positions = visible(q("SELECT p.*, (SELECT count(*) FROM items i WHERE i.position_id = p.id AND i.status <> 'Deprecated') AS n" +
      " FROM positions p ORDER BY p.sort_order IS NULL, p.sort_order, p.start_date DESC, p.id"), "positions");
    var out = sectionHead("Experience", "Your employers and the positions you held at each, newest first. " +
      "A promotion is a second position under the same employer.", addButton("employers", "Add an employer", { status: "Verified" }));
    out.push(newForm("employers", "New employer"));
    if (!employers.length && state.editing !== "new:employers") {
      out.push(empty("No employers yet", "Ask your AI to read your past resumes in Originals, or add an employer here."));
      return out;
    }
    employers.forEach(function (m) {
      var mine = positions.filter(function (p) { return p.employer_id === m.id; });
      var adding = state.editing === "new:positions" && state.newDefaults && String(state.newDefaults.employer_id) === String(m.id);
      out.push(h("section", { class: "group employer", "data-employer": String(m.id) },
        card("employers", m, m.name, joinNonEmpty([m.location, m.website]),
          m.notes ? h("p", { class: "row-body" }, m.notes) : null,
          [mine.length + (mine.length === 1 ? " position" : " positions"), statusEl(m.status)]),
        h("div", { class: "stack positions" },
          adding ? h("article", { class: "card editing" }, h("p", { class: "row-title" }, "New position at " + m.name), form("positions", null)) : null,
          mine.map(function (j) {
            return card("positions", j, j.title, j.department,
              j.notes ? h("p", { class: "row-body" }, j.notes) : null,
              [span(j.start_date, j.end_date), j.n + (j.n === 1 ? " item" : " items"), statusEl(j.status)]);
          }),
          !mine.length && !adding ? h("p", { class: "muted small" }, "No positions here yet.") : null,
          addButton("positions", "Add a position", { employer_id: String(m.id), status: "Verified" }, "Add a position at " + m.name))));
    });
    return out;
  };

  // The newest job's id as a string, "" when there is none: what a new item starts under.
  function recentJob() { return String((q(MOST_RECENT_JOB)[0] || { id: "" }).id); }
  // One item and, indented under it, the items inside it.
  function itemTree(r, ctx) {
    var kids = ctx.kids[r.id] || [];
    return h("li", { class: "item-node" }, itemCard(r, ctx),
      kids.length ? h("ul", { class: "item-children", "aria-label": "Inside " + itemName(r) }, kids.map(function (k) { return itemTree(k, ctx); })) : null);
  }
  function itemCard(r, ctx) {
    var name = itemName(r);
    var warn = r.position_id ? dateWarning(r, { start_date: r.job_start, end_date: r.job_end }) : "";
    var lines = ctx.lines[r.id] || [];
    var ms = visible(ctx.metrics[r.id] || [], "item_metrics");
    var files = visible(ctx.files[r.id] || [], "item_originals");
    var addingNumber = state.editing === "new:item_metrics" && state.newDefaults && String(state.newDefaults.item_id) === String(r.id);
    var from = !files.length && r.source ? h("span", { class: "len" }, "From: " + r.source) : null;
    return card("items", r, name, joinNonEmpty([r.kind, r.organization, r.from_whom]), [
      r.title && r.detail ? h("p", { class: "row-body" }, r.detail) : null,
      r.outputs ? h("p", { class: "result" }, h("span", { class: "result-label" }, "Outputs"), h("span", null, r.outputs)) : null,
      h("div", { class: "item-part metrics" }, h("p", { class: "row-sub" }, "Numbers"),
        ms.length ? h("ul", { class: "metric-list" }, ms.map(function (m) {
          return h("li", { class: "metric-item" }, card("item_metrics", m, joinNonEmpty([m.label, metricText(m)], ": "), null, null,
            [m.as_of ? "As of " + m.as_of : null, reviewFlag(m.status)]));
        })) : addingNumber ? null : h("p", { class: "muted small" }, "No numbers yet."),
        addingNumber ? h("article", { class: "card editing" }, h("p", { class: "row-title" }, "New number"), form("item_metrics", null)) : null,
        addButton("item_metrics", "Add a number", { item_id: String(r.id), status: "Verified", sort: "100" }, "Add a number to " + name)),
      h("div", { class: "item-part attachments" }, h("p", { class: "row-sub" }, "Originals attached"),
        files.length ? h("ul", { class: "attach-list" }, files.map(function (f) {
          return h("li", { class: "attach-item" }, card("item_originals", f, "Attached: " + originalName(f), f.note, null,
            [f.original_kind, isRetired(f) ? statusEl(f.status) : null]));
        })) : h("p", { class: "muted small" }, "No originals attached."),
        EDIT ? attachPicker(r, ctx.files[r.id] || [], name) : null),
      lines.length ? h("ul", { class: "sub-lines tree", "aria-label": "Resume lines written from this" }, lines.map(function (l) {
        return h("li", null, l.wording, " ", lineChip(l));
      })) : h("p", { class: "muted small sub-none" }, "No resume lines yet.")],
      [recordDate(r.start_date, r.end_date), warn ? h("span", { class: "date-warn" }, warn) : null, from, reviewFlag(r.status)],
      aiButton("Write resume lines with your AI: " + name, function () { return linesPrompt(r.id); }), name);
  }
  // Pick one of the originals not yet attached; "Attach" links it to this item.
  function attachPicker(item, links, name) {
    var linked = {};
    links.forEach(function (l) { if (!isRetired(l)) linked[l.original_id] = true; });
    var free = q("SELECT id, title, path FROM originals ORDER BY doc_date DESC, id DESC").filter(function (o) { return !linked[o.id]; });
    if (!free.length) return null;
    var pick = h("select", { class: "attach-pick", id: "attach-" + item.id, "aria-label": "Original to attach to " + name },
      h("option", { value: "" }, "Attach an original\u2026"), free.map(function (o) {
        return h("option", { value: String(o.id) }, o.title || o.path.split("/").pop());
      }));
    return h("div", { class: "attach-add" }, pick,
      h("button", { type: "button", class: "btn quiet", "aria-label": "Attach the chosen original to " + name,
        onclick: function () { attachOriginal(item, pick, this); } }, "Attach"));
  }
  function attachOriginal(item, pick, btn) {
    var oid = parseInt(pick.value, 10);
    if (!oid) { showError("Choose an original to attach first"); pick.focus(); return; }
    var before = updated;
    var old = q("SELECT rowid AS id, updated_at FROM item_originals WHERE item_id = ? AND original_id = ?", [item.id, oid])[0];
    btn.disabled = true;
    // A link that was removed earlier comes back; otherwise a new link is made.
    http("POST", "/save", old ? { table: "item_originals", expected_updated_at: old.updated_at, row: { id: old.id, status: "Active" } }
      : { table: "item_originals", expected_updated_at: null, row: { item_id: item.id, original_id: oid, status: "Active" } })
      .then(function (res) { return waitForRebuild(before, 25).then(function () { return res.id; }); })
      .then(function (id) {
        render();
        announce("Attached");
        focusItem("item_originals:" + id);
      })
      .catch(function (err) { btn.disabled = false; showError(plainError(err.message, "Couldn't attach")); });
  }

  // One Items view for every kind. Positions as headings, items inside them (children indented), then the rest.
  VIEWS.items = function () {
    var rows = visible(q("SELECT i.*, p.start_date AS job_start, p.end_date AS job_end FROM items i" +
      " LEFT JOIN positions p ON p.id = i.position_id ORDER BY i.id"), "items");
    var out = sectionHead("Items", "Everything you did or received: projects, responsibilities, achievements, awards, reviews and more. " +
      "Each can sit under a job, or stand alone. Resume lines are written from these.",
      addButton("items", "Add an item", { kind: "Achievement", status: "Verified", position_id: recentJob() }));
    out.push(newForm("items", "New item"));
    if (!rows.length && state.editing !== "new:items") {
      out.push(empty("No items yet", "Ask your AI to pull them from your reviews and job descriptions, or add one here."));
      return out;
    }
    var ctx = { kids: {}, lines: {}, metrics: {}, files: {} };
    var byId = {}, roots = [];
    rows.forEach(function (r) { byId[r.id] = r; });
    rows.forEach(function (r) {
      if (r.parent_item_id && byId[r.parent_item_id]) (ctx.kids[r.parent_item_id] = ctx.kids[r.parent_item_id] || []).push(r);
      else roots.push(r);
    });
    visible(q("SELECT * FROM bullet_variants ORDER BY item_id, track, id")).forEach(function (l) {
      (ctx.lines[l.item_id] = ctx.lines[l.item_id] || []).push(l);
    });
    q("SELECT * FROM item_metrics ORDER BY sort, id").forEach(function (m) {
      (ctx.metrics[m.item_id] = ctx.metrics[m.item_id] || []).push(m);
    });
    q("SELECT l.rowid AS id, l.*, o.title AS original_title, o.path AS original_path, o.kind AS original_kind" +
      " FROM item_originals l JOIN originals o ON o.id = l.original_id ORDER BY l.rowid").forEach(function (f) {
      (ctx.files[f.item_id] = ctx.files[f.item_id] || []).push(f);
    });
    var groups = q("SELECT p.id, p.title, p.start_date, p.end_date, e.name AS employer FROM positions p" +
      " JOIN employers e ON e.id = p.employer_id WHERE p.status <> 'Deprecated'" +
      " ORDER BY p.sort_order IS NULL, p.sort_order, p.start_date DESC, p.id").map(function (p) { return { pos: p, rows: [] }; });
    var loose = { pos: null, rows: [] };
    roots.forEach(function (r) {
      var g = r.position_id ? groups.filter(function (x) { return x.pos.id === r.position_id; })[0] : null;
      (g || loose).rows.push(r);
    });
    loose.rows.sort(function (a, b) {  // not tied to a job: newest first
      var x = a.end_date || a.start_date || "", y = b.end_date || b.start_date || "";
      return x === y ? a.id - b.id : x < y ? 1 : -1;
    });
    groups.concat([loose]).forEach(function (g) {
      if (!g.rows.length) return;
      var name = g.pos ? g.pos.title + " — " + g.pos.employer : "Not tied to a job";
      out.push(h("section", { class: "group item-group", "data-position": g.pos ? String(g.pos.id) : "none" },
        subHead(name, addButton("items", "Add an item", { kind: g.pos ? "Achievement" : "Award", status: "Verified",
          position_id: g.pos ? String(g.pos.id) : "" }, "Add an item to " + name)),
        g.pos && span(g.pos.start_date, g.pos.end_date) ? h("p", { class: "section-hint" }, span(g.pos.start_date, g.pos.end_date)) : null,
        h("ul", { class: "item-list stack acc" }, g.rows.map(function (r) { return itemTree(r, ctx); }))));
    });
    return out;
  };

  // "Short · Original": a line's length and version.
  function lineChip(l) { return h("span", { class: "len" }, joinNonEmpty([shown(l.length), l.track])); }
  function lineCount(rows) {
    var n = rows.filter(function (r) { return !isRetired(r); }).length;
    return n + (n === 1 ? " line" : " lines");
  }
  VIEWS.lines = function () {
    var tracks = q("SELECT name FROM tracks WHERE status = 'Active' ORDER BY sort, name").map(function (t) { return t.name; });
    var rows = visible(q("SELECT b.*, a.title AS item_title, a.detail AS item_detail, a.kind AS item_kind, a.position_id," +
      " p.title AS job_title, e.name AS employer FROM bullet_variants b JOIN items a ON a.id = b.item_id" +
      " LEFT JOIN positions p ON p.id = a.position_id LEFT JOIN employers e ON e.id = p.employer_id" +
      " ORDER BY p.sort_order IS NULL, p.sort_order, b.item_id, b.id"), "bullet_variants");
    if (state.track) rows = rows.filter(function (r) { return r.track === state.track; });
    var select = h("select", { id: "track-filter", onchange: function () { state.track = this.value; render(); } },
      h("option", { value: "" }, "All versions"), tracks.map(function (t) { return h("option", { value: t, selected: t === state.track }, t); }));
    var out = sectionHead("Resume Lines", "Ready-to-use wordings of your items. A version is a set of lines aimed at one kind of job, e.g. Leadership.",
      addButton("bullet_variants", "Add a resume line", { track: state.track || "Original", status: "Verified" }));
    out.push(h("div", { class: "filter" }, h("label", { for: "track-filter" }, h("strong", null, "Show version")), select,
      h("span", { class: "muted small" }, lineCount(rows))));
    out.push(newForm("bullet_variants", "New resume line"));
    if (!rows.length && state.editing !== "new:bullet_variants") {
      out.push(empty("No resume lines here yet", "Ask your AI to write lines from your items for this version."));
      return out;
    }
    var groups = [];
    rows.forEach(function (r) {
      var g = groups[groups.length - 1];
      if (!g || g.id !== r.item_id) groups.push(g = { id: r.item_id, fact: itemName({ title: r.item_title, detail: r.item_detail, kind: r.item_kind }),
        job: r.position_id ? r.job_title + " — " + r.employer : "Not tied to a job", rows: [] });
      g.rows.push(r);
    });
    out.push(h("div", { class: "stack acc" }, groups.map(function (g) {
      return h("article", { class: "card" },
        h("p", { class: "row-title" }, g.fact,
          aiButton("Write resume lines with your AI: " + g.fact, function () { return linesPrompt(g.id); })),
        h("p", { class: "row-sub" }, g.job),
        h("ul", { class: "sub-lines tree", "aria-label": "Resume lines written from this" }, g.rows.map(function (r) {
          return h("li", { class: "line-item" }, card("bullet_variants", r, null, null, h("p", { class: "row-body" }, r.wording),
            [lineChip(r), reviewFlag(r.status)], null, r.wording));
        })));
    })));
    return out;
  };

  VIEWS.qa = function () {
    var rows = visible(q("SELECT * FROM qa ORDER BY (answer IS NULL OR trim(answer) = '') DESC, sort IS NULL, sort, id"), "qa");
    // Keep the order while this tab stays open, so a just-answered question does not jump away.
    var order = state.qaOrder || (state.qaOrder = rows.map(function (r) { return r.id; }));
    var at = function (r) { var i = order.indexOf(r.id); return i < 0 ? order.length + r.id : i; };
    rows.sort(function (a, b) { return at(a) - at(b); });
    var live = rows.filter(function (r) { return !isRetired(r); });
    var open = live.filter(function (r) { return !r.answer || !r.answer.trim(); }).length;
    var out = sectionHead("Interview questions", "Common interview questions and your answers. Unanswered ones are listed first when you open this tab. " +
      (live.length ? (live.length - open) + " of " + live.length + " answered." : ""),
      addButton("qa", "Add a question", { status: "Needs answer", category: "Other" }));
    if (!EDIT) out.push(h("p", { class: "notice" }, "Met a new question in an interview? Ask your AI to add it here and help you answer it."));
    out.push(newForm("qa", "New question"));
    if (!rows.length && state.editing !== "new:qa") {
      out.push(empty("No questions yet", "Ask your AI to add the questions you meet in interviews."));
      return out;
    }
    out.push(h("div", { class: "stack" }, rows.map(function (r) {
      var answered = r.answer && r.answer.trim();
      return card("qa", r, r.question, r.category,
        answered ? h("p", { class: "row-body" }, r.answer) : h("p", { class: "row-body muted" }, "Not answered yet."),
        [statusEl(r.status), r.seeded ? "Common question #" + r.sort : "Added question"],
        aiButton("Answer with your AI: " + r.question, function () { return qaPrompt(r.id); }));
    })));
    return out;
  };

  VIEWS.originals = function () {
    var rows = q("SELECT * FROM originals ORDER BY doc_date DESC, id DESC");
    var out = sectionHead("Originals", "Your unedited source files: past resumes, job descriptions, reviews, letters. " +
      "They stay as they are; facts taken from them go into the other tabs.");
    out.push(EDIT ? dropZone() : h("p", { class: "notice" },
      "Adding files needs the Job-o-Matic app running (this page is a view-only copy). " +
      "You can also put files in the originals folder and ask your AI to index them."));
    if (!rows.length) {
      out.push(empty("No originals yet", "Add an old resume or a performance review to get started."));
      return out;
    }
    var usedBy = {};  // original id -> the items it backs up (item_originals)
    q("SELECT l.original_id, i.id, i.kind, i.title, i.detail FROM item_originals l JOIN items i ON i.id = l.item_id" +
      " WHERE l.status = 'Active' AND i.status <> 'Deprecated' ORDER BY i.id").forEach(function (u) {
      (usedBy[u.original_id] = usedBy[u.original_id] || []).push(u);
    });
    out.push(h("div", { class: "grid" }, rows.map(function (r) {
      var name = r.path.split("/").pop();
      var used = usedBy[r.id] || [];
      return card("originals", r, r.title || name, joinNonEmpty([r.kind, r.doc_date]),
        [h("p", { class: "row-body small muted", style: "overflow-wrap:anywhere" }, r.path),
          used.length ? h("div", { class: "used-by" }, h("p", { class: "row-sub" }, "Backs up these items"),
            h("ul", { class: "used-by-list" }, used.map(function (u) { return h("li", { "data-item": String(u.id) }, joinNonEmpty([u.kind, itemName(u)], ": ")); }))) : null,
          r.extracted === "Text read" || r.extracted === "Not yet" ? h("p", { class: "small" }, "Your AI will read this. Nothing was filled in yet.") : null,
          originalText(r)],
        [h("span", { class: "weight" }, WEIGHT[r.weight] || r.weight), "Facts taken out: ", statusEl(r.extracted),
          EDIT ? h("a", { href: "/original/" + r.id, download: name, "aria-label": "Open " + (r.title || name) }, "Open") : null]);
    })));
    return out;
  };

  // The file's text, one line per row. Each line can become an item or a resume line under the
  // picked job, through /save. No guessing: a line is only trimmed and a leading bullet mark dropped.
  function textLines(text) {
    return String(text || "").split(/\r?\n/).map(function (l) { return l.replace(/^\s*[•·▪◦*–-]\s+/, "").trim(); })
      .filter(function (l) { return l && l !== "(truncated)"; });
  }
  function textJob(o) { return o.id in state.textJob ? state.textJob[o.id] : String(o.position_id || ""); }
  function originalText(o) {
    var lines = textLines(texts[o.id]);
    if (!lines.length) return null;
    var pickId = "text-job-" + o.id, job = textJob(o);
    var box = h("details", { class: "orig-text", open: !!state.textOpen[o.id], ontoggle: function () { state.textOpen[o.id] = box.open; } },
      h("summary", null, "Text read from this file (" + lines.length + (lines.length === 1 ? " line)" : " lines)")),
      EDIT ? h("div", { class: "field" }, h("label", { for: pickId }, "Job for the lines you add"),
        h("select", { id: pickId, onchange: function () { state.textJob[o.id] = this.value; } }, optionsFor("job", [], job).map(function (j) {
          return h("option", { value: j[0], selected: j[0] === job }, j[1]);
        }))) : null,
      h("ol", { class: "text-lines" }, lines.map(function (line, i) {
        var done = state.textAdded[o.id + ":" + i];
        return h("li", null, h("span", null, line), EDIT ? h("span", { class: "text-tools" },
          done ? h("span", { class: "ok-msg small" }, "Added as " + done) : null,
          h("button", { type: "button", class: "btn quiet", "aria-label": "Add as item: " + line,
            onclick: function () { addFromText(o, i, line, false, this); } }, "Add as item"),
          h("button", { type: "button", class: "btn quiet", "aria-label": "Add as resume line: " + line,
            onclick: function () { addFromText(o, i, line, true, this); } }, "Add as resume line")) : null);
      })));
    return box;
  }
  // A resume line needs an item: "Add as resume line" saves the line as both (Original version). The new item is
  // attached to this original (item_originals), so the source is kept.
  function addFromText(o, i, line, asLine, btn) {
    var p = activePerson();
    if (!p) { showError("Add your profile first (Profile tab)"); return; }
    var job = textJob(o), before = updated, what = asLine ? "a resume line" : "an item";
    btn.disabled = true;
    http("POST", "/save", { table: "items", expected_updated_at: null,
      row: { person_id: p.id, kind: "Achievement", detail: line, position_id: job ? parseInt(job, 10) : null, status: "Verified" } })
      .then(function (res) {
        return http("POST", "/save", { table: "item_originals", expected_updated_at: null,
          row: { item_id: res.id, original_id: o.id, status: "Active" } }).then(function () { return res; });
      })
      .then(function (res) {
        return asLine ? http("POST", "/save", { table: "bullet_variants", expected_updated_at: null,
          row: { item_id: res.id, wording: line, track: "Original", status: "Verified" } }) : res;
      })
      .then(function () { return waitForRebuild(before, 25); })
      .then(function () {
        state.textAdded[o.id + ":" + i] = what;
        render();
        announce("Added as " + what);
        var back = stillThere(btn);
        if (back) back.focus();
      })
      .catch(function (err) { btn.disabled = false; showError(plainError(err.message, "Couldn't add")); });
  }
  // "AI output": a file the user's AI wrote (no paste box; it comes back as a file).
  var ORIGINAL_KINDS = ["Resume", "Job description", "Review", "Recommendation", "AI output", "Other"];
  // "What is it?" and Title come first; the file is added when it is chosen or dropped. Both survive re-renders.
  function dropZone() {
    var c = choices("select", ORIGINAL_KINDS, upload.kind, true);
    var kind = h("select", { id: "up-kind", onchange: function () { upload.kind = this.value; } }, c[0].map(function (o) {
      return h("option", { value: o[0], selected: o[0] === c[1] }, o[1]);
    }));
    var title = h("input", { id: "up-title", type: "text", placeholder: "Optional", value: upload.title,
      oninput: function () { upload.title = this.value; } });
    var msg = h("p", { class: "small", id: "up-msg" });
    var picker = h("input", { type: "file", id: "up-file", class: "visually-hidden", style: "position:absolute;left:-9999px",
      onchange: function () { if (this.files.length) send(this.files[0]); this.value = ""; } });
    var zone = h("div", { class: "drop" },
      h("div", { class: "form-row" },
        h("div", { class: "field" }, h("label", { for: "up-kind" }, "What is it?"), kind),
        h("div", { class: "field" }, h("label", { for: "up-title" }, "Title"), title)),
      h("p", null, h("strong", null, "Drop a file here"), " or ",
        h("label", { for: "up-file", class: "btn quiet", style: "display:inline-block" }, "Choose a file"), picker),
      h("p", { class: "small muted" }, "PDF, Word (DOCX), text, PNG or JPEG. The file is copied unedited; its text is read for your AI. " +
        "Something your AI wrote for you? Save it as a file and add it as “AI output”."), msg);
    zone.addEventListener("dragover", function (e) { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", function () { zone.classList.remove("over"); });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("over");
      if (e.dataTransfer.files.length) send(e.dataTransfer.files[0]);
    });
    // The message element is found again each time: a data reload may have redrawn the tab.
    function say(text, cls) {
      var m = document.getElementById("up-msg");
      if (m) { m.className = cls || "small"; m.textContent = text; }
      announce(text);
    }
    function send(file) {
      if (!kind.value) {
        say("Choose what it is first, then add the file again.");
        kind.focus();
        return;
      }
      say("Adding " + file.name + "…");
      var reader = new FileReader();
      reader.onerror = function () { showError("Could not read " + file.name); };
      reader.onload = function () {
        var before = updated;
        http("POST", "/upload", { filename: file.name, kind: kind.value, title: title.value.trim() || null,
          data_b64: String(reader.result).split(",")[1] || "" })
          .then(function (res) {
            upload = { kind: "", title: "" };
            return waitForRebuild(before, 25).then(function () { return res.id; });
          })
          .then(function (id) { say("Added " + file.name + ".", "small ok-msg"); focusItem("originals:" + id); })
          .catch(function (err) { say(""); showError("Not added: " + err.message); });
      };
      reader.readAsDataURL(file);
    }
    return zone;
  }

  VIEWS.how = function () {
    var out = sectionHead("How it works", "Three parts work together. You mostly just review.");
    out.push(h("div", { class: "how", role: "list" },
      h("div", { class: "part", role: "listitem" }, h("span", { class: "num" }, "1"), h("h3", null, "This screen"),
        h("p", null, "Shows everything in your career file. Open it any time, even with no internet. "
          + "With the app running you can fix small things inline and drop in files.")),
      h("div", { class: "part center", role: "listitem" }, h("span", { class: "num" }, "2"), h("h3", null, "Your AI"),
        h("p", null, "Does most of the work. Chat apps connect through MCP (a standard plug for AI tools); "
          + "AIs that run commands use db.py. It reads your originals, fills in facts and writes resume lines.")),
      h("div", { class: "part", role: "listitem" }, h("span", { class: "num" }, "3"), h("h3", null, "The originals folder"),
        h("p", null, "Holds your real files, unedited: old resumes, job descriptions, reviews, letters. "
          + "Browse it like any folder."))));
    out.push(h("div", { class: "prose" },
      h("h3", null, "Who changed what"),
      h("p", null, "Each row shows a small marker: ", h("span", { class: "who user" }, "You"), " for your edits, ",
        h("span", { class: "who ai" }, "AI"), " for your AI, and ", h("span", { class: "who app" }, "App"), " for the starter data."),
      h("h3", null, "Nothing is deleted"),
      h("p", null, "Removed rows are kept in history. Tick “Show removed” at the bottom to see them and restore them."),
      h("h3", null, "The full map"),
      h("p", null, h("a", { href: "#ai", onclick: function (e) { e.preventDefault(); if (go("ai")) focusItem(null); } }, "See the full map in For the AI"),
        ": every table and how they link."),
      h("h3", null, "Getting started"),
      h("p", null, "Give your AI an old resume (drop it in Originals) and ask it to fill in your profile. "
        + "Then work through the Q&A tab together, and add the questions you meet in real interviews.")));
    return out;
  };

  // Map of the database for the For the AI tab. Bands top to bottom; boxes are [x, y, plain label].
  var MAP_W = 1020, MAP_H = 580, BW = 140, BH = 46;
  var LANES = [["You", 0, 250], ["Your story", 250, 390], ["Your documents", 390, 485], ["Behind the scenes", 485, MAP_H]];
  var NODES = {
    people: [435, 36, "Your profile"], links: [175, 126, "Links"], images: [335, 126, "Photo"],
    qa: [535, 126, "Interview Q&A"], education: [695, 126, "Education"], skills: [855, 126, "Skills"],
    skill_links: [855, 196, "Skill uses"],
    employers: [100, 258, "Employers"], positions: [262, 258, "Positions"], items: [435, 258, "Items"],
    bullet_variants: [645, 258, "Resume lines"], tracks: [855, 258, "Versions"],
    item_metrics: [435, 334, "Numbers"], item_originals: [645, 334, "Attachments"],
    originals: [645, 410, "Original files"],
    audit: [15, 510, "Change log"], last_change: [215, 510, "Who changed last"], settings: [375, 510, "Settings"],
    schema_guide: [530, 510, "AI guide"], search_index: [685, 510, "Search index"], resume_json: [840, 510, "Resume per version"]
  };
  var ONE_MANY = "one \u2192 many";
  // [from, to, label, via points, dashed]. Solid = foreign key (to.from_id); dashed = linked by name or built from.
  var EDGES = [
    ["people", "links", ONE_MANY, [[505, 104], [245, 104]]],
    ["people", "images", ONE_MANY, [[505, 104], [405, 104]]], ["people", "qa", ONE_MANY, [[505, 104], [605, 104]]],
    ["people", "education", ONE_MANY, [[505, 104], [765, 104]]], ["people", "skills", ONE_MANY, [[505, 104], [925, 104]]],
    ["people", "items", ONE_MANY], ["people", "employers", null, [[505, 246], [170, 246]]],
    ["people", "originals", ONE_MANY, [[1008, 59], [1008, 433]]],
    ["skills", "skill_links", ONE_MANY],
    ["employers", "positions", null], ["positions", "items", null],
    ["items", "bullet_variants", ONE_MANY], ["items", "item_metrics", ONE_MANY],
    ["items", "item_originals", null, [[610, 320]]], ["originals", "item_originals", ONE_MANY],
    ["positions", "originals", null, [[332, 433]]],
    ["tracks", "bullet_variants", "by name", null, true], ["audit", "last_change", "latest", null, true]
  ];
  var MAP_PLAIN = {
    "employers>positions": "a promotion is a second position under the same employer",
    "positions>items": "an item can sit under a position, or stand alone",
    "items>item_originals": "an item can be backed up by many original files",
    "originals>item_originals": "an original file can back up many items",
    "positions>originals": "an original file can belong to a position",
    "tracks>bullet_variants": "each resume line names its version", "audit>last_change": "the latest change log entry for each row"
  };
  function edgePoint(n, toward) {
    var x = n[0], y = n[1], px = toward[0], py = toward[1];
    if (px >= x && px <= x + BW) return [px, py < y ? y : y + BH];
    if (py >= y && py <= y + BH) return [px < x ? x : x + BW, py];
    var cx = x + BW / 2, cy = y + BH / 2, dx = px - cx, dy = py - cy;
    var k = Math.min(Math.abs(BW / 2 / (dx || 1e-9)), Math.abs(BH / 2 / (dy || 1e-9)));
    return [cx + dx * k, cy + dy * k];
  }
  function mapSvg() {
    var lines = "", texts = "", boxes = "";
    LANES.forEach(function (l, i) {
      lines += '<rect class="' + (i % 2 ? "map-lane alt" : "map-lane") + '" x="0" y="' + l[1] + '" width="' + MAP_W + '" height="' + (l[2] - l[1]) + '"/>';
      texts += '<text class="map-lane-title" x="12" y="' + (l[1] + 22) + '">' + l[0] + "</text>";
    });
    EDGES.forEach(function (e) {
      var a = NODES[e[0]], b = NODES[e[1]], via = e[3] || [];
      var pts = [edgePoint(a, via[0] || [b[0] + BW / 2, b[1] + BH / 2])].concat(via,
        [edgePoint(b, via[via.length - 1] || [a[0] + BW / 2, a[1] + BH / 2])]);
      lines += '<polyline class="map-edge' + (e[4] ? " dashed" : "") + '" points="' + pts.map(function (p) { return p.join(","); }).join(" ") + '" marker-end="url(#map-arrow)"/>';
      if (!e[2]) return;
      var best = 0;
      for (var i = 1; i < pts.length - 1; i++) {
        if (Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) > Math.hypot(pts[best + 1][0] - pts[best][0], pts[best + 1][1] - pts[best][1])) best = i;
      }
      if (via.length === 2 && via[0][1] === 104) best = 2;
      var p = pts[best], q = pts[best + 1], vert = Math.abs(p[0] - q[0]) < 2;
      texts += '<text class="map-label" x="' + ((p[0] + q[0]) / 2 + (vert ? 5 : 0)) + '" y="' + ((p[1] + q[1]) / 2 + (vert ? 4 : -6)) +
        '" text-anchor="' + (vert ? "start" : "middle") + '">' + e[2] + "</text>";
    });
    Object.keys(NODES).forEach(function (id) {
      var n = NODES[id];
      boxes += '<rect class="map-node" x="' + n[0] + '" y="' + n[1] + '" width="' + BW + '" height="' + BH + '" rx="8"/>' +
        '<text class="map-name" x="' + (n[0] + BW / 2) + '" y="' + (n[1] + 20) + '" text-anchor="middle">' + n[2] + "</text>" +
        '<text class="map-table" x="' + (n[0] + BW / 2) + '" y="' + (n[1] + 37) + '" text-anchor="middle">' + id + "</text>";
    });
    return '<svg class="map-svg" viewBox="0 0 ' + MAP_W + " " + MAP_H + '" role="img" aria-labelledby="map-title map-desc">' +
      '<title id="map-title">Map of the Job-o-Matic database</title>' +
      '<desc id="map-desc">Boxes are tables, grouped in four bands: You, Your story, Your documents, Behind the scenes. ' +
      "Arrows point from one row to the many rows that use it. The list after the picture spells out every link.</desc>" +
      '<defs><marker id="map-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
      '<path class="map-arrow" d="M0,0 L10,5 L0,10 z"/></marker></defs>' + lines + boxes + texts + "</svg>";
  }
  function mapView() {
    var list = EDGES.map(function (e) {
      var plain = MAP_PLAIN[e[0] + ">" + e[1]];
      return h("li", null, NODES[e[0]][2] + " (" + e[0] + ") to " + NODES[e[1]][2] + " (" + e[1] + "): " +
        (e[4] ? plain : "one to many, through " + e[1] + "." + (e[0] === "people" ? "person" : e[0].replace(/s$/, "")) + "_id" +
          (plain ? "; " + plain : "")));
    });
    return h("figure", { class: "map", id: "map" },
      h("div", { class: "map-scroll", tabindex: "0", role: "region", "aria-label": "Database map (scrolls sideways on small screens)", innerHTML: mapSvg() }),
      h("p", { class: "map-hint small" }, "Swipe or scroll sideways to see the whole map \u2192"),
      h("figcaption", { class: "small muted" }, "Every table in your Job-o-Matic file and how they link. " +
        "\u201cone \u2192 many\u201d means one row at the start of the arrow has many rows at the end; dashed lines link by name."),
      h("ul", { class: "sr-only" }, list));
  }

  VIEWS.ai = function () {
    var out = sectionHead("For the AI", "The instructions your AI follows. You don't need to read this, but you can.");
    out.push(mapView());
    var text = window.AI_GUIDE;
    out.push(text ? markdown(text) : empty("The AI guide is not in this copy", "It lives in docs/AI_GUIDE.md in the app folder."));
    return out;
  };

  function inline(text) {
    var parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/);
    return parts.map(function (p) {
      if (/^`[^`]+`$/.test(p)) return h("code", null, p.slice(1, -1));
      if (/^\*\*[^*]+\*\*$/.test(p)) return h("strong", null, p.slice(2, -2));
      return p;
    });
  }
  function markdown(text) {
    var box = h("div", { class: "guide" });
    var lines = text.replace(/\r\n/g, "\n").split("\n");
    var para = [], list = null, code = null, table = null;
    function flush() {
      if (para.length) { box.appendChild(h("p", null, inline(para.join(" ")))); para = []; }
      list = null;
    }
    lines.forEach(function (line) {
      if (code !== null) {
        if (/^```/.test(line)) { box.appendChild(h("pre", null, h("code", null, code.join("\n")))); code = null; }
        else code.push(line);
        return;
      }
      if (/^```/.test(line)) { flush(); code = []; return; }
      if (/^\s*\|/.test(line)) {
        if (!table) { flush(); table = h("table"); box.appendChild(table); }
        if (/^[\s|:-]+$/.test(line)) return;
        var cells = line.trim().replace(/^\||\|$/g, "").split("|");
        var head = !table.rows.length;
        table.appendChild(h("tr", null, cells.map(function (c) { return h(head ? "th" : "td", null, inline(c.trim())); })));
        return;
      }
      table = null;
      var m = /^(#{1,4})\s+(.*)$/.exec(line);
      if (m) { flush(); box.appendChild(h("h" + (m[1].length + 2), null, inline(m[2]))); return; }  // under the tab's h2
      m = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(line);
      if (m) {
        if (para.length) { box.appendChild(h("p", null, inline(para.join(" ")))); para = []; }
        if (!list) { list = h("ul"); box.appendChild(list); }
        list.appendChild(h("li", null, inline(m[1])));
        return;
      }
      if (!line.trim()) { flush(); return; }
      if (list && /^\s+/.test(line)) { add(list.lastChild, [" ", inline(line.trim())]); return; }
      list = null;
      para.push(line.trim());
    });
    if (code !== null) box.appendChild(h("pre", null, h("code", null, code.join("\n"))));
    flush();
    return box;
  }

  function dataPanel() {
    var f = dataFolder(), from = window.JOBOMATIC_FOLDER;
    var sep = f && f.win ? "\\" : "/";
    var where = window.JOBOMATIC_DEMO ? "(demo: this made-up person has no folder on your computer)"
      : f ? f.path + sep + "my_data" : from || "the my_data folder inside your Job-o-Matic folder";
    return h("section", { class: "card data-panel", "aria-labelledby": "data-title" },
      h("h3", { id: "data-title" }, "Your data"),
      h("p", null, "Everything lives in one folder on this computer: ", h("code", null, where)),
      h("p", null, "It is backed up automatically each day, after your first change, to ", h("code", null, "my_data/backups"),
        " (the newest 30 are kept)."),
      h("p", { class: "small muted" }, "To back up everything yourself, copy the whole my_data folder somewhere safe."),
      folderActions());
  }
  // Edit mode only: the view-only file has no app to ask.
  function folderActions() {
    if (!EDIT) return null;
    var msg = h("span", { class: "small" });
    function run(path, failed, done) {
      msg.className = "small";
      msg.textContent = "";
      http("POST", path, {}).then(function (res) { msg.className = "small ok-msg"; msg.textContent = done(res); announce(msg.textContent); },
        function (err) { showError(plainError(err.message, failed)); });
    }
    return h("div", { class: "form-actions" },
      h("button", { type: "button", class: "btn", onclick: function () {
        run("/backup", "Couldn't back up", function (res) { return "Backed up to my_data/" + res.path; });
      } }, "Back up now"),
      h("button", { type: "button", class: "btn ghost", onclick: function () {
        run("/open-folder", "Couldn't open the folder", function () { return "Opened in a new window."; });
      } }, "Open my folder"), msg);
  }

  VIEWS.settings = function () {
    var out = sectionHead("Settings", "A few values the app and your AI use.");
    out.push(dataPanel());
    out.push(h("section", { class: "card data-panel", "aria-labelledby": "show-title" }, h("h3", { id: "show-title" }, "On screen"),
      h("label", { class: "toggle" }, h("input", { type: "checkbox", id: "show-ai", checked: window.jomAi(),
        onchange: function () { window.jomAi(this.checked); } }), "Show AI helpers"),
      h("p", { class: "small muted", style: "margin:6px 0 0" }, "The robot buttons that make a prompt for your AI, and “Tailor with your AI”. " +
        "Create Resume still offers both ways. Saved in this browser, like the theme.")));
    out.push(h("p", { class: "section-hint" }, "Your AI uses these two numbers to decide how much room older jobs get on a resume: " +
      "recent jobs get the most lines, the oldest group gets one line or is left off."));
    var settings = q("SELECT * FROM settings ORDER BY id");
    out.push(h("div", { class: "grid" }, settings.map(function (s) {
      return card("settings", s, s.label, null, h("p", { class: "row-body", style: "font-size:20px;font-weight:700" }, s.value),
        [s.note]);
    })));
    var tracks = visible(q("SELECT * FROM tracks ORDER BY sort, name"), "tracks");
    out.push(h("section", { class: "group", style: "margin-top:30px" },
      h("div", { class: "section-head" }, h("h3", null, "Versions"), addButton("tracks", "Add a version", { sort: 100, status: "Active" })),
      h("p", { class: "section-hint" }, "A version is a set of resume lines aimed at one kind of job, e.g. Leadership. Original is the plain one."),
      h("div", { class: "grid" }, newForm("tracks", "New version"), tracks.map(function (t) {
        return card("tracks", t, t.name, null, null, ["Order " + t.sort, statusEl(t.status)]);
      }))));
    return out;
  };

  // ---------- start ----------
  function start() {
    var hash = location.hash.slice(1);
    hash = HASH_ALIAS[hash] || hash;
    if (TABS.some(function (t) { return t[0] === hash; }) || PAGES.indexOf(hash) >= 0) state.tab = hash;
    document.getElementById("how-link").addEventListener("click", function (e) {
      e.preventDefault();
      if (go("how")) focusItem(null);
    });
    var toggle = document.getElementById("show-retired");
    toggle.addEventListener("change", function () { state.showRetired = toggle.checked; render(); });
    var themes = document.querySelectorAll('input[name="theme"]');
    var theme = window.jomTheme();
    Array.prototype.forEach.call(themes, function (r) {
      r.checked = r.value === theme;
      r.addEventListener("change", function () {
        var now = window.jomTheme(r.value);
        Array.prototype.forEach.call(themes, function (x) { x.checked = x.value === now; });
      });
    });
    document.getElementById("create-resume").addEventListener("click", openCreate);
    document.getElementById("tabs-left").addEventListener("click", function () { scrollTabs(-1); });
    document.getElementById("tabs-right").addEventListener("click", function () { scrollTabs(1); });
    document.getElementById("tabs").addEventListener("scroll", tabEdges);
    window.addEventListener("resize", tabEdges);
    if (document.fonts) document.fonts.ready.then(tabEdges);
    NARROW.addEventListener("change", function () { if (db && !state.editing) render(); });
    window.addEventListener("beforeunload", function (e) { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });
    document.getElementById("skip").addEventListener("click", function (e) {
      e.preventDefault();
      document.getElementById("main").focus();
    });
    renderMode();
    var config = window.SQL_WASM_B64 ? { wasmBinary: b64ToBytes(window.SQL_WASM_B64) } : { locateFile: function (f) { return "vendor/" + f; } };
    initSqlJs(config).then(function (lib) {
      SQL = lib;
      if (!EDIT) return useData(window.JOBOMATIC_DB);
      var reload = function () { if (!offline) refresh().catch(function (e) { showError(e.message); }); };
      setInterval(reload, 15000);
      window.addEventListener("focus", reload);
      document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") reload(); });
      setInterval(function () {
        http("GET", "/health").then(function () {
          if (offline) { setOffline(false); refresh(); }
        }, function () { setOffline(true); });
      }, 10000);
      return refresh();
    }).catch(function (e) {
      document.getElementById("main").textContent = "";
      showError("Could not open your career file: " + e.message);
    });
  }
  // tests/test_viewer.py runs the prompt builders in node, with no page: it sets window.JOM_TEST first.
  if (window.JOM_TEST) {
    window.JOM_TEST.load = function (lib, data) { SQL = lib; state.editing = "test"; useData(data); };
    window.JOM_TEST.prompts = { fill: fillPrompt, lines: linesPrompt, qa: qaPrompt, create: createPrompt, sections: SECTIONS };
    window.JOM_TEST.views = VIEWS;
    window.JOM_TEST.draft = { html: draftHtml, words: adWords, marked: marked };
    window.JOM_TEST.forms = { choices: choices, drafts: drafts, leave: leaveForm, edit: function (key) { state.editing = key; },
      extracted: extractedOptions };
    window.JOM_TEST.state = state;
    window.JOM_TEST.tabs = TABS;
    window.JOM_TEST.dates = { record: recordDate, job: span, warning: dateWarning };
    window.JOM_TEST.remove = { question: removeQuestion, live: liveStatus };
    window.JOM_TEST.neverInvent = NEVER_INVENT;
    return;
  }
  start();
})();
