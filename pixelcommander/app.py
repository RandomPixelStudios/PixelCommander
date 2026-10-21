"""Application entry point."""
import argparse
import os
import signal
import sys


def main():
    parser = argparse.ArgumentParser(prog="pixelcommander", description="Zwei-Fenster-Dateimanager")
    parser.add_argument("left", nargs="?", help="Startverzeichnis links")
    parser.add_argument("right", nargs="?", help="Startverzeichnis rechts")
    args = parser.parse_args()

    from .qt import QtWidgets, QtGui, QtCore, qexec
    QtWidgets.QApplication.setApplicationName("PixelCommander")
    QtWidgets.QApplication.setOrganizationName("pixelcommander")
    if hasattr(QtGui.QGuiApplication, "setDesktopFileName"):
        QtGui.QGuiApplication.setDesktopFileName("pixelcommander")
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from .mainwindow import PixelCommander
    w = PixelCommander(os.path.abspath(args.left) if args.left else None,
                       os.path.abspath(args.right) if args.right else None)
    w.show()
    sys.exit(qexec(app))


if __name__ == "__main__":
    main()
