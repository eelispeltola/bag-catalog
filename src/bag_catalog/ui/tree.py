"""The recordings table: a tree with a custom header, row painting and per-column cell painting.

Cells carry their content in data roles (see below) and RowDelegate paints them, so the
look follows the current theme without repopulating.
"""
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame, QHeaderView, QStyle, QStyledItemDelegate, QToolTip, QTreeWidget, QTreeWidgetItem,
)

from .. import theme
from ..fmt import fmt_clock, fmt_date
from ..model import sensor_label
from .common import caption_font, draw_chevron, draw_kind, draw_star, draw_status, scaled_font

COL_NAME, COL_START, COL_DUR, COL_DIST, COL_SIZE, COL_MSGS, COL_TIMELINE = range(7)
FIXED_HEADERS = ["Recording / bag", "Start", "Duration", "Distance", "Size", "Messages", "Timeline"]
NUMERIC = {COL_DUR, COL_DIST, COL_SIZE, COL_MSGS}
SORT_ROLE = Qt.UserRole + 1
SPAN_ROLE = Qt.UserRole + 2    # [(start, end), ...] as fractions of the recording
OBJ_ROLE = Qt.UserRole + 3     # the Bag or Recording of the row
REC_ROLE = Qt.UserRole + 4     # the row's Recording
STATUS_ROLE = Qt.UserRole + 5  # sensor columns: 'ok' | 'partial' | 'empty' | '' (absent)
CHIPS_ROLE = Qt.UserRole + 6   # notes column: [(text, tone)], tone in neutral | accent | error
TONE_ROLE = Qt.UserRole + 7    # theme token for the text colour (default 'text')
PREFIX_ROLE = Qt.UserRole + 8  # name column: muted label drawn before the name (the row's folder)
FAV_ROLE = Qt.UserRole + 9     # name column of recording rows: favorite star (True / False)
STAR_SLOT = 20                 # px reserved for the star before the name
GAPS_ROLE = Qt.UserRole + 10   # sensor columns: True if any of the sensor's topics has gaps
ROW_HEIGHT = 30
SENSOR_WIDTH = 32  # px per sensor column
SENSOR_BOTTOM = 20  # header space below the slanted sensor names, for the kind marker
LABEL_START, LABEL_LIFT = 6, 2  # where slanted names start: px along the slant / above SENSOR_BOTTOM


class SortItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(col, SORT_ROLE), other.data(col, SORT_ROLE)
        if a is None or b is None:
            return (a is None) > (b is None)
        return a < b


class CatalogHeader(QHeaderView):
    """Small-caps labels for the fixed columns; 45° slanted names + kind marker for sensor columns.

    Slanted labels extend over their right-hand neighbours, so hover, clicks and tooltips are
    resolved along the slant (section_at) rather than by x alone.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.sensors, self.required = [], set()
        self.first_sensor = len(FIXED_HEADERS)
        self._hover = -1
        self._pressed = None
        self._height = 64
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setMouseTracking(True)
        self.setMinimumSectionSize(24)
        self.setStretchLastSection(True)

    def leaf_font(self):
        return scaled_font(self.font(), 1.0, QFont.DemiBold)

    def parent_font(self):
        return scaled_font(self.font(), 0.94)

    def label_width(self, s):
        parent, leaf = sensor_label(s)
        return (QFontMetrics(self.parent_font()).horizontalAdvance(parent + "/" if parent else "")
                + QFontMetrics(self.leaf_font()).horizontalAdvance(leaf))

    def set_sensors(self, sensors, required):
        self.sensors, self.required = sensors, required
        shown = [s for i, s in enumerate(sensors) if not self.isSectionHidden(self.first_sensor + i)]
        need = (max([self.label_width(s) for s in shown] or [0]) + LABEL_START) / math.sqrt(2)
        self._height = max(64, min(200, math.ceil(need) + SENSOR_BOTTOM + LABEL_LIFT + 6))
        self.updateGeometry()
        self.viewport().update()

    def is_sensor(self, logical):
        return 0 <= logical - self.first_sensor < len(self.sensors)

    def section_at(self, pos):
        """Logical section under pos, following the 45° bands above the sensor columns."""
        raw = self.logicalIndexAt(pos.x())
        yb = self.height() - SENSOR_BOTTOM
        if pos.y() >= yb:
            return raw
        slanted = self.logicalIndexAt(round(pos.x() - (yb - pos.y())))
        if self.is_sensor(slanted):
            return slanted
        return -1 if self.is_sensor(raw) else raw

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), self._height)

    # -- mouse: sensor bands toggle the filter, everything else behaves like a normal header
    def mouseMoveEvent(self, e):
        idx = self.section_at(e.position().toPoint())
        if idx != self._hover:
            self._hover = idx
            self.setCursor(Qt.PointingHandCursor if self.is_sensor(idx) else Qt.ArrowCursor)
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:  # right-click opens the columns menu
            self._pressed = None
            super().mousePressEvent(e)
            return
        pos = e.position().toPoint()
        idx, raw = self.section_at(pos), self.logicalIndexAt(pos.x())
        if self.is_sensor(idx) or self.is_sensor(raw) or idx != raw:
            self._pressed = idx
            e.accept()
            return
        self._pressed = None
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pressed is None:
            super().mouseReleaseEvent(e)
            return
        idx = self.section_at(e.position().toPoint())
        if idx == self._pressed and self.is_sensor(idx):
            self.sectionClicked.emit(idx)
        self._pressed = None
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if not self.is_sensor(self.section_at(e.position().toPoint())):
            super().mouseDoubleClickEvent(e)

    def viewportEvent(self, e):
        if e.type() == QEvent.ToolTip:
            idx = self.section_at(e.pos())
            tip = self.model().headerData(idx, Qt.Horizontal, Qt.ToolTipRole) if idx >= 0 else None
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(e)

    # -- painting
    def paintSection(self, p, rect, logical):
        t = theme.current
        p.save()
        p.setClipRect(rect)
        p.fillRect(rect, t.c("surface"))
        if self.is_sensor(logical):
            draw_kind(p, QPointF(rect.center().x() + 0.5, rect.bottom() - 9), self.sensors[logical - self.first_sensor][0])
        else:
            self._paint_fixed(p, rect, logical)
        p.setPen(t.c("border"))
        p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        p.restore()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.sensors:
            p = QPainter(self.viewport())
            self._paint_slanted(p)
            p.end()

    def _paint_fixed(self, p, rect, logical):
        t = theme.current
        text = str(self.model().headerData(logical, Qt.Horizontal) or "").upper()
        sorted_here = self.isSortIndicatorShown() and self.sortIndicatorSection() == logical
        font = caption_font()
        fm = QFontMetrics(font)
        r = rect.adjusted(10, 0, -10, -9)
        right = logical in NUMERIC
        p.setFont(font)
        p.setPen(t.c("text" if sorted_here else "muted"))
        p.drawText(r, Qt.AlignBottom | (Qt.AlignRight if right else Qt.AlignLeft), text)
        if sorted_here:
            w = fm.horizontalAdvance(text)
            x = r.right() - w - 9 if right else r.left() + w + 9
            down = self.sortIndicatorOrder() == Qt.DescendingOrder
            draw_chevron(p, QPointF(x, r.bottom() - fm.ascent() / 2 + 1), "down" if down else "up", 3.2,
                         t.c("accent"), 1.5)

    def _paint_slanted(self, p):
        t = theme.current
        p.setRenderHint(QPainter.Antialiasing)
        yb = self.height() - SENSOR_BOTTOM
        h = yb - 2
        cols = [self.first_sensor + i for i in range(len(self.sensors))
                if not self.isSectionHidden(self.first_sensor + i)]
        if not cols:
            return
        # band fills for the hovered / filtered sensors
        for li in cols:
            s = self.sensors[li - self.first_sensor]
            fill = t.soft("accent") if s in self.required else (t.c("surface_alt") if li == self._hover else None)
            if fill is None:
                continue
            x0 = self.sectionViewportPosition(li)
            x1 = x0 + self.sectionSize(li)
            band = QPolygonF([QPointF(x0, self.height() - 1), QPointF(x0, yb), QPointF(x0 + h, yb - h),
                              QPointF(x1 + h, yb - h), QPointF(x1, yb), QPointF(x1, self.height() - 1)])
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPolygon(band)
            draw_kind(p, QPointF((x0 + x1) / 2 + 0.5, self.height() - 10), s[0])
        # labels along the bands
        pf, lf = self.parent_font(), self.leaf_font()
        pfm, lfm = QFontMetrics(pf), QFontMetrics(lf)
        avail = (yb - LABEL_LIFT - 6) * math.sqrt(2) - LABEL_START
        for li in cols:
            s = self.sensors[li - self.first_sensor]
            req = s in self.required
            parent, leaf = sensor_label(s)
            prefix = parent + "/" if parent else ""
            leaf = lfm.elidedText(leaf, Qt.ElideMiddle, int(avail))
            room = avail - lfm.horizontalAdvance(leaf)
            if prefix and pfm.horizontalAdvance(prefix) > room:
                prefix = pfm.elidedText(parent, Qt.ElideMiddle, max(0, int(room - pfm.horizontalAdvance("/")))) + "/"
            cx = self.sectionViewportPosition(li) + self.sectionSize(li) / 2
            p.save()
            p.translate(cx, yb - LABEL_LIFT)
            p.rotate(-45)
            y = (lfm.ascent() - lfm.descent()) / 2
            x = float(LABEL_START)
            if prefix:
                p.setFont(pf)
                p.setPen(t.c("accent" if req else "muted"))
                p.drawText(QPointF(x, y), prefix)
                x += pfm.horizontalAdvance(prefix)
            p.setFont(lf)
            p.setPen(t.c("accent" if req else "text"))
            p.drawText(QPointF(x, y), leaf)
            p.restore()


class RowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(super().sizeHint(option, index).width(), ROW_HEIGHT)

    def paint(self, p, opt, idx):
        t = theme.current
        p.save()
        if opt.state & QStyle.State_Selected:
            p.fillRect(opt.rect, t.selection())
        elif opt.state & QStyle.State_MouseOver:
            p.fillRect(opt.rect, t.c("surface_alt"))
        font = idx.data(Qt.FontRole) or opt.font
        p.setFont(font)
        status, chips = idx.data(STATUS_ROLE), idx.data(CHIPS_ROLE)
        if status is not None:
            draw_status(p, QPointF(opt.rect.center().x() + 0.5, opt.rect.center().y() + 0.5), status,
                        gaps=bool(status) and bool(idx.data(GAPS_ROLE)))
        elif chips is not None:
            self._chips(p, opt.rect, chips)
        elif idx.column() == COL_TIMELINE:
            self._timeline(p, opt.rect, idx.data(SPAN_ROLE), idx.parent().isValid())
        elif idx.column() == COL_START:
            self._start(p, opt.rect, idx.data(SORT_ROLE), font)
        else:
            text = idx.data(Qt.DisplayRole)
            if text:
                r = opt.rect.adjusted(4 if idx.column() == COL_NAME else 10, 0, -10, 0)
                align = Qt.AlignVCenter | (Qt.AlignRight if idx.column() in NUMERIC else Qt.AlignLeft)
                fav = idx.data(FAV_ROLE) if idx.column() == COL_NAME else None
                if fav is not None:
                    c = QPointF(r.left() + STAR_SLOT / 2 - 1, r.center().y() + 0.5)
                    if fav:
                        draw_star(p, c, 6.5, True, t.c("partial"))
                    elif opt.state & QStyle.State_MouseOver:
                        draw_star(p, c, 6.5, False, t.c("faint"))
                    r.setLeft(r.left() + STAR_SLOT)
                prefix = idx.data(PREFIX_ROLE) if idx.column() == COL_NAME else None
                if prefix:
                    p.setPen(t.c("muted"))
                    p.drawText(r, align, prefix)
                    r.setLeft(r.left() + QFontMetrics(font).horizontalAdvance(prefix + "  "))
                p.setPen(t.c(idx.data(TONE_ROLE) or "text"))
                p.drawText(r, align, QFontMetrics(font).elidedText(str(text), Qt.ElideRight, r.width()))
        p.restore()

    def _start(self, p, rect, ns, font):
        t = theme.current
        r = rect.adjusted(10, 0, -6, 0)
        if not ns:
            p.setPen(t.c("faint"))
            p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, "—")
            return
        date = fmt_date(ns)
        p.setPen(t.c("muted"))
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, date)
        p.setPen(t.c("text"))
        r.setLeft(r.left() + QFontMetrics(font).horizontalAdvance(date + "  "))
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, fmt_clock(ns))

    def _timeline(self, p, rect, spans, is_bag):
        if not spans:
            return
        t = theme.current
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(rect.left() + 10, rect.center().y() - 2, rect.width() - 20, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(t.c("border"))
        p.drawRoundedRect(track, 2.5, 2.5)
        p.setBrush(t.c("accent") if is_bag else t.c("muted", 0.55))
        for a, b in spans:
            p.drawRoundedRect(QRectF(track.left() + a * track.width(), track.top(),
                                     max(5.0, (b - a) * track.width()), track.height()), 2.5, 2.5)

    def _chips(self, p, rect, chips):
        t = theme.current
        font = caption_font(7.6)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 0.2)
        fm = QFontMetrics(font)
        p.setFont(font)
        p.setRenderHint(QPainter.Antialiasing)
        x, h = rect.left() + 8, 18
        y = rect.center().y() - h / 2 + 0.5
        for text, tone in chips:
            w = fm.horizontalAdvance(text) + 14
            if x + w > rect.right() - 4:
                break
            box = QRectF(x, y, w, h)
            if tone == "neutral":
                bg, edge, fg = t.c("surface_alt"), t.c("border"), t.c("muted")
            elif tone == "warn":
                fg = t.c("partial") if t.dark else t.c("partial").darker(140)
                bg, edge = t.soft("partial", 0.18 if t.dark else 0.1), t.soft("partial", 0.55)
            elif tone == "note":  # sticky-note yellow
                bg, edge, fg = t.soft("partial", 0.26 if t.dark else 0.16), t.soft("partial", 0.55), t.c("text")
            else:
                key = "accent" if tone == "accent" else "empty"
                bg, edge, fg = t.soft(key), t.soft(key, 0.45), t.c(key)
            p.setPen(QPen(edge, 1))
            p.setBrush(bg)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), h / 2, h / 2)
            p.setPen(fg)
            p.drawText(box, Qt.AlignCenter, text)
            x += w + 5


class CatalogTree(QTreeWidget):
    starClicked = Signal(object)  # the item whose favorite star was clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeader(CatalogHeader(self))
        self.setItemDelegate(RowDelegate(self))
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setIndentation(20)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def star_item(self, pos):
        """The item whose star is under `pos`, if any."""
        idx = self.indexAt(pos)
        if not idx.isValid() or idx.column() != COL_NAME or idx.data(FAV_ROLE) is None:
            return None
        left = self.visualRect(idx).left()
        return self.itemFromIndex(idx) if left <= pos.x() <= left + 4 + STAR_SLOT else None

    def mousePressEvent(self, e):
        item = self.star_item(e.position().toPoint()) if e.button() == Qt.LeftButton else None
        if item is not None:
            self.starClicked.emit(item)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.star_item(e.position().toPoint()) is None:
            super().mouseDoubleClickEvent(e)

    def drawRow(self, p, opt, idx):
        super().drawRow(p, opt, idx)
        if not idx.parent().isValid() and idx.row() > 0:  # hairline between recordings
            p.save()
            p.setPen(theme.current.c("border"))
            p.drawLine(0, opt.rect.top(), self.viewport().width(), opt.rect.top())
            p.restore()

    def drawBranches(self, p, rect, idx):
        t = theme.current
        if self.selectionModel().isSelected(idx):
            p.fillRect(rect, t.selection())
        else:
            h = self.indexAt(self.viewport().mapFromGlobal(QCursor.pos()))
            if h.isValid() and h.row() == idx.row() and h.parent() == idx.parent():
                p.fillRect(rect, t.c("surface_alt"))
        if self.model().hasChildren(idx):
            c = QPointF(rect.right() - self.indentation() / 2 + 3, rect.center().y() + 0.5)
            draw_chevron(p, c, "down" if self.isExpanded(idx) else "right", 3.2, t.c("muted"), 1.5)
