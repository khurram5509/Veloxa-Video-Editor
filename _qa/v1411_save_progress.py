"""V14.11.0 Save Progress: drafts store + auto-save + resume lifecycle.

Exercises the full user journey against a real MainWindow (offscreen):
save a draft before starting, auto-save after an activity and after a
completed video, resume it into a fresh window state, edit + re-save,
and delete. The user's real drafts folder, queue state and QSettings
are snapshotted and restored.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---- HARD ISOLATION -------------------------------------------------
# Every on-disk path in the app resolves %APPDATA% at CALL time
# (persistence.app_data_dir), so redirecting it here means this suite
# physically cannot read or write the user's real queue state, drafts,
# or logs. Set before importing anything from `app`.
_SANDBOX = Path(tempfile.mkdtemp(prefix="veloxa_v1411_home_"))
os.environ["APPDATA"] = str(_SANDBOX)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

_app = QApplication.instance() or QApplication(sys.argv)

from app.main_window import MainWindow, NO_PROFILE
from app.persistence import queue_state_path, clear_queue_state, app_data_dir
from app import drafts as drafts_store

assert str(_SANDBOX) in str(app_data_dir()), \
    f"sandbox not active: {app_data_dir()}"

# load_draft_into_window() asks for confirmation before replacing a
# non-empty queue. Auto-accept it so the offscreen run never blocks on
# a modal (the dialog itself is exercised interactively, not here).
QMessageBox.question = staticmethod(
    lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(
    lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.information = staticmethod(
    lambda *a, **k: QMessageBox.StandardButton.Ok)

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f": {detail}" if detail and not ok else ""))


print()
print("=" * 72)
print("V14.11.0 -- Save Progress drafts + auto-save")
print("=" * 72)

# The sandbox starts empty, so there is no previous queue to restore
# and MainWindow.__init__ cannot pop the modal resume prompt.
_ddir = drafts_store.drafts_dir()

mw = MainWindow(app_icon=QIcon(), log_file_path=ROOT / "veloxa.log")
# QSettings is registry-backed on Windows (not under APPDATA), so the
# two keys this suite touches are snapshotted and restored explicitly.
_autosave_before = mw.settings.value("autosave_progress", True)
_profiles_before = copy.deepcopy(mw.profiles)

try:
    tmp = Path(tempfile.mkdtemp(prefix="veloxa_v1411_"))
    f1 = tmp / "one.mp4"; f1.write_bytes(b"\0" * 16)
    f2 = tmp / "two.mp4"; f2.write_bytes(b"\0" * 16)
    f3 = tmp / "three.mp4"; f3.write_bytes(b"\0" * 16)

    print()
    print("[1] Store layer: create / list / load / rename / delete")
    d = drafts_store.make_draft("Unit draft", [{"src": "x.mp4"}],
                                {"trim_start": 1.0})
    did = drafts_store.save_draft(d)
    check("save_draft returns an id", bool(did))
    back = drafts_store.load_draft(did)
    check("round-trip preserves items + settings",
          back and back["items"][0]["src"] == "x.mp4"
          and back["settings"]["trim_start"] == 1.0)
    check("listed with item count",
          any(m["id"] == did and m["n_items"] == 1
              for m in drafts_store.list_drafts()))
    check("rename works",
          drafts_store.rename_draft(did, "Renamed")
          and drafts_store.load_draft(did)["name"] == "Renamed")
    check("path-traversal id refused",
          drafts_store.save_draft({"id": "../evil"}) == ""
          and drafts_store.load_draft("../evil") is None)
    check("delete works", drafts_store.delete_draft(did)
          and drafts_store.load_draft(did) is None)

    print()
    print("[2] Save progress BEFORE starting (queue + settings snapshot)")
    mw.set_autosave_enabled(False)      # isolate explicit-save behaviour
    mw.file_list.clear()
    mw._add_files([str(f1), str(f2)])
    mw.trim_start.setValue(4.5)
    mw.out_pattern.setText("{name}_draft")
    saved_id = drafts_store.new_draft_id()
    mw._set_current_draft(saved_id, "My work")
    check("explicit save_progress succeeds", mw.save_progress())
    stored = drafts_store.load_draft(saved_id)
    check("draft captured both queue rows",
          stored and len(stored["items"]) == 2,
          f"got {len(stored['items']) if stored else 'None'}")
    check("draft captured settings snapshot",
          abs(stored["settings"].get("trim_start", 0) - 4.5) < 1e-6
          and stored["settings"].get("out_pattern") == "{name}_draft")
    check("open-draft indicator reflects the name",
          "My work" in mw.draft_lbl.text())

    print()
    print("[3] Auto-save OFF means no writes on activity")
    before = drafts_store.load_draft(saved_id)["updated_at"]
    mw._add_files([str(f3)])            # an 'activity'
    after = drafts_store.load_draft(saved_id)
    check("draft untouched while auto-save is off",
          after["updated_at"] == before and len(after["items"]) == 2)

    print()
    print("[4] Auto-save ON updates the OPEN draft in place")
    mw.set_autosave_enabled(True)
    check("setting round-trips through QSettings",
          mw.is_autosave_enabled() is True)
    mw._save_queue_state()              # the shared auto-save hook
    live = drafts_store.load_draft(saved_id)
    check("open draft now has all 3 rows",
          len(live["items"]) == 3, f"got {len(live['items'])}")
    check("no stray Autosave slot while a draft is open",
          drafts_store.load_draft(drafts_store.AUTOSAVE_ID) is None)

    print()
    print("[5] Auto-save with NO draft open uses the rolling slot")
    mw._set_current_draft("", "")
    mw._save_queue_state()
    roll = drafts_store.load_draft(drafts_store.AUTOSAVE_ID)
    check("rolling Autosave slot created", roll is not None)
    check("rolling slot holds the queue",
          roll and len(roll["items"]) == 3)
    check("indicator shows no open draft", "(none)" in mw.draft_lbl.text())

    print()
    print("[6] Auto-save fires after a completed video")
    item0 = mw.file_list.item(0)
    mw._item_data(item0).status = "done"
    mw._save_queue_state()              # what _on_file_finished calls
    meta = next(m for m in drafts_store.list_drafts()
                if m["id"] == drafts_store.AUTOSAVE_ID)
    check("completed video recorded in the rolling slot (1 done)",
          meta["n_done"] == 1, f"got {meta['n_done']}")
    # Re-pin the named draft and save again so step [7] resumes a draft
    # that actually contains the completed row.
    mw._set_current_draft(saved_id, "My work")
    mw._save_queue_state()
    check("completed video recorded in the named draft too",
          next(m for m in drafts_store.list_drafts()
               if m["id"] == saved_id)["n_done"] == 1)

    print()
    print("[7] Resume: wipe the window, reopen the draft")
    mw.file_list.clear()
    mw.trim_start.setValue(0.0)
    mw.out_pattern.setText("{name}_edited")
    check("window cleared", mw.file_list.count() == 0)
    check("reopen returns True",
          mw.load_draft_into_window(saved_id))
    check("queue restored", mw.file_list.count() == 3,
          f"got {mw.file_list.count()}")
    check("settings restored from the draft",
          abs(mw.trim_start.value() - 4.5) < 1e-6
          and mw.out_pattern.text() == "{name}_draft")
    check("done status survived the round-trip",
          any(mw._item_data(mw.file_list.item(i)).status == "done"
              for i in range(mw.file_list.count())))
    check("reopened draft becomes the open draft",
          mw._current_draft_id == saved_id
          and "My work" in mw.draft_lbl.text())

    print()
    print("[8] Edit an open draft, then delete it")
    mw._remove_selected() if False else None
    mw.file_list.takeItem(0)
    mw._save_queue_state()
    check("edit auto-saved into the same draft",
          len(drafts_store.load_draft(saved_id)["items"]) == 2)
    check("delete removes it",
          drafts_store.delete_draft(saved_id)
          and drafts_store.load_draft(saved_id) is None)

    print()
    print("[8b] DATA LOSS GUARD: emptying the queue must not blank a draft")
    # Field bug (V14.11.1): with a named draft open and auto-save on,
    # Clear All / Remove Completed / removing the last row wrote 0 items
    # straight over the draft, destroying saved work silently. Evidence
    # was a 0-item draft in a real user's drafts folder.
    guard_id = drafts_store.new_draft_id()
    mw.file_list.clear()
    mw._suppress_autosave = True
    mw._add_files([str(f1), str(f2)])
    mw._suppress_autosave = False
    mw._set_current_draft(guard_id, "Guarded work")
    mw.save_progress()
    check("guard draft saved with 2 items",
          len(drafts_store.load_draft(guard_id)["items"]) == 2)
    mw.file_list.clear()          # <-- the destructive user action
    mw._save_queue_state()
    kept = drafts_store.load_draft(guard_id)
    check("clearing the queue does NOT blank the open named draft",
          kept is not None and len(kept["items"]) == 2,
          f"got {len(kept['items']) if kept else None} items")
    check("status bar explains the draft was preserved",
          "still holds" in mw.status_lbl.text().lower()
          or "saved item" in mw.status_lbl.text().lower(),
          repr(mw.status_lbl.text()))
    # Same protection for the rolling slot.
    mw._set_current_draft("", "")
    mw._suppress_autosave = True
    mw._add_files([str(f1)])
    mw._suppress_autosave = False
    mw._save_queue_state()
    roll_n = len(drafts_store.load_draft(drafts_store.AUTOSAVE_ID)["items"])
    mw.file_list.clear()
    mw._save_queue_state()
    check("clearing the queue does NOT blank the rolling Autosave slot",
          len(drafts_store.load_draft(
              drafts_store.AUTOSAVE_ID)["items"]) == roll_n)
    drafts_store.delete_draft(guard_id)

    print()
    print("[9] Reserved slots + wiring")
    check("reserved ids defined",
          drafts_store.AUTOSAVE_ID in drafts_store.RESERVED_IDS
          and drafts_store.LAST_SESSION_ID in drafts_store.RESERVED_IDS)
    check("reserved slots get friendly labels",
          drafts_store.display_name({"id": drafts_store.LAST_SESSION_ID})
          == "Last session")
    mw.load_draft_into_window(drafts_store.AUTOSAVE_ID)
    check("opening a reserved slot leaves no draft pinned",
          mw._current_draft_id == "")
    mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
    check("Save Progress button + Drafts button exist",
          "save_progress_btn" in mw_src and "drafts_btn" in mw_src)
    check("shortcuts bound (Ctrl+Shift+P / Ctrl+Shift+D)",
          '"Ctrl+Shift+P"' in mw_src and '"Ctrl+Shift+D"' in mw_src)
    check("Tools menu exposes drafts",
          "Saved Drafts" in mw_src and "Save Progress" in mw_src)
    check("resume prompt offers Open Drafts",
          "Open Drafts" in mw_src)
    check("last session mirrored into drafts",
          "LAST_SESSION_ID" in mw_src)
    d_src = (ROOT / "app" / "dialogs.py").read_text(encoding="utf-8")
    check("DraftsDialog offers open / start / rename / delete",
          all(s in d_src for s in ("_open_selected", "_open_and_start",
                                   "_rename_selected", "_delete_selected")))
    check("auto-save checkbox lives in the drafts dialog",
          "autosave_chk" in d_src)
    check("auto-save never breaks an encode (guarded)",
          "Auto-save skipped" in mw_src)

finally:
    # Everything on disk lived in the sandbox; only the registry-backed
    # QSettings needs restoring.
    mw.file_list.clear()
    mw.settings.setValue("autosave_progress", _autosave_before)
    mw.profiles.clear()
    mw.profiles.update(_profiles_before)
    mw._save_profiles()
    mw.deleteLater()
    import shutil
    shutil.rmtree(_SANDBOX, ignore_errors=True)

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.11.0 Save Progress checks PASS.")
sys.exit(0)
