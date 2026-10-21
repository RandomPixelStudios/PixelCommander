#!/bin/sh
# Builds dist/pixelcommander_<version>_all.deb  (works with or without dpkg-deb installed)
set -e
umask 022
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' pixelcommander/__init__.py)
PKG=pixelcommander
BUILD=$(mktemp -d)
ROOT="$BUILD/root"
trap 'rm -rf "$BUILD"' EXIT

install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/share/$PKG/pixelcommander" \
    "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/$PKG"
install -m 0644 pixelcommander/*.py "$ROOT/usr/share/$PKG/pixelcommander/"
install -m 0755 packaging/pixelcommander.sh "$ROOT/usr/bin/pixelcommander"
install -m 0644 packaging/pixelcommander.desktop "$ROOT/usr/share/applications/"
install -m 0644 packaging/pixelcommander.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 README.md "$ROOT/usr/share/doc/$PKG/"
cat > "$ROOT/usr/share/doc/$PKG/copyright" <<COPY
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: PixelCommander
Files: *
License: MIT
COPY
SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.8), python3-pyqt6 | python3-pyqt5
Recommends: python3-paramiko, xdg-utils, libglib2.0-bin, gvfs-backends, gvfs-fuse, p7zip-full | 7zip, qt6-svg-plugins | libqt5svg5
Suggests: unrar
Conflicts: speedcommander
Replaces: speedcommander
Maintainer: PixelCommander <randompixxelstudios@gmail.com>
Description: Two-panel file manager in the style of Total Commander
 PixelCommander is an orthodox two-panel file manager for Linux modelled
 after Total Commander: tabs, function key bar, internal viewer (Lister),
 archive browsing (zip/tar/7z/rar), file search, multi-rename tool,
 directory comparison and synchronization, checksums, file splitting,
 FTP/FTPS connections, network connections via GVFS and much more.
CTRL
cat > "$ROOT/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
umask 022
if [ "$1" = "configure" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
    command -v py3compile >/dev/null 2>&1 && py3compile -q /usr/share/pixelcommander || true
fi
exit 0
POST
cat > "$ROOT/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
umask 022
find /usr/share/pixelcommander -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
exit 0
PRE
chmod 0755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
(cd "$ROOT" && find usr -type f -exec md5sum {} + > DEBIAN/md5sums)

mkdir -p dist
OUT="dist/${PKG}_${VERSION}_all.deb"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$ROOT" "$OUT"
else
    # manual .deb: ar archive of debian-binary, control.tar.gz, data.tar.gz
    echo "2.0" > "$BUILD/debian-binary"
    tar --owner=0 --group=0 --numeric-owner -C "$ROOT/DEBIAN" -czf "$BUILD/control.tar.gz" .
    tar --owner=0 --group=0 --numeric-owner -C "$ROOT" -czf "$BUILD/data.tar.gz" --exclude=./DEBIAN ./usr
    rm -f "$OUT"
    (cd "$BUILD" && ar rc "$OLDPWD/$OUT" debian-binary control.tar.gz data.tar.gz)
fi
chmod 0644 "$OUT"
echo "Gebaut: $OUT"
