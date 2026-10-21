"""Line icons (24x24 stroke paths) rendered in any colour, plus the app icon."""
import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

APP_ICON = os.path.join(os.path.dirname(__file__), "resources", "icon.svg")

_PATHS = {
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3.5V8h4.5"/>'
               '<path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20.5V16h-4.5"/>',
    "export": '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
    "folder": '<path d="M3.5 7A1.5 1.5 0 0 1 5 5.5h4l2 2.5h8A1.5 1.5 0 0 1 20.5 9.5v8'
              'a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
    "close": '<path d="M17 7 7 17M7 7l10 10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "gap": '<path d="M3 12h5M16 12h5"/><path d="M10 7v10M14 7v10"/>',
    "columns": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M9.5 4.5v15M14.5 4.5v15"/>',
    "expand": '<path d="m6 9 6 6 6-6"/>',  # same chevrons as the tree rows
    "collapse": '<path d="m9 6 6 6-6 6"/>',
    "star": '<path d="m12 3.5 2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.75 1-5.8L3.5 9.7l5.9-.9z"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/>'
            '<path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/>',
    "play": '<path d="M7.5 5v14l11-7z"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
}


def _render(renderer, size, dpr):
    """What `renderer` draws, as a size × size pixmap that stays sharp on screens scaled by `dpr`."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)  # from here on, painting is in on-screen units
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pm


def _line_svg(name, color, fill):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{fill}" stroke="{color}" '
            f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>')


def pixmap(name, color, size=16, dpr=2.0, fill="none"):
    """The line icon `name`, stroked in `color` (and filled with `fill`)."""
    return _render(QSvgRenderer(QByteArray(_line_svg(name, color, fill).encode())), size, dpr)


def icon(name, color, size=16, fill="none"):
    """The line icon `name` as a QIcon, with versions for normal and high-resolution screens."""
    ic = QIcon()
    for dpr in (1.0, 2.0):
        ic.addPixmap(pixmap(name, color, size, dpr, fill))
    return ic


def app_pixmap(size, dpr=2.0):
    """The app's logo."""
    return _render(QSvgRenderer(APP_ICON), size, dpr)
