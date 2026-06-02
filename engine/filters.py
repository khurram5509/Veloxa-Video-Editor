"""FFmpeg filter-graph construction (watermark + scale + drawtext)."""
from __future__ import annotations

import os


# ---------------------------------------------------------------- text watermark

def _find_default_font() -> str:
    """First available common Windows bold font path, or ``''``."""
    for p in (
        r"C:/Windows/Fonts/arialbd.ttf",
        r"C:/Windows/Fonts/arial.ttf",
        r"C:/Windows/Fonts/segoeuib.ttf",
        r"C:/Windows/Fonts/seguisb.ttf",
        r"C:/Windows/Fonts/calibrib.ttf",
    ):
        if os.path.exists(p):
            return p
    return ""


def _drawtext_escape(s: str) -> str:
    """Escape a value for use inside a drawtext filter argument."""
    if not s:
        return ""
    out = s.replace("\\", "\\\\")
    out = out.replace(":", r"\:")
    out = out.replace("'", r"\'")
    out = out.replace("%", r"\%")
    return out


def _drawtext_path_escape(p: str) -> str:
    """Escape a Windows path for inside drawtext fontfile= value."""
    return p.replace("\\", "/").replace(":", r"\:")


def build_text_overlay(opts: dict) -> str:
    """Return a single ``drawtext=...`` segment, or '' if disabled."""
    text = (opts.get("text_wm_text") or "").strip()
    if not text:
        return ""
    size = int(opts.get("text_wm_size", 32))
    color = (opts.get("text_wm_color", "#ffffff") or "#ffffff").lstrip("#")
    if len(color) not in (6, 8):
        color = "ffffff"
    opacity = float(opts.get("text_wm_opacity", 1.0))
    preset = opts.get("text_wm_preset", "Bottom-Left")
    ox = int(opts.get("text_wm_offset_x", 0))
    oy = int(opts.get("text_wm_offset_y", 0))
    padding = int(opts.get("text_wm_padding", 20))

    if preset == "Top-Left":
        x = f"{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Top-Right":
        x = f"main_w-text_w-{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Bottom-Left":
        x = f"{padding}+({ox})"
        y = f"main_h-text_h-{padding}+({oy})"
    elif preset == "Bottom-Right":
        x = f"main_w-text_w-{padding}+({ox})"
        y = f"main_h-text_h-{padding}+({oy})"
    else:
        x = f"(main_w-text_w)/2+({ox})"
        y = f"(main_h-text_h)/2+({oy})"

    parts = [
        f"text='{_drawtext_escape(text)}'",
        f"fontsize={size}",
        f"fontcolor=0x{color}@{opacity:.3f}",
        f"shadowcolor=black@{min(0.85, opacity):.3f}",
        "shadowx=2", "shadowy=2",
        f"x={x}", f"y={y}",
    ]
    font = _find_default_font()
    if font:
        parts.insert(1, f"fontfile='{_drawtext_path_escape(font)}'")
    return "drawtext=" + ":".join(parts)


# ---------------------------------------------------------------- image WM helper

def _image_watermark_block(opts: dict, base_w: int, last: str,
                           wm_input_idx: int):
    """Construct the ``[N:v]format=rgba,...,scale[wm];[last][wm]overlay[v_wm]``
    pair for an image watermark. Returns ``(filter_parts, new_last)``."""
    opacity = float(opts["wm_opacity"])
    scale_pct = float(opts["wm_scale"])
    padding = int(opts["wm_padding"])
    preset = opts["wm_preset"]
    ox = int(opts["wm_offset_x"])
    oy = int(opts["wm_offset_y"])

    wm_target_w = max(2, int(base_w * scale_pct))

    if preset == "Top-Left":
        x = f"{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Top-Right":
        x = f"main_w-overlay_w-{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Bottom-Left":
        x = f"{padding}+({ox})"
        y = f"main_h-overlay_h-{padding}+({oy})"
    elif preset == "Bottom-Right":
        x = f"main_w-overlay_w-{padding}+({ox})"
        y = f"main_h-overlay_h-{padding}+({oy})"
    else:
        x = f"(main_w-overlay_w)/2+({ox})"
        y = f"(main_h-overlay_h)/2+({oy})"

    parts = [
        f"[{wm_input_idx}:v]format=rgba,colorchannelmixer=aa={opacity:.3f},"
        f"scale={wm_target_w}:-1[wm]",
        f"{last}[wm]overlay=x={x}:y={y}[v_wm]",
    ]
    return parts, "[v_wm]"


def _video_watermark_block(opts: dict, base_w: int, last: str,
                           wm_input_idx: int):
    """Like the image watermark block but for a video source.

    The video stream is expected to have been added to the FFmpeg command
    with ``-stream_loop -1`` so it loops as long as the main output runs;
    if the WM video is shorter than the output, it will repeat. The size
    slider, position presets, and opacity all work the same as for image
    watermarks.
    """
    opacity = float(opts.get("vid_wm_opacity", 1.0))
    scale_pct = float(opts.get("vid_wm_scale", 0.20))
    padding = int(opts.get("vid_wm_padding", 20))
    preset = opts.get("vid_wm_preset", "Top-Right")
    ox = int(opts.get("vid_wm_offset_x", 0))
    oy = int(opts.get("vid_wm_offset_y", 0))

    wm_target_w = max(2, int(base_w * scale_pct))

    if preset == "Top-Left":
        x = f"{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Top-Right":
        x = f"main_w-overlay_w-{padding}+({ox})"
        y = f"{padding}+({oy})"
    elif preset == "Bottom-Left":
        x = f"{padding}+({ox})"
        y = f"main_h-overlay_h-{padding}+({oy})"
    elif preset == "Bottom-Right":
        x = f"main_w-overlay_w-{padding}+({ox})"
        y = f"main_h-overlay_h-{padding}+({oy})"
    else:
        x = f"(main_w-overlay_w)/2+({ox})"
        y = f"(main_h-overlay_h)/2+({oy})"

    parts = [
        # Reset PTS to 0 so each loop starts fresh; format=rgba lets
        # colorchannelmixer apply a global opacity (alpha multiplier) even
        # when the source has no alpha channel.
        f"[{wm_input_idx}:v]format=rgba,colorchannelmixer=aa={opacity:.3f},"
        f"scale={wm_target_w}:-1,setpts=PTS-STARTPTS[vidwm]",
        # shortest=1 is critical when the WM is fed via -stream_loop -1:
        # without it, overlay's default longest-input behavior (longest =
        # infinite WM stream) keeps the encoder running forever even after
        # the main input ends.
        f"{last}[vidwm]overlay=x={x}:y={y}:shortest=1[v_vidwm]",
    ]
    return parts, "[v_vidwm]"


# ---------------------------------------------------------------- public builders

def build_filter(opts: dict, src_w: int, src_h: int,
                 for_preview: bool = False,
                 *,
                 image_wm_idx: int = None,
                 video_wm_idx: int = None):
    """Filter graph for VIDEO source.

    The caller adds inputs to the FFmpeg command and tells us where each
    watermark stream lives via ``image_wm_idx`` / ``video_wm_idx``. Pass
    ``None`` for any watermark not present in the inputs (regardless of what
    ``opts`` says) — that keeps the filter graph in sync with the actual
    command arguments.

    The size slider is ``% of video width`` — absolute pixel width is
    computed against the source frame width so the slider is meaningful
    regardless of the watermark image's natural size.
    """
    has_text_wm = bool((opts.get("text_wm_text") or "").strip())
    target_w = int(opts.get("out_w", 0) or 0)
    target_h = int(opts.get("out_h", 0) or 0)
    # V12.3.2 bugfix: emit a scale+pad step whenever ANY target W/H is
    # set, not only when source dims differ from target. The previous
    # ``src == target`` early-out meant a 1080x1920 portrait source
    # whose target was "1080p (1920x1080)" got encoded straight through
    # (because tuple-inequality fired but the encoder still saw 1080x1920
    # frames and ignored target_w/target_h), so the final container
    # ended up at 1080x1920 instead of the user's selected 1920x1080.
    # Always scaling — with force_original_aspect_ratio=decrease + pad —
    # guarantees the output frame size is EXACTLY (target_w x target_h)
    # while preserving aspect ratio (letterbox / pillarbox black bars).
    do_scale = (not for_preview
                and target_w > 0 and target_h > 0)
    speed = float(opts.get("speed", 1.0) or 1.0)
    # Skip setpts in preview — preview is a single frame, timestamps are
    # irrelevant for it and adding setpts confuses the renderer.
    do_speed = not for_preview and abs(speed - 1.0) > 1e-3

    parts = []
    last = "[0:v]"

    if do_speed:
        # setpts adjusts presentation timestamps. ``PTS/SPEED`` is the
        # canonical form (divides original PTS by the speed factor).
        parts.append(f"{last}setpts=PTS/{speed:.4f}[vspd]")
        last = "[vspd]"

    base_w = src_w if src_w > 0 else 1920

    if image_wm_idx is not None:
        block, last = _image_watermark_block(opts, base_w, last,
                                             wm_input_idx=image_wm_idx)
        parts.extend(block)

    if video_wm_idx is not None:
        block, last = _video_watermark_block(opts, base_w, last,
                                             wm_input_idx=video_wm_idx)
        parts.extend(block)

    if has_text_wm:
        text = build_text_overlay(opts)
        if text:
            parts.append(f"{last}{text}[v_text]")
            last = "[v_text]"

    if do_scale:
        # V12.3.2: aspect-ratio-preserving scale + pad. The output frame
        # is always exactly target_w x target_h. If the source aspect
        # ratio differs from the target's, the content is letterboxed
        # (or pillarboxed) with black bars instead of being stretched.
        # setsar=1 forces square pixels so video players show the file
        # at the actual pixel dims (some containers carry a non-1 SAR
        # which can make a 1920x1080 file display as 2880x1080 etc.).
        parts.append(
            f"{last}scale={target_w}:{target_h}:"
            f"force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1[vout]"
        )
        last = "[vout]"

    if for_preview:
        parts.append(f"{last}scale='min(1280,iw)':-2[prev]")
        last = "[prev]"

    return ";".join(parts), last


def build_audio_filter(opts: dict, target_w: int, target_h: int,
                       for_preview: bool = False,
                       *,
                       image_wm_idx: int = None,
                       video_wm_idx: int = None,
                       visual_pre_scaled: bool = False):
    """Filter graph for AUDIO + visual (image OR video) source.

    Inputs (consistent at preview and encode time): ``[0:v]`` is the visual,
    ``[1]`` is audio (real audio at encode, lavfi anullsrc at preview),
    plus optional image / video watermark inputs at ``image_wm_idx`` /
    ``video_wm_idx`` (typically 2 / 3 depending on what's present).

    V12.3.5 perf: ``visual_pre_scaled=True`` skips the per-frame
    ``scale+pad`` step on the visual. The caller (engine ``JobRunner``)
    sets this when it has already produced a target-sized PNG via a
    one-shot pre-pass, eliminating ~N frames worth of CPU filtering for
    a 25fps N-second-long audio job. Huge win for image visuals where
    scale+pad would otherwise run identically for every output frame.
    """
    has_text_wm = bool((opts.get("text_wm_text") or "").strip())
    if target_w <= 0 or target_h <= 0:
        target_w, target_h = 1920, 1080

    if visual_pre_scaled and not for_preview:
        # The caller guarantees [0:v] is already at target_w x target_h
        # with square pixels. Just rename the stream label.
        parts = [f"[0:v]setsar=1[bg]"]
    else:
        parts = [
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1[bg]"
        ]
    last = "[bg]"

    speed = float(opts.get("speed", 1.0) or 1.0)
    if not for_preview and abs(speed - 1.0) > 1e-3:
        # Match the visual to the audio's atempo: with -shortest cutting the
        # output at the (time-stretched) audio end, this makes a video visual
        # play through faster/slower instead of getting truncated mid-loop.
        # On a still image setpts is a harmless no-op.
        parts.append(f"{last}setpts=PTS/{speed:.4f}[vspd]")
        last = "[vspd]"

    if image_wm_idx is not None:
        # Canvas is the padded image at target_w; size slider is "% of width".
        block, last = _image_watermark_block(opts, target_w, last,
                                             wm_input_idx=image_wm_idx)
        parts.extend(block)

    if video_wm_idx is not None:
        block, last = _video_watermark_block(opts, target_w, last,
                                             wm_input_idx=video_wm_idx)
        parts.extend(block)

    if has_text_wm:
        text = build_text_overlay(opts)
        if text:
            parts.append(f"{last}{text}[v_text]")
            last = "[v_text]"

    if for_preview:
        parts.append(f"{last}scale='min(1280,iw)':-2[prev]")
        last = "[prev]"

    return ";".join(parts), last
