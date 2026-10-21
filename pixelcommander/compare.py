"""Compare files by content (diff) and synchronize directories."""
import difflib
import filecmp
import os
import shutil

from .qt import QtCore, QtGui, QtWidgets, Qt, qexec, QShortcut
from .utils import Mask, format_size, format_time, human_size, is_text_file


COLORS = {"del": "#ffc8c8", "ins": "#c8f0c8", "chg_a": "#ffd8b0", "chg_b": "#ffd8b0", "pad": "#e4e4e4"}


def _hex_lines(path, limit=4 * 2 ** 20):
    with open(path, "rb") as fh:
        data = fh.read(limit)
    out = []
    for i in range(0, len(data), 16):
        c = data[i:i + 16]
        out.append("%08X  %-47s  %s" % (i, " ".join("%02X" % b for b in c),
                                         "".join(chr(b) if 32 <= b < 127 else "." for b in c)))
    return out


class CompareTool(QtWidgets.QMainWindow):
    """Compare two files side by side (text diff or hex for binaries), copy blocks, edit and save."""
    open_windows = []

    def __init__(self, left=None, right=None, parent=None):
        super().__init__(parent)
        from .editor import CodeEdit
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Dateien vergleichen")
        self.lines = [[], []]
        self.enc = ["utf-8", "utf-8"]
        self.nl = ["\n", "\n"]
        self.binary = [False, False]
        self.modified = [False, False]
        self.blocks = []
        self.cur = -1
        self.editing = False

        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QtWidgets.QHBoxLayout()
        self.path_edits = []
        for side in (0, 1):
            ed = QtWidgets.QLineEdit()
            ed.setPlaceholderText("Datei %s wählen oder hierher ziehen…" % ("links" if side == 0 else "rechts"))
            ed.returnPressed.connect(lambda s=side: self.load_side(s, self.path_edits[s].text()))
            btn = QtWidgets.QToolButton()
            btn.setText("…")
            btn.setToolTip("Datei auswählen")
            btn.clicked.connect(lambda _c=False, s=side: self.pick(s))
            self.path_edits.append(ed)
            top.addWidget(ed, 1)
            top.addWidget(btn)
            if side == 0:
                sw = QtWidgets.QToolButton()
                sw.setText("⇄")
                sw.setToolTip("Seiten tauschen")
                sw.clicked.connect(self.swap)
                top.addWidget(sw)
        lay.addLayout(top)

        tb = QtWidgets.QHBoxLayout()

        def btn(text, slot, tip=None, key=None):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            if tip or key:
                b.setToolTip((tip or text) + (" (%s)" % key if key else ""))
            if key:
                sc = QShortcut(QtGui.QKeySequence(key), self)
                sc.activated.connect(slot)
            tb.addWidget(b)
            return b

        btn("Vergleichen", self.compare, key="F5")
        btn("▲ Vorheriger", lambda: self.jump(-1), "Vorheriger Unterschied", "Shift+F8")
        btn("▼ Nächster", lambda: self.jump(1), "Nächster Unterschied", "F8")
        self.to_right = btn("Block →", lambda: self.copy_block(0), "Aktuellen Block nach rechts kopieren", "Alt+Right")
        self.to_left = btn("← Block", lambda: self.copy_block(1), "Aktuellen Block nach links kopieren", "Alt+Left")
        self.edit_btn = QtWidgets.QPushButton("Bearbeiten")
        self.edit_btn.setCheckable(True)
        self.edit_btn.toggled.connect(self.set_editing)
        tb.addWidget(self.edit_btn)
        btn("Links speichern", lambda: self.save(0), key="Ctrl+S")
        btn("Rechts speichern", lambda: self.save(1), key="Ctrl+Shift+S")
        self.ignore_ws = QtWidgets.QCheckBox("Leerzeichen ign.")
        self.ignore_case = QtWidgets.QCheckBox("Groß/klein ign.")
        self.ignore_ws.toggled.connect(self.compare)
        self.ignore_case.toggled.connect(self.compare)
        tb.addWidget(self.ignore_ws)
        tb.addWidget(self.ignore_case)
        tb.addStretch(1)
        lay.addLayout(tb)

        sp = QtWidgets.QSplitter()
        self.panes = []
        for side in (0, 1):
            e = CodeEdit()
            e.setReadOnly(True)
            e.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
            e.highlight_line = False
            e.fileDropped.connect(lambda p, s=side: self.load_side(s, p))
            e.document().modificationChanged.connect(lambda m, s=side: self._mark_mod(s, m))
            sp.addWidget(e)
            self.panes.append(e)
        a, b = self.panes
        a.verticalScrollBar().valueChanged.connect(b.verticalScrollBar().setValue)
        b.verticalScrollBar().valueChanged.connect(a.verticalScrollBar().setValue)
        a.horizontalScrollBar().valueChanged.connect(b.horizontalScrollBar().setValue)
        b.horizontalScrollBar().valueChanged.connect(a.horizontalScrollBar().setValue)
        lay.addWidget(sp, 1)
        self.setCentralWidget(w)
        self.info = QtWidgets.QLabel()
        self.statusBar().addWidget(self.info, 1)
        QShortcut(QtGui.QKeySequence("Esc"), self, self.close)
        self.resize(1200, 760)
        for side, p in ((0, left), (1, right)):
            if p:
                self.load_side(side, p, compare=False)
        self.compare()
        CompareTool.open_windows.append(self)
        self.destroyed.connect(lambda *_: CompareTool.open_windows.remove(self)
                               if self in CompareTool.open_windows else None)

    # ------------------------------------------------------------ loading / saving
    def pick(self, side):
        start = self.path_edits[side].text() or self.path_edits[1 - side].text() or os.getcwd()
        p, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Datei wählen", os.path.dirname(start))
        if p:
            self.load_side(side, p)

    def load_side(self, side, path, compare=True):
        from .editor import read_text
        if not self._confirm_discard(side):
            return
        path = os.path.expanduser(path.strip())
        self.path_edits[side].setText(path)
        if not os.path.isfile(path):
            if path:
                self.info.setText("Datei nicht gefunden: " + path)
            self.lines[side] = []
            return
        try:
            if is_text_file(path):
                text, self.enc[side], self.nl[side], _b = read_text(path)
                self.lines[side] = text.split("\n")
                self.binary[side] = False
            else:
                self.lines[side] = _hex_lines(path)
                self.binary[side] = True
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Vergleichen", str(ex))
            return
        self.modified[side] = False
        if compare:
            if self.editing:
                self.edit_btn.setChecked(False)
            self.compare()

    def _confirm_discard(self, side):
        if not self.modified[side]:
            return True
        r = QtWidgets.QMessageBox.question(self, "Vergleichen", "Änderungen %s speichern?" % (
            "links" if side == 0 else "rechts"), QtWidgets.QMessageBox.StandardButton.Save |
            QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel)
        if r == QtWidgets.QMessageBox.StandardButton.Save:
            return self.save(side)
        return r == QtWidgets.QMessageBox.StandardButton.Discard

    def save(self, side):
        from .editor import write_text
        path = self.path_edits[side].text()
        if self.binary[side]:
            QtWidgets.QMessageBox.information(self, "Speichern", "Binärdateien (Hex-Ansicht) können nicht gespeichert "
                                              "werden.")
            return False
        if self.editing:
            self._pull(side)
        if not path:
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Speichern unter")
            if not path:
                return False
            self.path_edits[side].setText(path)
        try:
            write_text(path, "\n".join(self.lines[side]), self.enc[side], self.nl[side])
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Speichern", str(ex))
            return False
        self.modified[side] = False
        self.panes[side].document().setModified(False)
        self._update_title()
        self.statusBar().showMessage("Gespeichert: " + path, 3000)
        return True

    def swap(self):
        if self.editing:
            self.edit_btn.setChecked(False)
        for lst in (self.lines, self.enc, self.nl, self.binary, self.modified):
            lst.reverse()
        a, b = self.path_edits[0].text(), self.path_edits[1].text()
        self.path_edits[0].setText(b)
        self.path_edits[1].setText(a)
        self.compare()

    def _mark_mod(self, side, m):
        if m and self.editing:
            self.modified[side] = True
            self._update_title()

    def _update_title(self):
        names = []
        for s in (0, 1):
            n = os.path.basename(self.path_edits[s].text()) or "?"
            names.append(("*" if self.modified[s] else "") + n)
        self.setWindowTitle("Vergleichen: %s ↔ %s" % tuple(names))

    def closeEvent(self, e):
        if self.editing:
            self._pull(0)
            self._pull(1)
        if self._confirm_discard(0) and self._confirm_discard(1):
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------ editing mode
    def _pull(self, side):
        if self.editing and self.panes[side].document().isModified():
            self.lines[side] = self.panes[side].toPlainText().split("\n")
            self.modified[side] = True

    def set_editing(self, on):
        if on:
            self.editing = True
            for s, p in enumerate(self.panes):
                p.number_map = None
                p.set_extra([])
                p.setPlainText("\n".join(self.lines[s]))
                p.document().setModified(False)
                p.setReadOnly(self.binary[s])
                p.highlight_line = True
                p.gutter.update()
            self.to_left.setEnabled(False)
            self.to_right.setEnabled(False)
            self.info.setText("Bearbeitungsmodus – zum Vergleichen „Bearbeiten“ wieder ausschalten (oder F5)")
        else:
            self._pull(0)
            self._pull(1)
            self.editing = False
            for p in self.panes:
                p.setReadOnly(True)
                p.highlight_line = False
            self.to_left.setEnabled(True)
            self.to_right.setEnabled(True)
            self.compare()

    # ------------------------------------------------------------ diff
    def compare(self):
        if self.editing:
            self.edit_btn.setChecked(False)  # triggers compare via set_editing
            return
        la, lb = self.lines

        def norm(lines):
            out = lines
            if self.ignore_ws.isChecked():
                out = [" ".join(x.split()) for x in out]
            if self.ignore_case.isChecked():
                out = [x.lower() for x in out]
            return out

        sm = difflib.SequenceMatcher(None, norm(la), norm(lb), autojunk=False)
        rows_a, rows_b, num_a, num_b, kinds = [], [], [], [], []
        self.blocks = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    rows_a.append(la[i1 + k])
                    rows_b.append(lb[j1 + k])
                    num_a.append(i1 + k + 1)
                    num_b.append(j1 + k + 1)
                    kinds.append(None)
                continue
            start = len(rows_a)
            for k in range(max(i2 - i1, j2 - j1)):
                ha, hb = i1 + k < i2, j1 + k < j2
                rows_a.append(la[i1 + k] if ha else "")
                rows_b.append(lb[j1 + k] if hb else "")
                num_a.append(i1 + k + 1 if ha else None)
                num_b.append(j1 + k + 1 if hb else None)
                kinds.append((tag, ha, hb))
            self.blocks.append((tag, i1, i2, j1, j2, start, len(rows_a)))
        self.kinds = kinds
        for p, rows, nums in ((self.panes[0], rows_a, num_a), (self.panes[1], rows_b, num_b)):
            vs = p.verticalScrollBar().value()
            p.number_map = nums
            p.setPlainText("\n".join(rows))
            p.document().setModified(False)
            p.verticalScrollBar().setValue(vs)
            p.gutter.update()
        if self.cur >= len(self.blocks):
            self.cur = len(self.blocks) - 1
        self._paint()
        self._update_title()
        if not self.path_edits[0].text() or not self.path_edits[1].text():
            self.info.setText("Bitte zwei Dateien wählen (Pfad eingeben, „…“ oder Datei hierher ziehen).")
        elif not self.blocks:
            self.info.setText("Die Dateien sind identisch%s." % (
                " (bis auf ignorierte Unterschiede)" if self.ignore_ws.isChecked() or self.ignore_case.isChecked()
                else ""))
        else:
            kind = " – Binärvergleich (Hex)" if any(self.binary) else ""
            self.info.setText("%d Unterschied(e)%s   |   links %d Zeilen, rechts %d Zeilen" % (
                len(self.blocks), kind, len(la), len(lb)))

    def _sel(self, pane, row, color, strong=False):
        s = QtWidgets.QTextEdit.ExtraSelection()
        c = QtGui.QColor(color)
        if strong:
            c = c.darker(118)
        s.format.setBackground(c)
        s.format.setForeground(QtGui.QBrush(QtGui.QColor("#000000")))
        s.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
        s.cursor = QtGui.QTextCursor(pane.document().findBlockByNumber(row))
        return s

    def _paint(self):
        sa, sb = [], []
        cur_rng = None
        if 0 <= self.cur < len(self.blocks):
            cur_rng = self.blocks[self.cur][5:7]
        for row, k in enumerate(self.kinds):
            if k is None:
                continue
            tag, ha, hb = k
            strong = cur_rng is not None and cur_rng[0] <= row < cur_rng[1]
            if tag == "replace":
                ca = COLORS["chg_a"] if ha else COLORS["pad"]
                cb = COLORS["chg_b"] if hb else COLORS["pad"]
            elif tag == "delete":
                ca, cb = COLORS["del"], COLORS["pad"]
            else:
                ca, cb = COLORS["pad"], COLORS["ins"]
            sa.append(self._sel(self.panes[0], row, ca, strong))
            sb.append(self._sel(self.panes[1], row, cb, strong))
        self.panes[0].set_extra(sa)
        self.panes[1].set_extra(sb)

    def _block_at_cursor(self):
        for p in self.panes:
            if p.hasFocus():
                row = p.textCursor().blockNumber()
                for i, b in enumerate(self.blocks):
                    if b[5] <= row < b[6]:
                        return i
        return self.cur

    def jump(self, d):
        if not self.blocks:
            return
        if self.editing:
            self.edit_btn.setChecked(False)
        self.cur = (self.cur + d) % len(self.blocks) if self.cur >= 0 else (0 if d > 0 else len(self.blocks) - 1)
        row = self.blocks[self.cur][5]
        for p in self.panes:
            c = QtGui.QTextCursor(p.document().findBlockByNumber(row))
            p.setTextCursor(c)
        self.panes[0].centerCursor()
        self._paint()
        self.statusBar().showMessage("Unterschied %d von %d" % (self.cur + 1, len(self.blocks)), 2000)

    def copy_block(self, from_side):
        i = self._block_at_cursor()
        if not (0 <= i < len(self.blocks)):
            self.statusBar().showMessage("Zuerst einen Unterschied auswählen (F8 oder hineinklicken)", 3000)
            return
        to = 1 - from_side
        if self.binary[to]:
            return
        tag, i1, i2, j1, j2, _s, _e = self.blocks[i]
        src = [(i1, i2), (j1, j2)]
        a1, a2 = src[from_side]
        b1, b2 = src[to]
        self.lines[to][b1:b2] = self.lines[from_side][a1:a2]
        self.modified[to] = True
        self.cur = i
        self.compare()


DiffDialog = CompareTool


# ---------------------------------------------------------------- sync dirs

ACTIONS = {"right": "→", "left": "←", "none": "", "equal": "=", "neq": "≠"}


class SyncDirsDialog(QtWidgets.QDialog):
    def __init__(self, left, right, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verzeichnisse synchronisieren")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        lay = QtWidgets.QVBoxLayout(self)
        g = QtWidgets.QGridLayout()
        self.left = QtWidgets.QLineEdit(left)
        self.right = QtWidgets.QLineEdit(right)
        self.mask = QtWidgets.QLineEdit("*")
        g.addWidget(QtWidgets.QLabel("Links:"), 0, 0)
        g.addWidget(self.left, 0, 1)
        g.addWidget(QtWidgets.QLabel("Rechts:"), 0, 2)
        g.addWidget(self.right, 0, 3)
        g.addWidget(QtWidgets.QLabel("Dateien:"), 1, 0)
        g.addWidget(self.mask, 1, 1)
        opts = QtWidgets.QHBoxLayout()
        self.subdirs = QtWidgets.QCheckBox("Unterverzeichnisse")
        self.subdirs.setChecked(True)
        self.by_content = QtWidgets.QCheckBox("nach Inhalt")
        self.ignore_date = QtWidgets.QCheckBox("Datum ignorieren")
        self.asym = QtWidgets.QCheckBox("asymmetrisch (rechts = Kopie von links)")
        for w in (self.subdirs, self.by_content, self.ignore_date, self.asym):
            opts.addWidget(w)
        g.addLayout(opts, 1, 2, 1, 2)
        lay.addLayout(g)
        flt = QtWidgets.QHBoxLayout()
        flt.addWidget(QtWidgets.QLabel("Anzeigen:"))
        self.show_flags = {}
        for key, label in [("right", "→"), ("equal", "="), ("neq", "≠"), ("left", "←"), ("dups", "Duplikate"),
                           ("singles", "Einzelne")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(key != "equal")
            c.toggled.connect(self.fill)
            self.show_flags[key] = c
            flt.addWidget(c)
        flt.addStretch(1)
        cmp_btn = QtWidgets.QPushButton("Vergleichen")
        cmp_btn.setDefault(True)
        cmp_btn.clicked.connect(self.compare)
        flt.addWidget(cmp_btn)
        lay.addLayout(flt)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name links", "Größe", "Datum", "Aktion", "Datum", "Größe",
                                              "Name rechts"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.cell_clicked)
        self.table.cellDoubleClicked.connect(self.cell_dbl)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.ctx_menu)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel()
        row.addWidget(self.info, 1)
        self.del_missing = QtWidgets.QCheckBox("Im Ziel fehlende löschen (bei asymmetrisch)")
        row.addWidget(self.del_missing)
        sync_btn = QtWidgets.QPushButton("Synchronisieren…")
        sync_btn.clicked.connect(self.synchronize)
        close = QtWidgets.QPushButton("Schließen")
        close.clicked.connect(self.accept)
        row.addWidget(sync_btn)
        row.addWidget(close)
        lay.addLayout(row)
        self.items = []
        self.resize(1150, 700)

    def _scan(self, base, mask, recursive):
        res = {}
        for root, dirs, files in os.walk(base):
            if not recursive:
                dirs[:] = []
            for f in files:
                if not mask.match(f):
                    continue
                p = os.path.join(root, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                res[os.path.relpath(p, base)] = (st.st_size, st.st_mtime)
            for d in dirs:
                p = os.path.join(root, d)
                rel = os.path.relpath(p, base)
                res.setdefault(rel + "/", (None, None))
        return res

    def compare(self):
        L, R = self.left.text(), self.right.text()
        if not (os.path.isdir(L) and os.path.isdir(R)):
            QtWidgets.QMessageBox.warning(self, "Synchronisieren", "Beide Seiten müssen Verzeichnisse sein.")
            return
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            m = Mask(self.mask.text())
            a = self._scan(L, m, self.subdirs.isChecked())
            b = self._scan(R, m, self.subdirs.isChecked())
            self.items = []
            for rel in sorted(set(a) | set(b), key=lambda s: s.lower()):
                if rel.endswith("/"):
                    if rel in a and rel in b:
                        continue
                    act = "right" if rel in a else ("left" if not self.asym.isChecked() else "none")
                    if self.asym.isChecked() and rel not in a:
                        act = "delete"
                    self.items.append([rel, a.get(rel), b.get(rel), act, act])
                    continue
                ia, ib = a.get(rel), b.get(rel)
                if ia and ib:
                    same_size = ia[0] == ib[0]
                    if self.by_content.isChecked():
                        eq = same_size and filecmp.cmp(os.path.join(L, rel), os.path.join(R, rel), shallow=False)
                        if eq:
                            act = "equal"
                        elif self.ignore_date.isChecked():
                            act = "neq"
                        else:
                            act = "right" if ia[1] > ib[1] else "left"
                    else:
                        dt = abs(ia[1] - ib[1])
                        if same_size and (self.ignore_date.isChecked() or dt <= 2):
                            act = "equal"
                        elif self.ignore_date.isChecked() or dt <= 2:
                            act = "neq"
                        else:
                            act = "right" if ia[1] > ib[1] else "left"
                    if self.asym.isChecked() and act in ("left", "neq"):
                        act = "right"
                elif ia:
                    act = "right"
                else:
                    act = "delete" if self.asym.isChecked() else "left"
                self.items.append([rel, ia, ib, act, act])
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.fill()

    def visible(self, it):
        rel, ia, ib, orig, act = it
        both = ia is not None and ib is not None
        if both and not self.show_flags["dups"].isChecked():
            return False
        if not both and not self.show_flags["singles"].isChecked():
            return False
        key = orig if orig in ("right", "left", "equal", "neq") else ("left" if orig == "delete" else "right")
        return self.show_flags[key].isChecked()

    def fill(self):
        self.table.setRowCount(0)
        self.rows = []
        n_r = n_l = 0
        for idx, it in enumerate(self.items):
            if not self.visible(it):
                continue
            rel, ia, ib, orig, act = it
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.rows.append(idx)
            vals = [rel if ia else "", format_size(ia[0]) if ia and ia[0] is not None else ("<DIR>" if ia else ""),
                    format_time(ia[1]) if ia and ia[1] else "", self._act_text(act),
                    format_time(ib[1]) if ib and ib[1] else "",
                    format_size(ib[0]) if ib and ib[0] is not None else ("<DIR>" if ib else ""), rel if ib else ""]
            for c, v in enumerate(vals):
                ti = QtWidgets.QTableWidgetItem(v)
                if c == 3:
                    ti.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    f = ti.font()
                    f.setBold(True)
                    ti.setFont(f)
                if act == "right":
                    ti.setForeground(QtGui.QBrush(QtGui.QColor(0, 120, 0)))
                elif act == "left":
                    ti.setForeground(QtGui.QBrush(QtGui.QColor(0, 0, 200)))
                elif act == "neq" or act == "delete":
                    ti.setForeground(QtGui.QBrush(QtGui.QColor(200, 0, 0)))
                self.table.setItem(r, c, ti)
        for it in self.items:
            if it[4] == "right":
                n_r += 1
            elif it[4] == "left":
                n_l += 1
        self.info.setText("%d Einträge – %d → rechts, %d ← links, %d löschen" % (
            len(self.items), n_r, n_l, sum(1 for i in self.items if i[4] == "delete")))

    @staticmethod
    def _act_text(act):
        return {"right": "→", "left": "←", "equal": "=", "neq": "≠", "none": "", "delete": "✗"}[act]

    def cell_clicked(self, r, c):
        if c != 3:
            return
        it = self.items[self.rows[r]]
        cycle = ["right", "left", "none"]
        if it[3] == "delete":
            cycle = ["delete", "none"]
        cur = it[4] if it[4] in cycle else cycle[-1]
        it[4] = cycle[(cycle.index(cur) + 1) % len(cycle)]
        if it[4] == "left" and it[2] is None or it[4] == "right" and it[1] is None:
            it[4] = "none"
        self.table.item(r, 3).setText(self._act_text(it[4]))

    def cell_dbl(self, r, c):
        it = self.items[self.rows[r]]
        if it[1] and it[2] and not it[0].endswith("/"):
            CompareTool(os.path.join(self.left.text(), it[0]), os.path.join(self.right.text(), it[0])).show()

    def ctx_menu(self, pos):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        menu = QtWidgets.QMenu(self)

        def set_all(a):
            for r in rows:
                it = self.items[self.rows[r]]
                if a == "right" and it[1] is None or a == "left" and it[2] is None:
                    continue
                it[4] = a
                self.table.item(r, 3).setText(self._act_text(a))

        menu.addAction("Nach rechts kopieren →", lambda: set_all("right"))
        menu.addAction("← Nach links kopieren", lambda: set_all("left"))
        menu.addAction("Keine Aktion", lambda: set_all("none"))
        menu.addAction("Standard-Aktion", lambda: [self.items[self.rows[r]].__setitem__(4, self.items[self.rows[r]][3])
                                                   for r in rows] and self.fill())
        qexec(menu, self.table.viewport().mapToGlobal(pos))

    def synchronize(self):
        L, R = self.left.text(), self.right.text()
        to_r = [i[0] for i in self.items if i[4] == "right"]
        to_l = [i[0] for i in self.items if i[4] == "left"]
        dels = [i[0] for i in self.items if i[4] == "delete"] if self.del_missing.isChecked() else []
        if not (to_r or to_l or dels):
            return
        if QtWidgets.QMessageBox.question(
                self, "Synchronisieren", "%d Datei(en) nach rechts, %d nach links kopieren, %d rechts löschen?" % (
                    len(to_r), len(to_l), len(dels))) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        jobs = [(os.path.join(L, r), os.path.join(R, r)) for r in to_r] + \
               [(os.path.join(R, r), os.path.join(L, r)) for r in to_l]
        prog = QtWidgets.QProgressDialog("Synchronisiere…", "Abbrechen", 0, len(jobs) + len(dels), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        errors = []
        n = 0
        for s, d in jobs:
            if prog.wasCanceled():
                break
            prog.setLabelText(s)
            prog.setValue(n)
            n += 1
            QtWidgets.QApplication.processEvents()
            try:
                if s.endswith("/"):
                    shutil.copytree(s.rstrip("/"), d.rstrip("/"), symlinks=True, dirs_exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(s, d, follow_symlinks=False)
            except OSError as ex:
                errors.append("%s: %s" % (s, ex))
        for rel in dels:
            if prog.wasCanceled():
                break
            p = os.path.join(R, rel).rstrip("/")
            prog.setValue(n)
            n += 1
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.unlink(p)
            except OSError as ex:
                errors.append("%s: %s" % (p, ex))
        prog.setValue(len(jobs) + len(dels))
        if errors:
            QtWidgets.QMessageBox.warning(self, "Synchronisieren", "\n".join(errors[:30]))
        self.compare()
