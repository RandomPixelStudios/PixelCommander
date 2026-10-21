"""Update check against the GitHub releases, shown as a button in the top right corner of the menu bar."""
import json
import os
import re
import shutil
import tempfile
import urllib.request

from . import __version__
from .qt import QtCore, QtGui, QtWidgets, Signal, qexec

REPO = "RandomPixelStudios/PixelCommander"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES = "https://github.com/%s/releases" % REPO


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "PixelCommander/" + __version__,
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


class CheckThread(QtCore.QThread):
    done = Signal(object, str)  # release dict or None, error message

    def run(self):
        try:
            with _get(API) as r:
                data = json.loads(r.read().decode("utf-8"))
            deb = next((a["browser_download_url"] for a in data.get("assets", [])
                        if a.get("name", "").endswith(".deb")), None)
            self.done.emit({"version": data.get("tag_name", "").lstrip("vV"), "url": data.get("html_url", RELEASES),
                            "notes": data.get("body") or "", "deb": deb}, "")
        except Exception as ex:  # noqa: BLE001  (offline, rate limit, bad JSON)
            self.done.emit(None, str(ex))


class DownloadThread(QtCore.QThread):
    progress = Signal(int)
    done = Signal(str, str)  # path, error

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            d = tempfile.mkdtemp(prefix="pixelcommander-update-")
            path = os.path.join(d, self.url.rsplit("/", 1)[-1])
            with _get(self.url, 60) as r, open(path, "wb") as fh:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit(int(got * 100 / total))
            self.done.emit(path, "")
        except Exception as ex:  # noqa: BLE001
            self.done.emit("", str(ex))


class UpdateButton(QtWidgets.QToolButton):
    """Corner widget: shows the state of the update check; click = details / check again."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAutoRaise(True)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.release = None
        self.thread = None
        self.manual = False
        self.clicked.connect(self.on_click)
        self._state("idle")

    def _state(self, state, text=""):
        self.state = state
        icons = {"new": "software-update-available", "ok": "emblem-ok-symbolic", "error": "dialog-warning"}
        self.setIcon(QtGui.QIcon.fromTheme(icons.get(state, "view-refresh")))
        self.setText({"idle": "v%s" % __version__, "checking": "Suche Updates…", "ok": "v%s ✓" % __version__,
                      "error": "v%s" % __version__, "new": "Update: v%s" % text}.get(state, ""))
        self.setStyleSheet("QToolButton { color: white; background: #1f9a4e; border-radius: 4px; padding: 1px 8px;"
                           " font-weight: bold; }" if state == "new" else "")
        self.setToolTip({"idle": "Nach Updates suchen", "checking": "Verbindung zu GitHub…",
                         "ok": "PixelCommander ist aktuell – klicken zum erneut Prüfen",
                         "error": "Update-Prüfung fehlgeschlagen: %s\nKlicken zum erneut Prüfen" % text,
                         "new": "Neue Version verfügbar – klicken für Details"}.get(state, ""))
        # QMenuBar only lays out its corner widget on resize
        self.adjustSize()
        mb = self.parentWidget()
        if isinstance(mb, QtWidgets.QMenuBar):
            QtWidgets.QApplication.sendEvent(mb, QtGui.QResizeEvent(mb.size(), mb.size()))

    def check(self, manual=False):
        if self.thread is not None and self.thread.isRunning():
            return
        self.manual = manual
        self._state("checking")
        self.thread = CheckThread(self)
        self.thread.done.connect(self._checked)
        self.thread.start()

    def _checked(self, rel, err):
        if rel is None:
            self._state("error", err)
            if self.manual:
                QtWidgets.QMessageBox.warning(self.window(), "Update", "Update-Prüfung fehlgeschlagen:\n%s" % err)
            return
        if parse_version(rel["version"]) > parse_version(__version__):
            self.release = rel
            self._state("new", rel["version"])
            if self.manual:
                self.show_dialog()
        else:
            self._state("ok")
            if self.manual:
                QtWidgets.QMessageBox.information(self.window(), "Update",
                                                  "PixelCommander %s ist die neueste Version." % __version__)

    def on_click(self):
        if self.state == "new":
            self.show_dialog()
        else:
            self.check(manual=True)

    # ------------------------------------------------------------ update dialog
    def show_dialog(self):
        rel = self.release
        box = QtWidgets.QMessageBox(self.window())
        box.setWindowTitle("Update verfügbar")
        box.setIcon(QtWidgets.QMessageBox.Icon.Information)
        box.setText("<b>PixelCommander %s</b> ist verfügbar (installiert: %s)." % (rel["version"], __version__))
        box.setInformativeText(rel["notes"][:1500])
        can_install = bool(rel["deb"]) and shutil.which("pkexec") and shutil.which("apt")
        inst = box.addButton("Herunterladen && installieren", QtWidgets.QMessageBox.ButtonRole.AcceptRole) \
            if can_install else None
        page = box.addButton("Release-Seite öffnen", QtWidgets.QMessageBox.ButtonRole.ActionRole)
        box.addButton("Später", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        qexec(box)
        if inst is not None and box.clickedButton() is inst:
            self.download(rel["deb"])
        elif box.clickedButton() is page:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(rel["url"]))

    def download(self, url):
        dlg = QtWidgets.QProgressDialog("Lade Update herunter…", "Abbrechen", 0, 100, self.window())
        dlg.setWindowTitle("Update")
        dlg.setMinimumDuration(0)
        t = DownloadThread(url, self)
        t.progress.connect(dlg.setValue)

        def finished(path, err):
            dlg.close()
            if dlg.wasCanceled():
                return
            if err:
                QtWidgets.QMessageBox.warning(self.window(), "Update", "Download fehlgeschlagen:\n%s" % err)
                return
            self.install(path)
        t.done.connect(finished)
        t.start()
        self._dl = t

    def install(self, path):
        proc = QtCore.QProcess(self)
        self._proc = proc

        def finished(code, _status):
            if code == 0:
                QtWidgets.QMessageBox.information(self.window(), "Update",
                                                  "Update installiert. Bitte PixelCommander neu starten.")
                self._state("ok")
            else:
                out = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                QtWidgets.QMessageBox.warning(self.window(), "Update",
                                              "Installation fehlgeschlagen (Code %d):\n%s" % (code, out[-1500:]))
        proc.finished.connect(finished)
        proc.start("pkexec", ["apt", "install", "-y", path])
