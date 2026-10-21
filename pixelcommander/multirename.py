"""Multi-Rename tool (Ctrl+M), modelled after Total Commander's MRT."""
import os
import re
import time

from .config import config
from .qt import QtCore, QtWidgets, Qt
from .utils import split_ext

HELP = ("[N] Name  [N2-5] Zeichen 2–5  [N-3] die letzten 3  [E] Erweiterung  [C] Zähler  "
        "[P] Elternverzeichnis  [Y] [M] [D] Datum  [h] [m] [s] Zeit  [d] JJJJMMTT  [t] hhmmss  "
        "[U] ab hier GROSS  [L] klein  [F] Erster Buchstabe groß  [n] wie Original")


def _slice(s, spec):
    """spec like '', '2', '2-5', '-3', '2-', '3,4' (start,len)."""
    if not spec:
        return s
    try:
        if "," in spec:
            a, n = spec.split(",", 1)
            a = int(a)
            start = a - 1 if a > 0 else len(s) + a
            return s[start:start + int(n)]
        if "-" in spec:
            a, b = spec.split("-", 1)
            if a == "":
                return s[-int(b):]
            a = int(a)
            start = a - 1 if a > 0 else len(s) + a
            if b == "":
                return s[start:]
            b = int(b)
            end = b if b > 0 else len(s) + b + 1
            return s[start:end]
        a = int(spec)
        return s[a - 1:a] if a > 0 else s[a:len(s) + a + 1]
    except ValueError:
        return s


TOKEN = re.compile(r"\[([NEPCYMDhmsdtULFn])([^\]]*)\]")


def apply_mask(mask, name, ext, path, counter, mtime):
    lt = time.localtime(mtime or 0)
    out = []
    case_mode = None
    pos = 0
    for m in TOKEN.finditer(mask):
        lit = mask[pos:m.start()]
        out.append((lit, case_mode))
        pos = m.end()
        t, arg = m.group(1), m.group(2)
        val = ""
        if t == "N":
            val = _slice(name, arg)
        elif t == "E":
            val = _slice(ext, arg)
        elif t == "P":
            val = os.path.basename(os.path.dirname(path))
        elif t == "C":
            val = counter
        elif t == "Y":
            val = time.strftime("%Y", lt)
        elif t == "M":
            val = time.strftime("%m", lt)
        elif t == "D":
            val = time.strftime("%d", lt)
        elif t == "h":
            val = time.strftime("%H", lt)
        elif t == "m":
            val = time.strftime("%M", lt)
        elif t == "s":
            val = time.strftime("%S", lt)
        elif t == "d":
            val = time.strftime("%Y%m%d", lt)
        elif t == "t":
            val = time.strftime("%H%M%S", lt)
        elif t in "ULF":
            case_mode = t
            continue
        elif t == "n":
            case_mode = None
            continue
        out.append((val, case_mode))
    out.append((mask[pos:], case_mode))
    res = []
    for s, cm in out:
        if cm == "U":
            s = s.upper()
        elif cm == "L":
            s = s.lower()
        elif cm == "F":
            s = s[:1].upper() + s[1:].lower()
        res.append(s)
    return "".join(res)


class MultiRenameDialog(QtWidgets.QDialog):
    last_undo = []

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mehrfach-Umbenennen")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.entries = [e for e in entries if not e.is_up and e.path]
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QGridLayout()

        mg = QtWidgets.QGroupBox("Umbenennungsmaske: Dateiname")
        ml = QtWidgets.QVBoxLayout(mg)
        self.name_mask = QtWidgets.QComboBox()
        self.name_mask.setEditable(True)
        self.name_mask.addItems(["[N]"] + [h for h in config.get("rename_history", []) if h != "[N]"])
        ml.addWidget(self.name_mask)
        br = QtWidgets.QHBoxLayout()
        for tok in ["[N]", "[N#-#]", "[C]", "[YMD]", "[hms]", "[P]"]:
            b = QtWidgets.QPushButton(tok)
            b.setMaximumWidth(70)
            b.clicked.connect(lambda _c=False, t=tok: self._insert(t))
            br.addWidget(b)
        ml.addLayout(br)
        top.addWidget(mg, 0, 0)

        eg = QtWidgets.QGroupBox("Erweiterung")
        el = QtWidgets.QVBoxLayout(eg)
        self.ext_mask = QtWidgets.QLineEdit("[E]")
        el.addWidget(self.ext_mask)
        top.addWidget(eg, 0, 1)

        sg = QtWidgets.QGroupBox("Suchen && Ersetzen")
        sl = QtWidgets.QFormLayout(sg)
        self.search = QtWidgets.QLineEdit()
        self.replace = QtWidgets.QLineEdit()
        self.rx = QtWidgets.QCheckBox("RegEx")
        self.case = QtWidgets.QCheckBox("Groß/klein")
        self.once = QtWidgets.QCheckBox("Nur 1. Treffer")
        self.inc_ext = QtWidgets.QCheckBox("inkl. Erweiterung")
        sl.addRow("Suchen nach:", self.search)
        sl.addRow("Ersetzen durch:", self.replace)
        r = QtWidgets.QHBoxLayout()
        for w in (self.rx, self.case, self.once, self.inc_ext):
            r.addWidget(w)
        sl.addRow(r)
        top.addWidget(sg, 0, 2)

        cg = QtWidgets.QGroupBox("Groß-/Kleinschreibung")
        cl = QtWidgets.QVBoxLayout(cg)
        self.case_mode = QtWidgets.QComboBox()
        self.case_mode.addItems(["unverändert", "alles klein", "ALLES GROSS", "Erster Buchstabe groß",
                                 "Erster Buchstabe Jedes Wortes Groß"])
        cl.addWidget(self.case_mode)
        top.addWidget(cg, 1, 0)

        zg = QtWidgets.QGroupBox("Zähler [C]")
        zl = QtWidgets.QFormLayout(zg)
        self.c_start = QtWidgets.QSpinBox()
        self.c_start.setRange(0, 10 ** 8)
        self.c_start.setValue(1)
        self.c_step = QtWidgets.QSpinBox()
        self.c_step.setRange(-1000, 1000)
        self.c_step.setValue(1)
        self.c_digits = QtWidgets.QSpinBox()
        self.c_digits.setRange(1, 10)
        zl.addRow("Beginnen bei:", self.c_start)
        zl.addRow("Schrittweite:", self.c_step)
        zl.addRow("Stellen:", self.c_digits)
        top.addWidget(zg, 1, 1)

        hg = QtWidgets.QLabel(HELP)
        hg.setWordWrap(True)
        top.addWidget(hg, 1, 2)
        lay.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Alter Name", "Neuer Name", "Größe", "Datum"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel()
        row.addWidget(self.info, 1)
        self.go = QtWidgets.QPushButton("Start!")
        self.go.clicked.connect(self.execute)
        self.undo_btn = QtWidgets.QPushButton("Rückgängig")
        self.undo_btn.setEnabled(bool(MultiRenameDialog.last_undo))
        self.undo_btn.clicked.connect(self.undo)
        close = QtWidgets.QPushButton("Schließen")
        close.clicked.connect(self.accept)
        for b in (self.go, self.undo_btn, close):
            row.addWidget(b)
        lay.addLayout(row)

        for w in (self.ext_mask, self.search, self.replace):
            w.textChanged.connect(self.preview)
        self.name_mask.editTextChanged.connect(self.preview)
        for w in (self.rx, self.case, self.once, self.inc_ext):
            w.toggled.connect(self.preview)
        self.case_mode.currentIndexChanged.connect(self.preview)
        for w in (self.c_start, self.c_step, self.c_digits):
            w.valueChanged.connect(self.preview)
        self.resize(1000, 640)
        self.preview()

    def _insert(self, tok):
        le = self.name_mask.lineEdit()
        if tok == "[YMD]":
            tok = "[Y]-[M]-[D]"
        elif tok == "[hms]":
            tok = "[h][m][s]"
        elif tok == "[N#-#]":
            tok = "[N1-8]"
        le.insert(tok)
        le.setFocus()

    def compute(self):
        names = []
        cnt = self.c_start.value()
        for e in self.entries:
            base, ext = split_ext(e.name, e.is_dir)
            c = str(cnt).zfill(self.c_digits.value())
            cnt += self.c_step.value()
            nb = apply_mask(self.name_mask.currentText(), base, ext, e.path, c, e.mtime)
            ne = apply_mask(self.ext_mask.text(), base, ext, e.path, c, e.mtime) if not e.is_dir else ""
            full = nb + ("." + ne if ne else "")
            s = self.search.text()
            if s:
                target = full if self.inc_ext.isChecked() else nb
                flags = 0 if self.case.isChecked() else re.I
                pat = s if self.rx.isChecked() else re.escape(s)
                rep = self.replace.text() if self.rx.isChecked() else self.replace.text().replace("\\", "\\\\")
                try:
                    target = re.sub(pat, rep, target, count=1 if self.once.isChecked() else 0, flags=flags)
                except re.error:
                    pass
                full = target if self.inc_ext.isChecked() else target + ("." + ne if ne else "")
            cm = self.case_mode.currentIndex()
            if cm == 1:
                full = full.lower()
            elif cm == 2:
                full = full.upper()
            elif cm == 3:
                full = full[:1].upper() + full[1:].lower()
            elif cm == 4:
                full = re.sub(r"(^|[\s_\-\.(\[])(\w)", lambda m: m.group(1) + m.group(2).upper(), full.lower())
            names.append(full)
        return names

    def preview(self):
        names = self.compute()
        self.table.setRowCount(len(self.entries))
        dupes = {n for n in names if names.count(n) > 1}
        from .utils import format_size, format_time
        from .qt import QtGui
        for r, (e, n) in enumerate(zip(self.entries, names)):
            it = QtWidgets.QTableWidgetItem(e.name)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, it)
            ni = QtWidgets.QTableWidgetItem(n)
            if n in dupes or "/" in n or not n:
                ni.setForeground(QtGui.QBrush(QtGui.QColor(220, 0, 0)))
            self.table.setItem(r, 1, ni)
            si = QtWidgets.QTableWidgetItem("<DIR>" if e.is_dir else format_size(e.size))
            si.setFlags(si.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, si)
            di = QtWidgets.QTableWidgetItem(format_time(e.mtime))
            di.setFlags(di.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 3, di)
        self.info.setText("%d Datei(en)%s" % (len(names), " – Achtung: doppelte Namen!" if dupes else ""))

    def execute(self):
        config.push_history("rename_history", self.name_mask.currentText())
        config.save()
        pairs = []
        for r, e in enumerate(self.entries):
            new = self.table.item(r, 1).text()
            if new and new != e.name:
                pairs.append((e.path, os.path.join(os.path.dirname(e.path), new)))
        if not pairs:
            return
        targets = [d for _s, d in pairs]
        if len(set(targets)) != len(targets):
            QtWidgets.QMessageBox.warning(self, "Umbenennen", "Mehrere Dateien würden denselben Namen bekommen.")
            return
        sources = {s for s, _d in pairs}
        # two-phase rename to allow swaps (a->b, b->a)
        temp = []
        errors = []
        done = []
        for s, d in pairs:
            if os.path.lexists(d) and d not in sources:
                errors.append("%s existiert bereits" % os.path.basename(d))
                continue
            t = s + ".__sc_tmp__%d" % os.getpid()
            try:
                os.rename(s, t)
                temp.append((t, s, d))
            except OSError as ex:
                errors.append("%s: %s" % (os.path.basename(s), ex.strerror))
        for t, s, d in temp:
            try:
                os.rename(t, d)
                done.append((s, d))
            except OSError as ex:
                os.rename(t, s)
                errors.append("%s: %s" % (os.path.basename(s), ex.strerror))
        MultiRenameDialog.last_undo = done
        self.undo_btn.setEnabled(bool(done))
        if errors:
            QtWidgets.QMessageBox.warning(self, "Umbenennen", "\n".join(errors[:30]))
        # update entries for further renames
        mapping = dict(done)
        for e in self.entries:
            if e.path in mapping:
                e.path = mapping[e.path]
                e.name = os.path.basename(e.path)
        self.preview()
        self.info.setText("%d Datei(en) umbenannt" % len(done))

    def undo(self):
        done = MultiRenameDialog.last_undo
        errors = []
        back = {}
        for s, d in reversed(done):
            try:
                os.rename(d, s)
                back[d] = s
            except OSError as ex:
                errors.append("%s: %s" % (d, ex.strerror))
        MultiRenameDialog.last_undo = []
        self.undo_btn.setEnabled(False)
        for e in self.entries:
            if e.path in back:
                e.path = back[e.path]
                e.name = os.path.basename(e.path)
        self.preview()
        if errors:
            QtWidgets.QMessageBox.warning(self, "Rückgängig", "\n".join(errors))
