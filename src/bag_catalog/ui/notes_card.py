"""The Recording notes card: notes and the Favorite button for the selected recordings, kept in
bag_notes.yaml in each recording's folder (see notes.py)."""
import html
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QToolButton

from .. import icons, theme
from ..notes import NOTES_FILE, write_notes
from .common import Card, caption_font, scaled_font


class NotesCard(Card):
    """Editable for exactly one selected recording, read-only for several. Typing saves after a pause."""
    saved = Signal()  # a recording's notes were written: its annotations need refreshing
    favoriteClicked = Signal()

    def __init__(self, parent=None):
        super().__init__("Recording notes", parent=parent)
        self.recs = []  # the recordings shown
        self._loading = False
        self.edit = QPlainTextEdit()
        self.edit.setTabChangesFocus(True)
        self.edit.textChanged.connect(self._changed)
        self.status = QLabel(objectName="muted", wordWrap=True)
        self.status.setFont(scaled_font(QApplication.font(), 0.85))
        self.fav_btn = QToolButton(objectName="favButton", text="Favorite", checkable=True,
                                   toolTip="Mark the selected recordings as favorites (Ctrl+D)")
        self.fav_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.fav_btn.setCursor(Qt.PointingHandCursor)
        self.fav_btn.setFixedHeight(QFontMetrics(caption_font()).height() + 2)  # keep the caption aligned with other cards
        self.fav_btn.clicked.connect(self.favoriteClicked)
        self.title_row.addWidget(self.fav_btn)
        self.lay.addWidget(self.edit, 1)
        self.lay.addWidget(self.status)
        self.setFixedWidth(240)
        self.save_timer = QTimer(self, singleShot=True, interval=700)
        self.save_timer.timeout.connect(self._save)

    def update_icon(self):
        t = theme.current
        on = self.fav_btn.isChecked()
        self.fav_btn.setIcon(icons.icon("star", t.partial if on else t.muted, 14, t.partial if on else "none"))

    def show_recordings(self, recs):
        """Show the selected recordings' notes: editable for exactly one, read-only otherwise."""
        same = [r.path for r in recs] == [r.path for r in self.recs]
        if not same:
            self.flush()
        self.recs = recs
        self.fav_btn.setEnabled(bool(recs))
        self.fav_btn.setChecked(bool(recs) and all(r.favorite for r in recs))
        self.fav_btn.setText("Favorite" if len(recs) < 2 else f"Favorite all {len(recs)}")
        self.update_icon()
        if same and (self.save_timer.isActive() or self.edit.hasFocus()):
            return  # don't disturb typing when the details refresh
        self._loading = True
        one = len(recs) == 1
        self.edit.setReadOnly(not one)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        if one:
            r = recs[0]
            self.edit.setPlainText(r.notes)
            self.edit.setPlaceholderText("Add notes about this recording…")
            self.status.setText(f"Saved as {NOTES_FILE} in {html.escape(os.path.basename(r.path))}/")
            if r.notes_error:
                self.status.setText(f"<span style='color:{theme.current.empty}'>{html.escape(r.notes_error)}</span>")
        elif recs:
            noted = [r for r in recs if r.notes]
            self.edit.setPlainText("\n\n".join(f"[{r.name}]\n{r.notes}" for r in noted))
            self.edit.setPlaceholderText("No notes on these recordings yet")
            self.status.setText(f"{len(noted)} of {len(recs)} recordings have notes · "
                                "select one recording to edit")
        else:
            self.edit.setPlainText("")
            self.edit.setPlaceholderText("Select a recording to add notes")
            self.status.setText("")
        self._loading = False

    def _changed(self):
        if not self._loading and len(self.recs) == 1:
            self.save_timer.start()
            self.status.setText("Editing…")

    def flush(self):
        """Save notes still waiting for the typing pause."""
        if self.save_timer.isActive():
            self._save()

    def _save(self):
        self.save_timer.stop()
        if len(self.recs) != 1 or self.edit.isReadOnly():
            return
        r = self.recs[0]
        text = self.edit.toPlainText().rstrip()
        if text != r.notes:
            err = write_notes(r.path, r.favorite, text)
            if err:
                self.status.setText(f"<span style='color:{theme.current.empty}'>{html.escape(err)}</span>")
                return
            r.notes = text
            self.saved.emit()
        self.status.setText(f"Saved to {html.escape(os.path.basename(r.path))}/{NOTES_FILE}")
