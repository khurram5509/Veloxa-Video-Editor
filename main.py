"""Veloxa Video Editor V13.0 - entry point.

If ``--cli`` is on argv, dispatch to the headless CLI runner. Otherwise
launch the Qt GUI. All real logic lives in the ``engine`` and ``app``
packages.
"""
from __future__ import annotations

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


def main():
    # CLI mode: avoid pulling in QtWidgets / building a window.
    if "--cli" in sys.argv:
        # Strip the --cli flag itself so argparse sees a clean argv.
        argv = [a for a in sys.argv[1:] if a != "--cli"]
        from app.cli import run_cli
        sys.exit(run_cli(argv))

    # GUI mode.
    from PyQt6.QtCore import QSettings
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication
    from app.main_window import MainWindow
    from app.persistence import setup_logging, prune_old_logs
    from app.theme import apply_theme, THEME_SYSTEM

    log_file = setup_logging()
    prune_old_logs(keep=30)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    # V13.1: System / Light / Dark theme switcher. Default is "system"
    # so a fresh install on Windows light-mode looks native; the user
    # can override via the View menu.
    s = QSettings("Veloxa-VD", "V10")
    apply_theme(app, s.value("theme_mode", THEME_SYSTEM))

    icon = _load_icon()
    app.setWindowIcon(icon)

    w = MainWindow(icon, log_file)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
