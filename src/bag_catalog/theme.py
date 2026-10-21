"""Colour tokens for light and dark mode, and the Qt palette + stylesheet built from them.

Custom-painted widgets read `theme.current` at paint time, so switching themes only needs
`use()` followed by a repaint.
"""
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


@dataclass(frozen=True)
class Theme:
    dark: bool
    window: str       # app background behind the cards
    surface: str      # cards, tables
    surface_alt: str  # hover, placeholders
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    ok: str
    partial: str
    empty: str
    camera: str       # sensor kinds, keyed like model.KIND_ORDER
    pointcloud: str
    other: str
    track: str

    def c(self, name, alpha=1.0):
        col = QColor(getattr(self, name))
        col.setAlphaF(alpha)
        return col

    def soft(self, name, amount=None):
        """Token blended into the surface colour: an opaque tint for backgrounds."""
        if amount is None:
            amount = 0.22 if self.dark else 0.13
        return mix(QColor(getattr(self, name)), QColor(self.surface), amount)

    def selection(self):
        return self.soft("accent")


def mix(a, b, t):
    """t parts of colour a over (1 - t) parts of b."""
    return QColor.fromRgbF(*(x * t + y * (1 - t) for x, y in zip(a.getRgbF()[:3], b.getRgbF()[:3])))


LIGHT = Theme(
    dark=False, window="#F2F3F5", surface="#FFFFFF", surface_alt="#F6F7F9", border="#E3E5E9",
    text="#1D2025", muted="#667080", faint="#A3AAB5", accent="#E2561F",
    ok="#2F9E55", partial="#D7970A", empty="#D4383E",
    camera="#8A5CF5", pointcloud="#0F9BAE", other="#98A1AC", track="#2368E8",
)
DARK = Theme(
    dark=True, window="#131518", surface="#1B1E23", surface_alt="#23272D", border="#2E333B",
    text="#E7E9EC", muted="#9AA3AF", faint="#5F6772", accent="#F26B38",
    ok="#46C26F", partial="#E8B33A", empty="#F05A5F",
    camera="#A889FA", pointcloud="#3CC6D3", other="#7D8590", track="#4F8DFF",
)

current = LIGHT


def use(theme):
    global current
    current = theme


def detect(override=None):
    if override in ("light", "dark"):
        return DARK if override == "dark" else LIGHT
    return DARK if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT


def palette(t):
    p = QPalette()
    roles = {
        QPalette.Window: t.window, QPalette.WindowText: t.text, QPalette.Base: t.surface,
        QPalette.AlternateBase: t.surface_alt, QPalette.Text: t.text, QPalette.Button: t.surface,
        QPalette.ButtonText: t.text, QPalette.HighlightedText: t.text, QPalette.PlaceholderText: t.faint,
        QPalette.ToolTipBase: t.surface, QPalette.ToolTipText: t.text, QPalette.Link: t.accent,
        QPalette.Accent: t.accent, QPalette.BrightText: "#FFFFFF", QPalette.Light: t.surface,
        QPalette.Midlight: t.surface_alt, QPalette.Mid: t.border, QPalette.Dark: t.border,
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    p.setColor(QPalette.Highlight, t.selection())
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(t.faint))
    return p


def stylesheet(t):
    sel = t.selection().name()
    chip_border = mix(QColor(t.accent), QColor(t.surface), 0.4).name()
    return f"""
QMainWindow, QWidget#central {{ background: {t.window}; }}
QFrame#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; }}
QLabel {{ background: transparent; }}
QLabel#cardTitle, QLabel#muted, QLabel#stats {{ color: {t.muted}; }}

QToolButton {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 8px; padding: 5px 10px;
}}
QToolButton:hover {{ background: {t.surface_alt}; border-color: {t.faint}; }}
QToolButton:pressed {{ background: {t.border}; }}
QToolButton#rootButton {{ background: transparent; border: none; color: {t.muted}; padding: 4px 6px; }}
QToolButton#rootButton:hover {{ background: {t.border}; color: {t.text}; }}
QFrame#folderChip {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; }}
QFrame#folderChip[missing="true"] {{ border-color: {t.empty}; }}
QFrame#folderChip QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 3px 6px; }}
QFrame#folderChip QToolButton:hover {{ background: {t.surface_alt}; }}
QFrame#folderChip[missing="true"] QToolButton#folderButton {{ color: {t.empty}; }}
QToolButton#folderRemove {{ padding: 3px 3px; }}
QToolButton#favButton {{ background: transparent; border: 1px solid transparent; padding: 0 6px; color: {t.muted}; }}
QToolButton#favButton:hover {{ border-color: {t.border}; color: {t.text}; }}
QToolButton#favButton:checked {{ color: {t.text}; }}
QToolButton#filterToggle {{
    background: transparent; border: 1px solid {t.border}; border-radius: 11px; padding: 1px 9px; color: {t.muted};
}}
QToolButton#filterToggle:hover {{ border-color: {t.faint}; color: {t.text}; }}
QToolButton#filterToggle:checked {{
    background: {t.soft("partial", 0.26 if t.dark else 0.16).name()}; border-color: {t.soft("partial", 0.55).name()};
    color: {t.text};
}}
QDoubleSpinBox {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 6px; padding: 3px 6px;
    selection-background-color: {sel}; selection-color: {t.text};
}}
QDoubleSpinBox:focus {{ border-color: {t.accent}; }}
QPlainTextEdit {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px;
    selection-background-color: {sel}; selection-color: {t.text};
}}
QPlainTextEdit:focus {{ border-color: {t.accent}; }}
QPlainTextEdit[readOnly="true"] {{ background: {t.surface_alt}; color: {t.muted}; }}
QToolButton#chip {{
    background: {t.soft("accent").name()}; color: {t.accent}; border: 1px solid {chip_border};
    border-radius: 11px; padding: 1px 9px; font-weight: 600;
}}
QToolButton#chip:hover {{ border-color: {t.accent}; }}
QToolButton#link {{ background: transparent; border: none; color: {t.muted}; padding: 1px 4px; }}
QToolButton#link:hover {{ color: {t.accent}; }}

QLineEdit {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 8px; padding: 5px 6px; selection-background-color: {sel}; selection-color: {t.text};
}}
QLineEdit:hover {{ border-color: {t.faint}; }}
QLineEdit:focus {{ border-color: {t.accent}; }}

QTreeView, QTableView {{ background: {t.surface}; border: none; outline: 0; }}
QHeaderView {{ background: {t.surface}; border: none; }}
QTableView QHeaderView::section {{
    background: {t.surface}; color: {t.muted}; border: none; border-bottom: 1px solid {t.border};
    padding: 4px 8px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {t.surface}; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t.border}; border-radius: 3px; }}
QScrollBar::handle:hover {{ background: {t.faint}; }}
QScrollBar::handle:vertical {{ min-height: 30px; }}
QScrollBar::handle:horizontal {{ min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: {t.window}; color: {t.muted}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 5px 7px; }}
QDialog#settings {{ background: {t.window}; }}
QScrollArea#settingsPage, QWidget#settingsPage {{ background: transparent; }}
QListWidget {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px; outline: 0;
}}
QListWidget::item {{ padding: 3px 4px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {sel}; color: {t.text}; }}
QListWidget#settingsNav {{ background: transparent; border: none; padding: 0; }}
QListWidget#settingsNav::item {{ padding: 0 10px; margin: 1px 0; }}
QListWidget#settingsNav::item:hover:!selected {{ background: {t.surface_alt}; }}
QLabel#error {{ color: {t.empty}; }}
QToolButton#primary {{ background: {t.accent}; color: #FFFFFF; border-color: {t.accent}; font-weight: 600; }}
QToolButton#primary:hover {{ background: {t.accent}; border-color: {t.text}; }}
QMenu {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
QMenu::item {{ padding: 6px 16px 6px 8px; border-radius: 5px; }}
QMenu::item:selected {{ background: {sel}; }}
QMenu::icon {{ padding-left: 6px; }}
"""
