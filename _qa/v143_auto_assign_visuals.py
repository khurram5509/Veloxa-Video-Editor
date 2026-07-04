"""V14.3.5 unit test: auto-assign audio visuals at add-to-queue time.

Drives ``MainWindow._auto_assign_audio_visuals_for_new`` through every
branch without instantiating the full MainWindow (which would block on
single-instance handshake + startup update poll). Binds the method
directly to a lightweight stub that mimics the attributes the method
reads.
"""
import os, sys, tempfile, types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import (
    QApplication, QListWidgetItem, QListWidget, QCheckBox, QComboBox)
from PyQt6.QtCore import Qt, QSettings

_app = QApplication.instance() or QApplication(sys.argv)

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


# Pull the two methods + dependencies out of MainWindow.
from app.main_window import MainWindow

# Lightweight stub with just what _auto_assign_audio_visuals_for_new
# and _has_audio_template_active touch.
class StubMW:
    def __init__(self):
        self.audio_template_combo = QComboBox()
        # Mirror the real template list.
        from engine import audio_template_choices
        for key, name in audio_template_choices():
            self.audio_template_combo.addItem(name, userData=key)
        self.audio_template_combo.setCurrentIndex(0)  # "none"

        self.profile_visuals_enabled = QCheckBox()
        self.profile_visuals_list = QListWidget()

        # Isolated INI-format settings so we don't pollute user prefs.
        tmpdir = Path(tempfile.mkdtemp(prefix="veloxa_settings_"))
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,
                          QSettings.Scope.UserScope, str(tmpdir))
        self.settings = QSettings("Veloxa-VD-Test", "V10-AutoAssign")

        # No ffprobe in this harness -- durations resolve to 0.0.
        self.ffprobe = None

    # The method needs these helpers. Re-bind from MainWindow.
    _has_audio_template_active = MainWindow._has_audio_template_active
    _auto_assign_audio_visuals_for_new = (
        MainWindow._auto_assign_audio_visuals_for_new)
    _pv_get_counter = MainWindow._pv_get_counter
    _pv_set_counter = MainWindow._pv_set_counter
    _pv_counter_key = MainWindow._pv_counter_key
    _pv_refresh_status = lambda self: None  # no-op (no pv_status_lbl)


mw = StubMW()


# ---- Fixtures: real files on disk for the existence checks ---------------
fixt = Path(tempfile.mkdtemp(prefix="veloxa_v143_fixtures_"))
visual1 = fixt / "bg1.png"
visual2 = fixt / "bg2.png"
visual3 = fixt / "bg3.png"
for v in (visual1, visual2, visual3):
    v.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)

audio1 = fixt / "song1.mp3"
audio2 = fixt / "song2.mp3"
audio3 = fixt / "song3.mp3"
audio4 = fixt / "song4.mp3"
for a in (audio1, audio2, audio3, audio4):
    a.write_bytes(b"ID3\x04\x00\x00" + b"\0" * 128)


def reset_pv_list(items):
    mw.profile_visuals_list.clear()
    for d in items:
        it = QListWidgetItem(d.get("path", ""))
        it.setData(Qt.ItemDataRole.UserRole, d)
        mw.profile_visuals_list.addItem(it)


def set_template(key: str):
    idx = mw.audio_template_combo.findData(key)
    if idx >= 0:
        mw.audio_template_combo.setCurrentIndex(idx)


print()
print("=" * 72)
print("V14.3.5 -- Auto-assign audio visuals on add")
print("=" * 72)


# ---- 1. Template active -> no-op ------------------------------------------
print()
print("[1] Audio template active -> auto-assign is a no-op")
set_template("spectrum_bars")
mw.profile_visuals_enabled.setChecked(True)
reset_pv_list([{"path": str(visual1), "kind": "image"},
               {"path": str(visual2), "kind": "image"}])
out = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2)], "TestProfile1")
check("Template set: returns empty dict",
      out == {})


# ---- 2. Checkbox OFF -> no-op ---------------------------------------------
print()
print("[2] Rotation checkbox OFF -> auto-assign is a no-op")
set_template("none")
mw.profile_visuals_enabled.setChecked(False)
reset_pv_list([{"path": str(visual1), "kind": "image"}])
out = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2)], "TestProfile2")
check("Checkbox OFF: returns empty dict",
      out == {})


# ---- 3. Empty list -> no-op -----------------------------------------------
print()
print("[3] Empty Profile Visuals list -> auto-assign is a no-op")
set_template("none")
mw.profile_visuals_enabled.setChecked(True)
reset_pv_list([])
out = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2)], "TestProfile3")
check("Empty list: returns empty dict",
      out == {})


# ---- 4. No audio paths -> no-op -------------------------------------------
print()
print("[4] No audio paths -> auto-assign is a no-op")
mw.profile_visuals_enabled.setChecked(True)
reset_pv_list([{"path": str(visual1), "kind": "image"}])
out = mw._auto_assign_audio_visuals_for_new([], "TestProfile4")
check("No audio paths: returns empty dict",
      out == {})


# ---- 5. HAPPY PATH: rotation actually round-robins ------------------------
print()
print("[5] Happy path: rotation round-robins through the list")
set_template("none")
mw.profile_visuals_enabled.setChecked(True)
reset_pv_list([
    {"path": str(visual1), "kind": "image"},
    {"path": str(visual2), "kind": "image"},
    {"path": str(visual3), "kind": "image"},
])
mw._pv_set_counter("TestProfile5", 0)
out = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2), str(audio3), str(audio4)],
    "TestProfile5")
check("Happy: all 4 audio files get assignments",
      len(out) == 4)
check("Happy: song1 -> visual1",
      out[str(audio1)][0] == str(visual1))
check("Happy: song2 -> visual2",
      out[str(audio2)][0] == str(visual2))
check("Happy: song3 -> visual3",
      out[str(audio3)][0] == str(visual3))
check("Happy: song4 -> visual1 (wrap-around)",
      out[str(audio4)][0] == str(visual1))
check("Happy: counter advanced to 4 (persisted)",
      mw._pv_get_counter("TestProfile5") == 4)
check("Happy: visual_kind preserved per row",
      all(v[1] == "image" for v in out.values()))


# ---- 6. Rotation continues across calls ----------------------------------
print()
print("[6] Counter persists: next call picks up where the last left off")
out2 = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2)], "TestProfile5")
check("Continued: first new -> visual2 (4 % 3 = 1)",
      out2[str(audio1)][0] == str(visual2))
check("Continued: second new -> visual3 (5 % 3 = 2)",
      out2[str(audio2)][0] == str(visual3))
check("Continued: counter now 6",
      mw._pv_get_counter("TestProfile5") == 6)


# ---- 7. Unusable visuals (missing files) are filtered out ----------------
print()
print("[7] Visuals with missing files are skipped")
set_template("none")
mw.profile_visuals_enabled.setChecked(True)
reset_pv_list([
    {"path": str(visual1), "kind": "image"},
    {"path": "/this/does/not/exist.png", "kind": "image"},
    {"path": str(visual2), "kind": "image"},
])
mw._pv_set_counter("TestProfile7", 0)
out = mw._auto_assign_audio_visuals_for_new(
    [str(audio1), str(audio2), str(audio3)], "TestProfile7")
check("Missing filtered: 3 audio rows get visuals",
      len(out) == 3)
check("Missing filtered: visual1 first",
      out[str(audio1)][0] == str(visual1))
check("Missing filtered: visual2 second (skipped the bogus entry)",
      out[str(audio2)][0] == str(visual2))
check("Missing filtered: visual1 third (2-item list wraps)",
      out[str(audio3)][0] == str(visual1))


# ---- 8. _build_jobs rotation does NOT double-advance ----------------------
print()
print("[8] _build_jobs skips rotation when row already has a visual")
import inspect
src = inspect.getsource(MainWindow._build_jobs)
check("_build_jobs has 'already_has_visual' guard",
      "already_has_visual" in src
      and "not already_has_visual" in src)


# ---- 9. _has_audio_template_active introspection -------------------------
print()
print("[9] _has_audio_template_active reflects combo state")
set_template("none")
check("Template 'none' -> False",
      mw._has_audio_template_active() is False)
set_template("waveform")
check("Template 'waveform' -> True",
      mw._has_audio_template_active() is True)
set_template("none")


# ---- 10. Source-level wiring in _add_files --------------------------------
print()
print("[10] _add_files calls auto-assign before legacy prompt path")
mw_src = inspect.getsource(MainWindow._add_files)
check("_add_files calls _auto_assign_audio_visuals_for_new",
      "_auto_assign_audio_visuals_for_new(" in mw_src)
check("_add_files gates legacy prompt on auto-assign result",
      "not per_audio_visual" in mw_src
      and "not self._has_audio_template_active()" in mw_src)
check("_add_files prefers per-row auto-assigned visual",
      "per_audio_visual[p]" in mw_src)


print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All auto-assign-visuals checks PASS.")
sys.exit(0)
