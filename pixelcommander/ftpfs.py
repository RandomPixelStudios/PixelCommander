"""FTP/FTPS file system (ftplib) for the panels: ftp://user@host:port/path."""
import ftplib
import os
import posixpath
import stat
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urlsplit

CHUNK = 1 << 16

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"), 1)}


class FtpError(OSError):
    pass


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except FtpError:
            raise
        except ftplib.all_errors as ex:
            raise FtpError(str(ex)) from ex
    return inner


def _parse_mdtm(v):
    try:
        return time.mktime(time.strptime(v[:14], "%Y%m%d%H%M%S")) - time.timezone
    except (ValueError, OverflowError):
        return None


def _parse_list_line(line):
    """Parse a unix style LIST line -> (name, is_dir, size, mtime, mode, link_target) or None."""
    parts = line.split(None, 8)
    if len(parts) < 9 or len(parts[0]) < 10:
        return None
    perms, size, mon, day, yt, name = parts[0], parts[4], parts[5], parts[6], parts[7], parts[8]
    typ = perms[0]
    target = None
    if typ == "l" and " -> " in name:
        name, target = name.split(" -> ", 1)
    mode = 0
    for i, ch in enumerate(perms[1:10]):
        if ch not in "-":
            mode |= 1 << (8 - i)
    mode |= {"d": stat.S_IFDIR, "l": stat.S_IFLNK}.get(typ, stat.S_IFREG)
    mtime = None
    try:
        m = _MONTHS[mon.lower()[:3]]
        if ":" in yt:
            now = time.localtime()
            year = now.tm_year
            hh, mm = yt.split(":")
            t = time.mktime((year, m, int(day), int(hh), int(mm), 0, 0, 0, -1))
            if t > time.time() + 86400:
                t = time.mktime((year - 1, m, int(day), int(hh), int(mm), 0, 0, 0, -1))
        else:
            t = time.mktime((int(yt), m, int(day), 0, 0, 0, 0, 0, -1))
        mtime = t
    except (KeyError, ValueError, OverflowError):
        pass
    try:
        size = int(size)
    except ValueError:
        size = 0
    return name, typ == "d", size, mtime, mode, target


class FtpFS:
    kind = "ftp"
    is_local = False
    writable = False

    def __init__(self, host, port=21, user="", password="", tls=False):
        self.host = host
        self.port = port or 21
        self.user = user or "anonymous"
        self.password = password
        self.tls = tls
        self._ftp = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------ connection
    @property
    def scheme(self):
        return "ftps" if self.tls else "ftp"

    @property
    def base_url(self):
        u = "" if self.user == "anonymous" else quote(self.user, safe="") + "@"
        p = "" if self.port == 21 else ":%d" % self.port
        return "%s://%s%s%s" % (self.scheme, u, self.host, p)

    def new_connection(self):
        ftp = ftplib.FTP_TLS(timeout=30) if self.tls else ftplib.FTP(timeout=30)
        ftp.encoding = "utf-8"
        ftp.connect(self.host, self.port)
        ftp.login(self.user, self.password or ("anonymous@" if self.user == "anonymous" else ""))
        if self.tls:
            ftp.prot_p()
        return ftp

    def conn(self):
        with self._lock:
            if self._ftp is not None:
                try:
                    self._ftp.voidcmd("NOOP")
                    return self._ftp
                except ftplib.all_errors:
                    self.close()
            self._ftp = self.new_connection()
            return self._ftp

    def close(self):
        with self._lock:
            if self._ftp is not None:
                try:
                    self._ftp.quit()
                except ftplib.all_errors:
                    pass
            self._ftp = None

    connect = _wrap(conn)

    # ------------------------------------------------------------ vfs api
    def _entry(self, inner, name, is_dir, size, mtime, mode, target=None):
        from .vfs import Entry
        return Entry(name, is_dir, 0 if is_dir else size, mtime, mode, posixpath.join(inner, name),
                     target is not None, target)

    @_wrap
    def list(self, inner, show_hidden=True, ftp=None):
        inner = inner or "/"
        ftp = ftp or self.conn()
        with self._lock:
            entries = []
            try:
                for name, facts in ftp.mlsd(inner, facts=["type", "size", "modify", "unix.mode"]):
                    t = facts.get("type", "").lower()
                    if t in ("cdir", "pdir") or name in (".", ".."):
                        continue
                    is_dir = t == "dir"
                    mode = int(facts["unix.mode"], 8) if "unix.mode" in facts else (0o755 if is_dir else 0o644)
                    mode |= stat.S_IFDIR if is_dir else stat.S_IFREG
                    entries.append(self._entry(inner, name, is_dir, int(facts.get("size", 0) or 0),
                                               _parse_mdtm(facts.get("modify", "")), mode))
            except ftplib.error_perm as ex:
                if not str(ex).startswith("50"):
                    raise
                lines = []
                ftp.cwd(inner)
                ftp.retrlines("LIST -a", lines.append)
                for line in lines:
                    r = _parse_list_line(line)
                    if r is None or r[0] in (".", ".."):
                        continue
                    name, is_dir, size, mtime, mode, target = r
                    if target is not None:
                        is_dir = self._is_dir(ftp, posixpath.join(inner, name))
                    entries.append(self._entry(inner, name, is_dir, size, mtime, mode, target))
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]
        return entries

    def _is_dir(self, ftp, path):
        cur = ftp.pwd()
        try:
            ftp.cwd(path)
            return True
        except ftplib.error_perm:
            return False
        finally:
            ftp.cwd(cur)

    def exists_dir(self, inner):
        try:
            with self._lock:
                return self._is_dir(self.conn(), inner or "/")
        except ftplib.all_errors:
            return False

    @staticmethod
    def parent(inner):
        return posixpath.dirname(inner.rstrip("/")) or "/"

    @staticmethod
    def join(inner, name):
        return posixpath.join(inner, name)

    def display(self, inner):
        return self.base_url + quote(inner or "/")

    # ------------------------------------------------------------ operations
    def walk(self, ftp, path):
        """Yield (remote_path, entry) for all files/dirs below path (dirs before contents)."""
        for e in self.list(path, ftp=ftp):
            yield e.path, e
            if e.is_dir and not e.is_link:
                yield from self.walk(ftp, e.path)

    @_wrap
    def tree_size(self, path, stop=lambda: False):
        ftp = self.new_connection()
        try:
            total = 0
            for _p, e in self.walk(ftp, path):
                if stop():
                    return None
                if not e.is_dir:
                    total += e.size
            return total
        finally:
            try:
                ftp.quit()
            except ftplib.all_errors:
                pass

    @_wrap
    def download(self, ftp, remote, local, progress=None):
        with open(local, "wb") as fh:
            def cb(data):
                fh.write(data)
                if progress:
                    progress(len(data))
            ftp.retrbinary("RETR " + remote, cb, CHUNK)

    @_wrap
    def upload(self, ftp, local, remote, progress=None):
        with open(local, "rb") as fh:
            ftp.storbinary("STOR " + remote, fh, CHUNK, (lambda b: progress(len(b))) if progress else None)

    @_wrap
    def mkdir(self, path, ftp=None):
        ftp = ftp or self.conn()
        with self._lock:
            try:
                ftp.mkd(path)
            except ftplib.error_perm as ex:
                if not self._is_dir(ftp, path):
                    raise FtpError(str(ex)) from ex

    @_wrap
    def delete(self, ftp, path, is_dir):
        if is_dir:
            for e in self.list(path, ftp=ftp):
                self.delete(ftp, e.path, e.is_dir and not e.is_link)
            ftp.rmd(path)
        else:
            ftp.delete(path)

    @_wrap
    def rename(self, src, dst):
        with self._lock:
            self.conn().rename(src, dst)

    def extract_temp(self, inner):
        d = tempfile.mkdtemp(prefix="pixelcommander-ftp-")
        local = os.path.join(d, posixpath.basename(inner))
        with self._lock:
            self.download(self.conn(), inner, local)
        return local


_connections = {}


def _key(scheme, user, host, port):
    return "%s://%s@%s:%d" % (scheme, user or "anonymous", host.lower(), port)


def register(fs):
    _connections[_key(fs.scheme, fs.user, fs.host, fs.port)] = fs
    return fs


def unregister(fs):
    fs.close()
    _connections.pop(_key(fs.scheme, fs.user, fs.host, fs.port), None)


def connections():
    return list(_connections.values())


def is_ftp_url(location):
    return location.lower().startswith(("ftp://", "ftps://", "sftp://"))


def resolve(location):
    u = urlsplit(location)
    scheme = u.scheme.lower()
    if scheme == "sftp":
        from .sftpfs import SftpFS
        port = u.port or 22
        user = unquote(u.username) if u.username else os.environ.get("USER", "")
    else:
        port = u.port or 21
        user = unquote(u.username) if u.username else "anonymous"
    key = _key(scheme, user, u.hostname or "", port)
    fs = _connections.get(key)
    if fs is None:
        if scheme == "sftp":
            fs = register(SftpFS(u.hostname, port, user, unquote(u.password or "")))
        else:
            fs = register(FtpFS(u.hostname, port, user, unquote(u.password or ""), scheme == "ftps"))
    inner = posixpath.normpath(unquote(u.path) or "/")
    if not inner.startswith("/"):
        inner = "/" + inner
    return fs, "/" if inner == "//" else inner
