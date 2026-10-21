"""Background extraction of driven paths and thumbnails.

The job_* functions run in worker processes (spawned, so this module must not import Qt)
and need a ROS 2 environment for rosbag2_py.
"""
import hashlib
import math
import os

from .config import GAP_FACTOR_FLOOR, GAP_MIN_S_FLOOR, GNSS_TYPES

STATS_VERSION = 1
MAX_GAP_CANDIDATES = 5000


def worker_init():
    # rosbag2 logs harmless warnings on every open; errors are returned in job results instead
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)


def _open_reader(path, storage, topic, seek_ns=None):
    import rosbag2_py
    r = rosbag2_py.SequentialReader()
    r.open(rosbag2_py.StorageOptions(uri=path, storage_id=storage), rosbag2_py.ConverterOptions("", ""))
    r.set_filter(rosbag2_py.StorageFilter(topics=[topic]))
    if seek_ns:
        r.seek(seek_ns)
    return r


def _read(reader):
    while reader.has_next():
        _topic, data, t = reader.read_next()
        yield data, t


def cacheable(res):
    """Whether a job result may be cached: successes, and failures that a retry can't change."""
    return not res.get("error") or res.get("permanent", False)


def geo_dist(a, b):
    """Approximate metres between two (lat, lon) points (fine for short segments)."""
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371000 * math.radians(math.hypot(a[0] - b[0], (a[1] - b[1]) * k))


def job_track(candidates, gnss_types=GNSS_TYPES):
    """Return {'source','topic','bag','pts':[[t_ns,a,b],...]} from the first usable candidate.
    gnss: a,b = lat,lon (kept every >=2 m); odom: a,b = x,y metres, dead-reckoned (every >=1 m).
    A candidate that fails (e.g. a message type that isn't installed) doesn't stop the others."""
    errors = []
    for path, storage, topic, typ, _ in candidates:
        gnss = typ in gnss_types
        try:
            pts = _track_points(path, storage, topic, typ, gnss)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{topic}: {type(e).__name__}: {e}")
            continue
        if len(pts) >= 2:
            return {"source": "gnss" if gnss else "odom", "topic": topic, "bag": path, "pts": pts}
    return {"source": None, "pts": [], **({"error": "; ".join(errors)} if errors else {})}


def _track_points(path, storage, topic, typ, gnss):
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    cls = get_message(typ)
    pts = []
    if gnss:
        for data, t in _read(_open_reader(path, storage, topic)):
            m = deserialize_message(data, cls)
            p = (m.latitude, m.longitude)
            if m.status.status < 0 or not all(map(math.isfinite, p)) or p == (0.0, 0.0):
                continue
            if pts:
                d = geo_dist(pts[-1][1:], p)
                if d < 2 or d > 60 * max(1e-3, (t - pts[-1][0]) / 1e9):  # jitter / jumps
                    continue
            pts.append([t, *p])
        return pts
    x = y = h = 0.0
    last = None
    for data, t in _read(_open_reader(path, storage, topic)):
        m = deserialize_message(data, cls)
        tw = m.twist.twist if hasattr(m.twist, "twist") else m.twist
        if last is not None:
            dt_s = (t - last[0]) / 1e9
            if 0 < dt_s < 1.0:
                vx, vy, wz = last[1:]
                h += wz * dt_s
                x += (vx * math.cos(h) - vy * math.sin(h)) * dt_s
                y += (vx * math.sin(h) + vy * math.cos(h)) * dt_s
        last = (t, tw.linear.x, tw.linear.y, tw.angular.z)
        if not pts or math.hypot(x - pts[-1][1], y - pts[-1][2]) >= 1.0:
            pts.append([t, x, y])
    if last is not None and pts and pts[-1][0] != last[0]:
        pts.append([last[0], x, y])
    return pts


def job_thumb(path, storage, topic, typ, start_ns, offset_s):
    """First image at least offset_s into the bag (or the very first, for short bags)."""
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    try:
        cls = get_message(typ)
        for seek in (start_ns + int(offset_s * 1e9), None):
            for data, t in _read(_open_reader(path, storage, topic, seek)):
                m = deserialize_message(data, cls)
                if typ.endswith("CompressedImage"):
                    return {"kind": "compressed", "data": bytes(m.data), "t": t}
                return {"kind": "raw", "data": bytes(m.data), "w": m.width, "h": m.height,
                        "step": m.step, "encoding": m.encoding, "t": t}
        return {"error": "no image messages"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def job_stats(bag_path, start_ns, end_ns, types):
    """Per-topic timing and image size from the bag's MCAP indexes; no ROS or payload decoding.

    Returns {'finalized': bool, 'topics': {topic: {n, t0, t1, median_dt, cand, size?}}}. 'cand' holds
    every [start_ns, length_ns] pause that is a gap under the most sensitive allowed threshold,
    so the threshold can change later without re-reading the bag. A topic with >= 10 messages
    that starts late or stops early also gets a gap at the bag's start or end.
    """
    import numpy as np

    from .mcap_index import IMAGE_SIZE_TYPES, image_size, read_index, read_message
    try:
        files = sorted(f for f in os.listdir(bag_path) if f.endswith(".mcap"))
        if not files:  # e.g. sqlite3 (.db3): nothing to measure, now or on the next run
            return {"error": "not an MCAP bag", "permanent": True}
        times, first, finalized = {}, {}, True
        for name in files:
            path = os.path.join(bag_path, name)
            idx = read_index(path)
            finalized &= idx.finalized
            for topic, ts in idx.times.items():
                times.setdefault(topic, []).append(ts)
            for topic, loc in idx.first.items():
                if topic not in first or loc[0] < first[topic][1][0]:
                    first[topic] = (path, loc)
        topics = {}
        for topic, parts in times.items():
            ts = np.sort(np.concatenate(parts))
            d = np.diff(ts).astype(np.float64)
            med = float(np.median(d)) if len(d) else 0.0
            floor = max(GAP_FACTOR_FLOOR * med, GAP_MIN_S_FLOOR * 1e9)
            cand = [[int(ts[i]), int(d[i])] for i in np.nonzero(d > floor)[0][:MAX_GAP_CANDIDATES]]
            if len(ts) >= 10:
                if int(ts[0]) - start_ns > floor:
                    cand.insert(0, [int(start_ns), int(ts[0]) - start_ns])
                if end_ns - int(ts[-1]) > floor:
                    cand.append([int(ts[-1]), end_ns - int(ts[-1])])
            topics[topic] = {"n": int(len(ts)), "t0": int(ts[0]), "t1": int(ts[-1]), "median_dt": med, "cand": cand}
        for topic, typ in types.items():
            if typ in IMAGE_SIZE_TYPES and topic in first:
                try:
                    size = image_size(typ, read_message(*first[topic]))
                except Exception:  # noqa: BLE001 - resolution is a nice-to-have
                    size = None
                if size:
                    topics[topic]["size"] = list(size)
        return {"finalized": finalized, "topics": topics}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def topic_gaps(stat, factor, min_s):
    """[start_ns, length_ns] gaps of one topic under the given threshold."""
    thr = max(factor * stat["median_dt"], min_s * 1e9)
    return [g for g in stat["cand"] if g[1] > thr]


def merge_gaps(gaps_by_topic):
    """Number of distinct gap periods across topics (overlapping gaps count once)."""
    spans = sorted((g[0], g[0] + g[1]) for gs in gaps_by_topic.values() for g in gs)
    n, end = 0, None
    for a, b in spans:
        if end is None or a > end:
            n += 1
            end = b
        else:
            end = max(end, b)
    return n


def track_distance(track, t0=None, t1=None):
    pts = [p for p in track["pts"] if (t0 is None or p[0] >= t0) and (t1 is None or p[0] <= t1)]
    if track["source"] == "gnss":
        return sum(geo_dist(a[1:], b[1:]) for a, b in zip(pts, pts[1:]))
    return sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(pts, pts[1:]))


def cache_key(*parts):
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:20]
