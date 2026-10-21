"""Bags, recordings and sensors, read from rosbag2 metadata.yaml files only (no ROS needed)."""
import os
from dataclasses import dataclass, field

import yaml

from .config import GNSS_TYPES, IMAGE_TYPES, MERGED_MARKER, ODOM_TYPES, SENSOR_RULES, THUMB_SENSORS
from .notes import NOTES_FILE, read_notes

KIND_ORDER = {"camera": 0, "pointcloud": 1, "other": 2}
KIND_LABEL = {"camera": "Camera", "pointcloud": "Lidar / point cloud", "other": "Other"}


# The name lists the functions below take default to config.py; a profile (profile.py) can replace them.
def sensor_of(topic, msg_type, rules=SENSOR_RULES):
    """Topic -> (kind, sensor name), e.g. /camera/image_raw/compressed -> ('camera', 'camera')."""
    segs = [s for s in topic.strip("/").split("/") if s and s not in rules["ignored_segments"]] or ["(root)"]
    if msg_type in rules["camera_types"] or msg_type in rules["pointcloud_types"]:
        camera = msg_type in rules["camera_types"]
        kind, tail = ("camera", rules["camera_suffixes"]) if camera else ("pointcloud", rules["pointcloud_suffixes"])
        while len(segs) > 1 and segs[-1] in tail:
            segs.pop()
        name = "/".join(segs)
    else:
        kind, name = "other", segs[0]
    return kind, rules["aliases"].get(name, name)


def sensor_label(sensor):
    """('camera', 'stereo/left') -> ('stereo', 'left')."""
    parent, _, leaf = sensor[1].rpartition("/")
    return parent, leaf


@dataclass
class Topic:
    name: str
    type: str
    count: int
    sensor: tuple


@dataclass
class Bag:
    path: str
    name: str
    start_ns: int = 0
    duration_ns: int = 0
    message_count: int = 0
    size: int = 0
    storage: str = ""
    mtime: float = 0.0
    topics: list = field(default_factory=list)
    extras: list = field(default_factory=list)
    error: str = ""
    merged_from: list = field(default_factory=list)  # names of the bags whose messages this one holds (merged_bags)

    @property
    def end_ns(self):
        return self.start_ns + self.duration_ns

    @property
    def merged(self):
        """Made by merging other bags: named so, or found holding the messages of others in its folder."""
        return MERGED_MARKER in self.name or bool(self.merged_from)

    def sensors(self):
        """sensor -> 'ok' | 'partial' | 'empty' based on message counts of its topics."""
        out = {}
        for s in {t.sensor for t in self.topics}:
            counts = [t.count for t in self.topics if t.sensor == s]
            out[s] = "ok" if all(counts) else ("empty" if not any(counts) else "partial")
        return out

    def thumb_topic(self, cameras=THUMB_SENSORS, image_types=IMAGE_TYPES):
        """Image topic with messages from the first of `cameras` (sensor names) the bag has, or None."""
        for name in cameras:
            for t in self.topics:
                if t.sensor == ("camera", name) and t.type in image_types and t.count:
                    return t
        return None


@dataclass
class Recording:
    path: str
    name: str  # relative to its root folder
    bags: list
    root: str = ""
    favorite: bool = False  # these three come from bag_notes.yaml in the recording folder
    notes: str = ""
    notes_error: str = ""

    @property
    def start_ns(self):
        return min((b.start_ns for b in self.bags if b.start_ns), default=0)

    @property
    def end_ns(self):
        return max((b.end_ns for b in self.bags if b.start_ns), default=0)

    def sensors(self):
        out = {}
        rank = {"ok": 2, "partial": 1, "empty": 0}
        for b in self.bags:
            for s, st in b.sensors().items():
                if s not in out or rank[st] > rank[out[s]]:
                    out[s] = st
        return out

    def coverage(self):
        """Merged (start, end) fractions of the recording span that some bag covers."""
        span = max(1, self.end_ns - self.start_ns)
        out = []
        for a, b in sorted(((b.start_ns - self.start_ns) / span, (b.end_ns - self.start_ns) / span)
                           for b in self.bags if b.start_ns):
            if out and a <= out[-1][1] + 1e-3:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    def track_candidates(self, gnss_types=GNSS_TYPES, odom_types=ODOM_TYPES):
        """(bag, storage, topic, type, start_ns) to try for the path: GNSS first, then odom/twist.
        Within a kind, higher-rate topics first; for duplicates (e.g. merged bags) the smallest bag."""
        out, seen = [], set()
        for types in (gnss_types, odom_types):
            opts = sorted((-t.count, b.size, b.path, b.storage, t.name, t.type, b.start_ns)
                          for b in self.bags for t in b.topics if t.type in types and t.count > 1)
            for o in opts:
                if o[4] not in seen:
                    seen.add(o[4])
                    out.append(o[2:])
        return out

    def thumb_bag(self, cameras=THUMB_SENSORS, image_types=IMAGE_TYPES):
        for name in cameras:
            for b in sorted(self.bags, key=lambda b: b.size):
                t = b.thumb_topic(cameras, image_types)
                if t and t.sensor == ("camera", name):
                    return b
        return None


def merged_bags(bags, tolerance_ns=1_000_000):
    """[(merged bag, [the bags it holds])] among bags of one folder, from metadata only. A bag holds
    others when two or more bags lie within its time span, use only its topics, and their message
    counts add up to exactly its own, topic by topic. That is true of bags split by time or by topic
    and then merged, and practically never by chance. Bags named as merged are never parts."""
    def counts(bs):
        out = {}
        for b in bs:
            for t in b.topics:
                if t.count:
                    out[t.name] = out.get(t.name, 0) + t.count
        return out

    found = []
    for m in bags:
        own = counts([m])
        if not m.start_ns or not own:
            continue
        parts = [b for b in bags if b is not m and b.start_ns and MERGED_MARKER not in b.name
                 and b.start_ns >= m.start_ns - tolerance_ns and b.end_ns <= m.end_ns + tolerance_ns
                 and counts([b]).keys() <= own.keys()]
        if len(parts) >= 2 and counts(parts) == own:
            found.append((m, parts))
    return found


BAG_EXTS = (".mcap", ".db3")
SKIP_EXTS = BAG_EXTS + (".yaml",)


def load_bag(path, rules=SENSOR_RULES):
    bag = Bag(path=path, name=os.path.basename(path))
    sizes = {}
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if f == NOTES_FILE or f.startswith(".bag_notes."):
            continue  # (a loose bag's own notes) must not change mtime, which keys the caches
        if os.path.isfile(fp):
            sizes[f] = os.path.getsize(fp)
            bag.mtime = max(bag.mtime, os.path.getmtime(fp))
            if not f.endswith(SKIP_EXTS):
                bag.extras.append(f)
    listed = []
    meta = os.path.join(path, "metadata.yaml")
    if not os.path.exists(meta):
        bag.error = "no metadata.yaml (try `ros2 bag reindex`)"
    else:
        try:
            with open(meta) as fh:
                info = yaml.load(fh, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))["rosbag2_bagfile_information"]
            bag.start_ns = int(info["starting_time"]["nanoseconds_since_epoch"])
            bag.duration_ns = int(info["duration"]["nanoseconds"])
            bag.message_count = int(info.get("message_count", 0))
            bag.storage = info.get("storage_identifier", "")
            listed = [os.path.basename(str(f)) for f in info.get("relative_file_paths") or []]
            for t in info.get("topics_with_message_count", []):
                md = t["topic_metadata"]
                bag.topics.append(Topic(md["name"], md["type"], int(t.get("message_count", 0)),
                                        sensor_of(md["name"], md["type"], rules)))
        except Exception as e:  # noqa: BLE001 - show anything unreadable in the UI
            bag.error = f"metadata error: {e}"
    # the size is the bag's data: the files metadata.yaml lists, else its .mcap / .db3 files; not
    # metadata.yaml itself, notes, backups or anything else lying in the folder
    data = [f for f in listed if f in sizes] or [f for f in sizes if f.endswith(BAG_EXTS)]
    bag.size = sum(sizes[f] for f in data)
    return bag


def scan(root, rules=SENSOR_RULES):
    """Find bag directories (with metadata.yaml or bag files) and group them by parent dir.
    Bags directly in `root` are not grouped: each is its own recording."""
    groups = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        if "metadata.yaml" in filenames or any(f.endswith(BAG_EXTS) for f in filenames):
            groups.setdefault(os.path.dirname(dirpath), []).append(load_bag(dirpath, rules))
            dirnames[:] = []  # don't descend into a bag
    recs = []
    for parent, bags in groups.items():
        if os.path.normpath(parent) == os.path.normpath(root):
            recs += [Recording(b.path, b.name, [b], root) for b in bags]
        else:
            recs.append(Recording(parent, os.path.relpath(parent, root), sorted(bags, key=lambda b: b.name), root))
    for r in recs:
        r.favorite, r.notes, r.notes_error = read_notes(r.path)
    for bags in groups.values():  # by folder, so a loose bag in `root` can be found merged too
        for m, parts in merged_bags(bags):
            m.merged_from = [b.name for b in parts]
    return sorted(recs, key=lambda r: (r.start_ns or 0, r.name))


MAX_ROOTS = 3


def scan_all(roots, rules=SENSOR_RULES):
    """Recordings from several folders, merged by start time. Missing folders are skipped, and a
    bag reachable from two folders (one nested in the other) is listed once, under the first."""
    seen, recs = set(), []
    for root in roots:
        if os.path.isdir(root):
            for r in scan(root, rules):
                r.bags = [b for b in r.bags if b.path not in seen]
                if r.bags:
                    seen.update(b.path for b in r.bags)
                    recs.append(r)
    return sorted(recs, key=lambda r: (r.start_ns or 0, r.name))


def root_labels(roots):
    """Short distinct names for folders: the basename, plus parent components only where names clash."""
    parts = {r: [p for p in os.path.normpath(r).split(os.sep) if p] or [r] for r in roots}
    out = {}
    for r, p in parts.items():
        for n in range(1, len(p) + 1):
            if all(q[-n:] != p[-n:] for o, q in parts.items() if o != r):
                out[r] = "/".join(p[-n:])
                break
        else:
            out[r] = r
    return out
