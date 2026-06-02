"""Headless / CLI entry point for Veloxa Video Editor V12.3.

Invoked when ``--cli`` is on the command line. Reads profiles from the same
QSettings store the GUI uses, builds a job list from the supplied inputs,
runs the engine's ``BatchManager`` to completion, and prints progress.

Designed to be wired into Task Scheduler, build pipelines, or anything that
needs to drive the encoder without the GUI being open.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSettings

from engine import (
    BatchManager, find_ffmpeg, probe_duration,
    detect_available_encoders,
)
from .profile_opts import profile_to_opts


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv",
              ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
ALL_INPUT_EXTS = VIDEO_EXTS | AUDIO_EXTS


# ---------------------------------------------------------------- console attach

def _attach_to_parent_console():
    """Make a ``--windowed`` PyInstaller EXE able to write to its launching
    console (cmd / PowerShell). Silently no-ops if no parent console exists
    (e.g. when double-clicked from Explorer)."""
    if sys.platform != "win32":
        return
    try:
        # ATTACH_PARENT_PROCESS = -1 (DWORD 0xFFFFFFFF)
        if not ctypes.windll.kernel32.AttachConsole(-1):
            return
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        try:
            sys.stdin = open("CONIN$", "r", encoding="utf-8")
        except OSError:
            pass
    except OSError:
        pass


# ---------------------------------------------------------------- profile load

def _load_profiles(settings: QSettings) -> dict:
    raw = settings.value("profiles", "{}")
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _load_default_settings(settings: QSettings) -> dict:
    """Build a profile-shaped dict from the GUI's last-used settings."""
    s = settings

    def _get(key, default):
        v = s.value(key, default)
        return v if v is not None else default

    def _to_bool(v, default):
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v) if v is not None else default

    return {
        "trim_start": float(_get("trim_start", 0.0)),
        "trim_end": float(_get("trim_end", 0.0)),
        "wm_path": _get("wm_path", "") or "",
        "wm_preset": _get("wm_preset", "Bottom-Right"),
        "wm_off_x": int(_get("wm_off_x", 0)),
        "wm_off_y": int(_get("wm_off_y", 0)),
        "wm_padding": int(_get("wm_padding", 20)),
        "wm_opacity": int(_get("wm_opacity", 100)),
        "wm_scale": int(_get("wm_scale", 15)),
        "text_wm_text": _get("text_wm_text", "") or "",
        "text_wm_size": int(_get("text_wm_size", 36)),
        "text_wm_color": _get("text_wm_color", "#ffffff") or "#ffffff",
        "text_wm_preset": _get("text_wm_preset", "Bottom-Left"),
        "text_wm_off_x": int(_get("text_wm_off_x", 0)),
        "text_wm_off_y": int(_get("text_wm_off_y", 0)),
        "text_wm_padding": int(_get("text_wm_padding", 20)),
        "text_wm_opacity": int(_get("text_wm_opacity", 100)),
        "out_codec": _get("out_codec", "h264"),
        "out_encoder": _get("out_encoder", "(auto)"),
        "out_quality": _get("out_quality", "Balanced"),
        "out_res": _get("out_res", "4K (3840x2160)"),
        "parallel_jobs": int(_get("parallel_jobs", 1)),
        "force_stereo": _to_bool(_get("force_stereo", True), True),
        "loudnorm": _to_bool(_get("loudnorm", False), False),
        "speed": float(_get("speed", 1.0)),
        "out_suffix": _get("out_suffix", "_edited"),
    }


# ---------------------------------------------------------------- input expansion

def _expand_inputs(inputs: list) -> list:
    """Walk any directories in ``inputs``, returning a flat list of supported
    media files in deterministic (sorted) order."""
    out = []
    seen = set()
    for entry in inputs:
        p = Path(entry)
        if p.is_file():
            if p.suffix.lower() in ALL_INPUT_EXTS:
                if str(p.resolve()) not in seen:
                    seen.add(str(p.resolve()))
                    out.append(str(p.resolve()))
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if (child.is_file()
                        and child.suffix.lower() in ALL_INPUT_EXTS):
                    rp = str(child.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        out.append(rp)
        else:
            print(f"WARN: input not found, skipping: {entry}", file=sys.stderr)
    return out


def _kind_for(path: str) -> str:
    return "audio" if Path(path).suffix.lower() in AUDIO_EXTS else "video"


def _visual_kind_for(path: str):
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


# ---------------------------------------------------------------- command

def run_cli(argv: list) -> int:
    """Entry point. ``argv`` should NOT include ``--cli``."""
    _attach_to_parent_console()

    parser = argparse.ArgumentParser(
        prog="Veloxa-Video-Editor-V12.3 --cli",
        description="Veloxa Video Editor bulk encoder, headless mode.")
    parser.add_argument("--profile", default=None,
                        help="Profile name to use. Falls back to the GUI's "
                             "last-used settings if omitted.")
    parser.add_argument("--input", "-i", nargs="+", default=None,
                        help="Source file(s) and/or folder(s). Folders are "
                             "scanned recursively for supported media.")
    parser.add_argument("--output-dir", "-o", default=None,
                        help="Where to write outputs (default: next to each "
                             "source). Created if missing.")
    parser.add_argument("--visual", default=None,
                        help="Image OR video to use as the visual for any "
                             "audio inputs in this batch.")
    parser.add_argument("--parallel", type=int, default=None,
                        help="Concurrent jobs (1-2). Overrides the profile.")
    parser.add_argument("--list-profiles", action="store_true",
                        help="List saved profiles by name and exit.")
    parser.add_argument("--show-config", action="store_true",
                        help="Print the resolved engine opts as JSON and exit.")
    parser.add_argument("--no-overwrite", action="store_true",
                        help="Skip jobs whose destination file already exists "
                             "(default: overwrite without asking).")
    parser.add_argument("--speed", type=float, default=None,
                        help="Override playback speed (0.1-10.0, 1.0 = "
                             "unchanged).")
    parser.add_argument("--loudnorm", action="store_true",
                        help="Force audio loudness normalization on, even if "
                             "the profile has it off.")
    parser.add_argument("--suffix", default=None,
                        help="Override the output filename suffix (default: "
                             "from the profile, typically '_edited').")
    parser.add_argument("--max-length", type=float, default=None,
                        metavar="SECONDS",
                        help="Split inputs longer than this many seconds "
                             "into multiple parts. Each part is named "
                             "'<base>_Part1.mp4', '<base>_Part2.mp4', etc. "
                             "0 or omitted = no splitting.")
    args = parser.parse_args(argv)

    # Configure simple console logging for CLI use.
    root = logging.getLogger("veloxa")
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s | %(message)s",
        datefmt="%H:%M:%S"))
    root.addHandler(handler)

    # QCoreApplication is required for QSettings + signals/slots event loop.
    app = QCoreApplication(sys.argv)
    QCoreApplication.setOrganizationName("Veloxa-VD")
    QCoreApplication.setApplicationName("V10")
    settings = QSettings("Veloxa-VD", "V10")
    profiles = _load_profiles(settings)

    if args.list_profiles:
        if profiles:
            for name in sorted(profiles.keys(), key=str.lower):
                print(name)
        else:
            print("(no profiles saved)")
        return 0

    # Pick the profile / settings dict.
    if args.profile:
        if args.profile not in profiles:
            print(f"ERROR: profile '{args.profile}' not found. "
                  f"Use --list-profiles to see available.", file=sys.stderr)
            return 2
        profile_dict = profiles[args.profile]
    else:
        profile_dict = _load_default_settings(settings)

    ffmpeg, ffprobe = find_ffmpeg()
    if not ffmpeg:
        print("ERROR: FFmpeg binary not found. Either bundle it next to the "
              "app or add it to PATH.", file=sys.stderr)
        return 2

    available = detect_available_encoders(ffmpeg)
    opts = profile_to_opts(profile_dict, available)

    # CLI overrides land here so --show-config reflects what will actually run.
    if args.speed is not None:
        if args.speed < 0.1 or args.speed > 10.0:
            print("ERROR: --speed must be in [0.1, 10.0]", file=sys.stderr)
            return 2
        opts["speed"] = args.speed
    if args.loudnorm:
        opts["loudnorm"] = True
    if args.suffix is not None:
        # Back-compat: --suffix overrides any pattern with `{name}<suffix>`.
        opts["out_pattern"] = "{name}" + (args.suffix or "_edited")
    if args.max_length is not None:
        if args.max_length < 0:
            print("ERROR: --max-length must be >= 0", file=sys.stderr)
            return 2
        opts["max_length_s"] = float(args.max_length)
        opts["split_enabled"] = (args.max_length > 0)

    if args.show_config:
        print(json.dumps(opts, indent=2))
        return 0

    if not args.input:
        print("ERROR: no --input given. Use --help to see usage.",
              file=sys.stderr)
        return 2

    inputs = _expand_inputs(args.input)
    if not inputs:
        print("ERROR: no supported media files found in the provided "
              "inputs.", file=sys.stderr)
        return 2

    # Validate the visual once for the whole batch.
    visual_path = args.visual
    visual_kind = None
    visual_duration = 0.0
    if visual_path:
        visual_kind = _visual_kind_for(visual_path)
        if visual_kind is None or not os.path.exists(visual_path):
            print(f"ERROR: --visual must be an existing image or video: "
                  f"{visual_path}", file=sys.stderr)
            return 2
        if visual_kind == "video":
            visual_duration = probe_duration(ffprobe, visual_path)

    # Build the job list.
    output_dir = None
    if args.output_dir:
        output_dir = Path(args.output_dir)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"ERROR: could not create output dir: {e}",
                  file=sys.stderr)
            return 2

    pattern = opts.get("out_pattern") or "{name}_edited"
    max_length_s = float(opts.get("max_length_s") or 0.0)
    split_enabled = bool(opts.get("split_enabled", False)) and max_length_s > 0

    # V11.5: profile audio-visual rotation. Same logic as the GUI's
    # _build_jobs. The persistent counter lives in QSettings under
    # ``profile_visual_rotation/<safe_name>``.
    pv_enabled = bool(opts.get("profile_visuals_enabled", False))
    pv_list = [v for v in (opts.get("profile_visuals") or [])
               if isinstance(v, dict) and v.get("path")
               and os.path.exists(v.get("path"))]
    rotation_profile_name = args.profile or "_global"
    if pv_enabled and pv_list:
        from .profile_assets import rotation_key_for
        rotation_key = rotation_key_for(rotation_profile_name)
        try:
            rotation_start = int(settings.value(rotation_key, 0) or 0)
        except (TypeError, ValueError):
            rotation_start = 0
    else:
        rotation_key = None
        rotation_start = 0
    audio_seen = 0

    jobs = []
    audio_no_visual = []
    seen_dsts = set()  # avoid collisions when --output-dir collapses paths
    from datetime import datetime
    next_job_idx = 0
    for i, src in enumerate(inputs):
        kind = _kind_for(src)
        sp = Path(src)
        if kind == "audio":
            # Profile rotation overrides --visual when active.
            if pv_enabled and pv_list:
                pick = pv_list[(rotation_start + audio_seen) % len(pv_list)]
                v_path = pick.get("path")
                v_kind = pick.get("kind") or "image"
                v_dur = (probe_duration(ffprobe, v_path)
                         if v_kind == "video" else 0.0)
                audio_seen += 1
            elif visual_path:
                v_path, v_kind, v_dur = visual_path, visual_kind, visual_duration
            else:
                audio_no_visual.append(sp.name)
                continue
        else:
            v_path = v_kind = None
            v_dur = 0.0

        # Decide whether to split this input into parts. Probe duration once
        # and apply the user's trim values to compute the encodeable window.
        parts = []  # list of (clip_offset_s, clip_duration_s) tuples
        if split_enabled:
            src_dur = probe_duration(ffprobe, str(sp))
            trim_s = float(opts.get("trim_start", 0.0) or 0.0)
            trim_e = float(opts.get("trim_end", 0.0) or 0.0)
            usable = max(0.0, src_dur - trim_s - trim_e)
            if src_dur > 0 and usable > max_length_s:
                n_parts = int(usable // max_length_s) + (
                    1 if (usable % max_length_s) > 0.05 else 0)
                for k in range(n_parts):
                    off = trim_s + k * max_length_s
                    dur = min(max_length_s, max(0.0, src_dur - off - trim_e))
                    if dur > 0.05:
                        parts.append((off, dur))
        if not parts:
            parts = [(None, None)]  # single job, no clip override

        n_parts_total = len(parts)
        for part_no, (clip_off, clip_dur) in enumerate(parts, start=1):
            # Apply the user's filename pattern (V11). Same placeholder set
            # as the GUI; falls back to "_edited" suffix on a malformed
            # pattern.
            now = datetime.now()
            out_w = opts.get("out_w") or 0
            out_h = opts.get("out_h") or 0
            placeholders = {
                "name": sp.stem,
                "ext": sp.suffix.lstrip("."),
                "date": now.strftime("%Y%m%d"),
                "time": now.strftime("%H%M%S"),
                "codec": str(opts.get("encoder") or "").split("_")[0] or "h264",
                "encoder": opts.get("encoder", "auto"),
                "quality": (opts.get("speed_tier") or "Balanced")
                           .lower().replace(" ", "_"),
                "resolution": (f"{out_w}x{out_h}"
                               if out_w and out_h else "src"),
                "n": i + 1,
                "part": part_no,
                "parts": n_parts_total,
            }
            try:
                out_name = pattern.format_map(placeholders)
            except (KeyError, ValueError, IndexError):
                out_name = sp.stem + "_edited"
            # When splitting and the user's pattern doesn't already include
            # {part}, append `_PartN` so each slice gets a unique filename.
            if n_parts_total > 1 and "{part" not in pattern:
                # If pattern ends in .mp4, insert before extension.
                if out_name.lower().endswith(".mp4"):
                    out_name = out_name[:-4] + f"_Part{part_no}.mp4"
                else:
                    out_name = out_name + f"_Part{part_no}"
            out_name = out_name.replace("/", "_").replace("\\", "_")
            if not out_name.lower().endswith(".mp4"):
                out_name += ".mp4"
            if output_dir is not None:
                dst = output_dir / out_name
            else:
                dst = sp.with_name(out_name)
            # Two source files with the same stem (e.g. A/clip.mp4 and
            # B/clip.mp4) would otherwise both write to
            # <output-dir>/clip_edited.mp4, and the second silently
            # overwrites the first. Number the duplicates instead.
            if str(dst) in seen_dsts:
                base_stem = dst.stem
                n = 2
                while True:
                    cand = dst.with_name(f"{base_stem}_{n}{dst.suffix}")
                    if str(cand) not in seen_dsts:
                        dst = cand
                        break
                    n += 1
            if args.no_overwrite and dst.exists():
                print(f"SKIP: {dst.name} (already exists)")
                continue
            # Skip if src == dst (e.g. user asks to encode a file with empty
            # suffix back over itself).
            if Path(src).resolve() == Path(dst).resolve():
                print(f"SKIP: {sp.name} (would overwrite source)")
                continue
            seen_dsts.add(str(dst))
            per_job = None
            if clip_dur is not None:
                per_job = {"clip_offset_s": clip_off,
                           "clip_duration_s": clip_dur}
            # V12.3: same intro-on-Part1, outro-on-LastPart contract
            # as the GUI's _build_jobs uses.
            if n_parts_total > 1:
                if per_job is None:
                    per_job = {}
                per_job["apply_intro"] = (part_no == 1)
                per_job["apply_outro"] = (part_no == n_parts_total)
            jobs.append((next_job_idx, str(src), str(dst), kind,
                         v_path, v_kind, per_job))
            next_job_idx += 1

    # V11.5: persist the rotation counter so subsequent CLI runs of the
    # same profile pick up where this one left off.
    if rotation_key is not None and audio_seen > 0:
        settings.setValue(rotation_key, rotation_start + audio_seen)
        settings.sync()

    if audio_no_visual:
        print("ERROR: audio inputs need --visual <image|video>. Affected:",
              file=sys.stderr)
        for name in audio_no_visual[:10]:
            print(f"  {name}", file=sys.stderr)
        return 2

    if not jobs:
        print("Nothing to do. (All inputs were skipped.)")
        return 0

    parallel = (args.parallel
                if args.parallel is not None
                else int(profile_dict.get("parallel_jobs", 1)))
    parallel = max(1, min(2, parallel))

    print(f"Veloxa Video Editor V12.3 CLI - {len(jobs)} job(s), parallel={parallel}, "
          f"encoder={opts['encoder']}, codec={profile_dict.get('out_codec', 'h264')}, "
          f"speed={opts.get('speed', 1.0)}x, "
          f"loudnorm={'on' if opts.get('loudnorm') else 'off'}",
          flush=True)

    bm = BatchManager(jobs, parallel, ffmpeg, ffprobe, opts)

    state = {
        "started": time.monotonic(),
        "done": 0,
        "failed": 0,
        "last_pct": {},
    }
    total = len(jobs)

    def on_started(idx, path):
        n = state["done"] + state["failed"] + 1
        print(f"[{n}/{total}] START {Path(path).name}", flush=True)

    def on_progress(idx, pct):
        last = state["last_pct"].get(idx, -10)
        # Throttle to whole-percent steps to keep the log readable.
        if pct - last >= 5 or pct >= 100:
            state["last_pct"][idx] = pct
            print(f"  ... {idx}: {pct:5.1f}%", flush=True)

    def on_retrying(idx, attempt, last_err):
        print(f"  ... {idx}: retrying (attempt {attempt}) after: "
              f"{last_err[:120]}", flush=True)

    def on_finished(idx, ok, msg):
        if ok:
            state["done"] += 1
            n = state["done"] + state["failed"]
            dst = next((j[2] for j in jobs if j[0] == idx), "?")  # j[2] is dst whether tuple is 6- or 7-element
            try:
                size = os.path.getsize(dst) / 1_048_576
                size_str = f", {size:.1f} MB"
            except OSError:
                size_str = ""
            print(f"[{n}/{total}] DONE  {Path(dst).name}{size_str}",
                  flush=True)
        else:
            state["failed"] += 1
            n = state["done"] + state["failed"]
            print(f"[{n}/{total}] FAIL  job {idx}: {msg}", flush=True)

    def on_batch_end():
        elapsed = time.monotonic() - state["started"]
        print(
            f"\nBatch complete in {elapsed:.1f}s: "
            f"{state['done']} done, {state['failed']} failed.",
            flush=True)
        app.quit()

    bm.file_started.connect(on_started)
    bm.file_progress.connect(on_progress)
    bm.file_retrying.connect(on_retrying)
    bm.file_finished.connect(on_finished)
    bm.batch_finished.connect(on_batch_end)
    bm.start()

    app.exec()

    return 1 if state["failed"] > 0 else 0
