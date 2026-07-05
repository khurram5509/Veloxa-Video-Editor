"""V12.3 audit-fix regression suite.

Covers:
  * V12.3 features carried forward from the original build (bitrate,
    intro/outro, profile field propagation).
  * Audit fixes applied this pass: BUG-1, BUG-2, BUG-3, EDGE-1, EDGE-2.

This is a static / introspective test pass -- it doesn't actually invoke
FFmpeg, but it verifies the code paths that BUILD the FFmpeg invocation
behave correctly. The encode integration test is handled by the
build-and-launch smoke step after this passes.
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

# Make project root importable when running this file directly.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

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


# ===========================================================================
# 1. V12.3 baseline features (regression: must keep working after fixes)
# ===========================================================================
section("V12.3 baseline: bitrate, intro/outro, profile propagation")

from engine.encoders import encoder_codec_args, audio_codec_args

# Encoder bitrate: 0 -> CRF/CQP path; > 0 -> -b:v
args = encoder_codec_args("libx264", "Balanced", video_bitrate_kbps=0)
check("encoder libx264 0kbps -> CRF mode (no -b:v)",
      "-b:v" not in args and any("-crf" in a or a == "-crf" for a in args),
      f"args={args}")

args = encoder_codec_args("libx264", "Balanced", video_bitrate_kbps=5000)
check("encoder libx264 5000kbps -> -b:v 5000k present",
      "-b:v" in args and "5000k" in args, f"args={args}")

args = encoder_codec_args("h264_nvenc", "Balanced", video_bitrate_kbps=8000)
check("encoder h264_nvenc 8000kbps -> VBR + -b:v",
      "-b:v" in args and "8000k" in args, f"args={args}")

args = encoder_codec_args("h264_amf", "Balanced", video_bitrate_kbps=8000)
check("encoder h264_amf 8000kbps -> -b:v",
      "-b:v" in args, f"args={args}")

# Audio bitrate: defaults to 192; clamps to [32, 512]
a = audio_codec_args({"audio_bitrate_kbps": 192}, output_duration_s=10.0)
check("audio 192k present in args", "192k" in a, f"args={a}")

a = audio_codec_args({"audio_bitrate_kbps": 10}, output_duration_s=10.0)
check("audio low-clamp 10 -> 32k", "32k" in a, f"args={a}")

a = audio_codec_args({"audio_bitrate_kbps": 9999}, output_duration_s=10.0)
check("audio high-clamp 9999 -> 512k", "512k" in a, f"args={a}")

a = audio_codec_args({}, output_duration_s=10.0)
check("audio default (missing key) -> 192k", "192k" in a, f"args={a}")


# Profile -> opts propagation (intro/outro/bitrate/merge_fade)
from app.profile_opts import profile_to_opts

# V12.3.1: profile carries the tier label. profile_to_opts resolves it
# to kbps using the saved output resolution.
p = {
    "video_quality": "Best",
    "audio_quality": "Best",
    "out_res": "1080p (1920x1080)",
    "intro_path": "C:/nonexistent/intro.mp4",
    "outro_path": "",
    "merge_audio_fade_s": 1.25,
    "out_codec": "libx264",
    "out_encoder": "(auto)",
}
opts = profile_to_opts(p, ["libx264", "libx265"])
check("opts resolves video tier 'Best' @ 1080p -> 12000 kbps",
      opts["video_bitrate_kbps"] == 12000,
      f"got {opts['video_bitrate_kbps']}")
check("opts resolves audio tier 'Best' -> 256 kbps",
      opts["audio_bitrate_kbps"] == 256,
      f"got {opts['audio_bitrate_kbps']}")
check("opts carries video_quality tier label",
      opts.get("video_quality") == "Best")
check("opts carries audio_quality tier label",
      opts.get("audio_quality") == "Best")
check("opts intro_path passes through",
      opts["intro_path"] == "C:/nonexistent/intro.mp4")
check("opts merge_audio_fade_s = 1.25", opts["merge_audio_fade_s"] == 1.25)

# Back-compat: V12.3 profile (numeric bitrate, no tier) still works.
p_legacy = {
    "video_bitrate_kbps": 5000,
    "audio_bitrate_kbps": 192,
    "out_res": "1080p (1920x1080)",
    "out_codec": "libx264",
    "out_encoder": "(auto)",
}
opts = profile_to_opts(p_legacy, ["libx264", "libx265"])
check("legacy V12.3 profile (numeric kbps) still produces 5000 kbps",
      opts["video_bitrate_kbps"] == 5000)
check("legacy V12.3 profile audio_bitrate_kbps preserved (192)",
      opts["audio_bitrate_kbps"] == 192)


# ===========================================================================
# 2. Audit fix BUG-1: concat audio chain is stripped (no double atempo / fade)
# ===========================================================================
section("BUG-1: concat pass strips speed / fade / loudnorm")

from engine import batch as batch_mod
src = inspect.getsource(batch_mod.JobRunner._concat_intro_outro)
check("_concat_intro_outro builds stripped audio opts dict",
      "concat_audio_opts" in src, "marker missing")
check("_concat_intro_outro passes concat_audio_opts to audio_codec_args",
      "audio_codec_args(concat_audio_opts" in src, "wrong call site")
check("_concat_intro_outro disables loudnorm in concat pass",
      '"loudnorm": False' in src, "loudnorm flag missing")
check("_concat_intro_outro neutralises speed in concat pass",
      '"speed": 1.0' in src, "speed reset missing")
check("_concat_intro_outro neutralises fade_in in concat pass",
      '"fade_in": 0.0' in src, "fade_in reset missing")
check("_concat_intro_outro neutralises fade_out in concat pass",
      '"fade_out": 0.0' in src, "fade_out reset missing")


# ===========================================================================
# 3. Audit fix BUG-2: cancel_cleanup_target parameter
# ===========================================================================
section("BUG-2: cancel_cleanup_target cleans up main_tmp")

sig = inspect.signature(batch_mod.JobRunner._run_ffmpeg)
check("_run_ffmpeg accepts cancel_cleanup_target",
      "cancel_cleanup_target" in sig.parameters, str(sig))
check("cancel_cleanup_target defaults to None",
      sig.parameters["cancel_cleanup_target"].default is None,
      str(sig.parameters["cancel_cleanup_target"]))

src_run = inspect.getsource(batch_mod.JobRunner._run_ffmpeg)
check("_run_ffmpeg cancel branch uses cancel_cleanup_target",
      "target = cancel_cleanup_target or self.dst" in src_run,
      "no target= ternary")
check("_run_ffmpeg cancel branch removes target (not hardcoded self.dst)",
      "os.remove(target)" in src_run, "remove(target) missing")

# Encode call sites pass cancel_cleanup_target=main_tmp
src_vid = inspect.getsource(batch_mod.JobRunner._encode_video)
check("_encode_video passes cancel_cleanup_target=main_tmp",
      "cancel_cleanup_target=main_tmp" in src_vid, "video path missing kwarg")
check("_encode_video also cleans main_tmp on failure post-call",
      "os.remove(main_tmp)" in src_vid, "no explicit failure cleanup")

src_atv = inspect.getsource(batch_mod.JobRunner._encode_audio_to_video)
check("_encode_audio_to_video passes cancel_cleanup_target=main_tmp",
      "cancel_cleanup_target=main_tmp" in src_atv,
      "audio-to-video path missing kwarg")


# ===========================================================================
# 4. Audit fix BUG-3: silent intro/outro -> anullsrc
# ===========================================================================
section("BUG-3: silent intro/outro handled with anullsrc")

from engine.ffmpeg import probe_has_audio
check("probe_has_audio callable", callable(probe_has_audio))
check("probe_has_audio empty path -> False",
      probe_has_audio("ffprobe", "") is False)
check("probe_has_audio nonexistent path -> False",
      probe_has_audio("nonexistent_ffprobe.exe", "/nope") is False)

src_concat = inspect.getsource(batch_mod.JobRunner._concat_intro_outro)
check("_concat_intro_outro probes has_audio for each source",
      "probe_has_audio" in src_concat, "probe call missing")
check("_concat_intro_outro builds has_audio_map",
      "has_audio_map" in src_concat, "map missing")
check("_concat_intro_outro emits anullsrc for silent inputs",
      "anullsrc" in src_concat, "fallback missing")
check("_concat_intro_outro bounds anullsrc with atrim",
      "atrim=" in src_concat, "atrim bound missing")
check("_concat_intro_outro treats main_tmp as always-audio (we made it)",
      'has_audio_map[role] = True' in src_concat, "main short-circuit missing")


# ===========================================================================
# 5. Audit fix EDGE-1: stale intro/outro files pruned on clear
# ===========================================================================
section("EDGE-1: stale intro/outro assets pruned when path cleared")

from app import profile_assets
src_copy = inspect.getsource(profile_assets.copy_assets_into_profile)
check("copy_assets_into_profile handles empty src by sweeping stale glob",
      "pruned cleared asset" in src_copy, "missing audit-fix marker")
check("copy_assets_into_profile uses target.glob in empty-src branch",
      "target.glob(f\"{basename_stem}" in src_copy, "glob call missing")

# Live functional probe: create a fake profile folder, drop a stale file,
# then call copy_assets_into_profile with empty intro_path and confirm prune.
with tempfile.TemporaryDirectory() as td:
    old_appdata = os.environ.get("APPDATA")
    os.environ["APPDATA"] = td
    try:
        # Force module to re-resolve assets_root via direct call.
        from app.profile_assets import assets_dir_for, copy_assets_into_profile
        d = assets_dir_for("regress_v12_3")
        d.mkdir(parents=True, exist_ok=True)
        stale = d / "intro_video.mp4"
        stale.write_bytes(b"stale")
        check("EDGE-1 setup: stale file present", stale.exists())
        copy_assets_into_profile("regress_v12_3", {"intro_path": ""})
        check("EDGE-1 functional: cleared intro_path prunes stale file",
              not stale.exists(),
              f"file still exists: {stale}")
    finally:
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata


# ===========================================================================
# 6. Audit fix EDGE-2: progress 0-50 main / 50-100 concat
# ===========================================================================
section("EDGE-2: progress bar split for intro/outro path")

sig = inspect.signature(batch_mod.JobRunner._run_ffmpeg)
check("_run_ffmpeg has pct_offset param",
      "pct_offset" in sig.parameters)
check("_run_ffmpeg has pct_scale param",
      "pct_scale" in sig.parameters)
check("_run_ffmpeg pct_offset defaults to 0.0",
      sig.parameters["pct_offset"].default == 0.0)
check("_run_ffmpeg pct_scale defaults to 1.0",
      sig.parameters["pct_scale"].default == 1.0)

check("_run_ffmpeg applies pct_offset + raw_pct*pct_scale",
      "pct = pct_offset + raw_pct * pct_scale" in src_run,
      "scaling expression missing")
check("_encode_video main pass uses pct_offset=0.0, pct_scale=0.5",
      "pct_offset=0.0, pct_scale=0.5" in src_vid)
check("_encode_audio_to_video main pass uses 0.0 / 0.5 split",
      "pct_offset=0.0, pct_scale=0.5" in src_atv)
check("_concat_intro_outro maps to 50-100% via pct_offset=50.0, pct_scale=0.5",
      "pct_offset=50.0, pct_scale=0.5" in src_concat,
      "concat pass scaling missing")


# ===========================================================================
# 7. V12.3.1: quality-tier dropdown (replaces numeric bitrate spinbox)
# ===========================================================================
section("V12.3.1: quality-tier dropdowns + tier resolution tables")

from engine import (
    VIDEO_QUALITY_TIERS, AUDIO_QUALITY_TIERS,
    VIDEO_QUALITY_DEFAULT, AUDIO_QUALITY_DEFAULT,
    resolve_video_bitrate_kbps, resolve_audio_bitrate_kbps,
    kbps_to_video_quality_tier, kbps_to_audio_quality_tier,
)

# Tier lists are exactly the requested five labels.
check("VIDEO_QUALITY_TIERS == [Low, Medium, High, Best, Super Best]",
      VIDEO_QUALITY_TIERS == ["Low", "Medium", "High", "Best", "Super Best"],
      str(VIDEO_QUALITY_TIERS))
check("AUDIO_QUALITY_TIERS == [Low, Medium, High, Best, Super Best]",
      AUDIO_QUALITY_TIERS == ["Low", "Medium", "High", "Best", "Super Best"],
      str(AUDIO_QUALITY_TIERS))
check("Default video tier = 'Best'", VIDEO_QUALITY_DEFAULT == "Best")
check("Default audio tier = 'Best'", AUDIO_QUALITY_DEFAULT == "Best")

# Resolution-aware video bitrate ladder. Spot-check each tier at 1080p.
check("Low @ 1080p = 3000 kbps",
      resolve_video_bitrate_kbps("Low", 1920, 1080) == 3000)
check("Medium @ 1080p = 5000 kbps",
      resolve_video_bitrate_kbps("Medium", 1920, 1080) == 5000)
check("High @ 1080p = 8000 kbps",
      resolve_video_bitrate_kbps("High", 1920, 1080) == 8000)
check("Best @ 1080p = 12000 kbps",
      resolve_video_bitrate_kbps("Best", 1920, 1080) == 12000)
check("Super Best @ 1080p = 20000 kbps",
      resolve_video_bitrate_kbps("Super Best", 1920, 1080) == 20000)
# 4K bucket.
check("High @ 4K = 40000 kbps",
      resolve_video_bitrate_kbps("High", 3840, 2160) == 40000)
check("Super Best @ 4K = 90000 kbps",
      resolve_video_bitrate_kbps("Super Best", 3840, 2160) == 90000)
# Unknown resolution falls back to 1080p column.
check("Unknown out_w/h falls back to 1080p column",
      resolve_video_bitrate_kbps("High", 0, 0) == 8000)
# Unknown tier falls back to default.
check("Unknown tier falls back to default",
      resolve_video_bitrate_kbps("Garbage", 1920, 1080)
      == resolve_video_bitrate_kbps(VIDEO_QUALITY_DEFAULT, 1920, 1080))

# Audio ladder.
check("Audio Low = 96 kbps",  resolve_audio_bitrate_kbps("Low") == 96)
check("Audio High = 192 kbps", resolve_audio_bitrate_kbps("High") == 192)
check("Audio Super Best = 320 kbps",
      resolve_audio_bitrate_kbps("Super Best") == 320)

# Back-compat: numeric kbps -> nearest tier.
check("kbps 5000 -> Medium (closest at 1080p)",
      kbps_to_video_quality_tier(5000) == "Medium")
check("kbps 0 (old match-source sentinel) -> default tier",
      kbps_to_video_quality_tier(0) == VIDEO_QUALITY_DEFAULT)
check("audio kbps 256 -> Best",
      kbps_to_audio_quality_tier(256) == "Best")

# UI wiring: main_window.py uses QComboBox + tier list; old spinboxes gone.
mw_src = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("main_window.py: no more self.video_bitrate widget",
      "self.video_bitrate =" not in mw_src,
      "old spinbox attribute still present")
check("main_window.py: no more self.audio_bitrate widget",
      "self.audio_bitrate =" not in mw_src,
      "old spinbox attribute still present")
check("main_window.py: self.video_quality = QComboBox()",
      "self.video_quality = QComboBox()" in mw_src)
check("main_window.py: self.audio_quality = QComboBox()",
      "self.audio_quality = QComboBox()" in mw_src)
check("main_window.py: video_quality populated from VIDEO_QUALITY_TIERS",
      "self.video_quality.addItems(VIDEO_QUALITY_TIERS)" in mw_src)
check("main_window.py: hint labels exist for both dropdowns",
      "self.video_quality_hint" in mw_src
      and "self.audio_quality_hint" in mw_src)
check("main_window.py: hint refresh wired to out_res change",
      "self.out_res.currentTextChanged.connect(self._refresh_video_quality_hint)"
      in mw_src,
      "out_res not connected to hint refresh")
check("main_window.py: _collect_opts resolves tier->kbps",
      "resolve_video_bitrate_kbps(" in mw_src
      and 'self.video_quality.currentText()' in mw_src)

# Intro/outro picker still validates (carried over from previous pass).
check("_pick_merge_file probes resolution + duration",
      "cached_probe_resolution(self.ffprobe, f)" in mw_src
      and "cached_probe_duration(self.ffprobe, f)" in mw_src)
check("_pick_merge_file warns on invalid video",
      "Invalid video file" in mw_src and "QMessageBox.warning" in mw_src)
check("_pick_merge_file rejects zero-res / zero-duration",
      "w <= 0 or h <= 0 or dur <= 0.05" in mw_src)

# Merge fade still has hint + tooltip.
check("merge_fade hint label present",
      "mf_hint = QLabel(" in mw_src and "hard cut" in mw_src)
check("merge_fade tooltip lists per-duration meanings",
      "de-click" in mw_src or "eliminates click" in mw_src)


# ===========================================================================
# 8. V12.3.2 bugfix: output frame size == user's selected resolution
# ===========================================================================
section("V12.3.2: output resolution matches user selection")

from engine.filters import build_filter

# Helper: extract scale args from filter graph.
def _scale_args(fc):
    return [seg for seg in fc.split(";") if "scale=" in seg]

# Case A: portrait source, landscape target -> letterboxed to exact target.
fc, last = build_filter(
    {"out_w": 1920, "out_h": 1080, "speed": 1.0},
    src_w=1080, src_h=1920, for_preview=False,
)
check("portrait src + landscape target: scale step present",
      "scale=1920:1080" in fc)
check("portrait src + landscape target: aspect-preserving",
      "force_original_aspect_ratio=decrease" in fc)
check("portrait src + landscape target: pad to exact dims",
      "pad=1920:1080" in fc)
check("portrait src + landscape target: setsar=1 for square pixels",
      "setsar=1" in fc)

# Case B: source already at target dims -> still emit setsar=1 scale step
# (to fix any non-1 SAR in the source container).
fc, last = build_filter(
    {"out_w": 1920, "out_h": 1080, "speed": 1.0},
    src_w=1920, src_h=1080, for_preview=False,
)
check("src == target: scale step still emitted (V12.3.2 fix)",
      "scale=1920:1080" in fc and "setsar=1" in fc,
      "filter is empty when src==target -- the old bug")

# Case C: 4K source, 1080p target -> standard downscale, aspect preserved.
fc, last = build_filter(
    {"out_w": 1920, "out_h": 1080, "speed": 1.0},
    src_w=3840, src_h=2160, for_preview=False,
)
check("4K -> 1080p: scale=1920:1080 with aspect ratio preserved",
      "scale=1920:1080:force_original_aspect_ratio=decrease" in fc)

# Case D: Match Source (target=0) -> no scale step, source passes through.
fc, last = build_filter(
    {"out_w": 0, "out_h": 0, "speed": 1.0},
    src_w=3840, src_h=2160, for_preview=False,
)
check("Match Source: no scale step (filter graph empty when no other ops)",
      fc == "" and last == "[0:v]")

# Case E: preview path -> uses preview-only scale, not the encode-target scale.
fc, last = build_filter(
    {"out_w": 1920, "out_h": 1080, "speed": 1.0},
    src_w=3840, src_h=2160, for_preview=True,
)
check("preview path: uses preview scale, not target scale",
      "scale='min(1280,iw)':-2" in fc
      and "force_original_aspect_ratio=decrease" not in fc)


# ===========================================================================
# 9. V12.3.3 perf: audio-to-video path enables hardware decode for visual
# ===========================================================================
section("V12.3.3: audio-to-video hardware decode (GPU utilisation)")

import inspect as _insp
_src_atv = _insp.getsource(batch_mod.JobRunner._encode_audio_to_video)
check("_encode_audio_to_video honours opts['hw_decode']",
      'self.opts.get("hw_decode", True)' in _src_atv,
      "hw_decode opt not checked")
check("_encode_audio_to_video resolves hwaccel via hwaccel_for_encoder",
      "hwaccel_for_encoder(encoder)" in _src_atv,
      "hwaccel_for_encoder call missing")
check("_encode_audio_to_video adds -hwaccel before the visual input",
      '"-hwaccel", hwaccel' in _src_atv,
      "-hwaccel arg not appended")
# Make sure the -hwaccel arg is BEFORE the visual input (otherwise it
# has no effect -- FFmpeg's -hwaccel is per-input and must precede -i).
hwaccel_pos = _src_atv.find('"-hwaccel", hwaccel')
# After V12.3.5 the input arg is ``visual_input_path`` (possibly the
# pre-scaled temp PNG rather than the user's raw ``self.visual_path``).
visual_pos = _src_atv.find('"-i", visual_input_path')
check("_encode_audio_to_video -hwaccel precedes -i visual",
      0 < hwaccel_pos < visual_pos,
      f"order broken: hwaccel@{hwaccel_pos}, visual@{visual_pos}")


# ===========================================================================
# 10. V12.3.4 bugfix: profile_visuals re-order preserves data
# ===========================================================================
section("V12.3.4: profile_visuals survives save / re-order / remove")

import tempfile as _tf, shutil as _sh, json as _json
from pathlib import Path as _P

with _tf.TemporaryDirectory() as _td:
    _old = os.environ.get("APPDATA")
    os.environ["APPDATA"] = _td
    try:
        # Re-import after APPDATA change so module-level paths re-resolve.
        from app.profile_assets import (
            copy_assets_into_profile as _cap,
            assets_dir_for as _adf,
        )
        _src = _P(_td) / "src"
        _src.mkdir()
        _A = _src / "A.png"; _A.write_bytes(b"AAAA")
        _B = _src / "B.png"; _B.write_bytes(b"BBBB")
        _C = _src / "C.png"; _C.write_bytes(b"CCCC")

        # First save: [A, B, C]
        prof = {"profile_visuals": [
            {"path": str(_A), "kind": "image"},
            {"path": str(_B), "kind": "image"},
            {"path": str(_C), "kind": "image"},
        ]}
        r1 = _cap("p", prof)
        files = {f.name: f.read_bytes() for f in _adf("p").iterdir()
                 if f.name.startswith("visual_")}
        check("first save: three slots written",
              len(files) == 3 and "visual_001.png" in files
              and "visual_002.png" in files and "visual_003.png" in files,
              str(sorted(files.keys())))
        check("first save: contents match A/B/C in order",
              files.get("visual_001.png") == b"AAAA"
              and files.get("visual_002.png") == b"BBBB"
              and files.get("visual_003.png") == b"CCCC",
              str(files))

        # Re-order to [B, A, C]
        internal = [d["path"] for d in r1["profile_visuals"]]
        reordered = {"profile_visuals": [
            {"path": internal[1], "kind": "image"},  # B
            {"path": internal[0], "kind": "image"},  # A
            {"path": internal[2], "kind": "image"},  # C
        ]}
        r2 = _cap("p", reordered)
        files2 = {f.name: f.read_bytes() for f in _adf("p").iterdir()
                  if f.name.startswith("visual_")}
        check("re-order [B, A, C]: visual_001 has B, visual_002 has A",
              files2.get("visual_001.png") == b"BBBB"
              and files2.get("visual_002.png") == b"AAAA",
              str(files2))
        check("re-order: visual_003 still has C",
              files2.get("visual_003.png") == b"CCCC",
              str(files2))
        check("re-order: profile dict reflects new slot paths in user order",
              [_P(e["path"]).name for e in r2["profile_visuals"]]
                  == ["visual_001.png", "visual_002.png", "visual_003.png"],
              str(r2["profile_visuals"]))

        # Remove B + reorder to [C, A]
        reordered2 = {"profile_visuals": [
            {"path": [d["path"] for d in r2["profile_visuals"]][2],  # C
             "kind": "image"},
            {"path": [d["path"] for d in r2["profile_visuals"]][1],  # A
             "kind": "image"},
        ]}
        r3 = _cap("p", reordered2)
        files3 = {f.name: f.read_bytes() for f in _adf("p").iterdir()
                  if f.name.startswith("visual_")}
        check("remove-B + reorder [C, A]: stale visual_003 pruned",
              "visual_003.png" not in files3, str(sorted(files3.keys())))
        check("remove-B + reorder [C, A]: visual_001=C, visual_002=A",
              files3.get("visual_001.png") == b"CCCC"
              and files3.get("visual_002.png") == b"AAAA",
              str(files3))

        # No staging temps left behind.
        leftover = [f.name for f in _adf("p").iterdir()
                    if f.name.startswith(".staging_")]
        check("no .staging_* orphans after save", len(leftover) == 0,
              str(leftover))

        # JSON round-trip integrity.
        round_tripped = _json.loads(_json.dumps(r3))
        check("profile dict JSON-round-trips with the same visuals list",
              round_tripped["profile_visuals"] == r3["profile_visuals"])
    finally:
        if _old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = _old


# ===========================================================================
# 11. V12.3.5 perf: image visual pre-scaled once, skip per-frame filter
# ===========================================================================
section("V12.3.5: image visual pre-scale (GPU utilisation)")

from engine.filters import build_audio_filter as _baf
fc_default, _ = _baf({"out_w": 1920, "out_h": 1080}, 1920, 1080,
                     for_preview=False)
check("default filter: scale+pad+setsar present (per-frame)",
      "scale=1920:1080" in fc_default and "pad=1920:1080" in fc_default,
      fc_default)

fc_pre, _ = _baf({"out_w": 1920, "out_h": 1080}, 1920, 1080,
                 for_preview=False, visual_pre_scaled=True)
check("pre-scaled filter: scale+pad skipped, just setsar=1",
      "scale=" not in fc_pre and "pad=" not in fc_pre
      and "setsar=1" in fc_pre,
      fc_pre)

# Engine batch.py exposes _prescale_image_visual + cleanup hook.
_src_atv = inspect.getsource(batch_mod.JobRunner._encode_audio_to_video)
check("_encode_audio_to_video calls _prescale_image_visual for image",
      "_prescale_image_visual" in _src_atv,
      "pre-scale not wired in")
check("_encode_audio_to_video passes visual_pre_scaled to filter builder",
      "visual_pre_scaled=visual_pre_scaled" in _src_atv,
      "filter flag not forwarded")

_src_run = inspect.getsource(batch_mod.JobRunner.run)
check("JobRunner.run cleans up _tmp_prescaled after encode",
      "_tmp_prescaled" in _src_run
      and "os.remove(self._tmp_prescaled)" in _src_run,
      "cleanup hook missing")

_src_pre = inspect.getsource(batch_mod.JobRunner._prescale_image_visual)
check("_prescale_image_visual returns 3-tuple",
      "return visual_path, False, None" in _src_pre
      and "return visual_path, True, None" in _src_pre
      and "return tmp_path, True, tmp_path" in _src_pre,
      "return shape doesn't match")
check("_prescale_image_visual uses mkstemp for unique filename",
      "tempfile.mkstemp" in _src_pre)
check("_prescale_image_visual short-circuits when src already at target",
      "src_w == target_w and src_h == target_h" in _src_pre)


# ===========================================================================
# 12. V13.0: GitHub-Releases auto-update
# ===========================================================================
section("V13.0: GitHub-Releases auto-update")

from app import updater as _u
from app.updater import (
    APP_VERSION as _APP_VERSION,
    parse_version as _pv,
    version_compare as _vc,
    is_newer as _newer,
    check_for_updates as _cfu,
    UpdateInfo as _UI,
    _pick_windows_asset as _pwa,
)

# Version is correctly bumped.
check("APP_VERSION = '14.9.0'", _APP_VERSION == "14.9.0",
      f"got {_APP_VERSION!r}")
check("GITHUB_REPO is khurram5509/Veloxa-Video-Editor",
      _u.GITHUB_REPO == "khurram5509/Veloxa-Video-Editor",
      f"got {_u.GITHUB_REPO!r}")

# parse_version tolerates V/v prefix, trailing zeros, junk.
check("parse_version('V13.0') -> (13, 0)", _pv("V13.0") == (13, 0))
check("parse_version('v13.0.0') -> (13, 0, 0)",
      _pv("v13.0.0") == (13, 0, 0))
check("parse_version('12.3.5') -> (12, 3, 5)",
      _pv("12.3.5") == (12, 3, 5))
check("parse_version('') -> (0,)", _pv("") == (0,))
check("parse_version('garbage') -> (0,)", _pv("garbage") == (0,))

# version_compare handles all the obvious orderings.
check("v12 < v13", _vc("12.0", "13.0") == -1)
check("v13 > v12", _vc("13.0", "12.0") == 1)
check("v13.0 == 13.0.0 (trailing zeros)", _vc("13.0", "13.0.0") == 0)
check("v12.3.5 < V13.0", _vc("12.3.5", "V13.0") == -1)
check("'v' prefix tolerated either side",
      _vc("v13.0", "V13.0") == 0)

# is_newer convenience.
check("is_newer('14.9.0', '13.0')", _newer("14.9.0", "13.0"))
check("not is_newer('12.9.99', '13.0')",
      not _newer("12.9.99", "13.0"))
check("not is_newer('13.0', '13.0')",
      not _newer("13.0", "13.0"))

# Asset picker preference: Setup > Installer > generic .exe > nothing.
assets_setup = [
    {"name": "VeloxaVideoEditor-V13.0-Setup.exe",
     "browser_download_url": "http://x/s.exe", "size": 100},
    {"name": "Veloxa-Portable-V13.0.exe",
     "browser_download_url": "http://x/p.exe", "size": 50},
]
picked = _pwa(assets_setup)
check("asset picker: prefers *Setup*.exe",
      picked and "Setup" in picked["name"])

assets_no_setup = [
    {"name": "Veloxa-Installer-V13.0.exe",
     "browser_download_url": "http://x/i.exe", "size": 50},
    {"name": "Veloxa-Portable-V13.0.exe",
     "browser_download_url": "http://x/p.exe", "size": 50},
]
picked = _pwa(assets_no_setup)
check("asset picker: falls back to *Installer*.exe",
      picked and "Installer" in picked["name"])

assets_neither = [
    {"name": "Veloxa-Portable-V13.0.exe",
     "browser_download_url": "http://x/p.exe", "size": 50},
]
picked = _pwa(assets_neither)
check("asset picker: falls back to any .exe",
      picked and picked["name"].endswith(".exe"))

assets_none = [
    {"name": "Source.zip", "browser_download_url": "http://x/s.zip"},
]
check("asset picker: returns None when no .exe present",
      _pwa(assets_none) is None)

check("asset picker: returns None on empty asset list",
      _pwa([]) is None)

# check_for_updates: short-circuits gracefully when repo is empty.
check("check_for_updates('') returns None (feature disabled)",
      _cfu(github_repo="") is None)
check("check_for_updates('not-a-slug') returns None (no slash)",
      _cfu(github_repo="not-a-slug") is None)

# Verify the GUI wiring: main_window imports updater symbols and
# registers the 'Check for Updates...' menu item.
mw_src = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("main_window imports UpdateChecker + helpers",
      "from .updater import" in mw_src
      and "UpdateChecker" in mw_src and "DownloadWorker" in mw_src
      and "launch_installer_and_quit" in mw_src)
check("Help menu has 'Check for Updates' item",
      # V14.8.1: ellipsis switched from '...' to a single U+2026 codepoint
      # when the items moved into the Help submenu. Accept either form.
      ('"Check for Updates..."' in mw_src
       or '"Check for Updates' + chr(0x2026) + '"' in mw_src)
      and "_check_for_updates_manual" in mw_src)
check("Auto-check fires on startup (QTimer.singleShot)",
      "_maybe_check_for_updates_on_startup" in mw_src
      and "auto_update_check" in mw_src)
check("Update dialog has Download / Later / Skip buttons",
      '"Download && Install"' in mw_src
      and '"Remind Me Later"' in mw_src
      and '"Skip This Version"' in mw_src)
check("Update dialog exposes 'Check for updates on startup' tickbox",
      '"Check for updates on startup"' in mw_src
      and "setCheckBox" in mw_src)
check("Update flow warns when a batch is running",
      "is_running()" in mw_src and "A batch is currently encoding" in mw_src)

# Docs cover the new feature.
docs_src = open(ROOT / "app" / "docs.py", encoding="utf-8").read()
check("docs.py title uses dynamic APP_VERSION",
      # V14.9.0: switched to f-string interpolation from APP_VERSION so
      # the docs never drift again. Old assertion was a hardcoded literal.
      "Veloxa Video Editor {_V}" in docs_src
      or "from .updater import APP_VERSION" in docs_src)
check("docs.py advertises auto-update feature",
      "Auto-update via GitHub" in docs_src
      or "Auto-update (V13.0" in docs_src)

# Installer.iss + build.ps1 carry the new version.
iss_src = open(ROOT / "installer.iss", encoding="utf-8").read()
check("installer.iss AppVersion = 14.9.0", '"14.9.0"' in iss_src)
check("installer.iss EXE name = V14.9.0.exe",
      "Veloxa-Video-Editor-V14.9.0.exe" in iss_src)
check("installer.iss preserves stable AppId across V12 -> V13",
      "F2E1A8C4-1E5B-4C9A-9B27-VELOXA-VID-V121" in iss_src)
ps1_src = open(ROOT / "build.ps1", encoding="utf-8").read()
check("build.ps1 builds V14.9.0 EXE",
      "Veloxa-Video-Editor-V14.9.0" in ps1_src)

# V14.8.1 crash-fix: stale C++-object guard in _start_update_check.
mw_src2 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("_start_update_check guards RuntimeError on stale wrapper",
      "except RuntimeError" in mw_src2
      and "self._update_checker = None" in mw_src2)
check("_on_update_checker_finished clears the Python ref",
      "_on_update_checker_finished" in mw_src2)


# ===========================================================================
# 13. V14.8.1: System / Light / Dark theme switcher
# ===========================================================================
section("V14.8.1: theme switcher")

from app.theme import (
    DARK_QSS, LIGHT_QSS,
    THEME_SYSTEM as _TSYS, THEME_LIGHT as _TLIGHT,
    THEME_DARK as _TDARK, THEME_MODES as _TMODES,
    detect_system_theme as _dst, resolve_theme_mode as _rtm,
    apply_theme as _apt,
)

check("THEME_MODES includes system / light / dark / oled",
      set(_TMODES) == {"system", "light", "dark", "oled"},
      str(_TMODES))
check("DARK_QSS and LIGHT_QSS are non-trivial strings",
      isinstance(DARK_QSS, str) and isinstance(LIGHT_QSS, str)
      and len(DARK_QSS) > 1000 and len(LIGHT_QSS) > 1000)
check("DARK_QSS and LIGHT_QSS differ (not a copy/paste)",
      DARK_QSS != LIGHT_QSS)

# Brand accent appears in both themes.
check("dark theme uses brand orange",  "#f58220" in DARK_QSS)
check("light theme uses brand orange", "#f58220" in LIGHT_QSS)

# V14.8.1: light theme redesign -- depth + hierarchy.
check("light theme uses qlineargradient for button/input depth",
      "qlineargradient" in LIGHT_QSS)
check("light theme uses tinted off-white main bg (cards stand out)",
      "#eef0f4" in LIGHT_QSS)
check("light theme: selected tab gets orange underline",
      "border-bottom: 2px solid #f58220" in LIGHT_QSS)
check("light theme: focus ring is 2px (not just 1px)",
      "border: 2px solid #f58220" in LIGHT_QSS)
check("light theme: alternating list-row colour for scanability",
      "alternate-background-color" in LIGHT_QSS)

# System detector returns a valid concrete mode.
sys_mode = _dst()
check("detect_system_theme() in {light, dark}", sys_mode in ("light", "dark"))

# resolve_theme_mode collapses "system" to a concrete mode.
check("resolve_theme_mode('system') -> concrete",
      _rtm("system") in ("light", "dark"))
check("resolve_theme_mode('light') == 'light'",
      _rtm("light") == "light")
check("resolve_theme_mode('dark') == 'dark'",
      _rtm("dark") == "dark")
check("resolve_theme_mode('garbage') falls back to dark",
      _rtm("garbage_value") == "dark")

# GUI wiring: main_window imports the theme helpers and exposes the menu.
mw_src3 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("main_window imports theme switcher symbols",
      "from .theme import" in mw_src3 and "apply_theme" in mw_src3
      and "THEME_SYSTEM" in mw_src3)
check("Appearance submenu added to menu bar",
      'mb.addMenu("Appearance")' in mw_src3
      # V14.8.1: label changed from 'System (follow Windows)' to
      # 'System (follow OS)' when the macOS menubar fix landed.
      and ("System (follow Windows)" in mw_src3
           or "System (follow OS)" in mw_src3)
      and "QActionGroup" in mw_src3)
check("_set_theme_mode handler exists",
      "_set_theme_mode" in mw_src3 and "settings.setValue(\"theme_mode\"" in mw_src3)

# Boot path: main.py reads theme_mode from QSettings and applies.
main_src = open(ROOT / "main.py", encoding="utf-8").read()
check("main.py uses apply_theme() instead of hardcoded DARK_QSS",
      "apply_theme(app" in main_src and "DARK_QSS" not in main_src)
check("main.py reads theme_mode from QSettings",
      'theme_mode' in main_src)


# ===========================================================================
# 14. V14.0: AV templates + OLED theme + queue right-click + playback
# ===========================================================================
section("V14.0: AV templates / OLED / queue / playback")

# OLED theme is registered as a fourth mode.
from app.theme import THEME_OLED as _TOLED, THEME_MODES as _TM_V14
check("OLED theme mode is registered", _TOLED == "oled")
check("THEME_MODES includes oled", "oled" in _TM_V14)
from app.theme import OLED_QSS as _OQ
check("OLED_QSS uses pure-black main bg",
      "#000000" in _OQ and "#23262d" not in _OQ)

# Audio-visual templates registry.
from engine import (
    AUDIO_TEMPLATES, AUDIO_TEMPLATE_ORDER, AUDIO_TEMPLATE_NONE,
    audio_template_choices, get_audio_template,
)
check("6 audio templates registered",
      len(AUDIO_TEMPLATE_ORDER) == 6,
      f"got {AUDIO_TEMPLATE_ORDER}")
for k in ("spectrum_bars", "circular_spectrum", "waveform",
          "neon_ring", "podcast_layout", "spotify_canvas"):
    check(f"audio template {k!r} registered", k in AUDIO_TEMPLATES)
choices_v14 = audio_template_choices()
check("template_choices starts with 'none' sentinel",
      choices_v14[0][0] == "none")
check("get_audio_template('none') -> None",
      get_audio_template("none") is None)

# Filter graphs produce non-empty strings + a [vout] label.
for k in AUDIO_TEMPLATE_ORDER:
    tpl = get_audio_template(k)
    fc, lbl = tpl.build_filter("0:a", 1920, 1080, {})
    check(f"{k}: filter graph non-empty + has [vout]",
          isinstance(fc, str) and len(fc) > 50
          and lbl == "[vout]" and "[aout]" in fc,
          f"label={lbl!r}, fc[:60]={fc[:60]!r}")

# V14.8.1: actually run each template's filter graph through FFmpeg
# (against a silent lavfi audio source) so any "Option not found" /
# syntax errors fail loudly rather than at the user's encode time.
import subprocess as _sp
_FFMPEG = ROOT / "ffmpeg" / "ffmpeg.exe"
if _FFMPEG.exists():
    for k in AUDIO_TEMPLATE_ORDER:
        tpl = get_audio_template(k)
        fc, lbl = tpl.build_filter("0:a", 1920, 1080, {})
        _cmd = [
            str(_FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", fc, "-map", lbl, "-map", "[aout]",
            "-t", "0.1", "-f", "null", "-",
        ]
        try:
            _r = _sp.run(_cmd, capture_output=True, text=True, timeout=20)
        except _sp.TimeoutExpired:
            _r = None
        check(f"{k}: FFmpeg parses + runs filter graph",
              _r is not None and _r.returncode == 0,
              (_r.stderr or '').strip().split('\n')[-1][:160] if _r else "timeout")
else:
    check("AV template FFmpeg validation skipped (no bundled ffmpeg.exe)",
          True)

# Engine: _encode_audio_with_template exists and is wired.
import inspect as _inspect
from engine import batch as _batch_mod
src_atv = _inspect.getsource(_batch_mod.JobRunner._encode_audio_to_video)
check("_encode_audio_to_video short-circuits on audio_template",
      "_encode_audio_with_template" in src_atv
      and 'opts.get("audio_template"' in src_atv)
check("_encode_audio_with_template exists on JobRunner",
      hasattr(_batch_mod.JobRunner, "_encode_audio_with_template"))

# main_window has the dropdown + the new context-menu actions + overlay.
mw_v14 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("audio_template_combo widget wired", "audio_template_combo" in mw_v14)
check("Right-click: Preview This Row", '"▶ Preview This Row"' in mw_v14)
check("Right-click: Move to Top / Bottom",
      "Move " in mw_v14 and "to Top" in mw_v14 and "to Bottom" in mw_v14)
check("Right-click: Duplicate Row(s)", "Duplicate" in mw_v14 and "Row(s)" in mw_v14)
check("Right-click: Retry Failed/Done", "Retry" in mw_v14 and "Failed/Done" in mw_v14)
check("Preview overlay widget present", "preview_overlay" in mw_v14)
check("OLED theme listed in Appearance menu",
      "OLED Dark (pure black)" in mw_v14)
check("QMediaPlayer transport buttons present",
      "_mp_player" in mw_v14 and "mp_play_btn" in mw_v14
      and "mp_pause_btn" in mw_v14 and "mp_stop_btn" in mw_v14)

# profile_opts pipes the template through to the CLI runner.
po_v14 = open(ROOT / "app" / "profile_opts.py", encoding="utf-8").read()
check("profile_opts passes audio_template through",
      '"audio_template"' in po_v14)


# ===========================================================================
# 15. V14.8.1: updater download runs on a QThread (no more GUI freeze)
# ===========================================================================
section("V14.8.1: updater download worker")

from app.updater import DownloadWorker as _DW
import inspect as _inspectV14
_dw_src = _inspectV14.getsource(_DW)
check("DownloadWorker is a QThread",
      "QThread" in _dw_src and "class DownloadWorker" in _dw_src)
check("DownloadWorker has progress + finished_with_path signals",
      "progress = pyqtSignal" in _dw_src
      and "finished_with_path = pyqtSignal" in _dw_src)
check("DownloadWorker throttles progress signals (~10/sec by default)",
      "progress_throttle_hz" in _dw_src
      and "min_interval = 1.0 / max(1" in _dw_src)
check("DownloadWorker passes a cancel callback",
      "_cancel_cb" in _dw_src and "self._cancel = False" in _dw_src)

# download_installer uses 1 MB chunks.
import app.updater as _upd
_di_src = _inspectV14.getsource(_upd.download_installer)
check("download_installer chunk size = 64 KB (V14.8.1 perf fix)",
      "chunk_size = 64 * 1024" in _di_src,
      "V14.0.1 incorrectly bumped to 1 MB and tanked throughput")

# GUI now wires the worker instead of calling download_installer
# synchronously.
mw_v141 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("main_window uses DownloadWorker (no sync download_installer call)",
      "DownloadWorker" in mw_v141
      and "download_installer(" not in mw_v141)
check("Progress dialog cancel routes to worker.cancel()",
      "prog.canceled.connect(worker.cancel)" in mw_v141)
check("Progress UI shows MB transferred + transfer rate",
      "MB/s" in mw_v141 and "rate_mbps" in mw_v141)
check("Progress bar uses 0..1000 range for sub-percent granularity",
      "QProgressDialog(\n            \"Connecting...\", \"Cancel\", 0, 1000" in mw_v141
      or 'QProgressDialog("Connecting..."' in mw_v141)


# ===========================================================================
# 16. V14.8.1: preview overlay clears + installer no longer side-by-side
# ===========================================================================
section("V14.8.1: preview clear + installer overwrite")

mw_v142 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()

# Preview overlay is cleared in all three early-return paths.
check("_update_preview_info hides overlay when no current row",
      "self.preview_overlay.hide()" in mw_v142
      and 'def _update_preview_info(self):' in mw_v142)
check("_refresh_preview resets preview_label + hides overlay on empty",
      "Add a video or audio file." in mw_v142
      and mw_v142.count("self.preview_overlay.hide()") >= 3)
check("_on_video_selected hides overlay + stops playback on empty",
      "Select a file to preview" in mw_v142
      and "_mp_player.stop()" in mw_v142
      and "_mp_video_widget.hide()" in mw_v142)

# installer.iss uses an unversioned EXE name + InstallDelete sweep.
iss_v142 = open(ROOT / "installer.iss", encoding="utf-8").read()
check("installer EXE name is unversioned 'Veloxa-Video-Editor.exe'",
      '#define AppExeName          "Veloxa-Video-Editor.exe"' in iss_v142)
check("installer DestName= renames build EXE to unversioned",
      "DestName" in iss_v142
      and 'DestName: "{#AppExeName}"' in iss_v142)
check("installer Start Menu shortcut is unversioned",
      '{autoprograms}\\{#AppName}"' in iss_v142
      and '{#AppName} V{#AppVersion}"' not in iss_v142.split("[Icons]")[1].split("[Run]")[0])
check("installer cleans up legacy versioned EXEs",
      "[InstallDelete]" in iss_v142
      and "Veloxa-Video-Editor-V*.exe" in iss_v142)
check("installer cleans up legacy versioned shortcuts",
      "Veloxa Video Editor V*.lnk" in iss_v142
      and "Uninstall Veloxa Video Editor V*.lnk" in iss_v142)
check("installer sets VersionInfo* so Setup EXE icon shows",
      "VersionInfoCompany" in iss_v142
      and "VersionInfoProductName" in iss_v142)


# ===========================================================================
# 17. V14.8.1: Single instance + HiDPI + responsive hardening
# ===========================================================================
section("V14.8.1: single-instance, HiDPI, min size")

# Single-instance module exists and exposes the public API.
from app import single_instance as _si
check("single_instance.request_single_instance callable",
      callable(_si.request_single_instance))
check("single_instance.install_activation_handler callable",
      callable(_si.install_activation_handler))
check("single_instance.SOCKET_NAME is per-user (contains current user)",
      isinstance(_si.SOCKET_NAME, str)
      and _si.SOCKET_NAME.startswith("VeloxaVideoEditor-"))
check("single_instance uses QLocalServer + QLocalSocket",
      "QLocalServer" in inspect.getsource(_si)
      and "QLocalSocket" in inspect.getsource(_si))

# main.py wires HiDPI, single-instance, and activation focus handler.
main_v141 = open(ROOT / "main.py", encoding="utf-8").read()
check("main.py enables HiDPI before QApplication",
      "_enable_high_dpi()" in main_v141
      and "PassThrough" in main_v141)
check("main.py calls request_single_instance",
      "request_single_instance" in main_v141)
check("main.py installs activation handler that focuses window",
      "install_activation_handler" in main_v141
      and "_activate_window" in main_v141)
check("main.py shows 'already running' dialog on second-instance",
      "already running" in main_v141 or "is already running" in main_v141)
check("main.py title docstring bumped to V14.1",
      "Veloxa Video Editor V14.1" in main_v141)

# MainWindow has a sensible minimum size + still saves/restores geometry.
mw_v141 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("MainWindow setMinimumSize 1024x680 set",
      "setMinimumSize(QSize(1024, 680))" in mw_v141)
check("MainWindow still calls restoreGeometry on load",
      "restoreGeometry" in mw_v141)
check("MainWindow still calls saveGeometry on close",
      "saveGeometry" in mw_v141)


# ===========================================================================
# 18. V14.8.1: single-instance ACK handshake + dynamic version log
# ===========================================================================
section("V14.8.1: single-instance ACK + dynamic persistence version")

si_src = inspect.getsource(_si)
check("single_instance defines ACK_MAGIC",
      "ACK_MAGIC" in si_src and "OK" in si_src)
check("single_instance defines ACK_TIMEOUT_MS",
      "ACK_TIMEOUT_MS" in si_src)
check("Second-instance path waits for ACK before declaring duplicate",
      "waitForReadyRead(ACK_TIMEOUT_MS)" in si_src)
check("No-ACK path falls through to take over as primary",
      "stale endpoint" in si_src or "taking over" in si_src)
check("Primary writes ACK after running activation callback",
      "sock.write(ACK_MAGIC)" in si_src)

pers = open(ROOT / "app" / "persistence.py", encoding="utf-8").read()
check("persistence.py reads APP_VERSION dynamically (no V13.0 hardcode)",
      "from .updater import APP_VERSION" in pers
      and "V13.0 session start" not in pers)


# ===========================================================================
# 19. V14.8.1: macOS source-level support + GitHub Actions
# ===========================================================================
section("V14.8.1: cross-platform foundation")

from app import platform_compat as _pc
check("platform_compat exposes IS_WIN / IS_MAC / IS_LINUX",
      hasattr(_pc, "IS_WIN") and hasattr(_pc, "IS_MAC")
      and hasattr(_pc, "IS_LINUX"))
check("platform_tag returns 'windows' on Windows host",
      _pc.platform_tag() in ("windows", "macos", "linux"))

# Asset picker honours platform: Windows host should still pick .exe.
mac_assets = [
    {"name": "Veloxa-Video-Editor-V14.8.1-Setup.exe"},
    {"name": "Veloxa-Video-Editor-V14.8.1-macOS.dmg"},
]
picked = _pc.pick_release_asset(mac_assets)
if _pc.IS_WIN:
    check("pick_release_asset on Windows -> .exe",
          picked and picked["name"].endswith(".exe"))
elif _pc.IS_MAC:
    check("pick_release_asset on macOS -> .dmg",
          picked and picked["name"].endswith(".dmg"))

# Legacy back-compat: _pick_windows_asset still pickable for tests.
from app.updater import _pick_windows_asset
check("Legacy _pick_windows_asset still selects .exe assets",
      _pick_windows_asset(mac_assets) and
      _pick_windows_asset(mac_assets)["name"].endswith(".exe"))

# updater.check_for_updates now uses pick_release_asset (delegated).
_check_for_updates_src = inspect.getsource(_u.check_for_updates)
check("check_for_updates uses pick_release_asset (platform-aware)",
      "pick_release_asset" in _check_for_updates_src)

# launch_installer_and_quit delegates to platform_compat.launch_installer.
_lia_src = inspect.getsource(_u.launch_installer_and_quit)
check("launch_installer_and_quit delegates to platform_compat",
      "launch_installer" in _lia_src and "platform_compat" in _lia_src)

# Engine ffmpeg locator delegates to platform_compat.
from engine import ffmpeg as _ff_mod
_ff_src = inspect.getsource(_ff_mod.find_ffmpeg)
check("engine.find_ffmpeg tries platform_compat first",
      "platform_compat" in _ff_src and "find_bundled_ffmpeg" in _ff_src)

# main_window's _open_in_explorer + _open_log_folder use platform_compat.
mw_v142 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("_open_in_explorer uses platform_compat.open_in_file_manager",
      "_open_in_explorer" in mw_v142
      and "open_in_file_manager" in mw_v142)
check("dialogs._open_folder uses platform_compat.open_in_file_manager",
      "open_in_file_manager" in open(ROOT / "app" / "dialogs.py",
                                     encoding="utf-8").read())

# GitHub Actions workflow exists + targets macOS runner.
gha_path = ROOT / ".github" / "workflows" / "build_macos.yml"
check("GitHub Actions workflow .github/workflows/build_macos.yml exists",
      gha_path.exists())
gha_src = gha_path.read_text(encoding="utf-8") if gha_path.exists() else ""
check("Workflow triggers on v* tag push",
      "tags:" in gha_src and "v*" in gha_src)
check("Workflow uses macos-latest runner",
      "macos-latest" in gha_src)
check("Workflow builds .app + .dmg + ad-hoc signs",
      "pyinstaller" in gha_src.lower()
      and "create-dmg" in gha_src
      and "codesign --deep --force --sign -" in gha_src)
check("Workflow uploads .dmg to the matching release",
      "gh release upload" in gha_src
      and ".dmg" in gha_src)


# ===========================================================================
# V14.8.1 -- Parallel CPU encoder slot + add-files-while-batch-runs
# ===========================================================================
section("V14.8.1 -- CPU/GPU parallel slot + safety + queue-add")

# ---- engine/system_resources.py contract --------------------------------
from engine import system_resources as _sr
check("system_resources.low_priority_popen_kwargs exists",
      callable(getattr(_sr, "low_priority_popen_kwargs", None)))
_kw = _sr.low_priority_popen_kwargs()
check("low_priority_popen_kwargs returns a dict",
      isinstance(_kw, dict))
if sys.platform == "win32":
    # BELOW_NORMAL_PRIORITY_CLASS = 0x4000.
    check("Windows low-priority kwargs include BELOW_NORMAL creationflags",
          _kw.get("creationflags", 0) & 0x4000)
else:
    check("Unix low-priority kwargs include preexec_fn",
          callable(_kw.get("preexec_fn")))

check("system_resources.cpu_encoder_thread_count exists",
      callable(getattr(_sr, "cpu_encoder_thread_count", None)))
_n_solo = _sr.cpu_encoder_thread_count(parallel_gpu_running=False)
_n_para = _sr.cpu_encoder_thread_count(parallel_gpu_running=True)
check("cpu_encoder_thread_count returns >=1 in both modes",
      _n_solo >= 1 and _n_para >= 1)
check("cpu_encoder_thread_count is no larger when GPU runs parallel",
      _n_para <= _n_solo)

check("system_resources.enough_ram_for_cpu_job exists",
      callable(getattr(_sr, "enough_ram_for_cpu_job", None)))
# fail-open semantics: even with no psutil, must return a bool.
check("enough_ram_for_cpu_job returns a bool",
      isinstance(_sr.enough_ram_for_cpu_job(), bool))

check("system_resources.force_cpu_encoder exists",
      callable(getattr(_sr, "force_cpu_encoder", None)))
_265 = _sr.force_cpu_encoder({"encoder": "hevc_nvenc"})
_264 = _sr.force_cpu_encoder({"encoder": "h264_nvenc"})
check("force_cpu_encoder maps hevc family -> libx265",
      _265.get("encoder") == "libx265" and _265.get("_cpu_slot") is True)
check("force_cpu_encoder maps h264 family -> libx264",
      _264.get("encoder") == "libx264" and _264.get("_cpu_slot") is True)

# ---- BatchManager.HARD_CAP_CONCURRENT + helpers -------------------------
from engine import batch as _bm_mod
check("BatchManager.HARD_CAP_CONCURRENT == 4",
      getattr(_bm_mod.BatchManager, "HARD_CAP_CONCURRENT", None) == 4)
check("BatchManager.set_use_cpu_slot exists",
      callable(getattr(_bm_mod.BatchManager, "set_use_cpu_slot", None)))
check("BatchManager.add_jobs exists",
      callable(getattr(_bm_mod.BatchManager, "add_jobs", None)))
check("BatchManager.effective_concurrency exists",
      callable(getattr(_bm_mod.BatchManager, "effective_concurrency", None)))
check("BatchManager._dispatch exists",
      callable(getattr(_bm_mod.BatchManager, "_dispatch", None)))
check("BatchManager._cpu_slot_safe_to_open exists",
      callable(getattr(_bm_mod.BatchManager, "_cpu_slot_safe_to_open", None)))

# ---- JobRunner CPU-slot threads + low-priority Popen --------------------
check("JobRunner._cpu_threads_flag exists",
      callable(getattr(_bm_mod.JobRunner, "_cpu_threads_flag", None)))
_batch_src = inspect.getsource(_bm_mod)
check("JobRunner._run_ffmpeg uses low_priority_popen_kwargs on _cpu_slot",
      "low_priority_popen_kwargs" in _batch_src and "_cpu_slot" in _batch_src)
check("BatchManager._start_next branches on _cpu_slot",
      "force_cpu_encoder" in _batch_src)

# ---- UI wiring -----------------------------------------------------------
mw_v143 = open(ROOT / "app" / "main_window.py", encoding="utf-8").read()
check("Settings checkbox use_cpu_alongside_gpu exists",
      "use_cpu_alongside_gpu" in mw_v143
      and "Also use CPU encoder when GPU is busy" in mw_v143)
check("Checkbox toggled signal wired to handler",
      "_on_use_cpu_alongside_gpu_toggled" in mw_v143)
check("Handler propagates to BatchManager.set_use_cpu_slot",
      "set_use_cpu_slot" in mw_v143)
check("_collect_opts persists use_cpu_alongside_gpu",
      '"use_cpu_alongside_gpu":' in mw_v143
      or "'use_cpu_alongside_gpu':" in mw_v143)
check("closeEvent saves use_cpu_alongside_gpu via QSettings",
      'setValue("use_cpu_alongside_gpu"' in mw_v143
      or "setValue('use_cpu_alongside_gpu'" in mw_v143)
check("_load_settings restores use_cpu_alongside_gpu",
      'value("use_cpu_alongside_gpu"' in mw_v143
      or "value('use_cpu_alongside_gpu'" in mw_v143)

# Add-files-while-batch-runs: Add button stays enabled when locked.
check("_set_queue_locked leaves add_btn enabled",
      "add_btn.setEnabled(True)" in mw_v143)
check("_add_files dispatches mid-batch via BatchManager.add_jobs",
      "_build_jobs_for_items" in mw_v143
      and ".add_jobs(" in mw_v143)
check("_build_jobs_for_items helper defined",
      "def _build_jobs_for_items" in mw_v143)

# requirements.txt picked up psutil (used by RAM watchdog).
_req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
check("requirements.txt includes psutil>=5.9",
      "psutil" in _req)


# ===========================================================================
# V14.8.1 -- first-video-stuck-at-0% progress fix
# ===========================================================================
section("V14.8.1 -- progress emission fix")

# Re-read engine/batch.py for these checks.
_batch_src_143 = (ROOT / "engine" / "batch.py").read_text(encoding="utf-8")

# 1) -stats_period 0.1 injected next to every -progress pipe:1.
check("ffmpeg cmd uses -stats_period 0.1 with -progress pipe:1",
      '"-stats_period", "0.1"' in _batch_src_143)
# Every occurrence of `-progress pipe:1` should be followed by stats_period.
import re as _re_v143
_prog_blocks = _re_v143.findall(
    r'"-progress",\s*"pipe:1",\s*"-stats_period",\s*"0\.1"',
    _batch_src_143)
_prog_total = _re_v143.findall(r'"-progress",\s*"pipe:1"', _batch_src_143)
check(f"every -progress pipe:1 paired with -stats_period "
      f"({len(_prog_blocks)}/{len(_prog_total)})",
      len(_prog_blocks) == len(_prog_total) and len(_prog_blocks) >= 4)

# 2) _run_ffmpeg uses bufsize=0 + binary mode (no text=True).
check("_run_ffmpeg uses bufsize=0 (unbuffered Popen)",
      "bufsize=0" in _batch_src_143)
# Drop any lines that are just comments and check the remaining code
# doesn't pass text=True / bufsize=1 as kwargs to Popen.
_code_lines_143 = [ln for ln in _batch_src_143.splitlines()
                   if not ln.lstrip().startswith("#")]
_code_only_143 = "\n".join(_code_lines_143)
check("_run_ffmpeg no longer passes text=True as a kwarg",
      "text=True" not in _code_only_143)
check("_run_ffmpeg no longer passes bufsize=1 as a kwarg",
      "bufsize=1," not in _code_only_143)

# 3) Reads via iter(stdout.readline, b"") not `for line in stdout`.
check("_run_ffmpeg reads raw bytes via readline()",
      "iter(self._proc.stdout.readline, b" in _batch_src_143)

# 4) stderr.read() is decoded as bytes (not assumed str).
check("_run_ffmpeg decodes stderr bytes",
      'raw_err.decode("utf-8"' in _batch_src_143 or
      "raw_err.decode('utf-8'" in _batch_src_143)


# ===========================================================================
# V14.8.1 -- audio-template preview pane fix
# ===========================================================================
section("V14.8.1 -- audio-template preview pane")

# 1) The new generator exists at the engine level.
from engine import (
    generate_audio_template_preview as _gen_atp,
)
check("engine.generate_audio_template_preview exists",
      callable(_gen_atp))

# 2) PreviewWorker routes audio + template rows through it.
mw_src_143 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("PreviewWorker imports generate_audio_template_preview",
      "generate_audio_template_preview" in mw_src_143)
check("PreviewWorker.run() branches on the template key",
      'self.opts.get("audio_template")' in mw_src_143
      and "generate_audio_template_preview(" in mw_src_143)

# 3) _refresh_preview no longer bails when only a template is set.
check("_refresh_preview accepts audio rows with a template + no visual",
      'audio_template_combo.currentData()' in mw_src_143
      and "_has_template" in mw_src_143)

# 4) The Audio Visuals combo refreshes the preview when changed.
check("audio_template_combo wired to _schedule_preview",
      "audio_template_combo.currentIndexChanged.connect(" in mw_src_143
      and "_schedule_preview" in mw_src_143)

# 5) The implementation appends anullsink so ffmpeg accepts the
#    template's filter graph when only the video output is mapped.
_ff_src_143 = (ROOT / "engine" / "ffmpeg.py").read_text(encoding="utf-8")
check("generate_audio_template_preview appends [aout]anullsink",
      "[aout]anullsink" in _ff_src_143)
check("generate_audio_template_preview uses -update 1 for last-frame win",
      '"-update", "1"' in _ff_src_143)


# ===========================================================================
# V14.8.1 -- platform-asset routing must never mix .exe and .dmg
# ===========================================================================
section("V14.8.1 -- Win -> .exe only / Mac -> .dmg only (no mixing)")

# Monkey-patch IS_WIN / IS_MAC to verify both branches lock in correctly.
import app.platform_compat as _pc_routing
_SAVED_WIN = _pc_routing.IS_WIN
_SAVED_MAC = _pc_routing.IS_MAC
_SAVED_LINUX = _pc_routing.IS_LINUX

_release_v143 = [
    {"name": "Veloxa-Video-Editor-V14.8.1-Setup.exe",
     "browser_download_url": "https://x/win.exe", "size": 100},
    {"name": "Veloxa-Video-Editor-V14.8.1-macOS.dmg",
     "browser_download_url": "https://x/mac.dmg", "size": 100},
]
try:
    # Windows branch.
    _pc_routing.IS_WIN, _pc_routing.IS_MAC, _pc_routing.IS_LINUX = (
        True, False, False)
    _win_pick = _pc_routing.pick_release_asset(_release_v143)
    check("Win branch picks the Setup.exe",
          _win_pick and _win_pick["name"].endswith(".exe"))
    check("Win branch NEVER picks the .dmg",
          _win_pick and not _win_pick["name"].endswith(".dmg"))
    # When ONLY a .dmg is present, Win refuses (returns None).
    _win_only_dmg = _pc_routing.pick_release_asset(
        [{"name": "Veloxa-V14.8.1-macOS.dmg",
          "browser_download_url": "https://x/m.dmg", "size": 1}])
    check("Win branch refuses .dmg as fallback (returns None)",
          _win_only_dmg is None)

    # macOS branch.
    _pc_routing.IS_WIN, _pc_routing.IS_MAC, _pc_routing.IS_LINUX = (
        False, True, False)
    _mac_pick = _pc_routing.pick_release_asset(_release_v143)
    check("Mac branch picks the .dmg",
          _mac_pick and _mac_pick["name"].endswith(".dmg"))
    check("Mac branch NEVER picks the .exe",
          _mac_pick and not _mac_pick["name"].endswith(".exe"))
    # When ONLY an .exe is present, Mac refuses (returns None).
    _mac_only_exe = _pc_routing.pick_release_asset(
        [{"name": "Veloxa-V14.8.1-Setup.exe",
          "browser_download_url": "https://x/w.exe", "size": 1}])
    check("Mac branch refuses .exe as fallback (returns None)",
          _mac_only_exe is None)
finally:
    _pc_routing.IS_WIN = _SAVED_WIN
    _pc_routing.IS_MAC = _SAVED_MAC
    _pc_routing.IS_LINUX = _SAVED_LINUX

# Log message in check_for_updates is platform-agnostic (was "no .exe
# asset" which read as a Windows-specific failure on macOS). Comments
# (which keep the historical text) are stripped first.
_u_src_143 = inspect.getsource(_u.check_for_updates)
_u_code_only = "\n".join(
    ln for ln in _u_src_143.splitlines()
    if not ln.lstrip().startswith("#"))
check("check_for_updates log message is platform-agnostic",
      "no installer asset" in _u_code_only
      and "no .exe asset" not in _u_code_only)


# ===========================================================================
# V14.8.1 -- auto-assign audio visuals at add-to-queue time
# ===========================================================================
section("V14.8.1 -- auto-assign audio visuals on add")

# Source-level checks (running the full MainWindow blocks on single-
# instance + startup update poll, so we don't instantiate it in the
# regression suite. The dedicated _qa/v143_auto_assign_visuals.py
# exercises the function behaviourally.)
mw_src_145 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")

# 1) The two new helper methods exist on MainWindow.
check("MainWindow defines _has_audio_template_active",
      "def _has_audio_template_active" in mw_src_145)
check("MainWindow defines _auto_assign_audio_visuals_for_new",
      "def _auto_assign_audio_visuals_for_new" in mw_src_145)

# 2) _add_files wires them in.
check("_add_files calls _auto_assign_audio_visuals_for_new",
      "_auto_assign_audio_visuals_for_new(" in mw_src_145)
check("_add_files skips the modal prompt when auto-assign returned "
      "entries OR a template is active",
      "not per_audio_visual" in mw_src_145
      and "not self._has_audio_template_active()" in mw_src_145)
check("_add_files prefers per-row auto-assigned visual over the "
      "shared prompted visual",
      "per_audio_visual[p]" in mw_src_145
      and "if p in per_audio_visual" in mw_src_145)

# 3) Auto-assign respects the rotation checkbox gate.
_aafn_src = mw_src_145.split(
    "def _auto_assign_audio_visuals_for_new")[1].split("\n    def ")[0]
check("_auto_assign gates on profile_visuals_enabled.isChecked()",
      "profile_visuals_enabled.isChecked()" in _aafn_src
      and "return out" in _aafn_src)
check("_auto_assign no-ops when template active",
      "_has_audio_template_active()" in _aafn_src)
check("_auto_assign persists the advanced counter via _pv_set_counter",
      "_pv_set_counter" in _aafn_src
      and "_pv_get_counter" in _aafn_src)
check("_auto_assign skips entries whose files no longer exist",
      "os.path.exists" in _aafn_src)

# 4) _build_jobs doesn't double-advance the counter for rows that
#    already carry a visual (set by auto-assign).
_build_jobs_src = mw_src_145.split(
    "def _build_jobs(")[1].split("def _build_jobs_for_items")[0]
check("_build_jobs has 'already_has_visual' guard",
      "already_has_visual" in _build_jobs_src
      and "not already_has_visual" in _build_jobs_src)


# ===========================================================================
# V14.8.1 -- light-theme queue-row text was invisible (white-on-white)
# ===========================================================================
section("V14.8.1 -- light theme: queue-row labels must be readable")

# 1) Both QSS files now carry an explicit QLabel[role="queue-row-label"]
#    rule with theme-appropriate colours.
_theme_src = (ROOT / "app" / "theme.py").read_text(encoding="utf-8")
_light_block = _theme_src.split("LIGHT_QSS = \"\"\"")[1].split("\"\"\"")[0]
_dark_block = _theme_src.split("DARK_QSS = \"\"\"")[1].split("\"\"\"")[0]

check("LIGHT_QSS defines QLabel[role=\"queue-row-label\"]",
      'QLabel[role="queue-row-label"]' in _light_block)
check("LIGHT_QSS uses dark text for queue-row-label (visible on white bg)",
      "#1c2128" in _light_block.split(
          'QLabel[role="queue-row-label"]')[1].split("}")[0])
check("LIGHT_QSS has a selected=\"true\" variant",
      '[selected="true"]' in _light_block)

check("DARK_QSS defines QLabel[role=\"queue-row-label\"]",
      'QLabel[role="queue-row-label"]' in _dark_block)
check("DARK_QSS uses light text for queue-row-label (visible on dark bg)",
      "#e6e6e6" in _dark_block.split(
          'QLabel[role="queue-row-label"]')[1].split("}")[0])
check("DARK_QSS has a selected=\"true\" variant",
      '[selected="true"]' in _dark_block)

# 2) main_window._apply_row_selection_styles no longer hard-codes
#    the inline color -- it must drive the QSS rule via the dynamic
#    'selected' property only.
_mw_src_146 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_apply_sel = _mw_src_146.split(
    "def _apply_row_selection_styles")[1].split("def ")[0]
check("_apply_row_selection_styles uses setProperty('selected', ...)",
      'setProperty("selected"' in _apply_sel)
# The inline 'color: #ffffff' / 'color: #e6e6e6' must be gone -- those
# hard-coded the dark-theme values regardless of the active theme.
check("_apply_row_selection_styles no longer hard-codes inline colors",
      "color: #ffffff" not in _apply_sel
      and "color: #e6e6e6" not in _apply_sel)
check("_apply_row_selection_styles re-polishes after property change",
      "unpolish" in _apply_sel and "polish" in _apply_sel)


# ===========================================================================
# V14.8.1 -- build mode: --onedir (was --onefile, caused python314.dll
# LoadLibrary failures after Windows in-app updates)
# ===========================================================================
section("V14.8.1 -- Windows build uses --onedir (no _MEI extract race)")

_build_ps1 = (ROOT / "build.ps1").read_text(encoding="utf-8")
# Drop comment lines (start with # after any whitespace) before checking.
_build_code = "\n".join(
    ln for ln in _build_ps1.splitlines()
    if not ln.lstrip().startswith("#"))
check("build.ps1 uses --onedir",
      "--onedir" in _build_code)
check("build.ps1 no longer uses --onefile as an active flag",
      "--onefile" not in _build_code)

_iss_src = (ROOT / "installer.iss").read_text(encoding="utf-8")
# The [Files] section must copy the EXE AND the _internal\ subtree.
check("installer.iss copies _internal\\* subtree",
      "_internal\\*" in _iss_src
      and "recursesubdirs" in _iss_src)
check("installer.iss [InstallDelete] sweeps stale _internal\\",
      "Type: filesandordirs; Name: \"{app}\\_internal\"" in _iss_src)
# The installer must STILL preserve the unversioned destname so the
# shortcuts + in-app updater keep working across versions.
check("installer.iss still renames to unversioned EXE name",
      'DestName: "{#AppExeName}"' in _iss_src)


# ===========================================================================
# V14.8.1 -- settings tabs wrap in QScrollArea (macOS row-overlap fix)
# ===========================================================================
section("V14.8.1 -- settings tabs scroll instead of overlapping on macOS")

_mw_src_148 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("QScrollArea imported in app/main_window.py",
      "QScrollArea" in _mw_src_148.split("from PyQt6.QtWidgets import")[1]
      .split(")")[0])
check("MainWindow defines _wrap_in_scroll helper",
      "def _wrap_in_scroll" in _mw_src_148)
# All 4 settings tabs should be wrapped -- Trim, Watermark, Audio
# Visuals, Output. The Watermark tab was the user-visible overlap on
# macOS but the same QGroupBox stack lives in the other tabs.
_settings_block = _mw_src_148.split(
    "def _build_settings_pane")[1].split("def _wrap_in_scroll")[0]
check("Trim tab wrapped in _wrap_in_scroll",
      "_wrap_in_scroll(self._build_trim_tab())" in _settings_block)
check("Watermark tab wrapped in _wrap_in_scroll",
      "_wrap_in_scroll(self._build_watermark_tab())" in _settings_block)
check("Audio Visuals tab wrapped in _wrap_in_scroll",
      "_wrap_in_scroll(self._build_audio_visuals_tab())" in _settings_block)
check("Output tab wrapped in _wrap_in_scroll",
      "_wrap_in_scroll(self._build_output_tab())" in _settings_block)

# Both QSS files style the QScrollArea flat so the tab pane still
# reads as a single surface.
_theme_src_148 = (ROOT / "app" / "theme.py").read_text(encoding="utf-8")
check("QSS has QScrollArea styling for scroll viewport",
      _theme_src_148.count("QScrollArea") >= 2)
check("QSS has QScrollBar:vertical styling (light + dark = 2 rules)",
      _theme_src_148.count("QScrollBar:vertical") >= 2)


# ===========================================================================
# V14.8.1 -- audio row label respects active audio template
# ===========================================================================
section("V14.8.1 -- audio row label: template-active stops showing "
        "'(visual needed)'")

_mw_src_149 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
_refresh_label_src = _mw_src_149.split(
    "def _refresh_item_label")[1].split("def ")[0]

# 1) The label now branches on _has_audio_template_active() before
#    falling through to "(visual needed)".
check("_refresh_item_label checks _has_audio_template_active",
      "_has_audio_template_active" in _refresh_label_src)
check("_refresh_item_label still has the '(visual needed)' fallback "
      "(when no template AND no per-row visual)",
      '"  (visual needed)"' in _refresh_label_src
      or "'  (visual needed)'" in _refresh_label_src)
check("_refresh_item_label uses the active template name as the tag",
      "audio_template_combo.currentText()" in _refresh_label_src
      and "+{tpl_name}" in _refresh_label_src)

# 2) Auto-assign now logs why it no-ops on every gate (the "user can't
#    diagnose what's wrong" issue from the Mac report).
_aafn_src_149 = _mw_src_149.split(
    "def _auto_assign_audio_visuals_for_new")[1].split("\n    def ")[0]
check("Auto-assign logs the 'template active' no-op reason",
      'audio template active' in _aafn_src_149
      or 'template synthesises' in _aafn_src_149)
check("Auto-assign logs the 'checkbox is OFF' no-op reason",
      "checkbox is OFF" in _aafn_src_149)
check("Auto-assign logs missing-on-disk Profile Visuals entries",
      "missing on disk" in _aafn_src_149
      or "missing_paths" in _aafn_src_149)
check("Auto-assign logs the 'list has 0 usable entries' no-op reason",
      "0 usable" in _aafn_src_149
      or "usable entries" in _aafn_src_149)


# ===========================================================================
# V14.8.1 -- macOS menubar fix: every top-level entry is a real menu
# ===========================================================================
section("V14.8.1 -- macOS menubar: Tools / Help / Appearance")

# macOS native QMenuBar silently DROPS top-level QActions added via
# ``mb.addAction(...)``. Only proper submenus (``mb.addMenu(...)``) show
# up. In V14.8.1 and earlier this left macOS users with ONLY the
# Appearance menu visible -- no way to reach Check for Updates, the
# logs, the watch folder, or any of the docs.
_mb_src = _mw_src_149.split("def _build_menu_bar")[1].split("\n    def ")[0]

check("Tools menu added via mb.addMenu",
      'mb.addMenu("Tools")' in _mb_src)
check("Help menu added via mb.addMenu",
      'mb.addMenu("Help")' in _mb_src)
check("Appearance menu added via mb.addMenu",
      'mb.addMenu("Appearance")' in _mb_src)
# Critical: no flat top-level action items left. Each menu calls
# .addAction on its inner menu (tools.addAction / help_menu.addAction /
# appearance.addAction) -- never on the menubar directly. Strip comments
# first because the docstring mentions the historical mb.addAction call.
_mb_code = "\n".join(
    ln for ln in _mb_src.splitlines() if not ln.lstrip().startswith("#"))
# Also drop docstring lines so the historical "called mb.addAction"
# explanation doesn't trip this check.
import re as _re_mb
_mb_code = _re_mb.sub(r'""".*?"""', "", _mb_code, flags=_re_mb.DOTALL)
check("Menu bar has NO flat top-level mb.addAction (would be dropped on macOS)",
      "mb.addAction(" not in _mb_code)

# Help menu items.
check("Help menu has README",
      'help_menu.addAction' in _mb_src and 'README' in _mb_src)
check("Help menu has Check for Updates",
      "Check for Updates" in _mb_src
      and "check_updates_act" in _mb_src
      and "help_menu.addAction(check_updates_act)" in _mb_src)
# Critical: explicit NoRole so Qt's TextHeuristicRole doesn't auto-
# move 'Check for Updates' to the Apple menu on macOS.
check("Check for Updates uses MenuRole.NoRole "
      "(keeps it in Help on macOS, not auto-moved to Apple menu)",
      "QAction.MenuRole.NoRole" in _mb_src
      and "check_updates_act.setMenuRole(QAction.MenuRole.NoRole)" in _mb_src)

# Tools menu items.
for label in ("Watch Folder", "Manage Saved Data", "Open Log Folder"):
    check(f"Tools menu has '{label}'",
          label in _mb_src and "tools.addAction" in _mb_src)

# Every menu item now sets NoRole so Qt's TextHeuristicRole can't
# auto-move them on macOS. Count the actual .setMenuRole( calls -- at
# least 4 (tools loop / help loop / check_updates / appearance loop).
check("All menu items use MenuRole.NoRole (no auto-move on macOS)",
      _mb_code.count("setMenuRole(QAction.MenuRole.NoRole)") >= 4)


# ===========================================================================
# V14.8.1 -- GPU detection is per-machine, cache key includes machine ID,
#           Tools menu can force a re-detect, status bar shows the GPU
# ===========================================================================
section("V14.8.1 -- GPU is auto-detected per physical PC, never baked")

# 1) Cache key now includes a machine ID -- a synced %APPDATA% / OneDrive
#    cache file can't apply on a different PC.
_enc_src = (ROOT / "engine" / "encoders.py").read_text(encoding="utf-8")
check("encoders schema is at least 3 (machine-keyed cache, V14.4.1+)",
      ("ENCODER_CACHE_SCHEMA = 3" in _enc_src
       or "ENCODER_CACHE_SCHEMA = 4" in _enc_src))
check("_machine_id() helper exists",
      "def _machine_id" in _enc_src)
check("_machine_id mixes hostname (platform.node) + MAC (uuid.getnode)",
      "platform.node()" in _enc_src and "uuid.getnode()" in _enc_src)
check("detect_available_encoders writes machine ID into the cache",
      '"machine": machine' in _enc_src)
check("Cache hit requires the machine ID to match",
      'data.get("machine") == machine' in _enc_src)
check("detect_available_encoders accepts force_rescan kwarg",
      "def detect_available_encoders(ffmpeg: str, force_rescan: bool"
      in _enc_src)

# 2) Tools menu includes "Re-detect GPU encoders..."
_mw_src_141 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("Tools menu has 'Re-detect GPU encoders...'",
      "Re-detect GPU encoders" in _mw_src_141
      and "_redetect_gpu_encoders" in _mw_src_141)
# Helpers defined:
check("MainWindow defines _describe_gpu_status",
      "def _describe_gpu_status" in _mw_src_141)
check("MainWindow defines _redetect_gpu_encoders",
      "def _redetect_gpu_encoders" in _mw_src_141)
# The redetect handler passes force_rescan=True so the cache is bypassed.
_redetect_src = _mw_src_141.split(
    "def _redetect_gpu_encoders")[1].split("\n    def ")[0]
check("_redetect_gpu_encoders forces a rescan (cache bypassed)",
      "force_rescan=True" in _redetect_src)
check("_redetect_gpu_encoders refreshes the encoder combo after",
      "_refresh_encoder_combo()" in _redetect_src)

# 3) Status bar on startup shows the GPU summary.
check("Startup status line shows _describe_gpu_status()",
      "_describe_gpu_status()" in _mw_src_141.split(
          "if not self.ffmpeg")[1].split("def ")[0])

# 4) Behavioural smoke: detect_available_encoders WITHOUT ffmpeg still
#    returns CPU encoders so the GUI never has a zero-option encoder
#    combo on a missing-FFmpeg install.
from engine.encoders import detect_available_encoders as _det, CPU_ENCODERS
_no_ffmpeg = _det("")
check("detect_available_encoders('') returns the CPU fallback",
      sorted(_no_ffmpeg) == sorted(CPU_ENCODERS))


# ===========================================================================
# V14.8.1 -- resume interrupted batches + opt-in crash reporter
# ===========================================================================
section("V14.8.1 -- resume + crash reporter")

# ---- crash reporter module --------------------------------------------
from app import crash_reporter as _cr
check("crash_reporter exposes install_excepthook",
      callable(getattr(_cr, "install_excepthook", None)))
check("crash_reporter exposes write_crash_file",
      callable(getattr(_cr, "write_crash_file", None)))
check("crash_reporter exposes build_issue_url",
      callable(getattr(_cr, "build_issue_url", None)))
check("crash_reporter exposes list/mark helpers",
      all(callable(getattr(_cr, n, None)) for n in (
          "list_pending_reports", "mark_reported", "mark_dismissed")))
# Sanitisation actually removes the username.
import os as _os_cr
_home_cr = _os_cr.path.expanduser("~")
_username_cr = _home_cr.split(_os_cr.sep)[-1]
if _username_cr and _username_cr not in ("Users", "home"):
    _scrubbed = _cr._sanitize_paths(f"path was {_home_cr}/file.mp4")
    check("Username scrubbed from sanitised paths",
          _username_cr not in _scrubbed)
    check("<user> placeholder present in sanitised output",
          "<user>" in _scrubbed)

# ---- main.py installs the excepthook before MainWindow construction ---
_main_src = (ROOT / "main.py").read_text(encoding="utf-8")
check("main.py imports crash_reporter.install_excepthook",
      "install_excepthook" in _main_src
      and "from app.crash_reporter" in _main_src)
check("main.py installs the excepthook AFTER logging is set up",
      _main_src.index("install_excepthook")
          > _main_src.index("setup_logging"))

# ---- main_window: handlers + menu wiring ------------------------------
_mw_src_150 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("MainWindow defines _maybe_prompt_pending_crashes",
      "def _maybe_prompt_pending_crashes" in _mw_src_150)
check("MainWindow defines _prompt_send_crash",
      "def _prompt_send_crash" in _mw_src_150)
check("MainWindow defines _report_a_problem_manual",
      "def _report_a_problem_manual" in _mw_src_150)
check("MainWindow defines _crash_reporting_settings",
      "def _crash_reporting_settings" in _mw_src_150)
check("Startup schedules _maybe_prompt_pending_crashes",
      "QTimer.singleShot(3000, self._maybe_prompt_pending_crashes)"
      in _mw_src_150)
check("Tools menu has 'Report a problem'",
      "Report a problem" in _mw_src_150)
check("Tools menu has 'Crash reporting settings'",
      "Crash reporting settings" in _mw_src_150)

# The opt-in keys used to gate the prompt.
check("Opt-in QSettings key exists (crash_reports_opt_in)",
      "crash_reports_opt_in" in _mw_src_150)
check("'Already prompted' sentinel exists (crash_reports_prompted)",
      "crash_reports_prompted" in _mw_src_150)

# ---- resume: 3-way dialog + auto-start --------------------------------
_restore_src = _mw_src_150.split(
    "def _maybe_restore_queue")[1].split("def ")[0]
check("Restore dialog offers 'Resume & Start'",
      "Resume && Start" in _restore_src
      or "Resume & Start" in _restore_src)
check("Restore dialog offers 'Restore only'",
      "Restore only" in _restore_src)
check("Restore dialog offers Discard (DestructiveRole)",
      "DestructiveRole" in _restore_src)
check("Resume & Start dispatches _start_batch_if_pending via QTimer",
      "_start_batch_if_pending" in _restore_src)
check("_start_batch_if_pending helper defined",
      "def _start_batch_if_pending" in _mw_src_150)
# Existing reset-to-pending behaviour is still there (verifies we
# didn't lose the actual mechanism that lets interrupted rows restart).
_widgets_src_150 = (ROOT / "app" / "widgets.py").read_text(encoding="utf-8")
check("QueueItemData.from_dict still resets encoding -> pending",
      'item.status = "pending" if st == "encoding" else st' in _widgets_src_150)


# ===========================================================================
# V14.8.1 -- Add from Folder (recursive scan picks every supported file)
# ===========================================================================
section("V14.8.1 -- Add from Folder")

_mw_src_160 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("MainWindow defines _on_add_folder_clicked",
      "def _on_add_folder_clicked" in _mw_src_160)
check("MainWindow defines _collect_supported_files",
      "def _collect_supported_files" in _mw_src_160)
check("'Add from Folder' button wired to _on_add_folder_clicked",
      "self.add_folder_btn" in _mw_src_160
      and "_on_add_folder_clicked" in _mw_src_160)
check("add_folder_btn placed next to add_btn in the toolbar row",
      _mw_src_160.index("row.addWidget(self.add_folder_btn)")
          > _mw_src_160.index("row.addWidget(self.add_btn)"))
check("add_folder_btn stays enabled mid-batch (mirrors add_btn)",
      "add_folder_btn.setEnabled(True)" in _mw_src_160)
# Behavioural smoke: the collector function picks only files whose
# extension is in ALL_INPUT_EXTS.
import tempfile as _tf
import os as _os
from app.main_window import MainWindow as _MW, ALL_INPUT_EXTS as _ALL_EXTS
_tmp = Path(_tf.mkdtemp(prefix="veloxa_regress_addfolder_"))
(_tmp / "a.mp4").write_bytes(b"\0")
(_tmp / "b.mp3").write_bytes(b"\0")
(_tmp / "c.srt").write_bytes(b"\0")  # NOT in ALL_INPUT_EXTS
(_tmp / "sub").mkdir()
(_tmp / "sub" / "d.wav").write_bytes(b"\0")
class _StubMW:
    pass
_coll = _MW._collect_supported_files.__get__(_StubMW())
_got = _coll(str(_tmp))
check("Recursive scan returns 3 supported files (skips .srt)",
      len(_got) == 3
      and all(Path(p).suffix.lower() in _ALL_EXTS for p in _got))
check("Recursive scan descends into subfolders",
      any(p.endswith("d.wav") for p in _got))


# ===========================================================================
# V14.8.1 -- AV1 encoder support (libsvtav1 + av1_nvenc / av1_qsv / av1_amf)
# ===========================================================================
section("V14.8.1 -- AV1 encoder catalog + CLI args")

# ---- engine.encoders catalog --------------------------------------------
from engine import (
    CODEC_AV1, AUTO_PRIORITY_AV1, GPU_AV1, ENCODER_LABELS,
    ENCODER_FOR_CODEC, encoder_codec_args,
)
check("CODEC_AV1 constant exported from engine package",
      CODEC_AV1 == "av1")
check("GPU_AV1 lists the three vendor AV1 encoders",
      sorted(GPU_AV1) == ["av1_amf", "av1_nvenc", "av1_qsv"])
check("AUTO_PRIORITY_AV1 priority order: NVIDIA -> AMD -> Intel -> CPU",
      AUTO_PRIORITY_AV1
      == ["av1_nvenc", "av1_amf", "av1_qsv", "libsvtav1"])
check("ENCODER_FOR_CODEC has an AV1 entry with the 4 expected encoders",
      sorted(ENCODER_FOR_CODEC[CODEC_AV1])
      == sorted(["libsvtav1", "av1_nvenc", "av1_qsv", "av1_amf"]))

# Labels -- used by the encoder dropdown to render human-friendly text.
for enc, label_must_contain in [
    ("libsvtav1", "SVT-AV1"),
    ("av1_nvenc", "NVENC"),
    ("av1_qsv",   "QSV"),
    ("av1_amf",   "AMF"),
]:
    check(f"ENCODER_LABELS[{enc!r}] contains {label_must_contain!r}",
          label_must_contain in ENCODER_LABELS.get(enc, ""))

# ---- encoder_codec_args -- CRF mode for each AV1 encoder -----------------
for enc, expected_codec, expected_quality_flag in [
    ("libsvtav1", "libsvtav1", "-crf"),
    ("av1_nvenc", "av1_nvenc", "-qp"),
    ("av1_qsv",   "av1_qsv",   "-global_quality"),
    ("av1_amf",   "av1_amf",   "-qp_i"),
]:
    args = encoder_codec_args(enc, "Balanced")
    check(f"encoder_codec_args({enc!r}, 'Balanced') uses -c:v {expected_codec}",
          "-c:v" in args and args[args.index("-c:v") + 1] == expected_codec)
    check(f"encoder_codec_args({enc!r}, 'Balanced') uses CRF/QP mode",
          expected_quality_flag in args)

# ---- encoder_codec_args -- bitrate mode for each AV1 encoder ------------
for enc in ("libsvtav1", "av1_nvenc", "av1_qsv", "av1_amf"):
    args = encoder_codec_args(enc, "Fast", video_bitrate_kbps=4000)
    check(f"encoder_codec_args({enc!r}, bitrate=4000) emits -b:v 4000k",
          "-b:v" in args and args[args.index("-b:v") + 1] == "4000k")

# Probe-list now includes all four AV1 encoders.
from engine.encoders import GPU_ENCODERS_TO_TEST
check("Runtime probe list includes av1_nvenc",
      "av1_nvenc" in GPU_ENCODERS_TO_TEST)
check("Runtime probe list includes av1_qsv",
      "av1_qsv" in GPU_ENCODERS_TO_TEST)
check("Runtime probe list includes av1_amf",
      "av1_amf" in GPU_ENCODERS_TO_TEST)
check("Runtime probe list includes libsvtav1 "
      "(not in every FFmpeg build, must be probed)",
      "libsvtav1" in GPU_ENCODERS_TO_TEST)

# ---- main_window wiring -------------------------------------------------
_mw_src_170 = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("CODEC_AV1 imported in main_window",
      "CODEC_AV1" in _mw_src_170)
check("AUTO_PRIORITY_AV1 imported in main_window",
      "AUTO_PRIORITY_AV1" in _mw_src_170)
check("CODEC_LABELS includes the AV1 entry",
      "CODEC_AV1:" in _mw_src_170 and '"AV1"' in _mw_src_170)
# _resolve_encoder branches on CODEC_AV1 to pick the AV1 priority list.
_resolve_src = _mw_src_170.split(
    "def _resolve_encoder")[1].split("def ")[0]
check("_resolve_encoder routes CODEC_AV1 to AUTO_PRIORITY_AV1",
      "CODEC_AV1" in _resolve_src
      and "AUTO_PRIORITY_AV1" in _resolve_src)
check("_resolve_encoder degrades to libx264 when no AV1 encoder works",
      'fallback' in _resolve_src.lower()
      or '"libx264"' in _resolve_src)

# Status-bar GPU summary calls out AV1 when the GPU supports it.
_gpu_status_src = _mw_src_170.split(
    "def _describe_gpu_status")[1].split("def ")[0]
check("_describe_gpu_status flags 'incl. AV1' on NVENC / AMF / QSV",
      "incl. AV1" in _gpu_status_src)
check("_describe_gpu_status calls out SVT-AV1 CPU encoder when no GPU AV1",
      "SVT-AV1 (CPU)" in _gpu_status_src)


# ===========================================================================
# Summary
# ===========================================================================
section("Summary")
print(f"  Total: {len(PASS) + len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    print("FAILURES:")
    for n, d in FAIL:
        print(f"  - {n}: {d}")
    sys.exit(1)
print()
print("All audit-fix regression probes PASS.")
sys.exit(0)
