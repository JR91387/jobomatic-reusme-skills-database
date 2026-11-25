"""The running Job-o-Matic version, for the update check and the app's footer.

pip / uv / pipx installs read the package metadata. A zip or repo checkout has none,
so it reads pyproject.toml (the zip ships it in app/)."""
import importlib.metadata
import tomllib

from jobomatic import paths

DIST_NAME = "job-o-matic"
VERSION = "1.3.0"  # the single source: pyproject.toml and server.json must match (tests/test_updates_c5.py)


def _from_pyproject():
    try:
        with open(paths.PKG.parents[1] / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def get_version():
    """'1.3.0', or None when no version can be found."""
    if not paths.installed():
        found = _from_pyproject()
        if found:
            return found
    try:
        return importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _from_pyproject()
