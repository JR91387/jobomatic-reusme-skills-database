/* Job-o-Matic update notice and the "Check for updates" setting. App mode only (the helper serves the page);
   the view-only file leaves this script out. The check itself runs in the helper: once a day at most. */
(function () {
  "use strict";
  if (typeof window.HELPER_TOKEN !== "string" || !window.fetch) return;

  var bar = document.getElementById("update-bar");
  var box = document.getElementById("check-updates-box");
  var toggle = document.getElementById("check-updates");

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-JobOMatic": window.HELPER_TOKEN },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || "The app answered " + r.status);
        return j;
      });
    });
  }

  function el(tag, text, attrs) {
    var n = document.createElement(tag);
    if (text) n.textContent = text;
    for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
    return n;
  }

  function setShown(on) {  // inline display, so no stylesheet rule can override the hidden attribute
    bar.hidden = !on;
    bar.style.display = on ? "flex" : "none";
  }

  function styleBar() {
    var s = bar.style;
    s.maxWidth = "1120px";
    s.margin = "8px auto";
    s.padding = "8px 14px";
    s.flexWrap = "wrap";
    s.alignItems = "center";
    s.gap = "8px 14px";
    s.border = "1px solid var(--border)";
    s.borderRadius = "var(--radius)";
    s.background = "var(--surface-raised)";
    s.color = "var(--text)";
    s.fontSize = "14px";
  }

  function copyButton(text) {
    var b = el("button", "Copy", { type: "button" });
    b.addEventListener("click", function () {
      var done = function () { b.textContent = "Copied"; };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { b.textContent = "Select and copy"; });
    });
    return b;
  }

  function safeLink(url) {  // the helper only passes GitHub links; never follow any other scheme
    return typeof url === "string" && url.indexOf("https://") === 0 ? url : null;
  }

  function note(text) {  // one line after a restart: "Updated to X…" or "put the previous version back"
    bar.textContent = "";
    styleBar();
    bar.appendChild(el("span", text));
    var close = el("button", "OK", { type: "button" });
    close.addEventListener("click", function () { setShown(false); });
    bar.appendChild(close);
    setShown(true);
  }

  function waitForRestart(oldBoot, out) {  // the helper restarts; reload once a new one answers /health
    var tries = 0;
    function poll() {
      tries += 1;
      fetch("/health", { cache: "no-store" }).then(function (r) {
        var boot = r.headers.get("X-JobOMatic-Boot");
        if (r.ok && boot && boot !== oldBoot) location.reload();
        else later();
      }, later);
    }
    function later() {
      if (tries < 180) setTimeout(poll, 1000);
      else out.textContent = "Job-o-Matic did not come back. Open it again from your app menu.";
    }
    setTimeout(poll, 1000);
  }

  function show(st) {
    bar.textContent = "";
    styleBar();
    bar.appendChild(el("strong", "Job-o-Matic " + st.latest + " is available"));
    bar.appendChild(el("span", "(you have " + (st.current || "an older version") + ")"));
    if (st.action === "button") {
      var btn = el("button", "Update now", { type: "button" });
      var out = el("span", "");
      btn.addEventListener("click", function () {
        btn.disabled = true;
        out.textContent = "Updating… this can take a minute.";
        post("/update", {}).then(function (r) {
          out.textContent = r.message || (r.ok ? "Updated." : "The update did not finish.");
          if (r.output) out.title = r.output;
          if (r.ok && r.restart) return waitForRestart(r.boot, out);
          if (!r.ok) btn.disabled = false;
          if (!r.ok && r.command) {
            bar.insertBefore(el("code", r.command), out.nextSibling);
            bar.insertBefore(copyButton(r.command), out.nextSibling.nextSibling);
          }
        }, function (e) {
          out.textContent = "The update did not finish: " + e.message;
          btn.disabled = false;
        });
      });
      bar.appendChild(btn);
      bar.appendChild(out);
    } else if (st.action === "command" && st.command) {
      bar.appendChild(el("span", "To update, run:"));
      bar.appendChild(el("code", st.command));
      bar.appendChild(copyButton(st.command));
    } else if (safeLink(st.url)) {
      bar.appendChild(el("a", "Download it", { href: safeLink(st.url), target: "_blank", rel: "noopener" }));
    }
    var close = el("button", "Not now", { type: "button" });
    close.addEventListener("click", function () { setShown(false); });
    bar.appendChild(close);
    setShown(true);
  }

  function load() {
    return fetch("/update-status").then(function (r) { return r.ok ? r.json() : null; }).then(function (st) {
      if (!st) return;
      toggle.checked = !!st.enabled;
      box.hidden = false;
      if ((st.updated_to || st.update_failed) && st.message) note(st.message);
      else if (st.enabled && st.newer && st.latest) show(st);
      else setShown(false);
    }, function () { /* offline or the app stopped: say nothing */ });
  }

  toggle.addEventListener("change", function () {
    var want = toggle.checked;
    post("/update-settings", { check_updates: want }).then(function () {
      if (want) load();
      else setShown(false);
    }, function () { toggle.checked = !want; });
  });

  load();
})();
