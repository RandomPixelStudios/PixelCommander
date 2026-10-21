"""PixelCommander main window: two tabbed panels, menus, button bar, command line, function key bar."""
import os
import re
import shlex
import shutil
import subprocess

from . import __version__, fileops, vfs
from .config import config
from .qt import QtCore, QtGui, QtWidgets, Qt, QAction, qexec, CTRL, SHIFT, event_pos
from .panel import TabbedPanel, MODE_FULL, MODE_BRIEF, MODE_THUMBS, MODE_TREE
from .model import COL_NAME, COL_EXT, COL_SIZE, COL_DATE, COL_ATTR
from .utils import (find_dir_nocase, Mask, human_size, open_default, open_terminal, run_command_template,
                    is_executable_file,
                    icons, theme_icon, split_ext, text_icon)
from .viewer import Lister, ListerWidget
from .imageviewer import ImageViewer, is_image
from .iconpicker import load_icon, pick_icon
from .pixicons import builtin_icon

# name: (label, default shortcut, icon, menu)
COMMANDS = {
    # Dateien
    "cm_View": ("Ansehen (Lister, nur lesen)", "F3", "document-preview", "files"),
    "cm_ViewExternal": ("Mit externem Programm ansehen", "Alt+F3", "", "files"),
    "cm_ImageView": ("Bildbetrachter", "Shift+F3", "image-x-generic", "files"),
    "cm_Edit": ("Bearbeiten (Editor)", "F4", "document-edit", "files"),
    "cm_EditNewFile": ("Neue Datei bearbeiten", "Shift+F4", "document-new", "files"),
    "cm_Copy": ("Kopieren", "F5", "edit-copy", "files"),
    "cm_CopySamePanel": ("Kopieren im selben Fenster", "Shift+F5", "", "files"),
    "cm_RenMov": ("Umbenennen/Verschieben", "F6", "go-next", "files"),
    "cm_RenameOnly": ("Umbenennen (direkt)", "Shift+F6", "edit-rename", "files"),
    "cm_MkDir": ("Verzeichnis erstellen", "F7", "folder-new", "files"),
    "cm_Delete": ("Löschen", "F8", "edit-delete", "files"),
    "cm_DeleteDel": ("Löschen (Entf)", "Del", "", None),
    "cm_DeletePermanent": ("Endgültig löschen", "Shift+Del", "edit-delete-shred", "files"),
    "cm_DeletePermanentF8": ("Endgültig löschen (Shift+F8)", "Shift+F8", "", None),
    "cm_CreateLink": ("Verknüpfung erstellen…", "Ctrl+Shift+F5", "insert-link", "files"),
    "cm_ChangeAttributes": ("Attribute ändern…", "Ctrl+Shift+A", "document-properties", "files"),
    "cm_Properties": ("Eigenschaften…", "Alt+Return", "document-properties", "files"),
    "cm_OpenWith": ("Öffnen mit…", "", "document-open", "files"),
    "cm_PackFiles": ("Packen…", "Alt+F5", "package-x-generic", "files"),
    "cm_UnpackFiles": ("Entpacken…", "Alt+F9", "archive-extract", "files"),
    "cm_TestArchive": ("Archiv testen", "Alt+Shift+F9", "", "files"),
    "cm_CompareFilesByContent": ("Dateien vergleichen (nach Inhalt)…", "Ctrl+Shift+K", "document-compare", "files"),
    "cm_MultiRenameFiles": ("Mehrfach-Umbenennen…", "Ctrl+M", "edit-rename", "files"),
    "cm_CRCCreate": ("Prüfsummen erzeugen (MD5/SHA)…", "", "", "files"),
    "cm_CRCVerify": ("Prüfsummen verifizieren…", "", "", "files"),
    "cm_SplitFile": ("Datei aufteilen…", "", "", "files"),
    "cm_CombineFiles": ("Dateien zusammenfügen…", "", "", "files"),
    "cm_CalcSpace": ("Belegten Speicher berechnen", "Ctrl+L", "", "files"),
    "cm_Exit": ("Beenden", "Alt+F4", "application-exit", "files"),
    # Markieren
    "cm_SelectGroup": ("Gruppe markieren…", "", "", "mark"),
    "cm_UnselectGroup": ("Gruppe demarkieren…", "", "", "mark"),
    "cm_SelectAll": ("Alle markieren (wie eingestellt)", "Ctrl+A", "edit-select-all", "mark"),
    "cm_SelectAllFiles": ("Alle Dateien markieren", "", "", "mark"),
    "cm_SelectAllFolders": ("Alle Verzeichnisse markieren", "", "", "mark"),
    "cm_SelectAllBoth": ("Alle Dateien und Verzeichnisse markieren", "", "", "mark"),
    "cm_ClearAll": ("Alle demarkieren", "Ctrl+Shift+D", "", "mark"),
    "cm_UnselectAllFiles": ("Alle Dateien demarkieren", "", "", "mark"),
    "cm_UnselectAllFolders": ("Alle Verzeichnisse demarkieren", "", "", "mark"),
    "cm_InvertSelection": ("Markierung umkehren (wie eingestellt)", "", "edit-select-invert", "mark"),
    "cm_ExchangeSelFiles": ("Markierung umkehren (nur Dateien)", "", "", "mark"),
    "cm_ExchangeSelBoth": ("Markierung umkehren (Dateien und Verzeichnisse)", "", "", "mark"),
    "cm_SelectCurrentExtension": ("Gleiche Erweiterung markieren", "", "", "mark"),
    "cm_SaveSelection": ("Markierung speichern", "", "", "mark"),
    "cm_RestoreSelection": ("Markierung wiederherstellen", "", "", "mark"),
    "cm_CopyNamesToClip": ("Dateinamen in Zwischenablage", "", "", "mark"),
    "cm_CopyFullNamesToClip": ("Namen mit Pfad in Zwischenablage", "Ctrl+Shift+C", "", "mark"),
    "cm_CompareDirs": ("Verzeichnisse vergleichen", "Shift+F2", "view-split-left-right", "mark"),
    # Befehle
    "cm_SearchFor": ("Dateien suchen…", "Alt+F7", "edit-find", "commands"),
    "cm_SyncDirs": ("Verzeichnisse synchronisieren…", "", "folder-sync", "commands"),
    "cm_DirHotlist": ("Verzeichnis-Hotlist", "Ctrl+D", "bookmarks", "commands"),
    "cm_SwapPanels": ("Fenster tauschen", "Ctrl+U", "", "commands"),
    "cm_TargetEqualSource": ("Ziel = Quelle", "Ctrl+Shift+E", "", "commands"),
    "cm_TransferLeft": ("Verzeichnis unter Cursor links öffnen", "Ctrl+Left", "", "commands"),
    "cm_TransferRight": ("Verzeichnis unter Cursor rechts öffnen", "Ctrl+Right", "", "commands"),
    "cm_OpenTerminal": ("Terminal hier öffnen", "Ctrl+Shift+T", "utilities-terminal", "commands"),
    "cm_CopyToClipboard": ("Kopieren (Zwischenablage)", "Ctrl+C", "edit-copy", "commands"),
    "cm_CutToClipboard": ("Ausschneiden (Zwischenablage)", "Ctrl+X", "edit-cut", "commands"),
    "cm_PasteFromClipboard": ("Einfügen (Zwischenablage)", "Ctrl+V", "edit-paste", "commands"),
    "cm_QuickFilter": ("Schnellsuche mit Filter", "Ctrl+S", "view-filter", "commands"),
    "cm_QuickSearch": ("Schnellsuche", "", "edit-find", "commands"),
    "cm_LeftOpenDrives": ("Laufwerksliste links", "Alt+F1", "", "commands"),
    "cm_RightOpenDrives": ("Laufwerksliste rechts", "Alt+F2", "", "commands"),
    "cm_CmdLineHistory": ("Kommandozeilen-Verlauf", "Alt+F8", "", "commands"),
    "cm_AddPathToCmdline": ("Pfad in Kommandozeile", "Ctrl+P", "", "commands"),
    "cm_AddFilenameToCmdline": ("Dateiname in Kommandozeile", "Ctrl+Return", "", "commands"),
    "cm_AddPathAndNameToCmdline": ("Pfad+Name in Kommandozeile", "Ctrl+Shift+Return", "", "commands"),
    "cm_ConnectNetwork": ("Netzwerkverbindung (SFTP/FTP/SMB/WebDAV)…", "Ctrl+F", "network-server", "net"),
    "cm_DisconnectNetwork": ("Netzwerkverbindung trennen…", "Ctrl+Shift+F", "network-offline", "net"),
    # Ansicht
    "cm_BriefView": ("Kurz", "Ctrl+F1", "view-list-details", "view"),
    "cm_FullView": ("Voll", "Ctrl+F2", "view-list-text", "view"),
    "cm_ThumbnailsView": ("Miniaturansicht", "Ctrl+Shift+F1", "view-list-icons", "view"),
    "cm_TreeView": ("Verzeichnisbaum", "Ctrl+F8", "view-list-tree", "view"),
    "cm_QuickView": ("Schnellansicht", "Ctrl+Q", "view-preview", "view"),
    "cm_SortByName": ("Nach Name sortieren", "Ctrl+F3", "", "view"),
    "cm_SortByExt": ("Nach Erweiterung sortieren", "Ctrl+F4", "", "view"),
    "cm_SortByDate": ("Nach Datum sortieren", "Ctrl+F5", "", "view"),
    "cm_SortBySize": ("Nach Größe sortieren", "Ctrl+F6", "", "view"),
    "cm_SortByAttr": ("Nach Attributen sortieren", "Ctrl+F7", "", "view"),
    "cm_ReverseOrder": ("Umgekehrte Sortierung", "", "view-sort-descending", "view"),
    "cm_AllFiles": ("Alle Dateien", "Ctrl+F10", "", "view"),
    "cm_ExecutablesOnly": ("Nur Programme", "Ctrl+F11", "", "view"),
    "cm_UserFilter": ("Benutzerdefiniert (Filter)…", "Ctrl+F12", "", "view"),
    "cm_RereadSource": ("Neu einlesen", "Ctrl+R", "view-refresh", "view"),
    "cm_RereadF2": ("Neu einlesen (F2)", "F2", "", None),
    "cm_ConfigShowHidden": ("Versteckte Dateien anzeigen", "Ctrl+H", "view-hidden", "view"),
    "cm_OpenNewTab": ("Neuer Tab", "Ctrl+T", "tab-new", "view"),
    "cm_OpenDirInNewTab": ("Verzeichnis in neuem Tab", "Ctrl+Up", "", "view"),
    "cm_OpenDirInNewTabOther": ("Verzeichnis in neuem Tab (anderes Fenster)", "Ctrl+Shift+Up", "", "view"),
    "cm_CloseCurrentTab": ("Tab schließen", "Ctrl+W", "tab-close", "view"),
    "cm_CloseAllTabs": ("Alle anderen Tabs schließen", "Ctrl+Shift+W", "", "view"),
    "cm_LockTab": ("Tab sperren / entsperren", "Ctrl+Shift+L", "object-locked", "view"),
    "cm_LockTabNav": ("Tab sperren, Verzeichniswechsel erlaubt", "", "", "view"),
    "cm_NextTab": ("Nächster Tab", "Ctrl+Tab", "", "view"),
    "cm_PrevTab": ("Vorheriger Tab", "Ctrl+Shift+Tab", "", "view"),
    # Konfiguration
    "cm_Config": ("Einstellungen…", "", "preferences-system", "config"),
    "cm_ConfigHotlist": ("Hotlist konfigurieren…", "", "", "config"),
    "cm_SaveSettings": ("Einstellungen speichern", "", "document-save", "config"),
    # Hilfe
    "cm_Keyboard": ("Tastaturbelegung", "F1", "help-contents", "help"),
    "cm_CheckUpdates": ("Nach Updates suchen", "", "system-software-update", "help"),
    "cm_About": ("Über PixelCommander", "", "help-about", "help"),
    "cm_SwitchPanel": ("Fenster wechseln (Tab)", "", "", None),
    "cm_FocusCmdLine": ("Kommandozeile fokussieren", "", "", None),
}

MENUS = [("files", "&Dateien"), ("mark", "&Markieren"), ("commands", "&Befehle"), ("net", "&Netz"),
         ("view", "&Ansicht"), ("config", "&Konfiguration"), ("help", "&Hilfe")]

SEPARATORS_AFTER = {"cm_Edit", "cm_RenameOnly", "cm_DeletePermanent", "cm_OpenWith", "cm_TestArchive",
                    "cm_MultiRenameFiles", "cm_CombineFiles", "cm_CalcSpace", "cm_UnselectGroup",
                    "cm_SelectCurrentExtension", "cm_RestoreSelection", "cm_SelectAllBoth", "cm_UnselectAllFolders",
                    "cm_ExchangeSelBoth", "cm_CopyFullNamesToClip",
                    "cm_DirHotlist", "cm_TransferRight", "cm_OpenTerminal", "cm_PasteFromClipboard",
                    "cm_RightOpenDrives", "cm_QuickView", "cm_ReverseOrder", "cm_UserFilter",
                    "cm_ConfigShowHidden", "cm_TreeView"}

BUTTON_ABBR = {"cm_RereadSource": "↻", "cm_BriefView": "≡", "cm_FullView": "☰", "cm_ThumbnailsView": "▦",
               "cm_TreeView": "🌲", "cm_SelectAll": "✓*", "cm_InvertSelection": "±", "cm_PackFiles": "ZIP",
               "cm_UnpackFiles": "UNZ", "cm_SearchFor": "🔍", "cm_MultiRenameFiles": "MR", "cm_CompareDirs": "⇄",
               "cm_SyncDirs": "⟳", "cm_CompareFilesByContent": "≠", "cm_OpenTerminal": ">_",
               "cm_ConfigShowHidden": ".*", "cm_Config": "⚙", "cm_Copy": "F5", "cm_RenMov": "F6",
               "cm_QuickView": "QV", "cm_DirHotlist": "★", "cm_SwapPanels": "↔"}

FKEYS = [("F3", "Ansehen", "cm_View"), ("F4", "Bearbeiten", "cm_Edit"), ("F5", "Kopieren", "cm_Copy"),
         ("F6", "Verschieben", "cm_RenMov"), ("F7", "Neuer Ordner", "cm_MkDir"), ("F8", "Löschen", "cm_Delete"),
         ("Alt+F4", "Beenden", "cm_Exit")]


class CmdLine(QtWidgets.QComboBox):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.addItems(config.get("cmd_history", []))
        self.setCurrentIndex(-1)
        self.lineEdit().installEventFilter(self)
        self.installEventFilter(self)  # editable combo: keys may arrive at the combo itself
        comp = QtWidgets.QCompleter(self)
        fsm = QtGui.QFileSystemModel(comp) if hasattr(QtGui, "QFileSystemModel") else QtWidgets.QFileSystemModel(comp)
        fsm.setRootPath("/")
        comp.setModel(fsm)
        self.lineEdit().setCompleter(None)

    def text(self):
        return self.currentText()

    def setText(self, t):
        self.setEditText(t)

    def clear(self):
        self.setEditText("")

    def insert(self, t):
        self.lineEdit().insert(t)

    def backspace(self):
        self.lineEdit().backspace()

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Type.KeyPress and (obj is self or obj is self.lineEdit()) \
                and not self.view().isVisible():
            k = ev.key()
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if ev.modifiers() & CTRL:
                    return False
                self.main.run_cmdline(bool(ev.modifiers() & SHIFT))
                return True
            if k == Qt.Key.Key_Escape:
                self.clear()
                self.main.active_panel().activate(focus=True)
                return True
            if k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and not self.text():
                self.main.active_panel().activate(focus=True)
                QtWidgets.QApplication.sendEvent(self.main.active_panel().view, ev)
                return True
            if k == Qt.Key.Key_Tab:
                self.main.active_panel().activate(focus=True)
                return True
        return super().eventFilter(obj, ev)


class PixelCommander(QtWidgets.QMainWindow):
    def __init__(self, start_left=None, start_right=None):
        super().__init__()
        self.setWindowTitle("PixelCommander %s" % __version__)
        self.setWindowIcon(theme_icon("pixelcommander", QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        self.actions = {}
        self.saved_selection = []
        self.search_dialogs = []
        self.quickview_on = False
        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._build_buttonbar()
        self.apply_settings()
        geo = config.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QtCore.QByteArray.fromHex(geo.encode()))
            except Exception:  # noqa: BLE001
                self.resize(1200, 760)
        else:
            self.resize(1200, 760)
        if not start_left and config.get("start_left"):
            start_left = os.path.expanduser(config["start_left"])
        if not start_right and config.get("start_right"):
            start_right = os.path.expanduser(config["start_right"])
        if start_left:
            self.left.current().set_location(start_left)
        if start_right:
            self.right.current().set_location(start_right)
        self.active_side = config.get("active_panel", "left")
        self.set_active(self.left if self.active_side == "left" else self.right)
        QtCore.QTimer.singleShot(0, lambda: self.active_panel().activate(focus=True))
        self.mount_timer = QtCore.QTimer(self)
        self.mount_timer.timeout.connect(self._check_mounts)
        self.mount_timer.start(3000)
        self._mounts_sig = self._mount_signature()

    # ------------------------------------------------------------ construction
    def _build_actions(self):
        user = config.get("user_hotkeys", {})
        for name, (label, key, icon, _menu) in COMMANDS.items():
            a = QAction(label, self)
            if builtin_icon(name) is not None:
                a.setIcon(builtin_icon(name))
            elif icon:
                a.setIcon(QtGui.QIcon.fromTheme(icon))
            key = user.get(name, key)
            if key:
                a.setShortcut(QtGui.QKeySequence(key))
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            fn = getattr(self, name.replace("cm_", "cmd_"), None)
            if fn is None:
                continue
            a.triggered.connect(lambda _c=False, f=fn: self._run(f))
            self.addAction(a)
            self.actions[name] = a
        self.actions["cm_ConfigShowHidden"].setCheckable(True)
        self.actions["cm_ConfigShowHidden"].setChecked(bool(config.get("show_hidden")))
        self.actions["cm_QuickView"].setCheckable(True)

    def _run(self, fn):
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Fehler", str(ex))

    def _build_ui(self):
        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        self.left = TabbedPanel(self, "left")
        self.right = TabbedPanel(self, "right")
        self.left.activated.connect(self.set_active)
        self.right.activated.connect(self.set_active)
        self.left_stack = QtWidgets.QStackedWidget()
        self.right_stack = QtWidgets.QStackedWidget()
        self.left_qv = ListerWidget(compact=True)
        self.right_qv = ListerWidget(compact=True)
        self.left_stack.addWidget(self.left)
        self.left_stack.addWidget(self.left_qv)
        self.right_stack.addWidget(self.right)
        self.right_stack.addWidget(self.right_qv)
        self.splitter.addWidget(self.left_stack)
        self.splitter.addWidget(self.right_stack)
        self.splitter.setChildrenCollapsible(False)
        sp = config.get("splitter")
        if sp:
            try:
                self.splitter.restoreState(QtCore.QByteArray.fromHex(sp.encode()))
            except Exception:  # noqa: BLE001
                pass
        self.splitter.splitterMoved.connect(lambda *_: None)
        self.splitter.handle(1).installEventFilter(self)
        self._alt_alone = False
        QtWidgets.QApplication.instance().installEventFilter(self)  # Alt alone -> quick search box
        lay.addWidget(self.splitter, 1)

        cl = QtWidgets.QHBoxLayout()
        cl.setContentsMargins(0, 0, 0, 0)
        self.cmd_label = QtWidgets.QLabel()
        self.cmd_label.setTextFormat(Qt.TextFormat.PlainText)
        self.cmdline = CmdLine(self)
        cl.addWidget(self.cmd_label)
        cl.addWidget(self.cmdline, 1)
        self.cmd_widget = QtWidgets.QWidget()
        self.cmd_widget.setLayout(cl)
        lay.addWidget(self.cmd_widget)

        fk = QtWidgets.QHBoxLayout()
        fk.setContentsMargins(0, 0, 0, 0)
        fk.setSpacing(2)
        for key, label, cmd in FKEYS:
            b = QtWidgets.QPushButton("%s %s" % (key, label))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFlat(False)
            b.clicked.connect(lambda _c=False, c=cmd: self.actions[c].trigger())
            fk.addWidget(b)
        self.fkey_widget = QtWidgets.QWidget()
        self.fkey_widget.setLayout(fk)
        lay.addWidget(self.fkey_widget)
        self.setCentralWidget(central)

        for tp in (self.left, self.right):
            for p in tp.panels():
                self._hook_panel(p)
            tp.tabs.currentChanged.connect(lambda _i, t=tp: [self._hook_panel(p) for p in t.panels()])

    def _hook_panel(self, p):
        if getattr(p, "_hooked", False):
            return
        p._hooked = True
        for v in (p.full, p.brief, p.thumbs):
            v.selectionModel().currentChanged.connect(lambda *_a, pp=p: self.on_cursor_changed(pp))

    def _alt_search_panel(self):
        """Active panel if its file list or its quick search box has the focus and quick search is set to Alt."""
        from .panel import qs_mode
        if qs_mode() != "alt" or not self.isActiveWindow() or QtWidgets.QApplication.activePopupWidget():
            return None
        p = self.active_panel()
        fw = QtWidgets.QApplication.focusWidget()
        if fw is None or self.cmdline.text():
            return None
        return p if fw is p.view or fw is p.quick.edit else None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.ShortcutOverride) and not ev.isAutoRepeat():
            other = ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier |
                                      Qt.KeyboardModifier.MetaModifier)
            if ev.key() == Qt.Key.Key_Alt and not other and self._alt_search_panel() is not None:
                # the menu bar arms its Alt handling on ShortcutOverride already: swallow both
                self._alt_alone = True
                ev.accept()
                return True
            if ev.key() != Qt.Key.Key_Alt and t == QtCore.QEvent.Type.KeyPress:
                self._alt_alone = False
        elif t == QtCore.QEvent.Type.KeyRelease and ev.key() == Qt.Key.Key_Alt and not ev.isAutoRepeat():
            if self._alt_alone:
                self._alt_alone = False
                p = self._alt_search_panel()
                if p is not None:
                    if p.quick.isVisible():
                        # TC-like toggle: Alt again closes the box (keeps a filter only if one is active)
                        p.quick.close_search(clear_filter=False)
                    else:
                        p.quick.open("")
                return True
        elif t in (QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.WindowDeactivate):
            self._alt_alone = False
        if t == QtCore.QEvent.Type.MouseButtonDblClick and obj is self.splitter.handle(1):
            # double click on splitter handle: 50/50
            w = self.splitter.width()
            self.splitter.setSizes([w // 2, w // 2])
            return True
        return super().eventFilter(obj, ev)

    def _build_menus(self):
        mb = self.menuBar()
        menus = {}
        for key, title in MENUS:
            menus[key] = mb.addMenu(title)
        for name, (label, key, icon, menu) in COMMANDS.items():
            if menu and name in self.actions:
                menus[menu].addAction(self.actions[name])
                if name in SEPARATORS_AFTER:
                    menus[menu].addSeparator()
        # view menu toggles
        vm = menus["config"]
        vm.addSeparator()
        for key, label in [("show_buttonbar", "Buttonleiste"), ("show_drivebar", "Laufwerksleisten"),
                           ("show_cmdline", "Kommandozeile"), ("show_fkeys", "Funktionstastenleiste"),
                           ("check_updates", "Beim Start nach Updates suchen")]:
            a = vm.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(config.get(key)))
            a.toggled.connect(lambda c, k=key: (config.__setitem__(k, c), self.apply_settings()))
        from .updater import UpdateButton
        self.update_button = UpdateButton(self)
        mb.setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)
        if config.get("check_updates", True):
            QtCore.QTimer.singleShot(3000, self.update_button.check)
        self.hotlist_menu = None

    def _build_buttonbar(self):
        if hasattr(self, "toolbar"):
            self.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
        tb = ButtonBar(self)
        tb.setObjectName("buttonbar")
        tb.setIconSize(QtCore.QSize(22, 22))
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for b in config.get("buttons", []):
            cmd, icon, tip = (list(b) + ["", "", ""])[:3]
            if cmd == "-":
                tb.register(tb.addSeparator(), cmd, None)
                continue
            if cmd in self.actions:
                a = self.actions[cmd]
                custom = load_icon(icon) if icon and icon != COMMANDS.get(cmd, ("", "", ""))[2] else None
                if custom is not None and not custom.isNull():
                    a.setIcon(custom)
                elif builtin_icon(cmd) is not None:
                    a.setIcon(builtin_icon(cmd))
                elif icon and not load_icon(icon).isNull():
                    a.setIcon(load_icon(icon))
                if a.icon().isNull() or not (a.icon().availableSizes() or builtin_icon(cmd)):
                    a.setIcon(text_icon(BUTTON_ABBR.get(cmd, cmd[3:5])))
                tb.addAction(a)
                tb.register(a, cmd, a)
            else:
                ic = load_icon(icon or "system-run")
                if ic.isNull() or not ic.availableSizes():
                    ic = text_icon(os.path.basename(cmd.split()[0])[:2].upper())
                a = tb.addAction(ic, tip or cmd)
                a.triggered.connect(lambda _c=False, c=cmd: self.run_external_button(c))
                tb.register(a, cmd, a)
            a.setToolTip("%s%s" % (tip or a.text(), (" (%s)" % a.shortcut().toString()) if a.shortcut().toString()
                                   else ""))
        self.addToolBar(tb)
        self.toolbar = tb

    def apply_settings(self):
        if hasattr(self, "toolbar"):
            self.toolbar.setVisible(bool(config.get("show_buttonbar", True)))
        self.cmd_widget.setVisible(bool(config.get("show_cmdline", True)))
        self.fkey_widget.setVisible(bool(config.get("show_fkeys", True)))
        font = None
        if config.get("font_family"):
            font = QtGui.QFont(config["font_family"])
            if config.get("font_size"):
                font.setPointSize(int(config["font_size"]))
        from .utils import apply_theme
        apply_theme(config.get("theme", "system"))
        for tp in (self.left, self.right):
            tp.drivebuttons.setVisible(bool(config.get("show_drivebuttons", True)))
            tp.drivebar.setVisible(bool(config.get("show_drivebar", True)))
            tp.tabs.tabBar().setAutoHide(not config.get("show_tabs_always"))
            for p in tp.panels():
                if font:
                    for v in (p.full, p.brief, p.thumbs, p.tree):
                        v.setFont(font)
                p.apply_view_settings()
        self.on_panel_changed(self.active_panel()) if hasattr(self, "active_side") else None

    # ------------------------------------------------------------ panel access
    def active_tabbed(self):
        return self.left if self.active_side == "left" else self.right

    def active_panel(self):
        return self.active_tabbed().current()

    def other_tabbed(self, tp=None):
        tp = tp or self.active_tabbed()
        return self.right if tp is self.left else self.left

    def other_panel(self, panel=None):
        if panel is None:
            return self.other_tabbed().current()
        return (self.right if panel.side == "left" else self.left).current()

    def set_active(self, tp):
        self.active_side = tp.side
        for t in (self.left, self.right):
            for p in t.panels():
                p.set_active_look(t is tp and p is t.current())
        self.update_cmd_label()
        if self.quickview_on:
            self._update_quickview()

    def on_panel_changed(self, p):
        if p.side == getattr(self, "active_side", None):
            self.update_cmd_label()
        for t in (getattr(self, "left", None), getattr(self, "right", None)):
            if t is None:
                continue
            for x in t.panels():
                x.set_active_look(t.side == getattr(self, "active_side", "left") and x is t.current())

    def on_cursor_changed(self, p):
        if self.quickview_on and p is self.active_panel():
            self._update_quickview()

    def update_cmd_label(self):
        p = self.active_panel()
        if p is None:
            return
        d = p.local_dir() or p.location_text()
        home = os.path.expanduser("~")
        if d.startswith(home):
            d = "~" + d[len(home):]
        if len(d) > 50:
            d = "…" + d[-49:]
        self.cmd_label.setText(d + " $")

    # ------------------------------------------------------------ helpers
    def _need_local(self, p, what="Diese Funktion"):
        if p.fs.kind == "ftp":
            QtWidgets.QMessageBox.information(self, "PixelCommander",
                                              "%s ist auf FTP-Servern nicht möglich." % what)
            return False
        if p.fs.kind == "archive":
            QtWidgets.QMessageBox.information(self, "PixelCommander",
                                              "%s ist in Archiven nicht möglich." % what)
            return False
        return True

    def _refresh_all(self):
        for tp in (self.left, self.right):
            tp.drivebar.update_for(tp.current())
            for p in tp.panels():
                if p.isVisible():
                    p.refresh()

    def _what(self, entries):
        if len(entries) == 1:
            e = entries[0]
            return "„%s“" % e.name
        nd = sum(1 for e in entries if e.is_dir)
        nf = len(entries) - nd
        parts = []
        if nf:
            parts.append("%d Datei(en)" % nf)
        if nd:
            parts.append("%d Verzeichnis(se)" % nd)
        return " und ".join(parts)

    def _mount_signature(self):
        try:
            with open("/proc/mounts") as fh:
                return hash(fh.read())
        except OSError:
            return None

    def _check_mounts(self):
        sig = self._mount_signature()
        if sig != self._mounts_sig:
            self._mounts_sig = sig
            for tp in (self.left, self.right):
                tp.drivebar.reload()
                tp.drivebar.update_for(tp.current())

    # ------------------------------------------------------------ open / view / edit
    def open_file(self, panel, path):
        if vfs.is_archive_name(path) and vfs.archive_backend(path):
            if panel.set_location(path):
                return
        if is_image(path) and config.get("internal_image_viewer", True):
            self.view_image(path, [x.path for x in panel.model.entries if not x.is_dir and x.path])
            return
        if is_executable_file(path):
            if QtWidgets.QMessageBox.question(self, "Ausführen", "Programm ausführen?\n%s" % path) == \
                    QtWidgets.QMessageBox.StandardButton.Yes:
                subprocess.Popen([path], cwd=os.path.dirname(path), start_new_session=True)
            return
        open_default(path)

    def open_archive_member(self, panel, entry):
        try:
            tmp = panel.fs.extract_temp(entry.path)
        except Exception as ex:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Archiv", str(ex))
            return
        open_default(tmp)

    def view_file(self, path, siblings=None):
        ext_viewer = config.get("viewer")
        if ext_viewer:
            run_command_template(ext_viewer, path)
            return
        if is_image(path) and config.get("internal_image_viewer", True):
            self.view_image(path, siblings)
            return
        w = Lister(path, siblings or [path])
        w.show()

    def view_image(self, path, siblings=None):
        ImageViewer(path, siblings or [path]).show()

    def cmd_ImageView(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_up or e.is_dir or not e.path:
            return
        path = e.path
        if p.fs.kind in ("archive", "ftp"):
            try:
                path = p.fs.extract_temp(e.path)
            except Exception as ex:  # noqa: BLE001
                QtWidgets.QMessageBox.warning(self, "Archiv", str(ex))
                return
            self.view_image(path)
            return
        self.view_image(path, [x.path for x in p.model.entries if not x.is_dir and x.path])

    def cmd_View(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_up:
            return
        if p.fs.kind in ("archive", "ftp"):
            if e.is_dir:
                if p.fs.kind == "ftp":
                    p.calc_dir_sizes([e])
                return
            try:
                tmp = p.fs.extract_temp(e.path)
            except Exception as ex:  # noqa: BLE001
                QtWidgets.QMessageBox.warning(self, "Archiv", str(ex))
                return
            self.view_file(tmp)
            return
        if e.is_dir:
            p.calc_dir_sizes([e])
            return
        files = [x.path for x in p.model.entries if not x.is_dir and x.path]
        self.view_file(e.path, files)

    def cmd_ViewExternal(self):
        p = self.active_panel()
        e = p.current_entry()
        if e and not e.is_up and e.path and p.fs.is_local:
            open_default(e.path)

    def cmd_Edit(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_up or e.is_dir:
            return
        path = e.path
        if p.fs.kind == "archive":
            try:
                path = p.fs.extract_temp(e.path)
            except Exception as ex:  # noqa: BLE001
                QtWidgets.QMessageBox.warning(self, "Archiv", str(ex))
                return
            QtWidgets.QMessageBox.information(self, "Archiv", "Die Datei wurde in einen temporären Ordner entpackt.\n"
                                              "Änderungen werden nicht ins Archiv zurückgeschrieben:\n" + path)
        self.open_editor(path)

    def open_editor(self, path):
        if config.get("use_internal_editor", True) or not config.get("editor"):
            from .editor import Editor
            ed = Editor(path)
            ed.show()
            ed.activateWindow()
            return ed
        run_command_template(config["editor"], path, os.path.dirname(path))
        return None

    def cmd_EditNewFile(self):
        p = self.active_panel()
        d = p.local_dir()
        if not d:
            return
        e = p.current_entry()
        name, ok = QtWidgets.QInputDialog.getText(self, "Neue Datei bearbeiten", "Dateiname:",
                                                  text=e.name if e and not e.is_up and not e.is_dir else "neu.txt")
        if not ok or not name:
            return
        path = os.path.join(d, name)
        if not os.path.exists(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "a").close()
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Fehler", str(ex))
                return
        p.refresh()
        p.select_name(os.path.relpath(path, d).split("/")[0])
        self.open_editor(path)

    def cmd_OpenWith(self):
        p = self.active_panel()
        paths = [e.path for e in p.selected_entries() if e.path and p.fs.is_local]
        if not paths:
            return
        apps = self._apps_for(paths[0])
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Öffnen mit")
        lay = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget()
        for name, exe, icon in apps:
            it = QtWidgets.QListWidgetItem(QtGui.QIcon.fromTheme(icon or "application-x-executable"), name)
            it.setData(Qt.ItemDataRole.UserRole, exe)
            lst.addItem(it)
        lay.addWidget(lst)
        ed = QtWidgets.QLineEdit()
        ed.setPlaceholderText("oder eigenes Kommando (z.B. gimp)")
        lay.addWidget(ed)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        lay.addWidget(bb)
        dlg.resize(420, 480)
        if not qexec(dlg):
            return
        cmd = ed.text().strip() or (lst.currentItem().data(Qt.ItemDataRole.UserRole) if lst.currentItem() else "")
        if not cmd:
            return
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
        parts = [x for x in parts if not (x.startswith("%") and len(x) == 2)]
        subprocess.Popen(parts + paths, cwd=os.path.dirname(paths[0]), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _apps_for(self, path):
        mime = QtCore.QMimeDatabase().mimeTypeForFile(path).name()
        dirs = [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications",
                "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications",
                os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
        res, other = [], []
        seen = set()
        for d in dirs:
            try:
                files = sorted(os.listdir(d))
            except OSError:
                continue
            for f in files:
                if not f.endswith(".desktop") or f in seen:
                    continue
                seen.add(f)
                info = {}
                try:
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        sect = None
                        for line in fh:
                            line = line.strip()
                            if line.startswith("["):
                                sect = line
                                continue
                            if sect == "[Desktop Entry]" and "=" in line:
                                k, v = line.split("=", 1)
                                info.setdefault(k, v)
                except OSError:
                    continue
                if info.get("NoDisplay") == "true" or info.get("Type") != "Application" or "Exec" not in info:
                    continue
                name = info.get("Name[de]") or info.get("Name") or f
                item = (name, info["Exec"], info.get("Icon", ""))
                if mime in info.get("MimeType", "").split(";"):
                    res.append(item)
                else:
                    other.append(item)
        return res + sorted(other)

    # ------------------------------------------------------------ copy / move / delete
    def _start_op(self, op, title, panels_refresh=True, **kw):
        def fin(ok, msg):
            self._refresh_all()
        fileops.start(op, title, self, fin, **kw)

    def cmd_Copy(self, same_panel=False, move=False):
        src = self.active_panel()
        entries = src.selected_entries()
        if not entries:
            return
        dst_panel = src if same_panel else self.other_panel()
        if move and not (self._need_local(src, "Verschieben") and self._need_local(dst_panel, "Verschieben")):
            return
        if dst_panel.fs.kind == "ftp" and src.fs.kind != "ftp":
            self._ftp_upload(src, entries, dst_panel)
            return
        if dst_panel.fs.kind == "ftp" and same_panel:
            QtWidgets.QMessageBox.information(self, "Kopieren", "Kopieren innerhalb des FTP-Servers ist nicht möglich.")
            return
        if dst_panel.fs.kind == "archive" or (dst_panel.fs.kind == "results" and not same_panel):
            if dst_panel.fs.kind == "archive":
                QtWidgets.QMessageBox.information(self, "Kopieren", "Das Ziel ist ein Archiv. Bitte zum Hinzufügen "
                                                  "„Packen“ (Alt+F5) verwenden.")
                return
        dest_dir = dst_panel.local_dir() or (src.local_dir() or os.path.expanduser("~"))
        if same_panel or (len(entries) == 1 and move and dst_panel is src):
            default = os.path.join(dest_dir, entries[0].name) if len(entries) == 1 else dest_dir + "/"
        else:
            default = dest_dir.rstrip("/") + "/" + ("*.*" if len(entries) > 1 or entries[0].is_dir else entries[0].name)
            if len(entries) > 1 or entries[0].is_dir:
                default = dest_dir.rstrip("/") + "/"
        from .dialogs import CopyDialog
        dlg = CopyDialog("Verschieben/Umbenennen" if move else "Kopieren", self._what(entries), default, self, move)
        if not qexec(dlg):
            return
        target, mask, _ask = dlg.values()
        if not target:
            return
        target = os.path.expanduser(target)
        if not target.startswith("/"):
            target = os.path.join(src.local_dir() or dest_dir, target)
        new_name = None
        base = os.path.basename(target)
        if target.endswith("/") or base in ("*.*", "*") or os.path.isdir(target):
            dest = target.rstrip("/") if base not in ("*.*", "*") else os.path.dirname(target)
            dest = dest or "/"
        elif len(entries) == 1:
            dest, new_name = os.path.split(target)
        else:
            dest = target
        if src.fs.kind == "archive":
            self._start_op("extract", "Entpacken", archive=src.fs.archive, inner_paths=[e.path for e in entries],
                           base_inner=src.inner, dest_dir=dest)
            return
        if src.fs.kind == "ftp":
            src.model.clear_marks()
            self._start_op("ftp_download", "Herunterladen", fs=src.fs,
                           items=[(e.path, e.is_dir and not e.is_link) for e in entries], dest_dir=dest,
                           new_name=new_name)
            return
        sources = [e.path for e in entries]
        if new_name and len(sources) == 1 and os.path.dirname(sources[0]) == dest and move:
            # plain rename
            try:
                if os.path.lexists(os.path.join(dest, new_name)) and QtWidgets.QMessageBox.question(
                        self, "Umbenennen", "%s existiert. Überschreiben?" % new_name) != \
                        QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                os.rename(sources[0], os.path.join(dest, new_name))
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Umbenennen", str(ex))
            src.refresh()
            src.select_name(new_name)
            return
        if new_name and not move and os.path.dirname(sources[0]) == dest and new_name == os.path.basename(sources[0]):
            QtWidgets.QMessageBox.warning(self, "Kopieren", "Eine Datei kann nicht auf sich selbst kopiert werden.")
            return
        src.model.clear_marks()
        self._start_op("copy", "Verschieben" if move else "Kopieren", sources=sources, dest_dir=dest,
                       new_name=new_name, mask=mask, move=move)

    def _ftp_upload(self, src, entries, dst_panel):
        if not src.fs.is_local:
            QtWidgets.QMessageBox.information(self, "Hochladen", "Nur lokale Dateien können hochgeladen werden.")
            return
        if QtWidgets.QMessageBox.question(self, "Hochladen", "%s hochladen nach\n%s ?" % (
                self._what(entries), dst_panel.location_text())) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        src.model.clear_marks()
        self._start_op("ftp_upload", "Hochladen", fs=dst_panel.fs, sources=[e.path for e in entries],
                       dest_inner=dst_panel.inner)

    def cmd_CopySamePanel(self):
        self.cmd_Copy(same_panel=True)

    def cmd_RenMov(self):
        self.cmd_Copy(move=True)

    def cmd_RenameOnly(self):
        self.active_panel().rename_inplace()

    def cmd_MkDir(self):
        p = self.active_panel()
        d = p.local_dir()
        if p.fs.kind == "ftp":
            name, ok = QtWidgets.QInputDialog.getText(self, "Neues Verzeichnis", "Neues Verzeichnis auf dem Server:")
            name = name.strip().strip("/")
            if not ok or not name:
                return
            try:
                path = p.inner
                for part in name.split("/"):
                    path = p.fs.join(path, part)
                    p.fs.mkdir(path)
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Verzeichnis erstellen", str(ex))
                return
            p.refresh()
            p.select_name(name.split("/")[0])
            return
        if not d:
            self._need_local(p, "Verzeichnis erstellen")
            return
        e = p.current_entry()
        default = e.name if e and not e.is_up and e.is_dir else (split_ext(e.name)[0] if e and not e.is_up else "")
        dlg = QtWidgets.QInputDialog(self)
        dlg.setWindowTitle("Neues Verzeichnis")
        dlg.setLabelText("Neues Verzeichnis (auch mehrere Ebenen, z.B. a/b/c):")
        dlg.setTextValue(default)
        if not qexec(dlg):
            return
        name = dlg.textValue().strip()
        if not name:
            return
        path = os.path.join(d, os.path.expanduser(name))
        try:
            os.makedirs(path)
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Verzeichnis erstellen", str(ex))
            return
        p.refresh()
        rel = os.path.relpath(path, d)
        p.select_name(rel.split("/")[0])

    def _delete(self, permanent=False):
        p = self.active_panel()
        if p.fs.kind == "archive":
            QtWidgets.QMessageBox.information(self, "Löschen", "Löschen in Archiven wird nicht unterstützt.")
            return
        entries = p.selected_entries()
        if not entries:
            return
        if p.fs.kind == "ftp":
            if QtWidgets.QMessageBox.question(self, "Löschen", "%s auf dem Server ENDGÜLTIG löschen?" %
                                              self._what(entries)) != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            row = p.current_row()
            p.model.clear_marks()

            def fin_ftp(ok, msg):
                self._refresh_all()
                p.select_row(row)
            fileops.start("ftp_delete", "Löschen", self, fin_ftp, fs=p.fs,
                          items=[(e.path, e.is_dir and not e.is_link) for e in entries])
            return
        trash = config.get("use_trash", True) and not permanent
        if config.get("confirm_delete", True) or permanent:
            msg = "%s %s?" % (self._what(entries), "in den Papierkorb verschieben" if trash else "ENDGÜLTIG löschen")
            nonempty = [e for e in entries if e.is_dir and not e.is_link and _dir_nonempty(e.path)]
            if nonempty and not trash:
                msg += "\n\nAchtung: %d Verzeichnis(se) sind nicht leer!" % len(nonempty)
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question if trash else
                                        QtWidgets.QMessageBox.Icon.Warning, "Löschen", msg,
                                        QtWidgets.QMessageBox.StandardButton.Yes |
                                        QtWidgets.QMessageBox.StandardButton.No, self)
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Yes)
            if qexec(box) != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        row = p.current_row()
        p.model.clear_marks()

        def fin(ok, msg):
            self._refresh_all()
            p.select_row(row)
        fileops.start("delete", "Löschen", self, fin, sources=[e.path for e in entries], trash=trash)

    def cmd_Delete(self):
        self._delete(False)

    def cmd_DeleteDel(self):
        self._delete(False)

    def cmd_DeletePermanent(self):
        self._delete(True)

    def cmd_DeletePermanentF8(self):
        self._delete(True)

    def drop_files(self, panel, paths, target, action):
        if not paths:
            return
        dest = target or panel.local_dir()
        if not dest:
            QtWidgets.QMessageBox.information(self, "Ablegen", "Hier können keine Dateien abgelegt werden.")
            return
        paths = [x for x in paths if os.path.dirname(x.rstrip("/")) != dest.rstrip("/") or action == "link"]
        if not paths:
            return
        if action == "ask":
            menu = QtWidgets.QMenu(self)
            ca = menu.addAction(QtGui.QIcon.fromTheme("edit-copy"), "Hierher kopieren")
            ma = menu.addAction(QtGui.QIcon.fromTheme("go-jump"), "Hierher verschieben")
            la = menu.addAction(QtGui.QIcon.fromTheme("insert-link"), "Verknüpfung hier erstellen")
            menu.addSeparator()
            menu.addAction("Abbrechen")
            r = qexec(menu, QtGui.QCursor.pos())
            action = {ca: "copy", ma: "move", la: "link"}.get(r)
            if not action:
                return
        if action == "link":
            for x in paths:
                try:
                    os.symlink(x, os.path.join(dest, os.path.basename(x)))
                except OSError as ex:
                    QtWidgets.QMessageBox.warning(self, "Verknüpfung", str(ex))
            self._refresh_all()
            return
        if config.get("confirm_drop", True) and QtWidgets.QMessageBox.question(self, "Drag & Drop", "%d Objekt(e) nach %s %s?" % (
                len(paths), dest, "verschieben" if action == "move" else "kopieren")) != \
                QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._start_op("copy", "Verschieben" if action == "move" else "Kopieren", sources=paths, dest_dir=dest,
                       move=action == "move")

    # ------------------------------------------------------------ clipboard
    def _set_clip(self, cut):
        p = self.active_panel()
        paths = [e.path for e in p.selected_entries() if e.path and p.fs.is_local]
        if not paths:
            return
        md = QtCore.QMimeData()
        urls = [QtCore.QUrl.fromLocalFile(x) for x in paths]
        md.setUrls(urls)
        md.setText("\n".join(paths))
        gnome = ("cut" if cut else "copy") + "\n" + "\n".join(u.toString(QtCore.QUrl.ComponentFormattingOption.FullyEncoded)
                                                             for u in urls)
        md.setData("x-special/gnome-copied-files", gnome.encode())
        md.setData("application/x-kde-cutselection", b"1" if cut else b"0")
        QtWidgets.QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage("%d Objekt(e) %s" % (len(paths), "ausgeschnitten" if cut else "kopiert"), 3000)

    def cmd_CopyToClipboard(self):
        self._set_clip(False)

    def cmd_CutToClipboard(self):
        self._set_clip(True)

    def cmd_PasteFromClipboard(self):
        p = self.active_panel()
        dest = p.local_dir()
        if not dest:
            return
        md = QtWidgets.QApplication.clipboard().mimeData()
        if md is None:
            return
        cut = False
        if md.hasFormat("x-special/gnome-copied-files"):
            data = bytes(md.data("x-special/gnome-copied-files")).decode(errors="replace")
            cut = data.startswith("cut")
        elif md.hasFormat("application/x-kde-cutselection"):
            cut = bytes(md.data("application/x-kde-cutselection")).strip() == b"1"
        paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if not paths and md.hasText():
            paths = [x for x in md.text().splitlines() if x.startswith("/") and os.path.exists(x)]
        if not paths:
            return
        same = [x for x in paths if os.path.dirname(x.rstrip("/")) == dest.rstrip("/")]
        if same and not cut:
            # paste copy in same dir -> create "copy" names
            for x in same:
                from .utils import unique_name
                tgt = unique_name(x)
                try:
                    if os.path.isdir(x) and not os.path.islink(x):
                        shutil.copytree(x, tgt, symlinks=True)
                    else:
                        shutil.copy2(x, tgt, follow_symlinks=False)
                except OSError as ex:
                    QtWidgets.QMessageBox.warning(self, "Einfügen", str(ex))
            paths = [x for x in paths if x not in same]
            p.refresh()
            if not paths:
                return
        self._start_op("copy", "Verschieben" if cut else "Kopieren", sources=paths, dest_dir=dest, move=cut)
        if cut:
            QtWidgets.QApplication.clipboard().clear()

    def cmd_CopyNamesToClip(self):
        p = self.active_panel()
        QtWidgets.QApplication.clipboard().setText("\n".join(e.name for e in p.selected_entries()))

    def cmd_CopyFullNamesToClip(self):
        p = self.active_panel()
        QtWidgets.QApplication.clipboard().setText("\n".join(
            (e.path if p.fs.is_local else p.fs.display(e.path)) for e in p.selected_entries()))

    # ------------------------------------------------------------ selection
    def _ask_mask(self, title):
        """TC Num+/Num- dialog: mask with history + 'include directories'. Returns (mask, dirs) or None."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel("Maske, z.B. *.txt *.doc | *.bak   (Verzeichnisse: name/ )"))
        cb = QtWidgets.QComboBox()
        cb.setEditable(True)
        hist = config.get("select_history", []) or ["*.*"]
        cb.addItems(hist)
        cb.setCurrentIndex(0)
        cb.lineEdit().selectAll()
        cb.setMinimumWidth(360)
        lay.addWidget(cb)
        dirs = QtWidgets.QCheckBox("Auch Verzeichnisse")
        dirs.setChecked(bool(config.get("select_group_dirs", False)))
        lay.addWidget(dirs)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not qexec(dlg):
            return None
        t = cb.currentText().strip() or "*"
        config.push_history("select_history", t, 20)
        return t, dirs.isChecked()

    def cmd_SelectGroup(self):
        r = self._ask_mask("Gruppe markieren")
        if r:
            self.active_panel().mark_mask(r[0], True, r[1])

    def cmd_UnselectGroup(self):
        r = self._ask_mask("Gruppe demarkieren")
        if r:
            self.active_panel().mark_mask(r[0], False, r[1])

    def cmd_SelectAll(self):
        if config.get("select_all_dirs", True):
            self.cmd_SelectAllBoth()
        else:
            self.cmd_SelectAllFiles()

    def cmd_SelectAllFiles(self):
        self.active_panel().model.mark_where(lambda e: not e.is_dir)

    def cmd_SelectAllFolders(self):
        self.active_panel().model.mark_where(lambda e: e.is_dir)

    def cmd_SelectAllBoth(self):
        self.active_panel().model.mark_where(lambda e: True)

    def cmd_ClearAll(self):
        self.active_panel().model.clear_marks()

    def cmd_UnselectAllFiles(self):
        self.active_panel().model.mark_where(lambda e: not e.is_dir, False)

    def cmd_UnselectAllFolders(self):
        self.active_panel().model.mark_where(lambda e: e.is_dir, False)

    def cmd_InvertSelection(self):
        self.active_panel().model.invert_marks(files_only=not config.get("select_group_dirs", False))

    def cmd_ExchangeSelFiles(self):
        self.active_panel().model.invert_marks(files_only=True)

    def cmd_ExchangeSelBoth(self):
        self.active_panel().model.invert_marks(files_only=False)

    def cmd_SelectCurrentExtension(self):
        self.active_panel().select_same_ext(True)

    def cmd_SaveSelection(self):
        self.saved_selection = list(self.active_panel().model.marked)

    def cmd_RestoreSelection(self):
        names = set(self.saved_selection)
        self.active_panel().model.mark_where(lambda e: e.name in names)

    def cmd_CompareDirs(self):
        a, b = self.left.current(), self.right.current()
        a.model.clear_marks()
        b.model.clear_marks()
        fa = {e.name: e for e in a.model.entries if not e.is_up and not e.is_dir}
        fb = {e.name: e for e in b.model.entries if not e.is_up and not e.is_dir}
        ma = {n for n, e in fa.items() if n not in fb or (e.mtime or 0) > (fb[n].mtime or 0) + 1}
        mb = {n for n, e in fb.items() if n not in fa or (e.mtime or 0) > (fa[n].mtime or 0) + 1}
        a.model.mark_where(lambda e: e.name in ma)
        b.model.mark_where(lambda e: e.name in mb)
        if not ma and not mb:
            QtWidgets.QMessageBox.information(self, "Verzeichnisse vergleichen",
                                              "Die Dateien in beiden Verzeichnissen sind gleich.")

    # ------------------------------------------------------------ archives
    def cmd_PackFiles(self):
        p = self.active_panel()
        if not self._need_local(p, "Packen"):
            return
        entries = p.selected_entries()
        if not entries:
            return
        dest_dir = self.other_panel().local_dir() or p.local_dir()
        name = entries[0].name if len(entries) == 1 else os.path.basename(p.local_dir().rstrip("/")) or "archiv"
        if len(entries) == 1 and not entries[0].is_dir:
            name = split_ext(name)[0]
        from .dialogs import PackDialog
        dlg = PackDialog(self._what(entries), os.path.join(dest_dir, name + ".zip"), self)
        if not qexec(dlg):
            return
        target = dlg.target.text().strip()
        fmt = dlg.fmt()
        base = p.local_dir() if p.fs.kind == "local" else "/"
        if p.fs.kind == "results":
            base = os.path.commonpath([os.path.dirname(e.path) for e in entries])
        if dlg.each.isChecked():
            for e in entries:
                t = os.path.join(os.path.dirname(target), (e.name if e.is_dir else split_ext(e.name)[0]) + "." + fmt)
                self._start_op("pack", "Packen", sources=[e.path], base_dir=os.path.dirname(e.path), archive=t,
                               fmt=fmt, move=dlg.move.isChecked(), level=dlg.level.value(),
                               password=dlg.password.text() or None)
            return
        self._start_op("pack", "Packen", sources=[e.path for e in entries], base_dir=base, archive=target, fmt=fmt,
                       move=dlg.move.isChecked(), level=dlg.level.value(), password=dlg.password.text() or None)

    def cmd_UnpackFiles(self):
        p = self.active_panel()
        dest = self.other_panel().local_dir() or p.local_dir()
        if p.fs.kind == "archive":
            entries = p.selected_entries()
            if not entries:
                entries = p.model.entries[1:]
            from .dialogs import UnpackDialog
            dlg = UnpackDialog(self._what(entries), dest, self)
            if qexec(dlg):
                self._start_op("extract", "Entpacken", archive=p.fs.archive, inner_paths=[e.path for e in entries],
                               base_inner=p.inner, dest_dir=dlg.dest.text())
            return
        archives = [e.path for e in p.selected_entries() if not e.is_dir and vfs.is_archive_name(e.name)]
        if not archives:
            QtWidgets.QMessageBox.information(self, "Entpacken", "Keine Archive markiert.")
            return
        from .dialogs import UnpackDialog
        dlg = UnpackDialog("%d Archiv(e)" % len(archives), dest, self)
        if not qexec(dlg):
            return
        self._start_op("unpack", "Entpacken", archives=archives, dest_dir=dlg.dest.text().strip(),
                       separate=dlg.separate.isChecked(), mask=dlg.mask.text())

    def cmd_TestArchive(self):
        p = self.active_panel()
        archives = [e.path for e in p.selected_entries() if not e.is_dir and vfs.is_archive_name(e.name)]
        if p.fs.kind == "archive":
            archives = [p.fs.archive]
        results = []
        for a in archives:
            try:
                be = vfs.archive_backend(a)
                if be == "zip":
                    import zipfile
                    with zipfile.ZipFile(a) as zf:
                        bad = zf.testzip()
                    results.append("%s: %s" % (os.path.basename(a), "OK" if bad is None else "FEHLER in " + bad))
                elif be == "tar":
                    import tarfile
                    with tarfile.open(a) as tf:
                        for ti in tf:
                            if ti.isfile():
                                f = tf.extractfile(ti)
                                while f.read(1 << 20):
                                    pass
                    results.append("%s: OK" % os.path.basename(a))
                elif be == "7z":
                    r = subprocess.run([vfs.sevenzip(), "t", a], capture_output=True, text=True, errors="replace")
                    results.append("%s: %s" % (os.path.basename(a), "OK" if r.returncode == 0 else "FEHLER"))
                else:
                    results.append("%s: nicht testbar" % os.path.basename(a))
            except Exception as ex:  # noqa: BLE001
                results.append("%s: FEHLER %s" % (os.path.basename(a), ex))
        if results:
            QtWidgets.QMessageBox.information(self, "Archiv testen", "\n".join(results))

    # ------------------------------------------------------------ tools
    def cmd_MultiRenameFiles(self):
        p = self.active_panel()
        if not p.fs.is_local:
            self._need_local(p, "Umbenennen")
            return
        entries = p.model.marked_entries() or [e for e in p.model.entries if not e.is_up]
        if not entries:
            return
        from .multirename import MultiRenameDialog
        dlg = MultiRenameDialog(entries, self)
        qexec(dlg)
        self._refresh_all()

    def cmd_SearchFor(self):
        p = self.active_panel()
        from .search import SearchDialog
        sel = [e.path for e in p.model.marked_entries() if e.is_dir]
        dlg = SearchDialog(self, p.local_dir() or os.path.expanduser("~"), sel)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def cmd_SyncDirs(self):
        from .compare import SyncDirsDialog
        dlg = SyncDirsDialog(self.left.current().local_dir() or "", self.right.current().local_dir() or "", self)
        qexec(dlg)
        self._refresh_all()

    def cmd_CompareFilesByContent(self):
        p = self.active_panel()
        sel = [e for e in p.model.marked_entries() if not e.is_dir]
        if len(sel) == 2:
            a, b = sel[0].path, sel[1].path
        else:
            e = p.current_entry()
            o = self.other_panel()
            oe = o.current_entry()
            if not e or e.is_dir or e.is_up or not p.fs.is_local:
                from .compare import CompareTool
                CompareTool().show()
                return
            other = [x for x in o.model.marked_entries() if not x.is_dir]
            if other:
                b = other[0].path
            elif oe and not oe.is_dir:
                b = oe.path
            elif o.local_dir() and os.path.isfile(os.path.join(o.local_dir(), e.name)):
                b = os.path.join(o.local_dir(), e.name)
            else:
                b = None
            a = e.path
        if p.side == "right" and b:
            a, b = b, a
        from .compare import CompareTool
        CompareTool(a, b).show()

    def cmd_ChangeAttributes(self):
        p = self.active_panel()
        if not p.fs.is_local:
            return
        paths = p.selected_paths()
        if not paths:
            return
        from .dialogs import AttributesDialog
        dlg = AttributesDialog(paths, self)
        if qexec(dlg):
            err = dlg.apply()
            if err:
                QtWidgets.QMessageBox.warning(self, "Attribute", "\n".join(err[:30]))
            p.refresh()

    def cmd_Properties(self):
        p = self.active_panel()
        e = p.current_entry()
        if not p.fs.is_local:
            return
        path = e.path if e and not e.is_up else p.local_dir()
        if not path:
            return
        from .dialogs import PropertiesDialog
        qexec(PropertiesDialog(path, self, self))
        p.refresh()

    def cmd_CreateLink(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_up or not p.fs.is_local:
            return
        dest = self.other_panel().local_dir() or p.local_dir()
        from .dialogs import LinkDialog
        dlg = LinkDialog(e.path, os.path.join(dest, e.name), self)
        if qexec(dlg):
            try:
                dlg.create()
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Verknüpfung", str(ex))
            self._refresh_all()

    def cmd_CRCCreate(self):
        p = self.active_panel()
        files = [e.path for e in p.selected_entries() if not e.is_dir and e.path]
        if not files or not p.local_dir():
            return
        from .dialogs import ChecksumCreateDialog
        qexec(ChecksumCreateDialog(files, p.local_dir(), self))
        p.refresh()

    def cmd_CRCVerify(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_dir or not e.path:
            return
        from .dialogs import verify_checksum_file
        verify_checksum_file(e.path, self)

    def cmd_SplitFile(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_dir or e.is_up or not p.local_dir():
            return
        from .dialogs import SplitDialog, split_file
        dlg = SplitDialog(e.path, self.other_panel().local_dir() or p.local_dir(), self)
        if qexec(dlg):
            try:
                split_file(e.path, dlg.dest.text(), dlg.part_size(), dlg.crc.isChecked(), self)
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Aufteilen", str(ex))
            self._refresh_all()

    def cmd_CombineFiles(self):
        p = self.active_panel()
        e = p.current_entry()
        if not e or e.is_dir or e.is_up or not p.local_dir():
            return
        from .dialogs import combine_files
        try:
            combine_files(e.path, self.other_panel().local_dir() or p.local_dir(), self)
        except OSError as ex:
            QtWidgets.QMessageBox.warning(self, "Zusammenfügen", str(ex))
        self._refresh_all()

    def cmd_CalcSpace(self):
        p = self.active_panel()
        if not p.fs.is_local:
            return
        sel = p.model.marked_entries() or [e for e in p.model.entries if e.is_dir and not e.is_up]
        p.calc_dir_sizes([e for e in sel if e.is_dir])

    def cmd_Exit(self):
        self.close()

    # ------------------------------------------------------------ navigation commands
    def cmd_DirHotlist(self):
        p = self.active_panel()
        menu = QtWidgets.QMenu(self)
        for item in config.get("hotlist", []):
            if item.get("title") == "-":
                menu.addSeparator()
                continue
            a = menu.addAction(icons().folder, item.get("title") or item.get("path"))
            a.setToolTip(item.get("path"))
            a.triggered.connect(lambda _c=False, path=item.get("path"): self._hot_go(path))
        if config.get("hotlist"):
            menu.addSeparator()
        menu.addAction(QtGui.QIcon.fromTheme("list-add"), "Aktuelles Verzeichnis hinzufügen", self._hot_add)
        menu.addAction("Konfigurieren…", self.cmd_ConfigHotlist)
        pos = p.path_edit.mapToGlobal(QtCore.QPoint(0, p.path_edit.height()))
        qexec(menu, pos)

    def _hot_go(self, path):
        p = self.active_panel()
        if p.set_location(path):
            p.activate(focus=True)

    def _hot_add(self):
        p = self.active_panel()
        loc = p.location()
        if p.fs.kind == "results":
            return
        title, ok = QtWidgets.QInputDialog.getText(self, "Hotlist", "Titel:",
                                                   text=os.path.basename(loc.rstrip("/")) or loc)
        if ok:
            config["hotlist"] = config.get("hotlist", []) + [{"title": title or loc, "path": loc}]
            config.save()

    def cmd_ConfigHotlist(self):
        from .dialogs import HotlistDialog
        dlg = HotlistDialog(self)
        if qexec(dlg):
            dlg.save()

    def cmd_SwapPanels(self):
        a, b = self.left.current(), self.right.current()
        la, lb = a.location(), b.location()
        ma, mbm = a.mode, b.mode
        a.set_location(lb)
        b.set_location(la)
        a.set_mode(mbm)
        b.set_mode(ma)
        self.set_active(self.other_tabbed())
        self.active_panel().activate(focus=True)

    def cmd_TargetEqualSource(self):
        self.other_panel().set_location(self.active_panel().location())

    def _transfer(self, to_side):
        p = self.active_panel()
        target = (self.left if to_side == "left" else self.right).current()
        if p is target:
            # same side: TC opens current dir in the other panel
            other = self.other_panel()
            e = p.current_entry()
            if e and e.is_dir and not e.is_up and p.fs.kind == "local":
                other.set_location(e.path)
            else:
                other.set_location(p.location())
            return
        e = p.current_entry()
        if e and e.is_dir and not e.is_up:
            target.set_location(e.path if p.fs.kind == "local" else p.fs.display(e.path))
        elif e and not e.is_dir and p.fs.kind == "local" and vfs.is_archive_name(e.name):
            target.set_location(e.path)
        else:
            target.set_location(p.location())

    def cmd_TransferLeft(self):
        if self.active_side == "right":
            self._transfer("left")
        else:
            self._transfer_same("left")

    def cmd_TransferRight(self):
        if self.active_side == "left":
            self._transfer("right")
        else:
            self._transfer_same("right")

    def _transfer_same(self, side):
        # Ctrl+Left in left panel (TC): show current dir in the other panel
        p = self.active_panel()
        e = p.current_entry()
        other = self.other_panel()
        if e and e.is_dir and not e.is_up and p.fs.kind == "local":
            other.set_location(e.path)
        else:
            other.set_location(p.location())

    def cmd_OpenTerminal(self):
        p = self.active_panel()
        d = p.local_dir() or os.path.expanduser("~")
        if not open_terminal(d):
            QtWidgets.QMessageBox.warning(self, "Terminal", "Terminal „%s“ konnte nicht gestartet werden."
                                          % config.get("terminal"))

    def run_in_terminal(self, path):
        open_terminal(os.path.dirname(path), shlex.quote(path), hold=True)

    def cmd_QuickFilter(self):
        self.active_panel().open_quick_filter()

    def cmd_QuickSearch(self):
        p = self.active_panel()
        p.activate(focus=True)
        p.quick.open("")

    def cmd_LeftOpenDrives(self):
        self.set_active(self.left)
        self.left.drivebar.popup()

    def cmd_RightOpenDrives(self):
        self.set_active(self.right)
        self.right.drivebar.popup()

    def cmd_CmdLineHistory(self):
        self.cmdline.setFocus()
        self.cmdline.showPopup()

    def cmd_AddPathToCmdline(self):
        p = self.active_panel()
        self.cmdline.insert(shlex.quote(p.local_dir() or "") + "/")
        self.cmdline.setFocus()

    def cmd_AddFilenameToCmdline(self):
        p = self.active_panel()
        e = p.current_entry()
        if e and not e.is_up:
            self.cmdline.insert(shlex.quote(e.name) + " ")

    def cmd_AddPathAndNameToCmdline(self):
        p = self.active_panel()
        e = p.current_entry()
        if e and not e.is_up and e.path:
            self.cmdline.insert(shlex.quote(e.path) + " ")

    def cmd_FocusCmdLine(self):
        if self.cmdline.text():
            self.cmdline.setFocus()

    def cmd_SwitchPanel(self):
        o = self.other_tabbed()
        self.set_active(o)
        o.current().activate(focus=True)

    def run_cmdline(self, in_terminal=False):
        cmd = self.cmdline.text().strip()
        if not cmd:
            return
        p = self.active_panel()
        cwd = p.local_dir() or os.path.expanduser("~")
        config.push_history("cmd_history", cmd)
        self.cmdline.blockSignals(True)
        self.cmdline.clear()
        idx = self.cmdline.findText(cmd)
        if idx >= 0:
            self.cmdline.removeItem(idx)
        self.cmdline.insertItem(0, cmd)
        self.cmdline.setCurrentIndex(-1)
        self.cmdline.setEditText("")
        self.cmdline.blockSignals(False)
        if re.fullmatch(r"[A-Za-z]:[\\/]?", cmd):
            if p.set_location(cmd):
                p.activate(focus=True)
            return
        if cmd == "cd" or cmd.startswith("cd "):
            target = cmd
            while target == "cd" or target.startswith("cd "):  # also "cd cd /path"
                target = target[2:].strip()
            target = target or "~"
            try:
                target = " ".join(shlex.split(target))
            except ValueError:
                pass
            target = os.path.expanduser(target)
            if target == "-":
                p.go_back()
            elif vfs.is_url(target):
                p.set_location(target)
            else:
                full = os.path.normpath(os.path.join(cwd, target))
                found = find_dir_nocase(full)
                if found:
                    p.set_location(found)
                else:
                    QtWidgets.QMessageBox.warning(self, "cd", "Verzeichnis nicht gefunden:\n%s" % full)
            p.activate(focus=True)
            return
        if in_terminal:
            open_terminal(cwd, cmd, hold=True)
        else:
            try:
                subprocess.Popen(cmd, shell=True, cwd=cwd, start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, "Ausführen", str(ex))
        p.activate(focus=True)
        QtCore.QTimer.singleShot(800, p.refresh)

    def run_external_button(self, cmd, files=None):
        p = self.active_panel()
        if cmd.startswith("cd:"):
            if p.set_location(cmd[3:]):
                p.activate(focus=True)
            return
        e = p.current_entry()
        cwd = p.local_dir() or os.path.expanduser("~")
        dropped = files is not None
        if files is None:
            files = [e.path] if e and not e.is_up and e.path and p.fs.is_local else []
        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()
        out = []
        used = False
        for x in parts:
            if x == "%s":
                out.extend(files)
                used = True
            elif "%s" in x:
                out.append(x.replace("%s", files[0] if files else ""))
                used = True
            else:
                out.append(x)
        if dropped and not used:
            out.extend(files)
        if out and out[0] == "xdg-open" and len(out) > 1:
            for f in out[1:]:
                open_default(f)
            return
        try:
            subprocess.Popen(out, cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL)
        except (OSError, ValueError) as ex:
            QtWidgets.QMessageBox.warning(self, "Button", str(ex))

    def drop_on_button(self, action, paths, index):
        tb = self.toolbar
        cmd = tb.cmd_of.get(action) if action is not None else None
        if cmd and cmd != "-":
            if not cmd.startswith("cm_"):
                self.run_external_button(cmd, paths)
            elif cmd == "cm_View":
                for x in paths:
                    if os.path.isfile(x):
                        self.view_file(x)
            elif cmd == "cm_Edit":
                for x in paths:
                    if os.path.isfile(x):
                        self.open_editor(x)
            elif cmd == "cm_CompareFilesByContent":
                from .compare import CompareTool
                CompareTool(paths[0], paths[1] if len(paths) > 1 else None).show()
            elif cmd == "cm_OpenTerminal":
                open_terminal(paths[0] if os.path.isdir(paths[0]) else os.path.dirname(paths[0]))
            else:
                self.statusBar().showMessage("Auf diesen Button können keine Dateien gezogen werden. Zum Anlegen "
                                             "eines neuen Buttons auf eine freie Stelle ziehen.", 4000)
            return
        buttons = list(config.get("buttons", []))
        index = max(0, min(index, len(buttons)))
        for x in paths:
            buttons.insert(index, button_for_path(x))
            index += 1
        config["buttons"] = buttons
        config.save()
        self._build_buttonbar()
        self.apply_settings()
        self.statusBar().showMessage("%d Button(s) hinzugefügt" % len(paths), 3000)

    def edit_button(self, index):
        buttons = list(config.get("buttons", []))
        if not 0 <= index < len(buttons):
            return
        cmd, icon, tip = (list(buttons[index]) + ["", "", ""])[:3]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Button bearbeiten")
        f = QtWidgets.QFormLayout(dlg)
        ce = QtWidgets.QLineEdit(cmd)
        ce.setToolTip("cm_… = interner Befehl, cd:/pfad = Verzeichnis wechseln, sonst Programm (%s = Datei)")
        ie = QtWidgets.QLineEdit(icon)
        te = QtWidgets.QLineEdit(tip)
        f.addRow("Kommando:", ce)
        irow = QtWidgets.QHBoxLayout()
        prev = QtWidgets.QLabel()
        prev.setFixedSize(28, 28)

        def upd_prev(*_a):
            ic = load_icon(ie.text().strip())
            prev.setPixmap(ic.pixmap(24, 24) if not ic.isNull() else QtGui.QPixmap())
        ie.textChanged.connect(upd_prev)
        upd_prev()
        pick = QtWidgets.QPushButton("Auswählen…")

        def do_pick():
            r = pick_icon(ie.text().strip(), dlg)
            if r is not None:
                ie.setText(r)
        pick.clicked.connect(do_pick)
        irow.addWidget(prev)
        irow.addWidget(ie, 1)
        irow.addWidget(pick)
        f.addRow("Symbol:", irow)
        f.addRow("Tooltip:", te)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        dlg.resize(520, 10)
        if qexec(dlg):
            buttons[index] = [ce.text().strip(), ie.text().strip(), te.text().strip()]
            config["buttons"] = buttons
            config.save()
            self._build_buttonbar()
            self.apply_settings()

    def remove_button(self, index, sep=False):
        buttons = list(config.get("buttons", []))
        if sep:
            buttons.insert(index, ["-", "", ""])
        elif 0 <= index < len(buttons):
            del buttons[index]
        config["buttons"] = buttons
        config.save()
        self._build_buttonbar()
        self.apply_settings()

    # ------------------------------------------------------------ network
    def _connect_ftp(self, scheme, host, port, user, password, path):
        from . import ftpfs, sftpfs
        title = scheme.upper()
        try:
            port = int(port) if port else (22 if scheme == "sftp" else 21)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, title, "Ungültiger Port: %s" % port)
            return
        if scheme == "sftp":
            fs = sftpfs.SftpFS(host, port, user, password)
        else:
            fs = ftpfs.FtpFS(host, port, user, password, scheme == "ftps")
        while True:
            QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                fs.connect()
                break
            except sftpfs.UnknownHostKey as ex:
                QtWidgets.QApplication.restoreOverrideCursor()
                if QtWidgets.QMessageBox.question(
                        self, title, "%s\n\nDem Server vertrauen und den Schlüssel in ~/.ssh/known_hosts "
                        "speichern?" % ex) != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
                try:
                    fs.trust_key(ex.key)
                except OSError as ex2:
                    QtWidgets.QMessageBox.warning(self, title, "known_hosts nicht schreibbar:\n%s" % ex2)
                    return
                continue
            except OSError as ex:
                QtWidgets.QMessageBox.warning(self, title, "Verbindung fehlgeschlagen:\n%s" % ex)
                return
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        old = [c for c in ftpfs.connections() if (c.scheme, c.user, c.host.lower(), c.port) ==
               (fs.scheme, fs.user, fs.host.lower(), fs.port)]
        for c in old:
            ftpfs.unregister(c)
        ftpfs.register(fs)
        url = fs.display("/" + path.lstrip("/"))
        config.push_history("net_history", url, 20)
        self.active_panel().set_location(url)
        self.active_panel().activate(focus=True)

    def cmd_ConnectNetwork(self):
        gio = shutil.which("gio")
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Netzwerkverbindung")
        f = QtWidgets.QFormLayout(dlg)
        proto = QtWidgets.QComboBox()
        proto.addItems(["sftp", "ftp", "ftps", "smb", "dav", "davs", "nfs", "afp"])
        host = QtWidgets.QLineEdit()
        port = QtWidgets.QLineEdit()
        port.setPlaceholderText("Standard")
        path = QtWidgets.QLineEdit()
        user = QtWidgets.QLineEdit(os.environ.get("USER", ""))
        user.setPlaceholderText("leer = anonymous (FTP)")
        pw = QtWidgets.QLineEdit()
        pw.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        hist = QtWidgets.QComboBox()
        hist.addItem("")
        hist.addItems(config.get("net_history", []))
        f.addRow("Zuletzt:", hist)
        f.addRow("Protokoll:", proto)
        f.addRow("Server:", host)
        f.addRow("Port:", port)
        f.addRow("Pfad/Freigabe:", path)
        f.addRow("Benutzer:", user)
        f.addRow("Passwort:", pw)

        def from_hist(t):
            if not t:
                return
            u = QtCore.QUrl(t)
            proto.setCurrentText(u.scheme())
            host.setText(u.host())
            port.setText(str(u.port()) if u.port() > 0 else "")
            path.setText(u.path())
            user.setText(u.userName())
        hist.currentTextChanged.connect(from_hist)
        from . import sftpfs
        f.addRow(QtWidgets.QLabel("SFTP (SSH)%s, FTP/FTPS: direkte Verbindung. Andere Protokolle über GVFS (gio mount).\n"
                                  "SFTP: Passwort leer = SSH-Schlüssel / ssh-agent." %
                                  ("" if sftpfs.available() else " – über GVFS, da python3-paramiko fehlt")))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if not qexec(dlg) or not host.text().strip():
            return
        if proto.currentText() in ("ftp", "ftps") or (proto.currentText() == "sftp" and sftpfs.available()):
            self._connect_ftp(proto.currentText(), host.text().strip(), port.text().strip(), user.text().strip(),
                              pw.text(), path.text().strip())
            return
        if not gio:
            QtWidgets.QMessageBox.warning(self, "Netzwerk", "„gio“ wurde nicht gefunden (Paket gvfs / libglib2.0-bin).")
            return
        url = "%s://%s%s%s%s" % (proto.currentText(), (user.text() + "@") if user.text() else "",
                                 host.text().strip(), (":" + port.text().strip()) if port.text().strip() else "",
                                 ("/" + path.text().strip().lstrip("/")) if path.text().strip() else "/")
        config.push_history("net_history", url, 20)
        before = set(os.listdir("/run/user/%d/gvfs" % os.getuid())) if os.path.isdir(
            "/run/user/%d/gvfs" % os.getuid()) else set()
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            answers = "%s\n%s\n%s\n" % (user.text(), "", pw.text())
            r = subprocess.run([gio, "mount", url], input=(pw.text() + "\n") * 1 if user.text() else answers,
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            r = None
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        gvfs = "/run/user/%d/gvfs" % os.getuid()
        if r is not None and r.returncode != 0 and "already mounted" not in (r.stderr or "").lower() \
                and "bereits eingehängt" not in (r.stderr or ""):
            QtWidgets.QMessageBox.warning(self, "Netzwerk", "Verbindung fehlgeschlagen:\n%s" % (r.stderr or r.stdout))
            return
        after = set(os.listdir(gvfs)) if os.path.isdir(gvfs) else set()
        new = sorted(after - before)
        target = os.path.join(gvfs, new[0]) if new else None
        if target is None and os.path.isdir(gvfs):
            hn = host.text().strip()
            for n in sorted(after):
                if hn in n:
                    target = os.path.join(gvfs, n)
                    break
        if target:
            self.active_panel().set_location(target)
            for tp in (self.left, self.right):
                tp.drivebar.reload()
        else:
            QtWidgets.QMessageBox.information(self, "Netzwerk", "Verbunden, aber kein FUSE-Pfad gefunden (gvfs-fuse "
                                              "installiert?).")

    def cmd_DisconnectNetwork(self):
        gvfs = "/run/user/%d/gvfs" % os.getuid()
        try:
            mounts = sorted(os.listdir(gvfs))
        except OSError:
            mounts = []
        from . import ftpfs
        ftps = {c.base_url: c for c in ftpfs.connections()}
        if not mounts and not ftps:
            QtWidgets.QMessageBox.information(self, "Netzwerk", "Keine Netzwerkverbindungen vorhanden.")
            return
        item, ok = QtWidgets.QInputDialog.getItem(self, "Verbindung trennen", "Verbindung:",
                                                  list(ftps) + mounts, 0, False)
        if not ok:
            return
        if item in ftps:
            for tp in (self.left, self.right):
                for p in tp.panels():
                    if p.fs is ftps[item]:
                        p.set_location(os.path.expanduser("~"))
            ftpfs.unregister(ftps[item])
            return
        for tp in (self.left, self.right):
            for p in tp.panels():
                if p.local_dir() and p.local_dir().startswith(os.path.join(gvfs, item)):
                    p.set_location(os.path.expanduser("~"))
        r = subprocess.run(["gio", "mount", "-u", os.path.join(gvfs, item)], capture_output=True, text=True)
        if r.returncode != 0:
            QtWidgets.QMessageBox.warning(self, "Netzwerk", r.stderr)
        for tp in (self.left, self.right):
            tp.drivebar.reload()

    # ------------------------------------------------------------ view commands
    def cmd_BriefView(self):
        self.active_panel().set_mode(MODE_BRIEF)

    def cmd_FullView(self):
        self.active_panel().set_mode(MODE_FULL)

    def cmd_ThumbnailsView(self):
        self.active_panel().set_mode(MODE_THUMBS)

    def cmd_TreeView(self):
        p = self.active_panel()
        p.set_mode(MODE_FULL if p.mode == MODE_TREE else MODE_TREE)

    def cmd_QuickView(self):
        self.quickview_on = not self.quickview_on
        self.actions["cm_QuickView"].setChecked(self.quickview_on)
        if not self.quickview_on:
            self.left_stack.setCurrentIndex(0)
            self.right_stack.setCurrentIndex(0)
            self.active_panel().activate(focus=True)
            return
        self._update_quickview()

    def _update_quickview(self):
        act = self.active_side
        (self.left_stack if act == "left" else self.right_stack).setCurrentIndex(0)
        stack = self.right_stack if act == "left" else self.left_stack
        qv = self.right_qv if act == "left" else self.left_qv
        stack.setCurrentIndex(1)
        p = self.active_panel()
        e = p.current_entry()
        if e and not e.is_up and e.path and p.fs.is_local:
            qv.load(e.path)
        else:
            qv.load(None)

    def _sort(self, col):
        self.active_panel().sort_by(col)

    def cmd_SortByName(self):
        self._sort(COL_NAME)

    def cmd_SortByExt(self):
        self._sort(COL_EXT)

    def cmd_SortByDate(self):
        self._sort(COL_DATE)

    def cmd_SortBySize(self):
        self._sort(COL_SIZE)

    def cmd_SortByAttr(self):
        self._sort(COL_ATTR)

    def cmd_ReverseOrder(self):
        p = self.active_panel()
        self._sort(p.full.header().sortIndicatorSection())

    def cmd_AllFiles(self):
        p = self.active_panel()
        p.filter_edit.clear()
        p.filter_edit.hide()

    def cmd_ExecutablesOnly(self):
        p = self.active_panel()
        p.model.beginResetModel()
        p.model.entries = [e for e in p.model.entries if e.is_up or e.is_dir or
                           (e.mode is not None and e.mode & 0o111)]
        p.model.endResetModel()
        p.update_status()

    def cmd_UserFilter(self):
        p = self.active_panel()
        m, ok = QtWidgets.QInputDialog.getText(self, "Filter", "Nur Dateien anzeigen, die passen auf (z.B. *.jpg):",
                                               text=p.filter_edit.text() or "*.*")
        if ok:
            p.filter_edit.show()
            p.filter_edit.setText(m if m not in ("*", "*.*") else "")
            if not p.filter_edit.text():
                p.filter_edit.hide()
            p.view.setFocus()

    def cmd_RereadSource(self):
        for tp in (self.left, self.right):
            tp.drivebar.reload()
            tp.drivebar.update_for(tp.current())
        self.active_panel().refresh()

    def cmd_RereadF2(self):
        self.cmd_RereadSource()

    def cmd_ConfigShowHidden(self):
        config["show_hidden"] = not config.get("show_hidden")
        self.actions["cm_ConfigShowHidden"].setChecked(config["show_hidden"])
        self._refresh_all()

    def cmd_OpenNewTab(self):
        tp = self.active_tabbed()
        p = tp.add_tab(self.active_panel().location() if self.active_panel().fs.kind != "results" else None)
        self._hook_panel(p)
        self.apply_settings()
        p.activate(focus=True)

    def cmd_OpenDirInNewTab(self, other=False):
        p = self.active_panel()
        e = p.current_entry()
        loc = p.location()
        if e and e.is_dir and not e.is_up:
            loc = e.path if p.fs.kind == "local" else p.fs.display(e.path)
        tp = self.other_tabbed() if other else self.active_tabbed()
        np_ = tp.add_tab(loc, activate=not other)
        self._hook_panel(np_)
        self.apply_settings()
        if not other:
            np_.activate(focus=True)

    def cmd_OpenDirInNewTabOther(self):
        self.cmd_OpenDirInNewTab(other=True)

    def cmd_CloseCurrentTab(self):
        tp = self.active_tabbed()
        tp.close_tab()
        tp.current().activate(focus=True)

    def cmd_LockTab(self):
        tp = self.active_tabbed()
        p = self.active_panel()
        on = not (p.locked and not p.lock_nav)
        tp.set_locked(p, on)
        self.statusBar().showMessage("Tab %s" % ("gesperrt – Verzeichniswechsel öffnet einen neuen Tab" if on
                                                  else "entsperrt"), 3000)

    def cmd_LockTabNav(self):
        tp = self.active_tabbed()
        p = self.active_panel()
        on = not (p.locked and p.lock_nav)
        tp.set_locked(p, on, nav=True)
        self.statusBar().showMessage("Tab %s" % (
            "gesperrt, Verzeichniswechsel erlaubt – beim erneuten Aktivieren zurück nach " + (p.lock_path or "")
            if on else "entsperrt"), 4000)

    def cmd_CloseAllTabs(self):
        tp = self.active_tabbed()
        tp.close_others(tp.tabs.currentIndex())

    def cmd_NextTab(self):
        tp = self.active_tabbed()
        tp.tabs.setCurrentIndex((tp.tabs.currentIndex() + 1) % tp.tabs.count())
        tp.current().activate(focus=True)

    def cmd_PrevTab(self):
        tp = self.active_tabbed()
        tp.tabs.setCurrentIndex((tp.tabs.currentIndex() - 1) % tp.tabs.count())
        tp.current().activate(focus=True)

    # ------------------------------------------------------------ config / help
    def cmd_Config(self):
        from .dialogs import SettingsDialog
        cmds = {n: (v[0], v[1], v[2]) for n, v in COMMANDS.items() if n in self.actions}
        dlg = SettingsDialog(cmds, self)
        if qexec(dlg):
            dlg.apply()
            user = config.get("user_hotkeys", {})
            for n, a in self.actions.items():
                a.setShortcut(QtGui.QKeySequence(user.get(n, COMMANDS[n][1]) or ""))
            self._build_buttonbar()
            self.apply_settings()
            self._refresh_all()

    def cmd_SaveSettings(self):
        self.save_state()
        self.statusBar().showMessage("Einstellungen gespeichert", 2000)

    def cmd_Keyboard(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Tastaturbelegung")
        lay = QtWidgets.QVBoxLayout(dlg)
        t = QtWidgets.QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Taste", "Funktion"])
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().hide()
        rows = [(a.shortcut().toString(), a.text()) for n, a in self.actions.items() if a.shortcut().toString()]
        rows += [("Tab", "Fenster wechseln"), ("Enter", "Öffnen / Verzeichnis wechseln / Archiv öffnen"),
                 ("Shift+Enter", "Programm/Kommando im Terminal ausführen"),
                 ("Backspace / Ctrl+PgUp", "Übergeordnetes Verzeichnis"), ("Ctrl+PgDown", "Verzeichnis/Archiv öffnen"),
                 ("Ctrl+\\", "Wurzelverzeichnis"), ("Alt+← / Alt+→", "Zurück / Vorwärts im Verlauf"),
                 ("Alt+↓", "Verzeichnisverlauf"), ("Einfg", "Datei markieren und weiter"),
                 ("Leertaste", "Markieren (bei Verzeichnis: Größe berechnen)"),
                 ("Shift+Pfeiltasten", "Markieren"), ("Num +", "Gruppe markieren"), ("Num -", "Gruppe demarkieren"),
                 ("Num *", "Markierung umkehren"), ("Num /", "Markierung wiederherstellen"),
                 ("Alt+Num +", "Gleiche Erweiterung markieren"), ("Ctrl+Num + / -", "Alle (de)markieren"),
                 ("Buchstaben", "Schnellsuche (einstellbar)"), ("Esc", "Kommandozeile leeren / Filter schließen"),
                 ("Doppelklick Tab-Leiste", "Neuer Tab / Tab schließen"), ("Mittelklick Tab", "Tab schließen"),
                 ("Lister: 1/2/3/4", "Text / Binär / Hex / Bild"), ("Lister: N / P", "Nächste / vorherige Datei"),
                 ("Lister: F7 / F3", "Suchen / Weitersuchen"), ("Lister: W", "Zeilenumbruch")]
        for k, f in rows:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QtWidgets.QTableWidgetItem(k))
            t.setItem(r, 1, QtWidgets.QTableWidgetItem(f))
        t.resizeColumnsToContents()
        lay.addWidget(t)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(620, 640)
        qexec(dlg)

    def cmd_CheckUpdates(self):
        self.update_button.check(manual=True)

    def cmd_About(self):
        from .qt import QT6
        QtWidgets.QMessageBox.about(self, "Über PixelCommander", (
            "<h2>PixelCommander %s</h2><p>Zwei-Fenster-Dateimanager für Linux nach dem Vorbild von "
            "Total Commander.</p><p>Python %s, %s %s</p>" % (
                __version__, ".".join(map(str, __import__("sys").version_info[:3])), "PyQt6" if QT6 else "PyQt5",
                QtCore.PYQT_VERSION_STR)))

    # ------------------------------------------------------------ context menu
    def show_context_menu(self, panel, pos, background=False):
        menu = QtWidgets.QMenu(self)
        e = panel.current_entry()
        if not background and e and not e.is_up:
            menu.addAction(QtGui.QIcon.fromTheme("document-open"), "Öffnen", panel.open_current)
            if panel.fs.is_local and not e.is_dir:
                menu.addAction("Öffnen mit…", self.cmd_OpenWith)
            menu.addSeparator()
            for n in ("cm_View", "cm_Edit"):
                if not e.is_dir or n == "cm_View":
                    menu.addAction(self.actions[n])
            menu.addSeparator()
            for n in ("cm_CutToClipboard", "cm_CopyToClipboard"):
                menu.addAction(self.actions[n])
        menu.addAction(self.actions["cm_PasteFromClipboard"])
        menu.addSeparator()
        if not background and e and not e.is_up:
            for n in ("cm_Copy", "cm_RenMov", "cm_RenameOnly", "cm_Delete", "cm_CreateLink"):
                menu.addAction(self.actions[n])
            menu.addSeparator()
            menu.addAction(self.actions["cm_PackFiles"])
            if vfs.is_archive_name(e.name) and not e.is_dir:
                menu.addAction(self.actions["cm_UnpackFiles"])
            menu.addSeparator()
            menu.addAction(self.actions["cm_CopyFullNamesToClip"])
        menu.addAction(self.actions["cm_MkDir"])
        menu.addAction(self.actions["cm_EditNewFile"])
        menu.addAction(self.actions["cm_OpenTerminal"])
        menu.addSeparator()
        menu.addAction(self.actions["cm_Properties"])
        qexec(menu, pos)

    # ------------------------------------------------------------ state
    def save_state(self):
        config["geometry"] = bytes(self.saveGeometry().toHex()).decode()
        config["splitter"] = bytes(self.splitter.saveState().toHex()).decode()
        config["left"] = self.left.state()
        config["right"] = self.right.state()
        config["active_panel"] = self.active_side
        config["columns"] = self.left.current().column_widths()
        hist = [self.cmdline.itemText(i) for i in range(self.cmdline.count())]
        config["cmd_history"] = hist[:50]
        config.save()

    def closeEvent(self, e):
        if config.get("confirm_exit") and QtWidgets.QMessageBox.question(
                self, "Beenden", "PixelCommander beenden?") != QtWidgets.QMessageBox.StandardButton.Yes:
            e.ignore()
            return
        if fileops._running:
            if QtWidgets.QMessageBox.question(self, "Beenden", "Es laufen noch Dateioperationen. Trotzdem beenden?") \
                    != QtWidgets.QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            for w in list(fileops._running):
                w.cancel = True
                w.paused.set()
                w.wait(2000)
        self.save_state()
        super().closeEvent(e)


def _dir_nonempty(path):
    try:
        with os.scandir(path) as it:
            return next(it, None) is not None
    except OSError:
        return False


class ButtonBar(QtWidgets.QToolBar):
    """Button bar: accepts dropped files (run with that button / add as new button) and has a context menu."""

    def __init__(self, main):
        super().__init__("Buttonleiste")
        self.main = main
        self.setAcceptDrops(True)
        self.cmd_of = {}
        self.entries = []  # (action, index in config)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.ctx_menu)

    def register(self, action, cmd, _a):
        self.entries.append(action)
        self.cmd_of[action] = cmd

    def index_of(self, action):
        for i, a in enumerate(self.entries):
            if a is action:
                return i
        return -1

    def insert_index(self, pos):
        for i, a in enumerate(self.entries):
            w = self.widgetForAction(a)
            if w is not None and pos.x() < w.geometry().center().x():
                return i
        return len(self.entries)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            a = self.actionAt(event_pos(e))
            cmd = self.cmd_of.get(a) if a is not None else None
            if cmd and cmd != "-":
                self.main.statusBar().showMessage("Loslassen: mit „%s“ ausführen" % (a.text() or cmd), 1000)
            else:
                self.main.statusBar().showMessage("Loslassen: als neuen Button hinzufügen", 1000)

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        e.acceptProposedAction()
        pos = event_pos(e)
        a = self.actionAt(pos)
        if a is not None and self.cmd_of.get(a) == "-":
            a = None
        idx = self.insert_index(pos)
        QtCore.QTimer.singleShot(0, lambda: self.main.drop_on_button(a, paths, idx))

    def ctx_menu(self, pos):
        a = self.actionAt(pos)
        i = self.index_of(a) if a is not None else -1
        menu = QtWidgets.QMenu(self)
        if i >= 0 and self.cmd_of.get(a) != "-":
            menu.addAction("Button bearbeiten…", lambda: self.main.edit_button(i))
        if i >= 0:
            menu.addAction("Entfernen", lambda: self.main.remove_button(i))
        menu.addAction("Trennlinie einfügen", lambda: self.main.remove_button(i if i >= 0 else len(self.entries),
                                                                              sep=True))
        menu.addSeparator()
        menu.addAction("Buttonleiste konfigurieren…", self.main.cmd_Config)
        menu.addAction("Tipp: Dateien/Programme hierher ziehen = neuer Button").setEnabled(False)
        qexec(menu, self.mapToGlobal(pos))


def button_for_path(path):
    """Create a button entry [cmd, icon, tooltip] for a dropped file."""
    name = os.path.basename(path.rstrip("/")) or path
    if path.endswith(".desktop") and os.path.isfile(path):
        info = {}
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                sect = None
                for line in fh:
                    line = line.strip()
                    if line.startswith("["):
                        sect = line
                    elif sect == "[Desktop Entry]" and "=" in line:
                        k, v = line.split("=", 1)
                        info.setdefault(k, v)
        except OSError:
            pass
        exe = info.get("Exec", "")
        has_file = any(c in exe for c in ("%f", "%F", "%u", "%U"))
        exe = re.sub(r"%[fFuUdDnNickvm]", "", exe).strip()
        if has_file:
            exe += " %s"
        return [exe or shlex.quote(path), info.get("Icon", "application-x-executable"),
                info.get("Name[de]") or info.get("Name") or name]
    if os.path.isdir(path):
        return ["cd:" + path, "folder", name]
    if is_executable_file(path):
        return [shlex.quote(path), "application-x-executable", name]
    mt = QtCore.QMimeDatabase().mimeTypeForFile(path)
    return ["xdg-open " + shlex.quote(path), mt.iconName(), name]
