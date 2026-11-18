#!/usr/bin/env python3
# Made by Jerry Reinitz of Reinitz Industries, Tulsa. Custom software that fits the job and works. https://jerryreinitz.com
"""Print (or with --write, install) the Claude Desktop config entry for the Job-O-Matic MCP server.

Bundle layout: Job-o-Matic/app/scripts/ (this file), Job-o-Matic/python/, Job-o-Matic/my_data/."""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[2]


def config_path():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def entry():
    python = BUNDLE / "python" / ("python.exe" if sys.platform == "win32" else "bin/python3")
    return {
        "command": str(python),
        "args": [str(BUNDLE / "app" / "src" / "jobomatic" / "mcp_server.py")],
        "env": {"JOBOMATIC_DB": str(BUNDLE / "my_data" / "jobomatic.db")},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="merge into the Claude Desktop config (a .bak copy is made first)")
    args = ap.parse_args()
    snippet = {"mcpServers": {"job-o-matic": entry()}}
    path = config_path()
    if not args.write:
        print(
            "Preview only \u2014 nothing was changed. "
            f"Run again with --write to add Job-o-Matic to {path}. "
            "Your other Claude Desktop settings are kept, and a backup is made first.\n"
        )
        print(json.dumps(snippet, indent=2))
        return
    backup = None
    config = {}
    if path.exists():
        backup = path.with_name(f"{path.name}.{datetime.now().astimezone():%Y%m%d%H%M%S}.bak")
        shutil.copy2(path, backup)
        config = json.loads(path.read_text(encoding="utf-8"))
    servers = config.setdefault("mcpServers", {})
    existed = "job-o-matic" in servers
    servers["job-o-matic"] = snippet["mcpServers"]["job-o-matic"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if existed:
        print(f"Job-o-Matic was already set \u2014 updated in {path}. Your other settings were kept.")
    else:
        print(f"Added Job-o-Matic to {path}. Your other settings were kept.")
    e = snippet["mcpServers"]["job-o-matic"]
    print(f"Program: {e['command']}\nServer: {e['args'][0]}\nYour data file: {e['env']['JOBOMATIC_DB']}")
    print(f"Backup of your old settings: {backup}" if backup else "No earlier settings file existed, so no backup was needed.")
    print("What was added:")
    print(json.dumps(snippet, indent=2))
    print("Fully quit Claude Desktop (Cmd+Q on Mac) and reopen it.")


if __name__ == "__main__":
    main()
