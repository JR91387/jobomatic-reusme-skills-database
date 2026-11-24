/* Fills a templates/resume_*_v1.html file from a resume_json document. Mirrors src/jobomatic/resume.py
   (tests/test_resume_parity.py keeps them in step). Plain script: window.JOM.renderResume in the page, globalThis in Node. */
(function (root) {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#x27;" };

  function e(v) { return v === null || v === undefined ? "" : String(v).replace(/[&<>"']/g, function (c) { return ESC[c]; }); }

  function month(v) {
    if (!v) return "";
    var m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(v);
    return m ? MONTHS[parseInt(m[2], 10) - 1] + " " + m[1] : v;
  }

  // Phone for display. The server keeps E.164 (+15551234567); this only changes how it looks. Mirrored in
  // src/jobomatic/resume.py (_phone). style: paren | dash | dot | intl (the page's Phone style setting).
  var PHONE_STYLES = ["paren", "dash", "dot", "intl"];
  var CC2 = /^(20|27|3[0-46-9]|4[013-9]|5[1-8]|6[0-6]|8[1246]|9[0-58])/;
  function formatPhone(value, style) {
    var raw = value === null || value === undefined ? "" : String(value).trim();
    var digits = raw.replace(/\D/g, "");
    var plus = raw.charAt(0) === "+";
    if (!plus && digits.length === 11 && digits.charAt(0) === "1") digits = digits.slice(1);
    if (!plus && digits.length === 10) { plus = true; digits = "1" + digits; }
    if (!plus || digits.length < 8 || digits.length > 15) return raw;
    var m = /^1(\d{3})(\d{3})(\d{4})$/.exec(digits);
    if (m) {
      if (style === "dash") return m[1] + "-" + m[2] + "-" + m[3];
      if (style === "dot") return m[1] + "." + m[2] + "." + m[3];
      if (style === "intl") return "+1 " + m[1] + " " + m[2] + " " + m[3];
      return "(" + m[1] + ") " + m[2] + "-" + m[3];
    }
    var cc = /^[17]/.test(digits) ? 1 : CC2.test(digits) ? 2 : 3;
    var national = digits.slice(cc), groups = [];
    while (national.length > 4) { groups.unshift(national.slice(-4)); national = national.slice(0, -4); }
    groups.unshift(national);
    return "+" + digits.slice(0, cc) + " " + groups.join(" ");
  }

  function contact(person, links) {
    var phone = formatPhone(person.phone, typeof root.jomPhoneStyle === "function" ? root.jomPhoneStyle() : "paren");
    var html = [person.location, phone, person.email].filter(Boolean).map(function (p) { return "<span>" + e(p) + "</span>"; });
    links.forEach(function (l) { html.push("<span><a href=\"" + e(l.url) + "\">" + e(l.label || l.url) + "</a></span>"); });
    return html.join("\n");
  }

  function head(title, when, sub) {
    return '<div class="jh"><span class="jt">' + e(title) + '</span><span class="jd">' + e(when) + "</span></div>" +
      '<div class="jo">' + e(sub) + "</div>";
  }

  function position(p) {
    var when = month(p.start_date) + " - " + (month(p.end_date) || "Present");
    var bullets = p.lines.map(function (l) { return "<li>" + e(l.wording) + "</li>"; }).join("");
    var dept = p.department ? '<div class="jo">' + e(p.department) + "</div>" : "";
    return '<div class="pos"><div class="jh"><span class="jt">' + e(p.title) + '</span><span class="jd">' + e(when) + "</span></div>" +
      dept + (bullets ? "<ul>" + bullets + "</ul>" : "") + "</div>";
  }

  function employer(m) {
    var loc = m.location ? '<div class="jo">' + e(m.location) + "</div>" : "";
    return '<div class="job"><div class="jh"><span class="jt">' + e(m.name) + "</span></div>" + loc +
      m.positions.map(position).join("") + "</div>";
  }

  function education(r) {
    return '<div class="edu">' + head(r.name, r.year, [r.institution, r.location].filter(Boolean).join(", ")) + "</div>";
  }

  function record(r) {
    var dates = [];
    [r.start_date, r.end_date].filter(Boolean).map(month).forEach(function (d) { if (dates.indexOf(d) < 0) dates.push(d); });
    var desc = r.detail ? "<p>" + e(r.detail) + "</p>" : "";
    return '<div class="rec">' + head(r.title, dates.join(" - "), [r.organization, r.from_whom].filter(Boolean).join(", ")) + desc + "</div>";
  }

  function section(title, body) { return body ? "<section><h2>" + title + "</h2>" + body + "</section>" : ""; }

  function skillsGrouped(skills) {
    var groups = new Map();
    skills.forEach(function (s) {
      var cat = s.category || "Other";
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat).push(e(s.name));
    });
    var out = "";
    groups.forEach(function (names, cat) { out += "<p><b>" + e(cat) + "</b><span>" + names.join(", ") + "</span></p>"; });
    return out;
  }

  function renderResume(doc, template, templates) {
    var source = templates && templates[template];
    if (!source) throw new Error("Unknown resume style " + JSON.stringify(template));
    var person = doc.person;
    var edu = doc.education.filter(function (r) { return r.kind !== "Certification"; });
    var certs = doc.education.filter(function (r) { return r.kind === "Certification"; });
    function kind(k) { return doc.items.filter(function (r) { return r.kind === k; }); }
    var tags = doc.skills.map(function (s) { return "<span>" + e(s.name) + "</span>"; }).join("");
    var values = {
      name: e(person.full_name || person.name),
      headline: e(person.headline),
      contact_html: contact(person, doc.links),
      summary_section: section("Summary", person.summary ? '<p class="sum">' + e(person.summary) + "</p>" : ""),
      experience_section: section("Experience", doc.employers.map(employer).join("")),
      skills_section: section("Skills", doc.skills.length ? '<div class="sk">' + skillsGrouped(doc.skills) + "</div>" : ""),
      skills_tags_section: section("Skills", tags ? '<div class="tags">' + tags + "</div>" : ""),
      education_section: section("Education", edu.map(education).join("")),
      certifications_section: section("Certifications", certs.map(education).join("")),
      awards_section: section("Awards", kind("Award").map(record).join("")),
      projects_section: section("Projects", kind("Project").map(record).join(""))
    };
    return source.replace(/\$(?:\$|\{([_a-z][_a-z0-9]*)\}|([_a-z][_a-z0-9]*))/gi, function (m, braced, plain) {
      if (m === "$$") return "$";
      var key = braced || plain;
      if (!(key in values)) throw new Error("Resume style " + template + " has an unknown field $" + key);
      return values[key];
    });
  }

  root.JOM = root.JOM || {};
  root.JOM.renderResume = renderResume;
  root.JOM.formatPhone = formatPhone;
  root.JOM.PHONE_STYLES = PHONE_STYLES;
})(typeof window !== "undefined" ? window : globalThis);
