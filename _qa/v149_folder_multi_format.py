"""V14.9.0 unit tests: multi-format picker in Add-from-Folder.

Focus is on the deletion behaviour (irreversible + nuclear scope)
because that's the risky new code path. Also verifies the dialog
wiring, the source-level integration into ``_on_add_folder_clicked``,
and that per-file failures don't kill the sweep.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget
_app = QApplication.instance() or QApplication(sys.argv)

from app.main_window import MainWindow

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


# ---- Stub MainWindow so we can bind the two new methods without
#      constructing the whole window (which blocks on single-instance).
# _delete_non_chosen_from_folder passes ``self`` to QMessageBox(self),
# which requires a QWidget -- so the stub inherits QWidget.
class _StubMW(QWidget):
    def __init__(self):
        super().__init__()
        # The delete helper writes to self.status_lbl; a stub with a
        # single setText method is enough.
        class _Lbl:
            def setText(self, *a, **kw): pass
        self.status_lbl = _Lbl()

_prompt = MainWindow._prompt_folder_format_picker
_delete = MainWindow._delete_non_chosen_from_folder


print()
print("=" * 72)
print("V14.9.0 -- Add-from-Folder multi-format picker")
print("=" * 72)


# ---- 1. Enumerate-only path (user hits Cancel on confirm) ---------------
# Auto-answer the QMessageBox with the Cancel button by patching exec.
print()
print("[1] User cancels confirm -> NOTHING is deleted, files intact")
fixt1 = Path(tempfile.mkdtemp(prefix="veloxa_v149_"))
(fixt1 / "keep.mp4").write_bytes(b"\0" * 8)
(fixt1 / "drop.mkv").write_bytes(b"\0" * 8)
(fixt1 / "notes.txt").write_bytes(b"\0" * 8)

import unittest.mock as mock
stub = _StubMW()
with mock.patch.object(QMessageBox, "exec", return_value=0), \
     mock.patch.object(QMessageBox, "clickedButton",
                       return_value=object()):
    # clickedButton returns SOMETHING that isn't del_btn (we didn't
    # patch addButton, so it's a real QPushButton but not the one the
    # method captured). The method treats "anything other than del_btn"
    # as Cancel.
    ok, n = _delete(stub, str(fixt1), {".mp4"})
check("Cancel path returns (False, 0)",
      ok is False and n == 0)
check("Cancel path leaves keep.mp4 intact",
      (fixt1 / "keep.mp4").exists())
check("Cancel path leaves drop.mkv intact (not deleted)",
      (fixt1 / "drop.mkv").exists())
check("Cancel path leaves notes.txt intact",
      (fixt1 / "notes.txt").exists())


# ---- 2. Actual deletion (patch confirm to click the delete button) ------
print()
print("[2] Confirm-delete path -> non-chosen files permanently removed")
fixt2 = Path(tempfile.mkdtemp(prefix="veloxa_v149_"))
(fixt2 / "keep.mp4").write_bytes(b"\0" * 8)
(fixt2 / "keep2.MP4").write_bytes(b"\0" * 8)     # case-insensitive
(fixt2 / "drop.mkv").write_bytes(b"\0" * 8)
(fixt2 / "artwork.jpg").write_bytes(b"\0" * 8)   # NUCLEAR scope
(fixt2 / "subs.srt").write_bytes(b"\0" * 8)      # NUCLEAR scope
nested = fixt2 / "extras"
nested.mkdir()
(nested / "sting.mov").write_bytes(b"\0" * 8)
(nested / "kept.mp4").write_bytes(b"\0" * 8)

# Patch QMessageBox.exec to be a no-op AND patch clickedButton to
# return the "delete" button. We inspect addButton to grab the ref.
class _ClickTracker:
    def __init__(self): self.del_btn = None
tracker = _ClickTracker()
_orig_add = QMessageBox.addButton
def _spy_add(self, *args, **kwargs):
    btn = _orig_add(self, *args, **kwargs)
    # First DestructiveRole button = the delete one.
    if (args and len(args) >= 2
            and args[1] == QMessageBox.ButtonRole.DestructiveRole):
        tracker.del_btn = btn
    return btn
with mock.patch.object(QMessageBox, "exec", return_value=0), \
     mock.patch.object(QMessageBox, "addButton", _spy_add), \
     mock.patch.object(QMessageBox, "clickedButton",
                       lambda self: tracker.del_btn):
    ok, n = _delete(stub, str(fixt2), {".mp4"})
check("Delete path returns (True, 4) -- dropped 4 non-mp4 files",
      ok is True and n == 4, f"got ({ok}, {n})")
check("Delete path removed drop.mkv",
      not (fixt2 / "drop.mkv").exists())
check("Delete path removed artwork.jpg (nuclear scope)",
      not (fixt2 / "artwork.jpg").exists())
check("Delete path removed subs.srt (nuclear scope)",
      not (fixt2 / "subs.srt").exists())
check("Delete path removed extras/sting.mov (subfolder)",
      not (nested / "sting.mov").exists())
check("Delete path KEPT keep.mp4",
      (fixt2 / "keep.mp4").exists())
check("Delete path KEPT keep2.MP4 (case-insensitive match)",
      (fixt2 / "keep2.MP4").exists())
check("Delete path KEPT extras/kept.mp4 (nested chosen)",
      (nested / "kept.mp4").exists())


# ---- 3. Empty doomed list = short-circuit ---------------------------------
print()
print("[3] Folder with only the chosen formats -> confirm is skipped")
fixt3 = Path(tempfile.mkdtemp(prefix="veloxa_v149_"))
(fixt3 / "a.mp4").write_bytes(b"\0")
(fixt3 / "b.mp4").write_bytes(b"\0")
# No confirm patch -- the method should never call exec.
with mock.patch.object(QMessageBox, "exec",
                       side_effect=AssertionError(
                           "exec should NOT fire on empty doomed list")):
    ok, n = _delete(stub, str(fixt3), {".mp4"})
check("Empty doomed list returns (True, 0)",
      ok is True and n == 0)
check("Both a.mp4 and b.mp4 still exist",
      (fixt3 / "a.mp4").exists() and (fixt3 / "b.mp4").exists())


# ---- 4. Source-level wiring in _on_add_folder_clicked --------------------
print()
print("[4] Add-from-Folder now consults the format picker")
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_h_src = mw_src.split("def _on_add_folder_clicked")[1].split("def ")[0]
check("_on_add_folder_clicked calls _prompt_folder_format_picker",
      "_prompt_folder_format_picker(" in _h_src)
check("_on_add_folder_clicked calls _delete_non_chosen_from_folder "
      "when delete_others is True",
      "_delete_non_chosen_from_folder(" in _h_src)
check("Picker only fires when > 1 unique extension is present",
      "len(unique_exts) > 1" in _h_src)
check("Cancelled picker (chosen is None) short-circuits without import",
      "chosen is None" in _h_src)
check("Empty-tick set (nothing chosen) short-circuits without import",
      "not chosen" in _h_src)

# The dialog itself:
_p_src = mw_src.split(
    "def _prompt_folder_format_picker")[1].split("def ")[0]
check("Picker uses QDialog, not just a QMessageBox",
      "QDialog(self)" in _p_src)
check("Picker builds one checkbox per unique extension",
      "QCheckBox(f\"{ext}" in _p_src or "for ext in unique_exts" in _p_src)
check("Picker exposes 'PERMANENTLY DELETE' warning language",
      "PERMANENTLY DELETE" in _p_src)
check("Picker returns (None, False) on Cancel",
      "return None, False" in _p_src)

# The deletion helper:
_d_src = mw_src.split(
    "def _delete_non_chosen_from_folder")[1].split("def ")[0]
check("Delete helper uses os.remove (permanent, not Recycle Bin)",
      "os.remove(" in _d_src)
check("Delete helper catches per-file OSError",
      "except OSError" in _d_src)
check("Delete helper walks with followlinks=False",
      "followlinks=False" in _d_src)
check("Delete helper's confirm has DestructiveRole button",
      "DestructiveRole" in _d_src)
check("Delete helper's default is Cancel (safer)",
      "setDefaultButton(cancel_btn)" in _d_src)
check("Delete helper shows a sample of up to 5 doomed paths",
      "doomed[:5]" in _d_src)


print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.9.0 folder-picker checks PASS.")
sys.exit(0)
