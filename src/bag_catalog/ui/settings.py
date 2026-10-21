"""Settings page: edits your own profile file (see profile.py), one page per section."""
import os

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import profile, theme
from ..fmt import home_short, plural
from .common import scaled_font

PAGES = [("Sensor columns", "sensors"), ("Camera frame", "thumbnails"), ("Routes", "routes"), ("Gaps", "gaps"),
         ("Map", "map")]
LABELS = {
    "camera_types": "Camera message types", "pointcloud_types": "Lidar / point cloud message types",
    "camera_suffixes": "Camera topic suffixes", "pointcloud_suffixes": "Lidar / point cloud topic suffixes",
    "ignored_segments": "Ignored topic name parts", "aliases": "Sensor renames",
    "cameras": "Cameras", "image_types": "Image message types", "offset_s": "Frame offset",
    "gnss_types": "GNSS message types", "odom_types": "Odometry message types",
    "factor": "Multiple of the usual interval", "min_s": "Minimum pause",
    "tile_url": "Tile URL", "attribution": "Attribution",
}
UNITS = {("thumbnails", "offset_s"): " s", ("gaps", "factor"): "×", ("gaps", "min_s"): " s"}
DECIMALS = {("gaps", "factor"): 1}  # as in the Gaps menu; others 2
EXPORT_NAME = "bag-catalog-settings.yaml"  # not bag_catalog.yaml: that would apply to every folder below it


class CameraList(QWidget):
    """Checkable, reorderable camera sensor names; the checked ones, in order, are the preference."""
    changed = Signal()

    def __init__(self, width=None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.list = QListWidget()
        if width:
            self.list.setFixedWidth(width)
        self.list.itemChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.list)
        self.row = QHBoxLayout()
        for text, step in (("Move up", -1), ("Move down", 1)):
            b = QToolButton(objectName="link", text=text)
            b.clicked.connect(lambda _=False, s=step: self.move(s))
            self.row.addWidget(b)
        self.row.addStretch(1)
        lay.addLayout(self.row)

    def set_cameras(self, order, found):
        """`order` first (kept even when not in the open folders, greyed), then the other cameras in `found`."""
        self.list.blockSignals(True)
        self.list.clear()
        for name in list(order) + sorted(set(found) - set(order)):
            it = QListWidgetItem(name, self.list)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if name in order else Qt.Unchecked)
            if name not in found:
                it.setForeground(theme.current.c("faint"))
                it.setToolTip("Not in the open folders")
        self.list.blockSignals(False)
        rows = min(8, max(3, self.list.count()))
        self.list.setFixedHeight(rows * max(24, self.list.sizeHintForRow(0)) + 2 * self.list.frameWidth() + 8)
        self.changed.emit()

    def cameras(self):
        items = map(self.list.item, range(self.list.count()))
        return [it.text() for it in items if it.checkState() == Qt.Checked]

    def move(self, step):
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + step < self.list.count():
            return
        self.list.insertItem(row + step, self.list.takeItem(row))
        self.list.setCurrentRow(row + step)
        self.changed.emit()


class Field:
    """Editor for one profile setting, picked by the type of its default."""

    def __init__(self, section, key, cameras_found):
        self.section, self.key = section, key
        default = profile.DEFAULTS[section][key]
        if key == "cameras":
            self.widget = CameraList()
            self.widget.changed.connect(self._changed)
            self._set = lambda v: self.widget.set_cameras(v, cameras_found)
            self._get = self.widget.cameras
        elif isinstance(default, float):
            self.widget = QDoubleSpinBox(decimals=DECIMALS.get((section, key), 2), singleStep=0.1,
                                         buttonSymbols=QDoubleSpinBox.NoButtons, suffix=UNITS.get((section, key), ""))
            self.widget.setRange(profile.MINIMUM.get((section, key), 0.0), profile.MAXIMUM.get((section, key), 3600))
            self.widget.setFixedWidth(120)
            self.widget.valueChanged.connect(self._changed)
            self._set, self._get = self.widget.setValue, self.widget.value
        elif isinstance(default, str):
            self.widget = QLineEdit()
            self.widget.textChanged.connect(self._changed)
            self._set, self._get = self.widget.setText, lambda: self.widget.text().strip()
        else:
            self.widget = QPlainTextEdit()
            self.widget.setTabChangesFocus(True)
            self.widget.setLineWrapMode(QPlainTextEdit.NoWrap)
            lines = min(8, max(3, len(default) + 1))
            self.widget.setFixedHeight(lines * self.widget.fontMetrics().lineSpacing() + 18)
            self.widget.textChanged.connect(self._changed)
            if isinstance(default, list):
                self._set = lambda v: self.widget.setPlainText("\n".join(v))
                self._get = lambda: [s.strip() for s in self.widget.toPlainText().splitlines() if s.strip()]
            else:
                self._set = lambda v: self.widget.setPlainText("\n".join(f"{a}: {b}" for a, b in v.items()))
                self._get = self._mapping
        self.on_change = None

    def _mapping(self):
        out = {}
        for line in filter(None, (s.strip() for s in self.widget.toPlainText().splitlines())):
            old, sep, new = line.partition(":")
            if not sep or not old.strip() or not new.strip():
                raise ValueError(f"line '{line}' should look like  old: new")
            out[old.strip()] = new.strip()
        return out

    def _changed(self, *_):
        if self.on_change:
            self.on_change()

    def set(self, value):
        self._set(value)

    def value(self):
        """The edited value, checked; ValueError if it isn't valid."""
        return profile.check(self.section, self.key, self._get())


class SettingsDialog(QDialog):
    """Once accepted, `values` holds {(section, key): value} for every profile setting, and
    `theme_choice` the colour scheme ('auto', 'light' or 'dark'), a personal setting kept outside the profile."""

    def __init__(self, layers, cameras_found, roots, theme_choice="auto", session_theme=None, parent=None):
        super().__init__(parent, objectName="settings")
        self.setWindowTitle("Settings")
        self.resize(860, 640)
        self.layers, self.roots, self.values = layers, roots, {}
        self.fields = {}  # (section, key) -> (Field, reset button)

        self.nav = QListWidget(objectName="settingsNav")
        self.nav.setFixedWidth(180)
        self.stack = QStackedWidget()
        for title, section in PAGES:
            self.nav.addItem(title)
            self.stack.addWidget(self._page(title, section, cameras_found))
        self.nav.addItem("Appearance")
        self.stack.addWidget(self._appearance_page(theme_choice, session_theme))
        self.nav.addItem("Profile files")
        self.stack.addWidget(self._files_page())
        for i in range(self.nav.count()):  # stylesheet padding doesn't size list rows
            self.nav.item(i).setSizeHint(QSize(0, self.nav.fontMetrics().height() + 16))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.error = QLabel(objectName="error", wordWrap=True)
        cancel = QToolButton(text="Cancel")
        cancel.clicked.connect(self.reject)
        save = QToolButton(objectName="primary", text="Save")
        save.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.error, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 14)
        outer.setSpacing(12)
        outer.addLayout(body, 1)
        outer.addLayout(buttons)

    def _scroll_page(self, title, intro):
        inner = QWidget(objectName="settingsPage")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(4, 0, 12, 12)
        lay.setSpacing(6)
        head = QLabel(title)
        head.setFont(scaled_font(self.font(), 1.3, QFont.DemiBold))
        lay.addWidget(head)
        lay.addWidget(QLabel(intro, wordWrap=True, objectName="muted"))
        area = QScrollArea(objectName="settingsPage", widgetResizable=True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(inner)
        return area, lay

    def _page(self, title, section, cameras_found):
        area, lay = self._scroll_page(title, profile.HELP[section])
        for key in profile.DEFAULTS[section]:
            field = Field(section, key, cameras_found)
            label = QLabel(LABELS[key])
            label.setFont(scaled_font(self.font(), 1.0, QFont.DemiBold))
            src = self.layers.origin.get((section, key))
            reset = QToolButton(objectName="link", text="Reset",
                                toolTip=f"Back to the value from {home_short(src)}" if src else
                                "Back to the built-in default")
            reset.clicked.connect(lambda _=False, f=field: f.set(self.layers.base[f.section][f.key]))
            origin = QLabel(f"from {home_short(src)}" if src else "", objectName="muted",
                            toolTip="The folder's shared profile sets this; your own value would win over it")
            row = QHBoxLayout()
            row.addWidget(label)
            row.addSpacing(6)
            row.addWidget(origin)
            row.addStretch(1)
            row.addWidget(reset)
            lay.addSpacing(10)
            lay.addLayout(row)
            default = profile.DEFAULTS[section][key]
            hint = ("" if key == "cameras" else " One per line." if isinstance(default, list) else
                    " One per line, as  old: new" if isinstance(default, dict) else "")
            lay.addWidget(QLabel(profile.HELP[f"{section}.{key}"].replace("\n", " ") + hint, wordWrap=True,
                                 objectName="muted"))
            lay.addWidget(field.widget, 0, Qt.AlignLeft if key in ("cameras", "offset_s", "factor", "min_s") else
                          Qt.Alignment())
            self.fields[section, key] = (field, reset)
            field.on_change = lambda f=field, r=reset, o=origin: self._show_state(f, r, o)
            field.set(self.layers.values[section][key])
            self._show_state(field, reset, origin)
        lay.addStretch(1)
        return area

    def _show_state(self, field, reset, origin):
        """Reset when the value differs from what it would be without your own settings; otherwise
        the folder profile it comes from, if any."""
        differs = self._differs(field)
        reset.setVisible(differs)
        origin.setVisible(not differs and bool(origin.text()))

    def _differs(self, field):
        try:
            return field.value() != self.layers.base[field.section][field.key]
        except ValueError:
            return True

    def _appearance_page(self, theme_choice, session_theme):
        area, lay = self._scroll_page("Appearance", "Personal display settings. They are not part of a profile, "
                                                    "so they are never shared with a folder.")
        lay.addSpacing(10)
        lay.addWidget(self._bold("Colour scheme"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.theme_buttons = {}
        group = QButtonGroup(self)
        for value, text in (("auto", "Follow the desktop"), ("light", "Light"), ("dark", "Dark")):
            b = QToolButton(objectName="filterToggle", text=text, checkable=True)
            b.setChecked(value == theme_choice)
            b.setCursor(Qt.PointingHandCursor)
            group.addButton(b)
            row.addWidget(b)
            self.theme_buttons[value] = b
        row.addStretch(1)
        lay.addLayout(row)
        if session_theme:
            lay.addWidget(QLabel(f"This session uses “{session_theme}” from --theme or BAG_CATALOG_THEME. "
                                 "The choice here applies when neither is given.", objectName="muted", wordWrap=True))
        lay.addStretch(1)
        return area

    @property
    def theme_choice(self):
        return next((v for v, b in self.theme_buttons.items() if b.isChecked()), "auto")

    def _files_page(self):
        area, lay = self._scroll_page(
            "Profile files",
            "Settings are plain YAML files. A folder's bag_catalog.yaml applies to everyone who opens that folder "
            "or one inside it; your own file, which this page writes, holds only what you changed and wins over it.")
        mine = profile.USER_FILE
        n = sum(len(k) for k in self.layers.user.values())
        lay.addSpacing(10)
        lay.addWidget(self._bold("Your settings"))
        lay.addWidget(QLabel(f"{home_short(mine)} · " + (f"{plural(n, 'setting')} changed" if n else
                             "nothing changed yet"), objectName="muted", wordWrap=True))
        edit = QToolButton(objectName="link", text="Open in text editor",
                           toolTip="Edits made by hand apply on the next rescan (F5)")
        edit.clicked.connect(self.open_user_file)
        lay.addWidget(edit, 0, Qt.AlignLeft)

        folders = [f for f in self.layers.used if f != mine]
        lay.addSpacing(10)
        lay.addWidget(self._bold("Folder profiles in use"))
        lay.addWidget(QLabel("<br>".join(home_short(f) for f in folders[::-1]) if folders else
                             "None.", objectName="muted", wordWrap=True))

        lay.addSpacing(10)
        lay.addWidget(self._bold("Import and export"))
        lay.addWidget(QLabel("Export writes the settings on these pages that differ from the built-in defaults to a "
                             f"YAML file. Saved as {profile.FOLDER_FILE} at the top of a bag folder, it becomes that "
                             "folder's profile. Import fills these pages from such a file: only the settings in it "
                             "change, and nothing applies until you Save.", objectName="muted", wordWrap=True))
        row = QHBoxLayout()
        export = QToolButton(objectName="link", text="Export to file…")
        export.clicked.connect(lambda: self.export_file())
        load = QToolButton(objectName="link", text="Import from file…")
        load.clicked.connect(lambda: self.import_file())
        row.addWidget(export)
        row.addWidget(load)
        row.addStretch(1)
        lay.addLayout(row)
        self.file_status = QLabel(objectName="muted", wordWrap=True, visible=False)
        lay.addWidget(self.file_status)
        lay.addStretch(1)
        return area

    def _bold(self, text):
        label = QLabel(text)
        label.setFont(scaled_font(self.font(), 1.0, QFont.DemiBold))
        return label

    def collect(self):
        """{(section, key): value} for every field, or None after showing the first problem."""
        out = {}
        for (section, key), (field, _) in self.fields.items():
            try:
                out[section, key] = field.value()
            except ValueError as e:
                self.nav.setCurrentRow([s for _, s in PAGES].index(section))
                field.widget.setFocus()
                self.error.setText(f"{dict((s, t) for t, s in PAGES)[section]} › {LABELS[key]}: {e}")
                return None
        self.error.clear()
        return out

    def save(self):
        values = self.collect()
        if values is not None:
            self.values = values
            self.accept()

    def export_file(self, path=None):
        """Write the settings on the pages (edits included) that differ from the built-in defaults."""
        values = self.collect()
        if values is None:
            return
        settings = profile.changed(profile.overlay(profile.DEFAULTS, _nested(values)), profile.DEFAULTS)
        if not settings:
            self._status("Nothing to export: every setting has its built-in value.")
            return
        if path is None:
            start = os.path.join(os.path.expanduser("~"), EXPORT_NAME)
            path, _ = QFileDialog.getSaveFileName(self, "Export settings", start, "YAML (*.yaml *.yml)")
            if not path:
                return
        try:
            profile.write(path, settings, profile.SHARE_HEADER)
        except OSError as e:
            self.error.setText(f"Could not export: {e.strerror or e}")
            return
        n = sum(len(keys) for keys in settings.values())
        note = (" As a folder profile, it applies to that folder and the folders inside it from the next rescan (F5)."
                if os.path.basename(path) == profile.FOLDER_FILE else "")
        self._status(f"Exported {plural(n, 'setting')} to {home_short(path)}.{note}")

    def _status(self, text):
        self.error.clear()
        self.file_status.setText(text)
        self.file_status.show()

    def import_file(self, path=None):
        """Put the settings of a profile file into the fields; they apply when the dialog is saved."""
        if path is None:
            start = self.roots[0] if self.roots else os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(self, "Import settings", start, "YAML (*.yaml *.yml)")
            if not path:
                return
        errors = []
        settings = profile.read(path, errors)
        for section, keys in settings.items():
            for key, value in keys.items():
                self.fields[section, key][0].set(value)
        n = sum(len(keys) for keys in settings.values())
        pages = [f"{title} ({', '.join(LABELS[k] for k in settings[section])})"
                 for title, section in PAGES if section in settings]
        self._status(f"Imported {plural(n, 'setting')} from {home_short(path)}: " + "; ".join(pages)
                     + ". Save to keep them." if n else f"No settings found in {home_short(path)}.")
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        self.error.setText(f"Skipped: {errors[0]}{more}" if errors else "")

    def open_user_file(self):
        if not os.path.exists(profile.USER_FILE):
            try:
                profile.write(profile.USER_FILE, self.layers.user, profile.USER_HEADER)
            except OSError as e:
                self.error.setText(f"Could not create {home_short(profile.USER_FILE)}: {e}")
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(profile.USER_FILE))


def _nested(values):
    out = {}
    for (section, key), value in values.items():
        out.setdefault(section, {})[key] = value
    return out
