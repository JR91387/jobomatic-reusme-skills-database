#!/usr/bin/env python3
"""Build the downloadable Job-o-Matic zips into dist/ (one per platform).

    python3 scripts/build_bundles.py | tee ../05_versions/v1.0.0/build.log

Downloads portable Python (cached in build/cache/), checks it against the
release's SHA256SUMS, installs requirements.txt wheels, adds the tracked app
files and a blank database. Any checksum mismatch or missing file aborts."""

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

VERSION = "1.1.0"
PBS_TAG = "20261026"
PBS_PYTHON = "3.13.18"
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
    "LICENSE",
    "NOTICE.md",
    "PRIVACY.md",
    "README.md",
]
OMIT = ("tests/", "scripts/build_bundles.py", "scripts/make_demo_originals.py")
ORIGINALS = ["resumes", "job_descriptions", "reviews", "recommendations", "other"]
VIEW_NAME = "Job-o-Matic (view only).html"

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
DIST = ROOT / "dist"
NOTES = ROOT.parent / "05_versions" / f"v{VERSION}"

RUN = "exec ./python/bin/python3 app/src/jobomatic/helper.py --open\n"
# Windows: on first run, make a Job-o-Matic.lnk beside the .bat with the app icon (one PowerShell call, no admin).
# goto instead of an if-block: a folder path holding ")" would end the block early.
WIN_SHORTCUT = (
    "if exist \"Job-o-Matic.lnk\" goto run\r\n"
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~dp0Job-o-Matic.lnk');"
    "$s.TargetPath='%~dp0python\\pythonw.exe';$s.Arguments='app\\src\\jobomatic\\helper.py --open';"
    "$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0app\\assets\\icon.ico,0';$s.Save()\" >nul 2>&1"
    " || echo Note: could not create the Job-o-Matic shortcut. This file still opens the app.\r\n"
    ":run\r\n"
)
# Linux: point the .desktop Icon= at this folder (a zip can't hold an absolute path); redone if the folder moves.
LINUX_ICON = (
    'ICON="$PWD/app/assets/icon-256.png"\n'
    'grep -qxF "Icon=$ICON" job-o-matic.desktop 2>/dev/null'
    ' || sed -i "s|^Icon=.*|Icon=$ICON|" job-o-matic.desktop 2>/dev/null || true\n'
)
LAUNCHERS = {
    "Job-o-Matic.bat": (
        '@echo off\r\ncd /d "%~dp0"\r\n' + WIN_SHORTCUT
        + 'start "" python\\pythonw.exe app\\src\\jobomatic\\helper.py --open\r\n'
    ),
    "Job-o-Matic.command": '#!/bin/sh\ncd "$(dirname "$0")" || exit 1\n' + RUN,
    "job-o-matic.sh": '#!/bin/sh\ncd "$(dirname "$(readlink -f "$0")")" || exit 1\n'
    + LINUX_ICON
    + RUN,
    "job-o-matic.desktop": (
        "[Desktop Entry]\nType=Application\nName=Job-o-Matic\nComment=Your career repository\n"
        'Exec=sh -c \'exec "$(dirname "$1")/job-o-matic.sh"\' _ %k\nTerminal=false\nIcon=job-o-matic\nCategories=Office;\n'
    ),
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
    CACHE.mkdir(parents=True, exist_ok=True)
    sums = {}
    (CACHE / "SHA256SUMS").unlink(missing_ok=True)
    for line in fetch("SHA256SUMS").read_text().splitlines():
        digest, _, name = line.partition("  ")
        sums[name.strip().lstrip("*")] = digest
    out = {}
    for plat, triple in PLATFORMS.items():
        name = pbs_asset(triple)
        if name not in sums:
            sys.exit(f"ABORT: {name} not listed in SHA256SUMS")
        path = fetch(name)
        if sha256(path) != sums[name]:
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
    subprocess.run(
        [
            str(UV),
            "pip",
            "install",
            "--quiet",
            "--target",
            str(site_packages(plat, pydir)),
            "--python-platform",
            triple,
            "--python-version",
            "3.13",
            "--only-binary",
            ":all:",
            "-r",
            str(ROOT / "requirements.txt"),
        ],
        check=True,
    )
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
    (NOTES / "release_notes.md").write_text(RELEASE_NOTES)
    print(sums, end="")
    print("✅ build complete")


RELEASE_NOTES = f"""# Job-o-Matic v{VERSION}

Four downloads: windows-x64, macos-arm64, macos-x64, linux-x64. Each unzips to a
`Job-o-Matic/` folder holding:

- `python/`: portable CPython {PBS_PYTHON} (python-build-standalone {PBS_TAG}) with `mcp` 2.3.0 and `pypdf` 6.21.4
- `app/`: the program (src, templates, AI guide, Claude Desktop connector, licence files)
- `my_data/jobomatic.db`: a blank database, and empty `originals/` folders
- a launcher (`Job-o-Matic.bat`, `Job-o-Matic.command`, or `job-o-matic.sh` + `.desktop`).
  On first run the Windows `.bat` makes a `Job-o-Matic.lnk` shortcut with the app icon beside itself;
  `job-o-matic.sh` points the `.desktop` file's icon at `app/assets/icon-256.png`
- `{VIEW_NAME}` (open by double-click, no program needed)

The demo seed (`app/src/db/seed_demo.sql`) ships but is not loaded by default.

## What's new
- **Install from PyPI.** `uvx job-o-matic-mcp` runs the MCP server with no download; `pip install job-o-matic` adds `job-o-matic` and `job-o-matic-db`. Listed in the official MCP Registry.

From v1.0.0, the first public release:
- **New data model.** Employers, then positions (a promotion is a second position under the same employer), then items: one typed table for responsibilities, achievements, awards, projects, reviews and more, with numbers in `item_metrics` and source documents linked through `item_originals`.
- **Built for your AI.** 15 MCP tools (including `save_many` and `add_original`), a plain-language `schema_guide`, and a wiki written for AI agents. What your AI writes appears in the app within seconds, marked "Needs review" until you check it.
- **Better prompts.** Prompts for chat-only AIs carry your real data and ask for text back; an AI-written file can come back in through Originals.
- **Safer edits.** Remove asks first and removed rows can be restored; a date outside its job shows a warning; forms keep what you typed through reloads and save conflicts.
- **Backups.** A checked daily copy, plus "Back up now" and "Open my folder" in Settings.
- **Downloads.** `START HERE.txt`, `README.md` and `PRIVACY.md` at the top of the zip.

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

if __name__ == "__main__":
    main()
