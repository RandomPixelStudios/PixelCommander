"""Windows-11-style button bar icons as SVG, matching the folder icons in winicons.py.

Keys are the names of the drawing functions in pixicons.py (without the leading underscore), so every command
mapped there gets the coloured icon; pixicons' line icons stay as fallback when Qt's SVG plugin is missing.
"""
import math

from .winicons import _svg_icon

DEFS = """<defs>
<linearGradient id="gB" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5aa9ff"/><stop offset="1" stop-color="#1f6fd6"/></linearGradient>
<linearGradient id="gG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6ad48a"/><stop offset="1" stop-color="#1f9a4e"/></linearGradient>
<linearGradient id="gR" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff7a7a"/><stop offset="1" stop-color="#d63035"/></linearGradient>
<linearGradient id="gA" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd767"/><stop offset="1" stop-color="#f7bd34"/></linearGradient>
<linearGradient id="gAb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8a317"/><stop offset="1" stop-color="#d18b0c"/></linearGradient>
<linearGradient id="gS" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a7b1bf"/><stop offset="1" stop-color="#6b7684"/></linearGradient>
<linearGradient id="gD" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b4555"/><stop offset="1" stop-color="#1f2630"/></linearGradient>
<linearGradient id="gW" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#eef1f5"/></linearGradient>
<linearGradient id="gBr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#dba56a"/><stop offset="1" stop-color="#b07a43"/></linearGradient>
<linearGradient id="gL" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8f4ff"/><stop offset="1" stop-color="#b9dcff"/></linearGradient>
</defs>"""

EDGE = "#b8bec7"
BLUE = "#2b7cd3"
GRAY = "#9aa4b2"


# ---------------------------------------------------------------- building blocks

def _svg(body):
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">%s%s</svg>' % (DEFS, body)


def _s(d, color, w=2.0, extra=""):
    return ('<path d="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linecap="round" '
            'stroke-linejoin="round"%s/>' % (d, color, w, extra))


def _f(d, fill, stroke=None, extra=""):
    st = ' stroke="%s" stroke-linejoin="round"' % stroke if stroke else ""
    return '<path d="%s" fill="%s"%s%s/>' % (d, fill, st, extra)


def _rect(x, y, w, h, r, fill, stroke=None):
    st = ' stroke="%s"' % stroke if stroke else ""
    return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s"%s/>' % (x, y, w, h, r, fill, st)


def _circle(cx, cy, r, fill, stroke=None, w=1.5):
    st = ' stroke="%s" stroke-width="%g"' % (stroke, w) if stroke else ""
    return '<circle cx="%g" cy="%g" r="%g" fill="%s"%s/>' % (cx, cy, r, fill, st)


def _page(x, y, w, h):
    f = w * 0.3
    return (_f("M%g %gH%gL%g %gV%gA1.5 1.5 0 0 1 %g %gH%gA1.5 1.5 0 0 1 %g %gV%gA1.5 1.5 0 0 1 %g %gz"
               % (x + 1.5, y, x + w - f, x + w, y + f, y + h - 1.5, x + w - 1.5, y + h, x + 1.5, x, y + h - 1.5,
                  y + 1.5, x + 1.5, y), "url(#gW)", EDGE)
            + _f("M%g %gV%gA1.2 1.2 0 0 0 %g %gH%g" % (x + w - f, y, y + f - 1.2, x + w - f + 1.2, y + f, x + w),
                 "#e3e6ea", EDGE))


def _lines(x, y, w, n, gap=3.5, colors=()):
    out = ""
    for i in range(n):
        ww = w if i % 3 != 2 else w * 0.65
        out += _s("M%g %gh%g" % (x, y + i * gap, ww), colors[i] if i < len(colors) and colors[i] else GRAY, 1.8)
    return out


def _folder(x, y, s):
    return ('<g transform="translate(%g %g) scale(%g)">' % (x, y, s)
            + _f("M2 7.5A2.5 2.5 0 0 1 4.5 5h7.1a2.5 2.5 0 0 1 1.77.73L15.6 8H27.5A2.5 2.5 0 0 1 30 10.5V24a2.5 2.5 "
                 "0 0 1-2.5 2.5h-23A2.5 2.5 0 0 1 2 24z", "url(#gAb)")
            + _f("M2 12.5A2.5 2.5 0 0 1 4.5 10h7.6a2.5 2.5 0 0 0 1.6-.58L15.6 8H27.5A2.5 2.5 0 0 1 30 10.5V24.5a2.5 "
                 "2.5 0 0 1-2.5 2.5h-23A2.5 2.5 0 0 1 2 24.5z", "url(#gA)")
            + _s("M2.6 11.3A2.5 2.5 0 0 1 4.5 10.5h7.6a2.5 2.5 0 0 0 1.6-.58l1.9-1.42h11.9", "#fff3c4", 1,
                 ' stroke-opacity=".7"')
            + "</g>")


def _window(x, y, w, h, bar="url(#gB)", body="url(#gW)"):
    return (_rect(x, y, w, h, 2.5, bar)
            + _f("M%g %gH%gV%gA2.5 2.5 0 0 1 %g %gH%gA2.5 2.5 0 0 1 %g %gz"
                 % (x + 0.8, y + 5, x + w - 0.8, y + h - 3, x + w - 3.3, y + h - 0.8, x + 3.3, x + 0.8, y + h - 3),
                 body))


# badge glyphs (white, centred on cx/cy)
def _plus(cx, cy):
    return "M%g %gh6M%g %gv6" % (cx - 3, cy, cx, cy - 3)


def _cross(cx, cy):
    return "M%g %gl5 5M%g %gl-5 5" % (cx - 2.5, cy - 2.5, cx + 2.5, cy - 2.5)


def _right(cx, cy):
    return "M%g %gh6M%g %gl2.6 2.6-2.6 2.6" % (cx - 3.2, cy, cx + 0.2, cy - 2.6)


def _down(cx, cy):
    return "M%g %gv6M%g %gl2.6 2.6 2.6-2.6" % (cx, cy - 3.2, cx - 2.6, cy + 0.2)


def _up(cx, cy):
    return "M%g %gv-6M%g %gl2.6-2.6 2.6 2.6" % (cx, cy + 3.2, cx - 2.6, cy - 0.2)


def _badge(glyph, grad, cx=23.5, cy=23.5, r=6.8):
    return _circle(cx, cy, r, grad, "#ffffff", 1.5) + _s(glyph(cx, cy), "#ffffff", 2.2)


def _poly(pts):
    return "M" + "L".join("%.2f %.2f" % p for p in pts) + "z"


def _star_pts(cx, cy, ro, ri):
    return [(cx + (ro if i % 2 == 0 else ri) * math.cos(-math.pi / 2 + i * math.pi / 5),
             cy + (ro if i % 2 == 0 else ri) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]


def _gear_path(cx, cy, ro, ri, hole):
    pts = []
    for i in range(16):
        a = math.pi * i / 8
        r = ro if i % 2 == 0 else ri
        for da in (-0.2, 0.2):
            pts.append((cx + r * math.cos(a + da), cy + r * math.sin(a + da)))
    return _poly(pts) + "M%g %ga%g %g 0 1 0 %g 0a%g %g 0 1 0 %g 0z" % (cx - hole, cy, hole, hole, 2 * hole, hole,
                                                                       hole, -2 * hole)


def _box():
    return (_rect(5.5, 12, 21, 16, 2, "url(#gBr)") + _rect(3.5, 6.5, 25, 7, 1.8, "#a8743f")
            + _rect(14.5, 6.5, 3, 15, 0.8, "#7a5129")
            + _s("M15.2 9h1.6M15.2 12h1.6M15.2 15h1.6M15.2 18h1.6", "#f1dcc0", 1.1)
            + _rect(13.6, 19.5, 4.8, 4, 1.2, "#e9ecef", "#9aa4b2"))


def _clipboard(x, y, w, h):
    return (_rect(x, y, w, h, 2.5, "url(#gBr)") + _rect(x + 2.5, y + 4, w - 5, h - 6.5, 1, "#ffffff")
            + _rect(x + w / 2 - 5, y - 1.5, 10, 5, 1.6, "url(#gS)"))


def _magnifier(cx, cy, r, glass_w=2.6, handle_w=3.4):
    d = r * 0.72
    return (_s("M%g %gL%g %g" % (cx + d, cy + d, cx + d + r * 0.8, cy + d + r * 0.8), "#3b4555", handle_w)
            + _circle(cx, cy, r, "url(#gL)", BLUE, glass_w)
            + _s("M%g %gA%g %g 0 0 1 %g %g" % (cx - r * 0.55, cy - r * 0.05, r * 0.55, r * 0.55, cx - r * 0.05,
                                               cy - r * 0.55), "#ffffff", 1.4))


def _pencil():
    return ('<g transform="translate(9.5 26) rotate(-45)">'
            + _f("M0 0L4.5 -2.6V2.6z", "#f3d2a2") + _f("M0 0L1.6 -0.9V0.9z", "#3b4555")
            + _rect(4.5, -2.6, 12, 5.2, 0.4, "url(#gA)") + _s("M4.5 0h12", "#d18b0c", 0.8)
            + _rect(16.5, -2.6, 1.8, 5.2, 0.3, "url(#gS)") + _rect(18.3, -2.6, 3, 5.2, 1.2, "#f28b9b")
            + "</g>")


def _globe():
    return (_circle(16, 16, 11, "url(#gB)")
            + '<ellipse cx="16" cy="16" rx="4.6" ry="11" fill="none" stroke="#ffffff" stroke-width="1.4" '
              'stroke-opacity=".9"/>'
            + _s("M5 16h22M7 10.5h18M7 21.5h18M16 5v22", "#ffffff", 1.4, ' stroke-opacity=".9"'))


def _eye():
    return (_f("M3 16Q16 4 29 16Q16 28 3 16z", "url(#gW)", "#8a94a3") + _circle(16, 16, 5.2, "url(#gB)")
            + _circle(16, 16, 2.2, "#1f2630") + _circle(17.6, 14.4, 1.1, "#ffffff"))


# ---------------------------------------------------------------- icons

def _arrow_ring(path, head, color):
    return _s(path, color, 3.4) + _f(_poly(head), color, color)


ICONS = {
    "reread": _arrow_ring("M22.9 10.2A9 9 0 1 0 25 16", [(25.1, 12.9), (24.6, 7.5), (20.0, 11.3)], BLUE),
    "brief": _window(3, 5, 26, 22) + _s("M16 11v14", EDGE, 1.2)
    + _lines(6, 14, 7, 3, 4) + _lines(19, 14, 7, 3, 4, (None, BLUE)),
    "full": _window(3, 5, 26, 22) + _rect(4, 16.2, 24, 3.6, 0.8, "#cfe6ff")
    + _s("M6 13.5h20", EDGE, 1.2) + _lines(6, 18, 10, 3, 3.8, (BLUE,)) + _lines(19, 18, 6, 3, 3.8, (BLUE,)),
    "thumbs": _rect(3.5, 3.5, 11, 11, 2.5, "url(#gB)") + _rect(17.5, 3.5, 11, 11, 2.5, "url(#gA)")
    + _rect(3.5, 17.5, 11, 11, 2.5, "url(#gG)") + _rect(17.5, 17.5, 11, 11, 2.5, "url(#gR)")
    + _f("M5 13l3.5-4 2.5 2.5 1.5-1.5 2 3z", "#ffffff", None, ' fill-opacity=".85"'),
    "tree": _s("M6.5 12.3V24.7H14M6.5 15.7H14", GRAY, 1.8)
    + _folder(1, 1, 0.42) + _folder(13, 9, 0.42) + _folder(13, 18, 0.42),
    "quickview": _window(3, 5, 26, 22) + _s("M14 11v14", EDGE, 1.2) + _lines(5.5, 14, 6, 3, 4)
    + _rect(16.5, 12.5, 10, 10, 1.5, "url(#gL)") + _circle(19.5, 15.5, 1.5, "#f5b100")
    + _f("M17 22l3.5-4 2.2 2.4 1.6-1.6 2.2 3.2z", BLUE),
    "select_all": _rect(4, 4, 24, 24, 5, "url(#gB)") + _s("M10 16.5l4 4 8-9", "#ffffff", 3.2),
    "invert": _rect(4, 4, 24, 24, 5, "url(#gW)", EDGE) + _f("M28 9V23A5 5 0 0 1 23 28H9z", "url(#gB)")
    + _s("M10 10.5l3 3M13 10.5l-3 3", GRAY, 1.8) + _s("M18 21l2 2 4-4.5", "#ffffff", 2.2),
    "pack": _box() + _badge(_down, "url(#gG)"),
    "unpack": _box() + _badge(_up, "url(#gB)"),
    "search": _magnifier(13, 13, 8.5, 3, 4.4),
    "multirename": _rect(2.5, 8, 27, 16, 3, "url(#gW)", EDGE)
    + '<text x="11.5" y="20.3" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="10" ' \
      'fill="#374151" text-anchor="middle">Ab</text>'
    + _s("M22.5 11v10M20.5 11h4M20.5 21h4", BLUE, 1.8),
    "compare_dirs": _folder(0, 0, 0.6) + _folder(12, 12, 0.6)
    + _s("M6 18.5v5h5", BLUE, 2.2) + _s("M26 13.5v-5h-5", "#d18b0c", 2.2),
    "sync": _arrow_ring("M7.5 13A9 9 0 0 1 24 11.5", [(25.75, 14.5), (26.1, 9.1), (20.9, 12.1)], BLUE)
    + _arrow_ring("M24.5 19A9 9 0 0 1 8 20.5", [(6.25, 17.5), (5.9, 22.9), (11.1, 19.9)], "#1f9a4e"),
    "compare_files": _page(2, 3, 14, 19) + _lines(4.5, 10, 7, 3, 3.5, ("#d63035",))
    + _page(16, 10, 14, 19) + _lines(18.5, 17, 7, 3, 3.5, ("#1f9a4e",)),
    "terminal": _rect(3, 5, 26, 22, 3, "url(#gD)") + _s("M8 12.5l4 3.5-4 3.5", "#4ade80", 2.4)
    + _s("M14.5 21h7", "#ffffff", 2.4),
    "hidden": _eye() + _s("M6 27L26 5", "#ffffff", 5) + _s("M6 27L26 5", "#d63035", 2.8),
    "config": _f(_gear_path(16, 16, 13, 9.5, 4.2), "url(#gS)", None, ' fill-rule="evenodd"')
    + _circle(16, 16, 4.2, "none", BLUE, 2.4),
    "copy": _page(4, 2, 15, 20) + _page(12, 9, 15, 20) + _lines(14.5, 17, 9, 3, 3.5, (BLUE, BLUE)),
    "move": _page(5, 3, 16, 22) + _lines(7.5, 11, 8, 3) + _badge(_right, "url(#gB)"),
    "mkdir": _folder(0, 0, 1) + _badge(_plus, "url(#gG)"),
    "delete": _s("M12.5 6V4h7v2", "#a3262b", 1.8) + _rect(5, 5.5, 22, 4, 1.8, "#c4282d")
    + _f("M7.5 10.5h17l-1.5 16a2 2 0 0 1-2 1.8h-10a2 2 0 0 1-2-1.8z", "url(#gR)")
    + _s("M13 14.5v9.5M19 14.5v9.5", "#ffffff", 1.8, ' stroke-opacity=".85"'),
    "view": _page(4, 2, 18, 24) + _lines(7, 10, 10, 3) + _magnifier(20.5, 20.5, 5, 2.4, 3.2),
    "edit": _page(3, 2, 18, 24) + _lines(6, 10, 10, 3) + _pencil(),
    "network": _globe(),
    "disconnect": _globe() + _badge(_cross, "url(#gR)"),
    "hotlist": _f(_poly(_star_pts(16, 17, 13, 5.6)), "url(#gA)", "#d18b0c"),
    "swap": _f(_poly([(4, 7.5), (19, 7.5), (19, 3.5), (27, 10), (19, 16.5), (19, 12.5), (4, 12.5)]), "url(#gB)",
               BLUE)
    + _f(_poly([(28, 19.5), (13, 19.5), (13, 15.5), (5, 22), (13, 28.5), (13, 24.5), (28, 24.5)]), "url(#gG)",
         "#1f9a4e"),
    "target_eq_source": _window(3, 5, 26, 22) + _s("M16 11v14", EDGE, 1.2)
    + _s("M8 18h14M18.5 14.5l3.5 3.5-3.5 3.5", BLUE, 2.4),
    "new_tab": _f("M3 26V9a2 2 0 0 1 2-2h7.5l2 3H27a2 2 0 0 1 2 2V26a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
                  "url(#gW)", EDGE) + _f("M3 9a2 2 0 0 1 2-2h7.5l2 3H3z", "url(#gB)")
    + _badge(_plus, "url(#gG)"),
    "clipboard_names": _clipboard(6, 4, 20, 25) + _lines(11, 13, 10, 4, 3.5, (BLUE,)),
    "calcspace": _circle(16, 16, 11, "url(#gL)", BLUE, 1.2)
    + _f("M16 16V5A11 11 0 0 1 26.34 19.76z", "url(#gB)")
    + _f("M16 16L26.34 19.76A11 11 0 0 1 20.65 25.97z", "url(#gA)"),
    "properties": _circle(16, 16, 12, "url(#gB)") + _circle(16, 10, 1.8, "#ffffff")
    + _s("M16 14.5v8.5", "#ffffff", 3),
    "paste": _clipboard(3, 5, 18, 23) + _page(14, 12, 15, 18) + _lines(16.5, 19, 8, 3, 3.2, (BLUE,)),
    "cut": _s("M12.5 20.5L21.5 4.5M19.5 20.5L10.5 4.5", "url(#gS)", 2.8)
    + _circle(10, 24, 3.8, "none", "#d63035", 2.8) + _circle(22, 24, 3.8, "none", "#d63035", 2.8)
    + _circle(16, 15.2, 1.2, "#3b4555"),
    "exit": _rect(5, 3.5, 15, 25, 1.8, "url(#gS)") + _rect(7, 5.5, 11, 23, 1, "url(#gBr)")
    + _circle(15.5, 17, 1.2, "#fff3c4") + _badge(_right, "url(#gR)"),
    "filter": _f("M4 6.5A1.5 1.5 0 0 1 5.5 5h21A1.5 1.5 0 0 1 27.6 7.4L19 17.5v7.6a1.5 1.5 0 0 1-.9 1.4l-3 1.4"
                 "A1.2 1.2 0 0 1 13 26.8V17.5L4.4 7.4A1.5 1.5 0 0 1 4 6.5z", "url(#gB)")
    + _s("M8 8.5h16", "#ffffff", 1.4, ' stroke-opacity=".7"'),
    "split": _page(6, 2, 20, 28) + _lines(9.5, 8, 12, 2, 3.5) + _lines(9.5, 21, 12, 2, 3.5)
    + _s("M2 15.5h28", "#d63035", 2, ' stroke-dasharray="2.5 2"'),
    "help": _circle(16, 16, 12, "url(#gB)")
    + '<text x="16" y="21.5" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="16" ' \
      'fill="#ffffff" text-anchor="middle">?</text>',
}

_cache = {}


def tool_icon(name):
    """Coloured SVG icon for a pixicons drawing name, or None (unknown name / SVG plugin missing)."""
    if name not in _cache:
        body = ICONS.get(name)
        _cache[name] = _svg_icon(_svg(body)) if body else None
    return _cache[name]
