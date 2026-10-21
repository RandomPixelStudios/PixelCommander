"""Item model for a file panel (Total Commander style columns, marking, sorting)."""
import os
import stat

from .config import config
from .qt import QtCore, QtGui, Qt, Signal
from .utils import format_mode, format_size, format_time, icons, natural_key, split_ext, human_size

COL_NAME, COL_EXT, COL_SIZE, COL_DATE, COL_ATTR = range(5)
HEADERS = ["Name", "Erw.", "Größe", "Datum", "Attr."]

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico", "tif", "tiff", "xpm", "pbm", "pgm", "ppm"}


class FileListModel(QtCore.QAbstractTableModel):
    renameRequested = Signal(object, str)
    marksChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_entries = []
        self.entries = []
        self.up_entry = None
        self.marked = set()
        self.sort_col = COL_NAME
        self.sort_order = Qt.SortOrder.AscendingOrder
        self.filter_text = ""
        self.filter_fn = None
        self.writable = True
        self.thumbs = False
        self.thumb_size = 96
        self._thumb_cache = {}
        self.mark_color = QtGui.QColor(220, 0, 0)

    # ------------------------------------------------------------ data setup
    def set_entries(self, entries, up_entry=None, writable=True):
        self.beginResetModel()
        self.all_entries = entries
        self.up_entry = up_entry
        self.writable = writable
        names = {e.name for e in entries}
        self.marked &= names
        self._apply()
        self.endResetModel()
        self.marksChanged.emit()

    def clear_marks(self):
        self.marked.clear()
        self._changed_all()

    def _apply(self):
        ents = self.all_entries
        if self.filter_text:
            ft = self.filter_text.lower()
            if any(c in ft for c in "*?["):
                import fnmatch
                ents = [e for e in ents if fnmatch.fnmatch(e.name.lower(), ft if "*" in ft else "*" + ft + "*")]
            else:
                ents = [e for e in ents if ft in e.name.lower()]
        if self.filter_fn is not None:
            ents = [e for e in ents if self.filter_fn(e)]
        ents = list(ents)
        self._sort_list(ents)
        self.entries = ([self.up_entry] if self.up_entry else []) + ents

    def _sort_list(self, ents):
        col = self.sort_col
        rev = self.sort_order == Qt.SortOrder.DescendingOrder

        def name_key(e):
            return natural_key(e.name)

        if col == COL_EXT:
            def key(e):
                b, x = split_ext(e.name, e.is_dir)
                return (x.lower(), natural_key(b))
        elif col == COL_SIZE:
            def key(e):
                s = e.dir_size if e.is_dir else e.size
                return (s if s is not None else -1, natural_key(e.name))
        elif col == COL_DATE:
            def key(e):
                return (e.mtime or 0, natural_key(e.name))
        elif col == COL_ATTR:
            def key(e):
                return (e.mode or 0, natural_key(e.name))
        elif col == -1:
            return
        else:
            key = name_key
        if config.get("dirs_first", True):
            dirs = [e for e in ents if e.is_dir]
            files = [e for e in ents if not e.is_dir]
            # TC: directories sorted by name unless sorting by name/date
            dkey = key if col in (COL_NAME, COL_DATE, COL_SIZE) else name_key
            dirs.sort(key=dkey, reverse=rev if col in (COL_NAME, COL_DATE, COL_SIZE) else False)
            files.sort(key=key, reverse=rev)
            ents[:] = dirs + files
        else:
            ents.sort(key=key, reverse=rev)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        self.sort_col = column
        self.sort_order = order
        self._apply()
        self.layoutChanged.emit()

    def set_filter_fn(self, fn):
        self.beginResetModel()
        self.filter_fn = fn
        self._apply()
        self.endResetModel()
        self.marksChanged.emit()

    def set_filter(self, text):
        self.beginResetModel()
        self.filter_text = text
        self._apply()
        self.endResetModel()

    # ------------------------------------------------------------ Qt api
    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole and section == COL_SIZE:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def entry(self, row):
        if 0 <= row < len(self.entries):
            return self.entries[row]
        return None

    def row_of(self, name):
        for i, e in enumerate(self.entries):
            if e.name == name:
                return i
        return -1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                if e.is_up:
                    return ".."
                if e.is_dir:
                    return "[%s]" % e.name if self._brief_full_names and not self.thumbs else e.name
                b, _x = split_ext(e.name)
                return b if not self._brief_full_names else e.name
            if col == COL_EXT:
                return "" if e.is_dir else split_ext(e.name)[1]
            if col == COL_SIZE:
                if e.is_up:
                    return ""
                if e.is_dir:
                    return format_size(e.dir_size) if e.dir_size is not None else "<DIR>"
                if e.is_link and e.broken:
                    return "<LINK>"
                return format_size(e.size)
            if col == COL_DATE:
                return format_time(e.mtime)
            if col == COL_ATTR:
                return format_mode(e.mode)
        elif role == Qt.ItemDataRole.EditRole and col == COL_NAME:
            return e.name
        elif role == Qt.ItemDataRole.DecorationRole and col == COL_NAME:
            if not config.get("show_icons", True):
                return None
            if self.thumbs and not e.is_dir and e.path and split_ext(e.name)[1].lower() in IMAGE_EXT:
                return self._thumb(e)
            ic = icons().for_name(e.name, e.is_dir)
            if e.is_link and not e.is_up:
                return ic  # overlay would be nicer; italic font marks links
            if not e.is_dir and e.mode is not None and e.mode & 0o111 and stat.S_ISREG(e.mode):
                if not split_ext(e.name)[1]:
                    return icons().exe
            return ic
        elif role == Qt.ItemDataRole.ForegroundRole:
            if e.name in self.marked:
                return QtGui.QBrush(self.mark_color)
            if e.name.startswith(".") and not e.is_up:
                return QtGui.QBrush(QtGui.QColor(128, 128, 128))
            if e.is_link and e.broken:
                return QtGui.QBrush(QtGui.QColor(160, 80, 0))
        elif role == Qt.ItemDataRole.FontRole:
            f = None
            if e.is_link:
                f = QtGui.QFont()
                f.setItalic(True)
            if e.name in self.marked:
                f = f or QtGui.QFont()
                f.setBold(True)
            return f
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col == COL_SIZE:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ToolTipRole and col == COL_NAME and not e.is_up:
            tip = e.name
            if e.is_link:
                tip += "\n→ " + (e.link_target or "")
            if not e.is_dir:
                tip += "\n" + human_size(e.size)
            tip += "\n" + format_time(e.mtime)
            return tip
        return None

    _brief_full_names = False

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        e = self.entry(index.row())
        if index.column() == COL_NAME and self.writable and e is not None and not e.is_up:
            f |= Qt.ItemFlag.ItemIsEditable
        if e is not None and e.is_dir:
            f |= Qt.ItemFlag.ItemIsDropEnabled
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.column() == COL_NAME:
            e = self.entry(index.row())
            if e and value and value != e.name:
                self.renameRequested.emit(e, value)
            return False
        return False

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction

    def mimeTypes(self):
        return ["text/uri-list"]

    def mimeData(self, indexes):
        md = QtCore.QMimeData()
        rows = sorted({i.row() for i in indexes})
        names = [self.entries[r].name for r in rows if not self.entries[r].is_up]
        if self.marked:
            ents = [e for e in self.entries if e.name in self.marked]
        else:
            ents = [e for e in self.entries if e.name in names]
        urls = [QtCore.QUrl.fromLocalFile(e.path) for e in ents if e.path and e.path.startswith("/")]
        md.setUrls(urls)
        md.setData("application/x-pixelcommander-source", str(id(self)).encode())
        return md

    # ------------------------------------------------------------ marking
    def _changed_row(self, row):
        self.dataChanged.emit(self.index(row, 0), self.index(row, 4))

    def _changed_all(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, 4))
        self.marksChanged.emit()

    def toggle_mark(self, row, state=None):
        e = self.entry(row)
        if e is None or e.is_up:
            return
        on = (e.name not in self.marked) if state is None else state
        if on:
            self.marked.add(e.name)
        else:
            self.marked.discard(e.name)
        self._changed_row(row)
        self.marksChanged.emit()

    def mark_where(self, pred, state=True):
        for e in self.entries:
            if e.is_up:
                continue
            if pred(e):
                if state:
                    self.marked.add(e.name)
                else:
                    self.marked.discard(e.name)
        self._changed_all()

    def invert_marks(self, files_only=False):
        for e in self.entries:
            if e.is_up or (files_only and e.is_dir):
                continue
            if e.name in self.marked:
                self.marked.discard(e.name)
            else:
                self.marked.add(e.name)
        self._changed_all()

    def marked_entries(self):
        return [e for e in self.entries if e.name in self.marked]

    def refresh_row(self, row):
        self._changed_row(row)

    # ------------------------------------------------------------ thumbnails
    def _thumb(self, e):
        key = (e.path, e.mtime, self.thumb_size)
        ic = self._thumb_cache.get(key)
        if ic is None:
            reader = QtGui.QImageReader(e.path)
            reader.setAutoTransform(True)
            sz = reader.size()
            if sz.isValid() and sz.width() > 0:
                sz.scale(self.thumb_size, self.thumb_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(sz)
            img = reader.read()
            ic = QtGui.QIcon(QtGui.QPixmap.fromImage(img)) if not img.isNull() else icons().for_name(e.name)
            if len(self._thumb_cache) > 2000:
                self._thumb_cache.clear()
            self._thumb_cache[key] = ic
        return ic

    def stats(self):
        files = [e for e in self.entries if not e.is_up and not e.is_dir]
        dirs = [e for e in self.entries if not e.is_up and e.is_dir]
        mf = [e for e in files if e.name in self.marked]
        md = [e for e in dirs if e.name in self.marked]
        size_all = sum(e.size for e in files) + sum(e.dir_size or 0 for e in dirs)
        size_m = sum(e.size for e in mf) + sum(e.dir_size or 0 for e in md)
        return dict(files=len(files), dirs=len(dirs), mfiles=len(mf), mdirs=len(md), size=size_all, msize=size_m)
