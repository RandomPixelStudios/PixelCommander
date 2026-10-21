"""SFTP file system over SSH (paramiko) for the panels: sftp://user@host:port/path.

Implements the same interface as ftpfs.FtpFS (kind "ftp" = remote file system), so all
FTP code paths (copy, delete, lister, directory sizes) work unchanged."""
import os
import posixpath
import stat
import tempfile
import threading
from urllib.parse import quote

try:
    import paramiko
except ImportError:  # optional dependency (python3-paramiko)
    paramiko = None

CHUNK = 1 << 15
KNOWN_HOSTS = os.path.expanduser("~/.ssh/known_hosts")


def available():
    return paramiko is not None


class SftpError(OSError):
    pass


class UnknownHostKey(SftpError):
    """Server key is not in known_hosts; the GUI asks the user and calls fs.trust_key()."""

    def __init__(self, host, key):
        self.host = host
        self.key = key
        fp = key.get_fingerprint().hex(":")
        super().__init__("Unbekannter Host-Schlüssel für %s (%s %s)" % (host, key.get_name(), fp))


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except SftpError:
            raise
        except OSError:
            raise
        except Exception as ex:  # noqa: BLE001  (paramiko.SSHException & co.)
            raise SftpError(str(ex)) from ex
    return inner


class _Conn:
    """One SSH session; mimics the parts of ftplib.FTP used by fileops (quit, size)."""

    def __init__(self, client):
        self.client = client
        self.sftp = client.open_sftp()

    def size(self, path):
        return self.sftp.stat(path).st_size

    def quit(self):
        try:
            self.sftp.close()
        finally:
            self.client.close()


class _RejectPolicy(object if paramiko is None else paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKey(hostname, key)


class SftpFS:
    kind = "ftp"
    is_local = False
    writable = False
    scheme = "sftp"

    def __init__(self, host, port=22, user="", password=""):
        self.host = host
        self.port = port or 22
        self.user = user or os.environ.get("USER", "")
        self.password = password
        self._conn = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------ connection
    @property
    def base_url(self):
        p = "" if self.port == 22 else ":%d" % self.port
        return "sftp://%s@%s%s" % (quote(self.user, safe=""), self.host, p)

    def _ssh_config(self):
        cfg = {}
        path = os.path.expanduser("~/.ssh/config")
        if os.path.isfile(path):
            try:
                c = paramiko.SSHConfig.from_path(path)
                cfg = c.lookup(self.host)
            except Exception:  # noqa: BLE001
                cfg = {}
        return cfg

    def new_connection(self):
        if paramiko is None:
            raise SftpError("SFTP benötigt das Python-Modul „paramiko“ (Paket python3-paramiko).")
        cfg = self._ssh_config()
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if os.path.isfile(KNOWN_HOSTS):
            client.load_host_keys(KNOWN_HOSTS)
        client.set_missing_host_key_policy(_RejectPolicy())
        client.connect(cfg.get("hostname", self.host), port=self.port, username=self.user,
                       password=self.password or None, key_filename=cfg.get("identityfile"),
                       timeout=30, allow_agent=True, look_for_keys=True)
        return _Conn(client)

    def trust_key(self, key):
        """Store the server key in ~/.ssh/known_hosts (after the user confirmed it)."""
        os.makedirs(os.path.dirname(KNOWN_HOSTS), mode=0o700, exist_ok=True)
        hk = paramiko.HostKeys()
        if os.path.isfile(KNOWN_HOSTS):
            hk.load(KNOWN_HOSTS)
        name = self.host if self.port == 22 else "[%s]:%d" % (self.host, self.port)
        hk.add(name, key.get_name(), key)
        hk.save(KNOWN_HOSTS)

    def conn(self):
        with self._lock:
            if self._conn is not None:
                t = self._conn.client.get_transport()
                if t is not None and t.is_active():
                    return self._conn
                self.close()
            self._conn = self.new_connection()
            return self._conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.quit()
                except Exception:  # noqa: BLE001
                    pass
            self._conn = None

    connect = _wrap(conn)

    # ------------------------------------------------------------ vfs api
    @_wrap
    def list(self, inner, show_hidden=True, ftp=None):
        from .vfs import Entry
        inner = inner or "/"
        c = ftp or self.conn()
        with self._lock:
            entries = []
            for a in c.sftp.listdir_attr(inner):
                path = posixpath.join(inner, a.filename)
                mode = a.st_mode or 0
                target = None
                is_dir = stat.S_ISDIR(mode)
                if stat.S_ISLNK(mode):
                    try:
                        target = c.sftp.readlink(path)
                        is_dir = stat.S_ISDIR(c.sftp.stat(path).st_mode)
                    except OSError:
                        target = target or ""
                entries.append(Entry(a.filename, is_dir, 0 if is_dir else (a.st_size or 0), a.st_mtime, mode,
                                     path, target is not None, target))
        if not show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]
        return entries

    def exists_dir(self, inner):
        try:
            with self._lock:
                return stat.S_ISDIR(self.conn().sftp.stat(inner or "/").st_mode)
        except Exception:  # noqa: BLE001
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
        c = self.new_connection()
        try:
            total = 0
            for _p, e in self.walk(c, path):
                if stop():
                    return None
                if not e.is_dir:
                    total += e.size
            return total
        finally:
            c.quit()

    @staticmethod
    def _cb(progress):
        if not progress:
            return None
        last = [0]

        def cb(done, _total):
            progress(done - last[0])
            last[0] = done
        return cb

    @_wrap
    def download(self, ftp, remote, local, progress=None):
        ftp.sftp.get(remote, local, callback=self._cb(progress))

    @_wrap
    def upload(self, ftp, local, remote, progress=None):
        ftp.sftp.put(local, remote, callback=self._cb(progress), confirm=False)

    @_wrap
    def mkdir(self, path, ftp=None):
        c = ftp or self.conn()
        with self._lock:
            try:
                c.sftp.mkdir(path)
            except OSError:
                if not stat.S_ISDIR(c.sftp.stat(path).st_mode):
                    raise

    @_wrap
    def delete(self, ftp, path, is_dir):
        if is_dir:
            for e in self.list(path, ftp=ftp):
                self.delete(ftp, e.path, e.is_dir and not e.is_link)
            ftp.sftp.rmdir(path)
        else:
            ftp.sftp.remove(path)

    @_wrap
    def rename(self, src, dst):
        with self._lock:
            self.conn().sftp.rename(src, dst)

    def extract_temp(self, inner):
        d = tempfile.mkdtemp(prefix="pixelcommander-sftp-")
        local = os.path.join(d, posixpath.basename(inner))
        with self._lock:
            self.download(self.conn(), inner, local)
        return local
