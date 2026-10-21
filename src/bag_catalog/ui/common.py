"""Small shared pieces: cards, fonts and the glyphs used in the table and legend."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .. import theme


class Card(QFrame):
    """Rounded panel with an optional small-caps title."""

    def __init__(self, title=None, margins=(14, 12, 14, 14), parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(8)
        self.title = None
        if title is not None:
            self.title = QLabel(objectName="cardTitle")
            self.title.setFont(caption_font())
            self.set_title(title)
            self.title_row = QHBoxLayout()  # caption, then any actions added by the owner
            self.title_row.setSpacing(6)
            self.title_row.addWidget(self.title)
            self.title_row.addStretch(1)
            self.lay.addLayout(self.title_row)

    def set_title(self, text):
        self.title.setText(text.upper())


def clear_layout(lay):
    """Remove and delete every widget in a layout, so it can be filled again."""
    while lay.count():
        w = lay.takeAt(0).widget()
        if w:
            w.deleteLater()


def caption_font(size=8.0):
    f = QFont(QApplication.font())
    f.setPointSizeF(size)
    f.setWeight(QFont.DemiBold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.7)
    return f


def scaled_font(base, factor=1.0, weight=None):
    f = QFont(base)
    f.setPointSizeF(base.pointSizeF() * factor)
    if weight is not None:
        f.setWeight(weight)
    return f


def tabular(font):
    """Same font with tabular (fixed-width) digits, so numbers line up in columns."""
    f = QFont(font)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return f


def draw_status(p, c, status, r=5.0, gaps=False):
    """Sensor status glyph: filled = recorded, half = some topics empty, ring = no messages;
    an amber halo marks gaps in the data."""
    t = theme.current
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if gaps:
        p.setPen(QPen(t.c("partial"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r + 2.6, r + 2.6)
    box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    if status == "ok":
        p.setPen(Qt.NoPen)
        p.setBrush(t.c("ok"))
        p.drawEllipse(box)
    elif status == "partial":
        p.setPen(QPen(t.c("partial"), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(box.adjusted(0.8, 0.8, -0.8, -0.8))
        p.setPen(Qt.NoPen)
        p.setBrush(t.c("partial"))
        p.drawPie(box, 90 * 16, 180 * 16)
    elif status == "empty":
        p.setPen(QPen(t.c("empty"), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(box.adjusted(0.8, 0.8, -0.8, -0.8))
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(t.c("faint", 0.45))
        p.drawEllipse(c, 1.6, 1.6)
    p.restore()


def draw_kind(p, c, kind, w=10.0):
    """Short coloured bar marking a sensor kind (camera / pointcloud / other)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(theme.current.c(kind))
    p.drawRoundedRect(QRectF(c.x() - w / 2, c.y() - 1.5, w, 3), 1.5, 1.5)
    p.restore()


def draw_star(p, c, r, filled, color, width=1.3):
    path = QPainterPath()
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.48
        pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(color if filled else Qt.NoBrush)
    p.drawPath(path)
    p.restore()


def draw_chevron(p, c, direction, size, color, width=1.6):
    s = size
    pts = {"right": [(-s / 2, -s), (s / 2, 0), (-s / 2, s)],
           "down": [(-s, -s / 2), (0, s / 2), (s, -s / 2)],
           "up": [(-s, s / 2), (0, -s / 2), (s, s / 2)]}[direction]
    path = QPainterPath(QPointF(c.x() + pts[0][0], c.y() + pts[0][1]))
    for x, y in pts[1:]:
        path.lineTo(c.x() + x, c.y() + y)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.restore()


def glyph_pixmap(draw, w=14, h=14, dpr=2.0):
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    img.setDevicePixelRatio(dpr)
    p = QPainter(img)
    draw(p, QPointF(w / 2, h / 2))
    p.end()
    return QPixmap.fromImage(img)
