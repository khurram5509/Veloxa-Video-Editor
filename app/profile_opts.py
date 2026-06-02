"""Convert a profile dict (settings as stored on disk) to engine opts (the
shape ``BatchManager`` expects). Used by the CLI runner; the GUI still
builds opts directly from its widget values.
"""
from __future__ import annotations

import os

from engine import (
    AUTO_PRIORITY_H264, AUTO_PRIORITY_HEVC, CODEC_H264, CODEC_HEVC,
    ENCODER_FOR_CODEC, ENCODER_LABELS,
    # V12.3.1: quality tier resolution.
    VIDEO_QUALITY_TIERS, AUDIO_QUALITY_TIERS,
    VIDEO_QUALITY_DEFAULT, AUDIO_QUALITY_DEFAULT,
    resolve_video_bitrate_kbps, resolve_audio_bitrate_kbps,
    kbps_to_video_quality_tier, kbps_to_audio_quality_tier,
)


# Same table the GUI uses; duplicated here to avoid pulling in
# `app.main_window` (and therefore PyQt6 widgets) from the CLI.
RESOLUTIONS = {
    "Match Source": None,
    "720p (1280x720)": (1280, 720),
    "1080p (1920x1080)": (1920, 1080),
    "1440p (2560x1440)": (2560, 1440),
    "4K (3840x2160)": (3840, 2160),
}

AUTO_ENCODER = "(auto)"


def resolve_encoder(codec: str, encoder_label: str,
                    available_encoders: list) -> str:
    """Map a profile's stored encoder label to an actual encoder name."""
    priority = AUTO_PRIORITY_HEVC if codec == CODEC_HEVC else AUTO_PRIORITY_H264
    if encoder_label == AUTO_ENCODER or not encoder_label:
        for name in priority:
            if name in available_encoders:
                return name
        return "libx265" if codec == CODEC_HEVC else "libx264"

    encoders_for_codec = ENCODER_FOR_CODEC[codec]
    for name in encoders_for_codec:
        if name not in available_encoders:
            continue
        if ENCODER_LABELS.get(name, name) == encoder_label:
            return name
    # Fall back to CPU.
    return "libx265" if codec == CODEC_HEVC else "libx264"


def _resolve_video_kbps(p: dict, out_w: int, out_h: int) -> int:
    """V12.3.1: prefer the tier label if present; fall back to the saved
    integer ``video_bitrate_kbps`` for profiles written by V12.3 (the
    short-lived numeric-bitrate UI). 0 = "match source" sentinel kept
    only to preserve back-compat with V12.3 profiles.
    """
    tier = (p.get("video_quality") or "").strip()
    if tier in VIDEO_QUALITY_TIERS:
        return resolve_video_bitrate_kbps(tier, out_w, out_h)
    kbps = int(p.get("video_bitrate_kbps", 0) or 0)
    return kbps  # 0 means "use encoder CRF/CQP mode"


def _resolve_audio_kbps(p: dict) -> int:
    """V12.3.1: same as :func:`_resolve_video_kbps` but for audio."""
    tier = (p.get("audio_quality") or "").strip()
    if tier in AUDIO_QUALITY_TIERS:
        return resolve_audio_bitrate_kbps(tier)
    return int(p.get("audio_bitrate_kbps", 192) or 192)


def profile_to_opts(profile: dict, available_encoders: list) -> dict:
    """Translate a profile dict (output of ``_collect_settings_dict()``) into
    the engine opts dict (input to ``BatchManager``).
    """
    p = profile or {}
    res = RESOLUTIONS.get(p.get("out_res", "4K (3840x2160)"))
    out_w, out_h = (res if res else (0, 0))

    wm_path = p.get("wm_path", "") or ""
    watermark = wm_path if wm_path and os.path.exists(wm_path) else None
    vid_wm_path = p.get("vid_wm_path", "") or ""
    video_wm = vid_wm_path if vid_wm_path and os.path.exists(vid_wm_path) else None

    codec = p.get("out_codec", CODEC_H264)
    encoder = resolve_encoder(codec, p.get("out_encoder", AUTO_ENCODER),
                              available_encoders)

    return {
        "trim_start":       float(p.get("trim_start", 0.0)),
        "trim_end":         float(p.get("trim_end", 0.0)),
        "watermark_path":   watermark,
        "wm_preset":        p.get("wm_preset", "Bottom-Right"),
        "wm_offset_x":      int(p.get("wm_off_x", 0)),
        "wm_offset_y":      int(p.get("wm_off_y", 0)),
        "wm_padding":       int(p.get("wm_padding", 20)),
        "wm_opacity":       int(p.get("wm_opacity", 100)) / 100.0,
        "wm_scale":         int(p.get("wm_scale", 15)) / 100.0,
        "text_wm_text":     p.get("text_wm_text", "") or "",
        "text_wm_size":     int(p.get("text_wm_size", 36)),
        "text_wm_color":    p.get("text_wm_color", "#ffffff"),
        "text_wm_preset":   p.get("text_wm_preset", "Bottom-Left"),
        "text_wm_offset_x": int(p.get("text_wm_off_x", 0)),
        "text_wm_offset_y": int(p.get("text_wm_off_y", 0)),
        "text_wm_padding":  int(p.get("text_wm_padding", 20)),
        "text_wm_opacity":  int(p.get("text_wm_opacity", 100)) / 100.0,
        "out_w":            out_w,
        "out_h":            out_h,
        "encoder":          encoder,
        "speed_tier":       p.get("out_quality", "Balanced"),
        "force_stereo":     bool(p.get("force_stereo", True)),
        "loudnorm":         bool(p.get("loudnorm", False)),
        "speed":            float(p.get("speed", 1.0) or 1.0),
        # V11: pattern (with back-compat against pre-V11 "out_suffix").
        "out_pattern":      (p.get("out_pattern")
                             or "{name}" + (p.get("out_suffix", "_edited")
                                            or "_edited")),
        # V11: audio fades + hardware decode.
        "fade_in":          float(p.get("fade_in", 0.0) or 0.0),
        "fade_out":         float(p.get("fade_out", 0.0) or 0.0),
        "hw_decode":        bool(p.get("hw_decode", True)),
        # V11: split-on-length. ``max_length_s`` > 0 means: any input whose
        # post-trim duration exceeds it should be sliced into ceil(d / max)
        # parts, each named ``..._Part1``, ``..._Part2``, ``..._Part3``, etc.
        "split_enabled":    bool(p.get("split_enabled", False)),
        "max_length_s":     float(p.get("split_max_seconds")
                                  or (float(p.get("split_max_minutes", 0) or 0) * 60.0)),
        # V11.3: profile audio visuals + round-robin rotation.
        "profile_visuals_enabled": bool(p.get("profile_visuals_enabled", False)),
        "profile_visuals":  list(p.get("profile_visuals") or []),
        # V14.0: real-time audio-visual template (key, "none" = use the
        # image / video visual pipeline instead).
        "audio_template":   p.get("audio_template") or "none",
        # V12.3.1: profile carries a quality-tier *label* (Low / Medium
        # / High / Best / Super Best). Resolve to kbps here so the
        # engine sees the same int it expected before. Back-compat: if
        # the profile pre-dates V12.3.1 and only has a numeric
        # ``video_bitrate_kbps`` / ``audio_bitrate_kbps``, honour that
        # int directly so existing profiles keep producing the same
        # output bitrate they did before.
        "video_bitrate_kbps": _resolve_video_kbps(p, out_w, out_h),
        "audio_bitrate_kbps": _resolve_audio_kbps(p),
        "video_quality": p.get("video_quality") or "",
        "audio_quality": p.get("audio_quality") or "",
        # Optional concatenation of intro / outro clips around the
        # encoded main video. Empty string = not used. merge_audio_fade_s
        # > 0 enables an audio crossfade at each join.
        "intro_path":       (p.get("intro_path") or "") or "",
        "outro_path":       (p.get("outro_path") or "") or "",
        "merge_audio_fade_s": float(p.get("merge_audio_fade_s", 0.0) or 0.0),
        # Video watermark; engine probes its duration on demand from FFmpeg.
        "video_wm_path":    video_wm,
        "video_wm_duration": 0.0,
        "vid_wm_preset":    p.get("vid_wm_preset", "Top-Right"),
        "vid_wm_offset_x":  int(p.get("vid_wm_off_x", 0)),
        "vid_wm_offset_y":  int(p.get("vid_wm_off_y", 0)),
        "vid_wm_padding":   int(p.get("vid_wm_padding", 20)),
        "vid_wm_opacity":   int(p.get("vid_wm_opacity", 100)) / 100.0,
        "vid_wm_scale":     int(p.get("vid_wm_scale", 20)) / 100.0,
    }
