"""The Topics table: one row per topic of the selected bags, with rate, resolution, gaps and counts."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from .. import theme
from ..extract import topic_gaps
from ..fmt import fmt_clock
from .common import tabular
from .tree import SORT_ROLE

TOPIC_COLS = ["Topic", "Hz", "Resolution", "Gaps", "Messages", "Type", "Sensor", "Bag"]


class TableItem(QTableWidgetItem):
    def __lt__(self, other):
        return (self.data(SORT_ROLE), self.text()) < (other.data(SORT_ROLE), other.text())


class TopicsTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(TOPIC_COLS), parent)
        self.setHorizontalHeaderLabels(TOPIC_COLS)
        for col, tip in (("Hz", "Typical rate: from the median interval between messages"),
                         ("Gaps", "Number of gaps · longest one (threshold set under “Gaps” in the bar above)"),
                         ("Messages", "Messages in the file (red when fewer than metadata.yaml lists)")):
            self.horizontalHeaderItem(TOPIC_COLS.index(col)).setToolTip(tip)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeader().setHighlightSections(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)  # topic names: keep both the namespace and the leaf
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.AscendingOrder)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(26)
        self.setFont(tabular(self.font()))

    def show_bags(self, bags, jobs, gap_threshold):
        """Fill the table with the topics of `bags`, using the statistics in `jobs` (a JobRunner).
        Returns (number of topics, number of them with no messages)."""
        t = theme.current
        self.setSortingEnabled(False)
        rows = [(b, tp) for b in bags for tp in b.topics]
        self.setRowCount(len(rows))
        for r, (b, tp) in enumerate(rows):
            st = jobs.topic_stat(b, tp.name)
            avg = tp.count / (b.duration_ns / 1e9) if b.duration_ns else 0
            gaps = topic_gaps(st, *gap_threshold) if st else []
            size = st.get("size") if st else None
            # (text, sort key, tooltip, tone)
            if st and st["median_dt"]:
                hz = 1e9 / st["median_dt"]
                hz_cell = (f"{hz:.1f}", hz, f"{hz:.2f} Hz typical (median interval {st['median_dt'] / 1e6:.1f} ms)\n"
                                           f"{avg:.2f} Hz on average over the bag", None)
            else:
                hz_cell = (f"{avg:.1f}" if avg else "—", avg,
                           "average over the bag" + ("" if st else " (measuring…)" if b.path not in jobs.topic_stats else ""), None)
            if st and st["n"] < tp.count:
                fix = ("`ros2 bag reindex <bag folder>` updates metadata.yaml to match the file." if jobs.finalized(b) else
                       "The file isn't finalized: repair it with `mcap recover` first, then `ros2 bag reindex`.")
                msgs_cell = (f"{st['n']:,} of {tp.count:,}", st["n"],
                             f"metadata.yaml lists {tp.count:,} messages, but only {st['n']:,} are in the file.\n{fix}",
                             "empty")
            else:
                msgs_cell = (f"{tp.count:,}", tp.count, "", None)
            if gaps:
                longest = max(g[1] for g in gaps) / 1e9
                lines = [f"{fmt_clock(g[0])}  +{(g[0] - b.start_ns) / 1e9:7.1f} s   {g[1] / 1e9:.2f} s"
                         + ("   (no data until the end)" if g[0] + g[1] >= b.end_ns else "") for g in gaps[:15]]
                more = f"\n…and {len(gaps) - 15} more" if len(gaps) > 15 else ""
                gap_cell = (f"{len(gaps)} · {longest:.2f} s", (len(gaps), longest),
                            "time       into bag   length\n" + "\n".join(lines) + more, "partial")
            else:
                gap_cell = ("—" if st else "…", (0, 0), "no gaps" if st else "not measured yet", "faint")
            cells = [(tp.name, tp.name, tp.name, None), hz_cell,
                     (f"{size[0]}×{size[1]}" if size else "", size[0] * size[1] if size else 0, "", None),
                     gap_cell, msgs_cell, (tp.type, tp.type, "", "muted"), (tp.sensor[1], tp.sensor[1], "", "muted"),
                     (b.name, b.name, "", "muted")]
            for c, (text, key, tip, tone) in enumerate(cells):
                it = TableItem(text)
                it.setData(SORT_ROLE, key)
                it.setToolTip(tip)
                if c in (1, 2, 4):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if tp.count == 0:
                    tone = "empty"
                if tone == "partial":
                    it.setForeground(t.c("partial") if t.dark else t.c("partial").darker(135))
                elif tone:
                    it.setForeground(t.c(tone))
                self.setItem(r, c, it)
        self.setColumnHidden(TOPIC_COLS.index("Bag"), len(bags) < 2)
        self.setColumnHidden(TOPIC_COLS.index("Resolution"),
                             not any("size" in (jobs.topic_stat(b, tp.name) or {}) for b, tp in rows))
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            self.setColumnWidth(c, min(self.columnWidth(c) + 8, 190 if c == 0 else 200))
        return len(rows), sum(1 for _, tp in rows if tp.count == 0)
