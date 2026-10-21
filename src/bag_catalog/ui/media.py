"""Camera thumbnail view, and decoding of thumbnail jobs into images."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme
from .common import scaled_font

RADIUS = 8


def qimage_from_job(res):
    if res["kind"] == "compressed":
        img = QImage()
        img.loadFromData(res["data"])
        return img
    fmt = {"rgb8": QImage.Format_RGB888, "bgr8": QImage.Format_BGR888, "mono8": QImage.Format_Grayscale8,
           "rgba8": QImage.Format_RGBA8888, "bgra8": QImage.Format_ARGB32}.get(res["encoding"])
    if fmt is None:
        return QImage()
    return QImage(res["data"], res["w"], res["h"], res["step"], fmt).copy()


class ThumbView(QWidget):
    """Image fitted into the widget with rounded corners and a caption pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm, self.text, self.caption = None, "", ""
        self.setMinimumSize(300, 170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def show_image(self, path, text, caption="", tip=""):
        pm = QPixmap(path) if path else None
        self.pm = pm if pm and not pm.isNull() else None
        self.text, self.caption = text, caption
        self.setToolTip(tip if self.pm else "")
        self.update()

    def paintEvent(self, _):
        t = theme.current
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        if not self.pm:
            frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QPen(t.c("border"), 1))
            p.setBrush(t.c("surface_alt"))
            p.drawRoundedRect(frame, RADIUS, RADIUS)
            p.setPen(t.c("muted"))
            p.drawText(self.rect().adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, self.text)
            return
        size = self.pm.size().scaled(self.size(), Qt.KeepAspectRatio)
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(QRectF(self.rect()).center())
        clip = QPainterPath()
        clip.addRoundedRect(target, RADIUS, RADIUS)
        p.setClipPath(clip)
        p.drawPixmap(target, self.pm, QRectF(self.pm.rect()))
        p.setClipping(False)
        if self.caption:
            font = scaled_font(self.font(), 0.8)
            fm = QFontMetrics(font)
            r = QRectF(0, 0, fm.horizontalAdvance(self.caption) + 14, fm.height() + 6)
            r.moveBottomLeft(target.bottomLeft() + QPointF(8, -8))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(r, Qt.AlignCenter, self.caption)
