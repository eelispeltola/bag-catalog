"""Recording notes and favorites, kept in each recording's folder (the parent of its bags) as
bag_notes.yaml. A bag lying directly in an opened folder is its own recording, so its file goes in
the bag folder itself.

The file is plain YAML so that people and other tools can read and edit it too:

    favorite: true
    notes: |
      Front camera fogged up after 5 minutes.
    updated: '2026-10-21T18:40:12'

Keys this module doesn't know are preserved. A file left with no favorite and no notes is deleted.
"""
import datetime as dt
import os

import yaml

from .files import atomic_write

NOTES_FILE = "bag_notes.yaml"
HEADER = "# Recording notes from bag-catalog. Plain YAML: fine to read or edit by hand.\n"
OWN_KEYS = ("favorite", "notes", "updated")


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s,
                                                             style="|" if "\n" in s else None))


def notes_path(folder):
    return os.path.join(folder, NOTES_FILE)


def _load(path):
    with open(path) as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("expected a mapping")
    return data


def read_notes(folder):
    """(favorite, notes, error message or '')."""
    try:
        data = _load(notes_path(folder))
    except FileNotFoundError:
        return False, "", ""
    except (OSError, ValueError, yaml.YAMLError) as e:
        return False, "", f"{NOTES_FILE} unreadable: {e}"
    return bool(data.get("favorite", False)), str(data.get("notes") or "").rstrip(), ""


def write_notes(folder, favorite, notes):
    """Save (atomically) and return '' on success or an error message."""
    path = notes_path(folder)
    notes = notes.rstrip()
    try:
        extra = {k: v for k, v in _load(path).items() if k not in OWN_KEYS}
    except (OSError, ValueError, yaml.YAMLError):
        extra = {}  # missing or unreadable: start over
    try:
        if not favorite and not notes and not extra:
            if os.path.exists(path):
                os.remove(path)
            return ""
        data = {"favorite": bool(favorite), "notes": notes, **extra,
                "updated": dt.datetime.now().isoformat(timespec="seconds")}
        # the temporary file is .bag_notes.yaml.*.tmp, which load_bag() skips
        atomic_write(path, HEADER + yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1000))
        return ""
    except OSError as e:
        return f"Couldn't save {NOTES_FILE}: {e.strerror or e}"
