"""Personal app state kept by Qt in ~/.config/bag-catalog/bag-catalog.conf: open folders, hidden
columns and the colour scheme. Shareable settings live in profile files instead (profile.py)."""
from PySide6.QtCore import QSettings


def store():
    return QSettings("bag-catalog", "bag-catalog")


def saved_list(key):
    value = store().value(key, [])
    return [value] if isinstance(value, str) else list(value or [])


def saved_roots():
    return saved_list("roots")


def saved_theme():
    """'auto', 'light' or 'dark', as chosen in Settings."""
    return store().value("theme", "auto")


def take_legacy_settings():
    """{(section, key): value} for the gap threshold and thumbnail cameras that earlier versions kept
    here; they now live in the profile file, so they are removed from here."""
    s, out = store(), {}
    if s.contains("thumb_cameras"):
        out["thumbnails", "cameras"] = saved_list("thumb_cameras")
    for key, name in (("gap_factor", "factor"), ("gap_min_s", "min_s")):
        try:
            if s.contains(key):
                out["gaps", name] = float(s.value(key))
        except (TypeError, ValueError):
            pass
    for key in ("thumb_cameras", "gap_factor", "gap_min_s"):
        s.remove(key)
    return out
