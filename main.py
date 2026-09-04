"""Veloxa Video Editor V14.1 - entry point.

If ``--cli`` is on argv, dispatch to the headless CLI runner. Otherwise
launch the Qt GUI. All real logic lives in the ``engine`` and ``app``
packages.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_icon():
    from PyQt6.QtGui import QIcon
    from app.theme import make_runtime_icon
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "app.ico"
        if bundled.exists():
            return QIcon(str(bundled))
    else:
        local = Path(__file__).resolve().parent / "app.ico"
        if local.exists():
            return QIcon(str(local))
    return make_runtime_icon()


def _enable_high_dpi():
    """V14.1.0: enable Qt's HiDPI scaling BEFORE QApplication is
    constructed. PassThrough rounding means we preserve fractional
    scale factors (125%, 150%, 175%, …) instead of snapping to
    integer multiples — important on Windows where most laptops use
    150% by default and snapping to 100% or 200% looks wrong.
    """
    from PyQt6.QtCore import Qt
    try:
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    # The two env vars below are set BEFORE QApplication construction
    # so they take effect for this process. Defensive — most Qt6
    # builds enable HiDPI by default, but explicit beats implicit.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def main():
    # CLI mode: avoid pulling in QtWidgets / building a window.
    if "--cli" in sys.argv:
        # Strip the --cli flag itself so argparse sees a clean argv.
        argv = [a for a in sys.argv[1:] if a != "--cli"]
        from app.cli import run_cli
        sys.exit(run_cli(argv))

    # V14.1: HiDPI before any Qt class is instantiated.
    _enable_high_dpi()

    # GUI mode.
    from PyQt6.QtCore import QSettings
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from app.main_window import MainWindow
    from app.persistence import setup_logging, prune_old_logs
    from app.theme import apply_theme, THEME_SYSTEM
    from app import single_instance

    log_file = setup_logging()
    prune_old_logs(keep=30)

    # V14.5.0: opt-in crash reporter. Install the excepthook BEFORE
    # we touch Qt — that way even an exception during ``MainWindow``
    # construction lands in a crash file under
    # ``%APPDATA%\Veloxa-VD\V10\logs\crash_*.txt``. On the next
    # successful launch the GUI scans for pending crash files and (if
    # the user has opted in) offers to send them via a pre-filled
    # GitHub Issue.
    try:
        from app.crash_reporter import install_excepthook
        from app.updater import APP_VERSION
        from app.persistence import log_dir as _log_dir
        install_excepthook(_log_dir(), log_file, APP_VERSION)
    except Exception:
        # Crash reporter is opt-in and never required for normal
        # operation — if it fails to install, log and continue.
        import logging as _logging
        _logging.getLogger("veloxa").info(
            "Could not install crash reporter (continuing)", exc_info=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    # V13.1: System / Light / Dark theme switcher. Default is "system"
    # so a fresh install on Windows light-mode looks native; the user
    # can override via the View menu.
    from app.persistence import app_qsettings
    s = app_qsettings()   # V14.11.3: honours VELOXA_SETTINGS_FILE
    apply_theme(app, s.value("theme_mode", THEME_SYSTEM))

    icon = _load_icon()
    app.setWindowIcon(icon)

    # V14.1: single-instance guard. If another instance is already
    # running, ping it (which raises + focuses its window) and exit.
    if not single_instance.request_single_instance():
        # A primary instance was found and signalled — show a quick
        # toast and exit. Using a tray-style modal so the user gets
        # immediate feedback their click registered.
        msg = QMessageBox()
        msg.setWindowIcon(icon)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Veloxa Video Editor")
        msg.setText("Veloxa Video Editor is already running.")
        msg.setInformativeText(
            "The existing window has been brought to the front.")
        # Auto-close after 2 seconds so the user doesn't have to dismiss.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, msg.close)
        msg.exec()
        sys.exit(0)

    w = MainWindow(icon, log_file)
    # V14.1: wire single-instance activation to the main window so a
    # second launch raises + focuses this one.
    single_instance.install_activation_handler(
        lambda: _activate_window(w))
    w.show()
    sys.exit(app.exec())


def _activate_window(w):
    """V14.1: bring the main window to the foreground in response to
    a second-instance launch. Handles minimised, hidden, and
    background-but-visible cases."""
    from PyQt6.QtCore import Qt
    try:
        if w.isMinimized():
            w.showNormal()
        if not w.isVisible():
            w.show()
        w.raise_()
        # activateWindow is the canonical "give me focus" call;
        # setWindowState with the active flag is a belt-and-braces
        # for the minimised+hidden cases.
        w.setWindowState(
            (w.windowState() & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowActive)
        w.activateWindow()
    except Exception:
        pass


if __name__ == "__main__":
    main()
