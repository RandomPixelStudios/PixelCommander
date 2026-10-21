"""Icon chooser for buttons: lists icons of the installed icon themes, or any image file."""
import os

from .qt import QtCore, QtGui, QtWidgets, Qt, qexec

ICON_EXT = (".svg", ".svgz", ".png", ".xpm")
_cache = None


def load_icon(spec):
    """Icon from a theme name or an image file path (empty icon if not found)."""
    if not spec:
        return QtGui.QIcon()
    if os.path.isabs(spec) or spec.startswith("~"):
        p = os.path.expanduser(spec)
        return QtGui.QIcon(p) if os.path.isfile(p) else QtGui.QIcon()
    from .winicons import win_icon
    win = win_icon(spec)
    if win is not None:
        return win
    ic = QtGui.QIcon.fromTheme(spec)
    if ic.isNull():
        path = icon_names().get(spec)
        if path:
            return QtGui.QIcon(path)
    return ic


def _theme_chain():
    names = []
    cur = QtGui.QIcon.themeName()
    fallback = QtGui.QIcon.fallbackThemeName() if hasattr(QtGui.QIcon, "fallbackThemeName") else ""
    todo = [t for t in (cur, fallback) if t]
    bases = _bases()
    while todo:
        t = todo.pop(0)
        if t in names:
            continue
        names.append(t)
        for b in bases:
            idx = os.path.join(b, t, "index.theme")
            if os.path.isfile(idx):
                try:
                    with open(idx, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            if line.startswith("Inherits="):
                                todo.extend(x.strip() for x in line[9:].split(",") if x.strip())
                except OSError:
                    pass
                break
    for t in ("hicolor", "Adwaita", "breeze", "Papirus", "oxygen", "gnome", "Tango", "elementary"):
        if t not in names:
            names.append(t)
    return names


def _bases():
    out = []
    for b in list(QtGui.QIcon.themeSearchPaths()) + [os.path.expanduser("~/.local/share/icons"),
                                                      os.path.expanduser("~/.icons"), "/usr/share/icons",
                                                      "/usr/local/share/icons"]:
        b = b.replace(":/icons", "")
        if b and os.path.isdir(b) and b not in out:
            out.append(b)
    return out


def icon_names():
    """{icon name: file path} of all installed theme icons (current theme first)."""
    global _cache
    if _cache is not None:
        return _cache
    res = {}
    for theme in _theme_chain():
        for base in _bases():
            root = os.path.join(base, theme)
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                # prefer scalable / bigger icons for the preview
                for f in files:
                    if f.endswith(ICON_EXT):
                        name = f.rsplit(".", 1)[0]
                        if name.endswith(".svg"):
                            name = name[:-4]
                        if name not in res:
                            res[name] = os.path.join(dirpath, f)
    pix = "/usr/share/pixmaps"
    if os.path.isdir(pix):
        for f in os.listdir(pix):
            if f.endswith(ICON_EXT):
                res.setdefault(f.rsplit(".", 1)[0], os.path.join(pix, f))
    _cache = res
    return res


class _IconModel(QtCore.QAbstractListModel):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items  # list of (name, path)
        self.icons = {}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        name, path = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return name
        if role == Qt.ItemDataRole.ToolTipRole:
            return "%s\n%s" % (name, path)
        if role == Qt.ItemDataRole.DecorationRole:
            ic = self.icons.get(name)
            if ic is None:
                ic = QtGui.QIcon.fromTheme(name)
                if ic.isNull():
                    ic = QtGui.QIcon(path)
                self.icons[name] = ic
            return ic
        if role == Qt.ItemDataRole.UserRole:
            return name
        return None


class IconPicker(QtWidgets.QDialog):
    def __init__(self, current="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Symbol auswählen")
        self.result_icon = current
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Symbol suchen, z.B. folder, edit, terminal, archive …")
        self.search.setClearButtonEnabled(True)
        self.symbolic = QtWidgets.QCheckBox("„-symbolic“-Varianten")
        row.addWidget(self.search, 1)
        row.addWidget(self.symbolic)
        lay.addLayout(row)
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            names = icon_names()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.all_items = sorted(names.items(), key=lambda kv: kv[0].lower())
        self.model = _IconModel([], self)
        self.proxy = QtCore.QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.view = QtWidgets.QListView()
        self.view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.view.setIconSize(QtCore.QSize(32, 32))
        self.view.setGridSize(QtCore.QSize(96, 72))
        self.view.setUniformItemSizes(True)
        self.view.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.view.setMovement(QtWidgets.QListView.Movement.Static)
        self.view.setLayoutMode(QtWidgets.QListView.LayoutMode.Batched)
        self.view.setBatchSize(200)
        self.view.setWordWrap(True)
        self.view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.view.setModel(self.proxy)
        self.view.doubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.view, 1)
        self.info = QtWidgets.QLabel()
        lay.addWidget(self.info)
        bottom = QtWidgets.QHBoxLayout()
        file_btn = QtWidgets.QPushButton("Bilddatei wählen…")
        file_btn.clicked.connect(self.pick_file)
        none_btn = QtWidgets.QPushButton("Kein Symbol (Textsymbol)")
        none_btn.clicked.connect(self.choose_none)
        bottom.addWidget(file_btn)
        bottom.addWidget(none_btn)
        bottom.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom.addWidget(bb)
        lay.addLayout(bottom)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._update_info)
        self.symbolic.toggled.connect(self._fill)
        self._fill()
        self.resize(760, 560)
        if current and not os.path.isabs(current):
            self.search.setText(current)

    def _fill(self):
        sym = self.symbolic.isChecked()
        items = [kv for kv in self.all_items if sym or not kv[0].endswith("-symbolic")]
        self.model.beginResetModel()
        self.model.items = items
        self.model.endResetModel()
        self._update_info()

    def _update_info(self, *_a):
        self.info.setText("%d Symbole (Themes: %s)" % (self.proxy.rowCount(), ", ".join(_theme_chain()[:4])))
        if self.proxy.rowCount():
            t = self.search.text().strip().lower()
            best = 0
            for r in range(self.proxy.rowCount()):
                if self.proxy.data(self.proxy.index(r, 0)).lower() == t:
                    best = r
                    break
            self.view.setCurrentIndex(self.proxy.index(best, 0))
            self.view.scrollTo(self.proxy.index(best, 0))

    def pick_file(self):
        p, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Bilddatei", "/usr/share/icons",
                                                      "Bilder (*.png *.svg *.svgz *.xpm *.ico *.jpg)")
        if p:
            self.result_icon = p
            super().accept()

    def choose_none(self):
        self.result_icon = ""
        super().accept()

    def accept(self):
        idx = self.view.currentIndex()
        if idx.isValid():
            self.result_icon = self.proxy.data(idx, Qt.ItemDataRole.UserRole)
        super().accept()


def pick_icon(current, parent):
    """Returns the chosen icon spec or None if cancelled."""
    dlg = IconPicker(current, parent)
    if qexec(dlg):
        return dlg.result_icon
    return None
