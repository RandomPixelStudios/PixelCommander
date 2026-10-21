"""Persistent configuration stored as JSON in ~/.config/pixelcommander/config.json."""
import json
import os
import shutil

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "pixelcommander")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
_OLD_CONFIG_DIR = os.path.join(os.path.dirname(CONFIG_DIR), "speedcommander")
if not os.path.exists(CONFIG_DIR) and os.path.isdir(_OLD_CONFIG_DIR):
    # renamed from SpeedCommander: take over the old settings
    try:
        shutil.copytree(_OLD_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass


def _first_installed(candidates, fallback):
    for c in candidates:
        if shutil.which(c.split()[0]):
            return c
    return fallback


DEFAULT_BUTTONS = [
    ["cm_RereadSource", "view-refresh", "Neu einlesen"],
    ["cm_BriefView", "view-list-details", "Kurzansicht"],
    ["cm_FullView", "view-list-text", "Vollansicht"],
    ["cm_ThumbnailsView", "view-list-icons", "Miniaturansicht"],
    ["cm_TreeView", "view-list-tree", "Verzeichnisbaum"],
    ["-", "", ""],
    ["cm_SelectAll", "edit-select-all", "Alle markieren"],
    ["cm_InvertSelection", "edit-select-invert", "Markierung umkehren"],
    ["-", "", ""],
    ["cm_PackFiles", "package-x-generic", "Packen"],
    ["cm_UnpackFiles", "archive-extract", "Entpacken"],
    ["-", "", ""],
    ["cm_SearchFor", "edit-find", "Dateien suchen"],
    ["cm_MultiRenameFiles", "edit-rename", "Mehrfach-Umbenennen"],
    ["cm_CompareDirs", "view-split-left-right", "Verzeichnisse vergleichen"],
    ["cm_SyncDirs", "folder-sync", "Verzeichnisse synchronisieren"],
    ["cm_CompareFilesByContent", "document-compare", "Nach Inhalt vergleichen"],
    ["-", "", ""],
    ["cm_OpenTerminal", "utilities-terminal", "Terminal öffnen"],
    ["cm_ConfigShowHidden", "view-hidden", "Versteckte Dateien"],
    ["cm_Config", "preferences-system", "Einstellungen"],
]

OLD_DEFAULT_BUTTONS = [list(b) for b in DEFAULT_BUTTONS]

DEFAULT_BUTTONS = [
    ["cm_RereadSource", "", "Neu einlesen"],
    ["-", "", ""],
    ["cm_BriefView", "", "Kurzansicht"],
    ["cm_FullView", "", "Vollansicht"],
    ["cm_ThumbnailsView", "", "Miniaturansicht"],
    ["cm_TreeView", "", "Verzeichnisbaum"],
    ["cm_QuickView", "", "Schnellansicht"],
    ["-", "", ""],
    ["cm_View", "", "Ansehen"],
    ["cm_Edit", "", "Bearbeiten"],
    ["cm_Copy", "", "Kopieren"],
    ["cm_RenMov", "", "Verschieben/Umbenennen"],
    ["cm_MkDir", "", "Neues Verzeichnis"],
    ["cm_Delete", "", "Löschen"],
    ["-", "", ""],
    ["cm_SelectAll", "", "Alle markieren"],
    ["cm_InvertSelection", "", "Markierung umkehren"],
    ["cm_CopyNamesToClip", "", "Dateinamen kopieren"],
    ["-", "", ""],
    ["cm_PackFiles", "", "Packen"],
    ["cm_UnpackFiles", "", "Entpacken"],
    ["-", "", ""],
    ["cm_SearchFor", "", "Dateien suchen"],
    ["cm_MultiRenameFiles", "", "Mehrfach-Umbenennen"],
    ["cm_CompareDirs", "", "Verzeichnisse vergleichen"],
    ["cm_SyncDirs", "", "Verzeichnisse synchronisieren"],
    ["cm_CompareFilesByContent", "", "Nach Inhalt vergleichen"],
    ["cm_CalcSpace", "", "Belegten Speicher berechnen"],
    ["-", "", ""],
    ["cm_DirHotlist", "", "Verzeichnis-Hotlist"],
    ["cm_SwapPanels", "", "Fenster tauschen"],
    ["cm_TargetEqualSource", "", "Ziel = Quelle"],
    ["cm_OpenNewTab", "", "Neuer Tab"],
    ["-", "", ""],
    ["cm_ConnectNetwork", "", "FTP-/Netzwerkverbindung"],
    ["cm_DisconnectNetwork", "", "Verbindung trennen"],
    ["-", "", ""],
    ["cm_OpenTerminal", "", "Terminal öffnen"],
    ["cm_ConfigShowHidden", "", "Versteckte Dateien"],
    ["cm_Config", "", "Einstellungen"],
]

DEFAULTS = {
    "show_hidden": False,
    "dirs_first": True,
    "confirm_delete": True,
    "use_trash": True,
    "confirm_overwrite": True,
    "quicksearch_mode": "alt",  # letters | ctrlalt | alt
    "editor": "",
    "viewer": "",  # empty = internal Lister
    "terminal": "",
    "font_family": "",
    "font_size": 0,
    "date_format": "dd.MM.yyyy HH:mm",
    "size_format": "bytes",  # bytes | dynamic
    "show_buttonbar": True,
    "show_drivebar": True,
    "show_cmdline": True,
    "show_fkeys": True,
    "show_tabs_always": False,
    "show_icons": True,
    "mark_with_right_mouse": False,
    "geometry": None,
    "splitter": None,
    "left": {"tabs": [], "active": 0},
    "right": {"tabs": [], "active": 0},
    "active_panel": "left",
    "hotlist": [],
    "cmd_history": [],
    "search_history": [],
    "rename_history": [],
    "buttons": DEFAULT_BUTTONS,
    "user_hotkeys": {},
    "columns": [260, 60, 100, 130, 90],
    # added in 1.1
    "show_drivebuttons": True,
    "show_dotdot": True,
    "natural_sort": True,
    "case_sensitive_sort": False,
    "alt_rows": False,
    "col_ext": True,
    "col_size": True,
    "col_date": True,
    "col_attr": True,
    "theme": "system",
    "color_mark": "",
    "color_text": "",
    "color_bg": "",
    "color_cursor": "",
    "color_cursor_text": "",
    "confirm_exit": False,
    "confirm_drop": True,
    "dblclick_up": True,
    "space_moves_down": True,
    "use_internal_editor": True,
    "editor_wrap": False,
    "editor_line_numbers": True,
    "editor_tab_width": 4,
    "editor_font_size": 0,
    "lister_wrap": True,
    "start_left": "",
    "start_right": "",
    "drive_letters": {},
    # added in 1.2
    "qs_mode_v2": False,
    "qs_show_dialog": True,
    "qs_match_begin": True,
    "qs_match_end": False,
    "qs_filter": False,
    "qs_kind": "both",
    "select_all_dirs": True,
    "select_group_dirs": False,
    "plusminus_main": True,
}


class Config(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.load()
        if not self.get("qs_alt_only"):
            # 1.3: quick search only with Alt+letters by default
            self["quicksearch_mode"] = "alt"
            self["qs_alt_only"] = True
        if [list(b) for b in self.get("buttons", [])] == OLD_DEFAULT_BUTTONS:
            # untouched old button bar: switch to the new, larger default set
            self["buttons"] = json.loads(json.dumps(DEFAULT_BUTTONS))
        if not self.get("qs_tc_dialog"):
            # 1.4: like Total Commander, Alt+letters shows the search box below the panel
            self["qs_show_dialog"] = True
            self["qs_tc_dialog"] = True
        if not self.get("editor"):
            self["editor"] = _first_installed(
                ["gnome-text-editor", "gedit", "kate", "kwrite", "mousepad", "xed", "pluma", "featherpad",
                 "geany", "code"], "xdg-open")
        if not self.get("terminal"):
            self["terminal"] = _first_installed(
                ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "mate-terminal",
                 "tilix", "kitty", "alacritty", "lxterminal", "xterm"], "xterm")

    def load(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.update(data)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, CONFIG_FILE)
        except OSError:
            pass

    def push_history(self, key, value, limit=50):
        if not value:
            return
        hist = [h for h in self.get(key, []) if h != value]
        hist.insert(0, value)
        self[key] = hist[:limit]


config = Config()
