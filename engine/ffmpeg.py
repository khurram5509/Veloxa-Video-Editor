"""FFmpeg / ffprobe location, media probing, and single-frame previews."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .filters import build_filter, build_audio_filter


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ---------------------------------------------------------------- discovery

def _candidate_dirs():
    """Where we look for bundled or co-located ffmpeg / ffprobe binaries."""
    dirs = []
    if getattr(sys, "frozen", False):
        # Next to the EXE so users can swap in a custom build without rebuilding.
        dirs.append(Path(sys.executable).parent / "ffmpeg")
        # PyInstaller --onefile extracts bundled data here at runtime.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass) / "ffmpeg")
    else:
        dirs.append(Path(__file__).resolve().parent.parent / "ffmpeg")
    return dirs


def find_ffmpeg():
    """Return ``(ffmpeg_path, ffprobe_path)``; either may be ``None``."""
    ff_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    fp_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    for d in _candidate_dirs():
        ff = d / ff_name
        fp = d / fp_name
        if ff.exists() and fp.exists():
            return str(ff), str(fp)
    return shutil.which("ffmpeg"), shutil.which("ffprobe")


# ---------------------------------------------------------------- probing

def probe_duration(ffprobe: str, path: str) -> float:
    if not ffprobe or not path:
        return 0.0
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=15)
        return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return 0.0


def probe_has_audio(ffprobe: str, path: str) -> bool:
    """V12.3 audit fix (BUG-3): return True iff ``path`` has at least one
    audio stream. Used by the intro/outro concat pass — if an intro is a
    silent screen-capture or a soundless animation, we need to inject a
    synthetic silent track via ``anullsrc`` so the concat filter graph
    doesn't error out with "Stream specifier ':a' matches no streams"."""
    if not ffprobe or not path:
        return False
    cmd = [ffprobe, "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index",
           "-of", "csv=p=0", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return bool(r.stdout.strip())


def probe_resolution(ffprobe: str, path: str):
    """Return ``(width, height)`` of the first video stream, or ``(0, 0)``."""
    if not ffprobe or not path:
        return 0, 0
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height",
           "-of", "csv=s=x:p=0", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return 0, 0
    s = r.stdout.strip()
    if "x" in s:
        try:
            w, h = s.split("x")
            return int(w), int(h)
        except ValueError:
            pass
    return 0, 0


# ---------------------------------------------------------------- probe cache

# Module-level mtime-keyed cache so repeatedly probing the same file inside a
# session is essentially free. Invalidates automatically when the file is
# modified on disk (mtime changes).
_probe_cache = {}  # path -> (mtime, duration_or_None, (w, h)_or_None)


def cached_probe_duration(ffprobe: str, path: str) -> float:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return 0.0
    cached = _probe_cache.get(path)
    if cached and cached[0] == mtime and cached[1] is not None:
        return cached[1]
    duration = probe_duration(ffprobe, path)
    res = cached[2] if cached and cached[0] == mtime else None
    _probe_cache[path] = (mtime, duration, res)
    return duration


def cached_probe_resolution(ffprobe: str, path: str):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return 0, 0
    cached = _probe_cache.get(path)
    if cached and cached[0] == mtime and cached[2] is not None:
        return cached[2]
    res = probe_resolution(ffprobe, path)
    dur = cached[1] if cached and cached[0] == mtime else None
    _probe_cache[path] = (mtime, dur, res)
    return res


def clear_probe_cache() -> None:
    _probe_cache.clear()


# ---------------------------------------------------------------- preview

def generate_preview(ffmpeg: str, video_path: str, opts: dict,
                     out_path: str, src_w: int, src_h: int,
                     time_s: float = 0.0) -> bool:
    """Render one preview frame for a video source."""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(0.0, time_s):.3f}", "-i", video_path]

    image_wm_idx = video_wm_idx = None
    next_idx = 1
    wm_path = opts.get("watermark_path")
    if wm_path and os.path.exists(wm_path):
        cmd += ["-i", wm_path]
        image_wm_idx = next_idx
        next_idx += 1

    vid_wm_path = opts.get("video_wm_path")
    if vid_wm_path and os.path.exists(vid_wm_path):
        # For preview, seek the WM to the same offset as the main video,
        # wrapped to the WM's duration so longer scrubs land on later frames.
        vid_wm_dur = float(opts.get("video_wm_duration") or 0.0)
        if vid_wm_dur > 0:
            wm_seek = max(0.0, time_s) % max(0.001, vid_wm_dur)
            cmd += ["-ss", f"{wm_seek:.3f}", "-i", vid_wm_path]
        else:
            cmd += ["-i", vid_wm_path]
        video_wm_idx = next_idx
        next_idx += 1

    fc, last = build_filter(opts, src_w, src_h, for_preview=True,
                            image_wm_idx=image_wm_idx,
                            video_wm_idx=video_wm_idx)
    if fc:
        cmd += ["-filter_complex", fc, "-map", last]

    cmd += ["-frames:v", "1", "-q:v", "3", out_path]
    try:
        r = subprocess.run(cmd, capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and os.path.exists(out_path)


def generate_visual_preview(ffmpeg: str, visual_path: str, visual_kind: str,
                            visual_duration: float, opts: dict,
                            out_path: str, time_s: float = 0.0) -> bool:
    """Render one preview frame for an audio job whose visual is image OR video.

    For video visuals, the seek is wrapped to the visual's own duration so
    scrubbing the audio timeline shows progress through the looped clip.
    """
    target_w = int(opts.get("out_w") or 1920)
    target_h = int(opts.get("out_h") or 1080)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if visual_kind == "video" and visual_duration > 0:
        seek = max(0.0, time_s) % max(0.001, visual_duration)
        cmd += ["-ss", f"{seek:.3f}", "-i", visual_path]
    else:
        cmd += ["-i", visual_path]

    # Dummy audio so the watermark indices stay aligned with the encode
    # path: visual=0, audio=1, image_wm=2 (if any), video_wm=next.
    cmd += ["-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100"]

    image_wm_idx = video_wm_idx = None
    next_idx = 2
    wm_path = opts.get("watermark_path")
    if wm_path and os.path.exists(wm_path):
        cmd += ["-i", wm_path]
        image_wm_idx = next_idx
        next_idx += 1

    vid_wm_path = opts.get("video_wm_path")
    if vid_wm_path and os.path.exists(vid_wm_path):
        vid_wm_dur = float(opts.get("video_wm_duration") or 0.0)
        if vid_wm_dur > 0:
            wm_seek = max(0.0, time_s) % max(0.001, vid_wm_dur)
            cmd += ["-ss", f"{wm_seek:.3f}", "-i", vid_wm_path]
        else:
            cmd += ["-i", vid_wm_path]
        video_wm_idx = next_idx
        next_idx += 1

    fc, last = build_audio_filter(opts, target_w, target_h, for_preview=True,
                                  image_wm_idx=image_wm_idx,
                                  video_wm_idx=video_wm_idx)
    if fc:
        cmd += ["-filter_complex", fc, "-map", last]

    cmd += ["-frames:v", "1", "-q:v", "3", out_path]
    try:
        r = subprocess.run(cmd, capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and os.path.exists(out_path)
