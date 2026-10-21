"""Windows-11-style folder icons as embedded SVG, used instead of the desktop theme's folder icons."""
from .qt import QtCore, QtGui

FOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<defs>
<linearGradient id="b" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#e8a317"/><stop offset="1" stop-color="#d18b0c"/></linearGradient>
<linearGradient id="f" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#ffd767"/><stop offset="1" stop-color="#f7bd34"/></linearGradient>
</defs>
<path d="M2 7.5A2.5 2.5 0 0 1 4.5 5h7.1a2.5 2.5 0 0 1 1.77.73L15.6 8H27.5A2.5 2.5 0 0 1 30 10.5V24a2.5 2.5 0 0 1-2.5 2.5h-23A2.5 2.5 0 0 1 2 24z" fill="url(#b)"/>
<path d="M2 12.5A2.5 2.5 0 0 1 4.5 10h7.6a2.5 2.5 0 0 0 1.6-.58L15.6 8H27.5A2.5 2.5 0 0 1 30 10.5V24.5a2.5 2.5 0 0 1-2.5 2.5h-23A2.5 2.5 0 0 1 2 24.5z" fill="url(#f)"/>
<path d="M2.6 11.3A2.5 2.5 0 0 1 4.5 10.5h7.6a2.5 2.5 0 0 0 1.6-.58l1.9-1.42h11.9" fill="none" stroke="#fff3c4" stroke-opacity=".7"/>
</svg>"""

# Network share: folder with a small connection badge
REMOTE_SVG = FOLDER_SVG.replace("</svg>", """<rect x="17" y="17" width="12" height="9" rx="1.5" fill="#2b7cd3"/>
<rect x="19" y="19" width="8" height="4.5" rx=".5" fill="#cfe6ff"/>
<rect x="21" y="26" width="4" height="2.5" fill="#2b7cd3"/><rect x="18" y="28.5" width="10" height="1.5" rx=".75" fill="#2b7cd3"/>
</svg>""")


def _svg_icon(svg):
    icon = QtGui.QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        buf = QtCore.QBuffer()
        buf.setData(QtCore.QByteArray(svg.encode()))
        reader = QtGui.QImageReader(buf, b"svg")
        reader.setScaledSize(QtCore.QSize(size, size))
        img = reader.read()
        if img.isNull():
            return None  # Qt SVG image plugin not installed
        icon.addPixmap(QtGui.QPixmap.fromImage(img))
    return icon


_cache = {}


def win_icon(name):
    """Windows-style icon for "folder" / "folder-remote", or None if SVG rendering is unavailable."""
    if name not in _cache:
        svg = {"folder": FOLDER_SVG, "folder-remote": REMOTE_SVG}.get(name)
        _cache[name] = _svg_icon(svg) if svg else None
    return _cache[name]


# ---------------------------------------------------------------- file type icons
# Page with folded corner, a coloured lower band with a short label and an optional glyph in the upper area.

def _page(color, label, glyph=""):
    size = 9 if len(label) <= 3 else 7.2 if len(label) == 4 else 6
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<path d="M7 2h12.5L27 9.5V28a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" fill="#fbfbfb" stroke="#c4c4c4"/>
<path d="M19.5 2v5.5a2 2 0 0 0 2 2H27" fill="#e6e6e6" stroke="#c4c4c4"/>
%s
<rect x="3" y="19" width="22" height="9.5" rx="2" fill="%s"/>
<text x="14" y="%.1f" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="%.1f"
 fill="#ffffff" text-anchor="middle">%s</text>
</svg>""" % (glyph, color, 24 + size * 0.36, size, label)


G_CODE = '<path d="M11 8l-3.5 3.5L11 15M16 8l3.5 3.5L16 15" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
G_IMAGE = ('<rect x="7.5" y="6" width="13" height="10.5" rx="1.5" fill="{c}" opacity=".18"/>'
           '<circle cx="11" cy="9.3" r="1.5" fill="#f5b100"/>'
           '<path d="M8 16l4-4.5 2.5 2.8 2-2 3.5 3.7z" fill="{c}"/>')
G_VIDEO = ('<rect x="7" y="6" width="14" height="10.5" rx="2" fill="{c}" opacity=".18"/>'
           '<path d="M12 8.3v5.9l5-2.95z" fill="{c}"/>')
G_AUDIO = ('<path d="M12.5 14.5V7.5l7-1.6v7" fill="none" stroke="{c}" stroke-width="1.6"/>'
           '<circle cx="10.8" cy="14.6" r="1.9" fill="{c}"/><circle cx="17.8" cy="13" r="1.9" fill="{c}"/>')
G_ZIP = ('<path d="M13 2v15" stroke="{c}" stroke-width="2.4" stroke-dasharray="1.6 1.6"/>'
         '<rect x="11" y="13" width="4" height="4.5" rx="1" fill="{c}"/>')
G_JAVA = ('<path d="M9.5 10.5h8v3.5a3.5 3.5 0 0 1-3.5 3.5h-1A3.5 3.5 0 0 1 9.5 14z" fill="{c}"/>'
          '<path d="M17.5 11.3h1a1.6 1.6 0 0 1 0 3.2h-1.2" fill="none" stroke="{c}" stroke-width="1.2"/>'
          '<path d="M12 9c-1-1.2 1-2 0-3.3M14.6 9c-1-1.2 1-2 0-3.3" fill="none" stroke="#e76f00" stroke-width="1.1" stroke-linecap="round"/>')
G_PYTHON = ('<path d="M14 5.5c-3 0-3.4 1-3.4 2.3V9.6H14v.6H8.8C7.4 10.2 6.6 11.3 6.6 13s.8 2.8 2.2 2.8h1.4v-1.9c0-1.4 1.2-2.5 2.6-2.5h3.4c1.1 0 2-.9 2-2V7.8c0-1.3-1-2.3-4.2-2.3z" fill="#3a74a8"/>'
            '<path d="M14 18c3 0 3.4-1 3.4-2.3v-1.8H14v-.6h5.2c1.4 0 2.2-1.1 2.2-2.8s-.8-2.8-2.2-2.8h-1.4v1.9c0 1.4-1.2 2.5-2.6 2.5h-3.4c-1.1 0-2 .9-2 2v1.6c0 1.3 1 2.3 4.2 2.3z" fill="#f7c833"/>'
            '<circle cx="12.4" cy="7.3" r=".7" fill="#fff"/><circle cx="15.6" cy="16.2" r=".7" fill="#fff"/>')
G_ROBOT = ('<path d="M8.5 15a5.5 5.5 0 0 1 11 0z" fill="{c}"/>'
           '<path d="M10 9.3l-1.2-2M18 9.3l1.2-2" stroke="{c}" stroke-width="1.1" stroke-linecap="round"/>'
           '<circle cx="11.8" cy="12.6" r=".8" fill="#fff"/><circle cx="16.2" cy="12.6" r=".8" fill="#fff"/>')
G_SWIRL = ('<circle cx="14" cy="11" r="5.2" fill="none" stroke="{c}" stroke-width="1.8"/>'
           '<path d="M14 8.6a2.4 2.4 0 1 1-2.3 3.1" fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round"/>')
G_GRADLE = ('<path d="M7 15c0-4 3-6.5 6.5-6.5 2.3 0 3 1.4 4.6.8 1.1-.4 1.5-2.1.4-2.6-1-.5-1.6.3-1.6.3" fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round"/>'
            '<path d="M7.3 15.6h2.4l.6-2.2h4l.6 2.2h2.4l.6-3" fill="none" stroke="{c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>')
G_KOTLIN = ('<defs><linearGradient id="k" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e44857"/>'
            '<stop offset=".5" stop-color="#c711e1"/><stop offset="1" stop-color="#7f52ff"/></linearGradient></defs>'
            '<path d="M8.5 5.5h10l-5 5 5 5.5h-10z" fill="url(#k)"/>')
G_TEXT = '<path d="M8.5 7h11M8.5 10h11M8.5 13h7" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>'
G_SHEET = ('<rect x="8" y="6" width="12" height="10" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>'
           '<path d="M8 9.5h12M8 12.8h12M12.5 6v10" stroke="{c}" stroke-width="1.1"/>')
G_GEAR = ('<circle cx="14" cy="11" r="4.2" fill="none" stroke="{c}" stroke-width="2.6" stroke-dasharray="2 1.3"/>'
          '<circle cx="14" cy="11" r="2.4" fill="none" stroke="{c}" stroke-width="1.5"/>')
G_TERM = ('<rect x="7" y="6" width="14" height="10" rx="1.6" fill="{c}"/>'
          '<path d="M9.5 9l2 1.8-2 1.8M13 13h3.5" fill="none" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>')
G_DISC = '<circle cx="14" cy="11" r="5.3" fill="{c}" opacity=".85"/><circle cx="14" cy="11" r="1.5" fill="#fbfbfb"/>'
G_FONT = '<text x="14" y="16" font-family="DejaVu Serif, serif" font-size="11" font-weight="bold" fill="{c}" text-anchor="middle">Aa</text>'
G_PDF = ('<path d="M10 15.5c2.5-4 4-7 3.6-8.6-.3-1-1.5-.7-1.3.6.3 2.4 3 5.8 6 6.3 1.6.2 1.5-1.2-.3-1.2-3.4 0-6.6 2.3-8 2.9z" '
         'fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round"/>')
G_DB = ('<ellipse cx="14" cy="7.5" rx="5" ry="1.8" fill="{c}"/>'
        '<path d="M9 7.5v7c0 1 2.2 1.8 5 1.8s5-.8 5-1.8v-7" fill="none" stroke="{c}" stroke-width="1.5"/>'
        '<path d="M9 11c0 1 2.2 1.8 5 1.8s5-.8 5-1.8" fill="none" stroke="{c}" stroke-width="1.2"/>')

# group: (band colour, glyph, extensions); the label is the extension unless LABELS overrides it
TYPES = [
    ("#e76f00", G_JAVA, "java jar class war"),
    ("#3a74a8", G_PYTHON, "py pyw pyc pyi ipynb"),
    ("#7f52ff", G_KOTLIN, "kt kts"),
    ("#02303a", G_GRADLE, "gradle"),
    ("#3ddc84", G_ROBOT, "apk aab xapk apks"),
    ("#c8102e", G_SWIRL, "deb rpm snap flatpak appimage pkg"),
    ("#8d6e63", G_ZIP, "zip 7z rar tar gz tgz bz2 xz zst lz lzma tbz2 txz cab"),
    ("#0ea5e9", G_IMAGE, "png jpg jpeg gif bmp webp ico tif tiff heic avif xpm pbm pgm ppm raw cr2 nef"),
    ("#f97316", G_IMAGE, "svg psd xcf kra ai eps"),
    ("#e11d48", G_VIDEO, "mp4 mkv avi mov webm wmv flv m4v mpg mpeg 3gp ts"),
    ("#9333ea", G_AUDIO, "mp3 wav flac ogg opus m4a aac wma mid midi"),
    ("#dc2626", G_PDF, "pdf"),
    ("#2563eb", G_TEXT, "doc docx odt rtf"),
    ("#16a34a", G_SHEET, "xls xlsx ods csv tsv"),
    ("#ea580c", G_IMAGE, "ppt pptx odp"),
    ("#64748b", G_TEXT, "txt log md rst nfo"),
    ("#0f766e", G_GEAR, "json yaml yml toml ini cfg conf xml properties env"),
    ("#334155", G_TERM, "sh bash zsh fish bat cmd ps1"),
    ("#f0db4f", G_CODE, "js mjs cjs"), ("#3178c6", G_CODE, "ts tsx"), ("#61dafb", G_CODE, "jsx"),
    ("#e34f26", G_CODE, "html htm"), ("#264de4", G_CODE, "css scss sass less"),
    ("#00599c", G_CODE, "c h cpp cc cxx hpp"), ("#68217a", G_CODE, "cs"), ("#ce422b", G_CODE, "rs"),
    ("#00add8", G_CODE, "go"), ("#f05138", G_CODE, "swift"), ("#cc342d", G_CODE, "rb"),
    ("#777bb3", G_CODE, "php"), ("#0175c2", G_CODE, "dart"), ("#2c2d72", G_CODE, "lua"),
    ("#475569", G_CODE, "sql"), ("#f1502f", G_CODE, "diff patch"),
    ("#0369a1", G_DB, "db sqlite sqlite3"),
    ("#52525b", G_DISC, "iso img dmg"),
    ("#57534e", G_FONT, "ttf otf woff woff2"),
    ("#475569", G_GEAR, "exe msi dll so bin"),
]
LABELS = {"jpeg": "JPG", "appimage": "APP", "flatpak": "FLAT", "sqlite3": "SQL", "sqlite": "SQL", "properties": "PROP",
          "woff2": "WOFF", "ipynb": "IPY", "midi": "MID", "docx": "DOC", "xlsx": "XLS", "pptx": "PPT"}
_EXT = {}
for _color, _glyph, _exts in TYPES:
    for _e in _exts.split():
        _EXT[_e] = (_color, _glyph)

_file_cache = {}


def file_icon(ext):
    """Self-drawn icon for a file extension (without dot), or None if unknown / SVG unavailable."""
    ext = ext.lower()
    if ext not in _file_cache:
        spec = _EXT.get(ext)
        icon = None
        if spec:
            color, glyph = spec
            label = LABELS.get(ext, ext[:4].upper())
            text_dark = color.lower() in ("#f0db4f", "#61dafb", "#3ddc84")
            svg = _page(color, label, glyph.replace("{c}", color))
            if text_dark:
                svg = svg.replace('fill="#ffffff" text-anchor', 'fill="#1f2937" text-anchor')
            icon = _svg_icon(svg)
        _file_cache[ext] = icon
    return _file_cache[ext]
