"""Veloxa Video Editor encoding engine.

Pure logic — no UI dependencies beyond `PyQt6.QtCore` (used only for the Qt
signal/slot model on `BatchManager` and `JobRunner`). All FFmpeg interaction,
encoder detection, filter-graph construction, and bulk job orchestration
live here.
"""

from .ffmpeg import (
    find_ffmpeg,
    probe_duration,
    probe_resolution,
    probe_has_audio,
    cached_probe_duration,
    cached_probe_resolution,
    clear_probe_cache,
    generate_preview,
    generate_visual_preview,
)
from .encoders import (
    CPU_ENCODERS,
    GPU_H264,
    GPU_HEVC,
    AUTO_PRIORITY_H264,
    AUTO_PRIORITY_HEVC,
    SPEED_TIERS,
    CODEC_H264,
    CODEC_HEVC,
    ENCODER_LABELS,
    ENCODER_FOR_CODEC,
    detect_available_encoders,
    encoder_codec_args,
    audio_codec_args,
    hwaccel_for_encoder,
    # V12.3.1: quality-tier dropdowns
    VIDEO_QUALITY_TIERS,
    AUDIO_QUALITY_TIERS,
    VIDEO_QUALITY_DEFAULT,
    AUDIO_QUALITY_DEFAULT,
    VIDEO_QUALITY_BITRATE_KBPS,
    AUDIO_QUALITY_BITRATE_KBPS,
    resolve_video_bitrate_kbps,
    resolve_audio_bitrate_kbps,
    kbps_to_video_quality_tier,
    kbps_to_audio_quality_tier,
)
from .filters import build_filter, build_audio_filter
from .batch import JobRunner, BatchManager

__all__ = [
    # FFmpeg I/O
    "find_ffmpeg", "probe_duration", "probe_resolution", "probe_has_audio",
    "cached_probe_duration", "cached_probe_resolution", "clear_probe_cache",
    "generate_preview", "generate_visual_preview",
    # Encoders
    "CPU_ENCODERS", "GPU_H264", "GPU_HEVC",
    "AUTO_PRIORITY_H264", "AUTO_PRIORITY_HEVC", "SPEED_TIERS",
    "CODEC_H264", "CODEC_HEVC", "ENCODER_LABELS", "ENCODER_FOR_CODEC",
    "detect_available_encoders", "encoder_codec_args", "audio_codec_args",
    "VIDEO_QUALITY_TIERS", "AUDIO_QUALITY_TIERS",
    "VIDEO_QUALITY_DEFAULT", "AUDIO_QUALITY_DEFAULT",
    "VIDEO_QUALITY_BITRATE_KBPS", "AUDIO_QUALITY_BITRATE_KBPS",
    "resolve_video_bitrate_kbps", "resolve_audio_bitrate_kbps",
    "kbps_to_video_quality_tier", "kbps_to_audio_quality_tier",
    # Filters
    "build_filter", "build_audio_filter",
    # Batch orchestration
    "JobRunner", "BatchManager",
]
