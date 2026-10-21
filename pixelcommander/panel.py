"""File panel widgets: views, single panel, tabbed panel with drive bar."""
import os

from .config import config
from .model import FileListModel, COL_NAME, COL_EXT, COL_SIZE, COL_DATE, COL_ATTR
from .qt import (QtCore, QtGui, QtWidgets, Qt, Signal, qexec, CTRL, SHIFT, ALT, KEYPAD, global_pos, event_pos,
                 QActionGroup)
from .utils import Mask, disk_free, format_size, human_size, icons, list_drives, theme_icon
from . import vfs

MODE_FULL, MODE_BRIEF, MODE_THUMBS, MODE_TREE = "full", "brief", "thumbs", "tree"


class _ViewMixin:
    """Shared keyboard/mouse behaviour for the panel views."""
    panel = None

    def setup_common(self, panel):
        self.panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._drag_mark_state = None
        self._last_row = None

    def event(self, ev):
        if ev.type() == QtCore.QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) \
                and not ev.modifiers() & CTRL and self.panel is not None:
            self.panel.main.cmd_SwitchPanel()
            return True
        if ev.type() == QtCore.QEvent.Type.ShortcutOverride and self.panel is not None \
                and self.panel.is_quicksearch_key(ev):
            ev.accept()  # Alt+letter goes to the quick search, not to menu mnemonics
            return True
        return super().event(ev)

    def keyPressEvent(self, event):
        if self.state() == QtWidgets.QAbstractItemView.State.EditingState:
            return super().keyPressEvent(event)
        if self.panel.handle_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        self.panel.activate()
        idx = self.indexAt(event_pos(event))
        btn = event.button()
        mods = event.modifiers()
        if btn == Qt.MouseButton.RightButton and config.get("mark_with_right_mouse"):
            if idx.isValid():
                self.panel.model.toggle_mark(idx.row())
                self._drag_mark_state = self.panel.model.entry(idx.row()).name in self.panel.model.marked
                self._last_row = idx.row()
            return
        if btn == Qt.MouseButton.LeftButton and idx.isValid():
            if mods & CTRL:
                self.panel.model.toggle_mark(idx.row())
                self.setCurrentIndex(self.panel.model.index(idx.row(), 0))
                return
            if mods & SHIFT:
                cur = self.currentIndex().row()
                if cur < 0:
                    cur = 0
                a, b = sorted((cur, idx.row()))
                for r in range(a, b + 1):
                    self.panel.model.toggle_mark(r, True)
                self.setCurrentIndex(self.panel.model.index(idx.row(), 0))
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_mark_state is not None and event.buttons() & Qt.MouseButton.RightButton:
            idx = self.indexAt(event_pos(event))
            if idx.isValid() and idx.row() != self._last_row:
                self.panel.model.toggle_mark(idx.row(), self._drag_mark_state)
                self._last_row = idx.row()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_mark_state is not None and event.button() == Qt.MouseButton.RightButton:
            self._drag_mark_state = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        idx = self.indexAt(event_pos(event))
        if idx.isValid() and event.button() == Qt.MouseButton.LeftButton:
            self.panel.open_current()
            return
        if not idx.isValid() and event.button() == Qt.MouseButton.LeftButton and config.get("dblclick_up", True):
            self.panel.go_up()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if config.get("mark_with_right_mouse"):
            return
        idx = self.indexAt(event.pos())
        if idx.isValid():
            self.setCurrentIndex(self.panel.model.index(idx.row(), 0))
        self.panel.main.show_context_menu(self.panel, event.globalPos(), background=not idx.isValid())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        md = event.mimeData()
        if not md.hasUrls():
            return
        idx = self.indexAt(event_pos(event))
        target = None
        if idx.isValid():
            e = self.panel.model.entry(idx.row())
            if e and e.is_dir and self.panel.fs.kind == "local":
                target = self.panel.fs.parent(self.panel.inner) if e.is_up else e.path
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        mods = event.modifiers()
        if mods & SHIFT:
            action = "move"
        elif mods & CTRL and mods & SHIFT or mods & ALT:
            action = "link"
        else:
            action = "ask" if event.source() is None else "copy"
        event.acceptProposedAction()
        QtCore.QTimer.singleShot(0, lambda: self.panel.main.drop_files(self.panel, paths, target, action))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.panel:
            self.panel.activate()


class FullView(_ViewMixin, QtWidgets.QTreeView):
    def __init__(self, panel):
        super().__init__()
        self.setup_common(panel)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setItemsExpandable(False)
        self.setAllColumnsShowFocus(True)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(False)
        self.header().setSectionsMovable(False)
        self.header().setStretchLastSection(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)


class BriefView(_ViewMixin, QtWidgets.QListView):
    def __init__(self, panel, thumbs=False):
        super().__init__()
        self.setup_common(panel)
        self.setUniformItemSizes(not thumbs)
        if thumbs:
            self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            self.setIconSize(QtCore.QSize(96, 96))
            self.setGridSize(QtCore.QSize(124, 130))
            self.setWordWrap(True)
            self.setMovement(QtWidgets.QListView.Movement.Static)
        else:
            self.setFlow(QtWidgets.QListView.Flow.TopToBottom)
            self.setWrapping(True)
        self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.setLayoutMode(QtWidgets.QListView.LayoutMode.Batched)


class DirSizeThread(QtCore.QThread):
    result = Signal(str, object)

    def __init__(self, items, parent=None, fs=None):
        super().__init__(parent)
        self.items = items  # list of (name, path)
        self.fs = fs
        self.stop = False

    def run(self):
        for name, path in self.items:
            if self.fs is not None and hasattr(self.fs, "tree_size"):
                try:
                    total = self.fs.tree_size(path, lambda: self.stop)
                except OSError:
                    continue
                if total is None:
                    return
                self.result.emit(name, total)
                continue
            total = 0
            for root, dirs, files in os.walk(path):
                if self.stop:
                    return
                for f in files:
                    try:
                        total += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
            self.result.emit(name, total)


class PathEdit(QtWidgets.QLineEdit):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setFrame(False)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.setText(self.panel.location_text())
            self.panel.view.setFocus()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        self.panel.activate(focus=False)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.panel.main.cmd_DirHotlist()


QS_MODES = ["ctrlalt", "alt", "letters", "letters_dialog", "off"]


def qs_mode():
    m = config.get("quicksearch_mode", "alt")
    if m == "cmdline":
        return "off"
    if m == "letters" and not config.get("qs_mode_v2"):
        return "letters_dialog"  # pre 1.2 "letters" showed the dialog
    return m if m in QS_MODES else "ctrlalt"


def key_char(event):
    """Typed character of a key event; Alt+letter may come without text on some platforms."""
    t = event.text()
    if t and t.isprintable():
        return t
    k = event.key()
    if Qt.Key.Key_A <= k <= Qt.Key.Key_Z:
        c = chr(ord("a") + k - Qt.Key.Key_A)
        return c.upper() if event.modifiers() & SHIFT else c
    if Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
        return chr(ord("0") + k - Qt.Key.Key_0)
    if k in (Qt.Key.Key_Period, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
        return {Qt.Key.Key_Period: ".", Qt.Key.Key_Minus: "-", Qt.Key.Key_Underscore: "_"}[k]
    return ""


class QuickSearchEdit(QtWidgets.QLineEdit):
    def __init__(self, bar):
        super().__init__()
        self.bar = bar

    def event(self, e):
        if e.type() == QtCore.QEvent.Type.ShortcutOverride and e.modifiers() & ALT \
                and not e.modifiers() & CTRL and key_char(e) not in ("", " "):
            e.accept()  # TC: keep typing with Alt held, don't open menus
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        k = e.key()
        p = self.bar.panel
        if e.modifiers() & ALT and not e.modifiers() & CTRL and key_char(e) not in ("", " "):
            # QLineEdit ignores Alt+letter: insert it ourselves
            old = self.text()
            self.insert(key_char(e))
            self._typed(old, self.text())
            return
        if k == Qt.Key.Key_Escape:
            self.bar.close_search(clear_filter=True)
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.bar.close_search(clear_filter=False)
            p.open_current()
            return
        if k == Qt.Key.Key_Down:
            p.quick_find(self.text(), forward=True, skip_current=True)
            return
        if k == Qt.Key.Key_Up:
            p.quick_find(self.text(), forward=False, skip_current=True)
            return
        if k in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Tab, Qt.Key.Key_Insert):
            self.bar.close_search(clear_filter=False)
            QtWidgets.QApplication.sendEvent(p.view, e)
            return
        old = self.text()
        super().keyPressEvent(e)
        self._typed(old, self.text())

    def _typed(self, old, new):
        p = self.bar.panel
        if new == old:
            return
        # TC: typing the last letter again jumps to the next match
        if len(new) == len(old) + 1 and old and new[-1] == old[-1] and not p.quick_has_match(new) \
                and p.quick_has_match(old):
            self.setText(old)
            p.quick_find(old, forward=True, skip_current=True)
            return
        p.quick_changed(new)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        QtCore.QTimer.singleShot(0, self.bar.maybe_hide)


class QuickSearch(QtWidgets.QWidget):
    """Quick search dialog (TC: Ctrl+Alt+letters / letters / Ctrl+S) with options and filter mode."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(2)
        self.label = QtWidgets.QLabel("Suche:")
        self.edit = QuickSearchEdit(self)
        self.filter_btn = QtWidgets.QToolButton()
        self.filter_btn.setText("Filter")
        self.filter_btn.setCheckable(True)
        self.filter_btn.setToolTip("Nur passende Dateien anzeigen (Ctrl+S)")
        self.filter_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.filter_btn.toggled.connect(self._filter_toggled)
        self.opt_btn = QtWidgets.QToolButton()
        self.opt_btn.setText("▾")
        self.opt_btn.setToolTip("Optionen der Schnellsuche")
        self.opt_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.opt_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QtWidgets.QMenu(self)
        self.act_begin = menu.addAction("Anfang (Name beginnt mit Eingabe)")
        self.act_end = menu.addAction("Ende (Name endet mit Eingabe)")
        menu.addSeparator()
        self.act_filter = menu.addAction("Filter")
        menu.addSeparator()
        grp = QActionGroup(self)
        self.act_both = menu.addAction("Dateien und Verzeichnisse")
        self.act_files = menu.addAction("Nur Dateien")
        self.act_dirs = menu.addAction("Nur Verzeichnisse")
        for a in (self.act_begin, self.act_end, self.act_filter, self.act_both, self.act_files, self.act_dirs):
            a.setCheckable(True)
        for a in (self.act_both, self.act_files, self.act_dirs):
            grp.addAction(a)
        self.act_begin.setChecked(bool(config.get("qs_match_begin", True)))
        self.act_end.setChecked(bool(config.get("qs_match_end", False)))
        kind = config.get("qs_kind", "both")
        {"files": self.act_files, "dirs": self.act_dirs}.get(kind, self.act_both).setChecked(True)
        self.act_filter.toggled.connect(self.filter_btn.setChecked)
        for a in (self.act_begin, self.act_end, self.act_both, self.act_files, self.act_dirs):
            a.triggered.connect(self._opts_changed)
        menu.aboutToHide.connect(lambda: QtCore.QTimer.singleShot(0, self.edit.setFocus))
        self.opt_btn.setMenu(menu)
        lay.addWidget(self.label)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.filter_btn)
        lay.addWidget(self.opt_btn)
        self.hide()

    # options
    def match_begin(self):
        return self.act_begin.isChecked()

    def match_end(self):
        return self.act_end.isChecked()

    def kind(self):
        return "files" if self.act_files.isChecked() else ("dirs" if self.act_dirs.isChecked() else "both")

    def filter_on(self):
        return self.filter_btn.isChecked()

    def _opts_changed(self):
        config["qs_match_begin"] = self.match_begin()
        config["qs_match_end"] = self.match_end()
        config["qs_kind"] = self.kind()
        self.panel.quick_changed(self.edit.text())

    def _filter_toggled(self, on):
        self.act_filter.blockSignals(True)
        self.act_filter.setChecked(on)
        self.act_filter.blockSignals(False)
        config["qs_filter"] = on
        self.panel.quick_changed(self.edit.text())
        self.edit.setFocus()

    def open(self, text="", filter_mode=None):
        self.filter_btn.blockSignals(True)
        self.filter_btn.setChecked(bool(config.get("qs_filter", False)) if filter_mode is None else filter_mode)
        self.act_filter.setChecked(self.filter_btn.isChecked())
        self.filter_btn.blockSignals(False)
        self.show()
        self.edit.setText(text)
        self.edit.setFocus()
        self.panel.quick_changed(text)

    def close_search(self, clear_filter):
        self.hide()
        if clear_filter:
            self.panel.clear_quick_filter()
        self.panel.view.setFocus()
        self.panel.update_status()

    def maybe_hide(self):
        fw = QtWidgets.QApplication.focusWidget()
        if fw is not None and (fw is self.edit or self.isAncestorOf(fw)):
            return
        if QtWidgets.QApplication.activePopupWidget() is not None:
            return
        self.hide()
        self.panel.update_status()


class FilePanel(QtWidgets.QWidget):
    locationChanged = Signal(object)
    activated = Signal(object)

    def __init__(self, main, side, location=None):
        super().__init__()
        self.main = main
        self.side = side
        self.fs = vfs.LOCAL
        self.inner = os.path.expanduser("~")
        self.history = []
        self.hist_pos = -1
        self.mode = MODE_FULL
        self.size_thread = None
        self.locked = False      # TC "Tab gesperrt"
        self.lock_nav = False    # TC "Gesperrt, Verzeichniswechsel erlaubt"
        self.lock_path = None
        self.qs_buffer = ""
        self.tabbed = None
        self._active = False
        self.model = FileListModel(self)
        self.model.renameRequested.connect(self.on_rename)
        self.model.marksChanged.connect(self.update_status)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.path_edit = PathEdit(self)
        self.path_edit.returnPressed.connect(self.on_path_entered)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Schnellfilter (Esc schließt)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.on_filter)
        self.filter_edit.hide()
        self.filter_edit.installEventFilter(self)
        lay.addWidget(self.path_edit)
        lay.addWidget(self.filter_edit)

        self.stack = QtWidgets.QStackedWidget()
        self.full = FullView(self)
        self.full.setModel(self.model)
        self.full.header().sortIndicatorChanged.connect(lambda c, o: None)
        self.brief = BriefView(self)
        self.brief.setModel(self.model)
        self.thumbs = BriefView(self, thumbs=True)
        self.thumbs.setModel(self.model)
        self.tree_model = QtGui.QFileSystemModel(self) if hasattr(QtGui, "QFileSystemModel") else \
            QtWidgets.QFileSystemModel(self)
        self.tree_model.setFilter(QtCore.QDir.Filter.AllDirs | QtCore.QDir.Filter.NoDotAndDotDot)
        self.tree_model.setRootPath("/")
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.tree_model)
        for c in range(1, 4):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self.on_tree_clicked)
        self.tree.activated.connect(self.on_tree_clicked)
        for v in (self.full, self.brief, self.thumbs, self.tree):
            self.stack.addWidget(v)
        lay.addWidget(self.stack, 1)
        self.quick = QuickSearch(self)
        lay.addWidget(self.quick)
        self.status = QtWidgets.QLabel()
        self.status.setContentsMargins(4, 1, 4, 1)
        lay.addWidget(self.status)

        hdr = self.full.header()
        widths = config.get("columns") or [260, 60, 100, 130, 90]
        for i, w in enumerate(widths[:5]):
            self.full.setColumnWidth(i, w)
        hdr.setSectionResizeMode(COL_NAME, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.full.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)

        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._schedule_refresh)
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(400)
        self.refresh_timer.timeout.connect(lambda: self.refresh(keep=True))

        self.set_active_look(False)
        if location:
            if not self.set_location(location):
                self.set_location(os.path.expanduser("~"))
        else:
            self.set_location(os.path.expanduser("~"))

    # ------------------------------------------------------------ properties
    @property
    def view(self):
        return {MODE_FULL: self.full, MODE_BRIEF: self.brief, MODE_THUMBS: self.thumbs,
                MODE_TREE: self.tree}[self.mode]

    def location(self):
        return vfs.location_of(self.fs, self.inner)

    def location_text(self):
        return self.fs.display(self.inner)

    def local_dir(self):
        """Real directory if the panel shows a local directory, else None."""
        return self.inner if self.fs.kind == "local" else None

    def current_row(self):
        if self.mode == MODE_TREE:
            return -1
        return self.view.currentIndex().row()

    def current_entry(self):
        return self.model.entry(self.current_row())

    def selected_entries(self, allow_up=False):
        m = self.model.marked_entries()
        if m:
            return m
        e = self.current_entry()
        if e is None or (e.is_up and not allow_up):
            return []
        return [e]

    def selected_paths(self):
        return [e.path for e in self.selected_entries() if e.path]

    # ------------------------------------------------------------ appearance
    def apply_view_settings(self):
        cols = [None, "col_ext", "col_size", "col_date", "col_attr"]
        for i, key in enumerate(cols):
            if key:
                self.full.setColumnHidden(i, not config.get(key, True))
        alt = bool(config.get("alt_rows", False))
        for v in (self.full, self.brief):
            v.setAlternatingRowColors(alt)
        mc = config.get("color_mark")
        self.model.mark_color = QtGui.QColor(mc) if mc else QtGui.QColor(220, 0, 0)
        self.set_active_look(self._active)
        self.model.layoutChanged.emit()

    def set_active_look(self, active):
        self._active = active
        pal = self.palette()
        if active:
            hl = pal.color(QtGui.QPalette.ColorRole.Highlight).name()
            ht = pal.color(QtGui.QPalette.ColorRole.HighlightedText).name()
        else:
            hl = pal.color(QtGui.QPalette.ColorRole.Mid).name()
            ht = pal.color(QtGui.QPalette.ColorRole.Text).name()
        self.path_edit.setStyleSheet("QLineEdit{background:%s;color:%s;padding:2px 4px;font-weight:%s}"
                                     % (hl, ht, "bold" if active else "normal"))
        css = ""
        bg, fg = config.get("color_bg"), config.get("color_text")
        if bg or fg:
            css += "QAbstractItemView{%s%s}" % ("background:%s;" % bg if bg else "", "color:%s;" % fg if fg else "")
        cur, curt = config.get("color_cursor"), config.get("color_cursor_text")
        if active:
            if cur or curt:
                css += "QAbstractItemView::item:selected{%s%s}" % (
                    "background:%s;" % cur if cur else "", "color:%s;" % curt if curt else "")
        else:
            css += ("QAbstractItemView::item:selected{background:transparent;border:1px dotted %s;color:%s;}"
                    % (fg or pal.color(QtGui.QPalette.ColorRole.Text).name(),
                       fg or pal.color(QtGui.QPalette.ColorRole.Text).name()))
        for v in (self.full, self.brief, self.thumbs):
            v.setStyleSheet(css)

    def activate(self, focus=False):
        self.activated.emit(self)
        if focus:
            self.view.setFocus()

    def set_mode(self, mode):
        name = None
        e = self.current_entry()
        if e:
            name = e.name
        self.mode = mode
        self.model.thumbs = mode == MODE_THUMBS
        self.model._brief_full_names = mode in (MODE_BRIEF, MODE_THUMBS)
        self.model.layoutChanged.emit()
        self.stack.setCurrentWidget(self.view)
        if mode == MODE_TREE:
            d = self.local_dir() or os.path.expanduser("~")
            idx = self.tree_model.index(d)
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx)
        elif name:
            self.select_name(name)
        self.view.setFocus()

    def on_tree_clicked(self, idx):
        path = self.tree_model.filePath(idx)
        if path:
            self.main.other_panel(self).set_location(path)

    # ------------------------------------------------------------ navigation
    def set_location(self, location, select=None, add_history=True, keep_marks=False, force=False):
        from .utils import expand_drive
        location = os.path.expanduser(expand_drive(location.strip()))
        if location and not location.startswith(("/", "results://")) and not vfs.is_url(location) \
                and self.history:
            # relative path: relative to this panel (not to the process cwd)
            base = self.location_text() if self.fs.kind != "results" else os.path.expanduser("~")
            location = os.path.normpath(os.path.join(base, location))
        if self.locked and not self.lock_nav and not force and self.history and self.tabbed is not None:
            try:
                same = vfs.location_of(*vfs.resolve(location)) == self.location()
            except Exception:  # noqa: BLE001
                same = False
            if not same:
                # locked tab (TC): changing the directory opens a new tab
                np_ = self.tabbed.add_tab(self.location())
                if np_.set_location(location, select=select, force=True):
                    self.main._hook_panel(np_)
                    self.main.apply_settings()
                    np_.activate(focus=True)
                    return True
                self.tabbed.close_tab(self.tabbed.tabs.indexOf(np_), force=True)
                return False
        try:
            fs, inner = vfs.resolve(location)
            entries = fs.list(inner, show_hidden=config.get("show_hidden"))
        except vfs.ArchiveError as ex:
            QtWidgets.QMessageBox.warning(self, "Archiv", "Archiv kann nicht geöffnet werden:\n%s" % ex)
            return False
        except (OSError, FileNotFoundError) as ex:
            if self.isVisible():
                QtWidgets.QMessageBox.warning(self, "Fehler", "Verzeichnis kann nicht gelesen werden:\n%s\n\n%s"
                                              % (location, ex))
            return False
        old_loc = self.location()
        if not keep_marks:
            self.model.marked.clear()
            self.model.filter_fn = None
            self.quick.hide()
            self.qs_buffer = ""
        self.fs, self.inner = fs, inner
        up = self._up_entry()
        self.model.set_entries(entries, up, writable=fs.writable)
        self.path_edit.setText(self.location_text())
        self.path_edit.setToolTip(self.location_text())
        self._watch()
        if select is None and old_loc and add_history:
            # coming up from child directory -> select it
            if old_loc.startswith(self.location().rstrip("/") + "/"):
                rest = old_loc[len(self.location().rstrip("/")) + 1:]
                select = rest.split("/")[0]
        if self.filter_edit.isVisible() and not keep_marks:
            self.filter_edit.clear()
        self.select_name(select) if select else self.select_row(0)
        if add_history and fs.kind != "results":
            loc = self.location()
            if not self.history or self.history[self.hist_pos] != loc:
                self.history = self.history[:self.hist_pos + 1]
                self.history.append(loc)
                if len(self.history) > 100:
                    self.history = self.history[-100:]
                self.hist_pos = len(self.history) - 1
        if fs.kind == "local":
            try:
                os.chdir(inner)
            except OSError:
                pass
        self.update_status()
        self.locationChanged.emit(self)
        return True

    def _up_entry(self):
        if not config.get("show_dotdot", True):
            return None
        if self.fs.kind == "local":
            if self.inner == "/":
                return None
            return vfs.Entry("..", True, path=self.fs.parent(self.inner))
        if self.fs.kind == "archive":
            return vfs.Entry("..", True, path=None)
        if self.fs.kind == "ftp" and self.inner == "/":
            return None
        return vfs.Entry("..", True, path=None)

    def _watch(self):
        dirs = self.watcher.directories()
        if dirs:
            self.watcher.removePaths(dirs)
        if self.fs.kind == "local":
            self.watcher.addPath(self.inner)

    def _schedule_refresh(self, _p=None):
        self.refresh_timer.start()

    def refresh(self, keep=True):
        e = self.current_entry()
        name = e.name if e else None
        row = self.current_row()
        dir_sizes = {x.name: x.dir_size for x in self.model.all_entries if x.dir_size is not None}
        loc = self.location()
        if self.fs.kind == "local" and not os.path.isdir(self.inner):
            # directory vanished: go to the nearest existing parent
            p = self.inner
            while p != "/" and not os.path.isdir(p):
                p = os.path.dirname(p)
            self.set_location(p)
            return
        try:
            fs, inner = vfs.resolve(loc)
            entries = fs.list(inner, show_hidden=config.get("show_hidden"))
        except Exception:  # noqa: BLE001
            return
        for x in entries:
            if x.name in dir_sizes:
                x.dir_size = dir_sizes[x.name]
        self.fs, self.inner = fs, inner
        self.model.set_entries(entries, self._up_entry(), writable=fs.writable)
        if name and self.model.row_of(name) >= 0:
            self.select_name(name)
        else:
            self.select_row(min(max(row, 0), self.model.rowCount() - 1))
        self.update_status()

    def go_up(self):
        if self.fs.kind == "results":
            if self.history:
                self.set_location(self.history[self.hist_pos], add_history=False)
            return
        if self.fs.kind == "archive":
            if not self.inner:
                self.set_location(os.path.dirname(self.fs.archive), select=os.path.basename(self.fs.archive))
            else:
                self.set_location(self.fs.display(self.fs.parent(self.inner)),
                                  select=self.inner.rsplit("/", 1)[-1])
            return
        if self.fs.kind == "ftp":
            if self.inner != "/":
                self.set_location(self.fs.display(self.fs.parent(self.inner)),
                                  select=self.inner.rstrip("/").rsplit("/", 1)[-1])
            return
        if self.inner != "/":
            self.set_location(self.fs.parent(self.inner), select=os.path.basename(self.inner.rstrip("/")))

    def go_root(self):
        if self.fs.kind == "archive":
            self.set_location(self.fs.display(""))
        elif self.fs.kind == "ftp":
            self.set_location(self.fs.display("/"))
        else:
            self.set_location("/")

    def go_back(self):
        if self.hist_pos > 0:
            self.hist_pos -= 1
            self.set_location(self.history[self.hist_pos], add_history=False)

    def go_forward(self):
        if self.hist_pos < len(self.history) - 1:
            self.hist_pos += 1
            self.set_location(self.history[self.hist_pos], add_history=False)

    def show_history_menu(self):
        menu = QtWidgets.QMenu(self)
        for i in range(len(self.history) - 1, -1, -1):
            a = menu.addAction(self.history[i])
            if i == self.hist_pos:
                f = a.font()
                f.setBold(True)
                a.setFont(f)
            a.triggered.connect(lambda _c=False, i=i: self._hist_jump(i))
        qexec(menu, self.path_edit.mapToGlobal(QtCore.QPoint(0, self.path_edit.height())))

    def _hist_jump(self, i):
        self.hist_pos = i
        self.set_location(self.history[i], add_history=False)

    def on_path_entered(self):
        t = self.path_edit.text().strip()
        while t.lower() == "cd" or t.lower().startswith("cd "):
            t = t[2:].strip() or "~"
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
            t = t[1:-1]
        if not t:
            return
        if t == "-":
            self.go_back()
            self.view.setFocus()
            return
        from .utils import expand_drive
        full = os.path.expanduser(expand_drive(t))
        if not full.startswith(("/", "results://")) and not vfs.is_url(full):
            full = os.path.normpath(os.path.join(self.location_text() if self.fs.kind != "results"
                                                 else os.path.expanduser("~"), full))
        if not vfs.is_url(full) and not os.path.exists(full):
            from .utils import find_dir_nocase
            full = find_dir_nocase(full) or full
        if os.path.isfile(full) and not (vfs.is_archive_name(full) and vfs.archive_backend(full)):
            ok = self.set_location(os.path.dirname(full), select=os.path.basename(full))
        else:
            ok = self.set_location(full)
        if ok:
            self.view.setFocus()
        else:
            self.path_edit.setText(self.location_text())

    def open_current(self):
        e = self.current_entry()
        if e is None:
            return
        if e.is_up:
            self.go_up()
            return
        if self.fs.kind in ("archive", "ftp"):
            if e.is_dir:
                self.set_location(self.fs.display(e.path))
            else:
                self.main.open_archive_member(self, e)
            return
        if e.is_dir:
            self.set_location(e.path)
            return
        self.main.open_file(self, e.path)

    def select_row(self, row):
        if self.mode == MODE_TREE or self.model.rowCount() == 0:
            return
        row = max(0, min(row, self.model.rowCount() - 1))
        idx = self.model.index(row, 0)
        for v in (self.full, self.brief, self.thumbs):
            v.setCurrentIndex(idx)
        self.view.scrollTo(idx)

    def select_name(self, name):
        r = self.model.row_of(name)
        self.select_row(r if r >= 0 else 0)

    # ------------------------------------------------------------ keyboard
    def handle_key(self, event):
        k = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & CTRL)
        shift = bool(mods & SHIFT)
        alt = bool(mods & ALT)
        keypad = bool(mods & KEYPAD)
        text = event.text()
        row = self.current_row()
        n = self.model.rowCount()

        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl and not alt:
            cl = self.main.cmdline
            if cl.text().strip():
                self.main.run_cmdline(shift)
                return True
            if shift:
                e = self.current_entry()
                if e and not e.is_dir and self.fs.kind != "archive":
                    self.main.run_in_terminal(e.path)
                    return True
            self.open_current()
            return True
        if k == Qt.Key.Key_Backspace and not ctrl and not alt:
            if self.main.cmdline.text():
                self.main.cmdline.backspace()
                return True
            self.go_up()
            return True
        if k == Qt.Key.Key_PageUp and ctrl:
            self.go_up()
            return True
        if k == Qt.Key.Key_PageDown and ctrl:
            e = self.current_entry()
            if e and (e.is_dir or vfs.is_archive_name(e.name)):
                self.open_current()
            return True
        if k == Qt.Key.Key_Backslash and ctrl or (k == Qt.Key.Key_Slash and ctrl):
            self.go_root()
            return True
        if k == Qt.Key.Key_Left and alt:
            self.go_back()
            return True
        if k == Qt.Key.Key_Right and alt:
            self.go_forward()
            return True
        if k == Qt.Key.Key_Down and alt:
            self.show_history_menu()
            return True
        if k == Qt.Key.Key_Insert and not ctrl and not shift:
            self.model.toggle_mark(row)
            self.select_row(row + 1)
            return True
        if k == Qt.Key.Key_Space and not ctrl and not alt and not self.main.cmdline.text():
            e = self.current_entry()
            if e and not e.is_up:
                if e.is_dir and e.dir_size is None and (self.fs.is_local or self.fs.kind == "ftp"):
                    self.calc_dir_sizes([e])
                self.model.toggle_mark(row)
                if not (e.is_dir and False):
                    self.select_row(row + 1) if config.get("space_moves_down", True) else None
            return True
        if shift and k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                           Qt.Key.Key_Home, Qt.Key.Key_End) and self.mode != MODE_TREE:
            if k == Qt.Key.Key_Up:
                target = row - 1
            elif k == Qt.Key.Key_Down:
                target = row + 1
            elif k == Qt.Key.Key_Home:
                target = 0
            elif k == Qt.Key.Key_End:
                target = n - 1
            else:
                page = max(1, self.view.viewport().height() // max(1, self.view.sizeHintForRow(0)
                                                                     if self.mode == MODE_FULL else 18) - 1)
                target = row - page if k == Qt.Key.Key_PageUp else row + page
            target = max(0, min(target, n - 1))
            # TC: Shift+cursor marks the file under the cursor and moves
            st = None
            e = self.current_entry()
            if e and not e.is_up:
                st = e.name not in self.model.marked
            a, b = (row, target) if target >= row else (target, row)
            rng = range(a, b) if target > row else range(a + 1, b + 1)
            if k in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                rng = [row]
            for r in rng:
                self.model.toggle_mark(r, st if st is not None else True)
            self.select_row(target)
            return True
        # selection with + - * / (numeric keypad, optionally main keyboard)
        main_kb = (not keypad and config.get("plusminus_main", True) and not self.main.cmdline.text()
                   and not self.qs_buffer and not ctrl and not alt)
        if k == Qt.Key.Key_Plus and (keypad or main_kb) or (ctrl and k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal)
                                                            and not alt):
            if ctrl:
                self.main.cmd_SelectAll()
            elif alt:
                self.select_same_ext(True)
            else:
                self.main.cmd_SelectGroup()
            return True
        if k == Qt.Key.Key_Plus and keypad and alt:
            self.select_same_ext(True)
            return True
        if k == Qt.Key.Key_Minus and (keypad or main_kb) or (ctrl and k == Qt.Key.Key_Minus):
            if ctrl:
                self.main.cmd_ClearAll()
            elif alt:
                self.select_same_ext(False)
            else:
                self.main.cmd_UnselectGroup()
            return True
        if k == Qt.Key.Key_Asterisk and (keypad or main_kb):
            if shift and keypad:
                self.main.cmd_ExchangeSelBoth()
            else:
                self.main.cmd_InvertSelection()
            return True
        if k == Qt.Key.Key_Slash and keypad:
            self.main.cmd_RestoreSelection()
            return True
        if k == Qt.Key.Key_Escape:
            if self.qs_buffer:
                self.qs_buffer = ""
                self.update_status()
                return True
            if self.model.filter_fn is not None:
                self.clear_quick_filter()
                return True
            if self.filter_edit.isVisible():
                self.filter_edit.clear()
                self.filter_edit.hide()
                return True
            if self.main.cmdline.text():
                self.main.cmdline.clear()
                return True
            return False
        # letters: quick search or command line (TC: Konfiguration > Schnellsuche)
        mode = qs_mode()
        if self.is_quicksearch_key(event):
            text = key_char(event)
            if mode == "letters_dialog" or (mode in ("ctrlalt", "alt") and config.get("qs_show_dialog")):
                self.quick.open(text)
            else:
                self.quick_invisible(text)
            return True
        if text and text.isprintable() and text != " ":
            if not alt and not ctrl:
                self.qs_buffer = ""
                self.main.cmdline.setFocus()
                self.main.cmdline.insert(text)
                return True
        if self.qs_buffer and k not in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                                        Qt.Key.Key_AltGr):
            self.qs_buffer = ""  # TC: cursor keys reset the invisible quick search
            self.update_status()
        return False

    # ------------------------------------------------------------ quick search
    def is_quicksearch_key(self, event):
        text = key_char(event)
        if not text or not text.isprintable() or text == " ":
            return False
        mods = event.modifiers()
        ctrl, alt = bool(mods & CTRL), bool(mods & ALT)
        mode = qs_mode()
        return ((mode == "ctrlalt" and ctrl and alt) or (mode == "alt" and alt and not ctrl) or
                (mode in ("letters", "letters_dialog") and not alt and not ctrl))

    def _qs_options(self):
        return (self.quick.match_begin(), self.quick.match_end(), self.quick.kind())

    def quick_pattern(self, text):
        begin, end, _kind = self._qs_options()
        t = text.lower()
        if not begin and not t.startswith("*"):
            t = "*" + t
        if not end and not t.endswith("*"):
            t = t + "*"
        return t

    def quick_match(self, e, pat, kind=None):
        import fnmatch
        if e is None or e.is_up:
            return False
        kind = kind or self._qs_options()[2]
        if kind == "files" and e.is_dir or kind == "dirs" and not e.is_dir:
            return False
        return fnmatch.fnmatchcase(e.name.lower(), pat)

    def quick_has_match(self, text):
        pat = self.quick_pattern(text)
        return any(self.quick_match(e, pat) for e in self.model.all_entries)

    def quick_changed(self, text):
        if self.quick.isVisible() and self.quick.filter_on() and text:
            pat = self.quick_pattern(text)
            kind = self._qs_options()[2]
            cur = self.current_entry()

            def fn(e, pat=pat, kind=kind):
                if kind == "files" and e.is_dir or kind == "dirs" and not e.is_dir:
                    return True  # not searched -> stays visible
                return self.quick_match(e, pat, kind)
            self.model.set_filter_fn(fn)
            if cur and self.model.row_of(cur.name) >= 0 and self.quick_match(cur, pat):
                self.select_name(cur.name)
            else:
                self.quick_find(text)
        else:
            if self.model.filter_fn is not None:
                self.clear_quick_filter(keep_cursor=True)
            if text:
                self.quick_find(text)
        self.update_status()

    def clear_quick_filter(self, keep_cursor=True):
        if self.model.filter_fn is None:
            return
        cur = self.current_entry()
        self.model.set_filter_fn(None)
        if cur and keep_cursor:
            self.select_name(cur.name)
        self.update_status()

    def quick_invisible(self, ch):
        new = self.qs_buffer + ch
        if self.quick_has_match(new):
            self.qs_buffer = new
            self.quick_find(new)
        elif self.qs_buffer and ch.lower() == self.qs_buffer[-1:].lower():
            self.quick_find(self.qs_buffer, forward=True, skip_current=True)
        self.update_status()

    def start_quick(self, text):
        self.quick.open(text)

    def open_quick_filter(self):
        if self.quick.isVisible() and self.quick.filter_on():
            self.quick.close_search(clear_filter=True)
        else:
            self.quick.open(self.quick.edit.text() if self.quick.isVisible() else "", filter_mode=True)

    def quick_find(self, text, forward=True, skip_current=False):
        if not text:
            return False
        pat = self.quick_pattern(text)
        n = self.model.rowCount()
        start = max(self.current_row(), 0)
        if forward:
            first = start + 1 if skip_current else start
            order = list(range(first, n)) + list(range(0, min(first, n)))
        else:
            first = start - 1
            order = list(range(first, -1, -1)) + list(range(n - 1, first, -1))
        for r in order:
            if self.quick_match(self.model.entry(r), pat):
                self.select_row(r)
                return True
        return False

    def eventFilter(self, obj, ev):
        if obj is self.filter_edit and ev.type() == QtCore.QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self.filter_edit.clear()
                self.filter_edit.hide()
                self.view.setFocus()
                return True
            if ev.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.view.setFocus()
                return True
        return super().eventFilter(obj, ev)

    def toggle_user_filter(self):
        if self.filter_edit.isVisible():
            self.filter_edit.clear()
            self.filter_edit.hide()
            self.view.setFocus()
        else:
            self.filter_edit.show()
            self.filter_edit.setFocus()

    def on_filter(self, text):
        self.model.set_filter(text)
        self.select_row(0)
        self.update_status()

    # ------------------------------------------------------------ marking helpers
    def select_same_ext(self, state):
        e = self.current_entry()
        if not e or e.is_up:
            return
        from .utils import split_ext
        ext = split_ext(e.name, e.is_dir)[1].lower()
        self.model.mark_where(lambda x: not x.is_dir and split_ext(x.name)[1].lower() == ext, state)

    def mark_mask(self, mask_text, state=True, dirs=False):
        m = Mask(mask_text)
        dirs_too = dirs or any(d for _p, d in m.include)
        self.model.mark_where(lambda e: (dirs_too or not e.is_dir) and m.match(e.name, e.is_dir), state)

    # ------------------------------------------------------------ dir sizes
    def calc_dir_sizes(self, entries):
        items = [(e.name, e.path) for e in entries if e.is_dir and not e.is_up and e.path]
        if not items:
            return
        t = DirSizeThread(items, self, fs=self.fs if self.fs.kind == "ftp" else None)
        t.result.connect(self._on_dir_size)
        t.finished.connect(t.deleteLater)
        self.size_thread = t
        t.start()

    def _on_dir_size(self, name, size):
        r = self.model.row_of(name)
        if r >= 0:
            self.model.entry(r).dir_size = size
            self.model.refresh_row(r)
            self.update_status()

    # ------------------------------------------------------------ rename
    def rename_inplace(self):
        e = self.current_entry()
        if not e or e.is_up or not self.fs.writable:
            return
        if self.mode in (MODE_TREE,):
            return
        idx = self.model.index(self.current_row(), COL_NAME)
        self.view.edit(idx)
        ed = self.view.focusWidget()
        if isinstance(ed, QtWidgets.QLineEdit) and not e.is_dir:
            from .utils import split_ext
            b, x = split_ext(e.name)
            if x:
                QtCore.QTimer.singleShot(0, lambda: ed.setSelection(0, len(b)))

    def on_rename(self, entry, new_name):
        if "/" in new_name:
            QtWidgets.QMessageBox.warning(self, "Umbenennen", "Ungültiger Name.")
            return
        src = entry.path
        dst = os.path.join(os.path.dirname(src), new_name)
        if os.path.lexists(dst) and os.path.normcase(dst) != os.path.normcase(src):
            if QtWidgets.QMessageBox.question(self, "Umbenennen", "%s existiert bereits. Überschreiben?" % new_name) \
                    != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        try:
            os.rename(src, dst)
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Umbenennen", str(ex))
            return
        self.refresh()
        self.select_name(new_name)

    # ------------------------------------------------------------ status
    def update_status(self):
        s = self.model.stats()
        extra = ""
        if self.qs_buffer:
            extra = "Schnellsuche: %s   |   " % self.qs_buffer
        elif self.model.filter_fn is not None and not self.quick.isVisible():
            extra = "Filter: %s (Esc hebt auf)   |   " % self.quick.edit.text()
        self.status.setText(extra + "%s / %s in %d / %d Datei(en), %d / %d Verz." % (
            human_size(s["msize"]), human_size(s["size"]), s["mfiles"], s["files"], s["mdirs"], s["dirs"]))

    def column_widths(self):
        return [self.full.columnWidth(i) for i in range(5)]

    def sort_by(self, col):
        if self.full.header().sortIndicatorSection() == col:
            order = Qt.SortOrder.DescendingOrder if self.full.header().sortIndicatorOrder() == \
                Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            order = Qt.SortOrder.AscendingOrder
        name = self.current_entry().name if self.current_entry() else None
        self.full.sortByColumn(col, order)
        if name:
            self.select_name(name)

    def tab_title(self):
        if self.fs.kind == "results":
            return self.fs.title
        if self.fs.kind == "archive":
            return os.path.basename(self.fs.archive) + (("/" + self.inner) if self.inner else "")
        if self.fs.kind == "ftp":
            return self.fs.host + ":" + (self.inner.rstrip("/").rsplit("/", 1)[-1] or "/")
        t = os.path.basename(self.inner.rstrip("/")) or "/"
        if self.inner == os.path.expanduser("~"):
            t = "~"
        if self.locked:
            return ("+ " if self.lock_nav else "* ") + t
        return t


class DriveBar(QtWidgets.QWidget):
    def __init__(self, tabbed):
        super().__init__()
        self.tabbed = tabbed
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.combo = QtWidgets.QComboBox()
        self.combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo.setMaxVisibleItems(30)
        self.combo.activated.connect(self.on_chosen)
        self.info = QtWidgets.QLabel()
        self.info.setContentsMargins(6, 0, 0, 0)
        root_btn = QtWidgets.QToolButton()
        root_btn.setText("/")
        root_btn.setToolTip("Wurzelverzeichnis (Ctrl+\\)")
        root_btn.setAutoRaise(True)
        root_btn.clicked.connect(lambda: self.tabbed.current().go_root())
        up_btn = QtWidgets.QToolButton()
        up_btn.setText("..")
        up_btn.setToolTip("Übergeordnetes Verzeichnis (Backspace)")
        up_btn.setAutoRaise(True)
        up_btn.clicked.connect(lambda: self.tabbed.current().go_up())
        home_btn = QtWidgets.QToolButton()
        home_btn.setText("~")
        home_btn.setAutoRaise(True)
        home_btn.setToolTip("Persönlicher Ordner")
        home_btn.clicked.connect(lambda: self.tabbed.current().set_location(os.path.expanduser("~")))
        hist_btn = QtWidgets.QToolButton()
        hist_btn.setText("▾")
        hist_btn.setAutoRaise(True)
        hist_btn.setToolTip("Verlauf (Alt+↓)")
        hist_btn.clicked.connect(lambda: self.tabbed.current().show_history_menu())
        hot_btn = QtWidgets.QToolButton()
        hot_btn.setText("*")
        hot_btn.setAutoRaise(True)
        hot_btn.setToolTip("Verzeichnis-Hotlist (Ctrl+D)")
        hot_btn.clicked.connect(lambda: (self.tabbed.current().activate(), self.tabbed.main.cmd_DirHotlist()))
        lay.addWidget(self.combo)
        lay.addWidget(self.info, 1)
        for b in (hot_btn, hist_btn, home_btn, root_btn, up_btn):
            lay.addWidget(b)
        self.drives = []
        self.reload()

    def reload(self):
        from .utils import drive_letters
        self.drives = [(l, label, path, icon) for l, label, path, icon in drive_letters()]
        self.combo.clear()
        for letter, label, path, icon in self.drives:
            text = ("%s:  %s" % (letter, label)) if letter else label
            self.combo.addItem(theme_icon(icon, QtWidgets.QStyle.StandardPixmap.SP_DriveHDIcon), text, path)
            self.combo.setItemData(self.combo.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        b = getattr(self.tabbed, "drivebuttons", None)
        if b is not None:
            b.reload(self.drives)

    def drive_of(self, path):
        best, best_len = None, -1
        if path:
            for _letter, _l, dp, _ic in self.drives:
                if (path == dp or path.startswith(dp.rstrip("/") + "/")) and len(dp) > best_len:
                    best, best_len = dp, len(dp)
        return best

    def on_chosen(self, i):
        path = self.combo.itemData(i)
        if path:
            self.tabbed.go_drive(path)

    def popup(self):
        self.reload()
        self.update_for(self.tabbed.current())
        self.combo.showPopup()

    def update_for(self, panel):
        d = panel.local_dir() or (os.path.dirname(panel.fs.archive) if panel.fs.kind == "archive" else None)
        best = -1
        best_len = -1
        if d:
            for i, (_letter, _l, path, _ic) in enumerate(self.drives):
                if (d == path or d.startswith(path.rstrip("/") + "/")) and len(path) > best_len:
                    best, best_len = i, len(path)
        if best >= 0:
            self.combo.setCurrentIndex(best)
        b = getattr(self.tabbed, "drivebuttons", None)
        if b is not None:
            b.set_current(self.drives[best][2] if best >= 0 else None)
        free, total = disk_free(d) if d else (None, None)
        if free is not None:
            self.info.setText("%s von %s frei" % (human_size(free), human_size(total)))
        else:
            self.info.setText("")


class DriveButtons(QtWidgets.QWidget):
    """Total Commander style drive button bar: one button per drive letter."""

    def __init__(self, tabbed):
        super().__init__()
        self.tabbed = tabbed
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(1)
        self.buttons = {}

    def reload(self, drives):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.buttons = {}
        for letter, label, path, icon in drives:
            b = QtWidgets.QToolButton()
            b.setText(letter or label[:3])
            b.setIcon(theme_icon(icon, QtWidgets.QStyle.StandardPixmap.SP_DriveHDIcon))
            b.setIconSize(QtCore.QSize(14, 14))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            free, total = disk_free(path)
            b.setToolTip("%s:  %s\n%s%s" % (letter, label, path, ("\n%s von %s frei" % (
                human_size(free), human_size(total))) if free is not None else ""))
            b.clicked.connect(lambda _c=False, p=path: self.go(p))
            self.lay.addWidget(b)
            self.buttons[path] = b
        self.lay.addStretch(1)

    def go(self, path):
        self.tabbed.go_drive(path)

    def set_current(self, path):
        for pth, b in self.buttons.items():
            b.setChecked(pth == path)


class TabbedPanel(QtWidgets.QWidget):
    activated = Signal(object)

    def __init__(self, main, side):
        super().__init__()
        self.main = main
        self.side = side
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.last_dir = {}
        self.drivebar = DriveBar(self)
        self.drivebuttons = DriveButtons(self)
        self.drivebar.reload()
        lay.addWidget(self.drivebuttons)
        lay.addWidget(self.drivebar)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.tabs.tabBar().setAutoHide(not config.get("show_tabs_always"))
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.on_tab_dblclick)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_menu)
        self.tabs.tabBar().installEventFilter(self)
        lay.addWidget(self.tabs, 1)
        st = config.get(side) or {}
        tabs = st.get("tabs") or []
        for t in tabs:
            if isinstance(t, dict):
                p = self.add_tab(t.get("path"), activate=False)
                if t.get("mode"):
                    p.set_mode(t["mode"])
                if t.get("sort") is not None:
                    p.full.sortByColumn(t["sort"], Qt.SortOrder.DescendingOrder if t.get("desc")
                                        else Qt.SortOrder.AscendingOrder)
                lk = t.get("locked")
                p.locked = bool(lk)
                p.lock_nav = lk == "nav"
                p.lock_path = t.get("lock_path") or (p.location() if lk else None)
                if p.lock_nav and p.lock_path and p.location() != p.lock_path:
                    p.set_location(p.lock_path, force=True)
                self.update_title(p)
        if self.tabs.count() == 0:
            self.add_tab(os.path.expanduser("~"))
        self.tabs.setCurrentIndex(min(st.get("active", 0), self.tabs.count() - 1))

    def eventFilter(self, obj, ev):
        if obj is self.tabs.tabBar() and ev.type() == QtCore.QEvent.Type.MouseButtonRelease \
                and ev.button() == Qt.MouseButton.MiddleButton:
            i = self.tabs.tabBar().tabAt(event_pos(ev))
            if i >= 0:
                self.close_tab(i)
            return True
        return super().eventFilter(obj, ev)

    def current(self):
        return self.tabs.currentWidget()

    def go_drive(self, dpath):
        """TC: switching to a drive goes to the directory of the other panel if it is on the same drive,
        otherwise to the last directory used on that drive. Clicking the current drive goes to its root."""
        p = self.current()
        cur = p.local_dir() or (os.path.dirname(p.fs.archive) if p.fs.kind == "archive" else None)
        target = dpath
        if self.drivebar.drive_of(cur) != dpath:
            other = self.main.other_panel(p)
            od = other.local_dir() if other is not None else None
            if od and self.drivebar.drive_of(od) == dpath:
                target = od
            else:
                last = self.last_dir.get(dpath)
                if last and os.path.isdir(last):
                    target = last
        p.activate(focus=True)
        p.set_location(target)
        self.drivebar.update_for(self.current())

    def panels(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def add_tab(self, location=None, activate=True):
        p = FilePanel(self.main, self.side, location or (self.current().location() if self.current() else None))
        p.tabbed = self
        p.locationChanged.connect(self.on_location_changed)
        p.activated.connect(lambda _p: self.activated.emit(self))
        i = self.tabs.addTab(p, p.tab_title())
        if activate:
            self.tabs.setCurrentIndex(i)
        return p

    def close_tab(self, i=None, force=False):
        if self.tabs.count() <= 1:
            return
        i = self.tabs.currentIndex() if i is None else i
        p = self.tabs.widget(i)
        if p.locked and not force and QtWidgets.QMessageBox.question(self, "Tab schließen", "Tab ist gesperrt. Trotzdem schließen?") \
                != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.tabs.removeTab(i)
        p.deleteLater()

    def on_tab_dblclick(self, i):
        if i < 0:
            self.add_tab()
        else:
            self.close_tab(i)

    def tab_menu(self, pos):
        i = self.tabs.tabBar().tabAt(pos)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Neuer Tab", lambda: self.add_tab())
        if i >= 0:
            p = self.tabs.widget(i)
            menu.addAction("Tab schließen", lambda: self.close_tab(i))
            menu.addAction("Andere Tabs schließen", lambda: self.close_others(i))
            a = menu.addAction("Tab gesperrt")
            a.setCheckable(True)
            a.setChecked(p.locked and not p.lock_nav)
            a.triggered.connect(lambda c: self.set_locked(p, c))
            b = menu.addAction("Gesperrt, aber Verzeichniswechsel erlaubt")
            b.setCheckable(True)
            b.setChecked(p.locked and p.lock_nav)
            b.triggered.connect(lambda c: self.set_locked(p, c, nav=True))
            menu.addAction("In anderem Fenster öffnen", lambda: self.main.other_tabbed(self).add_tab(p.location()))
        qexec(menu, self.tabs.tabBar().mapToGlobal(pos))

    def set_locked(self, p, on, nav=False):
        p.locked = bool(on)
        p.lock_nav = bool(on and nav)
        p.lock_path = p.location() if on else None
        self.update_title(p)

    def close_others(self, keep):
        w = self.tabs.widget(keep)
        for j in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(j) is not w:
                self.close_tab(j)

    def on_tab_changed(self, i):
        p = self.current()
        if p and p.locked and p.lock_nav and p.lock_path and p.location() != p.lock_path:
            # "Verzeichniswechsel erlaubt": back to the locked directory when the tab is activated again
            p.set_location(p.lock_path, force=True)
        if p:
            self.drivebar.update_for(p)
            self.main.on_panel_changed(p)

    def update_title(self, p):
        i = self.tabs.indexOf(p)
        if i >= 0:
            self.tabs.setTabText(i, p.tab_title())
            self.tabs.setTabToolTip(i, p.location_text())

    def on_location_changed(self, p):
        d = p.local_dir()
        if d:
            drv = self.drivebar.drive_of(d)
            if drv:
                self.last_dir[drv] = d
        self.update_title(p)
        if p is self.current():
            self.drivebar.update_for(p)
            self.main.on_panel_changed(p)

    def state(self):
        tabs = []
        for p in self.panels():
            loc = p.location() if p.fs.kind != "results" else (p.history[p.hist_pos] if p.history else "~")
            if p.locked and p.lock_nav and p.lock_path:
                loc = p.lock_path
            tabs.append({"path": loc, "mode": p.mode,
                         "locked": ("nav" if p.lock_nav else True) if p.locked else False,
                         "lock_path": p.lock_path,
                         "sort": p.full.header().sortIndicatorSection(),
                         "desc": p.full.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder})
        return {"tabs": tabs, "active": self.tabs.currentIndex()}
