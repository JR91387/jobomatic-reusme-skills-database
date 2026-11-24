"""Where Job-o-Matic finds its own files and the person's data.

Two layouts:
- zip or repo checkout: Job-o-Matic/app/src/jobomatic/ with my_data/ beside app/ (unchanged since v0.1).
- pip install: the files ship inside the package under jobomatic/_data/, and data goes to the
  platform's user data folder, or JOBOMATIC_HOME when set.
"""
import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
DATA = PKG / "_data"  # exists only in an installed wheel
_REPO = {
    "db": PKG.parent / "db",
    "web": PKG.parent / "web",
    "templates": PKG.parents[1] / "templates",
    "AI_GUIDE.md": PKG.parents[1] / "docs" / "AI_GUIDE.md",
    "assets": PKG.parents[1] / "assets",  # app icons (zip: app/assets)
}
DB_NAME = "jobomatic.db"
HTML_NAME = "Job-o-Matic (view only).html"


def installed():
    return DATA.is_dir()


def resource(name):
    """One of: db, web, templates, AI_GUIDE.md, assets."""
    return DATA / name if installed() else _REPO[name]


def user_data_dir():
    home = os.environ.get("JOBOMATIC_HOME")
    if home:
        return Path(home).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Job-o-Matic"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Job-o-Matic"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "job-o-matic"


def default_data_dir():
    return user_data_dir() if installed() else PKG.parents[2] / "my_data"


def default_db():
    return default_data_dir() / DB_NAME


def view_html_path(data_dir):
    """The view-only page: beside my_data/ in a zip, inside the data folder when installed."""
    data_dir = Path(data_dir)
    return (data_dir if installed() else data_dir.parent) / HTML_NAME


def ensure_db(db_path):
    """A pip install starts with no database; create a blank one on first run. Zips ship their own."""
    from jobomatic import store

    db_path = Path(db_path)
    if installed() and not db_path.exists():
        store.new_database(db_path)
        return True
    return False
