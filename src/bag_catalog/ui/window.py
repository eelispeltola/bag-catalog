"""Main window: title bar, sensor filter, recordings table and the detail cards."""
import csv
import html
import os
import shlex
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QFontMetrics, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QSplitter,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import icons, profile, theme
from ..config import HAVE_ROS
from ..extract import merge_gaps, topic_gaps, track_distance
from ..fmt import fmt_dist, fmt_dur, fmt_size, fmt_time, home_short, plural
from ..model import KIND_LABEL, KIND_ORDER, MAX_ROOTS, Bag, Recording, root_labels, scan_all
from ..notes import write_notes
from ..prefs import saved_list, saved_theme, store, take_legacy_settings
from .common import Card, caption_font, clear_layout, draw_kind, draw_status, glyph_pixmap, scaled_font, tabular
from .folders import FolderBar
from .jobs import JobRunner
from .map_view import MapView, TileCache
from .media import ThumbView
from .menus import CameraMenu, GapMenu, StickyMenu
from .notes_card import NotesCard
from .settings import SettingsDialog
from .topics import TopicsTable
from .tree import (
    CHIPS_ROLE, COL_DIST, COL_DUR, COL_MSGS, COL_NAME, COL_SIZE, COL_START, COL_TIMELINE, FAV_ROLE, FIXED_HEADERS,
    GAPS_ROLE, OBJ_ROLE, PREFIX_ROLE, REC_ROLE, SENSOR_WIDTH, SORT_ROLE, SPAN_ROLE, STATUS_ROLE, TONE_ROLE, CatalogTree,
    SortItem,
)

STATUS_DESC = {"ok": "recorded", "partial": "some topics have 0 messages", "empty": "topics present but 0 messages"}
HINT = "Click ☆ to favorite a recording  ·  double-click opens the folder  ·  Ctrl+C copies paths  ·  right-click for more"


class CatalogWindow(QMainWindow):
    def __init__(self, roots, theme_override=None):
        super().__init__()
        self.roots = roots[:MAX_ROOTS]
        self.labels = {}
        self.theme_override = theme_override  # from the command line, for this session only
        self.recordings = []
        self.sensors = []
        self.required = set()
        self.fav_only = False
        self.hidden_cols = set(saved_list("hidden_columns"))  # fixed column names, e.g. "Timeline"
        self.hidden_sensors = set(saved_list("hidden_sensors"))  # sensor names as in the headers
        self.layers = None  # profile layers for the open folders (profile.py); re-read on every rescan
        self.cfg = None  # the settings in effect: layers.values
        self.pending = {}  # settings changed in the app, not yet written to your profile file
        self.sort_state = (COL_START, Qt.AscendingOrder)
        self.jobs = JobRunner(self)  # topic statistics, routes and camera frames, extracted in the background
        self.resize(1640, 980)
        self._build()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self.apply_theme(refresh=False)
        self.reload()

    # -- layout
    def _build(self):
        central = QWidget(objectName="central")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 14, 16, 4)
        outer.setSpacing(10)

        # title bar
        self.logo = QLabel()
        self.logo.setPixmap(icons.app_pixmap(30))
        title = QLabel("Bag Catalog", objectName="appTitle")
        title.setFont(scaled_font(QApplication.font(), 1.45, QFont.DemiBold))
        self.folder_bar = FolderBar()
        self.folder_bar.rootsChosen.connect(self.set_roots)
        self.search = QLineEdit(placeholderText="Search recordings, bags and topics…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(360)
        self.search.textChanged.connect(self.populate)
        self.search_icon = self.search.addAction(icons.icon("search", "#888"), QLineEdit.LeadingPosition)
        self.reload_btn = QToolButton(toolTip="Rescan folder (F5)")
        self.reload_btn.clicked.connect(self.reload)
        self.export_btn = QToolButton(text="Export CSV")
        self.export_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.export_btn.clicked.connect(self.export_csv)
        self.settings_btn = QToolButton(toolTip="Settings (Ctrl+,)")
        self.settings_btn.clicked.connect(self.open_settings)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.logo)
        top.addWidget(title)
        top.addSpacing(4)
        top.addWidget(self.folder_bar)
        top.addStretch(1)
        top.addWidget(self.search)
        top.addWidget(self.reload_btn)
        top.addWidget(self.export_btn)
        top.addWidget(self.settings_btn)

        # filter chips + totals
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.stats = QLabel(objectName="stats")
        filter_bar = QWidget()
        filter_bar.setFixedHeight(26)
        frow = QHBoxLayout(filter_bar)
        frow.setContentsMargins(2, 0, 2, 0)
        self.fav_filter = QToolButton(objectName="filterToggle", text="Favorites", checkable=True,
                                      toolTip="Show only favorite recordings")
        self.fav_filter.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.fav_filter.setCursor(Qt.PointingHandCursor)
        self.fav_filter.toggled.connect(self.set_fav_only)
        frow.addWidget(self.fav_filter)
        frow.addSpacing(8)
        frow.addLayout(self.chips)
        frow.addStretch(1)
        self.expand_btn = QToolButton(objectName="link", text="Expand all", toolTip="Expand all recordings (Ctrl+Shift+Down)")
        self.expand_btn.clicked.connect(self.expand_all)
        self.collapse_btn = QToolButton(objectName="link", text="Collapse all",
                                        toolTip="Collapse all recordings (Ctrl+Shift+Up)")
        self.collapse_btn.clicked.connect(self.collapse_all)
        self.columns_btn = QToolButton(objectName="link", text="Columns", toolTip="Show or hide columns")
        self.columns_btn.setPopupMode(QToolButton.InstantPopup)
        self.columns_menu = StickyMenu(self)
        self.columns_menu.aboutToShow.connect(lambda: self.fill_columns_menu(self.columns_menu))
        self.columns_btn.setMenu(self.columns_menu)
        self.gaps_btn = QToolButton(objectName="link", toolTip="What counts as a gap in a topic's data")
        self.gaps_btn.setPopupMode(QToolButton.InstantPopup)
        self.gap_menu = GapMenu(self)
        self.gap_menu.changed.connect(self.set_gap_threshold)
        self.gap_menu.resetRequested.connect(
            lambda: self.set_gap_threshold(self.layers.base["gaps"]["factor"], self.layers.base["gaps"]["min_s"]))
        self.gaps_btn.setMenu(self.gap_menu)
        for b in (self.expand_btn, self.collapse_btn, self.columns_btn, self.gaps_btn):
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCursor(Qt.PointingHandCursor)
            frow.addWidget(b)
        frow.addSpacing(14)
        frow.addWidget(self.stats)

        # recordings table
        self.tree = CatalogTree()
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setFont(tabular(self.tree.font()))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.itemSelectionChanged.connect(self.update_details)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_folder())
        self.tree.starClicked.connect(self.star_clicked)
        hdr = self.tree.header()
        hdr.sectionClicked.connect(self.header_clicked)
        hdr.sortIndicatorChanged.connect(self.sort_changed)
        hdr.setContextMenuPolicy(Qt.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self.header_menu)
        tree_card = Card(margins=(6, 2, 6, 6))
        tree_card.lay.addWidget(self.tree)

        # detail cards
        self.overview = QLabel(textInteractionFlags=Qt.TextSelectableByMouse, wordWrap=True)
        self.overview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.overview.setFont(tabular(self.overview.font()))
        ov_card = Card("Overview")
        ov_card.lay.addWidget(self.overview, 1)
        ov_card.setFixedWidth(240)
        self.notes_card = NotesCard()
        self.notes_card.favoriteClicked.connect(lambda: self.toggle_favorite(self.notes_card.recs))
        self.notes_card.saved.connect(self.refresh_annotations)
        self.stats_timer = QTimer(self, singleShot=True, interval=200)  # coalesce bursts of finished jobs
        self.stats_timer.timeout.connect(self.refresh_gaps)
        self.profile_timer = QTimer(self, singleShot=True, interval=500)  # e.g. while scrolling a gap value
        self.profile_timer.timeout.connect(self.save_profile)
        self.jobs.statsReady.connect(lambda _: self.stats_timer.start())
        self.jobs.trackReady.connect(lambda _: (self.refresh_distances(), self.update_details()))
        self.jobs.thumbReady.connect(lambda _: self.update_media())
        self.map = MapView(TileCache(self))
        self.map_card = Card("Route")
        self.map_card.lay.addWidget(self.map, 1)
        self.map_card.setFixedWidth(300)
        self.thumb = ThumbView()
        self.cam_card = Card("Camera")
        self.cams_btn = QToolButton(objectName="link", text="Cameras",
                                    toolTip="Which cameras the frame is taken from, in order of preference")
        self.cams_btn.setPopupMode(QToolButton.InstantPopup)
        self.cam_menu = CameraMenu(self)
        self.cam_menu.aboutToShow.connect(
            lambda: self.cam_menu.picker.set_cameras(self.cfg["thumbnails"]["cameras"], self.image_cameras()))
        self.cam_menu.resetRequested.connect(
            lambda: self.cam_menu.picker.set_cameras(self.layers.base["thumbnails"]["cameras"], self.image_cameras()))
        self.cam_menu.chosen.connect(self.set_thumb_cameras)
        self.cams_btn.setMenu(self.cam_menu)
        self.cams_btn.setCursor(Qt.PointingHandCursor)
        self.cams_btn.setFixedHeight(QFontMetrics(caption_font()).height() + 2)
        self.cam_card.title_row.addWidget(self.cams_btn)
        self.cam_card.lay.addWidget(self.thumb, 1)
        self.cam_card.setFixedWidth(300)
        self.topics = TopicsTable()
        self.topics_card = Card("Topics")
        self.topics_card.lay.addWidget(self.topics, 1)
        details = QWidget()
        dl = QHBoxLayout(details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)
        for w in (ov_card, self.notes_card, self.map_card, self.cam_card):
            dl.addWidget(w)
        dl.addWidget(self.topics_card, 1)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(10)
        split.setChildrenCollapsible(False)
        split.addWidget(tree_card)
        split.addWidget(details)
        split.setSizes([590, 350])

        outer.addLayout(top)
        outer.addWidget(filter_bar)
        outer.addWidget(split, 1)
        self.setCentralWidget(central)

        # status bar: hint on the left, legend on the right
        self.hint = QLabel(objectName="muted")
        self.statusBar().addWidget(self.hint, 1)
        self.legend = QWidget()
        self.legend_lay = QHBoxLayout(self.legend)
        self.legend_lay.setContentsMargins(0, 0, 6, 0)
        self.legend_lay.setSpacing(4)
        self.statusBar().addPermanentWidget(self.legend)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setContentsMargins(14, 0, 8, 2)

        for keys, fn in ((QKeySequence.Copy, self.copy_paths), (QKeySequence("F5"), self.reload),
                         (QKeySequence("Ctrl+D"), lambda: self.toggle_favorite()),
                         (QKeySequence("Ctrl+,"), self.open_settings),
                         (QKeySequence("Ctrl+Shift+Down"), self.expand_all),
                         (QKeySequence("Ctrl+Shift+Up"), self.collapse_all),
                         (QKeySequence.Find, lambda: (self.search.setFocus(), self.search.selectAll()))):
            act = QAction(self, shortcut=keys, triggered=fn)
            self.addAction(act)

    # -- theme
    def apply_theme(self, refresh=True):
        t = theme.detect(self.theme_override or saved_theme())
        theme.use(t)
        app = QApplication.instance()
        app.setPalette(theme.palette(t))
        app.setStyleSheet(theme.stylesheet(t))
        self.search_icon.setIcon(icons.icon("search", t.faint))
        self.reload_btn.setIcon(icons.icon("refresh", t.text))
        self.export_btn.setIcon(icons.icon("export", t.text))
        self.settings_btn.setIcon(icons.icon("settings", t.text))
        self.update_folders()
        self.update_fav_icons()
        self.gaps_btn.setIcon(icons.icon("gap", t.muted, 14))
        for btn, name in ((self.expand_btn, "expand"), (self.collapse_btn, "collapse"), (self.columns_btn, "columns")):
            btn.setIcon(icons.icon(name, t.muted, 14))
        self._build_legend()
        if refresh:
            self.populate()
            self.update_header_highlight()
            self.tree.header().viewport().update()

    def _build_legend(self):
        clear_layout(self.legend_lay)
        entries = [(lambda p, c, s=s: draw_status(p, c, s, 4.5), label) for s, label in
                   (("ok", "recorded"), ("partial", "some topics empty"), ("empty", "no messages"))]
        entries.append((lambda p, c: draw_status(p, c, "ok", 4.5, gaps=True), "gaps"))
        entries += [(lambda p, c, k=k: draw_kind(p, c, k, 11), KIND_LABEL[k].lower()) for k in KIND_ORDER]
        for i, (draw, label) in enumerate(entries):
            if i == 4:
                self.legend_lay.addSpacing(14)
            icon = QLabel()
            icon.setPixmap(glyph_pixmap(draw))
            self.legend_lay.addWidget(icon)
            self.legend_lay.addWidget(QLabel(label, objectName="muted"))
            self.legend_lay.addSpacing(8)

    # -- loading / populating
    def reload(self):
        self.notes_card.flush()  # rescanning re-reads notes from disk
        self.load_profile()
        self.labels = root_labels(self.roots)
        self.setWindowTitle("Bag Catalog — " + (home_short(self.roots[0]) if len(self.roots) == 1 else
                                                 ", ".join(self.labels[r] for r in self.roots)))
        self.update_folders()
        self.recordings = scan_all(self.roots, self.cfg["sensors"])
        found = {t.sensor for r in self.recordings for b in r.bags for t in b.topics}
        self.sensors = sorted(found, key=lambda s: (KIND_ORDER[s[0]], s[1]))
        self.required &= found
        headers = FIXED_HEADERS + [s[1] for s in self.sensors] + ["Notes"]
        self.tree.setColumnCount(len(headers))
        self.tree.setHeaderLabels(headers)
        hdr = self.tree.header()
        hdr.set_sensors(self.sensors, self.required)
        hi = self.tree.headerItem()
        for i, s in enumerate(self.sensors):
            topics = sorted({t.name for r in self.recordings for b in r.bags for t in b.topics if t.sensor == s})
            hi.setToolTip(len(FIXED_HEADERS) + i, f"<b>{s[1]}</b> · {KIND_LABEL[s[0]]}<br>"
                          + "<br>".join(topics) + "<br><br><i>Click to show only recordings with it</i>")
        hi.setToolTip(COL_DIST, "From GNSS fixes; if there are none, dead-reckoned from twist/odometry (≈)")
        self.jobs.start(self.recordings, self.cfg)
        self.populate()
        self.tree.sortByColumn(*self.sort_state)
        self.tree.setSortingEnabled(True)
        self.tree.updateGeometries()

        fm = QFontMetrics(self.tree.font())
        bfm = QFontMetrics(scaled_font(self.tree.font(), 1.0, QFont.DemiBold))
        cfm = QFontMetrics(caption_font())
        names = [b.name for r in self.recordings for b in r.bags] + [self.prefix(r) + "  " + r.name for r in self.recordings]
        widths = {COL_NAME: max([fm.horizontalAdvance(n) for n in names] + [cfm.horizontalAdvance("RECORDING / BAG")]) + 76,
                  COL_START: bfm.horizontalAdvance("2026-10-07  16:21:49") + 22,
                  COL_DUR: max(bfm.horizontalAdvance("0:00:00"), cfm.horizontalAdvance("DURATION")) + 32,
                  COL_DIST: bfm.horizontalAdvance("≈ 99.99 km") + 26,
                  COL_SIZE: bfm.horizontalAdvance("999.9 MB") + 26,
                  COL_MSGS: max(bfm.horizontalAdvance("9,999,999"), cfm.horizontalAdvance("MESSAGES")) + 32,
                  COL_TIMELINE: 130}
        widths.update((len(FIXED_HEADERS) + i, SENSOR_WIDTH) for i in range(len(self.sensors)))
        for c, w in widths.items():
            self.tree.setColumnWidth(c, w)
        self.apply_columns()

    # -- settings: profile files (profile.py), changed on the Settings page and in the Cameras / Gaps menus
    def load_profile(self):
        self.save_profile()  # anything still pending, so it isn't lost by re-reading the file
        self.layers = profile.load(self.roots)
        legacy = take_legacy_settings()
        if legacy:
            self.pending.update(legacy)
            self.save_profile()
        self.cfg = self.layers.values
        self.show_gap_threshold()
        self.map.tiles.set_source(self.cfg["map"]["tile_url"], self.cfg["map"]["attribution"])
        errors = self.layers.errors
        for e in errors:
            print(f"profile: {e}", file=sys.stderr)
        if errors:
            more = f" (and {len(errors) - 1} more, see the terminal)" if len(errors) > 1 else ""
            msg = (f"Profile problem: {errors[0]}{more}", 15000)
        elif any(f != profile.USER_FILE for f in self.layers.used):
            msg = ("Profile: " + ", ".join(map(home_short, self.layers.used)), 6000)
        else:
            return
        # deferred: a message shown before the window is would be drawn over the hint
        QTimer.singleShot(0, lambda: self.statusBar().showMessage(*msg))

    def change_settings(self, changes, save_now=False):
        """Apply {(section, key): value} now; your profile file is written shortly after."""
        self.pending.update(changes)
        self.layers.user = profile.apply_changes(self.layers.user, changes, self.layers.base)
        self.cfg = self.layers.values
        if save_now:
            self.save_profile()
        else:
            self.profile_timer.start()

    def save_profile(self):
        """Write pending changes into your profile file, re-reading it first to keep edits made by hand."""
        self.profile_timer.stop()
        if not self.pending or self.layers is None:
            return
        errors = []
        user = profile.apply_changes(profile.read(profile.USER_FILE, errors), self.pending, self.layers.base)
        if errors:  # unreadable: better to keep the file for the user to fix than to overwrite it
            self.statusBar().showMessage(f"Settings not saved: {errors[0]}", 15000)
            return
        try:
            profile.write(profile.USER_FILE, user, profile.USER_HEADER)
        except OSError as e:
            self.statusBar().showMessage(f"Settings not saved: {e}", 15000)
            return
        self.pending.clear()
        self.layers.user = user
        if profile.USER_FILE not in self.layers.used:
            self.layers.used.append(profile.USER_FILE)

    def image_cameras(self):
        types = self.cfg["thumbnails"]["image_types"]
        return {t.sensor[1] for r in self.recordings for b in r.bags for t in b.topics
                if t.sensor[0] == "camera" and t.type in types}

    def open_settings(self):
        self.save_profile()
        dlg = SettingsDialog(self.layers, self.image_cameras(), self.roots, saved_theme(),
                             self.theme_override, self)
        accepted = dlg.exec()
        dlg.deleteLater()
        if not accepted:
            return
        if dlg.theme_choice != saved_theme():
            store().setValue("theme", dlg.theme_choice)
            self.apply_theme()
        if any(self.cfg[s][k] != v for (s, k), v in dlg.values.items()):
            self.change_settings(dlg.values, save_now=True)
            self.reload()

    def bag_matches(self, rec, bag, text):
        if self.fav_only and not rec.favorite:
            return False
        if self.required and not any(bag.sensors().get(s) in ("ok", "partial") for s in self.required):
            return False
        if not text:
            return True
        hay = [rec.name, bag.name, self.prefix(rec), rec.notes] + [t.name for t in bag.topics]
        return any(text in h.lower() for h in hay)

    def populate(self):
        text = self.search.text().strip().lower()
        expanded = set()
        for i in range(self.tree.topLevelItemCount()):
            if self.tree.topLevelItem(i).isExpanded():
                expanded.add(self.tree.topLevelItem(i).data(COL_NAME, OBJ_ROLE).path)
        selected = {it.data(COL_NAME, OBJ_ROLE).path for it in self.tree.selectedItems()}
        sorting = self.tree.isSortingEnabled()
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        bold = scaled_font(self.tree.font(), 1.0, QFont.DemiBold)
        n_bags = total_size = total_dur = 0
        for rec in self.recordings:
            rs = rec.sensors()
            if any(rs.get(s) not in ("ok", "partial") for s in self.required):
                continue
            bags = [b for b in rec.bags if self.bag_matches(rec, b, text)]
            if not bags:
                continue
            ritem = self.make_row(rec.name, rec.start_ns, rec.end_ns - rec.start_ns,
                                  sum(b.size for b in bags), sum(b.message_count for b in bags), rs, rec)
            ritem.setData(COL_NAME, REC_ROLE, rec)
            ritem.setData(COL_NAME, PREFIX_ROLE, self.prefix(rec) or None)
            ritem.setData(COL_NAME, SORT_ROLE, (self.prefix(rec), rec.name))
            ritem.setData(COL_TIMELINE, SPAN_ROLE, rec.coverage())
            for c in range(self.tree.columnCount()):
                ritem.setFont(c, bold)
            self.annotate(ritem)
            self.tree.addTopLevelItem(ritem)
            span = max(1, rec.end_ns - rec.start_ns)
            for b in bags:
                item = self.make_row(b.name, b.start_ns, b.duration_ns, b.size, b.message_count, b.sensors(), b)
                item.setData(COL_NAME, REC_ROLE, rec)
                if b.start_ns:
                    item.setData(COL_TIMELINE, SPAN_ROLE,
                                 [((b.start_ns - rec.start_ns) / span, (b.end_ns - rec.start_ns) / span)])
                    item.setToolTip(COL_TIMELINE, f"{fmt_time(b.start_ns)} → {fmt_time(b.end_ns)}\n"
                                    f"starts +{(b.start_ns - rec.start_ns) / 1e9:.1f} s into the recording")
                self.annotate(item)
                if b.error:
                    item.setData(COL_NAME, TONE_ROLE, "empty")
                ritem.addChild(item)
                item.setSelected(b.path in selected)
            ritem.setExpanded(bool(text or self.required) or rec.path in expanded)
            ritem.setSelected(rec.path in selected)
            n_bags += len(bags)
            total_size += sum(b.size for b in bags)
            total_dur += rec.end_ns - rec.start_ns
        self.refresh_distances()
        self.tree.setSortingEnabled(sorting)
        self.tree.blockSignals(False)
        self.update_header_highlight()
        t = theme.current
        num = f"<span style='color:{t.text}; font-weight:600'>"
        self.stats.setText(f"{num}{self.tree.topLevelItemCount()}</span> recordings &nbsp;·&nbsp; "
                           f"{num}{n_bags}</span> bags &nbsp;·&nbsp; {num}{fmt_size(total_size)}</span>"
                           f" &nbsp;·&nbsp; {num}{fmt_dur(total_dur)}</span> recorded")
        self.update_fav_count()
        self.hint.setText(HINT if HAVE_ROS else
                          "rosbag2_py not found — source ROS 2 to see routes, distances and camera frames")
        self.update_details()

    def annotate(self, item):
        """Favorite star, note excerpt and file chips of a row; refreshed in place after edits."""
        notes_col = self.tree.columnCount() - 1
        obj = item.data(COL_NAME, OBJ_ROLE)
        if isinstance(obj, Recording):
            bags = obj.bags
            first = obj.notes.strip().splitlines()[0] if obj.notes.strip() else ""
            n_merged = sum(b.merged for b in bags)
            chips = ([(plural(len(bags), "bag"), "neutral")]
                     + ([(first if len(first) <= 40 else first[:39] + "…", "note")] if first else [])
                     + ([(f"{n_merged} merged", "accent")] if n_merged else [])
                     + [(e, "neutral") for e in sorted({e for b in bags for e in b.extras})]
                     + ([("errors", "error")] if any(b.error for b in bags) or obj.notes_error else []))
            item.setData(COL_NAME, FAV_ROLE, obj.favorite)
            n_gaps = merge_gaps(self.gaps_across(bags))
            n_unfinal = sum(not self.jobs.finalized(b) for b in bags)
            chips[1:1] = (([(plural(n_gaps, "gap"), "warn")] if n_gaps else [])
                          + ([(f"{n_unfinal} not finalized", "error")] if n_unfinal else []))
            item.setToolTip(notes_col, "\n\n".join(x for x in (obj.notes, obj.notes_error) if x))
            sensor_gaps = {s for b in bags for s in self.gap_sensors(b)}
        else:
            gaps = self.bag_gaps(obj) or {}
            n_gaps = merge_gaps(gaps)
            unfinal = not self.jobs.finalized(obj)
            chips = (([(plural(n_gaps, "gap"), "warn")] if n_gaps else [])
                     + ([("not finalized", "error")] if unfinal else [])
                     + ([("merged", "accent")] if obj.merged else [])
                     + [(e, "neutral") for e in obj.extras] + ([(obj.error, "error")] if obj.error else []))
            tips = [obj.error] if obj.error else []
            if unfinal:
                tips.append("Not finalized: the recorder stopped before writing the file's index, so data may be\n"
                            "missing at the end, and ROS often can't open it (then no route or camera frame).\n"
                            "To repair it: `mcap recover` (from the mcap CLI) writes a repaired copy of the file;\n"
                            "put it in place of the original, then `ros2 bag reindex <bag folder>` updates metadata.yaml.")
            if obj.merged_from:
                tips.append("Merged: holds the messages of " + ", ".join(obj.merged_from))
            tips += [f"{topic}: {plural(len(g), 'gap')}, longest {max(x[1] for x in g) / 1e9:.2f} s"
                     for topic, g in sorted(gaps.items())]
            item.setToolTip(notes_col, "\n".join(tips))
            sensor_gaps = self.gap_sensors(obj)
        for i, s in enumerate(self.sensors):
            item.setData(len(FIXED_HEADERS) + i, GAPS_ROLE, s in sensor_gaps)
        item.setData(notes_col, CHIPS_ROLE, chips)

    def all_items(self):
        """Every row of the recordings tree: each recording, then its bags."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top
            yield from (top.child(j) for j in range(top.childCount()))

    def refresh_annotations(self):
        for item in self.all_items():
            self.annotate(item)
        self.update_fav_count()
        self.tree.viewport().update()

    def update_fav_count(self):
        n_fav = sum(r.favorite for r in self.recordings)
        self.fav_filter.setText(f"Favorites · {n_fav}" if n_fav else "Favorites")

    # -- topic statistics and gaps (job_stats results; the threshold is applied here)
    def bag_gaps(self, bag):
        """{topic: [[start_ns, length_ns], ...]} under the current threshold; None until analysed."""
        st = self.jobs.topic_stats.get(bag.path)
        if not st or st.get("error"):
            return None
        out = {}
        for topic, s in st["topics"].items():
            g = topic_gaps(s, *self.gap_threshold())
            if g:
                out[topic] = g
        return out

    def gaps_across(self, bags):
        """All gaps of several bags, keyed (bag, topic); merge_gaps() of it counts overlaps once."""
        return {(b.path, topic): g for b in bags for topic, g in (self.bag_gaps(b) or {}).items()}

    def gap_sensors(self, bag):
        gaps = self.bag_gaps(bag) or {}
        return {t.sensor for t in bag.topics if t.name in gaps}

    def refresh_gaps(self):
        self.refresh_annotations()
        self.update_details()

    def gap_threshold(self):
        return self.cfg["gaps"]["factor"], self.cfg["gaps"]["min_s"]

    def set_gap_threshold(self, factor, min_s):
        if (factor, min_s) == self.gap_threshold():
            return
        self.change_settings({("gaps", "factor"): factor, ("gaps", "min_s"): min_s})
        self.show_gap_threshold()
        self.stats_timer.start()

    def show_gap_threshold(self):
        factor, min_s = self.gap_threshold()
        self.gap_menu.show_values(factor, min_s)
        self.gaps_btn.setText(f"Gaps: > {factor:g}× · {min_s:g} s")

    def gaps_text(self, bags):
        analysed = [b for b in bags if self.bag_gaps(b) is not None]
        if not analysed:
            return f"<span style='color:{theme.current.faint}'>…</span>"
        n = merge_gaps(self.gaps_across(analysed))
        topics = {topic for b in analysed for topic in self.bag_gaps(b)}
        if not n:
            return "none"
        return f"<span style='color:{theme.current.partial}'>{n}</span> in {plural(len(topics), 'topic')}"

    # -- thumbnail cameras
    def set_thumb_cameras(self, cams):
        if cams == self.cfg["thumbnails"]["cameras"]:
            return
        self.change_settings({("thumbnails", "cameras"): cams})
        self.jobs.start(self.recordings, self.cfg)  # thumbnails are cached per topic, so cameras chosen before come back at once
        self.update_details()

    # -- favorites and notes, per recording (bag_notes.yaml in the recording folder, see notes.py)
    def selected_recordings(self):
        recs = []
        for it in self.tree.selectedItems():
            rec = it.data(COL_NAME, REC_ROLE)
            if all(rec is not r for r in recs):
                recs.append(rec)
        return recs

    def set_fav_only(self, on):
        self.fav_only = on
        self.update_fav_icons()
        self.populate()

    def update_fav_icons(self):
        t = theme.current
        on = self.fav_filter.isChecked()
        self.fav_filter.setIcon(icons.icon("star", t.partial if on else t.muted, 14, t.partial if on else "none"))
        self.notes_card.update_icon()

    def star_clicked(self, item):
        self.toggle_favorite([item.data(COL_NAME, REC_ROLE)])

    def toggle_favorite(self, recs=None):
        recs = self.selected_recordings() if recs is None else recs
        if recs:
            self.set_favorite(recs, not all(r.favorite for r in recs))

    def set_favorite(self, recs, value):
        self.notes_card.flush()
        errors = []
        for r in recs:
            if r.favorite != value:
                err = write_notes(r.path, value, r.notes)
                if err:
                    errors.append(err)
                else:
                    r.favorite = value
        if errors:
            more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
            self.statusBar().showMessage(errors[0] + more, 8000)
        if self.fav_only:
            self.populate()
        else:
            self.refresh_annotations()
            self.notes_card.show_recordings(self.selected_recordings())

    def make_row(self, name, start, dur, size, msgs, sensors, obj):
        item = SortItem()
        item.setData(COL_NAME, OBJ_ROLE, obj)
        for col, text, key in ((COL_NAME, name, name), (COL_START, fmt_time(start), start),
                               (COL_DUR, fmt_dur(dur), dur), (COL_SIZE, fmt_size(size), size),
                               (COL_MSGS, f"{msgs:,}", msgs)):
            item.setText(col, text)
            item.setData(col, SORT_ROLE, key)
        item.setToolTip(COL_NAME, getattr(obj, "path", ""))
        topics = obj.topics if isinstance(obj, Bag) else [t for b in obj.bags for t in b.topics]
        for i, s in enumerate(self.sensors):
            col = len(FIXED_HEADERS) + i
            st = sensors.get(s)
            item.setData(col, SORT_ROLE, {"ok": 3, "partial": 2, "empty": 1}.get(st, 0))
            item.setData(col, STATUS_ROLE, st or "")
            if not st:
                continue
            lines = [f"{t.name}: {t.count:,} msgs" + (f" ({t.count / (dur / 1e9):.1f} Hz)" if isinstance(obj, Bag) and dur else "")
                     for t in topics if t.sensor == s]
            item.setToolTip(col, f"{s[1]} — {STATUS_DESC[st]}\n" + "\n".join(sorted(set(lines))))
        return item

    def distance_of(self, rec, window=(None, None)):
        """(text, sort key, tooltip, tone) for the distance driven in `window` of a recording."""
        track = self.jobs.tracks.get(rec.path)
        if not HAVE_ROS:
            return "n/a", None, "rosbag2_py not available (source ROS 2)", "faint"
        if track is None:
            return "…", None, "extracting…", "faint"
        if not track.get("source"):
            return "—", None, track.get("error") or "no GNSS or odometry/twist data", "faint"
        d = track_distance(track, *window)
        if track["source"] == "gnss":
            return fmt_dist(d), d, f"from {track['topic']}", None
        return "≈ " + fmt_dist(d), d, f"dead-reckoned from {track['topic']} (no GNSS)", None

    def refresh_distances(self):
        for item in self.all_items():
            rec, obj = item.data(COL_NAME, REC_ROLE), item.data(COL_NAME, OBJ_ROLE)
            window = (obj.start_ns, obj.end_ns) if isinstance(obj, Bag) else (None, None)
            text, key, tip, tone = self.distance_of(rec, window)
            item.setText(COL_DIST, text)
            item.setData(COL_DIST, SORT_ROLE, key)
            item.setData(COL_DIST, TONE_ROLE, tone)
            item.setToolTip(COL_DIST, tip)

    # -- column visibility and expand/collapse
    def apply_columns(self):
        for i, name in enumerate(FIXED_HEADERS):
            if i != COL_NAME:
                self.tree.setColumnHidden(i, name in self.hidden_cols)
        self.tree.setColumnHidden(self.tree.columnCount() - 1, "Notes" in self.hidden_cols)
        for i, s in enumerate(self.sensors):
            self.tree.setColumnHidden(len(FIXED_HEADERS) + i, s[1] in self.hidden_sensors)
        self.tree.header().set_sensors(self.sensors, self.required)
        self.tree.updateGeometries()

    def save_columns(self):
        store().setValue("hidden_columns", sorted(self.hidden_cols))
        store().setValue("hidden_sensors", sorted(self.hidden_sensors))
        self.apply_columns()

    def set_column_shown(self, name, shown):
        (self.hidden_cols.discard if shown else self.hidden_cols.add)(name)
        self.save_columns()

    def set_sensors_shown(self, names, shown):
        for n in names:
            (self.hidden_sensors.discard if shown else self.hidden_sensors.add)(n)
        self.save_columns()

    def reset_columns(self):
        self.hidden_cols.clear()
        self.hidden_sensors.clear()
        self.save_columns()

    def fill_columns_menu(self, menu):
        menu.clear()
        for name in FIXED_HEADERS[1:] + ["Notes"]:
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(name not in self.hidden_cols)
            a.toggled.connect(lambda on, n=name: self.set_column_shown(n, on))
        n_hidden = sum(s[1] in self.hidden_sensors for s in self.sensors)
        sub = StickyMenu(f"Sensor columns ({len(self.sensors) - n_hidden} of {len(self.sensors)} shown)", menu)
        menu.addMenu(sub)
        names = [s[1] for s in self.sensors]
        sub.addAction("Show all", lambda: self.set_sensors_shown(names, True))
        sub.addAction("Hide all", lambda: self.set_sensors_shown(names, False))
        kind = None
        for s in self.sensors:
            if s[0] != kind:
                kind = s[0]
                sub.addSection(KIND_LABEL[kind])
            a = sub.addAction(s[1])
            a.setCheckable(True)
            a.setChecked(s[1] not in self.hidden_sensors)
            a.toggled.connect(lambda on, n=s[1]: self.set_sensors_shown([n], on))
        menu.addSeparator()
        menu.addAction("Show all columns", self.reset_columns)

    def header_menu(self, pos):
        menu = StickyMenu(self)
        self.fill_columns_menu(menu)
        menu.exec(self.tree.header().mapToGlobal(pos))

    def expand_all(self):
        self.tree.expandAll()

    def collapse_all(self):
        self.tree.collapseAll()

    # -- sorting and the sensor filter
    def sort_changed(self, col, order):
        if self.tree.header().is_sensor(col):  # sensor headers filter instead of sorting
            QTimer.singleShot(0, lambda: self.tree.sortByColumn(*self.sort_state))
        else:
            self.sort_state = (col, order)

    def header_clicked(self, col):
        i = col - len(FIXED_HEADERS)
        if 0 <= i < len(self.sensors):
            self.toggle_required(self.sensors[i])

    def toggle_required(self, s):
        self.required ^= {s}
        self.populate()

    def clear_required(self):
        self.required.clear()
        self.populate()

    def update_header_highlight(self):
        hdr = self.tree.header()
        hdr.required = self.required
        hdr.viewport().update()
        clear_layout(self.chips)
        if not self.required:
            self.chips.addWidget(QLabel("Click a sensor column to show only recordings that have it",
                                        objectName="muted"))
            return
        self.chips.addWidget(QLabel("Recordings with", objectName="muted"))
        t = theme.current
        for s in sorted(self.required, key=lambda s: (KIND_ORDER[s[0]], s[1])):
            chip = QToolButton(objectName="chip", text=s[1], toolTip="Remove from filter")
            chip.setIcon(icons.icon("close", t.accent, 12))
            chip.setLayoutDirection(Qt.RightToLeft)
            chip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, s=s: self.toggle_required(s))
            self.chips.addWidget(chip)
        if len(self.required) > 1:
            self.chips.addWidget(QLabel("(bags with any of them)", objectName="muted"))
        clear = QToolButton(objectName="link", text="Clear")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self.clear_required)
        self.chips.addWidget(clear)

    # -- selection / details
    def selected_bags(self):
        bags = []
        for it in self.tree.selectedItems():
            obj = it.data(COL_NAME, OBJ_ROLE)
            if isinstance(obj, Recording):
                kids = [it.child(i).data(COL_NAME, OBJ_ROLE) for i in range(it.childCount())]
                bags += [b for b in kids if b not in bags]
            elif obj not in bags:
                bags.append(obj)
        return bags

    def update_details(self):
        bags = self.selected_bags()
        self.update_media()
        self.notes_card.show_recordings(self.selected_recordings())
        self.update_topics(bags)
        self.overview.setText(self.overview_html(bags))

    def overview_html(self, bags):
        t = theme.current

        def table(rows):
            cells = "".join(f"<tr><td style='color:{t.muted}; padding:2px 18px 2px 0'>{k}</td>"
                            f"<td style='padding:2px 0'>{v}</td></tr>" for k, v in rows)
            return f"<table cellspacing='0' cellpadding='0' style='margin-top:10px'>{cells}</table>"

        def breakable(s):  # allow wrapping long bag names and paths at separators
            return html.escape(s).replace("/", "/&#8203;").replace("_", "_&#8203;").replace("-", "-&#8203;")

        def head(title, sub):
            return (f"<div style='font-size:13pt; font-weight:600'>{breakable(title)}</div>"
                    f"<div style='color:{t.muted}; margin-top:2px'>{sub}</div>")

        def path_line(path):
            return f"<div style='color:{t.muted}; font-size:8.5pt; margin-top:8px'>{breakable(path)}</div>"

        if not bags:
            all_bags = [b for r in self.recordings for b in r.bags]
            starts = [r.start_ns for r in self.recordings if r.start_ns]
            folders = "".join(path_line(r) + ("" if os.path.isdir(r) else
                                              f"<div style='color:{t.empty}; font-size:8.5pt'>not found</div>")
                              for r in self.roots)
            return head(f"{len(self.recordings)} recordings", "Select a recording or bag for details") + table([
                ("Bags", f"{len(all_bags):,}"),
                ("Size", fmt_size(sum(b.size for b in all_bags))),
                ("Recorded", fmt_dur(sum(r.end_ns - r.start_ns for r in self.recordings))),
                ("First", fmt_time(min(starts, default=0))),
                ("Last", fmt_time(max((r.end_ns for r in self.recordings), default=0))),
            ]) + folders
        items = self.tree.selectedItems()
        rec = items[0].data(COL_NAME, REC_ROLE)
        whole = any(it.data(COL_NAME, OBJ_ROLE) is rec for it in items) and len(bags) == len(rec.bags)
        start = min((b.start_ns for b in bags if b.start_ns), default=0)
        end = max((b.end_ns for b in bags if b.start_ns), default=0)
        dist_text, _, _, tone = self.distance_of(rec, (None, None) if whole else (start, end))
        dist = dist_text if not tone else f"<span style='color:{t.faint}'>{dist_text}</span>"
        rows = [("Start", fmt_time(start)), ("End", fmt_time(end)), ("Duration", fmt_dur(end - start)),
                ("Distance", dist), ("Size", fmt_size(sum(b.size for b in bags))),
                ("Messages", f"{sum(b.message_count for b in bags):,}")]
        rows.append(("Gaps", self.gaps_text(bags)))
        if len(bags) == 1:
            b = bags[0]
            rows.append(("Storage", b.storage or "?"))
            if not self.jobs.finalized(b):
                rows.append(("Index", f"<span style='color:{t.empty}'>not finalized</span>"))
            out = head(b.name, f"Bag in {html.escape(rec.name)}") + table(rows)
            if b.extras:
                out += f"<div style='margin-top:8px; color:{t.muted}'>Also: {html.escape(', '.join(b.extras))}</div>"
            if b.error:
                out += f"<div style='margin-top:8px; color:{t.empty}'>{html.escape(b.error)}</div>"
            return out + path_line(b.path)
        title = rec.name if whole else f"{len(bags)} bags"
        sub = (f"Recording · {len(bags)} bags" if whole else f"Selected in {html.escape(rec.name)}") \
            + (f" · {html.escape(self.prefix(rec))}" if self.prefix(rec) else "")
        return head(title, sub) + table(rows) + path_line(rec.path)

    def update_topics(self, bags):
        n, n_empty = self.topics.show_bags(bags, self.jobs, self.gap_threshold())
        self.topics_card.set_title(f"Topics · {n}" + (f" · {n_empty} empty" if n_empty else "") if n else "Topics")

    def update_media(self):
        """Map + thumbnail for the current selection (first selected recording)."""
        items = self.tree.selectedItems()
        if not items:
            self.map.show_track(None, message="Select a recording to see its route")
            self.thumb.show_image(None, "Select a recording to see a camera frame")
            return
        rec = items[0].data(COL_NAME, REC_ROLE)
        bags = [b for b in self.selected_bags() if b in rec.bags]
        whole = any(it.data(COL_NAME, OBJ_ROLE) is rec for it in items)
        track = self.jobs.tracks.get(rec.path)
        if not HAVE_ROS:
            self.map.show_track(None, message="Source ROS 2 to see the route")
        elif track is None:
            self.map.show_track(None, message="Extracting route…")
        elif not track.get("source"):
            self.map.show_track(None, message="No GNSS or odometry data in this recording")
        else:
            window = None if whole or not bags else (min(b.start_ns for b in bags), max(b.end_ns for b in bags))
            self.map.show_track(track, window)
        # thumbnail: the recording's preferred camera, or the selected bag's own camera
        cams, image_types = self.cfg["thumbnails"]["cameras"], self.cfg["thumbnails"]["image_types"]
        tb = rec.thumb_bag(cams, image_types) if whole else next((b for b in bags if b.thumb_topic(cams, image_types)), None)
        if not HAVE_ROS:
            self.thumb.show_image(None, "Source ROS 2 to see camera frames")
        elif tb is None:
            images = any(t.type in image_types and t.count for b in (rec.bags if whole else bags) for t in b.topics)
            self.thumb.show_image(None, "None of the cameras chosen under “Cameras” has images here" if images else
                                  "No camera images" + ("" if whole else " in this bag"))
        elif tb.path not in self.jobs.thumbs:
            self.thumb.show_image(None, "Extracting frame…")
        else:
            tt = tb.thumb_topic(cams, image_types)
            self.thumb.show_image(self.jobs.thumbs[tb.path], "Could not decode the image", tt.sensor[1],
                                  f"{tt.name}\n{tb.name}")

    # -- actions
    def context_menu(self, pos):
        if not self.tree.selectedItems():
            return
        t = theme.current
        m = QMenu(self)
        m.addAction(icons.icon("copy", t.muted), "Copy bag paths", self.copy_paths)
        m.addAction(icons.icon("play", t.muted), "Copy `ros2 bag play` command", self.copy_play)
        m.addAction(icons.icon("folder", t.muted), "Open folder", self.open_folder)
        m.addSeparator()
        recs = self.selected_recordings()
        fav = bool(recs) and all(r.favorite for r in recs)
        m.addAction(icons.icon("star", t.partial, 16, "none" if fav else t.partial),
                    ("Remove recording from favorites" if fav else "Add recording to favorites") if len(recs) == 1
                    else ("Remove recordings from favorites" if fav else "Add recordings to favorites"),
                    lambda: self.set_favorite(recs, not fav))
        edit = m.addAction("Edit recording notes", lambda: self.notes_card.edit.setFocus())
        edit.setEnabled(len(recs) == 1)
        m.addSeparator()
        m.addAction(icons.icon("expand", t.muted), "Expand all", self.expand_all)
        m.addAction(icons.icon("collapse", t.muted), "Collapse all", self.collapse_all)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def copy_paths(self):
        bags = self.selected_bags()
        QApplication.clipboard().setText("\n".join(b.path for b in bags))
        self.statusBar().showMessage(f"Copied {len(bags)} path(s)", 3000)

    def copy_play(self):
        bags = self.selected_bags()
        QApplication.clipboard().setText("ros2 bag play " + " ".join(f"-i {shlex.quote(b.path)}" for b in bags))
        self.statusBar().showMessage(f"Copied play command for {len(bags)} bag(s)", 4000)

    def open_folder(self):
        items = self.tree.selectedItems()
        if items:
            obj = items[0].data(COL_NAME, OBJ_ROLE)
            subprocess.Popen(["xdg-open", obj.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def prefix(self, rec):
        """Folder label shown before recording names, when more than one folder is open."""
        return self.labels.get(rec.root, "") if len(self.roots) > 1 else ""

    def update_folders(self):
        self.folder_bar.set_roots(self.roots, self.labels)

    def set_roots(self, roots):
        new = list(dict.fromkeys(os.path.abspath(r) for r in roots))[:MAX_ROOTS]
        if len(new) < len(roots):
            self.statusBar().showMessage("That folder is already open", 4000)
        if new == self.roots:
            return
        self.roots = new
        store().setValue("roots", new)
        self.reload()

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.join(self.roots[0], "bag_catalog.csv"), "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["folder", "recording", "bag", "path", "start", "duration_s", "distance_m", "distance_source",
                        "size_bytes", "messages", "gaps", "finalized", "recording_favorite", "recording_notes"] + [s[1] for s in self.sensors] + ["files"])
            for rec in self.recordings:
                track = self.jobs.tracks.get(rec.path) or {}
                for b in rec.bags:
                    st = b.sensors()
                    dist = f"{track_distance(track, b.start_ns, b.end_ns):.0f}" if track.get("source") else ""
                    w.writerow([rec.root, rec.name, b.name, b.path, fmt_time(b.start_ns), f"{b.duration_ns / 1e9:.3f}",
                                dist, track.get("source") or "", b.size, b.message_count,
                                merge_gaps(self.bag_gaps(b) or {}) if self.bag_gaps(b) is not None else "",
                                int(self.jobs.finalized(b)),
                                int(rec.favorite), rec.notes]
                               + [st.get(s, "") for s in self.sensors]
                               + ["; ".join(b.extras + ([b.error] if b.error else []))])
        self.statusBar().showMessage(f"Wrote {path}", 5000)

    def closeEvent(self, e):
        self.notes_card.flush()
        self.save_profile()
        self.jobs.stop()
        super().closeEvent(e)
