"""V14.11.4 low-resource hardening:

  #1  Queue-state / draft persistence is COALESCED during a batch. The
      per-file callbacks mark dirty and flush at most ~once/1.5s instead
      of writing the whole queue to disk on every file start + finish.
      Interactive edits stay immediate; batch-end + close force a flush.
  #2  Preview generation is capped to ONE FFmpeg in flight; rapid changes
      on a slow CPU coalesce into a single re-render of the latest state
      instead of a pile of competing preview processes.

Runs against the real MainWindow, fully sandboxed (APPDATA + settings).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SB = Path(tempfile.mkdtemp(prefix="veloxa_v1414_"))
os.environ["APPDATA"] = str(_SB)
os.environ["VELOXA_SETTINGS_FILE"] = str(_SB / "settings.ini")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

_app = QApplication.instance() or QApplication(sys.argv)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

import app.main_window as mwmod
from app.main_window import MainWindow

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail and not ok else ""))

print()
print("=" * 72)
print("V14.11.4 -- low-resource hardening")
print("=" * 72)

mw = MainWindow(app_icon=QIcon(), log_file_path=ROOT / "veloxa.log")

try:
    print()
    print("[1] Persistence is coalesced, not written on every mark")
    writes = {"n": 0}
    _orig_save = mwmod.save_queue_state
    mwmod.save_queue_state = lambda items: writes.__setitem__("n", writes["n"] + 1)

    # Simulate a 200-file batch storming the per-file callback.
    writes["n"] = 0
    for _ in range(200):
        mw._schedule_persist()
    check("200 rapid schedule calls write 0 times immediately",
          writes["n"] == 0, f"got {writes['n']}")
    check("a flush is armed + marked dirty",
          mw._persist_timer.isActive() and mw._persist_pending)

    mw._flush_persist()
    check("flush writes exactly once", writes["n"] == 1, f"got {writes['n']}")
    check("flush clears dirty + stops the timer",
          not mw._persist_pending and not mw._persist_timer.isActive())

    mw._flush_persist()
    check("second flush with nothing pending is a no-op",
          writes["n"] == 1, f"got {writes['n']}")

    # Timer firing (the debounce elapsing) flushes once.
    mw._schedule_persist(); mw._schedule_persist()
    mw._persist_timer.timeout.emit()      # simulate the 1.5s elapsing
    check("timer firing flushes exactly once for a burst",
          writes["n"] == 2, f"got {writes['n']}")

    # Write-amplification win, quantified: 200 file events -> 1 flush.
    writes["n"] = 0
    for _ in range(200):
        mw._schedule_persist()
    mw._flush_persist()
    check("200 file events collapse to 1 disk write (was 200)",
          writes["n"] == 1, f"got {writes['n']}")
    mwmod.save_queue_state = _orig_save

    print()
    print("[2] Batch/close paths force an authoritative flush (source)")
    src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
    fin = src.split("def _on_batch_finished")[1].split("\n    def ")[0]
    check("batch-end stops the timer + clears pending",
          "self._persist_timer.stop()" in fin and
          "self._persist_pending = False" in fin)
    check("batch-end does a synchronous final _save_queue_state",
          "self._save_queue_state()" in fin)
    close = src.split("def closeEvent")[1].split("\n    def ")[0]
    check("closeEvent flushes before exit", "_flush_persist()" in close)
    started = src.split("def _on_file_started")[1].split("\n    def ")[0]
    finished = src.split("def _on_file_finished")[1].split("\n    def ")[0]
    check("per-file start uses coalesced persist (not direct save)",
          "_schedule_persist()" in started and
          "_save_queue_state()" not in started)
    check("per-file finish uses coalesced persist (not direct save)",
          "_schedule_persist()" in finished and
          "_save_queue_state()" not in finished)

    print()
    print("[3] Preview generation is capped to ONE FFmpeg in flight")
    # Fake PreviewWorker: counts spawns, never touches FFmpeg.
    spawned = {"n": 0}
    class _FakeSig:
        def connect(self, *_a, **_k): pass
    class _FakeWorker:
        def __init__(self, **kw): spawned["n"] += 1
        finished_with_path = _FakeSig()
        def start(self): pass
    mwmod.PreviewWorker = _FakeWorker

    tmp = Path(tempfile.mkdtemp(prefix="veloxa_src_"))
    clip = tmp / "clip.mp4"; clip.write_bytes(b"\0" * 64)
    mw.ffmpeg = mw.ffmpeg or "ffmpeg"   # any truthy path; worker is faked
    mw.file_list.clear()
    mw._add_files([str(clip)])
    mw.file_list.setCurrentRow(0)

    mw._preview_workers.clear(); mw._preview_pending = False
    spawned["n"] = 0
    mw._refresh_preview()
    check("first preview spawns exactly one worker",
          spawned["n"] == 1 and len(mw._preview_workers) == 1,
          f"spawned={spawned['n']} workers={len(mw._preview_workers)}")

    # A worker is in flight; rapid changes must NOT spawn more.
    for _ in range(10):
        mw._refresh_preview()
    check("10 changes while one is in flight spawn 0 more",
          spawned["n"] == 1, f"got {spawned['n']}")
    check("the latest change is remembered as pending",
          mw._preview_pending is True)

    # The running worker finishes -> exactly one coalesced re-render.
    mw._preview_workers.clear()          # emulate the worker exiting
    mw._on_preview_done("x", False, 0)   # sender() is None outside a signal
    check("finishing the in-flight worker triggers 1 re-render",
          spawned["n"] == 2, f"got {spawned['n']}")
    check("pending flag cleared after the coalesced re-render",
          mw._preview_pending is False)

    # No further pending -> a finish does not loop.
    mw._preview_workers.clear()
    mw._on_preview_done("x", False, 0)
    check("no spurious re-render when nothing is pending",
          spawned["n"] == 2, f"got {spawned['n']}")

finally:
    mw.deleteLater()
    import shutil
    shutil.rmtree(_SB, ignore_errors=True)

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.11.4 low-resource checks PASS.")
sys.exit(0)
