"""Update check and the "Update now" button.

Check: at most one request a day, only when the "Check for updates" setting is on (the default).
The request carries a User-Agent and nothing else: no data, no IDs. pip / uv / pipx installs ask
PyPI; zips ask GitHub Releases. The answer is cached in <data_dir>/update_check.json.

Update (run_update), always after a checked backup of the database into <data_dir>/backups/:
- pip, uv tool, pipx: the install's own upgrade command (list args, no shell, 300 s limit). Then
  the helper restarts itself (helper.restart) and the page reconnects through /health.
- zip: download this platform's release zip and SHA256SUMS, check the hash (a mismatch changes
  nothing), unpack app/ and python/ into Job-o-Matic/.update/ and write .update/READY. The helper
  then quits and runs the launcher, which swaps the new folders in before Python starts
  (app -> app.prev, python -> python.prev) and writes .update/TRIAL. The new helper deletes
  .update/ once it is listening (mark_started); if it exits with an error first, the launcher
  puts the .prev folders back and leaves .update/FAILED. my_data/ is never touched.

Test-only: JOBOMATIC_UPDATE_PYPI_URL and JOBOMATIC_UPDATE_RELEASES_URL replace the PyPI and GitHub
addresses for the update-path tests. They are not a user setting."""
import hashlib
import json
import os
import platform
import re
import shutil
import site
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from jobomatic import paths, store
from jobomatic.version import DIST_NAME, get_version

PYPI_URL = f"https://pypi.org/pypi/{DIST_NAME}/json"
GITHUB_API = "https://api.github.com/repos/JR91387/jobomatic-reusme-skills-database/releases/latest"
DOWNLOAD_URL = "https://github.com/JR91387/jobomatic-reusme-skills-database/releases/latest"
TRUSTED = "https://github.com/"
PYPI_ENV = "JOBOMATIC_UPDATE_PYPI_URL"  # test-only
RELEASES_ENV = "JOBOMATIC_UPDATE_RELEASES_URL"  # test-only
TIMEOUT = 3
DOWNLOAD_TIMEOUT = 60
MAX_DOWNLOAD = 500 * 1024 * 1024
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
CHECK_EVERY = 24 * 3600
UPDATE_TIMEOUT = 300
PENDING_FOR = 3600
SETTINGS = "settings.json"
CACHE = "update_check.json"
PENDING = "update_pending.json"
STAGE = ".update"  # beside app/ in a zip
DEFAULTS = {"check_updates": True}
UPDATE_COMMANDS = {  # kind -> (program, arguments); pip runs this Python's own pip
    "uv-tool": ("uv", ["tool", "install", "--upgrade", DIST_NAME]),
    "pipx": ("pipx", ["upgrade", DIST_NAME]),
}
COMMANDS = {kind: " ".join([prog, *args]) for kind, (prog, args) in UPDATE_COMMANDS.items()} | {"repo": "git pull"}
LAUNCHERS = {
    "windows-x64": "Job-o-Matic.bat",
    "macos-arm64": "Job-o-Matic.command",
    "macos-x64": "Job-o-Matic.command",
    "linux-x64": "job-o-matic.sh",
}
RESTART_NOTE = "Restart your AI app so it picks up the new MCP server."


class UpdateError(Exception):
    """A plain-language reason the update stopped; nothing was changed."""


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


def bundle_root():
    """The Job-o-Matic/ folder of a zip (app/, python/, my_data/ and the launcher)."""
    return paths.PKG.parents[2]


def platform_name():
    if sys.platform == "win32":
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if platform.machine().lower() in ("arm64", "aarch64") else "macos-x64"
    return "linux-x64"


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
    """1.3.0rc1, 1.3.0-rc1, 1.3.0.beta2, 1.3.1.dev0 and the like."""
    return bool(re.search(r"\d[.\-_]?(a|b|c|rc|dev|alpha|beta|pre|preview)\d*\b", str(v or ""), re.IGNORECASE))


def is_newer(latest, current):
    if not latest or not current or is_prerelease(latest):
        return False
    lk, ck = version_key(latest), version_key(current)
    return bool(lk) and bool(ck) and lk > ck


# ---------- addresses ----------

def pypi_url():
    return os.environ.get(PYPI_ENV) or PYPI_URL


def releases_url():
    return os.environ.get(RELEASES_ENV) or GITHUB_API


def trusted(url):
    """Only https://github.com/ links are followed or shown (or, in tests, the override's own host)."""
    url = str(url or "")
    if url.startswith(TRUSTED):
        return True
    override = os.environ.get(RELEASES_ENV)
    if not override:
        return False
    o, u = urlsplit(override), urlsplit(url)
    return u.scheme in ("http", "https") and (u.scheme, u.netloc) == (o.scheme, o.netloc)


def safe_url(url):
    return url if isinstance(url, str) and trusted(url) else DOWNLOAD_URL


def _get(url, current, timeout=TIMEOUT):
    return urlopen(Request(url, headers={"User-Agent": f"job-o-matic/{current or 'unknown'}"}), timeout=timeout)


def _get_json(url, current):
    with _get(url, current) as resp:
        data = json.loads(resp.read(2 * 1024 * 1024))
    if not isinstance(data, dict):
        raise TypeError("the answer is not a JSON object")
    return data


# ---------- the check ----------

def _fetch(kind, current):
    """(latest version, download url) from PyPI or GitHub. Raises on any network or format problem."""
    if kind == "zip":
        data = _get_json(releases_url(), current)
        return str(data["tag_name"]).lstrip("vV"), safe_url(data.get("html_url"))
    data = _get_json(pypi_url(), current)
    return str(data["info"]["version"]), DOWNLOAD_URL


def _pip_command():
    user = ["--user"] if _user_site_install() else []
    return [sys.executable, "-m", "pip", "install", "--upgrade", *user, DIST_NAME]


def _user_site_install():
    try:
        return paths.PKG.is_relative_to(Path(site.getusersitepackages()).resolve())
    except (AttributeError, ValueError, OSError):
        return False


def _find_program(name):
    """uv / pipx on PATH, or in the usual install folders (an app-menu start can have a short PATH)."""
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if sys.platform == "win32" else "")
    for folder in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        if (folder / exe).is_file():
            return str(folder / exe)
    return None


def update_command(kind):
    """The argv run_update runs for pip / uv-tool / pipx; None when the program can't be found."""
    if kind == "pip":
        return _pip_command()
    if kind not in UPDATE_COMMANDS:
        return None
    prog, args = UPDATE_COMMANDS[kind]
    found = _find_program(prog)
    return [found, *args] if found else None


def action_for(kind):
    """(action, command) the page offers: the button (pip, uv, pipx, zip) or a command to copy (repo)."""
    if kind == "pip":
        return "button", " ".join(f'"{a}"' if " " in a else a for a in _pip_command())
    if kind == "zip":
        return "button", ""
    if kind in UPDATE_COMMANDS:
        return "button", COMMANDS[kind]
    return "command", COMMANDS.get(kind, "")


def _cache_fresh(cache, kind, current, now):
    if cache.get("install_type") != kind or cache.get("current") != current:
        return False
    try:
        age = now - float(cache.get("checked") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age < CHECK_EVERY


def check(data_dir, force=False, now=None):
    """What /update-status answers. Never raises; offline just means latest is None."""
    try:
        return _check(data_dir, force, now)
    except Exception as e:  # noqa: BLE001 - the page must always get an answer
        return {"current": get_version(), "latest": None, "newer": False, "install_type": "unknown",
                "action": "command", "command": "", "url": DOWNLOAD_URL, "enabled": False,
                "error": f"{type(e).__name__}: {e}"[:200]}


def _check(data_dir, force, now):
    now = time.time() if now is None else now
    kind, current = install_type(), get_version()
    action, command = action_for(kind)
    enabled = bool(load_settings(data_dir).get("check_updates", True))
    out = {"current": current, "latest": None, "newer": False, "install_type": kind, "action": action,
           "command": command, "url": DOWNLOAD_URL, "enabled": enabled, **notice(data_dir, kind, current, now)}
    if not enabled:
        return out
    cache_file = Path(data_dir) / CACHE
    cache = _read_json(cache_file)
    if force or not _cache_fresh(cache, kind, current, now):
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
    latest = cache.get("latest")
    out["latest"] = latest if isinstance(latest, str) else None
    out["url"] = safe_url(cache.get("url"))
    out["newer"] = is_newer(out["latest"], current)
    if cache.get("error"):
        out["error"] = str(cache["error"])[:200]
    return out


# ---------- after an update ----------

def notice(data_dir, kind=None, current=None, now=None):
    """Once, after a restart: {"updated_to": version} or {"update_failed": True}; else {}."""
    kind = kind or install_type()
    current = current or get_version()
    now = time.time() if now is None else now
    pending_file = Path(data_dir) / PENDING
    if kind == "zip" and (bundle_root() / STAGE / "FAILED").exists():
        shutil.rmtree(bundle_root() / STAGE, ignore_errors=True)
        pending_file.unlink(missing_ok=True)
        return {"update_failed": True, "message": "The new version did not start, so the previous version "
                                                  "was put back. Your data was not changed."}
    pending = _read_json(pending_file)
    if not pending:
        return {}
    if current and pending.get("from") != current:
        pending_file.unlink(missing_ok=True)
        return {"updated_to": current, "message": f"Updated to {current}. {RESTART_NOTE}"}
    try:
        stale = now - float(pending.get("at") or 0) > PENDING_FOR
    except (TypeError, ValueError):
        stale = True
    if stale:
        pending_file.unlink(missing_ok=True)
    return {}


def mark_started():
    """The helper is listening: keep a zip update on trial (the launcher waits for .update/ to go)."""
    if install_type() != "zip":
        return
    stage_dir = bundle_root() / STAGE
    if (stage_dir / "TRIAL").exists():
        shutil.rmtree(stage_dir, ignore_errors=True)


def relaunch_command():
    """How the helper starts the zip's launcher after staging an update; None without one."""
    launcher = bundle_root() / LAUNCHERS[platform_name()]
    if not launcher.is_file():
        return None
    if sys.platform == "win32":
        return [os.environ.get("COMSPEC") or "cmd.exe", "/c", str(launcher)]
    return ["/bin/sh", str(launcher)]


# ---------- the update ----------

def backup(db_path):
    """A checked copy in <data_dir>/backups/, named so it sorts with the daily ones."""
    db_path = Path(db_path)
    folder = db_path.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"jobomatic_{datetime.now().astimezone():%Y-%m-%d_%H%M%S}_pre-update.db"
    store.checked_copy(db_path, target)
    return target


def run_update(db_path):
    """Back up, then update this install. On success the reply carries restart: 'exec' or 'launcher'."""
    kind, current = install_type(), get_version()
    base = {"install_type": kind, "current": current}
    if kind not in ("pip", "zip", *UPDATE_COMMANDS):
        return {**base, "ok": False, "command": COMMANDS.get(kind, ""),
                "message": "This copy updates with a command, not the button."}
    try:
        saved = backup(db_path)
    except (OSError, sqlite3.Error) as e:
        return {**base, "ok": False, "message": f"Nothing was changed: the backup before updating failed ({e})."}
    base["backup"] = saved.name
    result = _update_zip(current) if kind == "zip" else _update_package(kind)
    if result.get("ok"):
        try:
            (Path(db_path).parent / PENDING).write_text(json.dumps({"from": current, "at": time.time()}),
                                                        encoding="utf-8")
        except OSError:
            pass
    return {**base, **result}


def _update_package(kind):
    cmd = update_command(kind)
    if not cmd:
        prog = UPDATE_COMMANDS[kind][0]
        return {"ok": False, "command": COMMANDS[kind],
                "message": f"Couldn't find {prog}. Run this command yourself, then open Job-o-Matic again:"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=UPDATE_TIMEOUT, check=False,
                           stdin=subprocess.DEVNULL)
        output, ok = (r.stdout + r.stderr), r.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        output, ok = f"{type(e).__name__}: {e}", False
    tail = "\n".join(output.strip().splitlines()[-15:])
    if not ok:
        return {"ok": False, "command": " ".join(cmd), "output": tail,
                "message": "The update did not finish. The output below says why."}
    return {"ok": True, "restart": "exec", "command": " ".join(cmd), "output": tail,
            "message": "Updated. Restarting Job-o-Matic…"}


def _update_zip(current):
    root = bundle_root()
    part = root / ".update.zip"
    try:
        release = _get_json(releases_url(), current)
        latest = str(release.get("tag_name") or "").lstrip("vV")
        if not version_key(latest) or version_key(latest) <= version_key(current):
            return {"ok": False, "message": f"You have the newest version ({current})."}
        name = f"Job-o-Matic_v{latest}_{platform_name()}.zip"
        assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets") or []
                  if isinstance(a, dict)}
        for wanted in (name, "SHA256SUMS"):
            if not assets.get(wanted):
                raise UpdateError(f"The {latest} release has no {wanted}.")
            if not trusted(assets[wanted]):
                raise UpdateError(f"Refused a download address outside GitHub: {assets[wanted]}")
        with _get(assets["SHA256SUMS"], current, DOWNLOAD_TIMEOUT) as resp:
            sums = parse_sums(resp.read(1024 * 1024).decode("utf-8", "replace"))
        if name not in sums:
            raise UpdateError(f"SHA256SUMS does not list {name}.")
        if download(assets[name], part, current) != sums[name]:
            raise UpdateError("The download did not match its checksum.")
        stage(part, root, latest)
    except UpdateError as e:
        return {"ok": False, "message": f"Nothing was changed. {e}"}
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as e:
        return {"ok": False, "message": f"Nothing was changed. The update did not finish ({type(e).__name__}: {e})."}
    finally:
        part.unlink(missing_ok=True)
    return {"ok": True, "restart": "launcher", "latest": latest,
            "message": f"Downloaded {latest}. Restarting Job-o-Matic to finish…"}


def parse_sums(text):
    out = {}
    for line in text.splitlines():
        digest, _, name = line.strip().partition(" ")
        if re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            out[name.strip().lstrip("*")] = digest.lower()
    return out


def download(url, dest, current):
    """Streams url to dest; returns its SHA-256. Stops past MAX_DOWNLOAD."""
    h, size = hashlib.sha256(), 0
    with _get(url, current, DOWNLOAD_TIMEOUT) as resp, open(dest, "wb") as f:
        for block in iter(lambda: resp.read(1 << 20), b""):
            size += len(block)
            if size > MAX_DOWNLOAD:
                raise UpdateError("The download is larger than any Job-o-Matic release.")
            h.update(block)
            f.write(block)
    return h.hexdigest()


def stage(zip_path, root, version):
    """Unpack Job-o-Matic/app and Job-o-Matic/python from the release zip into root/.update/ + READY."""
    root = Path(root)
    work = root / ".update.part"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        with zipfile.ZipFile(zip_path) as z:
            _extract(z, work)
        for folder in ("app", "python"):
            if not (work / folder).is_dir():
                raise UpdateError(f"The download has no {folder}/ folder.")
        (work / "READY").write_text(version + "\n", encoding="utf-8")
        shutil.rmtree(root / STAGE, ignore_errors=True)
        work.rename(root / STAGE)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def _extract(z, dest):
    """Like extractall, but keeps symlinks and file modes, and refuses anything leaving dest."""
    top = "Job-o-Matic/"
    members = [i for i in z.infolist() if i.filename.startswith(top)
               and i.filename[len(top):].split("/", 1)[0] in ("app", "python")]
    if sum(i.file_size for i in members) > MAX_UNPACKED:
        raise UpdateError("The download unpacks to more than any Job-o-Matic release.")
    base = os.path.realpath(dest)
    for info in members:
        rel = info.filename[len(top):]
        parts = PurePosixPath(rel).parts
        if "\\" in rel or ":" in rel or any(p in ("..", ".") for p in parts):
            raise UpdateError(f"The download has an unsafe file name: {info.filename}")
        target = Path(dest).joinpath(*parts)
        mode = info.external_attr >> 16
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISLNK(mode):
            link = z.read(info).decode("utf-8")
            resolved = os.path.normpath(os.path.join(os.path.realpath(target.parent), link))
            if os.path.isabs(link) or os.path.commonpath([base, resolved]) != base:
                raise UpdateError(f"The download has a link leaving its folder: {info.filename}")
            os.symlink(link, target)
            continue
        with z.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        if mode & 0o777:
            os.chmod(target, mode & 0o777)
