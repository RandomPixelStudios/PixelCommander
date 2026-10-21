"""Helper functions: formatting, wildcard masks, mounts, trash, launching programs."""
import datetime
import fnmatch
import os
import re
import shlex
import shutil
import stat
import subprocess
import urllib.parse

from .config import config
from .qt import QtCore, QtGui, QtWidgets


# ---------------------------------------------------------------- formatting

def format_size(n, mode=None):
    if n is None:
        return ""
    mode = mode or config.get("size_format", "bytes")
    if mode == "bytes":
        return "{:,}".format(n).replace(",", ".")
    return human_size(n)


def human_size(n):
    if n is None:
        return ""
    units = ["B", "k", "M", "G", "T", "P"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            if u == "B":
                return "%d B" % n
            return ("%.1f %s" % (f, u)).replace(".", ",")
        f /= 1024.0
    return str(n)


def format_time(ts):
    if ts is None:
        return ""
    dt = QtCore.QDateTime.fromSecsSinceEpoch(int(ts))
    return dt.toString(config.get("date_format", "dd.MM.yyyy HH:mm"))


def format_mode(mode):
    if mode is None:
        return ""
    return stat.filemode(mode)


def split_ext(name, is_dir=False):
    """TC style: extension is everything after the last dot (not for leading dots / dirs)."""
    if is_dir or name == "..":
        return name, ""
    i = name.rfind(".")
    if i <= 0:
        return name, ""
    return name[:i], name[i + 1:]


# ---------------------------------------------------------------- masks

class Mask:
    """Total Commander like file mask: "*.txt *.doc | *.bak dir\\".

    Patterns are separated by spaces or ';'. Everything after '|' excludes.
    A pattern ending in '/' or '\\' only applies to directories.
    """

    def __init__(self, text="*"):
        self.text = (text or "*").strip() or "*"
        inc, _, exc = self.text.partition("|")
        self.include = self._parse(inc) or [("*", False)]
        self.exclude = self._parse(exc)

    @staticmethod
    def _parse(part):
        pats = []
        try:
            tokens = shlex.split(part.replace(";", " "))
        except ValueError:
            tokens = part.replace(";", " ").split()
        for t in tokens:
            dir_only = t.endswith("/") or t.endswith("\\")
            t = t.rstrip("/\\")
            if t == "*.*":
                t = "*"
            if t:
                pats.append((t.lower(), dir_only))
        return pats

    def _hit(self, pats, name, is_dir):
        n = name.lower()
        for p, dir_only in pats:
            if dir_only and not is_dir:
                continue
            if fnmatch.fnmatchcase(n, p):
                return True
            # TC: "*.txt" style; "name.*" should also match "name"
            if p.endswith(".*") and fnmatch.fnmatchcase(n, p[:-2]):
                return True
        return False

    def match(self, name, is_dir=False):
        if self.exclude and self._hit(self.exclude, name, is_dir):
            return False
        if is_dir and all(not d for _p, d in self.include) and self.text.strip() in ("*", "*.*"):
            return True
        return self._hit(self.include, name, is_dir)


# ---------------------------------------------------------------- mounts / drives

PSEUDO_FS = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "securityfs", "pstore",
             "debugfs", "tracefs", "configfs", "fusectl", "mqueue", "hugetlbfs", "bpf", "autofs", "binfmt_misc",
             "efivarfs", "rpc_pipefs", "nsfs", "ramfs", "squashfs", "overlay", "fuse.portal", "fuse.gvfsd-fuse",
             "selinuxfs", "fuse.snapfuse", "nfsd"}


def list_drives():
    """Return list of (label, path, icon_name)."""
    home = os.path.expanduser("~")
    drives = [("/", "/", "drive-harddisk"), ("~", home, "user-home")]
    seen = {"/", home}
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        lines = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mnt, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype in PSEUDO_FS or mnt in seen:
            continue
        if mnt.startswith(("/proc", "/sys", "/dev", "/run/user", "/snap", "/var/lib/docker", "/boot/efi")):
            continue
        if mnt.startswith("/run") and not mnt.startswith("/run/media"):
            continue
        seen.add(mnt)
        icon = "drive-removable-media" if mnt.startswith(("/media", "/run/media", "/mnt")) else "drive-harddisk"
        if fstype.startswith(("nfs", "cifs", "smb", "sshfs", "fuse.sshfs")):
            icon = "folder-remote"
        drives.append((os.path.basename(mnt) or mnt, mnt, icon))
    gvfs = "/run/user/%d/gvfs" % os.getuid()
    if os.path.isdir(gvfs):
        try:
            for n in sorted(os.listdir(gvfs)):
                drives.append((n.split("=", 1)[-1][:24], os.path.join(gvfs, n), "folder-remote"))
        except OSError:
            pass
    return drives


def disk_free(path):
    try:
        u = shutil.disk_usage(path)
        return u.free, u.total
    except OSError:
        return None, None


def mount_point(path):
    path = os.path.realpath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


# ---------------------------------------------------------------- trash (freedesktop.org spec)

def _trash_dir_for(path):
    home_trash = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    try:
        if os.lstat(path).st_dev == os.stat(os.path.expanduser("~")).st_dev:
            return home_trash
    except OSError:
        return home_trash
    top = mount_point(path)
    uid = os.getuid()
    cand = os.path.join(top, ".Trash", str(uid))
    shared = os.path.join(top, ".Trash")
    if os.path.isdir(shared) and not os.path.islink(shared) and os.stat(shared).st_mode & stat.S_ISVTX:
        return cand
    return os.path.join(top, ".Trash-%d" % uid)


def move_to_trash(path):
    """Move path to the trash. Raises OSError on failure."""
    gio = shutil.which("gio")
    trash = _trash_dir_for(path)
    files = os.path.join(trash, "files")
    info = os.path.join(trash, "info")
    try:
        os.makedirs(files, mode=0o700, exist_ok=True)
        os.makedirs(info, mode=0o700, exist_ok=True)
    except OSError:
        if gio and subprocess.call([gio, "trash", "--", path], stderr=subprocess.DEVNULL) == 0:
            return
        raise
    base = os.path.basename(path.rstrip("/")) or "file"
    name = base
    i = 1
    while True:
        info_path = os.path.join(info, name + ".trashinfo")
        try:
            fd = os.open(info_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            i += 1
            stem, ext = os.path.splitext(base)
            name = "%s.%d%s" % (stem, i, ext)
    abspath = os.path.abspath(path)
    if trash.startswith(mount_point(path)) and not trash.startswith(os.path.expanduser("~")):
        rel = os.path.relpath(abspath, mount_point(path))
    else:
        rel = abspath
    with os.fdopen(fd, "w") as fh:
        fh.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (
            urllib.parse.quote(rel), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    try:
        os.rename(path, os.path.join(files, name))
    except OSError:
        os.unlink(info_path)
        if gio and subprocess.call([gio, "trash", "--", path], stderr=subprocess.DEVNULL) == 0:
            return
        raise


# ---------------------------------------------------------------- launching

def _detach(args, cwd=None):
    try:
        subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def open_default(path, cwd=None):
    for opener in ("xdg-open", "gio"):
        exe = shutil.which(opener)
        if exe:
            args = [exe, path] if opener == "xdg-open" else [exe, "open", path]
            return _detach(args, cwd=cwd or os.path.dirname(path))
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def run_command_template(template, path=None, cwd=None):
    """Run "editor %s" or "editor" with path appended."""
    try:
        parts = shlex.split(template)
    except ValueError:
        parts = template.split()
    if not parts:
        return False
    if path is not None:
        if any("%s" in p for p in parts):
            parts = [p.replace("%s", path) for p in parts]
        else:
            parts.append(path)
    if parts[0] == "xdg-open" and path:
        return open_default(path, cwd)
    return _detach(parts, cwd=cwd)


def terminal_args(cmd=None, cwd=None, hold=True):
    term = config.get("terminal") or "xterm"
    exe = shlex.split(term)
    name = os.path.basename(exe[0])
    if not cmd:
        if name in ("gnome-terminal", "mate-terminal", "xfce4-terminal", "tilix"):
            return exe + ["--working-directory=" + (cwd or os.getcwd())]
        if name == "konsole":
            return exe + ["--workdir", cwd or os.getcwd()]
        return exe
    shell_cmd = cmd + ('; echo; read -p "[Enter] zum Schließen" _' if hold else "")
    if name in ("gnome-terminal", "tilix"):
        return exe + ["--", "bash", "-c", shell_cmd]
    if name in ("xfce4-terminal", "mate-terminal", "lxterminal"):
        return exe + ["-x", "bash", "-c", shell_cmd]
    if name in ("kitty", "alacritty") and name == "kitty":
        return exe + ["bash", "-c", shell_cmd]
    return exe + ["-e", "bash", "-c", shell_cmd]


def open_terminal(cwd, cmd=None, hold=True):
    return _detach(terminal_args(cmd, cwd, hold), cwd=cwd)


def is_executable_file(path):
    try:
        st = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode) or not os.access(path, os.X_OK):
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
        return head == b"\x7fELF" or head[:2] == b"#!"
    except OSError:
        return False


# ---------------------------------------------------------------- icons

class IconCache:
    def __init__(self):
        self.db = QtCore.QMimeDatabase()
        self.cache = {}
        self.provider = QtWidgets.QFileIconProvider()
        style = QtWidgets.QApplication.style()
        from .winicons import win_icon
        self.folder = win_icon("folder") or QtGui.QIcon.fromTheme(
            "folder", style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        self.file = QtGui.QIcon.fromTheme("text-x-generic",
                                          style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon))
        self.up = QtGui.QIcon.fromTheme("go-up", style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogToParent))
        self.link = QtGui.QIcon.fromTheme("emblem-symbolic-link", self.file)
        self.exe = QtGui.QIcon.fromTheme("application-x-executable", self.file)

    def for_name(self, name, is_dir=False):
        if name == "..":
            return self.up
        if is_dir:
            return self.folder
        _b, ext = split_ext(name)
        key = ext.lower()
        ic = self.cache.get(key)
        if ic is None:
            from .winicons import file_icon
            ic = file_icon(key)
        if ic is None:
            mt = self.db.mimeTypeForFile(name, QtCore.QMimeDatabase.MatchMode.MatchExtension)
            ic = QtGui.QIcon.fromTheme(mt.iconName())
            if ic.isNull():
                ic = QtGui.QIcon.fromTheme(mt.genericIconName())
            if ic.isNull():
                ic = self.file
            self.cache[key] = ic
        return ic

    def mime(self, path):
        return self.db.mimeTypeForFile(path).name()


_icons = None


def icons():
    global _icons
    if _icons is None:
        _icons = IconCache()
    return _icons


def theme_icon(name, fallback=None):
    from .winicons import win_icon
    win = win_icon(name)
    if win is not None:
        return win
    ic = QtGui.QIcon.fromTheme(name)
    if ic.isNull() and fallback is not None:
        return QtWidgets.QApplication.style().standardIcon(fallback)
    return ic


# ---------------------------------------------------------------- misc

def find_dir_nocase(path):
    """Existing directory for path, matching each component case-insensitively if needed (or None)."""
    path = os.path.normpath(path)
    if os.path.isdir(path):
        return path
    cur = "/"
    for part in [x for x in path.split("/") if x]:
        nxt = os.path.join(cur, part)
        if not os.path.isdir(nxt):
            try:
                cands = [n for n in os.listdir(cur) if n.lower() == part.lower() and os.path.isdir(os.path.join(cur, n))]
            except OSError:
                return None
            if not cands:
                return None
            nxt = os.path.join(cur, cands[0])
        cur = nxt
    return cur


def unique_name(path):
    if not os.path.lexists(path):
        return path
    d, n = os.path.split(path)
    stem, ext = os.path.splitext(n)
    i = 2
    while True:
        c = os.path.join(d, "%s (%d)%s" % (stem, i, ext))
        if not os.path.lexists(c):
            return c
        i += 1


def natural_key(s):
    if not config.get("natural_sort", True):
        return [s if config.get("case_sensitive_sort") else s.lower()]
    if config.get("case_sensitive_sort"):
        return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s.lower())]


def is_text_file(path, probe=8192):
    try:
        with open(path, "rb") as fh:
            data = fh.read(probe)
    except OSError:
        return False
    return b"\x00" not in data


def text_icon(text, size=22):
    """Fallback icon: short text on a rounded square (used when the icon theme lacks an icon)."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pal = QtWidgets.QApplication.palette()
    p.setBrush(pal.color(QtGui.QPalette.ColorRole.Button).darker(115))
    p.setPen(pal.color(QtGui.QPalette.ColorRole.Mid))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    f = p.font()
    f.setPixelSize(int(size * (0.42 if len(text) > 2 else 0.5)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(pal.color(QtGui.QPalette.ColorRole.ButtonText))
    p.drawText(QtCore.QRect(0, 0, size, size), int(QtCore.Qt.AlignmentFlag.AlignCenter), text[:3])
    p.end()
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- drive letters

LETTERS = "cdefghijklmnopqrstuvwxyzab"


def drive_letters(drives=None):
    """Return [(letter, label, path, icon)] sorted by letter. Letters are stable (stored in the config)."""
    if drives is None:
        drives = list_drives()
    mapping = dict(config.get("drive_letters") or {})
    used = set(mapping.values())
    changed = False
    out = []
    home = os.path.expanduser("~")
    for label, path, icon in drives:
        letter = mapping.get(path)
        if not letter:
            pref = "c" if path == "/" else ("h" if path == home else None)
            if pref and pref not in used:
                letter = pref
            else:
                letter = next((c for c in LETTERS if c not in used and c not in ("c", "h")), None) or \
                    next((c for c in LETTERS if c not in used), "")
            if letter:
                mapping[path] = letter
                used.add(letter)
                changed = True
        out.append((letter, label, path, icon))
    if changed:
        config["drive_letters"] = mapping
        config.save()
    out.sort(key=lambda t: (t[0] == "", LETTERS.index(t[0]) if t[0] in LETTERS else 99, t[2]))
    return out


def path_for_letter(letter):
    letter = letter.lower()
    for l, _label, path, _icon in drive_letters():
        if l == letter:
            return path
    for path, l in (config.get("drive_letters") or {}).items():
        if l == letter and os.path.isdir(path):
            return path
    return None


_DRIVE_RX = re.compile(r"^([A-Za-z]):(?:[\\/](.*))?$")


def expand_drive(location):
    """"c:" / "D:\\sub" / "d:/sub" -> real path, otherwise unchanged."""
    m = _DRIVE_RX.match(location.strip())
    if not m:
        return location
    base = path_for_letter(m.group(1))
    if not base:
        return location
    rest = (m.group(2) or "").replace("\\", "/").strip("/")
    return os.path.join(base, rest) if rest else base


# ---------------------------------------------------------------- theme

_orig_theme = {}


def apply_theme(name):
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if not _orig_theme:
        _orig_theme["style"] = app.style().objectName()
        _orig_theme["pal"] = QtGui.QPalette(app.palette())
    if _orig_theme.get("current") == name:
        return
    _orig_theme["current"] = name
    R = QtGui.QPalette.ColorRole
    if name == "dark":
        app.setStyle("Fusion")
        p = QtGui.QPalette()
        base, win, text = QtGui.QColor(36, 36, 40), QtGui.QColor(48, 48, 53), QtGui.QColor(225, 225, 225)
        for role, col in [(R.Window, win), (R.WindowText, text), (R.Base, base), (R.AlternateBase, QtGui.QColor(44, 44, 49)),
                          (R.ToolTipBase, win), (R.ToolTipText, text), (R.Text, text), (R.Button, win),
                          (R.ButtonText, text), (R.BrightText, QtGui.QColor(255, 80, 80)),
                          (R.Highlight, QtGui.QColor(42, 110, 190)), (R.HighlightedText, QtGui.QColor(255, 255, 255)),
                          (R.Link, QtGui.QColor(90, 160, 255)), (R.Mid, QtGui.QColor(70, 70, 76)),
                          (R.Dark, QtGui.QColor(25, 25, 28)), (R.Light, QtGui.QColor(70, 70, 76))]:
            p.setColor(role, col)
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, R.Text, QtGui.QColor(120, 120, 120))
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, R.ButtonText, QtGui.QColor(120, 120, 120))
        app.setPalette(p)
    elif name == "light":
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
    else:
        if _orig_theme.get("style"):
            app.setStyle(_orig_theme["style"])
        app.setPalette(_orig_theme["pal"])
