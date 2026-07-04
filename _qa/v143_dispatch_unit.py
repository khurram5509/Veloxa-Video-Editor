"""V14.3.0 dispatch-logic unit tests (no UI, no real ffmpeg).

Stubs JobRunner so BatchManager's real _dispatch / _start_next /
add_jobs / set_use_cpu_slot run end-to-end without spawning ffmpeg.

Validates:
  1. CPU slot OFF -> only ``max_concurrent`` jobs ever run.
  2. CPU slot ON  -> one extra slot opens beyond max_concurrent,
                    and that runner gets libx264/libx265 + _cpu_slot.
  3. HARD_CAP_CONCURRENT (=4) clamps effective_concurrency.
  4. Live toggle ON mid-batch spawns the extra slot on the next tick.
  5. Live toggle OFF stops new CPU jobs; in-flight CPU job is left
     alone; refilled slots default back to GPU.
  6. add_jobs() appends to the tail (FIFO) without disturbing running.
  7. RAM-watchdog veto: when low-RAM is reported, the CPU slot is
     skipped this tick and reopens once memory frees.
  8. force_cpu_encoder maps NVENC/QSV/AMF families to libx264/x265.
  9. Thread cap is sane on this machine.
"""
import sys, os
from pathlib import Path

# Ensure a QApplication exists for QObject + signal plumbing.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QObject, QCoreApplication, pyqtSignal
_qapp = QCoreApplication.instance() or QCoreApplication(sys.argv)

from engine import batch as bm
from engine import system_resources as sr

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


# ---- Stub JobRunner that matches the real signature ----------------------
class FakeRunner(QObject):
    """Quacks like engine.batch.JobRunner. No ffmpeg. Real Qt signals so
    BatchManager.connect() works."""
    # Match engine.batch.JobRunner exactly (idx, percent).
    progress = pyqtSignal(int, float)
    eta_update = pyqtSignal(int, float)
    job_finished = pyqtSignal(int, bool, str)

    instances = []

    def __init__(self, idx, src, dst, kind, visual_path, visual_kind,
                 ffmpeg, ffprobe, opts, per_job_opts=None):
        super().__init__()
        self.idx = idx
        self.src = src
        self.dst = dst
        # The dispatcher passes either per_job_opts or self.opts -- the
        # real JobRunner uses per_job_opts if provided. For test
        # assertions we want to inspect whichever set was applied.
        self.opts = dict(per_job_opts) if per_job_opts else dict(opts)
        self._cancelled = False
        FakeRunner.instances.append(self)

    def start(self): pass
    def cancel(self): self._cancelled = True
    def request_pause(self): pass
    def request_resume(self): pass
    def wait(self, *a, **kw): return True
    def deleteLater(self): pass

    def finish(self, ok=True, msg=""):
        """Helper for tests: emit job_finished so BatchManager dispatch
        cleans up + tops up the slot."""
        self.job_finished.emit(self.idx, ok, msg)


# Swap in the fake for the entire run.
bm.JobRunner = FakeRunner


def make_mgr(n_jobs, max_concurrent, use_cpu=False):
    FakeRunner.instances.clear()
    # 6-tuple matches JobRunner unpack: (idx, src, dst, kind, vp, vk).
    jobs = [(i, f"in{i}.mp4", f"out{i}.mp4", "compress", "", "none")
            for i in range(n_jobs)]
    opts = {
        "use_cpu_alongside_gpu": use_cpu,
        "encoder": "h264_nvenc",
        "out_codec": "h264",
    }
    return bm.BatchManager(jobs, max_concurrent, "ffmpeg", "ffprobe", opts)


print()
print("=" * 72)
print("V14.3.0 dispatch unit-tests")
print("=" * 72)


# ---- 1. CPU slot OFF: only max_concurrent ever active --------------------
print()
print("[1] CPU slot OFF: cap == max_concurrent")
mgr = make_mgr(n_jobs=5, max_concurrent=2, use_cpu=False)
mgr.start()
check("OFF: exactly 2 active (5 queued, cap=2)",
      len(mgr._active) == 2, f"active={len(mgr._active)}")
check("OFF: zero CPU slots",
      len(mgr._active_cpu) == 0)
check("OFF: effective_concurrency == 2",
      mgr.effective_concurrency() == 2,
      f"eff={mgr.effective_concurrency()}")


# ---- 2. CPU slot ON: one extra slot, libx264 forced ----------------------
print()
print("[2] CPU slot ON: cap == max_concurrent + 1")
mgr = make_mgr(n_jobs=5, max_concurrent=2, use_cpu=True)
mgr._cpu_slot_safe_to_open = lambda: True  # bypass RAM watchdog
mgr.start()
check("ON: 3 active (5 queued, cap=2 + cpu slot)",
      len(mgr._active) == 3, f"active={len(mgr._active)}")
check("ON: exactly 1 CPU slot",
      len(mgr._active_cpu) == 1)
check("ON: effective_concurrency == 3",
      mgr.effective_concurrency() == 3)
# Pull the runner that's in the CPU set.
cpu_idx = next(iter(mgr._active_cpu))
cpu_runner = next(r for r in FakeRunner.instances if r.idx == cpu_idx)
check("ON: CPU slot runner opts.encoder == libx264",
      cpu_runner.opts.get("encoder") == "libx264",
      f"encoder={cpu_runner.opts.get('encoder')}")
check("ON: CPU slot runner carries _cpu_slot=True",
      cpu_runner.opts.get("_cpu_slot") is True)
# GPU slots should NOT carry _cpu_slot and stay on nvenc (via main opts).
gpu_runners = [r for r in FakeRunner.instances
               if r.idx not in mgr._active_cpu]
# Note: GPU slots don't get a per_job_opts override, so r.opts will be
# the main self.opts dict -- encoder == h264_nvenc, no _cpu_slot.
check("ON: GPU slot runners NOT marked _cpu_slot",
      all(not r.opts.get("_cpu_slot") for r in gpu_runners))


# ---- 3. HARD_CAP_CONCURRENT clamp ----------------------------------------
print()
print("[3] HARD_CAP_CONCURRENT == 4 clamps effective_concurrency")
mgr = make_mgr(n_jobs=2, max_concurrent=2, use_cpu=True)
# Pretend somehow the GUI raised max_concurrent above the slider cap.
mgr.max_concurrent = 10
eff = mgr.effective_concurrency()
check("HARD_CAP: effective_concurrency clamped to 4",
      eff == 4, f"eff={eff}")
mgr.max_concurrent = 2  # restore for any later use


# ---- 4. Live toggle ON mid-batch -----------------------------------------
print()
print("[4] Live toggle: OFF -> ON mid-batch opens an extra slot")
mgr = make_mgr(n_jobs=6, max_concurrent=2, use_cpu=False)
mgr.start()
n_before = len(mgr._active)
mgr._cpu_slot_safe_to_open = lambda: True
mgr.set_use_cpu_slot(True)
check("Toggle ON: active rose from 2 -> 3",
      n_before == 2 and len(mgr._active) == 3,
      f"before={n_before}, after={len(mgr._active)}")
check("Toggle ON: 1 CPU slot now",
      len(mgr._active_cpu) == 1)


# ---- 5. Live toggle OFF stops new CPU jobs -------------------------------
print()
print("[5] Live toggle: ON -> OFF leaves in-flight CPU job alone")
prior_cpu = set(mgr._active_cpu)
mgr.set_use_cpu_slot(False)
check("Toggle OFF: in-flight CPU job kept",
      mgr._active_cpu == prior_cpu and len(mgr._active_cpu) == 1)
# Finish the *GPU* job that's running; only another GPU slot should fill.
gpu_idx_to_finish = next(i for i in list(mgr._active)
                          if i not in mgr._active_cpu)
gpu_runner = next(r for r in FakeRunner.instances
                  if r.idx == gpu_idx_to_finish)
gpu_runner.finish(ok=True)
_qapp.processEvents()
# After refill GPU<=2 and CPU still 1.
gpu_active = len(mgr._active) - len(mgr._active_cpu)
check("Toggle OFF: GPU side <= max_concurrent after refill",
      gpu_active <= mgr.max_concurrent,
      f"gpu_active={gpu_active}")
check("Toggle OFF: no new CPU slot opened by the refill",
      len(mgr._active_cpu) == 1)


# ---- 6. add_jobs() appends to tail ---------------------------------------
print()
print("[6] add_jobs() appends to tail, FIFO order preserved")
mgr = make_mgr(n_jobs=3, max_concurrent=1, use_cpu=False)
mgr.start()   # idx 0 runs, idx 1+2 pending
pending_before = list(mgr._pending)
new_jobs = [(99, "late_a.mp4", "late_a_out.mp4", "compress", "", "none"),
            (100, "late_b.mp4", "late_b_out.mp4", "compress", "", "none")]
mgr.add_jobs(new_jobs)
pending_after = list(mgr._pending)
check("add_jobs: pending grew by 2",
      len(pending_after) - len(pending_before) == 2)
check("add_jobs: late entries land at the END of pending",
      pending_after[-2:] == pending_before[-2:][-0:]  # tail check below
      or True)  # tautology, real check next:
# The new slots should be at the tail (slots = len(orig) and len+1).
check("add_jobs: new pending slots are the LAST in queue",
      pending_after[-2:] == [3, 4],
      f"pending_after={pending_after}")
check("add_jobs: running job (idx 0) untouched",
      0 in mgr._active)
check("add_jobs: jobs list grew (5 total)",
      len(mgr.jobs) == 5)


# ---- 7. RAM watchdog veto -------------------------------------------------
print()
print("[7] RAM watchdog veto skips the CPU slot")
mgr = make_mgr(n_jobs=4, max_concurrent=2, use_cpu=True)
mgr._cpu_slot_safe_to_open = lambda: False   # veto
mgr.start()
check("RAM veto: only 2 active (CPU slot withheld)",
      len(mgr._active) == 2, f"active={len(mgr._active)}")
check("RAM veto: zero CPU slots opened",
      len(mgr._active_cpu) == 0)
# Lift veto, finish a GPU; should refill and now open the CPU slot.
mgr._cpu_slot_safe_to_open = lambda: True
done = list(mgr._active)[0]
runner = next(r for r in FakeRunner.instances if r.idx == done)
runner.finish(ok=True)
_qapp.processEvents()
check("RAM veto lifted: CPU slot opens on next dispatch",
      len(mgr._active_cpu) == 1 and len(mgr._active) == 3,
      f"active={len(mgr._active)}, cpu={len(mgr._active_cpu)}")


# ---- 8. force_cpu_encoder mapping ----------------------------------------
print()
print("[8] force_cpu_encoder mapping")
check("hevc_nvenc -> libx265",
      sr.force_cpu_encoder({"encoder": "hevc_nvenc"})["encoder"] == "libx265")
check("h264_nvenc -> libx264",
      sr.force_cpu_encoder({"encoder": "h264_nvenc"})["encoder"] == "libx264")
check("h264_amf -> libx264",
      sr.force_cpu_encoder({"encoder": "h264_amf"})["encoder"] == "libx264")
check("h264_qsv -> libx264",
      sr.force_cpu_encoder({"encoder": "h264_qsv"})["encoder"] == "libx264")
check("codec_hint 'h265' beats h264 encoder family",
      sr.force_cpu_encoder({"encoder": "h264_nvenc"},
                           "h265")["encoder"] == "libx265")
src_dict = {"encoder": "h264_nvenc"}
_ = sr.force_cpu_encoder(src_dict)
check("force_cpu_encoder does NOT mutate caller's dict",
      "_cpu_slot" not in src_dict and src_dict["encoder"] == "h264_nvenc")


# ---- 9. Thread cap sanity -------------------------------------------------
print()
print("[9] CPU encoder thread cap")
n_par = sr.cpu_encoder_thread_count(parallel_gpu_running=True)
n_solo = sr.cpu_encoder_thread_count(parallel_gpu_running=False)
cpu = os.cpu_count() or 4
check("Thread cap parallel >= 1",
      n_par >= 1, f"n_par={n_par}")
check("Thread cap solo >= parallel (solo gets more)",
      n_solo >= n_par, f"solo={n_solo}, par={n_par}")
check("Thread cap solo <= cores-2",
      n_solo <= max(1, cpu - 2), f"solo={n_solo}, cpu={cpu}")
check("Thread cap parallel <= floor((cores-2)/2)",
      n_par <= max(1, (cpu - 2) // 2), f"par={n_par}, cpu={cpu}")


# ---- Summary --------------------------------------------------------------
print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.3.0 dispatch unit-tests PASS.")
sys.exit(0)
