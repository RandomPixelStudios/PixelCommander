"""Various dialogs: copy/move, attributes, properties, pack/unpack, checksums, split/combine, settings, hotlist."""
import grp
import hashlib
import os
import pwd
import stat
import time
import zlib

from .config import config
from .qt import QtCore, QtGui, QtWidgets, Qt, Signal, qexec
from .utils import format_size, format_time, human_size, split_ext
from . import vfs

OKCANCEL = QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel


def button_box(dlg, buttons=OKCANCEL):
    bb = QtWidgets.QDialogButtonBox(buttons)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def history_combo(key, current=""):
    cb = QtWidgets.QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
    items = [current] + [h for h in config.get(key, []) if h != current]
    cb.addItems([i for i in items if i is not None])
    cb.setCurrentIndex(0)
    cb.setMinimumWidth(420)
    return cb


# ---------------------------------------------------------------- copy / move

class CopyDialog(QtWidgets.QDialog):
    def __init__(self, title, what, dest, parent=None, move=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("%s %s nach:" % ("Verschiebe" if move else "Kopiere", what)))
        self.dest = history_combo("copy_history", dest)
        lay.addWidget(self.dest)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Nur Dateien dieses Typs:"))
        self.mask = QtWidgets.QLineEdit("*")
        row.addWidget(self.mask)
        lay.addLayout(row)
        self.ask_overwrite = QtWidgets.QCheckBox("Vor dem Überschreiben fragen")
        self.ask_overwrite.setChecked(True)
        lay.addWidget(self.ask_overwrite)
        lay.addWidget(button_box(self))
        le = self.dest.lineEdit()
        QtCore.QTimer.singleShot(0, lambda: self._select_name(le))

    @staticmethod
    def _select_name(le):
        t = le.text()
        base = os.path.basename(t)
        if base and not t.endswith("/"):
            b, x = split_ext(base)
            le.setSelection(len(t) - len(base), len(b))
        else:
            le.selectAll()

    def values(self):
        d = self.dest.currentText().strip()
        config.push_history("copy_history", d, 20)
        return d, self.mask.text().strip() or "*", self.ask_overwrite.isChecked()


# ---------------------------------------------------------------- properties / attributes

PERM_BITS = [("Besitzer", stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR),
             ("Gruppe", stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP),
             ("Andere", stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)]


def _uname(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, TypeError):
        return str(uid)


def _gname(gid):
    try:
        return grp.getgrgid(gid).gr_name
    except (KeyError, TypeError):
        return str(gid)


class AttributesDialog(QtWidgets.QDialog):
    """Change permissions, owner and timestamps of one or more files (TC: Files > Change attributes)."""

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.setWindowTitle("Attribute ändern")
        lay = QtWidgets.QVBoxLayout(self)
        first = paths[0]
        try:
            st = os.lstat(first)
        except OSError:
            st = None
        if len(paths) == 1:
            lay.addWidget(QtWidgets.QLabel("<b>%s</b>" % first.replace("<", "&lt;")))
        else:
            lay.addWidget(QtWidgets.QLabel("%d Objekte ausgewählt" % len(paths)))
        gb = QtWidgets.QGroupBox("Berechtigungen")
        g = QtWidgets.QGridLayout(gb)
        for c, t in enumerate(["", "Lesen", "Schreiben", "Ausführen"]):
            g.addWidget(QtWidgets.QLabel(t), 0, c)
        self.boxes = []
        for r, (label, rb, wb, xb) in enumerate(PERM_BITS, 1):
            g.addWidget(QtWidgets.QLabel(label), r, 0)
            for c, bit in enumerate((rb, wb, xb), 1):
                cb = QtWidgets.QCheckBox()
                cb.setTristate(len(paths) > 1)
                self._init_box(cb, bit)
                g.addWidget(cb, r, c)
                self.boxes.append((cb, bit))
        r = len(PERM_BITS) + 1
        for c, (label, bit) in enumerate([("SUID", stat.S_ISUID), ("SGID", stat.S_ISGID), ("Sticky", stat.S_ISVTX)], 1):
            cb = QtWidgets.QCheckBox(label)
            cb.setTristate(len(paths) > 1)
            self._init_box(cb, bit)
            g.addWidget(cb, r, c)
            self.boxes.append((cb, bit))
        self.octal = QtWidgets.QLineEdit()
        self.octal.setMaximumWidth(80)
        g.addWidget(QtWidgets.QLabel("Oktal:"), r + 1, 0)
        g.addWidget(self.octal, r + 1, 1)
        if st is not None and len(paths) == 1:
            self.octal.setText("%04o" % stat.S_IMODE(st.st_mode))
        for cb, _b in self.boxes:
            cb.stateChanged.connect(self._sync_octal)
        self.octal.textEdited.connect(self._octal_edited)
        lay.addWidget(gb)

        og = QtWidgets.QGroupBox("Besitzer")
        of = QtWidgets.QFormLayout(og)
        self.owner = QtWidgets.QComboBox()
        self.owner.setEditable(True)
        self.group = QtWidgets.QComboBox()
        self.group.setEditable(True)
        try:
            self.owner.addItems(sorted({p.pw_name for p in pwd.getpwall()}))
            self.group.addItems(sorted({x.gr_name for x in grp.getgrall()}))
        except Exception:  # noqa: BLE001
            pass
        if st is not None:
            self.owner.setCurrentText(_uname(st.st_uid))
            self.group.setCurrentText(_gname(st.st_gid))
        self.orig_owner = self.owner.currentText()
        self.orig_group = self.group.currentText()
        of.addRow("Benutzer:", self.owner)
        of.addRow("Gruppe:", self.group)
        lay.addWidget(og)

        tg = QtWidgets.QGroupBox("Datum/Zeit ändern")
        tg.setCheckable(True)
        tg.setChecked(False)
        tl = QtWidgets.QHBoxLayout(tg)
        self.dt = QtWidgets.QDateTimeEdit(QtCore.QDateTime.fromSecsSinceEpoch(int(st.st_mtime)) if st
                                          else QtCore.QDateTime.currentDateTime())
        self.dt.setCalendarPopup(True)
        self.dt.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        now = QtWidgets.QPushButton("Jetzt")
        now.clicked.connect(lambda: self.dt.setDateTime(QtCore.QDateTime.currentDateTime()))
        tl.addWidget(self.dt)
        tl.addWidget(now)
        self.time_group = tg
        lay.addWidget(tg)
        self.recursive = QtWidgets.QCheckBox("Auch Unterverzeichnisse bearbeiten")
        self.recursive.setEnabled(any(os.path.isdir(p) and not os.path.islink(p) for p in paths))
        lay.addWidget(self.recursive)
        lay.addWidget(button_box(self))

    def _init_box(self, cb, bit):
        vals = set()
        for p in self.paths:
            try:
                vals.add(bool(os.lstat(p).st_mode & bit))
            except OSError:
                pass
        if len(vals) > 1:
            cb.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            cb.setChecked(vals == {True})

    def _sync_octal(self):
        if any(cb.checkState() == Qt.CheckState.PartiallyChecked for cb, _b in self.boxes):
            self.octal.setText("")
            return
        m = 0
        for cb, bit in self.boxes:
            if cb.isChecked():
                m |= bit
        self.octal.setText("%04o" % m)

    def _octal_edited(self, t):
        try:
            m = int(t, 8)
        except ValueError:
            return
        for cb, bit in self.boxes:
            cb.blockSignals(True)
            cb.setChecked(bool(m & bit))
            cb.blockSignals(False)

    def apply(self):
        errors = []
        targets = []
        for p in self.paths:
            targets.append(p)
            if self.recursive.isChecked() and os.path.isdir(p) and not os.path.islink(p):
                for root, dirs, files in os.walk(p):
                    targets.extend(os.path.join(root, x) for x in dirs + files)
        uid = gid = -1
        if self.owner.currentText() != self.orig_owner or len(self.paths) > 1 and self.owner.currentText():
            try:
                uid = pwd.getpwnam(self.owner.currentText()).pw_uid
            except KeyError:
                uid = -1
        if self.group.currentText() != self.orig_group or len(self.paths) > 1 and self.group.currentText():
            try:
                gid = grp.getgrnam(self.group.currentText()).gr_gid
            except KeyError:
                gid = -1
        mt = self.dt.dateTime().toSecsSinceEpoch() if self.time_group.isChecked() else None
        for t in targets:
            try:
                if os.path.islink(t):
                    continue
                st = os.stat(t)
                mode = stat.S_IMODE(st.st_mode)
                for cb, bit in self.boxes:
                    s = cb.checkState()
                    if s == Qt.CheckState.Checked:
                        mode |= bit
                    elif s == Qt.CheckState.Unchecked:
                        mode &= ~bit
                if mode != stat.S_IMODE(st.st_mode):
                    os.chmod(t, mode)
                if (uid != -1 and uid != st.st_uid) or (gid != -1 and gid != st.st_gid):
                    os.chown(t, uid, gid)
                if mt is not None:
                    os.utime(t, (st.st_atime, mt))
            except OSError as ex:
                errors.append("%s: %s" % (t, ex.strerror or ex))
        return errors


class PropertiesDialog(QtWidgets.QDialog):
    def __init__(self, path, parent=None, main=None):
        super().__init__(parent)
        self.setWindowTitle("Eigenschaften – " + os.path.basename(path))
        self.path = path
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        try:
            lst = os.lstat(path)
        except OSError as ex:
            lay.addWidget(QtWidgets.QLabel(str(ex)))
            lay.addWidget(button_box(self, QtWidgets.QDialogButtonBox.StandardButton.Close))
            return
        try:
            st = os.stat(path)
        except OSError:
            st = lst
        db = QtCore.QMimeDatabase()
        mt = db.mimeTypeForFile(path)

        def sel(text):
            l = QtWidgets.QLabel(text)
            l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            l.setWordWrap(True)
            return l

        form.addRow("Name:", sel(os.path.basename(path)))
        form.addRow("Ort:", sel(os.path.dirname(path)))
        form.addRow("Typ:", sel("%s (%s)" % (mt.comment(), mt.name())))
        if stat.S_ISLNK(lst.st_mode):
            form.addRow("Verweis auf:", sel(os.readlink(path)))
        self.size_label = sel("")
        if stat.S_ISDIR(st.st_mode):
            self.size_label.setText("wird berechnet…")
            QtCore.QTimer.singleShot(10, self.calc_size)
        else:
            self.size_label.setText("%s (%s Bytes)" % (human_size(st.st_size), format_size(st.st_size, "bytes")))
        form.addRow("Größe:", self.size_label)
        form.addRow("Geändert:", sel(time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(st.st_mtime))))
        form.addRow("Zugriff:", sel(time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(st.st_atime))))
        form.addRow("Status geändert:", sel(time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(st.st_ctime))))
        form.addRow("Rechte:", sel("%s (%04o)" % (stat.filemode(lst.st_mode), stat.S_IMODE(lst.st_mode))))
        form.addRow("Besitzer:", sel("%s : %s" % (_uname(st.st_uid), _gname(st.st_gid))))
        form.addRow("Inode / Links:", sel("%d / %d" % (st.st_ino, st.st_nlink)))
        free, total = (None, None)
        try:
            import shutil
            u = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path))
            free, total = u.free, u.total
        except OSError:
            pass
        if free is not None:
            form.addRow("Datenträger:", sel("%s frei von %s" % (human_size(free), human_size(total))))
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        attr = QtWidgets.QPushButton("Attribute ändern…")
        attr.clicked.connect(self.change_attrs)
        row.addWidget(attr)
        if main is not None:
            ow = QtWidgets.QPushButton("Öffnen mit…")
            ow.clicked.connect(lambda: (self.accept(), main.cmd_OpenWith()))
            row.addWidget(ow)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(button_box(self, QtWidgets.QDialogButtonBox.StandardButton.Close))

    def calc_size(self):
        total = 0
        n_files = n_dirs = 0
        t0 = time.monotonic()
        for root, dirs, files in os.walk(self.path):
            n_dirs += len(dirs)
            for f in files:
                n_files += 1
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
            if time.monotonic() - t0 > 0.2:
                QtWidgets.QApplication.processEvents()
                t0 = time.monotonic()
                if not self.isVisible():
                    return
        self.size_label.setText("%s (%s Bytes)\n%d Dateien, %d Verzeichnisse" % (
            human_size(total), format_size(total, "bytes"), n_files, n_dirs))

    def change_attrs(self):
        d = AttributesDialog([self.path], self)
        if qexec(d):
            err = d.apply()
            if err:
                QtWidgets.QMessageBox.warning(self, "Attribute", "\n".join(err[:20]))


# ---------------------------------------------------------------- pack / unpack

class PackDialog(QtWidgets.QDialog):
    def __init__(self, what, default_target, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dateien packen")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("%s packen in Archiv:" % what))
        self.target = QtWidgets.QLineEdit(default_target)
        lay.addWidget(self.target)
        fg = QtWidgets.QGroupBox("Packer")
        fl = QtWidgets.QHBoxLayout(fg)
        self.fmt_buttons = {}
        for f in vfs.PACK_FORMATS:
            rb = QtWidgets.QRadioButton(f.upper())
            if f == "7z" and not vfs.sevenzip():
                rb.setEnabled(False)
                rb.setToolTip("7z nicht installiert (apt install p7zip-full)")
            rb.toggled.connect(self._fmt_changed)
            fl.addWidget(rb)
            self.fmt_buttons[f] = rb
        self.fmt_buttons["zip"].setChecked(True)
        lay.addWidget(fg)
        form = QtWidgets.QFormLayout()
        self.level = QtWidgets.QSpinBox()
        self.level.setRange(0, 9)
        self.level.setValue(6)
        form.addRow("Kompressionsstufe:", self.level)
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.password.setEnabled(False)
        form.addRow("Passwort (nur 7z):", self.password)
        lay.addLayout(form)
        self.move = QtWidgets.QCheckBox("Dateien nach dem Packen löschen (verschieben)")
        self.each = QtWidgets.QCheckBox("Jede Datei in ein eigenes Archiv packen")
        lay.addWidget(self.move)
        lay.addWidget(self.each)
        lay.addWidget(button_box(self))

    def fmt(self):
        for f, rb in self.fmt_buttons.items():
            if rb.isChecked():
                return f
        return "zip"

    def _fmt_changed(self):
        if not hasattr(self, "password"):
            return
        f = self.fmt()
        self.password.setEnabled(f == "7z")
        t = self.target.text()
        d, n = os.path.split(t)
        for ext in sorted(vfs.PACK_FORMATS, key=len, reverse=True):
            if n.lower().endswith("." + ext):
                n = n[:-len(ext) - 1]
                break
        self.target.setText(os.path.join(d, n + "." + f))


class UnpackDialog(QtWidgets.QDialog):
    def __init__(self, what, dest, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dateien entpacken")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("%s entpacken nach:" % what))
        self.dest = QtWidgets.QLineEdit(dest)
        lay.addWidget(self.dest)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Nur Dateien dieses Typs:"))
        self.mask = QtWidgets.QLineEdit("*")
        row.addWidget(self.mask)
        lay.addLayout(row)
        self.separate = QtWidgets.QCheckBox("Jedes Archiv in ein eigenes Unterverzeichnis (Name des Archivs)")
        lay.addWidget(self.separate)
        lay.addWidget(button_box(self))


# ---------------------------------------------------------------- checksums

HASHES = ["md5", "sha1", "sha256", "sha512", "crc32"]


def file_hash(path, algo, progress=None):
    if algo == "crc32":
        c = 0
        with open(path, "rb") as fh:
            while True:
                b = fh.read(1 << 20)
                if not b:
                    break
                c = zlib.crc32(b, c)
                if progress:
                    progress()
        return "%08X" % (c & 0xFFFFFFFF)
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
            if progress:
                progress()
    return h.hexdigest()


class ChecksumCreateDialog(QtWidgets.QDialog):
    def __init__(self, files, base, parent=None):
        super().__init__(parent)
        self.files = files
        self.base = base
        self.setWindowTitle("Prüfsummen erzeugen (CRC32, MD5, SHA)")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("%d Datei(en)" % len(files)))
        fl = QtWidgets.QHBoxLayout()
        self.algo = {}
        for a in HASHES:
            rb = QtWidgets.QRadioButton(a.upper())
            fl.addWidget(rb)
            self.algo[a] = rb
        self.algo["sha256"].setChecked(True)
        lay.addLayout(fl)
        self.single = QtWidgets.QCheckBox("Eine Prüfsummendatei für alle Dateien")
        self.single.setChecked(True)
        lay.addWidget(self.single)
        self.name = QtWidgets.QLineEdit(os.path.join(base, (os.path.basename(files[0]) if len(files) == 1 else
                                                           os.path.basename(base.rstrip("/")) or "checksums")))
        lay.addWidget(QtWidgets.QLabel("Dateiname (ohne Endung):"))
        lay.addWidget(self.name)
        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(self.output)
        row = QtWidgets.QHBoxLayout()
        self.go = QtWidgets.QPushButton("Erzeugen")
        self.go.clicked.connect(self.run)
        close = QtWidgets.QPushButton("Schließen")
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.go)
        row.addWidget(close)
        lay.addLayout(row)
        self.resize(640, 420)

    def run(self):
        algo = next(a for a, rb in self.algo.items() if rb.isChecked())
        ext = "sfv" if algo == "crc32" else algo
        lines = []
        self.go.setEnabled(False)
        tick = lambda: QtWidgets.QApplication.processEvents()  # noqa: E731
        for f in self.files:
            if os.path.isdir(f):
                continue
            try:
                h = file_hash(f, algo, tick)
            except OSError as ex:
                self.output.appendPlainText("FEHLER %s: %s" % (f, ex))
                continue
            rel = os.path.relpath(f, self.base)
            line = ("%s %s" % (rel, h)) if algo == "crc32" else ("%s *%s" % (h, rel))
            lines.append((f, line))
            self.output.appendPlainText(line)
        try:
            if self.single.isChecked():
                with open(self.name.text() + "." + ext, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(l for _f, l in lines) + "\n")
            else:
                for f, l in lines:
                    with open(f + "." + ext, "w", encoding="utf-8") as fh:
                        fh.write(l.replace(os.path.relpath(f, self.base), os.path.basename(f)) + "\n")
            self.output.appendPlainText("\nFertig.")
        except OSError as ex:
            self.output.appendPlainText("FEHLER beim Schreiben: %s" % ex)
        self.go.setEnabled(True)


def verify_checksum_file(path, parent):
    ext = path.rsplit(".", 1)[-1].lower()
    algo = {"md5": "md5", "sha1": "sha1", "sha": "sha1", "sha256": "sha256", "sha512": "sha512",
            "sfv": "crc32"}.get(ext)
    if algo is None:
        QtWidgets.QMessageBox.information(parent, "Prüfsummen", "Unbekannter Prüfsummen-Dateityp.")
        return
    base = os.path.dirname(path)
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Prüfsummen verifizieren – " + os.path.basename(path))
    lay = QtWidgets.QVBoxLayout(dlg)
    out = QtWidgets.QPlainTextEdit()
    out.setReadOnly(True)
    out.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
    lay.addWidget(out)
    lay.addWidget(button_box(dlg, QtWidgets.QDialogButtonBox.StandardButton.Close))
    dlg.resize(640, 420)
    dlg.show()
    ok = bad = missing = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if algo == "crc32":
            name, _s, h = line.rpartition(" ")
        else:
            h, _s, name = line.partition(" ")
            name = name.lstrip(" *")
        fp = os.path.join(base, name)
        QtWidgets.QApplication.processEvents()
        if not os.path.isfile(fp):
            out.appendPlainText("FEHLT   %s" % name)
            missing += 1
            continue
        try:
            actual = file_hash(fp, algo, QtWidgets.QApplication.processEvents)
        except OSError as ex:
            out.appendPlainText("FEHLER  %s: %s" % (name, ex))
            bad += 1
            continue
        if actual.lower() == h.lower():
            out.appendPlainText("OK      %s" % name)
            ok += 1
        else:
            out.appendPlainText("FALSCH  %s" % name)
            bad += 1
    out.appendPlainText("\n%d OK, %d fehlerhaft, %d fehlen" % (ok, bad, missing))
    qexec(dlg)


# ---------------------------------------------------------------- split / combine

class SplitDialog(QtWidgets.QDialog):
    SIZES = [("1,44 MB (Diskette)", 1457664), ("10 MB", 10 * 2 ** 20), ("100 MB", 100 * 2 ** 20),
             ("650 MB (CD)", 650 * 2 ** 20), ("700 MB (CD)", 700 * 2 ** 20), ("1 GB", 2 ** 30),
             ("4095 MB (FAT32)", 4095 * 2 ** 20), ("4,7 GB (DVD)", 4700 * 10 ** 6)]

    def __init__(self, path, dest, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Datei aufteilen")
        lay = QtWidgets.QFormLayout(self)
        lay.addRow(QtWidgets.QLabel("Datei aufteilen: <b>%s</b> (%s)" % (
            os.path.basename(path), human_size(os.path.getsize(path)))))
        self.dest = QtWidgets.QLineEdit(dest)
        lay.addRow("Ziel:", self.dest)
        self.size = QtWidgets.QComboBox()
        self.size.setEditable(True)
        for label, _n in self.SIZES:
            self.size.addItem(label)
        self.size.setCurrentIndex(2)
        lay.addRow("Teilgröße (oder Bytes / z.B. 25M):", self.size)
        self.crc = QtWidgets.QCheckBox("CRC32-Datei für das Zusammenfügen anlegen")
        self.crc.setChecked(True)
        lay.addRow(self.crc)
        lay.addRow(button_box(self))

    def part_size(self):
        t = self.size.currentText().strip()
        for label, n in self.SIZES:
            if t == label:
                return n
        mult = 1
        t2 = t.upper().replace(" ", "").replace(",", ".")
        for suf, m in (("KB", 1024), ("K", 1024), ("MB", 2 ** 20), ("M", 2 ** 20), ("GB", 2 ** 30), ("G", 2 ** 30)):
            if t2.endswith(suf):
                t2 = t2[:-len(suf)]
                mult = m
                break
        try:
            return int(float(t2) * mult)
        except ValueError:
            return 0


def split_file(path, dest_dir, part_size, write_crc, parent):
    total = os.path.getsize(path)
    if part_size <= 0:
        return
    n_parts = (total + part_size - 1) // part_size
    prog = QtWidgets.QProgressDialog("Teile Datei…", "Abbrechen", 0, max(1, n_parts), parent)
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    base = os.path.join(dest_dir, os.path.basename(path))
    crc = 0
    with open(path, "rb") as fi:
        for i in range(n_parts):
            if prog.wasCanceled():
                return
            prog.setValue(i)
            with open("%s.%03d" % (base, i + 1), "wb") as fo:
                remaining = part_size
                while remaining > 0:
                    b = fi.read(min(1 << 20, remaining))
                    if not b:
                        break
                    crc = zlib.crc32(b, crc)
                    fo.write(b)
                    remaining -= len(b)
                    QtWidgets.QApplication.processEvents()
    prog.setValue(n_parts)
    if write_crc:
        with open(base + ".crc", "w", encoding="utf-8") as fh:
            fh.write("filename=%s\nsize=%d\ncrc32=%08X\n" % (os.path.basename(path), total, crc & 0xFFFFFFFF))


def combine_files(first, dest_dir, parent):
    """first: path to .001 (or any part); combine all consecutive parts."""
    stem = first[:-4] if first[-4] == "." and first[-3:].isdigit() else first
    parts = []
    i = 1
    while os.path.exists("%s.%03d" % (stem, i)):
        parts.append("%s.%03d" % (stem, i))
        i += 1
    if not parts:
        QtWidgets.QMessageBox.warning(parent, "Zusammenfügen", "Keine Teildateien (*.001, *.002…) gefunden.")
        return None
    out_name = os.path.basename(stem)
    expected = None
    if os.path.exists(stem + ".crc"):
        with open(stem + ".crc", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, _s, v = line.strip().partition("=")
                if k == "filename" and v:
                    out_name = v
                elif k == "crc32":
                    expected = v.upper()
    target, ok = QtWidgets.QInputDialog.getText(parent, "Dateien zusammenfügen",
                                                "%d Teile zusammenfügen nach:" % len(parts),
                                                text=os.path.join(dest_dir, out_name))
    if not ok or not target:
        return None
    if os.path.exists(target) and QtWidgets.QMessageBox.question(parent, "Zusammenfügen",
                                                                 "%s existiert. Überschreiben?" % target) \
            != QtWidgets.QMessageBox.StandardButton.Yes:
        return None
    crc = 0
    prog = QtWidgets.QProgressDialog("Füge zusammen…", "Abbrechen", 0, len(parts), parent)
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    with open(target, "wb") as fo:
        for n, p in enumerate(parts):
            if prog.wasCanceled():
                return None
            prog.setValue(n)
            with open(p, "rb") as fi:
                while True:
                    b = fi.read(1 << 20)
                    if not b:
                        break
                    crc = zlib.crc32(b, crc)
                    fo.write(b)
                    QtWidgets.QApplication.processEvents()
    prog.setValue(len(parts))
    if expected and expected != "%08X" % (crc & 0xFFFFFFFF):
        QtWidgets.QMessageBox.warning(parent, "Zusammenfügen", "CRC-Fehler! Die Datei ist beschädigt.")
    elif expected:
        QtWidgets.QMessageBox.information(parent, "Zusammenfügen", "Fertig – CRC korrekt.")
    return target


# ---------------------------------------------------------------- hotlist

class HotlistDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verzeichnis-Hotlist konfigurieren")
        lay = QtWidgets.QHBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Titel", "Pfad"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        for item in config.get("hotlist", []):
            self._add(item.get("title", ""), item.get("path", ""))
        lay.addWidget(self.table, 1)
        col = QtWidgets.QVBoxLayout()
        for text, fn in [("Hinzufügen", lambda: self._add("Neu", os.getcwd())),
                         ("Trennlinie", lambda: self._add("-", "")),
                         ("Entfernen", self._remove), ("Nach oben", lambda: self._move(-1)),
                         ("Nach unten", lambda: self._move(1))]:
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        col.addWidget(button_box(self))
        lay.addLayout(col)
        self.resize(700, 400)

    def _add(self, title, path):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(title))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(path))

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _move(self, d):
        r = self.table.currentRow()
        t = r + d
        if r < 0 or not 0 <= t < self.table.rowCount():
            return
        a = [self.table.item(r, c).text() for c in range(2)]
        b = [self.table.item(t, c).text() for c in range(2)]
        for c in range(2):
            self.table.item(r, c).setText(b[c])
            self.table.item(t, c).setText(a[c])
        self.table.setCurrentCell(t, 0)

    def save(self):
        items = []
        for r in range(self.table.rowCount()):
            items.append({"title": self.table.item(r, 0).text(), "path": self.table.item(r, 1).text()})
        config["hotlist"] = items
        config.save()


# ---------------------------------------------------------------- settings

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, commands, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.commands = commands
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)

        # display
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.cb = {}
        for key, label in [("show_hidden", "Versteckte Dateien anzeigen (Ctrl+H)"),
                           ("dirs_first", "Verzeichnisse immer zuerst"),
                           ("show_icons", "Symbole anzeigen"),
                           ("show_buttonbar", "Buttonleiste anzeigen"),
                           ("show_drivebar", "Laufwerksleiste anzeigen"),
                           ("show_cmdline", "Kommandozeile anzeigen"),
                           ("show_fkeys", "Funktionstastenleiste anzeigen"),
                           ("show_drivebuttons", "Laufwerksbuttons (c: d: …) anzeigen"),
                           ("show_tabs_always", "Tab-Leiste immer anzeigen (auch bei einem Tab)"),
                           ("show_dotdot", "Eintrag „..“ anzeigen"),
                           ("alt_rows", "Zeilen abwechselnd einfärben"),
                           ("natural_sort", "Natürliche Sortierung (Datei2 vor Datei10)"),
                           ("case_sensitive_sort", "Groß-/Kleinschreibung beim Sortieren beachten"),
                           ("col_ext", "Spalte „Erw.“ anzeigen"), ("col_size", "Spalte „Größe“ anzeigen"),
                           ("col_date", "Spalte „Datum“ anzeigen"), ("col_attr", "Spalte „Attr.“ anzeigen")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(bool(config.get(key)))
            self.cb[key] = c
            f.addRow(c)
        self.theme = QtWidgets.QComboBox()
        self.theme_vals = ["system", "light", "dark"]
        self.theme.addItems(["System", "Hell", "Dunkel"])
        self.theme.setCurrentIndex(self.theme_vals.index(config.get("theme", "system"))
                                   if config.get("theme") in self.theme_vals else 0)
        f.addRow("Farbschema:", self.theme)
        self.size_fmt = QtWidgets.QComboBox()
        self.size_fmt.addItems(["Bytes (1.234.567)", "Dynamisch (1,2 M)"])
        self.size_fmt.setCurrentIndex(0 if config.get("size_format") == "bytes" else 1)
        f.addRow("Dateigröße:", self.size_fmt)
        self.date_fmt = QtWidgets.QLineEdit(config.get("date_format"))
        f.addRow("Datumsformat (Qt):", self.date_fmt)
        self.font_btn = QtWidgets.QPushButton(self._font_text())
        self.font_btn.clicked.connect(self._pick_font)
        f.addRow("Schrift der Dateilisten:", self.font_btn)
        tabs.addTab(w, "Darstellung")

        # operation
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        for key, label in [("confirm_delete", "Löschen bestätigen"),
                           ("use_trash", "In den Papierkorb löschen (F8/Entf); Shift+Entf löscht endgültig"),
                           ("confirm_drop", "Drag & Drop bestätigen"),
                           ("confirm_exit", "Beenden bestätigen"),
                           ("dblclick_up", "Doppelklick auf freie Fläche = übergeordnetes Verzeichnis")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(bool(config.get(key)))
            self.cb[key] = c
            f.addRow(c)
        tabs.addTab(w, "Bedienung")

        # quick search (TC: Konfiguration > Schnellsuche)
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        from .panel import qs_mode
        self.qs_vals = ["ctrlalt", "alt", "letters", "letters_dialog", "off"]
        self.qs = QtWidgets.QComboBox()
        self.qs.addItems(["Strg+Alt+Buchstaben (TC-Standard)", "Alt+Buchstaben", "Nur Buchstaben",
                          "Buchstaben mit Suchen-Dialog", "Deaktiviert (Buchstaben → Kommandozeile)"])
        self.qs.setCurrentIndex(self.qs_vals.index(qs_mode()))
        f.addRow("Schnellsuche starten mit:", self.qs)
        for key, label in [("qs_show_dialog", "Suchdialog auch bei Strg+Alt / Alt anzeigen "
                                              "(sonst unsichtbar, Anzeige in der Statuszeile)"),
                           ("qs_match_begin", "Anfang: Name muss mit der Eingabe beginnen (sonst * davor)"),
                           ("qs_match_end", "Ende: Name muss mit der Eingabe enden (sonst * danach)"),
                           ("qs_filter", "Filter: nur passende Dateien anzeigen (immer, nicht nur mit Strg+S)")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(bool(config.get(key, key == "qs_match_begin")))
            self.cb[key] = c
            f.addRow(c)
        self.qs_kind = QtWidgets.QComboBox()
        self.qs_kind_vals = ["both", "files", "dirs"]
        self.qs_kind.addItems(["Dateien und Verzeichnisse", "Nur Dateien", "Nur Verzeichnisse"])
        self.qs_kind.setCurrentIndex(self.qs_kind_vals.index(config.get("qs_kind", "both"))
                                     if config.get("qs_kind") in self.qs_kind_vals else 0)
        f.addRow("Suchen in:", self.qs_kind)
        hint = QtWidgets.QLabel("Platzhalter: * beliebig viele Zeichen, ? genau ein Zeichen. Erneutes Tippen des "
                                "letzten Buchstabens oder ↑/↓ springt zum nächsten Treffer. Strg+S öffnet die "
                                "Schnellsuche mit Filter, Esc hebt den Filter auf.")
        hint.setWordWrap(True)
        f.addRow(hint)
        tabs.addTab(w, "Schnellsuche")

        # selection
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        for key, label in [("select_all_dirs", "Strg+A / Strg+Num+ markiert auch Verzeichnisse"),
                           ("select_group_dirs", "Num+ / Num− / Num* gelten auch für Verzeichnisse"),
                           ("plusminus_main", "+ − * der Haupttastatur wie Ziffernblock verwenden "
                                              "(wenn Kommandozeile leer)"),
                           ("mark_with_right_mouse", "Rechte Maustaste markiert (statt Kontextmenü)"),
                           ("space_moves_down", "Leertaste bewegt Cursor nach unten")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(bool(config.get(key)))
            self.cb[key] = c
            f.addRow(c)
        tabs.addTab(w, "Markieren")

        # programs
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.editor = QtWidgets.QLineEdit(config.get("editor"))
        self.viewer = QtWidgets.QLineEdit(config.get("viewer"))
        self.viewer.setPlaceholderText("leer = interner Lister")
        self.terminal = QtWidgets.QLineEdit(config.get("terminal"))
        f.addRow("Editor (F4), %s = Datei:", self.editor)
        f.addRow("Externer Betrachter (F3):", self.viewer)
        f.addRow("Terminal:", self.terminal)
        for key, label in [("use_internal_editor", "Internen Editor für F4 verwenden (sonst obiges Programm)"),
                           ("editor_wrap", "Editor: Zeilenumbruch"),
                           ("editor_line_numbers", "Editor: Zeilennummern"),
                           ("lister_wrap", "Lister: Zeilenumbruch")]:
            c = QtWidgets.QCheckBox(label)
            c.setChecked(bool(config.get(key)))
            self.cb[key] = c
            f.addRow(c)
        self.tab_width = QtWidgets.QSpinBox()
        self.tab_width.setRange(1, 16)
        self.tab_width.setValue(int(config.get("editor_tab_width", 4)))
        f.addRow("Editor: Tabulatorbreite:", self.tab_width)
        self.ed_font = QtWidgets.QSpinBox()
        self.ed_font.setRange(0, 48)
        self.ed_font.setSpecialValueText("Standard")
        self.ed_font.setValue(int(config.get("editor_font_size") or 0))
        f.addRow("Editor/Lister: Schriftgröße:", self.ed_font)
        tabs.addTab(w, "Programme")

        # colors
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.colors = {}
        for key, label in [("color_mark", "Markierte Dateien"), ("color_text", "Text"), ("color_bg", "Hintergrund"),
                           ("color_cursor", "Cursor (Auswahlbalken)"), ("color_cursor_text", "Cursor-Text")]:
            b = QtWidgets.QPushButton()
            self.colors[key] = config.get(key) or ""
            self._color_btn(b, key)
            b.clicked.connect(lambda _c=False, k=key, bt=b: self._pick_color(k, bt))
            r = QtWidgets.QPushButton("Standard")
            r.clicked.connect(lambda _c=False, k=key, bt=b: (self.colors.__setitem__(k, ""), self._color_btn(bt, k)))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(b, 1)
            row.addWidget(r)
            f.addRow(label + ":", row)
        tabs.addTab(w, "Farben")

        # start
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.start_left = QtWidgets.QLineEdit(config.get("start_left", ""))
        self.start_right = QtWidgets.QLineEdit(config.get("start_right", ""))
        for e in (self.start_left, self.start_right):
            e.setPlaceholderText("leer = zuletzt benutztes Verzeichnis")
        f.addRow("Startverzeichnis links:", self.start_left)
        f.addRow("Startverzeichnis rechts:", self.start_right)
        tabs.addTab(w, "Start")

        # drives
        w = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(w)
        dl.addWidget(QtWidgets.QLabel("Laufwerksbuchstaben zuordnen (Buchstabe ändern per Doppelklick). "
                                      "„c:“ oder „d:\\ordner“ funktioniert in Pfadzeile und Kommandozeile."))
        self.drives = QtWidgets.QTableWidget(0, 3)
        self.drives.setHorizontalHeaderLabels(["Buchstabe", "Einhängepunkt", "Name"])
        self.drives.horizontalHeader().setStretchLastSection(True)
        self.drives.verticalHeader().hide()
        from .utils import drive_letters
        for letter, label, path, _icon in drive_letters():
            r = self.drives.rowCount()
            self.drives.insertRow(r)
            self.drives.setItem(r, 0, QtWidgets.QTableWidgetItem(letter))
            for c, v in ((1, path), (2, label)):
                it = QtWidgets.QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.drives.setItem(r, c, it)
        self.drives.resizeColumnsToContents()
        dl.addWidget(self.drives)
        tabs.addTab(w, "Laufwerke")

        # buttonbar
        w = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(w)
        self.btn_list = QtWidgets.QListWidget()
        for b in config.get("buttons", []):
            self._add_btn_item(b)
        bl.addWidget(self.btn_list, 1)
        col = QtWidgets.QVBoxLayout()
        self.cmd_combo = QtWidgets.QComboBox()
        self.cmd_combo.addItem("--- Trennlinie ---", "-")
        for name in sorted(commands):
            self.cmd_combo.addItem("%s – %s" % (name, commands[name][0]), name)
        col.addWidget(self.cmd_combo)
        self.ext_cmd = QtWidgets.QLineEdit()
        self.ext_cmd.setPlaceholderText("oder externer Befehl, z.B. gimp %s")
        col.addWidget(self.ext_cmd)
        for text, fn in [("Hinzufügen", self._btn_add), ("Symbol ändern…", self._btn_icon),
                         ("Entfernen", self._btn_remove),
                         ("Nach oben", lambda: self._btn_move(-1)), ("Nach unten", lambda: self._btn_move(1)),
                         ("Standard wiederherstellen", self._btn_reset)]:
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        bl.addLayout(col)
        tabs.addTab(w, "Buttonleiste")

        # hotkeys
        w = QtWidgets.QWidget()
        hl = QtWidgets.QVBoxLayout(w)
        hl.addWidget(QtWidgets.QLabel("Eigene Tastenkürzel (Doppelklick auf Taste zum Ändern, leer = Standard):"))
        self.hk = QtWidgets.QTableWidget(0, 3)
        self.hk.setHorizontalHeaderLabels(["Befehl", "Beschreibung", "Taste"])
        self.hk.horizontalHeader().setStretchLastSection(True)
        user = config.get("user_hotkeys", {})
        for name in sorted(commands):
            r = self.hk.rowCount()
            self.hk.insertRow(r)
            it = QtWidgets.QTableWidgetItem(name)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.hk.setItem(r, 0, it)
            it = QtWidgets.QTableWidgetItem(commands[name][0])
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.hk.setItem(r, 1, it)
            self.hk.setItem(r, 2, QtWidgets.QTableWidgetItem(user.get(name, commands[name][1] or "")))
        self.hk.resizeColumnsToContents()
        hl.addWidget(self.hk)
        tabs.addTab(w, "Tastenkürzel")

        lay.addWidget(button_box(self))
        self.resize(760, 520)
        self.font = None

    def _color_btn(self, b, key):
        c = self.colors.get(key)
        b.setText(c or "(Standard)")
        b.setStyleSheet("background:%s;color:%s" % (c, "#000" if QtGui.QColor(c).lightness() > 128 else "#fff")
                        if c else "")

    def _pick_color(self, key, b):
        start = QtGui.QColor(self.colors.get(key) or "#ffffff")
        c = QtWidgets.QColorDialog.getColor(start, self, "Farbe wählen")
        if c.isValid():
            self.colors[key] = c.name()
            self._color_btn(b, key)

    def _font_text(self):
        fam = config.get("font_family") or "Systemschrift"
        sz = config.get("font_size") or ""
        return "%s %s" % (fam, sz)

    def _pick_font(self):
        cur = QtGui.QFont(config.get("font_family") or self.font_btn.font().family())
        if config.get("font_size"):
            cur.setPointSize(config["font_size"])
        res = QtWidgets.QFontDialog.getFont(cur, self)
        # PyQt5 returns (font, ok), PyQt6 too
        font, ok = res if isinstance(res[0], QtGui.QFont) else (res[1], res[0])
        if ok:
            self.font = font
            self.font_btn.setText("%s %d" % (font.family(), font.pointSize()))

    def _add_btn_item(self, b):
        cmd, icon, tip = (list(b) + ["", "", ""])[:3]
        it = QtWidgets.QListWidgetItem("———" if cmd == "-" else "%s  (%s)" % (tip or cmd, cmd))
        it.setData(Qt.ItemDataRole.UserRole, [cmd, icon, tip])
        from .pixicons import builtin_icon
        if icon:
            from .iconpicker import load_icon
            it.setIcon(load_icon(icon))
        elif builtin_icon(cmd) is not None:
            it.setIcon(builtin_icon(cmd))
        self.btn_list.addItem(it)

    def _btn_icon(self):
        it = self.btn_list.currentItem()
        if it is None:
            return
        cmd, icon, tip = (list(it.data(Qt.ItemDataRole.UserRole)) + ["", "", ""])[:3]
        if cmd == "-":
            return
        from .iconpicker import pick_icon, load_icon
        r = pick_icon(icon, self)
        if r is not None:
            it.setData(Qt.ItemDataRole.UserRole, [cmd, r, tip])
            it.setIcon(load_icon(r))

    def _btn_add(self):
        ext = self.ext_cmd.text().strip()
        if ext:
            self._add_btn_item([ext, "system-run", ext])
            self.ext_cmd.clear()
            return
        name = self.cmd_combo.currentData()
        if name == "-":
            self._add_btn_item(["-", "", ""])
        else:
            self._add_btn_item([name, self.commands[name][2] or "", self.commands[name][0]])

    def _btn_remove(self):
        r = self.btn_list.currentRow()
        if r >= 0:
            self.btn_list.takeItem(r)

    def _btn_move(self, d):
        r = self.btn_list.currentRow()
        t = r + d
        if r < 0 or not 0 <= t < self.btn_list.count():
            return
        it = self.btn_list.takeItem(r)
        self.btn_list.insertItem(t, it)
        self.btn_list.setCurrentRow(t)

    def _btn_reset(self):
        from .config import DEFAULT_BUTTONS
        self.btn_list.clear()
        for b in DEFAULT_BUTTONS:
            self._add_btn_item(b)

    def apply(self):
        for k, c in self.cb.items():
            config[k] = c.isChecked()
        config["size_format"] = "bytes" if self.size_fmt.currentIndex() == 0 else "dynamic"
        config["date_format"] = self.date_fmt.text().strip() or "dd.MM.yyyy HH:mm"
        config["quicksearch_mode"] = self.qs_vals[self.qs.currentIndex()]
        config["qs_mode_v2"] = True
        config["qs_kind"] = self.qs_kind_vals[self.qs_kind.currentIndex()]
        config["editor"] = self.editor.text().strip()
        config["viewer"] = self.viewer.text().strip()
        config["terminal"] = self.terminal.text().strip()
        config["theme"] = self.theme_vals[self.theme.currentIndex()]
        config["editor_tab_width"] = self.tab_width.value()
        config["editor_font_size"] = self.ed_font.value()
        config["start_left"] = self.start_left.text().strip()
        config["start_right"] = self.start_right.text().strip()
        for k, v in self.colors.items():
            config[k] = v
        mapping = dict(config.get("drive_letters") or {})
        used = {}
        for r in range(self.drives.rowCount()):
            letter = self.drives.item(r, 0).text().strip().lower().rstrip(":")[:1]
            path = self.drives.item(r, 1).text()
            if letter and letter.isalpha() and letter not in used:
                # free the letter if another (unmounted) path held it
                for pth, l in list(mapping.items()):
                    if l == letter and pth != path:
                        del mapping[pth]
                mapping[path] = letter
                used[letter] = path
        config["drive_letters"] = mapping
        if self.font is not None:
            config["font_family"] = self.font.family()
            config["font_size"] = self.font.pointSize()
        config["buttons"] = [self.btn_list.item(i).data(Qt.ItemDataRole.UserRole)
                             for i in range(self.btn_list.count())]
        hk = {}
        for r in range(self.hk.rowCount()):
            name = self.hk.item(r, 0).text()
            key = self.hk.item(r, 2).text().strip()
            if key != (self.commands[name][1] or ""):
                hk[name] = key
        config["user_hotkeys"] = hk
        config.save()


# ---------------------------------------------------------------- symlink

class LinkDialog(QtWidgets.QDialog):
    def __init__(self, target, link_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Verknüpfung erstellen")
        f = QtWidgets.QFormLayout(self)
        self.target = QtWidgets.QLineEdit(target)
        self.link = QtWidgets.QLineEdit(link_path)
        f.addRow("Ziel der Verknüpfung:", self.target)
        f.addRow("Name der Verknüpfung:", self.link)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(["Symbolischer Link (absolut)", "Symbolischer Link (relativ)", "Harter Link"])
        f.addRow("Art:", self.kind)
        f.addRow(button_box(self))
        self.resize(560, 10)

    def create(self):
        t = self.target.text().strip()
        l = self.link.text().strip()
        k = self.kind.currentIndex()
        if k == 2:
            os.link(t, l)
        elif k == 1:
            os.symlink(os.path.relpath(t, os.path.dirname(l)), l)
        else:
            os.symlink(t, l)
