"""App-menu entry, like a real app: Start Menu (Windows), app menu (Linux/BSD), ~/Applications (macOS).

Made once, on the first run of a pip or zip install (marker: <data_dir>/shortcut.json), and any
time with `job-o-matic --add-shortcut` / `--remove-shortcut`. No new dependencies; no admin rights.
A failure prints one line and never stops the app."""
import base64
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from jobomatic import paths
from jobomatic.version import get_version

APP_NAME = "Job-o-Matic"
COMMENT = "Your career data, for your AI to use"
BUNDLE_ID = "com.reinitz.jobomatic"
DESKTOP_NAME = "job-o-matic.desktop"
MAC_EXEC = "job-o-matic"
MARKER = "shortcut.json"
SKIP_ENV = "JOBOMATIC_NO_SHORTCUT"
PS_TIMEOUT = 30


def _os():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "freedesktop"  # Linux, the BSDs, and other X11/Wayland desktops


def _install_type():
    from jobomatic.updates import install_type

    return install_type()


def icon(name):
    """Absolute path to a shipped icon: icon.ico, icon-256.png, icon.icns."""
    return (paths.resource("assets") / name).resolve()


def launch_command(os_name=None):
    """(program, [args]) that opens the app. pip: python -m jobomatic.helper; zip: the bundle's launcher."""
    os_name = os_name or _os()
    exe = Path(sys.executable)
    if os_name == "windows":
        pythonw = exe.with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else exe  # pythonw: no console window
    if paths.installed():
        return str(exe), ["-m", "jobomatic.helper", "--open"]
    bundle = paths.PKG.parents[2]
    launcher = {"freedesktop": bundle / "job-o-matic.sh", "mac": bundle / "Job-o-Matic.command"}.get(os_name)
    if launcher is not None and launcher.is_file() and _install_type() == "zip":
        return "/bin/sh", [str(launcher)]  # via sh: works even if unzipping dropped the execute bit
    return str(exe), [str(paths.PKG / "helper.py"), "--open"]


def shortcut_path(os_name=None):
    os_name = os_name or _os()
    if os_name == "windows":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"
    if os_name == "mac":
        return Path.home() / "Applications" / f"{APP_NAME}.app"
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "applications" / DESKTOP_NAME


# ---------- Windows ----------

def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def windows_script(lnk, program, args, workdir, ico):
    """The one PowerShell statement that writes the .lnk (WScript.Shell, as the old zip launcher did)."""
    arg_text = " ".join(f'"{a}"' if " " in a else a for a in args)
    return (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(lnk)});"
        f"$s.TargetPath={_ps_quote(program)};$s.Arguments={_ps_quote(arg_text)};"
        f"$s.WorkingDirectory={_ps_quote(workdir)};$s.IconLocation={_ps_quote(f'{ico},0')};"
        f"$s.Description={_ps_quote(COMMENT)};$s.Save()"
    )


def windows_command(script):
    """powershell argv; -EncodedCommand (UTF-16LE base64) so no path quoting can break the call."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def _add_windows(target):
    program, args = launch_command("windows")
    target.parent.mkdir(parents=True, exist_ok=True)
    script = windows_script(target, program, args, Path(program).parent, icon("icon.ico"))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(windows_command(script), capture_output=True, text=True, timeout=PS_TIMEOUT,
                       check=False, creationflags=flags)
    if r.returncode != 0 or not target.exists():
        raise OSError((r.stderr or r.stdout or f"PowerShell exit {r.returncode}").strip().splitlines()[-1])


# ---------- Linux / BSD (freedesktop) ----------

def _desktop_quote(arg):
    """Exec= quoting per the Desktop Entry spec: quote when needed; escape \\ " ` $ inside; % doubles."""
    arg = str(arg).replace("%", "%%")
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    for c in ("\\", '"', "`", "$"):
        arg = arg.replace(c, "\\" + c)
    return f'"{arg}"'


def desktop_entry(program, args, icon_path):
    exec_line = " ".join(_desktop_quote(a) for a in [program, *args])
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Comment={COMMENT}\n"
        f"Exec={exec_line}\n"
        f"Icon={icon_path}\n"
        "Terminal=false\n"
        "Categories=Office;\n"
        "StartupNotify=false\n"
    )


def _add_freedesktop(target):
    program, args = launch_command("freedesktop")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_entry(program, args, icon("icon-256.png")), encoding="utf-8")
    target.chmod(0o755)  # some desktops only launch entries marked executable
    _refresh_menu(target.parent)


def _refresh_menu(folder):
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, "-q", str(folder)], capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


# ---------- macOS ----------

def info_plist():
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": MAC_EXEC,
        "CFBundleIconFile": "icon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": get_version() or "0",
        "LSMinimumSystemVersion": "11.0",
    }


def mac_launcher(program, args):
    return "#!/bin/sh\nexec " + " ".join(shlex.quote(a) for a in [program, *args]) + "\n"


def _add_mac(target):
    program, args = launch_command("mac")
    contents = target / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(parents=True, exist_ok=True)
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(info_plist(), f)
    exe = contents / "MacOS" / MAC_EXEC
    exe.write_text(mac_launcher(program, args), encoding="utf-8")
    exe.chmod(0o755)
    icns = icon("icon.icns")
    if icns.is_file():
        shutil.copyfile(icns, contents / "Resources" / "icon.icns")
    os.utime(target)  # nudges Finder to pick up the icon


def _is_ours_mac(target):
    try:
        with open(target / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier") == BUNDLE_ID
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False


# ---------- public ----------

def _note(msg):
    print(f"Note: {msg}", file=sys.stderr, flush=True)


def _write_marker(data_dir, **fields):
    if data_dir is None:
        return
    try:
        fields["at"] = datetime.now(UTC).isoformat(timespec="seconds")
        (Path(data_dir) / MARKER).write_text(json.dumps(fields, indent=2), encoding="utf-8")
    except OSError:
        pass


def _target_id():
    program, args = launch_command()
    return " ".join([program, *args])


def add_shortcut(data_dir=None):
    """Makes (or refreshes) the app-menu entry. Returns its path, or None after printing a note."""
    os_name = _os()
    target = shortcut_path(os_name)
    try:
        {"windows": _add_windows, "mac": _add_mac, "freedesktop": _add_freedesktop}[os_name](target)
    except Exception as e:  # noqa: BLE001 - a shortcut must never stop the app
        _note(f"could not add {APP_NAME} to the app menu ({type(e).__name__}: {e}). The app still works.")
        _write_marker(data_dir, ok=False, removed=False, path=str(target), target=_safe_target_id(),
                      error=str(e)[:200])
        return None
    _write_marker(data_dir, ok=True, removed=False, path=str(target), target=_safe_target_id())
    return target


def _safe_target_id():
    try:
        return _target_id()
    except Exception:  # noqa: BLE001
        return ""


def remove_shortcut(data_dir=None):
    """Removes the app-menu entry. Returns its path if one was removed, else None. Never raises."""
    os_name = _os()
    target = shortcut_path(os_name)
    removed = None
    try:
        if os_name == "mac":
            if target.is_dir() and _is_ours_mac(target):
                shutil.rmtree(target)
                removed = target
        elif target.is_file():
            target.unlink()
            removed = target
            if os_name == "freedesktop":
                _refresh_menu(target.parent)
    except Exception as e:  # noqa: BLE001
        _note(f"could not remove {target} ({type(e).__name__}: {e}).")
        return None
    _write_marker(data_dir, ok=True, removed=True, path=str(target))
    return removed


def ensure_first_run(data_dir):
    """On the first run of a pip or zip install, add the app-menu entry once.

    Re-made only if the launch target changed (the zip folder moved, Python was reinstalled), and
    never after --remove-shortcut. Skipped for repo checkouts and when JOBOMATIC_NO_SHORTCUT=1."""
    try:
        if os.environ.get(SKIP_ENV) == "1" or _install_type() == "repo":
            return None
        marker = Path(data_dir) / MARKER
        state = {}
        if marker.is_file():
            try:
                state = json.loads(marker.read_text(encoding="utf-8"))
            except ValueError:
                state = {}
            if not isinstance(state, dict) or state.get("removed") or state.get("target") == _target_id():
                return None
        target = add_shortcut(data_dir)
        if target is not None:
            print(f"Added {APP_NAME} to your app menu: {target}", flush=True)
        return target
    except Exception as e:  # noqa: BLE001
        _note(f"skipped the app-menu entry ({type(e).__name__}: {e}).")
        return None
