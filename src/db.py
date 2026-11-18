#!/usr/bin/env python3
"""Read or change the Job-O-Matic database (zip/repo layout). Same as `job-o-matic-db`; see jobomatic/cli.py."""
from pathlib import Path

from jobomatic.cli import run

# Bundle layout: Job-o-Matic/app/src/db.py with Job-o-Matic/my_data/ beside app/.
DEFAULT_DB = Path(__file__).resolve().parents[2] / "my_data" / "jobomatic.db"

if __name__ == "__main__":
    run(DEFAULT_DB)
