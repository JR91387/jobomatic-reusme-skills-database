import os

# Tests must never add a real app-menu entry to the machine running them.
os.environ["JOBOMATIC_NO_SHORTCUT"] = "1"
