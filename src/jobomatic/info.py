"""What the page and the AI prompts need to know about this install: where the data is and how the MCP server starts."""
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from jobomatic import __version__, paths

SERVER_NAME = "job-o-matic"
SCRIPT = "job-o-matic-mcp"


def install_type():
    """'pip' | 'zip' | 'repo' -- updates.install_type with uv-tool and pipx counted as pip."""
    from jobomatic import updates

    kind = updates.install_type()
    return "pip" if kind in ("uv-tool", "pipx") else kind


def _console_script():
    """Full path of the job-o-matic-mcp script, or None when it can't be found."""
    found = shutil.which(SCRIPT)
    if found:
        return str(Path(found))
    exe = SCRIPT + (".exe" if sys.platform == "win32" else "")
    for folder in (sysconfig.get_path("scripts"), Path(sys.executable).parent):
        if folder and (Path(folder) / exe).is_file():
            return str(Path(folder) / exe)
    return None


def mcp_command(kind=None):
    """(command, args, full_path) a person's AI app runs to start the MCP server."""
    kind = kind or install_type()
    if kind == "pip":
        return SCRIPT, [], _console_script()
    server = str(paths.PKG / "mcp_server.py")
    if kind == "zip":
        bundle = paths.PKG.parents[2]  # <bundle>/app/src/jobomatic
        python = bundle / "python" / ("python.exe" if sys.platform == "win32" else "bin/python3")
        return str(python), [server], None
    return sys.executable, [server], None


def display(command, args):
    parts = [command] + list(args)
    return subprocess.list2cmdline(parts) if sys.platform == "win32" else " ".join(
        f'"{p}"' if " " in p else p for p in parts)


def app_info(db_path):
    db_path = Path(db_path).resolve()
    kind = install_type()
    command, args, full = mcp_command(kind)
    return {
        "version": __version__,
        "data_folder": str(db_path.parent),
        "db_path": str(db_path),
        "install_type": kind,
        "mcp": {
            "name": SERVER_NAME,
            "command": command,
            "args": args,
            "command_path": full,
            "display": display(command, args),
            "transport": "stdio",
            "env": {"JOBOMATIC_DB": str(db_path)},
        },
    }
