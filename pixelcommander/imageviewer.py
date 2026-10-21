"""Fast image viewer: zoom, pan, rotate, slideshow through the images of a folder, neighbours preloaded."""
import os

from .qt import QtCore, QtGui, QtWidgets, Qt, QShortcut, Signal
from .utils import human_size

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico", "tif", "tiff", "xpm", "pbm", "pgm", "ppm",
             "avif", "heic", "jxl", "tga"}


def is_image(path):
    return os.path.splitext(path)[1][1:].lower() in IMAGE_EXT


class _Loader(QtCore.QRunnable):
    """Decode an image in a worker thread."""

    class Sig(QtCore.QObject):
        done = Signal(str, QtGui.QImage)

    def __init__(self, path, sig):
        super().__init__()
        self.path = path
        self.sig = sig

    def run(self):
        reader = QtGui.QImageReader(self.path)
        reader.setAutoTransform(True)  # honour EXIF orientation
        self.sig.done.emit(self.path, reader.read())


class Canvas(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm = None
        self.movie = None
        self.scale = 1.0
        self.fit = True
        self.offset = QtCore.QPointF(0, 0)
        self._drag = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_pixmap(self, pm):
        self.pm = pm
        self.fit = True
        self.offset = QtCore.QPointF(0, 0)
        self.update()

    def eff_scale(self):
        if not self.pm or self.pm.isNull():
            return 1.0
        if self.fit:
            s = min(self.width() / self.pm.width(), self.height() / self.pm.height())
            return min(s, 1.0)  # never blow small images up when fitting
        return self.scale

    def zoom(self, factor, anchor=None):
        if not self.pm:
            return
        old = self.eff_scale()
        new = max(0.02, min(old * factor, 40.0))
        anchor = anchor or QtCore.QPointF(self.width() / 2, self.height() / 2)
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2) + self.offset
        self.offset += (centre - anchor) * (new / old - 1)
        self.fit = False
        self.scale = new
        self.update()

    def actual_size(self):
        self.fit = False
        self.scale = 1.0
        self.offset = QtCore.QPointF(0, 0)
        self.update()

    def toggle_fit(self):
        self.fit = not self.fit
        if not self.fit:
            self.scale = 1.0
        self.offset = QtCore.QPointF(0, 0)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#1b1b1d"))
        if not self.pm or self.pm.isNull():
            return
        s = self.eff_scale()
        w, h = self.pm.width() * s, self.pm.height() * s
        x = (self.width() - w) / 2 + self.offset.x()
        y = (self.height() - h) / 2 + self.offset.y()
        target = QtCore.QRectF(x, y, w, h)
        if self.pm.hasAlphaChannel():  # checkerboard behind transparent images
            p.save()
            p.setClipRect(target)
            c = 10
            for iy in range(int(y // c), int((y + h) // c) + 1):
                for ix in range(int(x // c), int((x + w) // c) + 1):
                    p.fillRect(ix * c, iy * c, c, c, QtGui.QColor("#3a3a3e" if (ix + iy) % 2 else "#2c2c30"))
            p.restore()
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, s < 4)
        p.drawPixmap(target, self.pm, QtCore.QRectF(self.pm.rect()))

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier or not self.window().wheel_navigates:
            self.zoom(1.15 if d > 0 else 1 / 1.15, e.position())
        else:
            self.window().step(-1 if d > 0 else 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.offset += e.position() - self._drag
            self._drag = e.position()
            self.update()

    def mouseReleaseEvent(self, _e):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, _e):
        self.window().toggle_fullscreen()


class ImageViewer(QtWidgets.QMainWindow):
    _open = []  # keep references so windows are not garbage collected

    def __init__(self, path, siblings=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.files = [f for f in (siblings or []) if is_image(f)] or [path]
        if path not in self.files:
            self.files.insert(0, path)
        self.index = self.files.index(path)
        self.cache = {}  # path -> QImage, only current and neighbours
        self.wheel_navigates = True
        self.rotation = 0
        self.pool = QtCore.QThreadPool.globalInstance()
        self.sig = _Loader.Sig()
        self.sig.done.connect(self._loaded)

        self.canvas = Canvas(self)
        self.setCentralWidget(self.canvas)
        self.status = QtWidgets.QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.slideshow = QtCore.QTimer(self, interval=3000)
        self.slideshow.timeout.connect(lambda: self.step(1, wrap=True))

        keys = [
            (("Right", "Space", "PgDown", "N"), lambda: self.step(1)),
            (("Left", "Backspace", "PgUp", "P"), lambda: self.step(-1)),
            (("Home",), lambda: self.go(0)), (("End",), lambda: self.go(len(self.files) - 1)),
            (("+", "=", "Ctrl++"), lambda: self.canvas.zoom(1.25)), (("-", "Ctrl+-"), lambda: self.canvas.zoom(0.8)),
            (("0", "Ctrl+0"), self.canvas.toggle_fit), (("1",), self.canvas.actual_size),
            (("R",), lambda: self.rotate(90)), (("L", "Shift+R"), lambda: self.rotate(-90)),
            (("F", "F11", "Return"), self.toggle_fullscreen), (("S",), self.toggle_slideshow),
            (("W",), self.toggle_wheel), (("Delete",), self.trash_current),
            (("Escape", "Q", "F3"), self.close_or_leave_fullscreen),
        ]
        for seqs, fn in keys:
            for s in seqs:
                QShortcut(QtGui.QKeySequence(s), self, activated=fn)

        self.resize(1100, 750)
        ImageViewer._open.append(self)
        self.destroyed.connect(lambda *_: ImageViewer._open.remove(self) if self in ImageViewer._open else None)
        self.go(self.index)

    # ------------------------------------------------------------ loading
    def _request(self, path):
        if path in self.cache:
            return
        self.cache[path] = None  # pending
        self.pool.start(_Loader(path, self.sig))

    def _loaded(self, path, img):
        if path not in self.cache:
            return
        self.cache[path] = img
        if path == self.files[self.index]:
            self._show(img)

    def go(self, i):
        if not self.files:
            return
        self.index = max(0, min(i, len(self.files) - 1))
        self.rotation = 0
        cur = self.files[self.index]
        keep = {self.files[j] for j in range(self.index - 1, self.index + 2) if 0 <= j < len(self.files)}
        for k in list(self.cache):
            if k not in keep:
                del self.cache[k]
        img = self.cache.get(cur)
        if img is not None:
            self._show(img)
        else:
            self.status.setText("Lade %s …" % os.path.basename(cur))
            self._request(cur)
        for k in keep:
            self._request(k)

    def step(self, d, wrap=False):
        n = self.index + d
        if wrap:
            n %= len(self.files)
        if 0 <= n < len(self.files):
            self.go(n)

    def _show(self, img):
        path = self.files[self.index]
        if img.isNull():
            self.canvas.set_pixmap(None)
            self.status.setText("Kann nicht angezeigt werden: %s" % path)
            return
        if self.rotation:
            img = img.transformed(QtGui.QTransform().rotate(self.rotation), Qt.TransformationMode.SmoothTransformation)
        self.canvas.set_pixmap(QtGui.QPixmap.fromImage(img))
        self.setWindowTitle("%s – Bildbetrachter" % os.path.basename(path))
        self._update_status()

    def _update_status(self):
        path = self.files[self.index]
        pm = self.canvas.pm
        try:
            size = human_size(os.path.getsize(path))
        except OSError:
            size = "?"
        zoom = "Einpassen" if self.canvas.fit else "%d %%" % round(self.canvas.eff_scale() * 100)
        extra = "  ·  Diashow" if self.slideshow.isActive() else ""
        self.status.setText("%d / %d   %s   %d × %d   %s   %s%s" % (
            self.index + 1, len(self.files), os.path.basename(path),
            pm.width() if pm else 0, pm.height() if pm else 0, size, zoom, extra))

    # ------------------------------------------------------------ actions
    def rotate(self, deg):
        self.rotation = (self.rotation + deg) % 360
        img = self.cache.get(self.files[self.index])
        if img is not None:
            self._show(img)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()
        else:
            self.statusBar().hide()
            self.showFullScreen()

    def close_or_leave_fullscreen(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        else:
            self.close()

    def toggle_slideshow(self):
        if self.slideshow.isActive():
            self.slideshow.stop()
        else:
            self.slideshow.start()
        self._update_status()

    def toggle_wheel(self):
        self.wheel_navigates = not self.wheel_navigates
        self.statusBar().showMessage("Mausrad: " + ("Blättern (Strg = Zoom)" if self.wheel_navigates else "Zoom"), 2000)

    def trash_current(self):
        from .utils import move_to_trash
        path = self.files[self.index]
        if QtWidgets.QMessageBox.question(self, "Löschen", "In den Papierkorb verschieben?\n%s" % path) != \
                QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            move_to_trash(path)
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Löschen", str(ex))
            return
        self.cache.pop(path, None)
        del self.files[self.index]
        if not self.files:
            self.close()
            return
        self.go(min(self.index, len(self.files) - 1))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.canvas.pm:
            self._update_status()
