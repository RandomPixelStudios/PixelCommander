"""Lister (F3): internal viewer for text, hex, binary and images; also used for Quick View (Ctrl+Q)."""
import os

from .qt import QtCore, QtGui, QtWidgets, Qt, qexec, QAction, QActionGroup
from .utils import human_size, format_time, split_ext
from .model import IMAGE_EXT

MAX_TEXT = 64 * 1024 * 1024
MAX_HEX = 16 * 1024 * 1024
ENCODINGS = ["auto", "utf-8", "latin-1", "cp1252", "cp850", "utf-16", "ascii"]


def hexdump(data, offset=0):
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hx = " ".join("%02X" % b for b in chunk[:8])
        if len(chunk) > 8:
            hx += "  " + " ".join("%02X" % b for b in chunk[8:])
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%08X  %-49s %s" % (offset + i, hx, txt))
    return "\n".join(lines)


class ListerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.path = None
        self.data = b""
        self.mode = "text"
        self.encoding = "auto"
        from .config import config
        self.wrap = bool(config.get("lister_wrap", True))
        self.zoom = 1.0
        self.fit = True
        self.compact = compact
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                          Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.text.setUndoRedoEnabled(False)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        self.text.setFont(mono)
        self.img_label = QtWidgets.QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_scroll = QtWidgets.QScrollArea()
        self.img_scroll.setWidget(self.img_label)
        self.img_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_scroll.setWidgetResizable(True)
        self.info = QtWidgets.QLabel()
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setWordWrap(True)
        self.stack.addWidget(self.text)
        self.stack.addWidget(self.img_scroll)
        self.stack.addWidget(self.info)
        lay.addWidget(self.stack)
        self.pixmap = None
        self.search_text = ""
        self.search_case = False

    def load(self, path):
        self.path = path
        self.pixmap = None
        if path is None:
            self.info.setText("")
            self.stack.setCurrentWidget(self.info)
            return
        if os.path.isdir(path):
            n_files = n_dirs = 0
            try:
                for de in os.scandir(path):
                    if de.is_dir(follow_symlinks=False):
                        n_dirs += 1
                    else:
                        n_files += 1
            except OSError:
                pass
            self.info.setText("<b>%s</b><br><br>Verzeichnis<br>%d Datei(en), %d Unterverzeichnis(se)" % (
                os.path.basename(path).replace("<", "&lt;"), n_files, n_dirs))
            self.stack.setCurrentWidget(self.info)
            return
        ext = split_ext(os.path.basename(path))[1].lower()
        if ext in IMAGE_EXT:
            reader = QtGui.QImageReader(path)
            reader.setAutoTransform(True)
            img = reader.read()
            if not img.isNull():
                self.pixmap = QtGui.QPixmap.fromImage(img)
                self.mode = "image"
                self.show_image()
                return
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as fh:
                self.data = fh.read(MAX_TEXT)
            self.truncated = size > MAX_TEXT
        except OSError as ex:
            self.info.setText("Datei kann nicht gelesen werden:\n%s" % ex)
            self.stack.setCurrentWidget(self.info)
            return
        if self.mode == "image":
            self.mode = "text"
        if self.mode == "text" and b"\x00" in self.data[:8192] and not self._is_utf16():
            self.mode = "hex"
        self.render()

    def _is_utf16(self):
        return self.data[:2] in (b"\xff\xfe", b"\xfe\xff")

    def decode(self):
        enc = self.encoding
        if enc == "auto":
            if self._is_utf16():
                enc = "utf-16"
            else:
                try:
                    return self.data.decode("utf-8")
                except UnicodeDecodeError:
                    enc = "cp1252"
        return self.data.decode(enc, errors="replace")

    def render(self):
        if self.mode == "image" and self.pixmap is not None:
            self.show_image()
            return
        self.stack.setCurrentWidget(self.text)
        if self.mode == "hex":
            self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
            txt = hexdump(self.data[:MAX_HEX])
            if len(self.data) > MAX_HEX:
                txt += "\n… (Hex-Ansicht auf %s begrenzt)" % human_size(MAX_HEX)
            self.text.setPlainText(txt)
        elif self.mode == "binary":
            self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
            d = self.data[:MAX_HEX]
            s = "".join(chr(b) if 32 <= b < 127 or b > 159 else "." for b in d)
            self.text.setPlainText("\n".join(s[i:i + 80] for i in range(0, len(s), 80)))
        else:
            self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap
                                      else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
            t = self.decode()
            if getattr(self, "truncated", False):
                t += "\n\n… (Datei gekürzt angezeigt)"
            self.text.setPlainText(t)

    def show_image(self):
        self.stack.setCurrentWidget(self.img_scroll)
        if self.pixmap is None:
            return
        if self.fit:
            vp = self.img_scroll.viewport().size()
            pm = self.pixmap
            if pm.width() > vp.width() or pm.height() > vp.height():
                pm = pm.scaled(vp, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            pm = self.pixmap.scaled(int(self.pixmap.width() * self.zoom), int(self.pixmap.height() * self.zoom),
                                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.img_label.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.mode == "image" and self.fit and self.pixmap is not None:
            self.show_image()

    def set_mode(self, mode):
        if mode == "image" and self.pixmap is None:
            return
        if self.mode == "image" and mode != "image" and self.path and not self.data:
            try:
                with open(self.path, "rb") as fh:
                    self.data = fh.read(MAX_TEXT)
            except OSError:
                pass
        if self.mode == "image" and mode != "image":
            try:
                with open(self.path, "rb") as fh:
                    self.data = fh.read(MAX_TEXT)
            except (OSError, TypeError):
                pass
        self.mode = mode
        self.render()

    def find(self, text=None, backward=False):
        if text is not None:
            self.search_text = text
        if not self.search_text or self.stack.currentWidget() is not self.text:
            return False
        flags = QtGui.QTextDocument.FindFlag(0)
        if backward:
            flags |= QtGui.QTextDocument.FindFlag.FindBackward
        if self.search_case:
            flags |= QtGui.QTextDocument.FindFlag.FindCaseSensitively
        if self.text.find(self.search_text, flags):
            return True
        cur = self.text.textCursor()
        cur.movePosition(QtGui.QTextCursor.MoveOperation.End if backward else QtGui.QTextCursor.MoveOperation.Start)
        self.text.setTextCursor(cur)
        return self.text.find(self.search_text, flags)


class Lister(QtWidgets.QMainWindow):
    open_windows = []

    def __init__(self, path, siblings=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.siblings = siblings or []
        self.w = ListerWidget(self)
        self.setCentralWidget(self.w)
        self.resize(900, 700)
        self._build_menu()
        self.load(path)
        Lister.open_windows.append(self)
        self.destroyed.connect(lambda *_: Lister.open_windows.remove(self) if self in Lister.open_windows else None)

    def _act(self, menu, text, slot, key=None, checkable=False):
        a = QAction(text, self)
        if key:
            a.setShortcut(QtGui.QKeySequence(key))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Datei")
        self._act(m, "&Nächste Datei", lambda: self.step(1), "N")
        self._act(m, "&Vorherige Datei", lambda: self.step(-1), "P")
        self._act(m, "Mit Standardprogramm öffnen", self.open_external)
        self._act(m, "&Bearbeiten (interner Editor)", self.edit_file, "F4")
        m.addSeparator()
        self._act(m, "Schließen", self.close, "Esc")
        self._act(m, "Schließen ", self.close, "Q")
        e = mb.addMenu("&Bearbeiten")
        self._act(e, "Kopieren", lambda: self.w.text.copy(), "Ctrl+C")
        self._act(e, "Alles markieren", lambda: self.w.text.selectAll(), "Ctrl+A")
        e.addSeparator()
        self._act(e, "&Suchen…", self.ask_find, "F7")
        self._act(e, "Suchen…", self.ask_find, "Ctrl+F")
        self._act(e, "Weitersuchen", lambda: self.w.find(), "F3")
        self._act(e, "Rückwärts suchen", lambda: self.w.find(backward=True), "Shift+F3")
        o = mb.addMenu("&Optionen")
        grp = QActionGroup(self)
        self.mode_actions = {}
        for key, (mode, label) in zip("1234", [("text", "&Text"), ("binary", "&Binär"), ("hex", "&Hex"),
                                               ("image", "B&ild/Multimedia")]):
            a = self._act(o, label, lambda _c=False, m=mode: self.set_mode(m), key, checkable=True)
            grp.addAction(a)
            self.mode_actions[mode] = a
        o.addSeparator()
        self.wrap_act = self._act(o, "&Zeilenumbruch", self.toggle_wrap, "W", checkable=True)
        self.wrap_act.setChecked(self.w.wrap)
        self.fit_act = self._act(o, "Bild an Fenster &anpassen", self.toggle_fit, "F", checkable=True)
        self.fit_act.setChecked(True)
        self._act(o, "Vergrößern", lambda: self.zoom(1.25), "+")
        self._act(o, "Verkleinern", lambda: self.zoom(0.8), "-")
        o.addSeparator()
        enc = o.addMenu("&Zeichensatz")
        eg = QActionGroup(self)
        for name in ENCODINGS:
            a = self._act(enc, name, lambda _c=False, n=name: self.set_encoding(n), checkable=True)
            eg.addAction(a)
            if name == "auto":
                a.setChecked(True)
        self.status = self.statusBar()

    def load(self, path):
        self.path = path
        self.w.load(path)
        self.setWindowTitle("Lister (nur lesen) – [%s]" % path)
        if self.w.mode in self.mode_actions:
            self.mode_actions[self.w.mode].setChecked(True)
        try:
            st = os.stat(path)
            self.status.showMessage("Nur Ansicht – F4 öffnet den Editor   |   %s   %s   %s" % (
                path, human_size(st.st_size), format_time(st.st_mtime)))
        except OSError:
            pass

    def step(self, d):
        if not self.siblings or self.path not in self.siblings:
            return
        i = self.siblings.index(self.path) + d
        if 0 <= i < len(self.siblings):
            self.load(self.siblings[i])

    def set_mode(self, m):
        self.w.set_mode(m)

    def set_encoding(self, n):
        self.w.encoding = n
        self.w.render()

    def toggle_wrap(self, c):
        self.w.wrap = c
        self.w.render()

    def toggle_fit(self, c):
        self.w.fit = c
        self.w.show_image()

    def zoom(self, f):
        if self.w.mode == "image":
            self.w.fit = False
            self.fit_act.setChecked(False)
            self.w.zoom *= f
            self.w.show_image()
        else:
            font = self.w.text.font()
            font.setPointSizeF(max(5.0, font.pointSizeF() * f))
            self.w.text.setFont(font)

    def ask_find(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Suchen")
        lay = QtWidgets.QFormLayout(dlg)
        ed = QtWidgets.QLineEdit(self.w.search_text)
        case = QtWidgets.QCheckBox("Groß-/Kleinschreibung beachten")
        case.setChecked(self.w.search_case)
        back = QtWidgets.QCheckBox("Rückwärts suchen")
        lay.addRow("Suchen nach:", ed)
        lay.addRow(case)
        lay.addRow(back)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addRow(bb)
        if qexec(dlg):
            self.w.search_case = case.isChecked()
            if not self.w.find(ed.text(), back.isChecked()):
                self.status.showMessage("„%s“ nicht gefunden" % ed.text(), 3000)

    def edit_file(self):
        from .editor import Editor
        Editor(self.path).show()

    def open_external(self):
        from .utils import open_default
        open_default(self.path)
