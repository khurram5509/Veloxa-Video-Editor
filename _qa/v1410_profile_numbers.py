"""V14.10.0: sticky profile shortcut numbers + digit-key assignment.

Covers: migration numbering, label round-trip, swap-on-conflict,
number preservation across profile updates, numbered combo display
with raw-name API semantics, and the live digit-buffer that assigns a
profile to selected queue rows. Runs against the real MainWindow
offscreen; the user's profile store and queue state are snapshotted
and restored exactly.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

_app = QApplication.instance() or QApplication(sys.argv)

from app.main_window import MainWindow, ProfileCombo, NO_PROFILE
from app.persistence import queue_state_path, clear_queue_state

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f": {detail}" if detail and not ok else ""))


print()
print("=" * 72)
print("V14.10.0 -- sticky profile numbers + digit shortcuts")
print("=" * 72)

mw = MainWindow(app_icon=QIcon(), log_file_path=ROOT / "veloxa.log")

profiles_before = copy.deepcopy(mw.profiles)
last_profile_before = mw.settings.value("last_profile", NO_PROFILE)
# Queue persistence is a JSON FILE (persistence.queue_state_path), NOT a
# QSettings key. Snapshot it -- our _add_files below overwrites it, and
# a leaked file makes every later MainWindow() pop the modal "Resume
# previous batch?" dialog, which hangs offscreen test runs forever.
_qpath = queue_state_path()
_qbackup = _qpath.read_text(encoding="utf-8") if _qpath.exists() else None

try:
    # Fresh, controlled profile set: no numbers at all -> migration.
    mw.profiles.clear()
    for nm in ("Bravo", "alpha", "Charlie"):
        mw.profiles[nm] = {"trim_start": 0.0}
    print()
    print("[1] Migration assigns 1..N alphabetically")
    changed = mw._ensure_profile_numbers()
    check("migration reports changes", changed)
    check("alpha -> 1", mw._profile_number("alpha") == 1)
    check("Bravo -> 2", mw._profile_number("Bravo") == 2)
    check("Charlie -> 3", mw._profile_number("Charlie") == 3)
    check("second pass is a no-op", not mw._ensure_profile_numbers())
    dup = dict(mw.profiles["Charlie"])
    dup["shortcut_number"] = 1          # collide with alpha
    mw.profiles["Delta"] = dup
    mw._ensure_profile_numbers()
    check("colliding import-style number gets reassigned (Delta -> 4)",
          mw._profile_number("Delta") == 4)

    print()
    print("[2] Label round-trip")
    check("label is 'N. Name'", mw._profile_label("alpha") == "1. alpha")
    check("label parses back to raw name",
          mw._profile_name_from_label("1. alpha") == "alpha")
    check("NO_PROFILE label untouched",
          mw._profile_label(NO_PROFILE) == NO_PROFILE)
    mw.profiles["7. Trap"] = {"shortcut_number": 9}
    check("literal name '7. Trap' wins exact match",
          mw._profile_name_from_label("7. Trap") == "7. Trap")
    del mw.profiles["7. Trap"]

    print()
    print("[3] Set-number swaps on conflict")
    mw._set_profile_number("Charlie", 1)         # alpha holds 1
    check("Charlie takes 1", mw._profile_number("Charlie") == 1)
    check("alpha received Charlie's old 3", mw._profile_number("alpha") == 3)
    mw._set_profile_number("Charlie", 42)        # free number, no swap
    check("free number assigns directly",
          mw._profile_number("Charlie") == 42)
    check("no one else changed", mw._profile_number("alpha") == 3
          and mw._profile_number("Bravo") == 2)

    print()
    print("[4] _store_profile preserves the number on update")
    mw._store_profile("Bravo", {"trim_start": 5.0})
    check("updated dict kept number 2",
          mw._profile_number("Bravo") == 2)
    check("updated dict kept new content",
          mw.profiles["Bravo"]["trim_start"] == 5.0)

    print()
    print("[5] Numbered combos keep raw-name API semantics")
    mw._refresh_profile_combo()
    texts = [mw.profile_combo.itemText(i)
             for i in range(mw.profile_combo.count())]
    check("combo displays numbered labels", "2. Bravo" in texts,
          f"texts={texts}")
    idx = mw.profile_combo.findText("Bravo")
    check("findText matches RAW name", idx >= 0)
    mw.profile_combo.blockSignals(True)
    mw.profile_combo.setCurrentIndex(idx)
    mw.profile_combo.blockSignals(False)
    check("currentText returns RAW name",
          mw.profile_combo.currentText() == "Bravo",
          f"got {mw.profile_combo.currentText()!r}")
    check("per-row combo class is ProfileCombo (source wiring)",
          "pc = ProfileCombo()" in
          (ROOT / "app" / "main_window.py").read_text(encoding="utf-8"))

    print()
    print("[6] Digit shortcut assigns profile to selected rows")
    tmp = Path(tempfile.mkdtemp(prefix="veloxa_v1410_"))
    f1 = tmp / "a.mp4"; f1.write_bytes(b"\0" * 16)
    f2 = tmp / "b.mp4"; f2.write_bytes(b"\0" * 16)
    mw.file_list.clear()
    mw._add_files([str(f1), str(f2)])
    check("2 rows queued", mw.file_list.count() == 2)
    mw.file_list.selectAll()
    # 'Charlie' holds 42: type '4' -> extendable (42 matches prefix),
    # buffer must WAIT, not apply.
    mw._on_profile_digit("4")
    check("'4' buffers because 42 could follow",
          mw._digit_buffer == "4" and mw._digit_timer.isActive())
    mw._on_profile_digit("2")
    # '42' is not a prefix of any other number -> applies immediately.
    check("'42' applied instantly (buffer cleared)",
          mw._digit_buffer == "")
    d0 = mw._item_data(mw.file_list.item(0))
    d1 = mw._item_data(mw.file_list.item(1))
    check("both rows now use Charlie (#42)",
          d0.profile_name == "Charlie" and d1.profile_name == "Charlie",
          f"got {d0.profile_name!r}, {d1.profile_name!r}")
    # Single digit with no larger candidate: 3 -> alpha, instant.
    mw._on_profile_digit("3")
    d0 = mw._item_data(mw.file_list.item(0))
    check("'3' applied instantly to alpha",
          d0.profile_name == "alpha", f"got {d0.profile_name!r}")
    # Unknown number: buffer for '9' has no profile.
    mw._on_profile_digit("9")
    check("unknown number leaves rows untouched",
          mw._item_data(mw.file_list.item(0)).profile_name == "alpha")

    print()
    print("[7] Dialog + storage wiring (source level)")
    d_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")
    check("Profile Manager has Set Number button",
          "Set Number..." in d_src and "_set_number_selected" in d_src)
    check("Duplicate drops the copied number",
          'dup.pop("shortcut_number", None)' in d_src)
    check("Import strips numbers that would steal an existing one",
          '_profile_by_number(n)' in d_src)
    check("Manager list stores raw name in UserRole",
          "it.setData(Qt.ItemDataRole.UserRole, name)" in d_src)

finally:
    # Restore the user's real state exactly.
    mw.profiles.clear()
    mw.profiles.update(profiles_before)
    mw._save_profiles()
    mw._refresh_profile_combo()
    mw.file_list.clear()
    if _qbackup is None:
        clear_queue_state()
    else:
        _qpath.write_text(_qbackup, encoding="utf-8")
    mw.settings.setValue("last_profile", last_profile_before)
    mw.deleteLater()

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.10.0 profile-number checks PASS.")
sys.exit(0)
