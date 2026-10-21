"""Background extraction of topic statistics, routes and camera frames, with their caches on disk.

The jobs themselves are in extract.py and run in worker processes; this side queues them, keeps
the results, and announces each one so the window can refresh what shows it.
"""
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal

from ..config import CACHE_DIR, HAVE_ROS
from ..extract import STATS_VERSION, cache_key, cacheable, job_stats, job_thumb, job_track, worker_init
from ..files import read_cache, write_cache
from .media import qimage_from_job


class JobRunner(QObject):
    statsReady = Signal(str)  # bag path
    trackReady = Signal(str)  # recording path
    thumbReady = Signal(str)  # bag path
    _finished = Signal(object, object, object)  # generation, key, result: from executor threads to the GUI thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self.topic_stats = {}  # bag path -> job_stats result (absent = pending)
        self.tracks = {}  # recording path -> track dict (absent = pending)
        self.thumbs = {}  # bag path -> thumbnail file path, or "" if failed
        self.generation = 0
        self.executor = None
        self._finished.connect(self._done)

    def stats_of(self, bag):
        """The bag's job_stats result; {} while it is pending."""
        return self.topic_stats.get(bag.path) or {}

    def finalized(self, bag):
        return self.stats_of(bag).get("finalized", True)

    def topic_stat(self, bag, topic):
        return (self.stats_of(bag).get("topics") or {}).get(topic)

    def start(self, recordings, cfg):
        """Load cached results for these recordings; queue extraction for the rest. Results of an
        earlier start() that arrive later are dropped."""
        self.generation += 1
        self.stop()
        self.tracks, self.thumbs, self.topic_stats = {}, {}, {}
        jobs = []
        for rec in recordings:
            for b in rec.bags:
                f = os.path.join(CACHE_DIR, "stats", cache_key(b.path, b.mtime, STATS_VERSION) + ".json")
                cached = read_cache(f)
                if cached is not None:
                    self.topic_stats[b.path] = cached
                else:
                    jobs.append((1.5, ("stats", b.path, f), job_stats,
                                 (b.path, b.start_ns, b.end_ns, {t.name: t.type for t in b.topics})))
        for rec in recordings if HAVE_ROS else []:
            cands = rec.track_candidates(cfg["routes"]["gnss_types"], cfg["routes"]["odom_types"])
            if not cands:
                self.tracks[rec.path] = {"source": None, "pts": []}
                continue
            mt = {b.path: b.mtime for b in rec.bags}
            f = os.path.join(CACHE_DIR, "tracks", cache_key(cands, [mt[c[0]] for c in cands]) + ".json")
            cached = read_cache(f)
            if cached is not None:
                self.tracks[rec.path] = cached
            else:
                jobs.append((0, ("track", rec.path, f), job_track, (cands, cfg["routes"]["gnss_types"])))
        cams, image_types, offset = (cfg["thumbnails"][k] for k in ("cameras", "image_types", "offset_s"))
        for rec in recordings if HAVE_ROS else []:
            first = rec.thumb_bag(cams, image_types)
            for b in rec.bags:
                t = b.thumb_topic(cams, image_types)
                if not t:
                    continue
                f = os.path.join(CACHE_DIR, "thumbs", cache_key(b.path, t.name, b.mtime, offset) + ".jpg")
                if os.path.exists(f):
                    self.thumbs[b.path] = f
                else:  # recording-level thumbnails before the rest
                    jobs.append((1 if b is first else 2, ("thumb", b.path, f), job_thumb,
                                 (b.path, b.storage, t.name, t.type, b.start_ns, offset)))
        if not jobs:
            return
        self.executor = ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1),
                                            mp_context=multiprocessing.get_context("spawn"),
                                            initializer=worker_init)
        gen = self.generation
        for _, key, fn, args in sorted(jobs, key=lambda j: j[0]):
            fut = self.executor.submit(fn, *args)
            fut.add_done_callback(lambda f, k=key: self._finished.emit(
                gen, k, f.result() if not f.cancelled() and not f.exception() else
                {"error": repr(f.exception()) if not f.cancelled() else "cancelled", "source": None, "pts": []}))

    def stop(self):
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None

    def _done(self, gen, key, res):
        if gen != self.generation:
            return
        kind, path, cache_file = key
        if kind in ("stats", "track"):
            if res.get("error"):
                print(f"{'topic stats' if kind == 'stats' else 'track'} {path}: {res['error']}", file=sys.stderr)
            if cacheable(res):
                try:
                    write_cache(cache_file, res)
                except OSError as e:
                    print(f"cache {cache_file}: {e}", file=sys.stderr)
        if kind == "stats":
            self.topic_stats[path] = res
            self.statsReady.emit(path)
        elif kind == "track":
            self.tracks[path] = res
            self.trackReady.emit(path)
        else:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            self.thumbs[path] = ""
            if res.get("error"):
                print(f"thumbnail {path}: {res['error']}", file=sys.stderr)
            else:
                img = qimage_from_job(res)
                if not img.isNull():
                    img.scaledToWidth(min(640, img.width()), Qt.SmoothTransformation).save(cache_file, "JPG", 85)
                    self.thumbs[path] = cache_file
            self.thumbReady.emit(path)
