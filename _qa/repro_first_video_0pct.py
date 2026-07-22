"""Reproduce the 'first encoding video stuck at 0%' bug.

Build a real 8-second video via ffmpeg lavfi testsrc, drop it through
JobRunner with a stub BatchManager-equivalent receiver, and dump every
progress emit with timestamp. If the first job emits only at the end
(or skips emissions entirely), we'll see a long quiet stretch followed
by one 100% emission. If progress flows normally, we'll see 20-40
emissions evenly spaced.
"""
import os, sys, time, tempfile, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEventLoop
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from engine import batch as bm

# Find ffmpeg.
ffmpeg = str(ROOT / "ffmpeg" / "ffmpeg.exe")
ffprobe = str(ROOT / "ffmpeg" / "ffprobe.exe")
if not os.path.exists(ffmpeg):
    print(f"FAIL: ffmpeg not at {ffmpeg}")
    sys.exit(1)

tmpdir = Path(tempfile.mkdtemp(prefix="veloxa_repro_"))
src = tmpdir / "src.mp4"
dst = tmpdir / "out.mp4"

# Build an 8-second 640x360 30fps test video with audio.
print(f"Generating test source at {src} ...")
gen = subprocess.run([
    ffmpeg, "-y",
    # 8-second source: long enough for several progress emissions,
    # short enough that the repro stays fast on any machine.
    "-f", "lavfi", "-i", "testsrc=duration=8:size=640x360:rate=30",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-shortest", str(src),
], capture_output=True, text=True, timeout=120)
if gen.returncode != 0:
    print("FAIL: source generation:", gen.stderr[-500:])
    sys.exit(1)
print(f"Source built: {os.path.getsize(src)} bytes")

# Standard opts equivalent to what the GUI would build for a basic
# H.264 transcode.
opts = {
    "out_codec": "h264",
    "encoder": "libx264",        # CPU encoder, deterministic.
    "out_res": "Original",
    "out_w": 640, "out_h": 360,
    "video_quality": "Balanced",
    "audio_quality": "Balanced",
    "hw_decode": False,
    "trim_start": 0.0, "trim_end": 0.0,
    "fade_in": 0.0, "fade_out": 0.0,
    "speed": 1.0,
    "force_stereo": True,
    "loudnorm": False,
    "out_pattern": "{name}_out",
}

# Collect every progress emission.
emits = []
finished = {"done": False, "ok": None, "msg": None}

t_start = time.monotonic()

def on_progress(idx, pct):
    emits.append((time.monotonic() - t_start, idx, pct))

def on_finished(idx, ok, msg):
    finished["done"] = True
    finished["ok"] = ok
    finished["msg"] = msg

runner = bm.JobRunner(0, str(src), str(dst), "video", "", "none",
                     ffmpeg, ffprobe, opts)
runner.progress.connect(on_progress)
runner.job_finished.connect(on_finished)

print("Starting JobRunner ...")
runner.start()

# Spin the event loop until job_finished fires (or 60s timeout).
deadline = time.monotonic() + 60
while not finished["done"] and time.monotonic() < deadline:
    _app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    time.sleep(0.02)

runner.wait(5000)

print()
print(f"Job finished: ok={finished['ok']}, msg={finished['msg']!r}")
print(f"Output size: {os.path.getsize(dst) if os.path.exists(dst) else 'MISSING'}")
print(f"Progress emissions: {len(emits)}")
if not emits:
    print("FAIL: ZERO progress emissions. First-video-0pct bug REPRODUCED.")
    sys.exit(1)
print()
print("First 5 emissions:")
for t, i, p in emits[:5]:
    print(f"  t={t:6.3f}s  idx={i}  pct={p:6.2f}")
print("Last 5 emissions:")
for t, i, p in emits[-5:]:
    print(f"  t={t:6.3f}s  idx={i}  pct={p:6.2f}")

# The bug signature is "silence, then a single 100% landing" -- i.e.
# NO graduated progress. Assert on the emission PATTERN, not wall-clock
# timing: on a fast machine the whole encode can finish in under a
# second, so FFmpeg's ~0.25s progress cadence makes any "first emit
# within X% of runtime" heuristic a false positive. Graduated
# emissions (2+ distinct values below 100%) prove progress flowed.
below_100 = sorted({round(p, 1) for _, _, p in emits if p < 100.0})
if len(below_100) < 2:
    first_t = emits[0][0]
    last_t = emits[-1][0]
    print()
    print(f"FAIL: no graduated progress -- only {below_100 or '[]'} seen "
          f"below 100% (first emit {first_t:.2f}s, runtime {last_t:.2f}s). "
          "This is the first-video-0pct signature.")
    sys.exit(1)

print()
print(f"PASS: graduated progress flowed throughout the encode "
      f"({len(below_100)} distinct values below 100%: {below_100}).")
sys.exit(0)
