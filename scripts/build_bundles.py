#!/usr/bin/env python3
"""Build the downloadable Job-o-Matic zips into dist/ (one per platform).

    python3 scripts/build_bundles.py | tee ../05_versions/v1.0.0/build.log

Downloads portable Python (cached in build/cache/), checks it against the
SHA-256 digests pinned below, installs the hash-locked wheels in
requirements-bundle.txt (--require-hashes), adds the tracked app files and a
blank database. Any checksum mismatch or missing file aborts.

The version comes from src/jobomatic/version.py; the "What's new" text from
scripts/release_notes/v<VERSION>.md. Refresh the wheel lock after changing
requirements.txt:
    uv pip compile requirements.txt -c bundle-constraints.txt --generate-hashes --universal \\
        --python-version 3.13 --no-header -o requirements-bundle.txt
bundle-constraints.txt holds per-platform pins (e.g. the last cryptography with macOS Intel wheels)."""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version(path=ROOT / "src" / "jobomatic" / "version.py"):
    """VERSION = "x.y.z" from version.py, the single source (no import: the build needs no sys.path)."""
    m = re.search(r'^VERSION = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not m:
        sys.exit(f"ABORT: no VERSION in {path}")
    return m.group(1)


VERSION = read_version()
PBS_TAG = "20261026"
PBS_PYTHON = "3.13.18"
PBS_SHA256 = {  # pinned from the release's SHA256SUMS; a new PBS_TAG needs new digests here
    "x86_64-pc-windows-msvc": "ebe90cc1dce2dd2d7afa1f0aa9b6c269c7c0174aeabdc6a801381602b7283424",
    "aarch64-apple-darwin": "e5af2fde6a937a0e0c795a0c595c4efb70578d57463a2657c819992b9b9acbac",
    "x86_64-apple-darwin": "708be9e7df297f68bdae589ea9e62a621db5abe7708f79e851c41410347452d1",
    "x86_64-unknown-linux-gnu": "126343c54daff4068efc1ac269518d0cc202d57857794948103dd1454e8881be",
}
PBS_URL = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/"
)
UV = Path.home() / ".local" / "bin" / "uv"
PLATFORMS = {
    "windows-x64": "x86_64-pc-windows-msvc",
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x64": "x86_64-apple-darwin",
    "linux-x64": "x86_64-unknown-linux-gnu",
}
APP_PATHS = [
    "src",
    "templates",
    "docs/AI_GUIDE.md",
    "docs/assets",
    "assets",
    "scripts/connect_claude_desktop.py",
    "pyproject.toml",  # the zip has no package metadata: __version__ reads the version from here
    "LICENSE",
    "NOTICE.md",
    "PRIVACY.md",
    "README.md",
]
OMIT = ("tests/", "scripts/build_bundles.py", "scripts/make_demo_originals.py")
ORIGINALS = ["resumes", "job_descriptions", "reviews", "recommendations", "other"]
VIEW_NAME = "Job-o-Matic (view only).html"

BUILD = ROOT / "build"
CACHE = BUILD / "cache"
DIST = ROOT / "dist"
NOTES = ROOT.parent / "05_versions" / f"v{VERSION}"
REQUIREMENTS = ROOT / "requirements-bundle.txt"
WHATS_NEW = ROOT / "scripts" / "release_notes" / f"v{VERSION}.md"

# The helper adds the app-menu entry itself on first run (Start Menu / app menu / ~/Applications,
# see src/jobomatic/shortcuts.py). The launchers start it, and first apply an update the app
# downloaded (src/jobomatic/updates.py): .update/READY means swap .update/app and .update/python in
# (the old ones become app.prev and python.prev) and write .update/TRIAL. The helper deletes
# .update/ once it is listening; if Python exits with an error before that (within TRIAL_SECONDS),
# the .prev folders go back and .update/FAILED tells the page. my_data/ is never touched.
TRIAL_SECONDS = 30
SH_LAUNCHER = """#!/bin/sh
# Job-o-Matic launcher.
CD_LINE
PY=./python/bin/python3
APP=app/src/jobomatic/helper.py
TRIAL_SECONDS=${JOBOMATIC_TRIAL_SECONDS:-TRIAL_DEFAULT}

give_up() {  # leave a note for the page; the next start runs normally
    rm -rf .update && mkdir .update && : > .update/FAILED
}

restore() {  # put the previous version back
    rm -rf app python
    mv app.prev app && mv python.prev python
    give_up
}

apply_update() {
    [ -d .update/app ] && [ -d .update/python ] || return 1
    rm -rf app.prev python.prev
    mv app app.prev || return 1
    if ! mv python python.prev; then
        mv app.prev app
        return 1
    fi
    if mv .update/app app && mv .update/python python; then
        rm -f .update/READY .update/EXIT.* && : > .update/TRIAL && return 0
    fi
    restore
    return 1
}

if [ -n "${JOBOMATIC_WAIT_PID:-}" ]; then  # started by "Update now": let the old helper exit first
    i=0
    while kill -0 "$JOBOMATIC_WAIT_PID" 2>/dev/null && [ "$i" -lt 30 ]; do
        sleep 1
        i=$((i + 1))
    done
fi

if [ -f .update/READY ] && ! apply_update; then
    echo "Job-o-Matic: the update could not be applied; starting the current version." >&2
    [ -f .update/FAILED ] || give_up
fi

if [ -f .update/TRIAL ]; then
    # The exit file carries this launcher's PID, so a helper from an earlier run that quits later
    # (to install the next update) can't be mistaken for this trial's result.
    EXIT_FILE=".update/EXIT.$$"
    ( "$PY" "$APP" --open; status=$?; { echo "$status" > "$EXIT_FILE"; } 2>/dev/null; exit "$status" ) &
    child=$!
    i=0
    while [ -f .update/TRIAL ] && [ ! -f "$EXIT_FILE" ] && [ "$i" -lt "$TRIAL_SECONDS" ]; do
        sleep 1
        i=$((i + 1))
    done
    if [ -f .update/TRIAL ] && [ -f "$EXIT_FILE" ] && [ "$(cat "$EXIT_FILE")" != 0 ]; then
        echo "Job-o-Matic: the new version did not start; putting the previous version back." >&2
        wait "$child"
        restore
        exec "$PY" "$APP" --open
    fi
    wait "$child"
    exit $?
fi

exec "$PY" "$APP" --open
""".replace("TRIAL_DEFAULT", str(TRIAL_SECONDS))

BAT_LAUNCHER = r"""@echo off
rem Job-o-Matic launcher.
setlocal
cd /d "%~dp0"
if defined JOBOMATIC_WAIT_PID powershell -NoProfile -Command "Wait-Process -Id %JOBOMATIC_WAIT_PID% -Timeout 30 -ErrorAction SilentlyContinue"
if not exist ".update\READY" goto trial
if not exist ".update\app" goto giveup
if not exist ".update\python" goto giveup
if exist app.prev rmdir /s /q app.prev
if exist python.prev rmdir /s /q python.prev
move app app.prev >nul || goto giveup
move python python.prev >nul || goto putapp
move .update\app app >nul || goto restore
move .update\python python >nul || goto restore
del .update\READY
type nul > .update\TRIAL
:trial
if not exist ".update\TRIAL" goto run
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -PassThru -FilePath 'python\pythonw.exe' -ArgumentList 'app\src\jobomatic\helper.py','--open'; $null = $p.Handle; for ($i = 0; $i -lt TRIAL_DEFAULT; $i++) { if (-not (Test-Path '.update\TRIAL')) { exit 0 }; if ($p.HasExited) { exit $p.ExitCode }; Start-Sleep 1 }; exit 0"
if errorlevel 1 goto restore
goto :eof
:restore
echo Job-o-Matic: the new version did not start; putting the previous version back.
if exist app rmdir /s /q app
if exist python rmdir /s /q python
move app.prev app >nul
move python.prev python >nul
goto giveup
:putapp
move app.prev app >nul
:giveup
if exist .update rmdir /s /q .update
mkdir .update
type nul > .update\FAILED
:run
start "" python\pythonw.exe app\src\jobomatic\helper.py --open
""".replace("TRIAL_DEFAULT", str(TRIAL_SECONDS))

LAUNCHERS = {
    "Job-o-Matic.bat": BAT_LAUNCHER.replace("\n", "\r\n"),
    "Job-o-Matic.command": SH_LAUNCHER.replace("CD_LINE", 'cd "$(dirname "$0")" || exit 1'),
    "job-o-matic.sh": SH_LAUNCHER.replace("CD_LINE", 'cd "$(dirname "$(readlink -f "$0")")" || exit 1'),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name):
    dest = CACHE / name
    if not dest.exists():
        print(f"download {name}")
        urllib.request.urlretrieve(PBS_URL + name.replace("+", "%2B"), dest)
    return dest


def pbs_asset(triple):
    return f"cpython-{PBS_PYTHON}+{PBS_TAG}-{triple}-install_only.tar.gz"


def verified_tarballs():
    """Each tarball must match the digest pinned in PBS_SHA256 (not a SHA256SUMS from the same server)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for plat, triple in PLATFORMS.items():
        name = pbs_asset(triple)
        if triple not in PBS_SHA256:
            sys.exit(f"ABORT: no pinned digest for {name}")
        path = fetch(name)
        if sha256(path) != PBS_SHA256[triple]:
            path.unlink()
            sys.exit(f"ABORT: checksum mismatch for {name}")
        print(f"ok checksum {name}")
        out[plat] = path
    return out


def tracked_app_files():
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *APP_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = [f for f in out.split("\0") if f and not f.startswith(OMIT)]
    if "src/db.py" not in files:
        sys.exit("ABORT: src/db.py is not tracked")
    return files


def site_packages(plat, pydir):
    sp = (
        pydir / "Lib" / "site-packages"
        if plat == "windows-x64"
        else pydir / "lib" / "python3.13" / "site-packages"
    )
    if not sp.is_dir():
        sys.exit(f"ABORT: no site-packages at {sp}")
    return sp


def strip_linux(pydir):
    targets = [pydir / "bin" / "python3.13", *pydir.joinpath("lib").rglob("*.so*")]
    for t in targets:
        if t.is_symlink() or not t.is_file():
            continue
        r = subprocess.run(
            ["strip", "--strip-unneeded", str(t)],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode:
            sys.exit(f"ABORT: strip failed on {t}: {r.stderr}")


def make_blank_db(dest):
    sys.path.insert(0, str(ROOT / "src"))
    from jobomatic import store

    dest.parent.mkdir(parents=True, exist_ok=True)
    store.new_database(dest)


def make_view(db, dest):
    sys.path.insert(0, str(ROOT / "src"))
    from jobomatic import viewer

    built = viewer.build(db)  # writes my_data/viewer_data.js and the view-only HTML beside my_data/
    if built != dest or not dest.exists():
        sys.exit(f"ABORT: viewer.build() wrote {built}, expected {dest}")


START_HERE = """START HERE - Job-o-Matic

Job-o-Matic keeps your career data for your AI to use. Connect an MCP app
such as Claude Desktop (it reads and saves for you) or copy a prompt into any chat AI. The screens
are for checking and fixing your data.

1. Open it: double-click the launcher in this folder (Job-o-Matic.bat on
   Windows, .command on Mac, job-o-matic.sh on Linux). Your computer may warn
   you once; README.md explains what to click. Nothing is sent anywhere.
2. To connect your AI, see README.md, section "Connect your AI".
3. Your data is in the my_data folder. Copy it to back up. See PRIVACY.md.
"""


def strip_images(text):
    """The zip ships no docs/assets, so drop markdown image lines from bundled copies."""
    return re.sub(r"^!\[[^\]]*\]\([^)]*\)[ \t]*\n+", "", text, flags=re.MULTILINE)


def add_top_level_docs(root, repo=ROOT):
    """START HERE.txt, README.md (HTML comments stripped) and PRIVACY.md at the zip top level."""
    (root / "START HERE.txt").write_text(START_HERE, encoding="utf-8")
    readme = (repo / "README.md").read_text(encoding="utf-8")
    readme = re.sub(r"<!--.*?-->\s*", "", readme, flags=re.DOTALL).rstrip() + "\n"
    readme = readme.replace("<version>", VERSION)
    (root / "README.md").write_text(strip_images(readme), encoding="utf-8")
    privacy = (repo / "PRIVACY.md").read_text(encoding="utf-8")
    (root / "PRIVACY.md").write_text(strip_images(privacy), encoding="utf-8")


def wheel_install_args(triple, target):
    """uv installs only wheels whose hashes are in requirements-bundle.txt."""
    return [str(UV), "pip", "install", "--quiet", "--target", str(target), "--python-platform", triple,
            "--python-version", "3.13", "--only-binary", ":all:", "--require-hashes", "-r", str(REQUIREMENTS)]


def assemble(plat, triple, tarball, files):
    root = BUILD / plat / "Job-o-Matic"
    shutil.rmtree(BUILD / plat, ignore_errors=True)
    root.mkdir(parents=True)
    with tarfile.open(tarball) as t:
        t.extractall(root, filter="data")
    pydir = root / "python"
    exe = pydir / ("python.exe" if plat == "windows-x64" else "bin/python3")
    if not exe.exists():
        sys.exit(f"ABORT: {exe} missing in {tarball.name}")
    if plat == "windows-x64" and not (pydir / "pythonw.exe").exists():
        sys.exit("ABORT: pythonw.exe missing in Windows build")
    subprocess.run(wheel_install_args(triple, site_packages(plat, pydir)), check=True)
    for f in files:
        dst = root / "app" / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dst)
    for d in ORIGINALS:
        (root / "my_data" / "originals" / d).mkdir(parents=True)
    db = root / "my_data" / "jobomatic.db"
    make_blank_db(db)
    for name, text in LAUNCHERS.items():
        if plat == "windows-x64" and name != "Job-o-Matic.bat":
            continue
        if plat.startswith("macos") and name != "Job-o-Matic.command":
            continue
        if plat == "linux-x64" and not name.startswith("job-o-matic."):
            continue
        (root / name).write_bytes(text.encode())
    make_view(db, root / VIEW_NAME)
    add_top_level_docs(root)
    for backup in (db.parent / "backups").glob("*"):  # the viewer build backs up the blank DB; don't ship it
        backup.unlink()
    (db.parent / "backups").rmdir()
    return root


def write_zip(plat, root):
    out = DIST / f"Job-o-Matic_v{VERSION}_{plat}.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root.parent).as_posix()
            if p.is_symlink():
                info = zipfile.ZipInfo(rel)
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, os.readlink(p))
                continue
            if p.is_dir():
                info = zipfile.ZipInfo(rel + "/")
                info.external_attr = (0o40755 << 16) | 0x10
                z.writestr(info, b"")
                continue
            info = zipfile.ZipInfo.from_file(p, rel)
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = (p.stat().st_mode & 0o111) or p.suffix in (
                ".command",
                ".sh",
                ".desktop",
            )
            mode = 0o755 if executable else 0o644
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, p.read_bytes())
    print(f"zip {out.name} {out.stat().st_size} bytes")
    return out


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main():
    if not WHATS_NEW.exists():
        sys.exit(f"ABORT: no release notes at {WHATS_NEW}")
    if not UV.exists():
        sys.exit(f"ABORT: uv not found at {UV}")
    tarballs = verified_tarballs()
    files = tracked_app_files()
    DIST.mkdir(exist_ok=True)
    zips = [
        write_zip(p, assemble(p, PLATFORMS[p], tarballs[p], files)) for p in PLATFORMS
    ]
    sums = "".join(f"{sha256(z)}  {z.name}\n" for z in zips)
    (DIST / "SHA256SUMS").write_text(sums)
    NOTES.mkdir(parents=True, exist_ok=True)
    (NOTES / "artifact_digests.txt").write_text(sums)
    head = git("rev-parse", "HEAD")
    root_commit = git("rev-list", "--max-parents=0", "HEAD").splitlines()[0]
    (NOTES / "git_range.txt").write_text(
        f"HEAD at build: {head}\nrange: {root_commit}..{head}\n"
    )
    (NOTES / "release_notes.md").write_text(release_notes())
    print(sums, end="")
    print("✅ build complete")


RELEASE_NOTES = """# Job-o-Matic v{VERSION}

Four downloads: windows-x64, macos-arm64, macos-x64, linux-x64. Each unzips to a
`Job-o-Matic/` folder holding:

- `python/`: portable CPython {PBS_PYTHON} (python-build-standalone {PBS_TAG}) with {packages}
- `app/`: the program (src, templates, AI guide, Claude Desktop connector, licence files)
- `my_data/jobomatic.db`: a blank database, and empty `originals/` folders
- a launcher (`Job-o-Matic.bat`, `Job-o-Matic.command`, or `job-o-matic.sh`).
  On first run the app adds itself to the Start Menu (Windows), the app menu (Linux) or
  `~/Applications` (macOS), with its icon; `--remove-shortcut` takes it out again
- `{VIEW_NAME}` (open by double-click, no program needed)

The demo seed (`app/src/db/seed_demo.sql`) ships but is not loaded by default.

{whats_new}

## First run
The launchers are not code-signed, so you will see a warning once:
- Windows: "Windows protected your PC" > More info > Run anyway. Keep the black window open while the app runs.
- macOS: System Settings > Privacy & Security > Open Anyway (macOS 15 and newer removed right-click > Open).
- Linux: `chmod +x job-o-matic.sh` once.

## Known limits
- Windows and macOS builds have not been run on real machines; only the Linux build was executed.
- Databases made by earlier test builds (before schema version 4) are not upgraded; start a new one.
- No OCR: scanned PDFs without a text layer yield no extracted text.
- Launchers are not code-signed; see First run above.
"""


def bundled_packages(path=ROOT / "requirements.txt"):
    """`mcp` 2.3.0, `phonenumbers` 9.0.44 and `pypdf` 6.21.4, from requirements.txt."""
    pins = [line.split("==") for line in path.read_text(encoding="utf-8").splitlines() if "==" in line]
    names = [f"`{n.strip()}` {v.strip()}" for n, v in pins]
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def release_notes():
    return RELEASE_NOTES.format(VERSION=VERSION, PBS_PYTHON=PBS_PYTHON, PBS_TAG=PBS_TAG, VIEW_NAME=VIEW_NAME,
                                packages=bundled_packages(), whats_new=WHATS_NEW.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
