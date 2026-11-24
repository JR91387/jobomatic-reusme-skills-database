"""Update check: is there a newer Job-o-Matic, and how does this install get it?

At most one request a day, only when the "Check for updates" setting is on (the default).
The request carries a User-Agent and nothing else: no data, no IDs. pip / uv / pipx installs
ask PyPI; zips ask GitHub Releases. The answer is cached in <data_dir>/update_check.json."""
import json
import os
import re
import site
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from jobomatic import paths
from jobomatic.version import DIST_NAME, get_version

PYPI_URL = f"https://pypi.org/pypi/{DIST_NAME}/json"
GITHUB_API = "https://api.github.com/repos/JR91387/jobomatic-reusme-skills-database/releases/latest"
DOWNLOAD_URL = "https://github.com/JR91387/jobomatic-reusme-skills-database/releases/latest"
TIMEOUT = 3
CHECK_EVERY = 24 * 3600
UPDATE_TIMEOUT = 300
SETTINGS = "settings.json"
CACHE = "update_check.json"
DEFAULTS = {"check_updates": True}
COMMANDS = {
    "uv-tool": f"uv tool install --upgrade {DIST_NAME}",
    "pipx": f"pipx upgrade {DIST_NAME}",
    "repo": "git pull",
}


def install_type():
    """'pip' | 'uv-tool' | 'pipx' | 'zip' | 'repo'."""
    if not paths.installed():
        bundle = paths.PKG.parents[2]
        if paths.PKG.parents[1].name == "app" and (bundle / "python").is_dir():
            return "zip"
        return "repo"
    prefix = Path(sys.prefix).resolve().as_posix().lower()
    for env, kind in (("UV_TOOL_DIR", "uv-tool"), ("PIPX_HOME", "pipx")):
        root = os.environ.get(env)
        if root and prefix.startswith(Path(root).expanduser().resolve().as_posix().lower() + "/"):
            return kind
    if "/uv/tools/" in prefix or "/uv/archive-" in prefix or "/cache/uv/" in prefix:
        return "uv-tool"
    if "/pipx/venvs/" in prefix:
        return "pipx"
    return "pip"


# ---------- settings ----------

def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_settings(data_dir):
    return {**DEFAULTS, **_read_json(Path(data_dir) / SETTINGS)}


def save_settings(data_dir, **changes):
    current = _read_json(Path(data_dir) / SETTINGS)
    current.update(changes)
    (Path(data_dir) / SETTINGS).write_text(json.dumps(current, indent=2), encoding="utf-8")
    return {**DEFAULTS, **current}


# ---------- versions ----------

def version_key(v):
    """(1, 2, 0) from '1.2.0', 'v1.2', '1.2.0rc1'. A suffix is ignored; () when there are no digits."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(v or ""))
    if not m:
        return ()
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_prerelease(v):
    return bool(re.search(r"\d(a|b|rc|dev|alpha|beta|pre)", str(v or ""), re.IGNORECASE))


def is_newer(latest, current):
    if not latest or not current or is_prerelease(latest):
        return False
    lk, ck = version_key(latest), version_key(current)
    return bool(lk) and bool(ck) and lk > ck


# ---------- the check ----------

def _fetch(kind, current):
    """(latest version, download url) from PyPI or GitHub. Raises on any network or format problem."""
    url = GITHUB_API if kind == "zip" else PYPI_URL
    req = Request(url, headers={"User-Agent": f"job-o-matic/{current or 'unknown'}"})
    with urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read(2 * 1024 * 1024))
    if kind == "zip":
        return str(data["tag_name"]).lstrip("vV"), data.get("html_url") or DOWNLOAD_URL
    return str(data["info"]["version"]), DOWNLOAD_URL


def _pip_command():
    user = ["--user"] if _user_site_install() else []
    return [sys.executable, "-m", "pip", "install", "--upgrade", *user, DIST_NAME]


def _user_site_install():
    try:
        return paths.PKG.is_relative_to(Path(site.getusersitepackages()).resolve())
    except (AttributeError, ValueError, OSError):
        return False


def action_for(kind):
    """(action, command) the page offers: a button (pip), a command to copy, or a download link (zip)."""
    if kind == "pip":
        return "button", " ".join(f'"{a}"' if " " in a else a for a in _pip_command())
    if kind == "zip":
        return "download", ""
    return "command", COMMANDS.get(kind, "")


def check(data_dir, force=False, now=None):
    """What /update-status answers. Never raises; offline just means latest is None."""
    now = time.time() if now is None else now
    kind, current = install_type(), get_version()
    action, command = action_for(kind)
    enabled = bool(load_settings(data_dir).get("check_updates", True))
    out = {"current": current, "latest": None, "newer": False, "install_type": kind, "action": action,
           "command": command, "url": DOWNLOAD_URL, "enabled": enabled}
    if not enabled:
        return out
    cache_file = Path(data_dir) / CACHE
    cache = _read_json(cache_file)
    fresh = (not force and cache.get("install_type") == kind and cache.get("current") == current
             and 0 <= now - float(cache.get("checked", 0) or 0) < CHECK_EVERY)
    if not fresh:
        try:
            latest, url = _fetch(kind, current)
            cache = {"checked": now, "install_type": kind, "current": current, "latest": latest, "url": url}
        except Exception as e:  # noqa: BLE001 - offline, blocked, rate-limited: all mean "no answer today"
            cache = {"checked": now, "install_type": kind, "current": current, "latest": None,
                     "error": f"{type(e).__name__}: {e}"[:200]}
        try:
            cache_file.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    out["latest"] = cache.get("latest")
    out["url"] = cache.get("url") or DOWNLOAD_URL
    out["newer"] = is_newer(out["latest"], current)
    if cache.get("error"):
        out["error"] = cache["error"]
    return out


def run_update():
    """pip installs only: upgrade in place. The running app keeps the old code until restarted."""
    kind = install_type()
    if kind != "pip":
        _, command = action_for(kind)
        return {"ok": False, "install_type": kind, "command": command,
                "message": "This install updates with a command or a download, not the button."}
    cmd = _pip_command()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=UPDATE_TIMEOUT, check=False)
        output, ok = (r.stdout + r.stderr), r.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        output, ok = f"{type(e).__name__}: {e}", False
    tail = "\n".join(output.strip().splitlines()[-15:])
    message = ("Updated. Restart Job-o-Matic to finish: Quit, then open it again." if ok
               else "The update did not finish. The output below says why.")
    return {"ok": ok, "install_type": kind, "command": " ".join(cmd), "output": tail, "message": message}
