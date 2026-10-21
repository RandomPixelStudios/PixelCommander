"""Find files dialog (Alt+F7)."""
import os
import re
import time

from .config import config
from .qt import QtCore, QtGui, QtWidgets, Qt, Signal, QShortcut
from .utils import Mask, human_size, format_time
from . import vfs


class SearchThread(QtCore.QThread):
    found = Signal(str)
    status = Signal(str)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.p = params
        self.stop = False

    def _text_match(self, path):
        p = self.p
        rx = p["text_rx"]
        try:
            with open(path, "rb") as fh:
                prev = b""
                while True:
                    if self.stop:
                        return False
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        return False
                    data = prev + chunk
                    if p["hex"]:
                        if p["hex"] in data:
                            return True
                    else:
                        txt = data.decode(p["encoding"], errors="replace")
                        if rx.search(txt):
                            return True
                    prev = data[-4096:]
        except OSError:
            return False

    def _props_ok(self, path, st):
        p = self.p
        if p["min_size"] is not None and st.st_size < p["min_size"]:
            return False
        if p["max_size"] is not None and st.st_size > p["max_size"]:
            return False
        if p["newer"] is not None and st.st_mtime < p["newer"]:
            return False
        if p["older"] is not None and st.st_mtime > p["older"]:
            return False
        return True

    def run(self):
        p = self.p
        mask = p["mask"]
        depth_limit = p["depth"]
        t0 = time.monotonic()
        count = 0
        for start in p["roots"]:
            base_depth = start.rstrip("/").count("/")
            for root, dirs, files in os.walk(start, followlinks=p["follow"]):
                if self.stop:
                    return
                if not p["hidden"]:
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    files = [f for f in files if not f.startswith(".")]
                if p["exclude_dirs"]:
                    dirs[:] = [d for d in dirs if not p["exclude_dirs"].match(d, True)]
                depth = root.rstrip("/").count("/") - base_depth
                if depth_limit is not None and depth >= depth_limit:
                    dirs[:] = []
                if time.monotonic() - t0 > 0.15:
                    self.status.emit("Durchsuche: " + root)
                    t0 = time.monotonic()
                if not p["files_only"] and not p["text_rx"] and not p["hex"]:
                    for d in dirs:
                        if mask.match(d, True) and p["name_rx"] is None or (p["name_rx"] and p["name_rx"].search(d)):
                            full = os.path.join(root, d)
                            try:
                                st = os.stat(full)
                            except OSError:
                                continue
                            if p["dirs_only"] or self._props_ok(full, st):
                                if p["min_size"] is None and p["max_size"] is None:
                                    self.found.emit(full)
                                    count += 1
                if p["dirs_only"]:
                    continue
                for f in files:
                    if self.stop:
                        return
                    if p["name_rx"] is not None:
                        if not p["name_rx"].search(f):
                            continue
                    elif not mask.match(f):
                        continue
                    full = os.path.join(root, f)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    if not self._props_ok(full, st):
                        continue
                    if p["text_rx"] or p["hex"]:
                        hit = self._text_match(full)
                        if p["not_containing"]:
                            hit = not hit
                        if not hit:
                            continue
                    self.found.emit(full)
                    count += 1
                if p["archives"]:
                    for f in files:
                        if vfs.is_archive_name(f):
                            full = os.path.join(root, f)
                            try:
                                fs = vfs.get_archive_fs(full)
                            except Exception:  # noqa: BLE001
                                continue
                            for m in fs.members_under(""):
                                if m and mask.match(os.path.basename(m)):
                                    self.found.emit(full + "/" + m)
                                    count += 1
        self.status.emit("%d Treffer" % count)


class SearchDialog(QtWidgets.QDialog):
    def __init__(self, main, start_dir, selection=None):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Dateien suchen")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.thread = None
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)

        g = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(g)
        self.mask = QtWidgets.QComboBox()
        self.mask.setEditable(True)
        self.mask.addItems(["*"] + [h for h in config.get("search_history", []) if h != "*"])
        self.mask.setToolTip("Mehrere Masken mit Leerzeichen oder ; trennen. Nach | ausschließen, z.B. *.txt | *.bak")
        f.addRow("Suchen nach:", self.mask)
        row = QtWidgets.QHBoxLayout()
        self.start = QtWidgets.QLineEdit(start_dir)
        self.start.setToolTip("Mehrere Startverzeichnisse mit ; trennen")
        pick = QtWidgets.QToolButton()
        pick.setText("…")
        pick.clicked.connect(self._pick_dir)
        row.addWidget(self.start)
        row.addWidget(pick)
        f.addRow("Suchen in:", row)
        if selection:
            sel_btn = QtWidgets.QPushButton("Nur markierte Verzeichnisse (%d)" % len(selection))
            sel_btn.clicked.connect(lambda: self.start.setText(";".join(selection)))
            f.addRow("", sel_btn)
        self.depth = QtWidgets.QComboBox()
        self.depth.addItems(["alle (unbegrenzt)", "nur aktuelles Verzeichnis"] +
                            ["%d Ebene(n)" % i for i in range(1, 10)])
        f.addRow("Unterverzeichnisse:", self.depth)
        self.regex_name = QtWidgets.QCheckBox("Regulärer Ausdruck im Dateinamen")
        f.addRow(self.regex_name)
        self.archives = QtWidgets.QCheckBox("Auch in Archiven suchen")
        f.addRow(self.archives)
        self.hidden = QtWidgets.QCheckBox("Versteckte Dateien/Verzeichnisse durchsuchen")
        self.hidden.setChecked(True)
        f.addRow(self.hidden)
        self.follow = QtWidgets.QCheckBox("Symbolischen Links folgen")
        f.addRow(self.follow)
        tg = QtWidgets.QGroupBox("Text suchen")
        tg.setCheckable(True)
        tg.setChecked(False)
        tf = QtWidgets.QFormLayout(tg)
        self.text = QtWidgets.QLineEdit()
        tf.addRow("Text:", self.text)
        self.case = QtWidgets.QCheckBox("Groß-/Kleinschreibung")
        self.words = QtWidgets.QCheckBox("Nur ganze Wörter")
        self.regex = QtWidgets.QCheckBox("Regulärer Ausdruck")
        self.hex = QtWidgets.QCheckBox("Hex (z.B. 50 4B 03 04)")
        self.notc = QtWidgets.QCheckBox("Dateien OHNE diesen Text")
        self.enc = QtWidgets.QComboBox()
        self.enc.addItems(["utf-8", "latin-1", "cp1252", "utf-16", "ascii"])
        for w in (self.case, self.words, self.regex, self.hex, self.notc):
            tf.addRow(w)
        tf.addRow("Zeichensatz:", self.enc)
        self.text_group = tg
        f.addRow(tg)
        tabs.addTab(g, "Allgemein")

        a = QtWidgets.QWidget()
        af = QtWidgets.QFormLayout(a)
        self.date_on = QtWidgets.QCheckBox("Datum zwischen")
        self.date_from = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addMonths(-1))
        self.date_to = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        for d in (self.date_from, self.date_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
        dr = QtWidgets.QHBoxLayout()
        dr.addWidget(self.date_from)
        dr.addWidget(QtWidgets.QLabel("und"))
        dr.addWidget(self.date_to)
        af.addRow(self.date_on, dr)
        self.age_on = QtWidgets.QCheckBox("Nicht älter als")
        self.age_val = QtWidgets.QSpinBox()
        self.age_val.setRange(1, 100000)
        self.age_unit = QtWidgets.QComboBox()
        self.age_unit.addItems(["Minuten", "Stunden", "Tage", "Wochen", "Monate", "Jahre"])
        self.age_unit.setCurrentIndex(2)
        ar = QtWidgets.QHBoxLayout()
        ar.addWidget(self.age_val)
        ar.addWidget(self.age_unit)
        af.addRow(self.age_on, ar)
        self.size_on = QtWidgets.QCheckBox("Dateigröße")
        self.size_op = QtWidgets.QComboBox()
        self.size_op.addItems([">=", "<=", "="])
        self.size_val = QtWidgets.QDoubleSpinBox()
        self.size_val.setRange(0, 1e12)
        self.size_unit = QtWidgets.QComboBox()
        self.size_unit.addItems(["Bytes", "KB", "MB", "GB"])
        sr = QtWidgets.QHBoxLayout()
        for w in (self.size_op, self.size_val, self.size_unit):
            sr.addWidget(w)
        af.addRow(self.size_on, sr)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["Dateien und Verzeichnisse", "Nur Dateien", "Nur Verzeichnisse"])
        af.addRow("Suchen nach:", self.kind)
        self.excl = QtWidgets.QLineEdit()
        self.excl.setPlaceholderText("z.B. .git node_modules __pycache__")
        af.addRow("Verzeichnisse überspringen:", self.excl)
        tabs.addTab(a, "Erweitert")

        self.results = QtWidgets.QListWidget()
        self.results.itemDoubleClicked.connect(lambda _i: self.goto_file())
        lay.addWidget(self.results, 1)
        self.status = QtWidgets.QLabel()
        lay.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Suche starten")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.start_search)
        self.stop_btn = QtWidgets.QPushButton("Abbrechen")
        self.stop_btn.clicked.connect(self.stop_search)
        self.stop_btn.setEnabled(False)
        view_btn = QtWidgets.QPushButton("Ansehen (F3)")
        view_btn.clicked.connect(self.view_file)
        goto_btn = QtWidgets.QPushButton("Gehe zu Datei")
        goto_btn.clicked.connect(self.goto_file)
        feed_btn = QtWidgets.QPushButton("In Liste ausgeben")
        feed_btn.setToolTip("Suchergebnisse im Dateifenster anzeigen (Feed to listbox)")
        feed_btn.clicked.connect(self.feed)
        new_btn = QtWidgets.QPushButton("Neue Suche")
        new_btn.clicked.connect(lambda: (self.results.clear(), self.status.clear()))
        for b in (self.start_btn, self.stop_btn, new_btn, view_btn, goto_btn, feed_btn):
            row.addWidget(b)
        lay.addLayout(row)
        QShortcut(QtGui.QKeySequence("F3"), self, self.view_file)
        self.resize(760, 640)
        self.mask.lineEdit().selectAll()

    def _pick_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Startverzeichnis", self.start.text())
        if d:
            self.start.setText(d)

    def params(self):
        mask_text = self.mask.currentText().strip() or "*"
        p = {"mask": Mask(mask_text), "name_rx": None, "roots": [], "depth": None, "hidden": self.hidden.isChecked(),
             "follow": self.follow.isChecked(), "text_rx": None, "hex": None, "not_containing": False,
             "encoding": self.enc.currentText(), "min_size": None, "max_size": None, "newer": None, "older": None,
             "files_only": self.kind.currentIndex() == 1, "dirs_only": self.kind.currentIndex() == 2,
             "archives": self.archives.isChecked(), "exclude_dirs": Mask(self.excl.text()) if self.excl.text().strip()
             else None}
        if self.regex_name.isChecked():
            p["name_rx"] = re.compile(mask_text, re.I)
        p["roots"] = [os.path.expanduser(r.strip()) for r in self.start.text().split(";") if r.strip()]
        di = self.depth.currentIndex()
        p["depth"] = None if di == 0 else (1 if di == 1 else di)
        if self.text_group.isChecked() and self.text.text():
            t = self.text.text()
            if self.hex.isChecked():
                p["hex"] = bytes.fromhex(t.replace(" ", ""))
            else:
                pat = t if self.regex.isChecked() else re.escape(t)
                if self.words.isChecked():
                    pat = r"\b" + pat + r"\b"
                p["text_rx"] = re.compile(pat, 0 if self.case.isChecked() else re.I)
            p["not_containing"] = self.notc.isChecked()
            p["files_only"] = True
        if self.date_on.isChecked():
            p["newer"] = QtCore.QDateTime(self.date_from.date(), QtCore.QTime(0, 0)).toSecsSinceEpoch()
            p["older"] = QtCore.QDateTime(self.date_to.date(), QtCore.QTime(23, 59, 59)).toSecsSinceEpoch()
        if self.age_on.isChecked():
            mult = [60, 3600, 86400, 7 * 86400, 30 * 86400, 365 * 86400][self.age_unit.currentIndex()]
            p["newer"] = time.time() - self.age_val.value() * mult
        if self.size_on.isChecked():
            n = int(self.size_val.value() * [1, 1024, 2 ** 20, 2 ** 30][self.size_unit.currentIndex()])
            op = self.size_op.currentText()
            if op == ">=":
                p["min_size"] = n
            elif op == "<=":
                p["max_size"] = n
            else:
                p["min_size"] = p["max_size"] = n
            p["files_only"] = True
        return p

    def start_search(self):
        self.stop_search()
        try:
            p = self.params()
        except (re.error, ValueError) as ex:
            QtWidgets.QMessageBox.warning(self, "Suche", "Ungültiger Suchausdruck: %s" % ex)
            return
        config.push_history("search_history", self.mask.currentText().strip())
        self.results.clear()
        self.thread = SearchThread(p, self)
        self.thread.found.connect(self._add)
        self.thread.status.connect(self.status.setText)
        self.thread.finished.connect(self._done)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.thread.start()

    def _add(self, path):
        self.results.addItem(path)

    def _done(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.results.count():
            self.results.setCurrentRow(0)
            self.results.setFocus()
        self.status.setText("Fertig – %d Treffer" % self.results.count())

    def stop_search(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop = True
            self.thread.wait(3000)

    def current_path(self):
        it = self.results.currentItem()
        return it.text() if it else None

    def view_file(self):
        p = self.current_path()
        if p and os.path.isfile(p):
            self.main.view_file(p)

    def goto_file(self):
        p = self.current_path()
        if not p:
            return
        panel = self.main.active_panel()
        panel.set_location(os.path.dirname(p), select=os.path.basename(p))
        panel.activate(focus=True)

    def feed(self):
        paths = [self.results.item(i).text() for i in range(self.results.count())]
        paths = [p for p in paths if os.path.lexists(p)]
        if not paths:
            return
        roots = [r.strip() for r in self.start.text().split(";") if r.strip()]
        base = os.path.expanduser(roots[0]) if len(roots) == 1 else "/"
        fs = vfs.ResultFS(paths, base, "Suchergebnisse")
        loc = vfs.register_results(fs)
        panel = self.main.active_panel()
        panel.set_location(loc)
        panel.activate(focus=True)
        self.close()

    def closeEvent(self, e):
        self.stop_search()
        super().closeEvent(e)
