"""Virtual file systems: local directories, archives (zip/tar/7z) and search results."""
import os
import posixpath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import zipfile


class Entry:
    __slots__ = ("name", "is_dir", "size", "mtime", "mode", "is_link", "link_target", "path", "uid", "gid",
                 "dir_size", "broken")

    def __init__(self, name, is_dir, size=0, mtime=None, mode=None, path=None, is_link=False, link_target=None,
                 uid=None, gid=None):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.mode = mode
        self.path = path
        self.is_link = is_link
        self.link_target = link_target
        self.uid = uid
        self.gid = gid
        self.dir_size = None
        self.broken = False

    @property
    def is_up(self):
        return self.name == ".."


def local_entry(path, name=None):
    name = name or os.path.basename(path) or path
    try:
        lst = os.lstat(path)
    except OSError:
        return None
    is_link = stat.S_ISLNK(lst.st_mode)
    st = lst
    target = None
    broken = False
    if is_link:
        try:
            target = os.readlink(path)
        except OSError:
            target = "?"
        try:
            st = os.stat(path)
        except OSError:
            broken = True
    is_dir = stat.S_ISDIR(st.st_mode)
    e = Entry(name, is_dir, 0 if is_dir else st.st_size, st.st_mtime, lst.st_mode if is_link else st.st_mode,
              path, is_link, target, st.st_uid, st.st_gid)
    e.broken = broken
    return e


class LocalFS:
    kind = "local"
    is_local = True
    writable = True

    def list(self, path, show_hidden=True):
        entries = []
        with os.scandir(path) as it:
            for de in it:
                if not show_hidden and de.name.startswith("."):
                    continue
                e = local_entry(de.path, de.name)
                if e is not None:
                    entries.append(e)
        return entries

    @staticmethod
    def parent(path):
        p = os.path.dirname(path.rstrip("/")) or "/"
        return p

    @staticmethod
    def join(path, name):
        return os.path.join(path, name)

    def display(self, path):
        return path


ARCHIVE_EXT = (".zip", ".jar", ".apk", ".war", ".epub", ".odt", ".ods", ".docx", ".xlsx", ".cbz",
               ".tar", ".tgz", ".tar.gz", ".tbz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz", ".tar.zst", ".tzst",
               ".7z", ".rar", ".cbr", ".iso", ".cab", ".arj", ".lzh", ".deb", ".rpm", ".cpio", ".xz", ".gz", ".bz2")
PACK_FORMATS = ["zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "7z"]


def sevenzip():
    for c in ("7z", "7zz", "7za", "7zr"):
        p = shutil.which(c)
        if p:
            return p
    return None


def is_archive_name(name):
    n = name.lower()
    return n.endswith(ARCHIVE_EXT)


def archive_backend(path):
    n = path.lower()
    if zipfile.is_zipfile(path):
        return "zip"
    if n.endswith((".gz", ".bz2", ".xz")) and not n.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        try:
            if tarfile.is_tarfile(path):
                return "tar"
        except (OSError, tarfile.TarError, EOFError):
            pass
        return "7z" if sevenzip() else None
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, tarfile.TarError, EOFError, Exception):
        pass
    if sevenzip() or (n.endswith((".rar", ".cbr")) and shutil.which("unrar")):
        return "7z" if sevenzip() else "unrar"
    if shutil.which("bsdtar"):
        return "bsdtar"
    return None


class ArchiveError(Exception):
    pass


_archive_cache = {}


class ArchiveFS:
    kind = "archive"
    is_local = False
    writable = False

    def __init__(self, archive):
        self.archive = archive
        self.backend = archive_backend(archive)
        if not self.backend:
            raise ArchiveError("Archivformat wird nicht unterstützt (für 7z/rar bitte p7zip-full / 7zip installieren)")
        self.tree = {"": {}}  # dir -> {name: Entry}
        self._load()

    # -- loading
    def _add(self, name, is_dir, size, mtime, mode):
        name = name.replace("\\", "/").lstrip("/")
        while name.startswith("./"):
            name = name[2:]
        name = name.rstrip("/")
        if not name or name == ".":
            return
        parts = name.split("/")
        for i in range(len(parts) - 1):
            d = "/".join(parts[:i])
            sub = "/".join(parts[:i + 1])
            self.tree.setdefault(d, {})
            if parts[i] not in self.tree[d]:
                self.tree[d][parts[i]] = Entry(parts[i], True, 0, mtime, stat.S_IFDIR | 0o755, sub)
            self.tree.setdefault(sub, {})
        d = "/".join(parts[:-1])
        self.tree.setdefault(d, {})
        existing = self.tree[d].get(parts[-1])
        if is_dir:
            self.tree.setdefault(name, {})
            if existing is not None:
                existing.mtime = mtime or existing.mtime
                return
        self.tree[d][parts[-1]] = Entry(parts[-1], is_dir, 0 if is_dir else size, mtime,
                                        mode or ((stat.S_IFDIR | 0o755) if is_dir else (stat.S_IFREG | 0o644)), name)

    def _load(self):
        try:
            if self.backend == "zip":
                with zipfile.ZipFile(self.archive) as zf:
                    for zi in zf.infolist():
                        mt = time.mktime(zi.date_time + (0, 0, -1))
                        mode = (zi.external_attr >> 16) or None
                        self._add(zi.filename, zi.is_dir(), zi.file_size, mt, mode)
            elif self.backend == "tar":
                with tarfile.open(self.archive) as tf:
                    for ti in tf:
                        self._add(ti.name, ti.isdir(), ti.size, ti.mtime,
                                  (stat.S_IFDIR if ti.isdir() else stat.S_IFREG) | ti.mode)
            elif self.backend == "7z":
                self._load_7z()
            elif self.backend == "unrar":
                self._load_unrar()
            elif self.backend == "bsdtar":
                self._load_bsdtar()
        except ArchiveError:
            raise
        except Exception as ex:  # noqa: BLE001 - archive libs raise many types
            raise ArchiveError(str(ex))

    def _load_7z(self):
        out = subprocess.run([sevenzip(), "l", "-slt", "-ba", "--", self.archive], capture_output=True,
                             text=True, errors="replace")
        if out.returncode != 0 and not out.stdout:
            raise ArchiveError(out.stderr.strip() or "7z Fehler")
        rec = {}
        for line in out.stdout.splitlines() + [""]:
            if not line.strip():
                if "Path" in rec:
                    is_dir = rec.get("Folder") == "+" or rec.get("Attributes", "").startswith("D")
                    mt = None
                    m = rec.get("Modified", "")
                    if m:
                        try:
                            mt = time.mktime(time.strptime(m[:19], "%Y-%m-%d %H:%M:%S"))
                        except ValueError:
                            mt = None
                    try:
                        size = int(rec.get("Size") or 0)
                    except ValueError:
                        size = 0
                    self._add(rec["Path"], is_dir, size, mt, None)
                rec = {}
                continue
            k, sep, v = line.partition(" = ")
            if sep:
                rec[k.strip()] = v

    def _load_unrar(self):
        out = subprocess.run(["unrar", "lb", self.archive], capture_output=True, text=True, errors="replace")
        for line in out.stdout.splitlines():
            self._add(line, False, 0, None, None)

    def _load_bsdtar(self):
        out = subprocess.run(["bsdtar", "-tf", self.archive], capture_output=True, text=True, errors="replace")
        if out.returncode != 0:
            raise ArchiveError(out.stderr.strip())
        for line in out.stdout.splitlines():
            self._add(line, line.endswith("/"), 0, None, None)

    # -- api
    def list(self, inner, show_hidden=True):
        inner = inner.strip("/")
        if inner not in self.tree:
            raise FileNotFoundError(inner)
        return [e for e in self.tree[inner].values() if show_hidden or not e.name.startswith(".")]

    def exists_dir(self, inner):
        return inner.strip("/") in self.tree

    @staticmethod
    def parent(inner):
        return posixpath.dirname(inner.strip("/"))

    @staticmethod
    def join(inner, name):
        return posixpath.join(inner, name) if inner else name

    def display(self, inner):
        return self.archive + ("/" + inner if inner else "")

    def members_under(self, inner):
        """All file/dir inner paths below inner (recursive), including inner itself."""
        inner = inner.strip("/")
        res = [inner]
        if inner in self.tree:
            stack = [inner]
            while stack:
                d = stack.pop()
                for e in self.tree.get(d, {}).values():
                    res.append(e.path)
                    if e.is_dir:
                        stack.append(e.path)
        return res

    def total_size(self, inner_paths):
        tot = 0
        for p in inner_paths:
            for m in self.members_under(p):
                d, n = posixpath.split(m)
                e = self.tree.get(d, {}).get(n)
                if e and not e.is_dir:
                    tot += e.size
        return tot

    def extract(self, inner_paths, base_inner, dest, progress=None, cancelled=None):
        """Extract given entries (paths relative to archive root) into dest, stripping base_inner."""
        base = base_inner.strip("/")
        wanted = set()
        for p in inner_paths:
            wanted.update(self.members_under(p))

        def rel(name):
            name = name.replace("\\", "/").lstrip("/")
            while name.startswith("./"):
                name = name[2:]
            name = name.rstrip("/")
            return name

        def target(name):
            r = rel(name)
            if base:
                r = r[len(base) + 1:]
            out = os.path.normpath(os.path.join(dest, r))
            if not (out == dest or out.startswith(os.path.normpath(dest) + os.sep)):
                raise ArchiveError("Unsicherer Pfad im Archiv: " + name)
            return out

        if self.backend == "zip":
            with zipfile.ZipFile(self.archive) as zf:
                for zi in zf.infolist():
                    if cancelled and cancelled():
                        return
                    if rel(zi.filename) not in wanted:
                        continue
                    out = target(zi.filename)
                    if zi.is_dir():
                        os.makedirs(out, exist_ok=True)
                        continue
                    if progress:
                        progress(rel(zi.filename), 0)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with zf.open(zi) as src, open(out, "wb") as dst:
                        while True:
                            buf = src.read(1 << 20)
                            if not buf:
                                break
                            dst.write(buf)
                            if progress:
                                progress(None, len(buf))
                    mode = zi.external_attr >> 16
                    if mode & 0o777:
                        os.chmod(out, mode & 0o777)
                    mt = time.mktime(zi.date_time + (0, 0, -1))
                    os.utime(out, (mt, mt))
        elif self.backend == "tar":
            with tarfile.open(self.archive) as tf:
                for ti in tf:
                    if cancelled and cancelled():
                        return
                    if rel(ti.name) not in wanted:
                        continue
                    out = target(ti.name)
                    if ti.isdir():
                        os.makedirs(out, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    if ti.issym():
                        if os.path.lexists(out):
                            os.unlink(out)
                        os.symlink(ti.linkname, out)
                        continue
                    if not ti.isfile():
                        continue
                    if progress:
                        progress(rel(ti.name), 0)
                    src = tf.extractfile(ti)
                    with src, open(out, "wb") as dst:
                        while True:
                            buf = src.read(1 << 20)
                            if not buf:
                                break
                            dst.write(buf)
                            if progress:
                                progress(None, len(buf))
                    os.chmod(out, ti.mode & 0o777)
                    os.utime(out, (ti.mtime, ti.mtime))
        else:
            tmp = tempfile.mkdtemp(prefix="sc-x-", dir=dest if os.access(dest, os.W_OK) else None)
            try:
                names = list(inner_paths)
                if self.backend == "7z":
                    cmd = [sevenzip(), "x", "-y", "-o" + tmp, "--", self.archive] + names
                elif self.backend == "unrar":
                    cmd = ["unrar", "x", "-o+", self.archive] + names + [tmp + "/"]
                else:
                    cmd = ["bsdtar", "-xf", self.archive, "-C", tmp] + names
                if progress:
                    progress(os.path.basename(self.archive), 0)
                r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
                if r.returncode != 0:
                    raise ArchiveError(r.stderr.strip() or r.stdout.strip()[-400:])
                src_base = os.path.join(tmp, base) if base else tmp
                for p in names:
                    s = os.path.join(tmp, p)
                    d = os.path.join(dest, os.path.relpath(s, src_base))
                    if os.path.isdir(s) and os.path.isdir(d):
                        shutil.copytree(s, d, dirs_exist_ok=True, symlinks=True)
                    else:
                        if os.path.lexists(d):
                            if os.path.isdir(d) and not os.path.islink(d):
                                shutil.rmtree(d)
                            else:
                                os.unlink(d)
                        os.makedirs(os.path.dirname(d), exist_ok=True)
                        shutil.move(s, d)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    def extract_temp(self, inner):
        d = tempfile.mkdtemp(prefix="pixelcommander-")
        self.extract([inner], posixpath.dirname(inner), d)
        return os.path.join(d, posixpath.basename(inner))


def get_archive_fs(path):
    try:
        mt = os.stat(path).st_mtime
    except OSError as ex:
        raise ArchiveError(str(ex))
    c = _archive_cache.get(path)
    if c and c[0] == mt:
        return c[1]
    fs = ArchiveFS(path)
    _archive_cache[path] = (mt, fs)
    if len(_archive_cache) > 8:
        _archive_cache.pop(next(iter(_archive_cache)))
    return fs


class ResultFS:
    """Feed-to-listbox: shows a flat list of real files (e.g. search results)."""
    kind = "results"
    is_local = True
    writable = False
    counter = 0

    def __init__(self, paths, base, title="Suchergebnisse"):
        ResultFS.counter += 1
        self.id = ResultFS.counter
        self.paths = list(paths)
        self.base = base
        self.title = title

    def list(self, inner, show_hidden=True):
        res = []
        for p in self.paths:
            try:
                name = os.path.relpath(p, self.base)
            except ValueError:
                name = p
            if name.startswith(".."):
                name = p
            e = local_entry(p, name)
            if e is not None:
                res.append(e)
        return res

    @staticmethod
    def parent(inner):
        return None

    @staticmethod
    def join(inner, name):
        return name

    def display(self, inner):
        return "[%s: %d]" % (self.title, len(self.paths))


_results = {}


def register_results(fs):
    _results[fs.id] = fs
    return "results://%d" % fs.id


LOCAL = LocalFS()


def is_url(location):
    return location.lower().startswith(("ftp://", "ftps://", "sftp://"))


def resolve(location):
    """Map a location string to (fs, inner path)."""
    if location.startswith("results://"):
        try:
            return _results[int(location[10:])], ""
        except (KeyError, ValueError):
            raise FileNotFoundError(location)
    from . import ftpfs
    if ftpfs.is_ftp_url(location):
        return ftpfs.resolve(location)
    location = os.path.expanduser(location)
    if not location.startswith("/"):
        location = os.path.abspath(location)
    location = os.path.normpath(location)
    if os.path.isdir(location):
        return LOCAL, location
    # find archive component
    probe = location
    rest = []
    while probe and probe != "/":
        if os.path.isfile(probe):
            fs = get_archive_fs(probe)
            inner = "/".join(reversed(rest))
            if not fs.exists_dir(inner):
                raise FileNotFoundError(location)
            return fs, inner
        if os.path.exists(probe):
            break
        probe, tail = os.path.split(probe)
        rest.append(tail)
    raise FileNotFoundError(location)


def location_of(fs, inner):
    if fs.kind == "local":
        return inner
    if fs.kind in ("archive", "ftp"):
        return fs.display(inner)
    return "results://%d" % fs.id
