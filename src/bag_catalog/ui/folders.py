"""The open folders in the title bar: a chip per folder (click to change, × to remove) and an Add button."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QToolButton, QWidget

from .. import icons, theme
from ..fmt import home_short
from ..model import MAX_ROOTS
from .common import clear_layout


class FolderBar(QWidget):
    rootsChosen = Signal(list)  # the folders the user asked for; the owner applies them

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roots, self.labels = [], {}
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)

    def set_roots(self, roots, labels):
        """Show these folders, each named by its short label when there are several."""
        self.roots, self.labels = list(roots), labels
        self.rebuild()

    def rebuild(self):
        clear_layout(self.lay)
        t = theme.current
        for i, root in enumerate(self.roots):
            missing = not os.path.isdir(root)
            chip = QFrame(objectName="folderChip")
            chip.setProperty("missing", missing)
            lay = QHBoxLayout(chip)
            lay.setContentsMargins(2, 0, 2, 0)
            lay.setSpacing(0)
            text = home_short(root) if len(self.roots) == 1 else self.labels.get(root, root)
            btn = QToolButton(objectName="folderButton", text=text)
            btn.setIcon(icons.icon("folder", t.empty if missing else t.muted))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(home_short(root) + (" — not found" if missing else "") + "\nClick to choose another folder")
            btn.clicked.connect(lambda _=False, i=i: self._change(i))
            lay.addWidget(btn)
            if len(self.roots) > 1:
                rm = QToolButton(objectName="folderRemove", toolTip="Remove this folder")
                rm.setIcon(icons.icon("close", t.muted, 12))
                rm.setCursor(Qt.PointingHandCursor)
                rm.clicked.connect(lambda _=False, i=i: self.rootsChosen.emit(self.roots[:i] + self.roots[i + 1:]))
                lay.addWidget(rm)
            self.lay.addWidget(chip)
        if len(self.roots) < MAX_ROOTS:
            add = QToolButton(objectName="rootButton", text="Add folder",
                              toolTip=f"Show bags from another folder too (up to {MAX_ROOTS})")
            add.setIcon(icons.icon("plus", t.muted))
            add.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            add.setCursor(Qt.PointingHandCursor)
            add.clicked.connect(self._add)
            self.lay.addWidget(add)

    def _change(self, i):
        d = QFileDialog.getExistingDirectory(self.window(), "Choose bag folder", self.roots[i])
        if d:
            self.rootsChosen.emit(self.roots[:i] + [d] + self.roots[i + 1:])

    def _add(self):
        start = os.path.dirname(self.roots[-1]) if self.roots else os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self.window(), "Add bag folder", start)
        if d:
            self.rootsChosen.emit(self.roots + [d])
