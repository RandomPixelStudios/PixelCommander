"""Built-in button bar icons, drawn with QPainter on a 24x24 grid.

The outline colour is taken from the current palette at paint time, so the icons follow light and dark mode;
the accent colours are chosen to be readable on both backgrounds.
"""
import math

from .qt import QtCore, QtGui, QtWidgets, Qt

BLUE = "#3b82f6"
AMBER = "#f2a516"
GREEN = "#22a55a"
RED = "#e5484d"


class _Pen:
    def __init__(self, p, fg):
        self.p = p
        self.fg = fg

    # ---------------------------------------------------------------- primitives
    def _pen(self, color=None, w=1.8):
        pen = QtGui.QPen(QtGui.QColor(color) if color else self.fg, w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _set(self, color, fill, w):
        self.p.setPen(self._pen(color, w) if color is not False else Qt.PenStyle.NoPen)
        if fill:
            c = QtGui.QColor(self.fg if fill == "fg" else fill)
            self.p.setBrush(c)
        else:
            self.p.setBrush(Qt.BrushStyle.NoBrush)

    def line(self, x1, y1, x2, y2, color=None, w=1.8):
        self._set(color, None, w)
        self.p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

    def poly(self, pts, color=None, fill=None, closed=False, w=1.8):
        self._set(color, fill, w)
        qp = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])
        if closed or fill:
            self.p.drawPolygon(qp)
        else:
            self.p.drawPolyline(qp)

    def rect(self, x, y, w_, h, r=1.5, color=None, fill=None, w=1.8):
        self._set(color, fill, w)
        self.p.drawRoundedRect(QtCore.QRectF(x, y, w_, h), r, r)

    def circle(self, cx, cy, r, color=None, fill=None, w=1.8):
        self._set(color, fill, w)
        self.p.drawEllipse(QtCore.QPointF(cx, cy), r, r)

    def arc(self, cx, cy, r, start, span, color=None, w=1.8):
        """Arc in degrees, counter-clockwise from 3 o'clock (Qt convention)."""
        self._set(color, None, w)
        self.p.drawArc(QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r), int(start * 16), int(span * 16))

    def path(self, path, color=None, fill=None, w=1.8):
        self._set(color, fill, w)
        self.p.drawPath(path)

    def text(self, x, y, w_, h, s, color=None, px=8, bold=True):
        f = QtGui.QFont(self.p.font())
        f.setPixelSize(px)
        f.setBold(bold)
        self.p.setFont(f)
        self.p.setPen(QtGui.QColor(color) if color else self.fg)
        self.p.drawText(QtCore.QRectF(x, y, w_, h), int(Qt.AlignmentFlag.AlignCenter), s)

    # ---------------------------------------------------------------- composites
    def arrow(self, x1, y1, x2, y2, color=None, head=3.2, w=1.8):
        self.line(x1, y1, x2, y2, color, w)
        a = math.atan2(y2 - y1, x2 - x1)
        for d in (2.5, -2.5):
            self.line(x2, y2, x2 - head * math.cos(a + d / 3.2), y2 - head * math.sin(a + d / 3.2), color, w)

    def doc(self, x, y, w_=12, h=16, color=None, fill=None):
        f = 3.5
        self.poly([(x, y), (x + w_ - f, y), (x + w_, y + f), (x + w_, y + h), (x, y + h)], color, fill, True)
        self.poly([(x + w_ - f, y), (x + w_ - f, y + f), (x + w_, y + f)], color)

    def folder(self, x, y, w_=18, h=13, color=None, fill=None):
        t = 6
        self.poly([(x, y + h), (x, y), (x + t, y), (x + t + 2, y + 2.2), (x + w_, y + 2.2), (x + w_, y + h)],
                  color, fill, True)

    def panels(self, color=None):
        self.rect(2.5, 4, 19, 16, 2, color)
        self.line(12, 4, 12, 20, color)

    def gear(self, cx, cy, r, color=None):
        teeth = 8
        pts = []
        for i in range(teeth * 2):
            a = math.pi * i / teeth
            rr = r if i % 2 == 0 else r * 0.74
            for da in (-0.17, 0.17):
                pts.append((cx + rr * math.cos(a + da), cy + rr * math.sin(a + da)))
        self.poly(pts, color, None, True, 1.6)
        self.circle(cx, cy, r * 0.32, color)

    def eye(self, cx, cy, color=None, pupil=BLUE):
        path = QtGui.QPainterPath()
        path.moveTo(cx - 9, cy)
        path.quadTo(cx, cy - 8.5, cx + 9, cy)
        path.quadTo(cx, cy + 8.5, cx - 9, cy)
        self.path(path, color)
        self.circle(cx, cy, 2.6, False, pupil)

    def magnifier(self, cx, cy, r=5.5, color=None, glass=None):
        self.circle(cx, cy, r, color, glass)
        d = r * 0.72
        self.line(cx + d, cy + d, cx + d + 5, cy + d + 5, color, 2.4)


# --------------------------------------------------------------------- icon drawings

def _reread(g):
    g.arc(12, 12, 7.5, 70, 280)
    g.poly([(14.2, 2.4), (14.6, 7.6), (19.6, 5.2)], False, BLUE, True)


def _brief(g):
    g.panels()
    for y in (8, 12, 16):
        g.line(5, y, 9.5, y)
        g.line(14.5, y, 19, y, BLUE if y == 12 else None)


def _full(g):
    g.rect(2.5, 4, 19, 16, 2)
    g.line(2.5, 8, 21.5, 8)
    for y in (11.5, 14.5, 17.5):
        g.line(5, y, 12, y, BLUE if y == 14.5 else None)
        g.line(15, y, 19, y)


def _thumbs(g):
    for x, y, c in ((3, 3, None), (13, 3, BLUE), (3, 13, None), (13, 13, None)):
        g.rect(x, y, 8, 8, 1.8, c)


def _tree(g):
    g.rect(3, 3, 6, 5, 1.2, None, BLUE)
    g.rect(13, 10, 6, 4.5, 1.2)
    g.rect(13, 17, 6, 4.5, 1.2)
    g.poly([(6, 8), (6, 19.2), (13, 19.2)])
    g.line(6, 12.2, 13, 12.2)


def _quickview(g):
    g.panels()
    g.line(5, 8, 9.5, 8)
    g.line(5, 12, 9.5, 12)
    g.line(5, 16, 9.5, 16)
    g.circle(16.8, 12, 3.2, BLUE)
    g.circle(16.8, 12, 1.1, False, BLUE)


def _select_all(g):
    g.rect(3, 3, 18, 18, 3)
    g.poly([(7.5, 12.5), (10.8, 15.8), (16.8, 8.5)], BLUE, None, False, 2.4)


def _invert(g):
    g.rect(3, 3, 18, 18, 3)
    g.poly([(3.9, 20.1), (20.1, 3.9), (20.1, 18), (18, 20.1)], False, BLUE, True)
    g.rect(3, 3, 18, 18, 3)


def _pack(g):
    g.rect(3.5, 6, 17, 14.5, 2, None, None)
    g.line(3.5, 10, 20.5, 10)
    g.poly([(5.5, 6), (7.5, 3), (16.5, 3), (18.5, 6)])
    for y in (11.5, 14, 16.5):
        g.line(12, y, 12, y + 1.2, AMBER, 2.4)
    g.rect(10.5, 7.2, 3, 2.2, 0.6, AMBER, AMBER, 1)


def _unpack(g):
    g.poly([(3.5, 11), (3.5, 20.5), (20.5, 20.5), (20.5, 11)])
    g.line(3.5, 14.5, 20.5, 14.5)
    g.arrow(12, 11.5, 12, 2.5, AMBER, 3.6, 2.2)


def _search(g):
    g.magnifier(10, 10, 6, None, None)
    g.arc(10, 10, 3.5, 100, 70, BLUE, 1.6)


def _multirename(g):
    g.rect(2.5, 6, 19, 12, 2)
    g.text(3.5, 6.5, 12, 11, "Ab", None, 8.5)
    g.line(17.5, 8.5, 17.5, 15.5, BLUE, 2)
    g.line(15.8, 8.5, 19.2, 8.5, BLUE, 1.5)
    g.line(15.8, 15.5, 19.2, 15.5, BLUE, 1.5)


def _compare_dirs(g):
    g.folder(1.5, 4, 9, 7)
    g.folder(13.5, 13, 9, 7)
    g.arrow(6, 14, 6, 19.5, BLUE, 2.6)
    g.line(6, 19.5, 11, 19.5, BLUE)
    g.arrow(18, 10, 18, 4.5, AMBER, 2.6)
    g.line(18, 4.5, 13, 4.5, AMBER)


def _sync(g):
    g.arc(12, 12, 7.5, 20, 150, BLUE)
    g.poly([(5.2, 7.2), (4.3, 11.3), (8.4, 10.4)], BLUE, None, False, 2)
    g.arc(12, 12, 7.5, 200, 150, GREEN)
    g.poly([(18.8, 16.8), (19.7, 12.7), (15.6, 13.6)], GREEN, None, False, 2)


def _compare_files(g):
    g.doc(2.5, 3, 9.5, 14)
    g.doc(12, 7, 9.5, 14)
    g.line(4.8, 9, 8.6, 9, RED)
    g.line(4.8, 12, 9, 12)
    g.line(14.3, 13, 18.6, 13, GREEN)
    g.line(14.3, 16, 18, 16)


def _terminal(g):
    g.rect(2.5, 4, 19, 16, 2.5)
    g.poly([(6.5, 9), (9.5, 12), (6.5, 15)], GREEN, None, False, 2)
    g.line(11.5, 15.5, 16.5, 15.5)


def _hidden(g):
    g.eye(12, 12)
    g.line(4.5, 19.5, 19.5, 4.5, RED, 2)


def _config(g):
    g.gear(12, 12, 9)
    g.circle(12, 12, 2.9, False, BLUE)


def _copy(g):
    g.doc(3, 2.5, 11, 14)
    g.doc(10, 7.5, 11, 14, BLUE)
    g.line(13, 14.5, 18, 14.5, BLUE)
    g.line(13, 17.5, 16.5, 17.5, BLUE)


def _move(g):
    g.doc(3, 4, 11, 15)
    g.arrow(10.5, 13, 21, 13, BLUE, 3.6, 2.2)


def _mkdir(g):
    g.folder(2, 5, 17, 13)
    g.line(18.5, 12.5, 18.5, 21, GREEN, 2.2)
    g.line(14.25, 16.75, 22.75, 16.75, GREEN, 2.2)


def _delete(g):
    g.line(3.5, 6.5, 20.5, 6.5)
    g.poly([(9.5, 6.5), (9.5, 3.5), (14.5, 3.5), (14.5, 6.5)])
    g.poly([(5.5, 6.5), (6.8, 20.5), (17.2, 20.5), (18.5, 6.5)], RED)
    g.line(10, 10, 10, 17, RED)
    g.line(14, 10, 14, 17, RED)


def _view(g):
    g.doc(4, 2.5, 13, 17)
    g.line(6.5, 9, 13, 9)
    g.line(6.5, 12, 11, 12)
    g.magnifier(15, 15.5, 3.3, BLUE)


def _edit(g):
    g.doc(3, 2.5, 12, 17)
    path = QtGui.QPainterPath()
    path.moveTo(11, 19)
    path.lineTo(11.6, 15.8)
    path.lineTo(19.2, 8.2)
    path.lineTo(21.8, 10.8)
    path.lineTo(14.2, 18.4)
    path.closeSubpath()
    g.path(path, AMBER, None, 1.7)


def _network(g):
    g.circle(12, 12, 8.5)
    g.line(3.5, 12, 20.5, 12)
    path = QtGui.QPainterPath()
    path.moveTo(12, 3.5)
    path.quadTo(6.5, 12, 12, 20.5)
    path.quadTo(17.5, 12, 12, 3.5)
    g.path(path, BLUE)


def _disconnect(g):
    _network(g)
    g.line(4.5, 19.5, 19.5, 4.5, RED, 2.2)


def _hotlist(g):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 9 if i % 2 == 0 else 3.9
        pts.append((12 + r * math.cos(a), 12.6 + r * math.sin(a)))
    g.poly(pts, AMBER, None, True, 1.7)


def _swap(g):
    g.arrow(4, 8.5, 20, 8.5, BLUE, 3.4)
    g.arrow(20, 15.5, 4, 15.5, None, 3.4)


def _target_eq_source(g):
    g.panels()
    g.arrow(6, 12, 18, 12, BLUE, 3)


def _new_tab(g):
    g.poly([(2.5, 20), (2.5, 6), (4, 4.5), (10, 4.5), (11.5, 8), (21.5, 8), (21.5, 20)], None, None, True)
    g.line(12, 11, 12, 17, GREEN, 2.2)
    g.line(9, 14, 15, 14, GREEN, 2.2)


def _clipboard_names(g):
    g.rect(4.5, 4.5, 15, 17, 2)
    g.rect(8.5, 2.5, 7, 4, 1.2, None, "fg")
    for y, c in ((11, BLUE), (14, None), (17, None)):
        g.line(8, y, 16, y, c)


def _calcspace(g):
    g.circle(12, 12, 8.5)
    path = QtGui.QPainterPath()
    path.moveTo(12, 12)
    path.lineTo(12, 3.5)
    path.arcTo(QtCore.QRectF(3.5, 3.5, 17, 17), 90, -120)
    path.closeSubpath()
    g.path(path, False, BLUE)


def _properties(g):
    g.rect(3.5, 3.5, 17, 17, 3)
    g.circle(12, 8, 1.3, False, BLUE)
    g.line(12, 11.5, 12, 17, BLUE, 2.2)


def _paste(g):
    g.rect(3.5, 4.5, 13, 16, 2)
    g.rect(7, 2.5, 6, 4, 1.2, None, "fg")
    g.doc(11, 10, 10, 12, BLUE)


def _cut(g):
    g.circle(7, 17.5, 3)
    g.circle(17, 17.5, 3)
    g.line(9, 15.3, 17, 3.5, BLUE)
    g.line(15, 15.3, 7, 3.5, BLUE)


def _exit(g):
    g.poly([(13, 4), (5, 4), (5, 20), (13, 20)])
    g.arrow(9.5, 12, 20.5, 12, RED, 3.4, 2.2)


def _filter(g):
    g.poly([(3.5, 4.5), (20.5, 4.5), (14, 12.5), (14, 19.5), (10, 17.5), (10, 12.5)], None, None, True)
    g.line(6.5, 7.5, 17.5, 7.5, BLUE, 1.4)


def _split(g):
    g.doc(6, 2.5, 12, 19)
    g.line(3, 12, 21, 12, RED, 1.6)
    for x in (4, 8, 12, 16, 20):
        g.line(x, 12, x + 1.2, 12, False, 1)


def _help(g):
    g.circle(12, 12, 8.5)
    g.text(5, 4.5, 14, 15, "?", BLUE, 12)


DRAW = {
    "cm_RereadSource": _reread, "cm_RereadF2": _reread,
    "cm_BriefView": _brief, "cm_FullView": _full, "cm_ThumbnailsView": _thumbs, "cm_TreeView": _tree,
    "cm_QuickView": _quickview,
    "cm_SelectAll": _select_all, "cm_SelectAllBoth": _select_all, "cm_InvertSelection": _invert,
    "cm_ExchangeSelBoth": _invert,
    "cm_PackFiles": _pack, "cm_UnpackFiles": _unpack, "cm_TestArchive": _pack,
    "cm_SearchFor": _search, "cm_QuickSearch": _search, "cm_QuickFilter": _filter, "cm_UserFilter": _filter,
    "cm_MultiRenameFiles": _multirename, "cm_RenameOnly": _multirename,
    "cm_CompareDirs": _compare_dirs, "cm_SyncDirs": _sync, "cm_CompareFilesByContent": _compare_files,
    "cm_OpenTerminal": _terminal, "cm_ConfigShowHidden": _hidden, "cm_Config": _config,
    "cm_Copy": _copy, "cm_CopySamePanel": _copy, "cm_CopyToClipboard": _copy, "cm_RenMov": _move,
    "cm_MkDir": _mkdir, "cm_Delete": _delete, "cm_DeletePermanent": _delete,
    "cm_View": _view, "cm_Edit": _edit, "cm_EditNewFile": _edit,
    "cm_ConnectNetwork": _network, "cm_DisconnectNetwork": _disconnect,
    "cm_DirHotlist": _hotlist, "cm_SwapPanels": _swap, "cm_TargetEqualSource": _target_eq_source,
    "cm_OpenNewTab": _new_tab, "cm_CopyNamesToClip": _clipboard_names, "cm_CopyFullNamesToClip": _clipboard_names,
    "cm_CalcSpace": _calcspace, "cm_Properties": _properties, "cm_ChangeAttributes": _properties,
    "cm_PasteFromClipboard": _paste, "cm_CutToClipboard": _cut, "cm_Exit": _exit,
    "cm_SplitFile": _split, "cm_Keyboard": _help, "cm_About": _help,
}


class _Engine(QtGui.QIconEngine):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def clone(self):
        return _Engine(self.fn)

    def paint(self, painter, rect, mode, state):
        pal = QtWidgets.QApplication.palette()
        fg = pal.color(QtGui.QPalette.ColorGroup.Disabled if mode == QtGui.QIcon.Mode.Disabled
                       else QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorRole.ButtonText)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        side = min(rect.width(), rect.height())
        painter.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
        painter.scale(side / 24.0, side / 24.0)
        if mode == QtGui.QIcon.Mode.Disabled:
            painter.setOpacity(0.45)
        self.fn(_Pen(painter, fg))
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QtGui.QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        self.paint(p, QtCore.QRect(QtCore.QPoint(0, 0), size), mode, state)
        p.end()
        return pm


def builtin_icon(cmd):
    """Theme-independent icon for an internal command, or None."""
    fn = DRAW.get(cmd)
    if not fn:
        return None
    from .toolicons import tool_icon
    return tool_icon(fn.__name__.lstrip("_")) or QtGui.QIcon(_Engine(fn))
