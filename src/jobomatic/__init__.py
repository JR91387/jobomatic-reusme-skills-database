"""Job-o-Matic. `__version__` is read lazily from jobomatic.version (package metadata, or pyproject.toml in a zip or repo)."""


def __getattr__(name):
    if name == "__version__":
        from jobomatic.version import get_version

        return get_version() or "0+unknown"
    raise AttributeError(name)
