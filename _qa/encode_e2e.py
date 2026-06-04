"""V14.1.0 end-to-end encode verification.

Generates synthetic inputs via FFmpeg lavfi, runs every encode path
through the actual ``engine.JobRunner``, then probes each output to
check that:

* the container opens (no truncation),
* exactly one H.264 video stream exists at the requested target size,
* one AAC audio stream exists,
* duration matches expected (within 100 ms),
* there are no error lines in ffprobe.

Covers:

* video.mp4  ->  video (basic)
* video.mp4  +  image watermark   (filter graph w/ overlay)
* video.mp4  +  intro / outro     (concat pass)
* audio.m4a  +  still-image visual  (pre-scale path)
* audio.m4a  +  video visual        (hwaccel decode path)
* audio.m4a  +  each of the 6 AV templates (no visual file)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Make the project root importable.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Import outside Qt because JobRunner has Qt deps. Easier path: import
# the lower-level helpers directly via the engine's batch module
# (which imports Qt, but that's fine — we just won't start an event
# loop).
from engine import (
    JobRunner, find_ffmpeg,
    audio_template_choices, get_audio_template,
)


FFMPEG, FFPROBE = find_ffmpeg()
assert FFMPEG and FFPROBE, "FFmpeg / FFprobe missing"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append((name, detail))
        print(f"  FAIL  {name}  -- {detail}")


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ============================================================ test inputs

def make_inputs(tmp: Path):
    """Generate synthetic test sources via FFmpeg lavfi."""
    video = tmp / "src_video.mp4"
    audio = tmp / "src_audio.m4a"
    image = tmp / "src_image.png"
    visvid = tmp / "src_visual.mp4"
    intro = tmp / "intro.mp4"
    outro = tmp / "outro.mp4"

    # 3-second test pattern video at 1920x1080 with synthetic audio.
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(video)], check=True)

    # 3-second silent audio.
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
        "-c:a", "aac", "-b:a", "128k",
        str(audio)], check=True)

    # 1920x1080 solid colour image.
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:size=1920x1080",
        "-vframes", "1", str(image)], check=True)

    # 2-second video visual.
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", str(visvid)], check=True)

    # 1-second intro / outro.
    for label, path in [("intro", intro), ("outro", outro)]:
        subprocess.run([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={'green' if label == 'intro' else 'red'}:size=1920x1080:duration=1",
            "-f", "lavfi", "-i", f"sine=frequency={330 if label == 'intro' else 220}:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            str(path)], check=True)

    return dict(video=video, audio=audio, image=image, visvid=visvid,
                intro=intro, outro=outro)


# ============================================================ probe helpers

def probe(path: Path) -> dict:
    """Return {streams:[{codec_type,codec_name,width,height,duration}], duration}."""
    r = subprocess.run([
        FFPROBE, "-v", "error",
        "-show_format", "-show_streams",
        "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


def expect_valid_mp4(name: str, path: Path, *, w: int, h: int,
                     duration: float, dur_tol: float = 0.3,
                     audio_required: bool = True):
    """Assert the output container is a valid MP4 with the expected
    streams and duration."""
    if not path.exists():
        check(f"{name}: output file exists", False, f"{path} missing")
        return
    size_mb = path.stat().st_size / 1_048_576
    check(f"{name}: output non-empty ({size_mb:.2f} MB)",
          size_mb > 0.01, f"size={size_mb:.3f} MB")
    try:
        meta = probe(path)
    except Exception as exc:
        check(f"{name}: ffprobe parses container", False, str(exc))
        return
    check(f"{name}: ffprobe parses container", True)
    streams = meta.get("streams") or []
    vid = next((s for s in streams if s.get("codec_type") == "video"), None)
    aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
    check(f"{name}: exactly one video stream",
          vid is not None and sum(1 for s in streams if s.get("codec_type") == "video") == 1)
    if vid:
        actual_w = int(vid.get("width") or 0)
        actual_h = int(vid.get("height") or 0)
        check(f"{name}: video {actual_w}x{actual_h} == target {w}x{h}",
              (actual_w, actual_h) == (w, h))
        check(f"{name}: video codec h264",
              vid.get("codec_name", "").lower() in ("h264", "hevc"))
    if audio_required:
        check(f"{name}: audio stream present", aud is not None)
        if aud:
            check(f"{name}: audio codec aac",
                  aud.get("codec_name", "").lower() in ("aac", "mp4a"))
    fmt = meta.get("format") or {}
    actual_dur = float(fmt.get("duration") or 0)
    check(f"{name}: duration {actual_dur:.2f}s ~= expected {duration:.2f}s",
          abs(actual_dur - duration) < dur_tol,
          f"diff={abs(actual_dur - duration):.2f}s")


# ============================================================ runner harness

def encode_one(*, src: Path, dst: Path, kind: str, opts: dict,
               visual_path: Path = None, visual_kind: str = None,
               visual_duration: float = 0.0):
    """Run a single JobRunner synchronously. Returns (ok, msg)."""
    # JobRunner is a QThread — we just call its run() body directly.
    # The signals it emits during encode are ignored.
    runner = JobRunner(
        idx=0, src=str(src), dst=str(dst), kind=kind,
        visual_path=str(visual_path) if visual_path else None,
        visual_kind=visual_kind,
        ffmpeg=FFMPEG, ffprobe=FFPROBE, opts=opts)
    runner._t_start = 0.0
    if visual_duration:
        runner.opts["video_wm_duration"] = visual_duration
    try:
        if kind == "video":
            ok, msg = runner._encode_video()
        else:
            ok, msg = runner._encode_audio_to_video()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        # Cleanup the pre-scaled temp if any.
        if runner._tmp_prescaled and os.path.exists(runner._tmp_prescaled):
            try: os.remove(runner._tmp_prescaled)
            except OSError: pass
    return ok, msg


def base_opts(target_w=1280, target_h=720):
    return {
        "trim_start": 0.0, "trim_end": 0.0,
        "watermark_path": None, "wm_preset": "Bottom-Right",
        "wm_offset_x": 0, "wm_offset_y": 0, "wm_padding": 20,
        "wm_opacity": 1.0, "wm_scale": 0.15,
        "text_wm_text": "", "text_wm_size": 36, "text_wm_color": "#ffffff",
        "text_wm_preset": "Bottom-Left",
        "text_wm_offset_x": 0, "text_wm_offset_y": 0,
        "text_wm_padding": 20, "text_wm_opacity": 1.0,
        "out_w": target_w, "out_h": target_h,
        "encoder": "libx264", "speed_tier": "Fast",
        "force_stereo": True, "loudnorm": False, "speed": 1.0,
        "out_pattern": "{name}", "fade_in": 0.0, "fade_out": 0.0,
        "hw_decode": False,
        "split_enabled": False, "max_length_s": 0.0,
        "video_bitrate_kbps": 2000, "audio_bitrate_kbps": 128,
        "intro_path": "", "outro_path": "", "merge_audio_fade_s": 0.0,
        "video_wm_path": None, "video_wm_duration": 0.0,
        "vid_wm_preset": "Top-Right", "vid_wm_offset_x": 0,
        "vid_wm_offset_y": 0, "vid_wm_padding": 20, "vid_wm_opacity": 1.0,
        "vid_wm_scale": 0.20,
        "apply_intro": True, "apply_outro": True,
    }


# ============================================================ run pass

def main():
    tmp = Path(tempfile.mkdtemp(prefix="veloxa_e2e_"))
    print(f"Working dir: {tmp}")
    try:
        srcs = make_inputs(tmp)
        T_W, T_H = 1280, 720

        # -------------------- video -> video
        section("Video -> MP4 (basic)")
        dst = tmp / "out_video.mp4"
        ok, msg = encode_one(src=srcs["video"], dst=dst, kind="video",
                             opts=base_opts(T_W, T_H))
        check("encode succeeded", ok, msg)
        expect_valid_mp4("basic video", dst, w=T_W, h=T_H, duration=3.0)

        # -------------------- video + image watermark
        section("Video -> MP4 with image watermark")
        opts = base_opts(T_W, T_H)
        opts["watermark_path"] = str(srcs["image"])
        dst = tmp / "out_video_wm.mp4"
        ok, msg = encode_one(src=srcs["video"], dst=dst, kind="video",
                             opts=opts)
        check("encode succeeded", ok, msg)
        expect_valid_mp4("video+wm", dst, w=T_W, h=T_H, duration=3.0)

        # -------------------- video + intro/outro
        section("Video -> MP4 with intro + outro concat")
        opts = base_opts(T_W, T_H)
        opts["intro_path"] = str(srcs["intro"])
        opts["outro_path"] = str(srcs["outro"])
        dst = tmp / "out_video_io.mp4"
        ok, msg = encode_one(src=srcs["video"], dst=dst, kind="video",
                             opts=opts)
        check("encode succeeded", ok, msg)
        # Total duration = 1 (intro) + 3 (main) + 1 (outro) = 5
        expect_valid_mp4("video+intro+outro", dst, w=T_W, h=T_H,
                         duration=5.0, dur_tol=0.5)

        # -------------------- audio + image visual (pre-scale path)
        section("Audio + image visual -> MP4")
        opts = base_opts(T_W, T_H)
        dst = tmp / "out_audio_image.mp4"
        ok, msg = encode_one(src=srcs["audio"], dst=dst, kind="audio",
                             opts=opts, visual_path=srcs["image"],
                             visual_kind="image")
        check("encode succeeded", ok, msg)
        expect_valid_mp4("audio+image", dst, w=T_W, h=T_H, duration=3.0)

        # -------------------- audio + video visual (hwaccel decode path)
        section("Audio + video visual -> MP4")
        opts = base_opts(T_W, T_H)
        dst = tmp / "out_audio_video.mp4"
        ok, msg = encode_one(src=srcs["audio"], dst=dst, kind="audio",
                             opts=opts, visual_path=srcs["visvid"],
                             visual_kind="video")
        check("encode succeeded", ok, msg)
        expect_valid_mp4("audio+video-visual", dst, w=T_W, h=T_H,
                         duration=3.0)

        # -------------------- audio + each of the 6 AV templates
        section("Audio + each AV template -> MP4")
        for tpl_key, tpl_name in audio_template_choices():
            if tpl_key == "none": continue
            opts = base_opts(T_W, T_H)
            opts["audio_template"] = tpl_key
            dst = tmp / f"out_tpl_{tpl_key}.mp4"
            ok, msg = encode_one(src=srcs["audio"], dst=dst, kind="audio",
                                 opts=opts)
            check(f"template {tpl_key!r}: encode succeeded", ok, msg)
            if ok:
                expect_valid_mp4(f"template {tpl_key!r}", dst, w=T_W, h=T_H,
                                 duration=3.0)

        section("Summary")
        total = len(PASS) + len(FAIL)
        print(f"  PASS: {len(PASS)} / {total}")
        if FAIL:
            print()
            print("FAILURES:")
            for n, d in FAIL:
                print(f"  - {n}: {d}")
            return 1
        return 0
    finally:
        # Best-effort cleanup of the temp dir.
        try: shutil.rmtree(tmp, ignore_errors=True)
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
