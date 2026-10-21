"""Route preview: GNSS tracks on OpenStreetMap tiles, or dead-reckoned paths on a grid."""
import hashlib
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme
from ..config import CACHE_DIR, TILE_ATTRIBUTION, TILE_URL, USER_AGENT
from ..extract import track_distance
from ..fmt import fmt_dist
from .common import scaled_font

RADIUS = 8


def fetch_tile(url, key):
    req = urllib.request.Request(url.format(z=key[0], x=key[1], y=key[2]), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except OSError:
        return None


class TileCache(QObject):
    """Map tiles (OpenStreetMap unless a profile says otherwise): memory -> disk cache -> network
    (max 2 parallel, per OSM policy)."""
    updated = Signal()
    fetched = Signal(object, object, object)  # url, key, bytes or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.url = None
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.fetched.connect(self._done)
        self.set_source(TILE_URL, TILE_ATTRIBUTION)

    def set_source(self, url, attribution):
        self.attribution = attribution
        if url == self.url:
            return
        self.url = url
        sub = "tiles" if url == TILE_URL else "tiles-" + hashlib.sha1(url.encode()).hexdigest()[:10]
        self.dir = os.path.join(CACHE_DIR, sub)
        self.mem, self.queue, self.inflight, self.failed = {}, [], set(), set()
        self.updated.emit()

    def get(self, z, x, y):
        key = (z, x, y)
        if key in self.mem:
            return self.mem[key]
        f = os.path.join(self.dir, str(z), str(x), f"{y}.png")
        if os.path.exists(f):
            pm = QPixmap(f)
            if not pm.isNull():
                self.mem[key] = pm
                return pm
        if key not in self.inflight and key not in self.failed and key not in self.queue:
            self.queue.append(key)
            self._pump()
        return None

    def _pump(self):
        while self.queue and len(self.inflight) < 2:
            key = self.queue.pop()  # newest first: the tiles currently on screen
            self.inflight.add(key)
            self.pool.submit(fetch_tile, self.url, key).add_done_callback(
                lambda f, u=self.url, k=key: self.fetched.emit(u, k, f.result()))

    def _done(self, url, key, data):
        if url != self.url:
            return  # requested before the tile source changed
        self.inflight.discard(key)
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.mem[key] = pm
            f = os.path.join(self.dir, str(key[0]), str(key[1]), f"{key[2]}.png")
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb") as fh:
                fh.write(data)
            self.updated.emit()
        else:
            self.failed.add(key)
        self._pump()


def world_px(lat, lon, z):
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


class MapView(QWidget):
    def __init__(self, tiles, parent=None):
        super().__init__(parent)
        self.tiles = tiles
        tiles.updated.connect(self.update)
        self.track = None
        self.window = None
        self.message = ""
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def show_track(self, track, window=None, message=""):
        self.track, self.window, self.message = track, window, message
        tip = ""
        if track and track.get("source"):
            tip = (f"Path from {track['topic']}" + (" (dead-reckoned, not georeferenced)"
                                                    if track["source"] == "odom" else "")
                   + (f"\nin {os.path.basename(track['bag'])}" if track.get("bag") else "")
                   + ("\nClick to open in OpenStreetMap" if track["source"] == "gnss" else ""))
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor if track and track.get("source") == "gnss" else Qt.ArrowCursor)
        self.update()

    def mousePressEvent(self, e):
        if self.track and self.track.get("source") == "gnss":
            pts = self.selected()
            lat = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
            lon = (min(p[2] for p in pts) + max(p[2] for p in pts)) / 2
            QDesktopServices.openUrl(QUrl(f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}"
                                          f"#map=16/{lat:.6f}/{lon:.6f}"))

    def selected(self):
        pts = self.track["pts"]
        if self.window:
            sel = [p for p in pts if self.window[0] <= p[0] <= self.window[1]]
            if len(sel) >= 2:
                return sel
        return pts

    def paintEvent(self, _):
        t = theme.current
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(frame, RADIUS, RADIUS)
        p.setClipPath(clip)
        p.fillRect(self.rect(), t.c("surface_alt"))
        if self.track and self.track.get("source"):
            self._paint_track(p)
        else:
            p.setPen(t.c("muted"))
            p.drawText(self.rect().adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
        p.setClipping(False)
        p.setPen(QPen(t.c("border"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(frame, RADIUS, RADIUS)

    def _paint_track(self, p):
        t = theme.current
        W, H, margin = self.width(), self.height(), 22
        bottom = 40  # keep the route clear of the distance label
        fit_h, mid_y = H - margin - bottom, (margin + H - bottom) / 2
        sel, allpts = self.selected(), self.track["pts"]
        gnss = self.track["source"] == "gnss"
        if gnss:
            la = [q[1] for q in sel]
            lo = [q[2] for q in sel]
            z = 18
            while z > 1:
                x0, y0 = world_px(max(la), min(lo), z)
                x1, y1 = world_px(min(la), max(lo), z)
                if x1 - x0 <= W - 2 * margin and y1 - y0 <= fit_h:
                    break
                z -= 1
            ox, oy = (x0 + x1) / 2 - W / 2, (y0 + y1) / 2 - mid_y
            n = 2 ** z
            for tx in range(int(ox // 256), int((ox + W) // 256) + 1):
                for ty in range(int(oy // 256), int((oy + H) // 256) + 1):
                    if 0 <= ty < n:
                        pm = self.tiles.get(z, tx % n, ty)
                        if pm:
                            p.drawPixmap(int(tx * 256 - ox), int(ty * 256 - oy), pm)
            if t.dark:
                p.fillRect(self.rect(), QColor(10, 12, 16, 90))

            def proj(q):
                x, y = world_px(q[1], q[2], z)
                return QPointF(x - ox, y - oy)
        else:
            xs = [q[1] for q in sel]
            ys = [q[2] for q in sel]
            w, h = max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0)
            k = min((W - 2 * margin) / w, fit_h / h)
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            bar_m = next((s for s in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000) if s * k >= 40), 10000)
            step = bar_m * k / 2
            p.setPen(QPen(t.c("border"), 1))
            gx = (W / 2 - cx * k) % step
            while gx < W:
                p.drawLine(QPointF(gx, 0), QPointF(gx, H))
                gx += step
            gy = (mid_y + cy * k) % step
            while gy < H:
                p.drawLine(QPointF(0, gy), QPointF(W, gy))
                gy += step

            def proj(q):
                return QPointF(W / 2 + (q[1] - cx) * k, mid_y - (q[2] - cy) * k)

            p.setPen(QPen(t.c("text"), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(12, 14), QPointF(12 + bar_m * k, 14))
            p.setFont(scaled_font(self.font(), 0.85))
            p.drawText(QPointF(12, 30), fmt_dist(bar_m))

        def poly(pts):
            path = QPainterPath(proj(pts[0]))
            for q in pts[1:]:
                path.lineTo(proj(q))
            return path

        if sel is not allpts:
            p.setPen(QPen(t.c("muted", 0.8), 2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(poly(allpts))
        route = poly(sel)
        p.setPen(QPen(QColor(255, 255, 255, 230), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(route)
        p.setPen(QPen(t.c("track"), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(route)
        for q, key in ((sel[0], "ok"), (sel[-1], "empty")):
            p.setPen(QPen(Qt.white, 2))
            p.setBrush(t.c(key))
            p.drawEllipse(proj(q), 5.5, 5.5)

        dist = fmt_dist(track_distance(self.track, sel[0][0], sel[-1][0]))
        self._pill(p, f"{dist}  ·  {'GNSS' if gnss else 'dead-reckoned'}", left=True)
        if gnss and self.tiles.attribution:
            self._pill(p, self.tiles.attribution, left=False, small=True)

    def _pill(self, p, text, left, small=False):
        t = theme.current
        font = scaled_font(self.font(), 0.78 if small else 0.9)
        fm = QFontMetrics(font)
        r = QRectF(0, 0, fm.horizontalAdvance(text) + 14, fm.height() + 6)
        r.moveBottom(self.height() - 8)
        if left:
            r.moveLeft(8)
        else:
            r.moveRight(self.width() - 8)
        bg = t.c("surface", 0.92)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(font)
        p.setPen(t.c("muted" if small else "text"))
        p.drawText(r, Qt.AlignCenter, text)
