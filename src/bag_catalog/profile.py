"""Profiles: shareable settings in YAML files.

A profile holds what differs between robots and teams: how topics are grouped into sensor columns,
which message types give routes and camera frames, what counts as a gap, and the map tiles. The
settings are read in layers, each replacing single settings of the ones before:

  1. the built-in defaults (config.py)
  2. bag_catalog.yaml in an open folder, or the nearest folder above it, for everyone who opens it;
     with several open folders, the first one's file wins
  3. your own ~/.config/bag-catalog/profile.yaml, which the Settings page writes. It holds only
     what you changed, so a setting you never touched follows the folder's file.

No Qt here.
"""
import copy
import os
from dataclasses import dataclass, field

import yaml

from .config import (
    GAP_FACTOR, GAP_FACTOR_FLOOR, GAP_MIN_S, GAP_MIN_S_FLOOR, GNSS_TYPES, IMAGE_TYPES, ODOM_TYPES, SENSOR_RULES,
    THUMB_OFFSET_S, THUMB_SENSORS, TILE_ATTRIBUTION, TILE_URL,
)
from .files import atomic_write
from .fmt import home_short

USER_FILE = os.path.expanduser("~/.config/bag-catalog/profile.yaml")
FOLDER_FILE = "bag_catalog.yaml"


def _plain(v):
    return sorted(v) if isinstance(v, (set, frozenset)) else copy.deepcopy(v)


DEFAULTS = {
    "sensors": {k: _plain(v) for k, v in SENSOR_RULES.items()},
    "thumbnails": {"cameras": list(THUMB_SENSORS), "image_types": _plain(IMAGE_TYPES), "offset_s": THUMB_OFFSET_S},
    "routes": {"gnss_types": _plain(GNSS_TYPES), "odom_types": _plain(ODOM_TYPES)},
    "gaps": {"factor": GAP_FACTOR, "min_s": GAP_MIN_S},
    "map": {"tile_url": TILE_URL, "attribution": TILE_ATTRIBUTION},
}

HELP = {
    "sensors": "How topics are grouped into sensor columns.",
    "sensors.camera_types": "Message types whose topics belong to a camera.",
    "sensors.pointcloud_types": "Message types whose topics belong to a lidar / point cloud sensor.",
    "sensors.camera_suffixes": "Trailing topic name parts dropped to get a camera's name\n"
                               "(/camera/image_raw/compressed -> camera).",
    "sensors.pointcloud_suffixes": "Trailing topic name parts dropped to get a lidar's name\n"
                                  "(/lidar/points -> lidar).",
    "sensors.ignored_segments": "Topic name parts left out everywhere (/stereo/driver/left/image -> stereo/left).",
    "sensors.aliases": "Renames sensors, as shown in the column headers. Topics of other kinds are\n"
                       "grouped by their first name part, so this also merges e.g. tf_static into tf.",
    "thumbnails": "The camera frame shown for a recording.",
    "thumbnails.cameras": "Sensor names in order of preference; the first one a recording has images from is used.",
    "thumbnails.image_types": "Message types decoded as images. Types ending in CompressedImage need a\n"
                              "'data' field; others need the fields of sensor_msgs/msg/Image.",
    "thumbnails.offset_s": "Take the first frame this many seconds in, to skip auto-exposure warm-up.",
    "routes": "Where the route and distance come from: GNSS if a recording has it, else odometry.",
    "routes.gnss_types": "Message types with latitude, longitude and status.status, like sensor_msgs/msg/NavSatFix.",
    "routes.odom_types": "Message types with a twist (or twist.twist), dead-reckoned into a path.",
    "gaps": "A gap is a pause in a topic that is longer than both a multiple of its usual interval and a minimum length.",
    "gaps.factor": f"How many times its usual interval between messages a pause must last ({GAP_FACTOR_FLOOR:g} to 50).",
    "gaps.min_s": f"How long a pause must last at least, in seconds ({GAP_MIN_S_FLOOR:g} to 60).",
    "map": "Background map for GNSS routes.",
    "map.tile_url": "Slippy-map tile URL with {z}, {x} and {y}. Respect the tile server's usage policy.",
    "map.attribution": "Credit shown on the map; most tile providers require one.",
}

MINIMUM = {("gaps", "factor"): GAP_FACTOR_FLOOR, ("gaps", "min_s"): GAP_MIN_S_FLOOR, ("thumbnails", "offset_s"): 0.0}
MAXIMUM = {("gaps", "factor"): 50.0, ("gaps", "min_s"): 60.0, ("thumbnails", "offset_s"): 3600.0}


def check(section, key, value):
    """`value` in the type of the default, or ValueError saying what's wrong."""
    default = DEFAULTS[section][key]
    if isinstance(default, float):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("should be a number")
        if value < MINIMUM.get((section, key), value):
            raise ValueError(f"should be at least {MINIMUM[section, key]:g}")
        if value > MAXIMUM.get((section, key), value):
            raise ValueError(f"should be at most {MAXIMUM[section, key]:g}")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError("should be text")
        if key == "tile_url" and not all(f"{{{c}}}" in value for c in "zxy"):
            raise ValueError("should contain {z}, {x} and {y}")
        return value
    if isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("should be a list of names")
        return list(value)
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError("should be a mapping of names, like  old: new")
    return dict(value)


def parse(data, where, errors):
    """The valid settings in `data` (a parsed profile file) as {section: {key: value}}. Unknown or
    invalid ones are left out and described in `errors`."""
    out = {}
    if data is None:
        return out
    if not isinstance(data, dict):
        errors.append(f"{where}: expected sections such as 'sensors:' at the top")
        return out
    for section, keys in data.items():
        if section not in DEFAULTS:
            errors.append(f"{where}: unknown section '{section}'")
        elif keys is not None and not isinstance(keys, dict):
            errors.append(f"{where}: '{section}' should hold settings, like  {section}: {{...}}")
        else:
            for key, value in (keys or {}).items():
                if key not in DEFAULTS[section]:
                    errors.append(f"{where}: unknown setting '{section}.{key}'")
                    continue
                try:
                    out.setdefault(section, {})[key] = check(section, key, value)
                except ValueError as e:
                    errors.append(f"{where}: {section}.{key} {e}")
    return out


def overlay(base, settings):
    """A copy of the full profile `base` with some `settings` ({section: {key: value}}) replaced."""
    out = copy.deepcopy(base)
    for section, keys in settings.items():
        out[section].update(copy.deepcopy(keys))
    return out


def changed(values, base):
    """The settings in `values` that differ from `base`, as {section: {key: value}}."""
    out = {}
    for section, keys in values.items():
        for key, value in keys.items():
            if value != base[section][key]:
                out.setdefault(section, {})[key] = copy.deepcopy(value)
    return out


def folder_file(root):
    """The nearest bag_catalog.yaml in `root` or a folder above it, or None."""
    d = os.path.abspath(root)
    while True:
        f = os.path.join(d, FOLDER_FILE)
        if os.path.isfile(f):
            return f
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


def read(path, errors):
    """Settings in a profile file; {} if it is missing or unreadable (described in `errors`)."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as e:
        errors.append(f"{home_short(path)}: {e}")
        return {}
    return parse(data, home_short(path), errors)


@dataclass
class Layers:
    base: dict  # defaults with the folder files applied: what resetting a setting returns to
    user: dict  # your own settings, only those you changed
    origin: dict = field(default_factory=dict)  # (section, key) -> folder file that set it in base
    used: list = field(default_factory=list)  # files read, in order
    errors: list = field(default_factory=list)

    @property
    def values(self):
        return overlay(self.base, self.user)


def load(roots):
    """All profile layers for these folders."""
    layers = Layers(copy.deepcopy(DEFAULTS), {})
    folders = list(dict.fromkeys(f for f in map(folder_file, roots) if f))
    for f in folders[::-1]:  # the first folder's last, so it wins
        settings = read(f, layers.errors)
        layers.base = overlay(layers.base, settings)
        layers.origin.update({(s, k): f for s, keys in settings.items() for k in keys})
        layers.used.append(f)
    layers.user = read(USER_FILE, layers.errors)
    if os.path.isfile(USER_FILE):
        layers.used.append(USER_FILE)
    return layers


def apply_changes(user, changes, base):
    """Your settings with `changes` ({(section, key): value}) made; a value equal to `base` is dropped,
    so the setting follows the folder's file (or the default) again."""
    out = copy.deepcopy(user)
    for (section, key), value in changes.items():
        if value == base[section][key]:
            out.get(section, {}).pop(key, None)
            if not out.get(section, True):
                del out[section]
        else:
            out.setdefault(section, {})[key] = copy.deepcopy(value)
    return out


def write(path, settings, header):
    """Write settings as a commented profile file (atomically)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write(path, dump(settings, header))


USER_HEADER = ("Your bag-catalog settings: only those you changed from the defaults or the open folder's\n"
               "bag_catalog.yaml. The Settings page rewrites this file, so comments added here are not kept.\n"
               "Edits by hand apply on the next rescan (F5).")
SHARE_HEADER = ("bag-catalog settings. Import them on the Settings page (Profile files), or save this file as\n"
                "bag_catalog.yaml at the top of a bag folder to apply it to everyone who opens that folder.\n"
                "Plain YAML: edit freely; anything left out keeps its built-in default.")


def dump(settings, header=SHARE_HEADER):
    """Settings ({section: {key: value}}, full or partial) as commented YAML."""
    out = [f"# {line}".rstrip() for line in header.splitlines()]
    for section in DEFAULTS:
        keys = settings.get(section)
        if not keys:
            continue
        out += ["", f"# {HELP[section]}", f"{section}:"]
        for key in DEFAULTS[section]:
            if key not in keys:
                continue
            out += [f"  # {line}" for line in HELP[f"{section}.{key}"].splitlines()]
            text = yaml.safe_dump({key: keys[key]}, default_flow_style=False, sort_keys=False, allow_unicode=True,
                                  width=1000)
            out += ["  " + line for line in text.splitlines()]
    return "\n".join(out) + "\n"
