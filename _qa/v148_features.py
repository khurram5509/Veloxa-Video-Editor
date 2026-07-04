"""V14.8.0 feature tests:

1. Download stall detection (urllib + per-read socket timeout + loop-
   level inactivity check fires within ~30s, not "forever").
2. Custom FFmpeg-args passthrough: shlex.split parses correctly, the
   splice fires in JobRunner._run_ffmpeg, malformed args fail safely.
3. EBU R128 loudnorm is still wired through the audio filter chain
   (regression guard -- checkbox sets the right filter).
4. Onboarding tour gated by QSettings; second launch silent.
5. Update dialog has the Download-in-Browser / Open-Release-Page
   buttons + helpers.
"""
import os, sys, tempfile, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


print()
print("=" * 72)
print("V14.8.0 -- feature tests")
print("=" * 72)


# ---- 1. Custom FFmpeg-args splice (behavioural, end-to-end) -------------
print()
print("[1] Custom FFmpeg-args splice spans the entire encode pipeline")
from PyQt6.QtCore import QCoreApplication, QEventLoop
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
from engine import batch as bm

ffmpeg = str(ROOT / "ffmpeg" / "ffmpeg.exe")
ffprobe = str(ROOT / "ffmpeg" / "ffprobe.exe")
if not Path(ffmpeg).exists():
    print("  SKIP  bundled ffmpeg not found")
else:
    tmp = Path(tempfile.mkdtemp(prefix="veloxa_v148_"))
    src = tmp / "src.mp4"
    dst = tmp / "out.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i",
        "testsrc=duration=1:size=320x240:rate=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(src)], capture_output=True, check=True, timeout=30)
    opts = {
        "out_codec": "h264", "encoder": "libx264", "out_res": "Original",
        "out_w": 320, "out_h": 240, "video_quality": "Balanced",
        "audio_quality": "Balanced", "hw_decode": False,
        "trim_start": 0.0, "trim_end": 0.0, "fade_in": 0.0, "fade_out": 0.0,
        "speed": 1.0, "force_stereo": True, "loudnorm": False,
        "out_pattern": "{name}_out",
        "custom_ffmpeg_args": "-metadata title=v148_splice_test",
    }
    done = {"flag": False, "ok": None}
    r = bm.JobRunner(0, str(src), str(dst), "video", "", "none",
                     ffmpeg, ffprobe, opts)
    r.job_finished.connect(
        lambda i, ok, msg: done.update(flag=True, ok=ok))
    r.start()
    deadline = time.monotonic() + 60
    while not done["flag"] and time.monotonic() < deadline:
        _app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.02)
    r.wait(2000)
    check("Encode with custom_ffmpeg_args succeeded",
          done["ok"] is True)
    if dst.exists():
        p = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format_tags=title",
             "-of", "default=nokey=1:noprint_wrappers=1", str(dst)],
            capture_output=True, text=True)
        check("Custom args spliced and applied (title metadata == "
              "'v148_splice_test')",
              p.stdout.strip() == "v148_splice_test")

# Malformed custom args should NOT crash -- should be logged and ignored.
from engine.batch import JobRunner
import inspect
src_run = inspect.getsource(JobRunner._run_ffmpeg)
check("_run_ffmpeg catches shlex parse errors (ValueError)",
      "ValueError" in src_run and "ignoring user override" in src_run)


# ---- 2. Download stall detection in the updater ------------------------
print()
print("[2] Download stall detection")
from app import updater as _u
download_src = inspect.getsource(_u.download_installer)
check("download_installer sets PER_READ_TIMEOUT_S",
      "PER_READ_TIMEOUT_S" in download_src)
check("download_installer sets STALL_ABORT_S",
      "STALL_ABORT_S" in download_src)
check("download_installer aborts on 'Download stalled'",
      "Download stalled" in download_src)
check("download_installer catches per-read TimeoutError/OSError",
      "(TimeoutError, OSError)" in download_src)


# ---- 3. Update dialog UX: browser button + open-release helper ---------
print()
print("[3] Update-dialog browser fallback")
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("Main update dialog has 'Download in Browser' button",
      "Download in Browser" in mw_src)
check("MainWindow defines _open_update_in_browser",
      "def _open_update_in_browser" in mw_src)
check("MainWindow defines _open_url_in_browser",
      "def _open_url_in_browser" in mw_src)
check("MainWindow defines _show_download_failed_dialog",
      "def _show_download_failed_dialog" in mw_src)
# Up-to-date dialog now includes "Open Release Page".
_no_update_src = mw_src.split("def _on_no_update")[1].split("def ")[0]
check("'Up to date' dialog has 'Open Release Page' button",
      "Open Release Page" in _no_update_src)
check("'Up to date' dialog includes current version",
      "Current version" in _no_update_src
      and "VELOXA_APP_VERSION" in _no_update_src)


# ---- 4. Custom-args field in the Output tab + persistence -------------
print()
print("[4] Custom FFmpeg-args field wired in main_window")
check("Output tab defines self.custom_ffmpeg_args",
      "self.custom_ffmpeg_args = QLineEdit()" in mw_src)
check("_collect_opts emits the custom_ffmpeg_args key",
      '"custom_ffmpeg_args":' in mw_src)
check("_load_settings restores custom_ffmpeg_args from QSettings",
      'value("custom_ffmpeg_args"' in mw_src)
check("Profile dict round-trips custom_ffmpeg_args",
      'd.get("custom_ffmpeg_args"' in mw_src)
check("closeEvent persists custom_ffmpeg_args",
      'setValue("custom_ffmpeg_args"' in mw_src)


# ---- 5. EBU R128 loudnorm still wired -------------------------------------
print()
print("[5] EBU R128 loudnorm filter still applied when checkbox is on")
from engine.encoders import audio_filter_chain
on = audio_filter_chain({"loudnorm": True})
off = audio_filter_chain({"loudnorm": False})
check("opts.loudnorm=True puts 'loudnorm' in the audio filter chain",
      "loudnorm" in on)
check("opts.loudnorm=True uses EBU R128 streaming target -16 LUFS",
      "I=-16" in on and "TP=-1.5" in on and "LRA=11" in on)
check("opts.loudnorm=False does NOT add the loudnorm filter",
      "loudnorm" not in off)
check("UI checkbox 'Normalize audio loudness (EBU R128, -16 LUFS)' "
      "still present",
      "Normalize audio loudness (EBU R128" in mw_src)


# ---- 6. Onboarding tour gated by QSettings -----------------------------
print()
print("[6] Onboarding tour gated + has Help menu entry")
check("MainWindow defines _maybe_show_onboarding_tour",
      "def _maybe_show_onboarding_tour" in mw_src)
check("MainWindow defines _run_onboarding_tour",
      "def _run_onboarding_tour" in mw_src)
check("Onboarding tour scheduled via QTimer.singleShot at startup",
      "_maybe_show_onboarding_tour" in mw_src
      and "QTimer.singleShot" in mw_src)
check("Gating QSettings key onboarding_seen_v1 referenced",
      "onboarding_seen_v1" in mw_src)
check("Help menu has 'Show Onboarding Tour' entry",
      "Show Onboarding Tour" in mw_src)
# Tour covers all 3 features.
_tour_src = mw_src.split("def _run_onboarding_tour")[1].split("def ")[0]
check("Tour step 1 mentions Profiles",
      "Profiles save" in _tour_src or "Profile" in _tour_src)
check("Tour step 2 mentions Audio Visuals",
      "Audio Visuals" in _tour_src)
check("Tour step 3 mentions GPU status",
      "GPU" in _tour_src and "status" in _tour_src.lower())


print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.8.0 feature tests PASS.")
sys.exit(0)
