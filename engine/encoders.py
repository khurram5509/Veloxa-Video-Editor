"""Encoder catalogue, runtime detection (cached), and codec/audio CLI args."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path

from .ffmpeg import CREATE_NO_WINDOW


# ---------------------------------------------------------------- catalogue

CPU_ENCODERS = ["libx264", "libx265"]
GPU_H264 = ["h264_nvenc", "h264_qsv", "h264_amf"]
GPU_HEVC = ["hevc_nvenc", "hevc_qsv", "hevc_amf"]
GPU_ENCODERS_TO_TEST = GPU_H264 + GPU_HEVC

CODEC_H264 = "h264"
CODEC_HEVC = "hevc"

ENCODER_FOR_CODEC = {
    CODEC_H264: ["libx264"] + GPU_H264,
    CODEC_HEVC: ["libx265"] + GPU_HEVC,
}

ENCODER_LABELS = {
    "libx264":    "CPU (x264)",
    "libx265":    "CPU (x265)",
    "h264_nvenc": "NVIDIA NVENC",
    "hevc_nvenc": "NVIDIA NVENC",
    "h264_qsv":   "Intel QSV",
    "hevc_qsv":   "Intel QSV",
    "h264_amf":   "AMD AMF",
    "hevc_amf":   "AMD AMF",
}

# Discrete GPU first, then iGPU, then CPU.
AUTO_PRIORITY_H264 = ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"]
AUTO_PRIORITY_HEVC = ["hevc_nvenc", "hevc_amf", "hevc_qsv", "libx265"]

SPEED_TIERS = ["Fast", "Balanced", "High Quality"]


# ---------------------------------------------------------------- V12.3.1: quality tiers
# The GUI exposes video / audio quality as a five-tier dropdown instead
# of raw kbps numbers — easier to pick the right value, harder to mis-type.
# These tables resolve a (tier, resolution) selection to an actual bitrate
# that gets handed to the encoder via the existing ``video_bitrate_kbps`` /
# ``audio_bitrate_kbps`` opts.

VIDEO_QUALITY_TIERS = ["Low", "Medium", "High", "Best", "Super Best"]
AUDIO_QUALITY_TIERS = ["Low", "Medium", "High", "Best", "Super Best"]

VIDEO_QUALITY_DEFAULT = "Best"
AUDIO_QUALITY_DEFAULT = "Best"

# bucket key = nominal vertical resolution; lookup picks the closest one.
VIDEO_QUALITY_BITRATE_KBPS = {
    "Low":        {720: 1500,  1080: 3000,  1440: 6000,  2160: 15000},
    "Medium":     {720: 2500,  1080: 5000,  1440: 10000, 2160: 25000},
    "High":       {720: 4000,  1080: 8000,  1440: 15000, 2160: 40000},
    "Best":       {720: 6000,  1080: 12000, 1440: 25000, 2160: 60000},
    "Super Best": {720: 10000, 1080: 20000, 1440: 40000, 2160: 90000},
}

AUDIO_QUALITY_BITRATE_KBPS = {
    "Low":         96,
    "Medium":      128,
    "High":        192,
    "Best":        256,
    "Super Best":  320,
}


def resolve_video_bitrate_kbps(tier: str, out_w: int, out_h: int) -> int:
    """Return the target video bitrate (kbps) for a quality tier at a
    given output resolution. ``out_w`` / ``out_h`` <= 0 (i.e. "Match
    Source" with unknown source size) falls back to the 1080p column.
    Unknown tier falls back to ``VIDEO_QUALITY_DEFAULT``.
    """
    table = VIDEO_QUALITY_BITRATE_KBPS.get(
        tier, VIDEO_QUALITY_BITRATE_KBPS[VIDEO_QUALITY_DEFAULT])
    if out_w <= 0 or out_h <= 0:
        return table[1080]
    # Pick the bucket whose pixel count the output is closest to.
    pixels = out_w * out_h
    buckets = (
        (1280 * 720,   720),
        (1920 * 1080,  1080),
        (2560 * 1440,  1440),
        (3840 * 2160,  2160),
    )
    closest = min(buckets, key=lambda b: abs(b[0] - pixels))
    return table[closest[1]]


def resolve_audio_bitrate_kbps(tier: str) -> int:
    """Return the AAC target bitrate (kbps) for an audio quality tier.
    Unknown tier falls back to ``AUDIO_QUALITY_DEFAULT``."""
    return AUDIO_QUALITY_BITRATE_KBPS.get(
        tier, AUDIO_QUALITY_BITRATE_KBPS[AUDIO_QUALITY_DEFAULT])


def kbps_to_video_quality_tier(kbps: int, out_w: int = 1920,
                               out_h: int = 1080) -> str:
    """Back-compat helper: a profile saved under the old numeric-bitrate
    UI carries ``video_bitrate_kbps`` as an int. Map it to the nearest
    tier so loading the profile selects something sensible in the new
    dropdown.

    ``kbps == 0`` (the old "match source" sentinel) maps to the default
    tier. Otherwise: pick the tier whose target-bitrate-for-resolution
    is closest to the saved value.
    """
    if not kbps or int(kbps) <= 0:
        return VIDEO_QUALITY_DEFAULT
    target = int(kbps)
    closest = min(
        VIDEO_QUALITY_TIERS,
        key=lambda t: abs(resolve_video_bitrate_kbps(t, out_w, out_h) - target),
    )
    return closest


def kbps_to_audio_quality_tier(kbps: int) -> str:
    """Back-compat for audio_bitrate_kbps -> tier label."""
    if not kbps or int(kbps) <= 0:
        return AUDIO_QUALITY_DEFAULT
    target = int(kbps)
    return min(AUDIO_QUALITY_TIERS,
               key=lambda t: abs(AUDIO_QUALITY_BITRATE_KBPS[t] - target))

ENCODER_PRESETS = {
    "libx264":    {"Fast": "fast",   "Balanced": "medium",   "High Quality": "slow"},
    "libx265":    {"Fast": "fast",   "Balanced": "medium",   "High Quality": "slow"},
    "h264_nvenc": {"Fast": "p3",     "Balanced": "p5",       "High Quality": "p7"},
    "hevc_nvenc": {"Fast": "p3",     "Balanced": "p5",       "High Quality": "p7"},
    "h264_qsv":   {"Fast": "faster", "Balanced": "medium",   "High Quality": "slower"},
    "hevc_qsv":   {"Fast": "faster", "Balanced": "medium",   "High Quality": "slower"},
    "h264_amf":   {"Fast": "speed",  "Balanced": "balanced", "High Quality": "quality"},
    "hevc_amf":   {"Fast": "speed",  "Balanced": "balanced", "High Quality": "quality"},
}


# ---------------------------------------------------------------- detection cache

# Bumped any time the detection probe changes (resolution, args, etc.) so
# poisoned caches from earlier builds are ignored automatically.
# V14.4.1: schema bumped to 3 — cache key now includes a machine ID
# (hostname + MAC) so a cache that travels with a synced %APPDATA% / OneDrive
# / roaming-profile setup won't apply on a different physical PC. Without
# this, a user with NVENC detected on their workstation would inherit
# h264_nvenc as "available" on their AMD laptop, then watch every encode
# fail with "Cannot load nvcuda.dll". V3 caches that ship with V14.4.1+
# are ignored on a different PC because the machine ID won't match.
ENCODER_CACHE_SCHEMA = 3


def _machine_id() -> str:
    """V14.4.1: short stable ID for the physical machine running the app.

    Combines the OS hostname and the first MAC address (via ``uuid.getnode``)
    and hashes the result so the on-disk cache file doesn't expose either
    raw. Same physical PC → same ID. A different PC → a different ID, so
    a cache that travelled along with a synced ``%APPDATA%`` is invalidated.
    """
    bits = []
    try:
        bits.append(platform.node() or "")
    except Exception:
        pass
    try:
        # uuid.getnode() returns the MAC of the first NIC, or a random
        # 48-bit int if it can't read one. Either is fine — both are
        # stable per boot on a given machine.
        bits.append(f"{uuid.getnode():012x}")
    except Exception:
        pass
    raw = "|".join(bits) or "unknown-machine"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _cache_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "Veloxa-VD"
    d.mkdir(parents=True, exist_ok=True)
    return d / "encoder_cache.json"


def _ffmpeg_version(ffmpeg: str) -> str:
    try:
        r = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True,
                           timeout=10, creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            return r.stdout.split("\n", 1)[0].strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _test_encoder(ffmpeg: str, name: str) -> bool:
    """Probe whether ``name`` can actually run on this system.

    320x240 clears NVENC's ~146x96 (H.264) / ~132x96 (HEVC) minimum sizes —
    smaller probes spuriously fail with ``Frame Dimension less than the
    minimum supported value``.
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=black:s=320x240:r=1:d=0.5",
           "-c:v", name, "-frames:v", "1", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def detect_available_encoders(ffmpeg: str, force_rescan: bool = False):
    """Return an ordered list of encoder names that work on this system.

    GPU encoders (NVENC / QSV / AMF on Windows, VideoToolbox on macOS) are
    probed by running a real FFmpeg encode at 320×240 against each
    candidate. Anything that returns exit code 0 is added to the list;
    everything else is dropped. CPU encoders (libx264 / libx265) always
    work and lead the list.

    Cached at ``%APPDATA%\\Veloxa-VD\\encoder_cache.json`` so repeat
    launches are instant. The cache key is the FFmpeg version string
    PLUS a machine ID (V14.4.1+) so a cache that travels with a
    synced %APPDATA% or OneDrive setup is automatically invalidated
    on a different physical PC.

    ``force_rescan=True`` ignores the cache and writes a fresh result —
    use this when the user clicks "Re-detect GPU encoders" or when the
    GPU has changed on the same physical machine.
    """
    if not ffmpeg:
        return list(CPU_ENCODERS)

    version = _ffmpeg_version(ffmpeg)
    machine = _machine_id()
    cache_file = _cache_path()
    if version and not force_rescan:
        try:
            if cache_file.exists():
                data = json.loads(cache_file.read_text())
                if (data.get("version") == version
                        and data.get("machine") == machine
                        and data.get("schema") == ENCODER_CACHE_SCHEMA):
                    encoders = data.get("encoders")
                    if isinstance(encoders, list) and encoders:
                        return encoders
        except Exception:
            pass

    available = list(CPU_ENCODERS)
    for name in GPU_ENCODERS_TO_TEST:
        if _test_encoder(ffmpeg, name):
            available.append(name)

    if version:
        try:
            cache_file.write_text(json.dumps({
                "version": version,
                "machine": machine,
                "schema": ENCODER_CACHE_SCHEMA,
                "encoders": available,
            }))
        except Exception:
            pass

    return available


# ---------------------------------------------------------------- args

def encoder_codec_args(encoder: str, speed_tier: str,
                       video_bitrate_kbps: int = 0):
    """Return the ``-c:v`` + quality args for the chosen encoder + tier.

    V12.3: ``video_bitrate_kbps`` (0 = "match source", i.e. use the
    encoder's CRF / CQP quality mode which approximates the source's
    visual quality without targeting a specific file size). When > 0,
    switches the encoder into target-bitrate mode and emits ``-b:v Nk``
    instead of the quality-based knobs.
    """
    preset = ENCODER_PRESETS.get(encoder, {}).get(speed_tier)
    use_bitrate = bool(video_bitrate_kbps and int(video_bitrate_kbps) > 0)
    br = f"{int(video_bitrate_kbps)}k" if use_bitrate else None

    if encoder == "libx264":
        if use_bitrate:
            return ["-c:v", "libx264", "-b:v", br,
                    "-preset", preset or "medium", "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-crf", "18",
                "-preset", preset or "medium", "-pix_fmt", "yuv420p"]
    if encoder == "libx265":
        if use_bitrate:
            return ["-c:v", "libx265", "-b:v", br,
                    "-preset", preset or "medium", "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx265", "-crf", "22",
                "-preset", preset or "medium", "-pix_fmt", "yuv420p"]
    if encoder == "h264_nvenc":
        if use_bitrate:
            return ["-c:v", "h264_nvenc", "-rc", "vbr",
                    "-b:v", br, "-maxrate", br,
                    "-preset", preset or "p5", "-pix_fmt", "yuv420p"]
        return ["-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "20",
                "-preset", preset or "p5", "-pix_fmt", "yuv420p"]
    if encoder == "hevc_nvenc":
        if use_bitrate:
            return ["-c:v", "hevc_nvenc", "-rc", "vbr",
                    "-b:v", br, "-maxrate", br,
                    "-preset", preset or "p5", "-pix_fmt", "yuv420p"]
        return ["-c:v", "hevc_nvenc", "-rc", "constqp", "-qp", "22",
                "-preset", preset or "p5", "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        if use_bitrate:
            return ["-c:v", "h264_qsv", "-b:v", br,
                    "-preset", preset or "medium", "-pix_fmt", "nv12"]
        return ["-c:v", "h264_qsv", "-global_quality", "22",
                "-preset", preset or "medium", "-pix_fmt", "nv12"]
    if encoder == "hevc_qsv":
        if use_bitrate:
            return ["-c:v", "hevc_qsv", "-b:v", br,
                    "-preset", preset or "medium", "-pix_fmt", "nv12"]
        return ["-c:v", "hevc_qsv", "-global_quality", "24",
                "-preset", preset or "medium", "-pix_fmt", "nv12"]
    if encoder == "h264_amf":
        if use_bitrate:
            return ["-c:v", "h264_amf", "-quality", preset or "balanced",
                    "-rc", "vbr_peak", "-b:v", br, "-maxrate", br,
                    "-pix_fmt", "yuv420p"]
        return ["-c:v", "h264_amf", "-quality", preset or "balanced",
                "-rc", "cqp", "-qp_i", "22", "-qp_p", "24", "-pix_fmt", "yuv420p"]
    if encoder == "hevc_amf":
        if use_bitrate:
            return ["-c:v", "hevc_amf", "-quality", preset or "balanced",
                    "-rc", "vbr_peak", "-b:v", br, "-maxrate", br,
                    "-pix_fmt", "yuv420p"]
        return ["-c:v", "hevc_amf", "-quality", preset or "balanced",
                "-rc", "cqp", "-qp_i", "24", "-qp_p", "26", "-pix_fmt", "yuv420p"]
    raise ValueError(f"Unknown encoder: {encoder}")


def _atempo_chain(speed: float) -> str:
    """``atempo`` only accepts [0.5, 100.0] in a single instance. To support
    speeds outside that, chain multiple atempo filters whose product equals
    the target speed (e.g. 4.0 -> ``atempo=2.0,atempo=2.0``).
    """
    if speed <= 0:
        return ""
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def audio_filter_chain(opts: dict, output_duration_s: float = 0.0) -> str:
    """Combined ``-af`` chain: loudnorm + atempo + fade-in / fade-out.

    ``output_duration_s`` is the post-trim post-speed audio length, used
    to place the fade-out at ``duration - fade_out``. Pass 0 to skip the
    fade-out even if it's requested.
    """
    parts = []
    if opts.get("loudnorm", False):
        # EBU R128 single-pass at a streaming/podcast loudness target.
        parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    speed = float(opts.get("speed", 1.0) or 1.0)
    if abs(speed - 1.0) > 1e-3:
        chain = _atempo_chain(speed)
        if chain:
            parts.append(chain)

    # Fades land AFTER atempo so the start time is in output-time.
    fade_in = float(opts.get("fade_in", 0.0) or 0.0)
    fade_out = float(opts.get("fade_out", 0.0) or 0.0)
    if fade_in > 0:
        parts.append(f"afade=in:st=0:d={fade_in:.3f}")
    if fade_out > 0 and output_duration_s > fade_out:
        st = output_duration_s - fade_out
        parts.append(f"afade=out:st={st:.3f}:d={fade_out:.3f}")

    return ",".join(parts)


def audio_codec_args(opts: dict, output_duration_s: float = 0.0):
    """Return audio output args: optional ``-af`` (loudnorm + atempo +
    fades), AAC encoder, optional ``-ac 2`` (force stereo upmix).

    V12.3: ``audio_bitrate_kbps`` opt (default 192) controls the AAC
    target bitrate. Clamped to [32, 512] kbps to keep ffmpeg happy.
    """
    args = []
    chain = audio_filter_chain(opts, output_duration_s)
    if chain:
        args += ["-af", chain]
    try:
        ab = int(opts.get("audio_bitrate_kbps", 192) or 192)
    except (TypeError, ValueError):
        ab = 192
    ab = max(32, min(512, ab))
    args += ["-c:a", "aac", "-b:a", f"{ab}k"]
    if opts.get("force_stereo", True):
        args += ["-ac", "2"]
    return args


def hwaccel_for_encoder(encoder: str) -> str:
    """Match the right ``-hwaccel`` mode to the chosen encoder so decode
    runs on the same hardware that does the encode (avoids round-tripping
    frames through system memory). Empty string = no hwaccel.
    """
    if not encoder:
        return ""
    if "nvenc" in encoder:
        return "cuda"
    if "qsv" in encoder:
        return "qsv"
    if "amf" in encoder:
        return "d3d11va"
    return ""
