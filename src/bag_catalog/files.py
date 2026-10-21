"""Writing files so they are never left half-written, and reading caches that might be."""
import json
import os
import tempfile


def atomic_write(path, text, mode=0o644):
    """Write `text` to `path` through a temporary file in the same folder, so readers (and a crash
    halfway) only ever see the old or the new content. The temporary file is named
    .<name>.*.tmp and removed if writing fails; OSError is raised."""
    folder, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=folder or ".", prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def read_cache(path):
    """Parsed JSON from a cache file, or None if it is missing or unreadable (then it is rebuilt)."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_cache(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, json.dumps(data))
