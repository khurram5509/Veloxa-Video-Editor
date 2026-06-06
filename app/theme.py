"""Visual theme: QSS stylesheets (dark + light), system-theme detection,
time/ETA formatters, runtime icon.

V13.1: refreshed design + System / Light / Dark theme switcher.

Public surface for the rest of the app:

* :data:`DARK_QSS`, :data:`LIGHT_QSS` — full Qt stylesheets.
* :func:`detect_system_theme` — ``"dark"`` or ``"light"``, derived from the
  Windows registry's ``AppsUseLightTheme`` key (falls back to dark on any
  platform / error).
* :func:`resolve_theme_mode` — collapses ``"system"`` into ``"dark"`` or
  ``"light"`` so the caller can use a single switch.
* :func:`apply_theme` — given a ``QApplication`` and a mode string,
  applies the right stylesheet.

The brand accent (orange) is preserved across both themes so the app is
recognisably Veloxa whichever variant the user picks.
"""
from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

log = logging.getLogger("veloxa.theme")


# ============================================================ brand palette

# Orange accent inspired by the VeloxaLAB logo. Used by both themes.
BRAND_ACCENT = "#f58220"
BRAND_ACCENT_HOVER = "#ff9a3d"
BRAND_ACCENT_DARK = "#d66e10"
BRAND_HANDLE = "#fbbf24"

# Theme mode strings. Persisted in QSettings under ``theme_mode``.
THEME_SYSTEM = "system"
THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_OLED = "oled"  # V14.0: pure-black variant for OLED panels
THEME_MODES = (THEME_SYSTEM, THEME_DARK, THEME_LIGHT, THEME_OLED)


# ============================================================ DARK QSS
#
# V13.1 design refresh: deeper-but-warmer panel background, softer
# borders, accent-coloured focus ring on all editable widgets, calmer
# button hover state, refined tab look.

DARK_QSS = """
/* ---- base ---- */
QMainWindow, QWidget {
    background-color: #23262d;
    color: #e8e9ec;
}
QLabel { color: #e8e9ec; }
QLabel[role="muted"]    { color: #8b909a; }
QLabel[role="title"]    { font-size: 18pt; font-weight: 800; color: #ffffff;
                          letter-spacing: 0.5px; }
QLabel[role="subtitle"] { color: #f58220; font-size: 9pt; font-weight: 700;
                          letter-spacing: 0.4px; }

/* ---- group boxes ---- */
QGroupBox {
    background: #2d313a;
    border: 1px solid #3d424e;
    border-radius: 10px;
    margin-top: 16px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
    color: #e8e9ec;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: #f58220;
}

/* ---- buttons ---- */
QPushButton {
    background: #3a3f4a;
    color: #e8e9ec;
    border: 1px solid #4b505c;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 22px;
}
QPushButton:hover    { background: #454b59; border-color: #5d6471; }
QPushButton:pressed  { background: #2f343e; }
QPushButton:disabled { background: #2a2d34; color: #6a6f79; border-color: #383c45; }

QPushButton#primary {
    background: #f58220; color: #1a1a1a; border: none; font-weight: 700;
}
QPushButton#primary:hover    { background: #ff9a3d; }
QPushButton#primary:pressed  { background: #d66e10; }
QPushButton#primary:disabled { background: #5a3a1a; color: #888; }

QPushButton#danger          { background: #b95252; color: #fff; border: none; }
QPushButton#danger:hover    { background: #c96363; }
QPushButton#danger:disabled { background: #3a2a2a; color: #888; }

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #1d2026;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    border-radius: 6px;
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
    background: #1d2026;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    selection-background-color: #f58220;
    selection-color: #1a1a1a;
}

/* ---- list / queue ---- */
QListWidget {
    background: #1a1d22;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    border-radius: 6px;
    padding: 2px;
}
QListWidget::item                { padding: 6px 8px; }
QListWidget::item:hover          { background: #262a31; }
QListWidget::item:selected       { background: #6a3d10; color: #ffffff; }
QListWidget::item:selected:hover { background: #7a4520; color: #ffffff; }
QListWidget::item:selected:!active { background: #4a3010; color: #ffffff; }
QListWidget:focus                { border: 1px solid #f58220; }

/* V14.3.6: queue-row-label colour is now driven from the QSS so it
   tracks the active theme. The label has a ``selected`` dynamic
   property updated by main_window._apply_row_selection_styles. */
QLabel[role="queue-row-label"] {
    color: #e6e6e6;
    background: transparent;
}
QLabel[role="queue-row-label"][selected="true"] {
    color: #ffffff;
    background: transparent;
    font-weight: 600;
}

/* ---- slider ---- */
QSlider::groove:horizontal {
    background: #1d2026;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal { background: #f58220; border-radius: 3px; }
QSlider::add-page:horizontal { background: #3d424e; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #ffffff;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 1px solid #f58220;
}
QSlider::handle:horizontal:hover { background: #ffe5cc; }

/* ---- progress ---- */
QProgressBar {
    background: #1a1d22;
    border: 1px solid #3d424e;
    border-radius: 6px;
    text-align: center;
    color: #e8e9ec;
    height: 18px;
}
QProgressBar::chunk { background: #f58220; border-radius: 5px; }

QProgressBar[role="queue-row-progress"] {
    background: #161920;
    border: 1px solid #2e3138;
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

/* ---- tabs ---- */
QTabWidget::pane {
    border: 1px solid #3d424e;
    border-radius: 8px;
    background: #2d313a;
    top: -1px;
}
QTabBar::tab {
    background: #23262d;
    color: #9aa0aa;
    padding: 7px 16px;
    border: 1px solid #3d424e;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #2d313a; color: #f58220; font-weight: 700; }
QTabBar::tab:hover    { color: #ffffff; }

/* V14.3.8: settings tabs are now wrapped in QScrollArea so their
   natural content height can exceed the tab pane (macOS native
   controls are taller than Windows defaults, causing row overlap
   without scroll). Style the scroll area + its viewport flat so it
   reads as part of the tab pane, not a sunken sub-frame. */
QScrollArea          { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical  {
    background: #23262d; width: 10px; margin: 2px 0; border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #4a4f5a; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #5d6371; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---- tooltip ---- */
QToolTip {
    background: #15171c;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    border-radius: 4px;
    padding: 5px 7px;
}

/* ---- splitter ---- */
QSplitter::handle             { background: #23262d; }
QSplitter::handle:horizontal  { width: 4px; }
QSplitter::handle:hover       { background: #f58220; }

/* ---- preview frame ---- */
QFrame#preview {
    background: #0c0e12;
    border: 1px solid #3d424e;
    border-radius: 8px;
}

/* ---- menus ---- */
QMenu {
    background: #23262d;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    padding: 4px 0;
}
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: #f58220; color: #1a1a1a; }
QMenu::separator { height: 1px; background: #3d424e; margin: 4px 8px; }

QMenuBar {
    background: #1a1d22;
    color: #e8e9ec;
    border-bottom: 1px solid #3d424e;
    padding: 2px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 14px;
    border-radius: 4px;
}
QMenuBar::item:selected { background: #f58220; color: #1a1a1a; }
QMenuBar::item:pressed  { background: #d66e10; color: #1a1a1a; }

/* ---- text browser (README dialogs etc.) ---- */
QTextBrowser {
    background: #1a1d22;
    color: #e8e9ec;
    border: 1px solid #3d424e;
    border-radius: 6px;
    padding: 12px;
    selection-background-color: #f58220;
    selection-color: #1a1a1a;
}
QTextBrowser a { color: #f58220; }

/* ---- checkbox ---- */
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4b505c;
    border-radius: 3px;
    background: #1d2026;
}
QCheckBox::indicator:checked {
    background: #f58220;
    border-color: #f58220;
}
QCheckBox::indicator:hover { border-color: #f58220; }

/* ---- scrollbars (subtle, dark-on-dark) ---- */
QScrollBar:vertical {
    background: #1a1d22;
    width: 12px;
    border-left: 1px solid #2e3138;
}
QScrollBar::handle:vertical {
    background: #3d424e;
    border-radius: 4px;
    min-height: 24px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #555a64; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1a1d22;
    height: 12px;
    border-top: 1px solid #2e3138;
}
QScrollBar::handle:horizontal {
    background: #3d424e;
    border-radius: 4px;
    min-width: 24px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #555a64; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


# ============================================================ LIGHT QSS
#
# A bright, calm light theme keyed to the same orange accent. Neutral
# warm-gray surfaces (avoiding pure white which is harsh under prolonged
# editing) and a darker text colour. Selection / focus / hover use the
# same brand colour as dark mode so a user switching between modes sees
# consistent emphasis cues.

LIGHT_QSS = """
/* ====================================================================
 * V13.1.1 light theme redesign.
 *
 * Goal: real visual hierarchy. The previous version was white-on-white
 * everywhere so panels and chrome blurred together. This pass:
 *   - Main window is a tinted off-white (#eef0f4) so white cards pop.
 *   - Cards (group boxes, list widgets, tab pane, text browsers) sit
 *     on pure #ffffff with a soft 1 px border + 12-14 px border radius.
 *   - Buttons get a subtle vertical gradient for a "raised" feel and
 *     a stronger 1 px shadow line beneath.
 *   - Selected tabs get a 2 px brand-orange bottom border.
 *   - Menubar has a clear bottom border separating chrome from content.
 *   - Bottom strip / status area has a subtle top border to anchor it.
 *   - Hover and pressed states are clearly differentiated.
 * ==================================================================== */

/* ---- base ---- */
QMainWindow {
    background-color: #eef0f4;
}
QWidget {
    background-color: #eef0f4;
    color: #1c2128;
}
QLabel { color: #1c2128; background: transparent; }
QLabel[role="muted"]    { color: #6e7682; }
QLabel[role="title"]    { font-size: 18pt; font-weight: 800; color: #0d1117;
                          letter-spacing: 0.3px; }
QLabel[role="subtitle"] { color: #d66e10; font-size: 9pt; font-weight: 700;
                          letter-spacing: 0.4px; }

/* ---- group boxes (the main "card" surface) ---- */
QGroupBox {
    background: #ffffff;
    border: 1px solid #d6dbe2;
    border-radius: 12px;
    margin-top: 18px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
    color: #1c2128;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    padding: 0 8px;
    color: #d66e10;
    background: #ffffff;
}

/* ---- buttons (subtle gradient = depth) ---- */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ffffff, stop:1 #f0f2f5);
    color: #1c2128;
    border: 1px solid #c4cad3;
    border-bottom-color: #b1b8c3;
    border-radius: 7px;
    padding: 6px 14px;
    min-height: 22px;
    font-weight: 500;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #fafbfc, stop:1 #e8ebef);
    border-color: #9aa1ad;
    border-bottom-color: #888f9b;
}
QPushButton:pressed {
    background: #e2e6eb;
    border-color: #9aa1ad;
    padding-top: 7px;
    padding-bottom: 5px;
}
QPushButton:disabled {
    background: #f0f2f5;
    color: #a5aab2;
    border-color: #dcdfe5;
}

QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ff9a3d, stop:1 #f58220);
    color: #ffffff;
    border: 1px solid #c66510;
    border-radius: 7px;
    font-weight: 700;
    padding: 6px 16px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ffae5c, stop:1 #ff9128);
}
QPushButton#primary:pressed { background: #d66e10; border-color: #a85510; }
QPushButton#primary:disabled {
    background: #f7c89a; color: #ffffff; border-color: #e5b285;
}

QPushButton#danger {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #e25656, stop:1 #c63d3d);
    color: #ffffff;
    border: 1px solid #a82828;
    border-radius: 7px;
    font-weight: 600;
}
QPushButton#danger:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ea6666, stop:1 #d04646);
}
QPushButton#danger:disabled {
    background: #f0bcbc; color: #ffffff; border-color: #d99f9f;
}

/* ---- inputs (subtle inner-shadow look via gradient) ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #f6f7f9, stop:0.1 #ffffff, stop:1 #ffffff);
    color: #1c2128;
    border: 1px solid #c4cad3;
    border-radius: 7px;
    padding: 5px 10px;
    min-height: 22px;
    selection-background-color: #f58220;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 2px solid #f58220;
    padding: 4px 9px;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: #f0f2f5;
    color: #a5aab2;
    border-color: #dcdfe5;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1c2128;
    border: 1px solid #c4cad3;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #f58220;
    selection-color: #ffffff;
    outline: 0;
}

/* ---- list / queue (alternating rows for scanability) ---- */
QListWidget {
    background: #ffffff;
    color: #1c2128;
    border: 1px solid #d6dbe2;
    border-radius: 8px;
    padding: 4px;
    alternate-background-color: #f7f8fa;
    outline: 0;
}
QListWidget::item                { padding: 7px 10px; border-radius: 5px; }
QListWidget::item:alternate      { background: #f7f8fa; }
QListWidget::item:hover          { background: #fff0dc; }
QListWidget::item:selected       { background: #ffe1c2; color: #1c2128; }
QListWidget::item:selected:hover { background: #ffd4a8; color: #1c2128; }
QListWidget::item:selected:!active { background: #fff0dc; color: #1c2128; }
QListWidget:focus                { border: 2px solid #f58220; padding: 3px; }

/* V14.3.6 fix: the per-row widget's filename label was hard-coded to
   light grey / white in main_window._apply_row_selection_styles, which
   was invisible on the light-theme white / cream row backgrounds. The
   label now carries a ``selected`` dynamic property and the colour is
   driven from here so it respects the active theme. */
QLabel[role="queue-row-label"] {
    color: #1c2128;
    background: transparent;
}
QLabel[role="queue-row-label"][selected="true"] {
    color: #1c2128;
    background: transparent;
    font-weight: 600;
}

/* ---- slider ---- */
QSlider::groove:horizontal {
    background: #d6dbe2;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ff9a3d, stop:1 #f58220);
    border-radius: 3px;
}
QSlider::add-page:horizontal { background: #d6dbe2; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #ffffff;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
    border: 2px solid #f58220;
}
QSlider::handle:horizontal:hover { background: #ffe5cc; }
QSlider::handle:horizontal:pressed { background: #ff9a3d; border-color: #d66e10; }

/* ---- progress ---- */
QProgressBar {
    background: #f0f2f5;
    border: 1px solid #d6dbe2;
    border-radius: 7px;
    text-align: center;
    color: #1c2128;
    height: 20px;
    font-weight: 600;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ff9a3d, stop:1 #f58220);
    border-radius: 6px;
}

QProgressBar[role="queue-row-progress"] {
    background: #e8ebef;
    border: 1px solid #cbd0d8;
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
    { background: #9aa0aa; border-radius: 2px; }

/* ---- tabs (selected tab gets a thick orange underline) ---- */
QTabWidget::pane {
    border: 1px solid #d6dbe2;
    border-radius: 10px;
    background: #ffffff;
    top: -1px;
}
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #5b6270;
    padding: 9px 18px 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #d66e10;
    font-weight: 700;
    border-bottom: 2px solid #f58220;
}
QTabBar::tab:hover:!selected { color: #1c2128; }

/* V14.3.8: settings tabs wrapped in QScrollArea for macOS layout
   sanity. Keep the scroll area flat so it reads as part of the tab
   pane (which is already styled with its own border + radius). */
QScrollArea          { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical  {
    background: #eef0f4; width: 10px; margin: 2px 0; border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #c4cad3; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #a5aab2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---- tooltip ---- */
QToolTip {
    background: #1c2128;
    color: #ffffff;
    border: 1px solid #1c2128;
    border-radius: 6px;
    padding: 6px 9px;
    font-weight: 500;
}

/* ---- splitter ---- */
QSplitter::handle             { background: transparent; }
QSplitter::handle:horizontal  { width: 6px; }
QSplitter::handle:hover       { background: #f58220; }

/* ---- preview frame (the dark video pane) ---- */
QFrame#preview {
    background: #15171c;
    border: 1px solid #c4cad3;
    border-radius: 10px;
}

/* ---- menus ---- */
QMenu {
    background: #ffffff;
    color: #1c2128;
    border: 1px solid #c4cad3;
    border-radius: 8px;
    padding: 5px 0;
}
QMenu::item { padding: 7px 26px; }
QMenu::item:selected { background: #f58220; color: #ffffff; }
QMenu::item:disabled { color: #a5aab2; }
QMenu::separator { height: 1px; background: #e8ebef; margin: 5px 10px; }

QMenuBar {
    background: #ffffff;
    color: #1c2128;
    border-bottom: 1px solid #d6dbe2;
    padding: 3px 4px;
    font-weight: 500;
}
QMenuBar::item {
    background: transparent;
    padding: 7px 14px;
    border-radius: 6px;
    margin: 0 2px;
}
QMenuBar::item:selected { background: #f58220; color: #ffffff; }
QMenuBar::item:pressed  { background: #d66e10; color: #ffffff; }

/* ---- text browser (README / Help dialogs) ---- */
QTextBrowser {
    background: #ffffff;
    color: #1c2128;
    border: 1px solid #d6dbe2;
    border-radius: 8px;
    padding: 14px;
    selection-background-color: #f58220;
    selection-color: #ffffff;
}
QTextBrowser a { color: #d66e10; }

/* ---- checkbox ---- */
QCheckBox { spacing: 8px; color: #1c2128; }
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #c4cad3;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #f58220;
    border-color: #f58220;
    image: none;
}
QCheckBox::indicator:hover { border-color: #f58220; }
QCheckBox::indicator:disabled {
    background: #f0f2f5; border-color: #dcdfe5;
}

/* ---- scrollbars ---- */
QScrollBar:vertical {
    background: #f4f5f7;
    width: 12px;
    border-left: 1px solid #e0e3e8;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #c4cad3;
    border-radius: 4px;
    min-height: 30px;
    margin: 3px;
}
QScrollBar::handle:vertical:hover { background: #9aa1ad; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #f4f5f7;
    height: 12px;
    border-top: 1px solid #e0e3e8;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #c4cad3;
    border-radius: 4px;
    min-width: 30px;
    margin: 3px;
}
QScrollBar::handle:horizontal:hover { background: #9aa1ad; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


# ============================================================ OLED QSS
#
# V14.0: pure-black variant for OLED panels. Same brand accent, same
# layout dimensions as DARK_QSS, but background is true #000000 so
# individual pixels are physically off on an OLED. Surfaces step up
# to subtle dark grays for hierarchy.

OLED_QSS = DARK_QSS.replace(
    "#23262d", "#000000"  # main window bg
).replace(
    "#2d313a", "#0e0f12"  # group box / pane surface (was warmer)
).replace(
    "#1a1d22", "#050608"  # menubar / list / progress bg
).replace(
    "#1d2026", "#050608"  # input / combo bg
).replace(
    "#0c0e12", "#000000"  # preview frame
).replace(
    "#15171c", "#000000"  # tooltip bg
).replace(
    "#161920", "#050608"  # queue-row progress bg
).replace(
    "#3a3f4a", "#1a1c20"  # button bg
).replace(
    "#454b59", "#222428"  # button hover
).replace(
    "#2f343e", "#101216"  # button pressed
).replace(
    "#2a2d34", "#0a0b0e"  # button disabled
).replace(
    "#3d424e", "#1f2227"  # border
).replace(
    "#4b505c", "#26292f"  # input border
).replace(
    "#262a31", "#0e1014"  # list item hover
)


# ============================================================ system detect

def detect_system_theme() -> str:
    """Return ``"dark"`` or ``"light"`` based on the OS preference.

    On Windows 10/11 this reads ``AppsUseLightTheme`` from
    ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize``.
    A value of ``0`` means dark mode, ``1`` means light.

    On non-Windows platforms or any failure to read the registry, we
    default to ``"dark"`` (matching the original Veloxa look).
    """
    if sys.platform != "win32":
        return THEME_DARK
    try:
        import winreg  # type: ignore
        sub = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return THEME_LIGHT if int(value) == 1 else THEME_DARK
    except (OSError, ValueError, ImportError) as exc:
        log.info("System theme detect fell back to dark: %s", exc)
        return THEME_DARK


def resolve_theme_mode(mode: str) -> str:
    """Collapse a user preference into the concrete theme to apply
    (``"light"`` / ``"dark"`` / ``"oled"``). ``"system"`` resolves to
    either ``"light"`` or ``"dark"`` based on Windows' preference."""
    if mode == THEME_SYSTEM:
        return detect_system_theme()
    if mode in (THEME_LIGHT, THEME_DARK, THEME_OLED):
        return mode
    return THEME_DARK  # safe fallback for unknown values


_QSS_FOR_MODE = {
    THEME_LIGHT: lambda: LIGHT_QSS,
    THEME_DARK:  lambda: DARK_QSS,
    THEME_OLED:  lambda: OLED_QSS,
}


def apply_theme(app, mode: str):
    """Apply the appropriate stylesheet to ``app`` based on ``mode``.

    ``mode`` is one of ``"system"`` / ``"light"`` / ``"dark"`` / ``"oled"``.
    After resolution, the stylesheet matching the concrete theme is
    applied via ``app.setStyleSheet(...)`` and re-polish is triggered
    so live widgets pick up the new look without a restart.
    """
    concrete = resolve_theme_mode(mode)
    qss = _QSS_FOR_MODE.get(concrete, lambda: DARK_QSS)()
    app.setStyleSheet(qss)
    # Force every existing widget to recompute its style (important when
    # the user flips themes at runtime — without this, some widgets keep
    # their old palette until they're hidden/shown).
    for w in app.allWidgets():
        try:
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()
        except Exception:
            pass
    log.info("Theme applied: mode=%r resolved=%r", mode, concrete)


# ============================================================ formatters

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


# ============================================================ runtime icon

def make_runtime_icon() -> QIcon:
    """Build the app icon programmatically (orange V on dark background).

    The icon is intentionally the same in both themes — the brand mark is
    the orange "V" on a near-black square. A light-theme variant of the
    icon would compete with the OS taskbar/start-menu treatment.
    """
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
