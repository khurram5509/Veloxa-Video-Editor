"""Visual theme: QSS stylesheet, color tokens, time/ETA formatters, runtime icon."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


# Brand palette (orange accent inspired by the VeloxaLAB logo).
BRAND_ACCENT = "#f58220"
BRAND_ACCENT_HOVER = "#ff9a3d"
BRAND_ACCENT_DARK = "#d66e10"
BRAND_HANDLE = "#fbbf24"


DARK_QSS = """
QMainWindow, QWidget { background-color: #2a2d33; color: #e6e6e6; }
QLabel { color: #e6e6e6; }
QLabel[role="muted"] { color: #8a8e96; }
QLabel[role="title"] { font-size: 18pt; font-weight: 800; color: #ffffff; }
QLabel[role="subtitle"] { color: #f58220; font-size: 9pt; font-weight: 600; }

QGroupBox {
    background: #353841;
    border: 1px solid #454952;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
    color: #e6e6e6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
    color: #f58220;
}

QPushButton {
    background: #454952;
    color: #e6e6e6;
    border: 1px solid #555a64;
    border-radius: 5px;
    padding: 6px 14px;
    min-height: 22px;
}
QPushButton:hover { background: #555a64; border-color: #6a6f79; }
QPushButton:pressed { background: #3a3e47; }
QPushButton:disabled { background: #2e3138; color: #6a6f79; border-color: #3e424a; }

QPushButton#primary {
    background: #f58220; color: #1a1a1a; border: none; font-weight: 700;
}
QPushButton#primary:hover { background: #ff9a3d; }
QPushButton#primary:pressed { background: #d66e10; }
QPushButton#primary:disabled { background: #5a3a1a; color: #888; }

QPushButton#danger { background: #b85a5a; color: #fff; border: none; }
QPushButton#danger:hover { background: #c66a6a; }
QPushButton#danger:disabled { background: #3a2a2a; color: #888; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #2a2d33;
    color: #e6e6e6;
    border: 1px solid #454952;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 22px;
    selection-background-color: #f58220;
    selection-color: #1a1a1a;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #f58220;
}
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #2a2d33;
    color: #e6e6e6;
    border: 1px solid #454952;
    selection-background-color: #f58220;
    selection-color: #1a1a1a;
}

QListWidget {
    background: #232529;
    color: #e6e6e6;
    border: 1px solid #454952;
    border-radius: 5px;
    padding: 2px;
}
QListWidget::item { padding: 6px 8px; }
QListWidget::item:hover { background: #2c3036; }
QListWidget::item:selected { background: #6a3d10; color: #ffffff; }
/* `:selected:hover` has higher specificity than `:hover` alone, so the
 * selection highlight stays visible when the mouse moves over a selected
 * row. Without this rule, hover overwrites the orange selection background
 * and the row looks unselected the moment you mouse over it. */
QListWidget::item:selected:hover { background: #7a4520; color: #ffffff; }
QListWidget::item:selected:!active { background: #4a3010; color: #ffffff; }
QListWidget:focus { border: 1px solid #f58220; }

QSlider::groove:horizontal {
    background: #2a2d33;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal { background: #f58220; border-radius: 3px; }
QSlider::add-page:horizontal { background: #454952; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #ffffff;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 1px solid #f58220;
}
QSlider::handle:horizontal:hover { background: #ffe5cc; }

QProgressBar {
    background: #232529;
    border: 1px solid #454952;
    border-radius: 5px;
    text-align: center;
    color: #e6e6e6;
    height: 18px;
}
QProgressBar::chunk { background: #f58220; border-radius: 4px; }

/* V12.1 improvement: status-colored slim per-row progress bar. The
 * dynamic `state` property is set in _refresh_row_widget; restyle
 * after polish/unpolish so colour swaps when the row's status moves
 * encoding -> done / failed / cancelled. */
QProgressBar[role="queue-row-progress"] {
    background: #1f2125;
    border: 1px solid #353940;
    border-radius: 3px;
    height: 12px;
    padding: 0;
}
QProgressBar[role="queue-row-progress"][state="encoding"]::chunk
    { background: #f58220; border-radius: 2px; }
QProgressBar[role="queue-row-progress"][state="done"]::chunk
    { background: #4caf50; border-radius: 2px; }
QProgressBar[role="queue-row-progress"][state="failed"]::chunk
    { background: #d63b3b; border-radius: 2px; }
QProgressBar[role="queue-row-progress"][state="cancelled"]::chunk
    { background: #6b6f78; border-radius: 2px; }

QTabWidget::pane {
    border: 1px solid #454952;
    border-radius: 6px;
    background: #353841;
    top: -1px;
}
QTabBar::tab {
    background: #2a2d33;
    color: #aaa;
    padding: 7px 16px;
    border: 1px solid #454952;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #353841; color: #f58220; font-weight: 600; }
QTabBar::tab:hover { color: #ffffff; }

QToolTip {
    background: #1e1e1e;
    color: #e6e6e6;
    border: 1px solid #454952;
    padding: 4px;
}

QSplitter::handle { background: #2a2d33; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:hover { background: #f58220; }

QFrame#preview {
    background: #0c0e12;
    border: 1px solid #454952;
    border-radius: 6px;
}

QMenu {
    background: #2a2d33;
    color: #e6e6e6;
    border: 1px solid #454952;
}
QMenu::item:selected { background: #f58220; color: #1a1a1a; }

QMenuBar {
    background: #232529;
    color: #e6e6e6;
    border-bottom: 1px solid #454952;
    padding: 2px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 14px;
    border-radius: 4px;
}
QMenuBar::item:selected { background: #f58220; color: #1a1a1a; }
QMenuBar::item:pressed { background: #d66e10; color: #1a1a1a; }

QTextBrowser {
    background: #232529;
    color: #e6e6e6;
    border: 1px solid #454952;
    border-radius: 5px;
    padding: 10px;
    selection-background-color: #f58220;
    selection-color: #1a1a1a;
}
QTextBrowser a { color: #f58220; }

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555a64;
    border-radius: 3px;
    background: #2a2d33;
}
QCheckBox::indicator:checked {
    background: #f58220;
    border-color: #f58220;
}
"""


def fmt_time(seconds: float) -> str:
    if seconds is None or seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - 3600 * h - 60 * m
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


def fmt_eta(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"


def make_runtime_icon() -> QIcon:
    """Build the app icon programmatically (orange V on dark background)."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(QColor("#0c0e12"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font_size = int(size * 0.72)
        f = QFont("Arial", font_size, QFont.Weight.Black)
        p.setFont(f)
        p.setPen(QColor(BRAND_ACCENT))
        rect = pm.rect().adjusted(0, max(2, size // 12), 0, 0)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "V")
        # Two umlaut squares above
        dot = max(2, size // 14)
        dy = max(1, size // 12)
        cx = size // 2
        gap = max(2, size // 7)
        p.fillRect(cx - gap - dot // 2, dy, dot, dot, QColor(BRAND_ACCENT))
        p.fillRect(cx + gap - dot // 2, dy, dot, dot, QColor(BRAND_ACCENT))
        p.end()
        icon.addPixmap(pm)
    return icon
