"""Drop-down menus of the main window: the Columns menu's base, Gaps and Cameras."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget, QWidgetAction

from ..profile import MAXIMUM, MINIMUM
from .settings import CameraList


class StickyMenu(QMenu):
    """Menu that stays open when a checkable item is toggled, so several columns can be changed at once."""

    def mouseReleaseEvent(self, e):
        a = self.activeAction()
        if a is not None and a.isCheckable() and a.isEnabled() and a.menu() is None:
            a.trigger()
            e.accept()
            return
        super().mouseReleaseEvent(e)


class GapMenu(QMenu):
    """What counts as a gap: a multiple of a topic's usual interval, and a minimum length."""
    changed = Signal(float, float)  # factor, min_s, as edited
    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = (None, None)  # as last shown; the boxes round them to their decimals
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(12, 10, 12, 10)
        form.setVerticalSpacing(8)
        intro = QLabel("A gap is a pause between two messages of a topic that is longer than both:",
                       wordWrap=True, objectName="muted")
        intro.setFixedWidth(270)
        form.addRow(intro)
        self.factor_box = QDoubleSpinBox(decimals=1, singleStep=0.5, suffix="× its usual interval",
                                         buttonSymbols=QDoubleSpinBox.NoButtons)
        self.factor_box.setRange(MINIMUM["gaps", "factor"], MAXIMUM["gaps", "factor"])
        self.min_box = QDoubleSpinBox(decimals=2, singleStep=0.05, suffix=" s", buttonSymbols=QDoubleSpinBox.NoButtons)
        self.min_box.setRange(MINIMUM["gaps", "min_s"], MAXIMUM["gaps", "min_s"])
        form.addRow("Multiple", self.factor_box)
        form.addRow("Minimum", self.min_box)
        for spin in (self.factor_box, self.min_box):
            spin.setToolTip("Type a value, or scroll / use the arrow keys")
        reset = QToolButton(objectName="link", text="Reset to defaults")
        reset.clicked.connect(self.resetRequested)
        form.addRow(reset)
        self.factor_box.valueChanged.connect(lambda v: self.changed.emit(v, self._values[1]))
        self.min_box.valueChanged.connect(lambda v: self.changed.emit(self._values[0], v))
        action = QWidgetAction(self)
        action.setDefaultWidget(box)
        self.addAction(action)

    def show_values(self, factor, min_s):
        self._values = (factor, min_s)
        for spin, v in ((self.factor_box, factor), (self.min_box, min_s)):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)


class CameraMenu(QMenu):
    """Which cameras the thumbnail comes from, in order of preference. The owner fills `picker` when
    the menu opens (aboutToShow) and on resetRequested; `chosen` reports the result when it closes."""
    chosen = Signal(list)
    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        intro = QLabel("The frame comes from the first checked camera that a recording has images from.",
                       wordWrap=True, objectName="muted")
        intro.setFixedWidth(270)
        lay.addWidget(intro)
        self.picker = CameraList(width=270)
        reset = QToolButton(objectName="link", text="Reset to defaults")
        reset.clicked.connect(self.resetRequested)
        self.picker.row.addWidget(reset)
        lay.addWidget(self.picker)
        action = QWidgetAction(self)
        action.setDefaultWidget(box)
        self.addAction(action)
        self.aboutToHide.connect(lambda: self.chosen.emit(self.picker.cameras()))
