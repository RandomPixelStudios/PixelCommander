"""Background file operations with progress dialog (copy, move, delete, extract, pack)."""
import os
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import zipfile

from .qt import QtCore, QtWidgets, Qt, Signal, qexec
from .utils import format_size, format_time, move_to_trash, Mask, human_size
from . import vfs

CHUNK = 1 << 20


class Cancelled(Exception):
    pass


class FileOpWorker(QtCore.QThread):
    progress = Signal(str, str, int, int)          # title-line, file, file pct, total pct
    ask = Signal(object)                            # request dict (blocking)
    done = Signal(bool, str)                        # ok, message

    def __init__(self, op, parent=None, **kw):
        super().__init__(parent)
        self.op = op
        self.kw = kw
        self.cancel = False
        self.paused = threading.Event()
        self.paused.set()
        self.answer = None
        self.overwrite_policy = None   # None | all | skip | older | rename
        self.skip_errors = False
        self.total = 0
        self.done_bytes = 0
        self.errors = []
        self._last_emit = 0.0

    # ------------------------------------------------------------ helpers
    def check(self):
        self.paused.wait()
        if self.cancel:
            raise Cancelled()

    def request(self, **req):
        self.answer = None
        self.ask.emit(req)  # BlockingQueuedConnection -> answer set by GUI
        return self.answer

    def emit_progress(self, line, name, fpct, force=False):
        now = time.monotonic()
        if force or now - self._last_emit > 0.05:
            self._last_emit = now
            tp = int(self.done_bytes * 100 / self.total) if self.total else 0
            self.progress.emit(line, name, fpct, min(tp, 100))

    def handle_error(self, what, ex):
        if self.skip_errors:
            self.errors.append("%s: %s" % (what, ex))
            return "skip"
        ans = self.request(kind="error", text="%s\n\n%s" % (what, ex))
        if ans == "retry":
            return "retry"
        if ans == "skip_all":
            self.skip_errors = True
        if ans in ("skip", "skip_all"):
            self.errors.append("%s: %s" % (what, ex))
            return "skip"
        raise Cancelled()

    def resolve_conflict(self, src, dst):
        """Return target path to write or None to skip."""
        pol = self.overwrite_policy
        if pol is None:
            ans = self.request(kind="overwrite", src=src, dst=dst)
        else:
            ans = pol
        if ans in ("all", "skip", "older", "rename_all", "larger") and pol is None and ans != "skip":
            pass
        if ans == "cancel" or ans is None:
            raise Cancelled()
        if ans == "overwrite":
            return dst
        if ans == "all":
            self.overwrite_policy = "all"
            return dst
        if ans == "skip":
            return None
        if ans == "skip_all":
            self.overwrite_policy = "skip_all"
            return None
        if ans == "skip_all" or pol == "skip_all":
            return None
        if ans in ("older", "older_all"):
            if ans == "older_all":
                self.overwrite_policy = "older_all"
            try:
                return dst if os.stat(src).st_mtime > os.stat(dst).st_mtime else None
            except OSError:
                return dst
        if ans in ("rename", "rename_all"):
            if ans == "rename_all":
                self.overwrite_policy = "rename_all"
            from .utils import unique_name
            return unique_name(dst)
        if isinstance(ans, tuple) and ans[0] == "newname":
            return os.path.join(os.path.dirname(dst), ans[1])
        return None

    # ------------------------------------------------------------ run
    def run(self):
        try:
            getattr(self, "do_" + self.op)(**self.kw)
            msg = ""
            if self.errors:
                msg = "%d Fehler:\n" % len(self.errors) + "\n".join(self.errors[:30])
            self.done.emit(not self.errors, msg)
        except Cancelled:
            self.done.emit(False, "Abgebrochen")
        except Exception as ex:  # noqa: BLE001
            self.done.emit(False, "Fehler: %s" % ex)

    # ------------------------------------------------------------ copy / move
    def _plan(self, sources, dest_dir, new_name, mask):
        """Build list of (src, dst, kind) with kind in dir/file/link."""
        items = []
        total = 0
        for src in sources:
            self.check()
            src = src.rstrip("/") or "/"
            name = new_name if new_name else os.path.basename(src)
            dst = os.path.join(dest_dir, name)
            if os.path.isdir(src) and not os.path.islink(src):
                rs = os.path.realpath(src)
                rd = os.path.realpath(dst)
                if rd == rs or rd.startswith(rs + os.sep):
                    raise Exception("Ein Verzeichnis kann nicht in sich selbst kopiert werden:\n" + src)
                items.append((src, dst, "dir"))
                for root, dirs, files in os.walk(src):
                    self.check()
                    rel = os.path.relpath(root, src)
                    troot = dst if rel == "." else os.path.join(dst, rel)
                    for d in sorted(dirs):
                        p = os.path.join(root, d)
                        if os.path.islink(p):
                            items.append((p, os.path.join(troot, d), "link"))
                        else:
                            items.append((p, os.path.join(troot, d), "dir"))
                    for f in sorted(files):
                        p = os.path.join(root, f)
                        if mask and not mask.match(f):
                            continue
                        if os.path.islink(p):
                            items.append((p, os.path.join(troot, f), "link"))
                        else:
                            try:
                                total += os.path.getsize(p)
                            except OSError:
                                pass
                            items.append((p, os.path.join(troot, f), "file"))
            elif os.path.islink(src):
                items.append((src, dst, "link"))
            else:
                if mask and not mask.match(os.path.basename(src)):
                    continue
                try:
                    total += os.path.getsize(src)
                except OSError:
                    pass
                items.append((src, dst, "file"))
        return items, total

    def _copy_file(self, src, dst, line):
        if os.path.lexists(dst):
            if os.path.samefile(src, dst) if os.path.exists(dst) else False:
                raise Exception("Quelle und Ziel sind identisch: " + src)
            dst = self.resolve_conflict(src, dst)
            if dst is None:
                try:
                    self.done_bytes += os.path.getsize(src)
                except OSError:
                    pass
                return False
        size = os.path.getsize(src)
        tmp = dst
        copied = 0
        with open(src, "rb") as fi:
            if os.path.lexists(dst) and not os.path.isdir(dst):
                try:
                    os.unlink(dst)
                except OSError:
                    pass
            with open(tmp, "wb") as fo:
                while True:
                    self.check()
                    buf = fi.read(CHUNK)
                    if not buf:
                        break
                    fo.write(buf)
                    copied += len(buf)
                    self.done_bytes += len(buf)
                    self.emit_progress(line, os.path.basename(src), int(copied * 100 / size) if size else 100)
        try:
            shutil.copystat(src, dst)
        except OSError:
            pass
        return True

    def _copy_link(self, src, dst):
        target = os.readlink(src)
        if os.path.lexists(dst):
            dst = self.resolve_conflict(src, dst)
            if dst is None:
                return
            if os.path.lexists(dst):
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst)
                else:
                    os.unlink(dst)
        os.symlink(target, dst)

    def do_copy(self, sources, dest_dir, new_name=None, mask=None, move=False):
        mask = Mask(mask) if mask and mask.strip() not in ("*", "*.*") else None
        verb = "Verschiebe" if move else "Kopiere"
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        if move and not mask:
            # fast path: rename on same filesystem
            rest = []
            for src in sources:
                self.check()
                dst = os.path.join(dest_dir, new_name or os.path.basename(src.rstrip("/")))
                try:
                    if os.path.lexists(dst):
                        if os.path.isdir(dst) and os.path.isdir(src) and not os.path.islink(src):
                            rest.append(src)
                            continue
                        dst2 = self.resolve_conflict(src, dst)
                        if dst2 is None:
                            continue
                        if os.path.lexists(dst2):
                            if os.path.isdir(dst2) and not os.path.islink(dst2):
                                shutil.rmtree(dst2)
                            else:
                                os.unlink(dst2)
                        dst = dst2
                    if os.stat(src, follow_symlinks=False).st_dev == os.stat(dest_dir).st_dev:
                        os.rename(src, dst)
                        self.emit_progress("%s %s" % (verb, src), os.path.basename(src), 100, True)
                    else:
                        rest.append(src)
                except OSError:
                    rest.append(src)
            sources = rest
            if not sources:
                return
        items, self.total = self._plan(sources, dest_dir, new_name, mask)
        dirs_made = []
        for src, dst, kind in items:
            self.check()
            line = "%s %s\n→ %s" % (verb, src, dst)
            while True:
                try:
                    if kind == "dir":
                        if not os.path.isdir(dst):
                            if os.path.lexists(dst):
                                raise Exception("Ziel existiert als Datei: " + dst)
                            os.makedirs(dst)
                        dirs_made.append((src, dst))
                    elif kind == "link":
                        self._copy_link(src, dst)
                    else:
                        self.emit_progress(line, os.path.basename(src), 0, True)
                        self._copy_file(src, dst, line)
                    break
                except Cancelled:
                    if kind == "file" and os.path.exists(dst):
                        try:
                            os.unlink(dst)  # remove partial file
                        except OSError:
                            pass
                    raise
                except Exception as ex:  # noqa: BLE001
                    if self.handle_error("%s → %s" % (src, dst), ex) != "retry":
                        break
        for src, dst in reversed(dirs_made):
            try:
                shutil.copystat(src, dst)
            except OSError:
                pass
        if move:
            for src, dst, kind in reversed(items):
                if not os.path.lexists(dst):
                    continue
                try:
                    if kind == "dir":
                        os.rmdir(src)
                    else:
                        os.unlink(src)
                except OSError:
                    pass
        self.emit_progress("Fertig", "", 100, True)

    # ------------------------------------------------------------ delete
    def do_delete(self, sources, trash=True):
        if trash:
            self.total = len(sources)
            for i, src in enumerate(sources):
                self.check()
                self.done_bytes = i
                self.emit_progress("In den Papierkorb: " + src, os.path.basename(src), 0, True)
                while True:
                    try:
                        move_to_trash(src)
                        break
                    except Exception as ex:  # noqa: BLE001
                        if self.handle_error("Papierkorb: " + src, ex) != "retry":
                            break
            return
        items = []
        for src in sources:
            if os.path.isdir(src) and not os.path.islink(src):
                for root, dirs, files in os.walk(src, topdown=False):
                    self.check()
                    for f in files:
                        items.append((os.path.join(root, f), False))
                    for d in dirs:
                        p = os.path.join(root, d)
                        items.append((p, not os.path.islink(p)))
                items.append((src, True))
            else:
                items.append((src, False))
        self.total = len(items)
        for i, (p, is_dir) in enumerate(items):
            self.check()
            self.done_bytes = i
            self.emit_progress("Lösche " + p, os.path.basename(p), 100)
            while True:
                try:
                    if is_dir:
                        os.rmdir(p)
                    else:
                        os.unlink(p)
                    break
                except FileNotFoundError:
                    break
                except Exception as ex:  # noqa: BLE001
                    if self.handle_error("Löschen: " + p, ex) != "retry":
                        break

    # ------------------------------------------------------------ ftp
    def _ftp(self, fs):
        try:
            return fs.new_connection()
        except Exception as ex:  # noqa: BLE001
            raise RuntimeError("FTP-Verbindung fehlgeschlagen: %s" % ex) from ex

    @staticmethod
    def _ftp_quit(ftp):
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            pass

    def _ftp_progress(self, line, name):
        def cb(n):
            self.check()
            self.done_bytes += n
            self.emit_progress(line, name, 0)
        return cb

    def do_ftp_download(self, fs, items, dest_dir, new_name=None):
        ftp = self._ftp(fs)
        try:
            plan = []  # (remote, local, is_dir, size)
            for remote, is_dir in items:
                self.check()
                local = os.path.join(dest_dir, new_name or remote.rstrip("/").rsplit("/", 1)[-1])
                plan.append((remote, local, is_dir, 0))
                if is_dir:
                    for rp, e in fs.walk(ftp, remote):
                        self.check()
                        plan.append((rp, os.path.join(local, rp[len(remote):].lstrip("/")),
                                     e.is_dir and not e.is_link, e.size))
                else:
                    try:
                        plan[-1] = (remote, local, False, ftp.size(remote) or 0)
                    except Exception:  # noqa: BLE001
                        pass
            self.total = sum(x[3] for x in plan) or 1
            os.makedirs(dest_dir, exist_ok=True)
            for remote, local, is_dir, _size in plan:
                self.check()
                line = "Lade herunter %s\n→ %s" % (fs.display(remote), local)
                while True:
                    try:
                        if is_dir:
                            os.makedirs(local, exist_ok=True)
                        else:
                            if os.path.lexists(local):
                                local = self.resolve_conflict(remote, local)
                                if local is None:
                                    break
                            fs.download(ftp, remote, local, self._ftp_progress(line, os.path.basename(local)))
                        break
                    except (Cancelled, RuntimeError):
                        raise
                    except Exception as ex:  # noqa: BLE001
                        if self.handle_error("Herunterladen: " + remote, ex) != "retry":
                            break
        finally:
            self._ftp_quit(ftp)

    def do_ftp_upload(self, fs, sources, dest_inner):
        ftp = self._ftp(fs)
        try:
            plan = []  # (local, remote, is_dir, size)
            for src in sources:
                self.check()
                remote = fs.join(dest_inner, os.path.basename(src.rstrip("/")))
                if os.path.isdir(src) and not os.path.islink(src):
                    plan.append((src, remote, True, 0))
                    for root, dirs, files in os.walk(src):
                        rel = os.path.relpath(root, src)
                        rbase = remote if rel == "." else fs.join(remote, rel)
                        for d in sorted(dirs):
                            plan.append((os.path.join(root, d), fs.join(rbase, d), True, 0))
                        for f in sorted(files):
                            lp = os.path.join(root, f)
                            try:
                                plan.append((lp, fs.join(rbase, f), False, os.path.getsize(lp)))
                            except OSError:
                                pass
                else:
                    plan.append((src, remote, False, os.path.getsize(src)))
            self.total = sum(x[3] for x in plan) or 1
            existing = {}
            for local, remote, is_dir, _size in plan:
                self.check()
                line = "Lade hoch %s\n→ %s" % (local, fs.display(remote))
                while True:
                    try:
                        if is_dir:
                            fs.mkdir(remote, ftp=ftp)
                        else:
                            parent = fs.parent(remote)
                            if parent not in existing:
                                existing[parent] = {e.name for e in fs.list(parent, ftp=ftp)}
                            name = remote.rsplit("/", 1)[-1]
                            if name in existing[parent] and self.overwrite_policy != "all":
                                ans = self.overwrite_policy or self.request(kind="overwrite", src=local,
                                                                            dst=fs.display(remote))
                                if ans == "all":
                                    self.overwrite_policy = "all"
                                elif ans == "skip_all":
                                    self.overwrite_policy = "skip_all"
                                    break
                                elif ans in (None, "cancel"):
                                    raise Cancelled()
                                elif ans != "overwrite":
                                    break
                            fs.upload(ftp, local, remote, self._ftp_progress(line, name))
                        break
                    except Cancelled:
                        raise
                    except Exception as ex:  # noqa: BLE001
                        if self.handle_error("Hochladen: " + local, ex) != "retry":
                            break
        finally:
            self._ftp_quit(ftp)

    def do_ftp_delete(self, fs, items):
        ftp = self._ftp(fs)
        try:
            for remote, is_dir in items:
                self.check()
                self.emit_progress("Lösche %s" % fs.display(remote), remote.rsplit("/", 1)[-1], 0, True)
                while True:
                    try:
                        fs.delete(ftp, remote, is_dir)
                        break
                    except Exception as ex:  # noqa: BLE001
                        if self.handle_error("Löschen: " + remote, ex) != "retry":
                            break
        finally:
            self._ftp_quit(ftp)

    # ------------------------------------------------------------ archives
    def do_extract(self, archive, inner_paths, base_inner, dest_dir):
        fs = vfs.get_archive_fs(archive)
        self.total = fs.total_size(inner_paths) or 1
        state = {"name": ""}

        def prog(name, n):
            self.check()
            if name is not None:
                state["name"] = name
            self.done_bytes += n
            self.emit_progress("Entpacke aus %s\n→ %s" % (os.path.basename(archive), dest_dir), state["name"], 0)

        os.makedirs(dest_dir, exist_ok=True)
        fs.extract(inner_paths, base_inner, dest_dir, prog, lambda: self.cancel)

    def do_unpack(self, archives, dest_dir, separate=False, mask=None):
        self.total = 0
        for a in archives:
            try:
                self.total += os.path.getsize(a)
            except OSError:
                pass
        for a in archives:
            self.check()
            d = dest_dir
            if separate:
                n = os.path.basename(a)
                for ext in sorted(vfs.ARCHIVE_EXT, key=len, reverse=True):
                    if n.lower().endswith(ext):
                        n = n[:-len(ext)]
                        break
                d = os.path.join(dest_dir, n)
            os.makedirs(d, exist_ok=True)
            try:
                fs = vfs.get_archive_fs(a)
                top = [e.path for e in fs.list("")]
                if mask and mask.strip() not in ("*", "*.*"):
                    m = Mask(mask)
                    top = [p for p in fs.members_under("") if p and m.match(os.path.basename(p))]
                    sub_total = 0
                else:
                    sub_total = 0
                self.emit_progress("Entpacke %s\n→ %s" % (a, d), os.path.basename(a), 0, True)
                fs.extract(top, "", d, lambda name, n: (self.check(), self.emit_progress(
                    "Entpacke %s\n→ %s" % (a, d), name or os.path.basename(a), 0)), lambda: self.cancel)
                self.done_bytes += os.path.getsize(a) + sub_total
            except Cancelled:
                raise
            except Exception as ex:  # noqa: BLE001
                if self.handle_error("Entpacken: " + a, ex) == "retry":
                    continue

    def do_pack(self, sources, base_dir, archive, fmt, move=False, level=6, password=None):
        files = []
        self.total = 0
        for s in sources:
            if os.path.isdir(s) and not os.path.islink(s):
                files.append(s)
                for root, dirs, fl in os.walk(s):
                    for d in dirs:
                        files.append(os.path.join(root, d))
                    for f in fl:
                        p = os.path.join(root, f)
                        files.append(p)
                        try:
                            self.total += os.lstat(p).st_size
                        except OSError:
                            pass
            else:
                files.append(s)
                try:
                    self.total += os.lstat(s).st_size
                except OSError:
                    pass
        line = "Packe nach " + archive
        if fmt == "zip":
            comp = zipfile.ZIP_DEFLATED if level > 0 else zipfile.ZIP_STORED
            mode = "a" if os.path.exists(archive) and zipfile.is_zipfile(archive) else "w"
            try:
                zf = zipfile.ZipFile(archive, mode, comp, compresslevel=level if level > 0 else None)
            except TypeError:
                zf = zipfile.ZipFile(archive, mode, comp)
            with zf:
                for p in files:
                    self.check()
                    arc = os.path.relpath(p, base_dir)
                    self.emit_progress(line, arc, 0)
                    if os.path.isdir(p) and not os.path.islink(p):
                        zf.write(p, arc + "/")
                    else:
                        zf.write(p, arc)
                        try:
                            self.done_bytes += os.lstat(p).st_size
                        except OSError:
                            pass
        elif fmt.startswith("tar"):
            m = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}[fmt]
            with tarfile.open(archive, m) as tf:
                for s in sources:
                    def filt(ti, _s=s):
                        self.check()
                        self.emit_progress(line, ti.name, 0)
                        self.done_bytes += ti.size
                        return ti
                    tf.add(s, os.path.relpath(s, base_dir), recursive=True, filter=filt)
        elif fmt == "7z":
            exe = vfs.sevenzip()
            if not exe:
                raise Exception("7z ist nicht installiert (Paket p7zip-full bzw. 7zip)")
            self.emit_progress(line, "", 0, True)
            cmd = [exe, "a", "-mx=%d" % min(9, max(0, level)), archive]
            if password:
                cmd.append("-p" + password)
            cmd += ["--"] + [os.path.relpath(s, base_dir) for s in sources]
            r = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True, errors="replace")
            if r.returncode != 0:
                raise Exception(r.stderr.strip() or r.stdout.strip()[-400:])
            self.done_bytes = self.total
        if move:
            self.do_delete(sources, trash=False)
        self.emit_progress("Fertig", "", 100, True)


class OverwriteDialog(QtWidgets.QDialog):
    def __init__(self, src, dst, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datei existiert bereits")
        self.result_value = "cancel"
        lay = QtWidgets.QVBoxLayout(self)

        def info(p):
            try:
                st = os.stat(p)
                return "%s Bytes, %s" % (format_size(st.st_size, "bytes"), format_time(st.st_mtime))
            except OSError:
                return "?"

        lay.addWidget(QtWidgets.QLabel("<b>Überschreiben:</b> %s<br>%s<br><br><b>mit:</b> %s<br>%s" % (
            dst.replace("&", "&amp;"), info(dst), src.replace("&", "&amp;"), info(src))))
        grid = QtWidgets.QGridLayout()
        buttons = [("Überschreiben", "overwrite"), ("Alle überschreiben", "all"),
                   ("Überspringen", "skip"), ("Alle überspringen", "skip_all"),
                   ("Ältere überschreiben", "older_all"), ("Umbenennen…", "rename_ask"),
                   ("Automatisch umbenennen", "rename_all"), ("Abbrechen", "cancel")]
        for i, (label, val) in enumerate(buttons):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _c=False, v=val: self._choose(v))
            grid.addWidget(b, i // 2, i % 2)
            if i == 0:
                b.setDefault(True)
        lay.addLayout(grid)
        self.dst = dst

    def _choose(self, v):
        if v == "rename_ask":
            name, ok = QtWidgets.QInputDialog.getText(self, "Umbenennen", "Neuer Name:",
                                                      text=os.path.basename(self.dst))
            if not ok or not name:
                return
            v = ("newname", name)
        self.result_value = v
        self.accept()


class ProgressDialog(QtWidgets.QDialog):
    finished_op = Signal(bool, str)

    def __init__(self, title, worker, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.worker = worker
        lay = QtWidgets.QVBoxLayout(self)
        self.line = QtWidgets.QLabel("Vorbereitung…")
        self.line.setWordWrap(True)
        self.line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.line)
        self.file_bar = QtWidgets.QProgressBar()
        self.total_bar = QtWidgets.QProgressBar()
        lay.addWidget(self.file_bar)
        lay.addWidget(self.total_bar)
        self.speed = QtWidgets.QLabel("")
        lay.addWidget(self.speed)
        row = QtWidgets.QHBoxLayout()
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.bg_btn = QtWidgets.QPushButton("Hintergrund")
        self.cancel_btn = QtWidgets.QPushButton("Abbrechen")
        row.addStretch(1)
        for b in (self.pause_btn, self.bg_btn, self.cancel_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.cancel_btn.clicked.connect(self.do_cancel)
        self.bg_btn.clicked.connect(self.showMinimized)
        self.started = time.monotonic()
        worker.progress.connect(self.on_progress)
        worker.ask.connect(self.on_ask, Qt.ConnectionType.BlockingQueuedConnection)
        worker.done.connect(self.on_done)
        self._show_timer = QtCore.QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self.show)
        self._show_timer.start(300)  # only show for operations lasting a bit

    def toggle_pause(self):
        if self.worker.paused.is_set():
            self.worker.paused.clear()
            self.pause_btn.setText("Fortsetzen")
        else:
            self.worker.paused.set()
            self.pause_btn.setText("Pause")

    def do_cancel(self):
        self.worker.cancel = True
        self.worker.paused.set()

    def reject(self):
        self.do_cancel()

    def on_progress(self, line, name, fpct, tpct):
        self.line.setText(line)
        self.file_bar.setValue(fpct)
        self.total_bar.setValue(tpct)
        el = time.monotonic() - self.started
        if el > 0.5 and self.worker.op in ("copy", "extract", "pack", "unpack", "ftp_download", "ftp_upload"):
            spd = self.worker.done_bytes / el
            self.speed.setText("%s/s  –  %s von %s" % (human_size(int(spd)), human_size(self.worker.done_bytes),
                                                          human_size(self.worker.total)))

    def on_ask(self, req):
        self._show_timer.stop()
        self.show()
        if req["kind"] == "overwrite":
            dlg = OverwriteDialog(req["src"], req["dst"], self)
            qexec(dlg)
            self.worker.answer = dlg.result_value
        elif req["kind"] == "error":
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            box.setWindowTitle("Fehler")
            box.setText(req["text"])
            retry = box.addButton("Wiederholen", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            skip = box.addButton("Überspringen", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            skip_all = box.addButton("Alle überspringen", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Abbrechen", QtWidgets.QMessageBox.ButtonRole.RejectRole)
            qexec(box)
            c = box.clickedButton()
            self.worker.answer = {retry: "retry", skip: "skip", skip_all: "skip_all"}.get(c, "cancel")

    def on_done(self, ok, msg):
        self._show_timer.stop()
        self.finished_op.emit(ok, msg)
        self.hide()
        if msg and msg != "Abgebrochen":
            QtWidgets.QMessageBox.warning(self.parent(), self.windowTitle(), msg)
        self.deleteLater()


_running = []


def start(op, title, parent, on_finish=None, **kw):
    worker = FileOpWorker(op, None, **kw)
    dlg = ProgressDialog(title, worker, parent)

    def fin(ok, msg):
        if on_finish:
            on_finish(ok, msg)

    def cleanup():
        if worker in _running:
            _running.remove(worker)

    dlg.finished_op.connect(fin)
    worker.finished.connect(cleanup)
    _running.append(worker)
    worker.start()
    return worker
