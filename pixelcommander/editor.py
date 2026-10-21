"""Internal text editor (F4) with line numbers, find/replace, encodings; CodeEdit is shared with the compare tool."""
import os
import re
import shutil
import tempfile

from .config import config
from .qt import QtCore, QtGui, QtWidgets, Qt, Signal, QAction, QActionGroup, qexec

ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "cp850", "utf-16", "ascii"]


def fixed_font():
    f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    if config.get("editor_font_size"):
        f.setPointSize(int(config["editor_font_size"]))
    return f


def read_text(path):
    """Return (text, encoding, newline, is_binary)."""
    with open(path, "rb") as fh:
        data = fh.read()
    binary = b"\x00" in data[:8192] and data[:2] not in (b"\xff\xfe", b"\xfe\xff")
    if data[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16"
    else:
        try:
            data.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            enc = "cp1252"
    text = data.decode(enc, errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    return text, enc, nl, binary


def write_text(path, text, enc, nl):
    data = (text.replace("\n", nl) if nl != "\n" else text).encode(enc, errors="replace")
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".sc-save-", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class _Gutter(QtWidgets.QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QtCore.QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_gutter(e)


class CodeEdit(QtWidgets.QPlainTextEdit):
    """QPlainTextEdit with line number gutter. number_map (list) overrides the shown numbers."""
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gutter = _Gutter(self)
        self.number_map = None
        self.show_numbers = config.get("editor_line_numbers", True)
        self.highlight_line = True
        self.setFont(fixed_font())
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight)
        self._extra = []
        self._update_width()
        self.set_tab_width(config.get("editor_tab_width", 4))

    def set_tab_width(self, n):
        w = self.fontMetrics().horizontalAdvance(" ") * int(n)
        if hasattr(self, "setTabStopDistance"):
            self.setTabStopDistance(w)
        else:
            self.setTabStopWidth(w)

    def gutter_width(self):
        if not self.show_numbers:
            return 0
        n = max(1, self.blockCount())
        return 10 + self.fontMetrics().horizontalAdvance("9") * max(3, len(str(n)))

    def _update_width(self, *_a):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def set_show_numbers(self, on):
        self.show_numbers = on
        self._update_width()
        self.resizeEvent(QtGui.QResizeEvent(self.size(), self.size()))
        self.gutter.update()

    def paint_gutter(self, e):
        p = QtGui.QPainter(self.gutter)
        pal = self.palette()
        p.fillRect(e.rect(), pal.color(QtGui.QPalette.ColorRole.Window))
        col = QtGui.QColor(pal.color(QtGui.QPalette.ColorRole.Text))
        col.setAlpha(130)
        p.setPen(col)
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        h = self.fontMetrics().height()
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top():
                if self.number_map is None:
                    label = str(num + 1)
                else:
                    v = self.number_map[num] if num < len(self.number_map) else None
                    label = str(v) if v else ""
                p.drawText(0, top, self.gutter.width() - 5, h, int(Qt.AlignmentFlag.AlignRight), label)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def set_extra(self, sels):
        self._extra = sels
        self._highlight()

    def _highlight(self):
        sels = list(self._extra)
        if self.highlight_line and not self.isReadOnly():
            s = QtWidgets.QTextEdit.ExtraSelection()
            c = QtGui.QColor(self.palette().color(QtGui.QPalette.ColorRole.Highlight))
            c.setAlpha(35)
            s.format.setBackground(c)
            s.format.setProperty(QtGui.QTextFormat.Property.FullWidthSelection, True)
            s.cursor = self.textCursor()
            s.cursor.clearSelection()
            sels.append(s)
        self.setExtraSelections(sels)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            e.acceptProposedAction()
            self.fileDropped.emit(urls[0])
            return
        super().dropEvent(e)


class FindBar(QtWidgets.QWidget):
    def __init__(self, editor_win):
        super().__init__()
        self.win = editor_win
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.find = QtWidgets.QLineEdit()
        self.find.setPlaceholderText("Suchen")
        self.repl = QtWidgets.QLineEdit()
        self.repl.setPlaceholderText("Ersetzen durch")
        self.case = QtWidgets.QCheckBox("Groß/klein")
        self.rx = QtWidgets.QCheckBox("RegEx")
        self.words = QtWidgets.QCheckBox("Ganze Wörter")
        nxt = QtWidgets.QPushButton("Weiter (F3)")
        prv = QtWidgets.QPushButton("Zurück")
        rep = QtWidgets.QPushButton("Ersetzen")
        rall = QtWidgets.QPushButton("Alle ersetzen")
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        lay.addWidget(self.find, 0, 0)
        lay.addWidget(nxt, 0, 1)
        lay.addWidget(prv, 0, 2)
        lay.addWidget(self.case, 0, 3)
        lay.addWidget(self.rx, 0, 4)
        lay.addWidget(self.words, 0, 5)
        lay.addWidget(close, 0, 6)
        lay.addWidget(self.repl, 1, 0)
        lay.addWidget(rep, 1, 1)
        lay.addWidget(rall, 1, 2)
        self.repl_widgets = [self.repl, rep, rall]
        nxt.clicked.connect(lambda: self.win.find_next())
        prv.clicked.connect(lambda: self.win.find_next(backward=True))
        rep.clicked.connect(self.win.replace_one)
        rall.clicked.connect(self.win.replace_all)
        close.clicked.connect(self.close_bar)
        self.find.returnPressed.connect(lambda: self.win.find_next())
        self.repl.returnPressed.connect(self.win.replace_one)
        self.hide()

    def open(self, replace=False):
        for w in self.repl_widgets:
            w.setVisible(replace)
        self.show()
        sel = self.win.edit.textCursor().selectedText()
        if sel and " " not in sel:
            self.find.setText(sel)
        self.find.setFocus()
        self.find.selectAll()

    def close_bar(self):
        self.hide()
        self.win.edit.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        super().keyPressEvent(e)

    def pattern(self):
        t = self.find.text()
        if not t:
            return None
        pat = t if self.rx.isChecked() else re.escape(t)
        if self.words.isChecked():
            pat = r"\b" + pat + r"\b"
        try:
            return re.compile(pat, 0 if self.case.isChecked() else re.I)
        except re.error:
            return None


class Editor(QtWidgets.QMainWindow):
    open_windows = []

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.path = None
        self.encoding = "utf-8"
        self.newline = "\n"
        self.edit = CodeEdit()
        self.edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth if config.get("editor_wrap")
                                  else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.edit.fileDropped.connect(self.open_path)
        self.findbar = FindBar(self)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.findbar)
        self.setCentralWidget(w)
        self.pos_label = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.pos_label)
        self.edit.cursorPositionChanged.connect(self.update_status)
        self.edit.document().modificationChanged.connect(self.update_title)
        self._build_menu()
        self.resize(900, 700)
        if path:
            self.load(path)
        else:
            self.update_title()
        Editor.open_windows.append(self)
        self.destroyed.connect(lambda *_: Editor.open_windows.remove(self) if self in Editor.open_windows else None)

    def _act(self, menu, text, slot, key=None, checkable=False, checked=False):
        a = QAction(text, self)
        if key:
            a.setShortcut(QtGui.QKeySequence(key))
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Datei")
        self._act(m, "&Neu", self.new_file, "Ctrl+N")
        self._act(m, "Ö&ffnen…", self.open_dialog, "Ctrl+O")
        self._act(m, "&Speichern", self.save, "Ctrl+S")
        self._act(m, "Speichern &unter…", self.save_as, "Ctrl+Shift+S")
        self._act(m, "Neu &laden", self.reload, "Ctrl+R")
        m.addSeparator()
        self._act(m, "&Schließen", self.close, "Esc")
        e = mb.addMenu("&Bearbeiten")
        self._act(e, "Rückgängig", self.edit.undo, "Ctrl+Z")
        self._act(e, "Wiederherstellen", self.edit.redo, "Ctrl+Y")
        e.addSeparator()
        self._act(e, "Ausschneiden", self.edit.cut, "Ctrl+X")
        self._act(e, "Kopieren", self.edit.copy, "Ctrl+C")
        self._act(e, "Einfügen", self.edit.paste, "Ctrl+V")
        self._act(e, "Alles markieren", self.edit.selectAll, "Ctrl+A")
        e.addSeparator()
        self._act(e, "&Suchen…", lambda: self.findbar.open(False), "Ctrl+F")
        self._act(e, "&Ersetzen…", lambda: self.findbar.open(True), "Ctrl+H")
        self._act(e, "Weitersuchen", lambda: self.find_next(), "F3")
        self._act(e, "Rückwärts suchen", lambda: self.find_next(backward=True), "Shift+F3")
        self._act(e, "&Gehe zu Zeile…", self.goto_line, "Ctrl+G")
        e.addSeparator()
        self._act(e, "Zeile duplizieren", self.dup_line, "Ctrl+D")
        self._act(e, "Zeile löschen", self.del_line, "Ctrl+Shift+K")
        self._act(e, "Auswahl GROSS", lambda: self.transform(str.upper), "Ctrl+Shift+U")
        self._act(e, "Auswahl klein", lambda: self.transform(str.lower), "Ctrl+U")
        self._act(e, "Datum/Uhrzeit einfügen", lambda: self.edit.insertPlainText(
            QtCore.QDateTime.currentDateTime().toString("dd.MM.yyyy HH:mm")), "F5")
        o = mb.addMenu("&Optionen")
        self.wrap_act = self._act(o, "&Zeilenumbruch", self.toggle_wrap, "Alt+Z", True, bool(config.get("editor_wrap")))
        self._act(o, "Zeilen&nummern", self.edit.set_show_numbers, None, True, self.edit.show_numbers)
        o.addSeparator()
        enc = o.addMenu("Zeichensatz (Speichern)")
        self.enc_group = QActionGroup(self)
        self.enc_actions = {}
        for n in ENCODINGS:
            a = self._act(enc, n, lambda _c=False, n=n: self.set_encoding(n), None, True)
            self.enc_group.addAction(a)
            self.enc_actions[n] = a
        renc = o.addMenu("Neu laden mit Zeichensatz")
        for n in ENCODINGS:
            self._act(renc, n, lambda _c=False, n=n: self.reload(n))
        nl = o.addMenu("Zeilenende")
        g = QActionGroup(self)
        self.lf_act = self._act(nl, "LF (Linux)", lambda: self.set_newline("\n"), None, True, True)
        self.crlf_act = self._act(nl, "CRLF (Windows)", lambda: self.set_newline("\r\n"), None, True)
        g.addAction(self.lf_act)
        g.addAction(self.crlf_act)
        tw = o.addMenu("Tabulatorbreite")
        g2 = QActionGroup(self)
        for n in (2, 4, 8):
            a = self._act(tw, str(n), lambda _c=False, n=n: self.edit.set_tab_width(n), None, True,
                          n == int(config.get("editor_tab_width", 4)))
            g2.addAction(a)
        o.addSeparator()
        self._act(o, "Schrift größer", lambda: self.zoom(1), "Ctrl++")
        self._act(o, "Schrift kleiner", lambda: self.zoom(-1), "Ctrl+-")
        self._act(o, "Schrift…", self.pick_font)

    # ------------------------------------------------------------ file handling
    def load(self, path, encoding=None):
        try:
            text, enc, nl, binary = read_text(path)
            if encoding:
                with open(path, "rb") as fh:
                    text = fh.read().decode(encoding, errors="replace").replace("\r\n", "\n")
                enc = encoding
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Editor", "Datei kann nicht geöffnet werden:\n%s" % ex)
            return False
        if binary and not encoding and QtWidgets.QMessageBox.question(
                self, "Editor", "Die Datei scheint binär zu sein. Trotzdem bearbeiten?") != \
                QtWidgets.QMessageBox.StandardButton.Yes:
            return False
        self.path = os.path.abspath(path)
        self.encoding, self.newline = enc, nl
        self.edit.setPlainText(text)
        self.edit.document().setModified(False)
        self.edit.setReadOnly(not os.access(path, os.W_OK))
        if enc in self.enc_actions:
            self.enc_actions[enc].setChecked(True)
        (self.crlf_act if nl == "\r\n" else self.lf_act).setChecked(True)
        self.update_title()
        self.update_status()
        return True

    def maybe_save(self):
        if not self.edit.document().isModified():
            return True
        r = QtWidgets.QMessageBox.question(
            self, "Editor", "„%s“ wurde geändert. Speichern?" % (os.path.basename(self.path) if self.path else "Neu"),
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard |
            QtWidgets.QMessageBox.StandardButton.Cancel)
        if r == QtWidgets.QMessageBox.StandardButton.Save:
            return self.save()
        return r == QtWidgets.QMessageBox.StandardButton.Discard

    def new_file(self):
        if not self.maybe_save():
            return
        self.path = None
        self.edit.clear()
        self.edit.setReadOnly(False)
        self.edit.document().setModified(False)
        self.update_title()

    def open_dialog(self):
        p, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Öffnen", os.path.dirname(self.path or os.getcwd()))
        if p:
            self.open_path(p)

    def open_path(self, p):
        if self.maybe_save():
            self.load(p)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            write_text(self.path, self.edit.toPlainText(), self.encoding, self.newline)
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Speichern", str(ex))
            return False
        self.edit.document().setModified(False)
        self.statusBar().showMessage("Gespeichert", 2000)
        return True

    def save_as(self):
        p, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Speichern unter", self.path or os.getcwd())
        if not p:
            return False
        self.path = p
        ok = self.save()
        self.update_title()
        return ok

    def reload(self, encoding=None):
        if self.path and self.maybe_save():
            self.load(self.path, encoding if isinstance(encoding, str) else None)

    def closeEvent(self, e):
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------ editing
    def find_next(self, backward=False):
        rx = self.findbar.pattern()
        if rx is None:
            self.findbar.open(False)
            return False
        text = self.edit.toPlainText()
        cur = self.edit.textCursor()
        if backward:
            pos = cur.selectionStart()
            matches = [m for m in rx.finditer(text, 0, pos)]
            m = matches[-1] if matches else None
            if m is None:
                ms = list(rx.finditer(text))
                m = ms[-1] if ms else None
        else:
            m = rx.search(text, cur.selectionEnd()) or rx.search(text, 0)
        if m is None:
            self.statusBar().showMessage("„%s“ nicht gefunden" % self.findbar.find.text(), 3000)
            return False
        c = self.edit.textCursor()
        c.setPosition(m.start())
        c.setPosition(m.end(), QtGui.QTextCursor.MoveMode.KeepAnchor)
        self.edit.setTextCursor(c)
        return True

    def replace_one(self):
        rx = self.findbar.pattern()
        if rx is None:
            return
        c = self.edit.textCursor()
        sel = c.selectedText()
        if sel and rx.fullmatch(sel):
            rep = rx.sub(self.findbar.repl.text(), sel, count=1) if self.findbar.rx.isChecked() \
                else self.findbar.repl.text()
            c.insertText(rep)
        self.find_next()

    def replace_all(self):
        rx = self.findbar.pattern()
        if rx is None:
            return
        text = self.edit.toPlainText()
        rep = self.findbar.repl.text()
        new, n = rx.subn(rep if self.findbar.rx.isChecked() else rep.replace("\\", "\\\\"), text)
        if n:
            c = self.edit.textCursor()
            c.beginEditBlock()
            c.select(QtGui.QTextCursor.SelectionType.Document)
            c.insertText(new)
            c.endEditBlock()
        self.statusBar().showMessage("%d Ersetzung(en)" % n, 3000)

    def goto_line(self):
        n, ok = QtWidgets.QInputDialog.getInt(self, "Gehe zu Zeile", "Zeile:", self.edit.textCursor().blockNumber() + 1,
                                              1, max(1, self.edit.blockCount()))
        if ok:
            c = QtGui.QTextCursor(self.edit.document().findBlockByNumber(n - 1))
            self.edit.setTextCursor(c)
            self.edit.centerCursor()

    def dup_line(self):
        c = self.edit.textCursor()
        t = c.block().text()
        c.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
        c.insertText("\n" + t)

    def del_line(self):
        M = QtGui.QTextCursor.MoveOperation
        K = QtGui.QTextCursor.MoveMode.KeepAnchor
        c = self.edit.textCursor()
        c.beginEditBlock()
        c.movePosition(M.StartOfBlock)
        c.movePosition(M.EndOfBlock, K)
        if not c.atEnd():
            c.movePosition(M.NextCharacter, K)
        elif c.blockNumber() > 0:
            c.movePosition(M.StartOfBlock)
            c.movePosition(M.PreviousCharacter)
            c.movePosition(M.End, K)
        c.removeSelectedText()
        c.endEditBlock()

    def transform(self, fn):
        c = self.edit.textCursor()
        if c.hasSelection():
            t = c.selectedText()
            c.insertText(fn(t).replace(" ", "\n"))

    def toggle_wrap(self, on):
        self.edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth if on
                                  else QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)

    def set_encoding(self, n):
        self.encoding = n
        self.update_status()

    def set_newline(self, nl):
        if nl != self.newline:
            self.newline = nl
            self.edit.document().setModified(True)
        self.update_status()

    def zoom(self, d):
        f = self.edit.font()
        f.setPointSize(max(5, f.pointSize() + d))
        self.edit.setFont(f)
        self.edit._update_width()

    def pick_font(self):
        res = QtWidgets.QFontDialog.getFont(self.edit.font(), self)
        font, ok = res if isinstance(res[0], QtGui.QFont) else (res[1], res[0])
        if ok:
            self.edit.setFont(font)
            self.edit._update_width()

    def update_title(self, *_a):
        name = os.path.basename(self.path) if self.path else "Unbenannt"
        mod = "*" if self.edit.document().isModified() else ""
        ro = " [schreibgeschützt]" if self.edit.isReadOnly() else ""
        self.setWindowTitle("%s%s%s – PixelCommander Editor" % (mod, name, ro))

    def update_status(self):
        c = self.edit.textCursor()
        self.pos_label.setText("Z %d, S %d   |   %s   |   %s" % (
            c.blockNumber() + 1, c.positionInBlock() + 1, self.encoding.upper(),
            "CRLF" if self.newline == "\r\n" else "LF"))
