import calendar
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from string import Template

from jobomatic.originals import _free_name

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
TEMPLATES = ("executive", "navy_bar", "two_column", "structured", "genz")


def _month(value):
    if not value:
        return ""
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", value)
    return f"{calendar.month_abbr[int(m[2])]} {m[1]}" if m else value


def _e(value):
    return escape(value or "")


def _contact(person, links):
    parts = [person["location"], person["phone"], person["email"]]
    html = [f"<span>{_e(p)}</span>" for p in parts if p]
    for link in links:
        html.append(f'<span><a href="{_e(link["url"])}">{_e(link["label"] or link["url"])}</a></span>')
    return "\n".join(html)


def _head(title, when, sub):
    return (
        f'<div class="jh"><span class="jt">{_e(title)}</span><span class="jd">{_e(when)}</span></div>'
        f'<div class="jo">{_e(sub)}</div>'
    )


def _position(pos):
    when = f"{_month(pos['start_date'])} - {_month(pos['end_date']) or 'Present'}"
    bullets = "".join(f"<li>{_e(line['wording'])}</li>" for line in pos["lines"])
    ul = f"<ul>{bullets}</ul>" if bullets else ""
    dept = f'<div class="jo">{_e(pos["department"])}</div>' if pos["department"] else ""
    return (f'<div class="pos"><div class="jh"><span class="jt">{_e(pos["title"])}</span>'
            f'<span class="jd">{_e(when)}</span></div>{dept}{ul}</div>')


def _employer(emp):
    loc = f'<div class="jo">{_e(emp["location"])}</div>' if emp["location"] else ""
    return (f'<div class="job"><div class="jh"><span class="jt">{_e(emp["name"])}</span></div>{loc}'
            f'{"".join(_position(p) for p in emp["positions"])}</div>')


def _education(row):
    sub = ", ".join(p for p in (row["institution"], row["location"]) if p)
    return f'<div class="edu">{_head(row["name"], row["year"], sub)}</div>'


def _record(row):
    dates = " - ".join(dict.fromkeys(_month(d) for d in (row["start_date"], row["end_date"]) if d))
    sub = ", ".join(p for p in (row["organization"], row["from_whom"]) if p)
    desc = f"<p>{_e(row['detail'])}</p>" if row["detail"] else ""
    return f'<div class="rec">{_head(row["title"], dates, sub)}{desc}</div>'


def _section(title, body):
    return f"<section><h2>{title}</h2>{body}</section>" if body else ""


def _skills_grouped(skills):
    groups = {}
    for s in skills:
        groups.setdefault(s["category"] or "Other", []).append(_e(s["name"]))
    return "".join(f"<p><b>{_e(cat)}</b><span>{', '.join(names)}</span></p>" for cat, names in groups.items())


def resume_data(conn, track="Original"):
    """The resume_json document for a track, as a dict."""
    if conn.execute("SELECT 1 FROM tracks WHERE name = ?", (track,)).fetchone() is None:
        names = [r[0] for r in conn.execute("SELECT name FROM tracks ORDER BY sort, name")]
        raise ValueError(f"Unknown version (track) {track!r}; use one of {', '.join(names)}")
    row = conn.execute("SELECT resume FROM resume_json WHERE track = ?", (track,)).fetchone()
    if row is None:
        raise ValueError("No Active person")
    return json.loads(row[0])


def build_resume(conn, data_dir, template, track="Original"):
    """Writes resumes/<date>_<template>_<track>_<time>.html (never over an earlier file) and returns its path."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; use one of {', '.join(TEMPLATES)}")
    doc = resume_data(conn, track)
    person = doc["person"]

    education = [r for r in doc["education"] if r["kind"] != "Certification"]
    certifications = [r for r in doc["education"] if r["kind"] == "Certification"]
    by_kind = {kind: [r for r in doc["items"] if r["kind"] == kind] for kind in ("Award", "Project")}
    tags = "".join(f"<span>{_e(s['name'])}</span>" for s in doc["skills"])
    summary = f'<p class="sum">{_e(person["summary"])}</p>' if person["summary"] else ""

    html = Template((TEMPLATES_DIR / f"resume_{template}_v1.html").read_text(encoding="utf-8")).substitute(
        name=_e(person["full_name"] or person["name"]),
        headline=_e(person["headline"]),
        contact_html=_contact(person, doc["links"]),
        summary_section=_section("Summary", summary),
        experience_section=_section("Experience", "".join(_employer(m) for m in doc["employers"])),
        skills_section=_section("Skills", f'<div class="sk">{_skills_grouped(doc["skills"])}</div>' if doc["skills"] else ""),
        skills_tags_section=_section("Skills", f'<div class="tags">{tags}</div>' if tags else ""),
        education_section=_section("Education", "".join(_education(r) for r in education)),
        certifications_section=_section("Certifications", "".join(_education(r) for r in certifications)),
        awards_section=_section("Awards", "".join(_record(r) for r in by_kind["Award"])),
        projects_section=_section("Projects", "".join(_record(r) for r in by_kind["Project"])),
    )
    safe_track = re.sub(r"[^A-Za-z0-9_-]+", "_", track)
    folder = Path(data_dir) / "resumes"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    out = _free_name(folder, f"{now:%Y-%m-%d}_{template}_{safe_track}_{now:%H%M%S}.html")
    out.write_text(html, encoding="utf-8")
    return out
