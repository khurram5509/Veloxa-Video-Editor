"""V14.10.0 tooltip audit: every interactive widget must carry a
tooltip, every tooltip must be mirrored into accessibleDescription
(screen-reader path), and every menu must actually SHOW its action
tooltips (QMenu hides them unless setToolTipsVisible(True)).

Constructs the real MainWindow offscreen so the checks cover the live
widget tree, not source grep.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---- HARD ISOLATION (V14.11.3) -------------------------------------
# Sandbox BOTH stores before importing `app`: %APPDATA% (queue state /
# drafts / logs) and VELOXA_SETTINGS_FILE (the QSettings store, which is
# otherwise the Windows REGISTRY). Constructing MainWindow against the
# real registry can rewrite profiles; this suite must never touch them.
import tempfile
_SANDBOX = Path(tempfile.mkdtemp(prefix="veloxa_v1410tt_home_"))
os.environ["APPDATA"] = str(_SANDBOX)
os.environ["VELOXA_SETTINGS_FILE"] = str(_SANDBOX / "settings.ini")

from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QCheckBox, QComboBox, QSpinBox,
    QDoubleSpinBox, QLineEdit, QSlider,
)
from PyQt6.QtGui import QIcon

_app = QApplication.instance() or QApplication(sys.argv)

from app.main_window import MainWindow
from app.dialogs import mirror_tooltips_to_accessibility  # noqa: F401
from app.persistence import queue_state_path, clear_queue_state

# Sandbox starts empty: no previous queue, so no modal resume prompt.
_qpath = queue_state_path()
_qbackup = None

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


print()
print("=" * 72)
print("V14.10.0 -- tooltip + accessibility audit")
print("=" * 72)

mw = MainWindow(app_icon=QIcon(), log_file_path=ROOT / "veloxa.log")
# Isolation guard: fail LOUDLY if the settings store is not the sandbox.
# (Compare resolved paths: Qt reports forward slashes, tempfile gives
# backslashes on Windows.)
assert Path(mw.settings.fileName()).resolve().is_relative_to(
    _SANDBOX.resolve()), f"settings NOT sandboxed: {mw.settings.fileName()}"

INTERACTIVE = (QPushButton, QCheckBox, QComboBox, QSpinBox,
               QDoubleSpinBox, QLineEdit, QSlider)

print()
print("[1] Every visible interactive widget has a tooltip")
missing, tipped, mirrored = [], 0, 0
for w in mw.findChildren(QWidget):
    if not isinstance(w, INTERACTIVE):
        continue
    # Qt builds an internal QLineEdit inside every spin box; the spin
    # box itself carries the tooltip, so the internal child is exempt.
    if w.objectName() == "qt_spinbox_lineedit":
        continue
    # Hidden compat widgets (e.g. the locked speed-tier combo) are
    # exempt -- the user can never hover them.
    if not w.isVisibleTo(mw) and not w.toolTip():
        continue
    if w.toolTip():
        tipped += 1
        if w.accessibleDescription():
            mirrored += 1
    else:
        missing.append(
            f"{type(w).__name__}({w.objectName() or 'unnamed'})")

check(f"0 interactive widgets missing a tooltip ({tipped} tipped)",
      not missing, "; ".join(missing[:10]))
check("Every tooltip is mirrored to accessibleDescription "
      f"({mirrored}/{tipped})",
      mirrored == tipped)

print()
print("[2] Menus show tooltips and every action has one")
menus = {a.text(): a.menu() for a in mw.menuBar().actions() if a.menu()}
for name in ("Tools", "Help", "Appearance"):
    m = menus.get(name)
    check(f"{name} menu exists", m is not None)
    if m is None:
        continue
    check(f"{name} menu has toolTipsVisible", m.toolTipsVisible())
    acts = [a for a in m.actions() if not a.isSeparator()]
    untipped = [a.text() for a in acts
                if not a.toolTip() or a.toolTip() == a.text()]
    check(f"{name}: all {len(acts)} actions have tooltips",
          not untipped, "; ".join(untipped))

print()
print("[3] Settings tabs carry tab tooltips")
tab_widget = None
for w in mw.findChildren(QWidget):
    if type(w).__name__ == "QTabWidget":
        tab_widget = w
        break
check("QTabWidget found", tab_widget is not None)
if tab_widget is not None:
    empty = [tab_widget.tabText(i) for i in range(tab_widget.count())
             if not tab_widget.tabToolTip(i)]
    check(f"All {tab_widget.count()} tabs have tab tooltips",
          not empty, "; ".join(empty))

print()
print("[4] Dialogs mirror tooltips for screen readers")
d_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")
check("dialogs.py defines mirror_tooltips_to_accessibility",
      "def mirror_tooltips_to_accessibility" in d_src)
check("All 3 dialog classes call the mirror helper",
      d_src.count("mirror_tooltips_to_accessibility(self)") >= 3)
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("Folder-format picker dialog mirrors tooltips",
      "mirror_tooltips_to_accessibility(dlg)" in mw_src)
check("MainWindow mirrors its own tree at startup",
      "mirror_tooltips_to_accessibility(self)" in mw_src)

print()
print("[5] Failed silent startup update-check must not erase GPU status")
# Bug-report 04/09 #3: the auto-check fires ~1.5 s after the GPU summary
# is written; on a rate-limited / offline launch it overwrote that line.
gpu = mw._describe_gpu_status()
mw._gpu_status_text = gpu
mw.status_lbl.setText(gpu)
mw._on_update_check_failed("GitHub's hourly API limit was reached",
                           manual=False)
check("GPU summary survives a failed silent auto-check",
      mw.status_lbl.text() == gpu, repr(mw.status_lbl.text())[:80])
mw.status_lbl.setText("Ready")
mw._on_update_check_failed("offline", manual=False)
check("a non-GPU status line still gets the failure notice",
      "Update check unavailable" in mw.status_lbl.text())

mw.deleteLater()

# Restore the user's real queue state exactly as we found it.
if _qbackup is None:
    clear_queue_state()
else:
    _qpath.write_text(_qbackup, encoding="utf-8")

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All tooltip-audit checks PASS.")
sys.exit(0)
