#!/bin/sh
# Job-o-Matic installer for macOS, Linux and BSD.
#
#   curl -LsSf https://raw.githubusercontent.com/JR91387/jobomatic-reusme-skills-database/main/install.sh | sh
#
# What it does:
#   1. Installs (or upgrades) the job-o-matic package: with uv if you have it,
#      otherwise with "python3 -m pip install --user" (needs Python 3.12 or newer).
#   2. Starts Job-o-Matic in the background. On its first run it adds itself to your
#      app menu and opens in your browser.
# Safe to run again: it upgrades in place and never touches your data folder.
set -eu

# The whole body is a function called on the last line, so a download cut short runs nothing.
main() {
    PKG=job-o-matic
    say() { printf '%s\n' "$*"; }
    fail() { printf 'Stopped: %s\n' "$*" >&2; exit 1; }

    if command -v uv >/dev/null 2>&1; then
        say "Installing Job-o-Matic with uv: uv tool install --upgrade $PKG"
        uv tool install --upgrade "$PKG" || fail "uv could not install $PKG (see the message above)."
        BIN_DIR=$(uv tool dir --bin 2>/dev/null || printf '%s' "$HOME/.local/bin")
    else
        command -v python3 >/dev/null 2>&1 \
            || fail "Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/ (or install uv: https://docs.astral.sh/uv/), then run this again."
        python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
            || fail "Job-o-Matic needs Python 3.12 or newer; this computer has $(python3 -V 2>&1). Install a newer Python or uv (https://docs.astral.sh/uv/), then run this again."
        python3 -m pip --version >/dev/null 2>&1 \
            || fail "pip is missing for python3. Install it (for example: sudo apt install python3-pip) or install uv (https://docs.astral.sh/uv/), then run this again."
        say "Installing Job-o-Matic with pip: python3 -m pip install --user --upgrade $PKG"
        python3 -m pip install --user --upgrade "$PKG" \
            || fail "pip could not install $PKG. If it says \"externally-managed-environment\", install uv (https://docs.astral.sh/uv/) and run this again."
        BIN_DIR="$(python3 -m site --user-base)/bin"
    fi

    if command -v job-o-matic >/dev/null 2>&1; then
        CMD=$(command -v job-o-matic)
    elif [ -x "$BIN_DIR/job-o-matic" ]; then
        CMD="$BIN_DIR/job-o-matic"
        say "Tip: add $BIN_DIR to your PATH so you can type job-o-matic in a terminal."
    else
        fail "installed, but the job-o-matic command was not found in $BIN_DIR."
    fi

    say "Starting Job-o-Matic: $CMD --open"
    nohup "$CMD" --open >/dev/null 2>&1 &
    say "Done. Job-o-Matic opens in your browser and is in your app menu from now on."
}

main "$@"
