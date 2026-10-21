"""Qt compatibility layer: PyQt6 preferred, PyQt5 as fallback (Debian 11 / Ubuntu 20.04)."""
import os

_force5 = os.environ.get("PIXELCOMMANDER_QT") == "5"

try:
    if _force5:
        raise ImportError
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt6.QtCore import Qt  # noqa: F401
    from PyQt6.QtGui import QAction, QShortcut, QActionGroup  # noqa: F401
    QT6 = True
except ImportError:
    from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt5.QtCore import Qt  # noqa: F401
    from PyQt5.QtWidgets import QAction, QShortcut, QActionGroup  # noqa: F401
    QT6 = False

Signal = QtCore.pyqtSignal
Slot = QtCore.pyqtSlot


def qexec(obj, *args):
    """Call exec()/exec_() depending on binding."""
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn(*args)


def mods_of(event):
    """Return keyboard modifiers of an event as plain int-like flag object."""
    return event.modifiers()


def has_mod(event, mod):
    return bool(event.modifiers() & mod)


def event_pos(event):
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def global_pos(event):
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
KEYPAD = Qt.KeyboardModifier.KeypadModifier
NOMOD = Qt.KeyboardModifier.NoModifier
