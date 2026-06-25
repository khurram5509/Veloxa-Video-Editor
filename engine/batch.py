"""Per-file `JobRunner` (QThread) plus `BatchManager` orchestration.

This is the bulk-processing engine. ``BatchManager`` accepts a list of jobs
and a max-concurrency value, spawns ``JobRunner`` threads up to that limit,
and emits progress / completion signals. All FFmpeg interaction happens via
the runners; the manager only schedules.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .ffmpeg import (
    CREATE_NO_WINDOW,
    probe_duration,
    probe_resolution,
)
from .filters import build_filter, build_audio_filter
from .encoders import encoder_codec_args, audio_codec_args, hwaccel_for_encoder


log = logging.getLogger("veloxa.engine")


# ============================================================== JobRunner

class JobRunner(QThread):
    """Encodes one file. Many can run concurrently under a BatchManager.

    Job tuple shape: ``(idx, src, dst, kind, visual_path, visual_kind)``
    where ``kind`` is ``"video"`` or ``"audio"`` and the visual fields are
    ignored for video jobs.
    """

    progress = pyqtSignal(int, float)         # idx, percent 0..100
    eta_update = pyqtSignal(int, float)       # idx, eta seconds
    job_finished = pyqtSignal(int, bool, str) # idx, success, message

    def __init__(self, idx: int, src: str, dst: str, kind: str,
                 visual_path: str, visual_kind: str,
                 ffmpeg: str, ffprobe: str, opts: dict,
                 per_job_opts: dict | None = None):
        super().__init__()
        self.idx = idx
        self.src = src
        self.dst = dst
        self.kind = kind
        self.visual_path = visual_path
        self.visual_kind = visual_kind
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        # Per-job overrides (e.g. clip_offset_s / clip_duration_s used by the
        # split-on-length feature) take priority over the shared opts dict.
        if per_job_opts:
            self.opts = {**opts, **per_job_opts}
        else:
            self.opts = opts
        self._proc = None
        self._cancel = False
        self._t_start = 0.0
        # V12.3.5: optional cached pre-scaled image visual, cleaned up
        # at end of ``run()``.
        self._tmp_prescaled = None

    def cancel(self):
        self._cancel = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _cpu_threads_flag(self) -> list:
        """V14.3.0: when this job is running in the parallel CPU slot
        (``opts["_cpu_slot"] is True``) and using libx264/libx265,
        return ``["-threads", "N"]`` where N leaves headroom for the
        OS / GUI / the parallel GPU job. Empty list otherwise."""
        if not self.opts.get("_cpu_slot"):
            return []
        encoder = (self.opts.get("encoder") or "").lower()
        if encoder not in ("libx264", "libx265"):
            return []
        try:
            from .system_resources import cpu_encoder_thread_count
        except Exception:
            return []
        n = cpu_encoder_thread_count(parallel_gpu_running=True)
        return ["-threads", str(n)]

    def run(self):
        self._t_start = time.monotonic()
        log.info("Job %d START [%s] %s -> %s",
                 self.idx, self.kind, self.src, self.dst)
        try:
            if self.kind == "audio":
                ok, msg = self._encode_audio_to_video()
            else:
                ok, msg = self._encode_video()
        except Exception as e:
            ok, msg = False, f"Internal error: {e}"
            log.exception("Job %d crashed", self.idx)

        elapsed = time.monotonic() - self._t_start
        if ok:
            try:
                size = os.path.getsize(self.dst) if os.path.exists(self.dst) else 0
            except OSError:
                size = 0
            log.info("Job %d OK in %.1fs (%.1f MB) %s",
                     self.idx, elapsed, size / 1_048_576, self.dst)
        else:
            log.warning("Job %d FAIL in %.1fs: %s", self.idx, elapsed, msg)

        # V12.3.5: drop any cached pre-scaled image. Best-effort —
        # if cleanup fails it's a small PNG in %TEMP%, OS will sweep.
        if self._tmp_prescaled and os.path.exists(self._tmp_prescaled):
            try:
                os.remove(self._tmp_prescaled)
            except OSError:
                pass
            self._tmp_prescaled = None

        self.job_finished.emit(self.idx, ok, msg)

    # ---- video encode -----------------------------------------

    def _encode_video(self):
        duration = probe_duration(self.ffprobe, self.src)
        src_w, src_h = probe_resolution(self.ffprobe, self.src)
        if duration <= 0:
            return False, "Could not read video duration"

        # Per-job clip overrides (used by split-on-length) bypass the
        # whole-clip trim math and pull a specific window out of the source.
        clip_off = float(self.opts.get("clip_offset_s") or 0.0)
        clip_dur = float(self.opts.get("clip_duration_s") or 0.0)
        if clip_dur > 0:
            start = max(0.0, clip_off)
            seg = min(clip_dur, max(0.0, duration - start))
        else:
            start = max(0.0, float(self.opts.get("trim_start", 0)))
            end_trim = max(0.0, float(self.opts.get("trim_end", 0)))
            seg = duration - start - end_trim
        if seg <= 0.05:
            return False, f"Trim too aggressive ({duration:.1f}s video)"

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]

        # Hardware decode for the main video input (subsequent inputs
        # like watermark images don't benefit and can break with cuda).
        encoder = self.opts.get("encoder", "libx264")
        if self.opts.get("hw_decode", True):
            hwaccel = hwaccel_for_encoder(encoder)
            if hwaccel:
                cmd += ["-hwaccel", hwaccel]

        cmd += ["-ss", f"{start:.3f}", "-t", f"{seg:.3f}", "-i", self.src]

        image_wm_idx = video_wm_idx = None
        next_idx = 1
        wm_path = self.opts.get("watermark_path")
        if wm_path and os.path.exists(wm_path):
            cmd += ["-i", wm_path]
            image_wm_idx = next_idx
            next_idx += 1
        vid_wm_path = self.opts.get("video_wm_path")
        if vid_wm_path and os.path.exists(vid_wm_path):
            # -stream_loop -1 makes a short WM video repeat indefinitely so
            # it covers the full output duration.
            cmd += ["-stream_loop", "-1", "-i", vid_wm_path]
            video_wm_idx = next_idx
            next_idx += 1

        fc, last = build_filter(self.opts, src_w, src_h, for_preview=False,
                                image_wm_idx=image_wm_idx,
                                video_wm_idx=video_wm_idx)
        if fc:
            cmd += ["-filter_complex", fc, "-map", last]
        else:
            cmd += ["-map", "0:v"]

        # Output audio length after trim + speed change, so audio fades
        # land at the right place.
        speed = float(self.opts.get("speed", 1.0) or 1.0)
        out_duration = seg / max(speed, 1e-3)

        cmd += ["-map", "0:a?"]
        cmd += encoder_codec_args(
            encoder,
            self.opts.get("speed_tier", "Balanced"),
            video_bitrate_kbps=self.opts.get("video_bitrate_kbps", 0))
        # V14.3.0: cap libx264/libx265 thread count when running as the
        # parallel CPU slot so the GPU job + GUI still have CPU time.
        cmd += self._cpu_threads_flag()
        cmd += audio_codec_args(self.opts, output_duration_s=out_duration)
        # V12.3: when this profile has an intro and/or outro configured,
        # encode the main video to a temp file first; ``_run_ffmpeg``
        # detects the trailing ``__concat_target__`` sentinel below and
        # routes through the 2-pass concat path. Otherwise write
        # directly to self.dst as before.
        intro = (self.opts.get("intro_path") or "").strip()
        outro = (self.opts.get("outro_path") or "").strip()
        apply_intro = (intro and os.path.exists(intro)
                       and self.opts.get("apply_intro", True))
        apply_outro = (outro and os.path.exists(outro)
                       and self.opts.get("apply_outro", True))
        if apply_intro or apply_outro:
            main_tmp = self.dst + ".main.mp4"
            cmd += ["-movflags", "+faststart",
                    "-progress", "pipe:1", "-stats_period", "0.1", "-nostats",
                    main_tmp]
            # V12.3 audit fix (EDGE-2): split progress 0-50 main / 50-100
            # concat so the bar doesn't snap to 0% during the concat pass.
            ok, msg = self._run_ffmpeg(cmd, seg,
                                        cancel_cleanup_target=main_tmp,
                                        pct_offset=0.0, pct_scale=0.5)
            if not ok:
                # V12.3 audit fix (BUG-2): clean up the main temp on
                # main-encode failure / cancel so we don't leak
                # half-finished `<dst>.main.mp4` files into the user's
                # output folder. _run_ffmpeg's own cancel branch deletes
                # whatever was passed as cancel_cleanup_target.
                try:
                    if os.path.exists(main_tmp):
                        os.remove(main_tmp)
                except OSError:
                    pass
                return ok, msg
            return self._concat_intro_outro(main_tmp, self.dst,
                                            intro if apply_intro else "",
                                            outro if apply_outro else "")
        cmd += ["-movflags", "+faststart",
                "-progress", "pipe:1", "-stats_period", "0.1", "-nostats",
                self.dst]
        return self._run_ffmpeg(cmd, seg)

    # ---- V12.3.5 perf: image-visual pre-scale -----------------

    def _prescale_image_visual(self, visual_path: str,
                               target_w: int, target_h: int):
        """Pre-scale ``visual_path`` to ``target_w x target_h`` and
        return ``(path_to_use, is_at_target_dims, tmp_to_cleanup)``.

        Three cases:
          * source already at target dims  →
              (visual_path, True,  None) — caller can skip per-frame
              scale+pad.
          * source scaled successfully     →
              (tmp_png, True, tmp_png) — caller uses the cached PNG and
              cleans it up when the job finishes.
          * probe or scale failed          →
              (visual_path, False, None) — caller falls back to the
              traditional per-frame filter chain.

        Why: with ``-loop 1 -i image`` the encoder receives N identical
        frames per second of audio. The default filter graph does
        ``scale+pad`` per output frame even though every frame produces
        the same pixels — pure waste at 25 fps for a 20-minute clip
        that's 30,000 redundant scales. Doing it once here lets NVENC
        run much closer to its rated throughput.
        """
        if target_w <= 0 or target_h <= 0:
            return visual_path, False, None
        try:
            src_w, src_h = probe_resolution(self.ffprobe, visual_path)
        except Exception:
            src_w, src_h = 0, 0
        # Source is already at target size — no pre-scale needed, but
        # we still want the caller to skip the per-frame scale filter.
        if src_w == target_w and src_h == target_h:
            return visual_path, True, None
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f"veloxa_visual_pre_{os.getpid()}_{self.idx}_",
            suffix=".png")
        os.close(tmp_fd)  # we just want the unique filename; ffmpeg writes it
        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", visual_path,
            "-vf", (f"scale={target_w}:{target_h}:"
                    f"force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"setsar=1"),
            "-frames:v", "1",
            tmp_path,
        ]
        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=30,
                creationflags=CREATE_NO_WINDOW)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Job %d pre-scale failed (%s); using original",
                        self.idx, exc)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return visual_path, False, None
        if r.returncode != 0 or not os.path.exists(tmp_path):
            log.warning("Job %d pre-scale rc=%d; using original",
                        self.idx, r.returncode)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return visual_path, False, None
        log.info("Job %d pre-scaled image %dx%d -> %dx%d (%s)",
                 self.idx, src_w, src_h, target_w, target_h, tmp_path)
        return tmp_path, True, tmp_path

    # ---- V14.0: audio + real-time audio-visual template -> video --

    def _encode_audio_with_template(self, tpl):
        """V14.0: encode an audio file into video using one of the
        real-time FFmpeg-filter-based audio visualisations registered
        in :mod:`engine.audio_templates`. The template's filter graph
        produces the video stream directly from the audio — no
        user-supplied visual is required.

        The encode tail (encoder args, audio codec, intro/outro concat)
        mirrors ``_encode_audio_to_video`` so all the existing profile
        knobs (bitrate, fade, loudnorm, intro/outro, output dims) work
        unchanged.
        """
        duration = probe_duration(self.ffprobe, self.src)
        if duration <= 0:
            return False, "Could not read audio duration"

        clip_off = float(self.opts.get("clip_offset_s") or 0.0)
        clip_dur = float(self.opts.get("clip_duration_s") or 0.0)
        if clip_dur > 0:
            start = max(0.0, clip_off)
            seg = min(clip_dur, max(0.0, duration - start))
        else:
            start = max(0.0, float(self.opts.get("trim_start", 0)))
            end_trim = max(0.0, float(self.opts.get("trim_end", 0)))
            seg = duration - start - end_trim
        if seg <= 0.05:
            return False, f"Trim too aggressive ({duration:.1f}s audio)"

        target_w = int(self.opts.get("out_w") or 1920)
        target_h = int(self.opts.get("out_h") or 1080)
        if target_w <= 0 or target_h <= 0:
            target_w, target_h = 1920, 1080

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        cmd += ["-ss", f"{start:.3f}", "-t", f"{seg:.3f}", "-i", self.src]

        # Build the template's filter graph from the audio input.
        fc, vout_label = tpl.build_filter("0:a", target_w, target_h, self.opts)
        cmd += ["-filter_complex", fc,
                "-map", vout_label, "-map", "[aout]"]

        encoder = self.opts.get("encoder", "libx264")
        cmd += encoder_codec_args(
            encoder,
            self.opts.get("speed_tier", "Balanced"),
            video_bitrate_kbps=self.opts.get("video_bitrate_kbps", 0))
        # V14.3.0: cap libx264/libx265 thread count when running as the
        # parallel CPU slot so the GPU job + GUI still have CPU time.
        cmd += self._cpu_threads_flag()
        speed = float(self.opts.get("speed", 1.0) or 1.0)
        out_duration = seg / max(speed, 1e-3)
        cmd += audio_codec_args(self.opts, output_duration_s=out_duration)
        cmd += ["-r", "30", "-shortest"]

        # Same intro/outro concat path as the other audio-to-video flow.
        intro = (self.opts.get("intro_path") or "").strip()
        outro = (self.opts.get("outro_path") or "").strip()
        apply_intro = (intro and os.path.exists(intro)
                       and self.opts.get("apply_intro", True))
        apply_outro = (outro and os.path.exists(outro)
                       and self.opts.get("apply_outro", True))
        if apply_intro or apply_outro:
            main_tmp = self.dst + ".main.mp4"
            cmd += ["-movflags", "+faststart",
                    "-progress", "pipe:1", "-stats_period", "0.1", "-nostats", main_tmp]
            ok, msg = self._run_ffmpeg(cmd, seg,
                                        cancel_cleanup_target=main_tmp,
                                        pct_offset=0.0, pct_scale=0.5)
            if not ok:
                try:
                    if os.path.exists(main_tmp):
                        os.remove(main_tmp)
                except OSError:
                    pass
                return ok, msg
            return self._concat_intro_outro(main_tmp, self.dst,
                                            intro if apply_intro else "",
                                            outro if apply_outro else "")
        cmd += ["-movflags", "+faststart",
                "-progress", "pipe:1", "-stats_period", "0.1", "-nostats", self.dst]
        return self._run_ffmpeg(cmd, seg)

    # ---- audio + image/video visual -> video ------------------

    def _encode_audio_to_video(self):
        # V14.0: real-time audio template short-circuit. When a template
        # like "spectrum_bars" or "neon_ring" is selected the visual is
        # synthesised from the audio itself, so no user-supplied visual
        # is required. Templates are looked up here and, when present,
        # ``_encode_audio_with_template`` runs an alternative pipeline.
        template_key = (self.opts.get("audio_template") or "").strip()
        if template_key and template_key != "none":
            from .audio_templates import get_template
            tpl = get_template(template_key)
            if tpl is not None:
                return self._encode_audio_with_template(tpl)

        if not self.visual_path or not os.path.exists(self.visual_path):
            return False, "No visual set for audio file"

        duration = probe_duration(self.ffprobe, self.src)
        if duration <= 0:
            return False, "Could not read audio duration"

        clip_off = float(self.opts.get("clip_offset_s") or 0.0)
        clip_dur = float(self.opts.get("clip_duration_s") or 0.0)
        if clip_dur > 0:
            start = max(0.0, clip_off)
            seg = min(clip_dur, max(0.0, duration - start))
        else:
            start = max(0.0, float(self.opts.get("trim_start", 0)))
            end_trim = max(0.0, float(self.opts.get("trim_end", 0)))
            seg = duration - start - end_trim
        if seg <= 0.05:
            return False, f"Trim too aggressive ({duration:.1f}s audio)"

        target_w = int(self.opts.get("out_w") or 1920)
        target_h = int(self.opts.get("out_h") or 1080)
        if target_w <= 0 or target_h <= 0:
            target_w, target_h = 1920, 1080

        # V12.3.5 perf: for an IMAGE visual the scale+pad filter runs
        # identically on every output frame — a 20-minute encode at 25
        # fps means 30,000 redundant CPU scale ops while NVENC sits
        # mostly idle waiting for frames. Pre-scale the image once to
        # target dims and tell the filter graph to skip the per-frame
        # scale via ``visual_pre_scaled=True``. Frees the CPU bottleneck
        # so the encoder can run closer to its rated speed (visible as
        # higher GPU% in Task Manager).
        visual_input_path = self.visual_path
        visual_pre_scaled = False
        if self.visual_kind == "image":
            visual_input_path, visual_pre_scaled, tmp = (
                self._prescale_image_visual(
                    self.visual_path, target_w, target_h))
            self._tmp_prescaled = tmp  # may be None

        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        # V12.3.3 perf: enable hardware decode for the visual input. The
        # video path already does this; without it here the CPU has to
        # decode the looping visual video while the GPU encoder sits
        # idle waiting for frames (visible as low GPU utilisation in
        # Task Manager when encoding audio + video visual). Images are
        # unaffected — single-frame loop runs the same speed either way,
        # and ``-hwaccel`` is harmless when applied to a PNG/JPG input.
        encoder = self.opts.get("encoder", "libx264")
        if self.opts.get("hw_decode", True):
            hwaccel = hwaccel_for_encoder(encoder)
            if hwaccel:
                cmd += ["-hwaccel", hwaccel]
        if self.visual_kind == "video":
            cmd += ["-stream_loop", "-1", "-i", visual_input_path]
        else:
            cmd += ["-loop", "1", "-i", visual_input_path]

        cmd += ["-ss", f"{start:.3f}", "-t", f"{seg:.3f}", "-i", self.src]

        image_wm_idx = video_wm_idx = None
        next_idx = 2
        wm_path = self.opts.get("watermark_path")
        if wm_path and os.path.exists(wm_path):
            cmd += ["-i", wm_path]
            image_wm_idx = next_idx
            next_idx += 1
        vid_wm_path = self.opts.get("video_wm_path")
        if vid_wm_path and os.path.exists(vid_wm_path):
            cmd += ["-stream_loop", "-1", "-i", vid_wm_path]
            video_wm_idx = next_idx
            next_idx += 1

        fc, last = build_audio_filter(self.opts, target_w, target_h,
                                      for_preview=False,
                                      image_wm_idx=image_wm_idx,
                                      video_wm_idx=video_wm_idx,
                                      visual_pre_scaled=visual_pre_scaled)
        cmd += ["-filter_complex", fc, "-map", last, "-map", "1:a"]
        cmd += encoder_codec_args(
            encoder,
            self.opts.get("speed_tier", "Balanced"),
            video_bitrate_kbps=self.opts.get("video_bitrate_kbps", 0))
        # V14.3.0: cap libx264/libx265 thread count when running as the
        # parallel CPU slot so the GPU job + GUI still have CPU time.
        cmd += self._cpu_threads_flag()
        # Audio length after trim + speed change for accurate fade-out.
        speed = float(self.opts.get("speed", 1.0) or 1.0)
        out_duration = seg / max(speed, 1e-3)
        cmd += audio_codec_args(self.opts, output_duration_s=out_duration)
        if self.visual_kind != "video":
            cmd += ["-r", "25"]
        # V12.3: intro/outro concat support (same as video path).
        intro = (self.opts.get("intro_path") or "").strip()
        outro = (self.opts.get("outro_path") or "").strip()
        apply_intro = (intro and os.path.exists(intro)
                       and self.opts.get("apply_intro", True))
        apply_outro = (outro and os.path.exists(outro)
                       and self.opts.get("apply_outro", True))
        if apply_intro or apply_outro:
            main_tmp = self.dst + ".main.mp4"
            cmd += ["-movflags", "+faststart", "-shortest",
                    "-progress", "pipe:1", "-stats_period", "0.1", "-nostats", main_tmp]
            # V12.3 audit fix (EDGE-2): 0-50 main / 50-100 concat split.
            ok, msg = self._run_ffmpeg(cmd, seg,
                                        cancel_cleanup_target=main_tmp,
                                        pct_offset=0.0, pct_scale=0.5)
            if not ok:
                # V12.3 audit fix (BUG-2): same temp-cleanup as the
                # video path.
                try:
                    if os.path.exists(main_tmp):
                        os.remove(main_tmp)
                except OSError:
                    pass
                return ok, msg
            return self._concat_intro_outro(main_tmp, self.dst,
                                            intro if apply_intro else "",
                                            outro if apply_outro else "")
        cmd += ["-movflags", "+faststart",
                "-shortest",
                "-progress", "pipe:1", "-stats_period", "0.1", "-nostats",
                self.dst]
        return self._run_ffmpeg(cmd, seg)

    # ---- subprocess driver ------------------------------------

    def _run_ffmpeg(self, cmd: list, total_seconds: float,
                    cancel_cleanup_target: str = None,
                    pct_offset: float = 0.0, pct_scale: float = 1.0):
        # V14.8.0: power-user FFmpeg-args passthrough. Anything in
        # ``opts["custom_ffmpeg_args"]`` is parsed with shlex.split
        # (so quoted values survive) and spliced just before the
        # output file — every cmd construction in this module ends
        # ``... -nostats <output_path>``, so the last cmd element is
        # always the destination we want the custom flags to apply
        # to. Doing the splice here means every call site picks it
        # up without seven near-identical edits.
        raw_custom = (self.opts.get("custom_ffmpeg_args") or "").strip()
        if raw_custom and len(cmd) >= 2:
            try:
                import shlex
                extra = shlex.split(raw_custom)
            except ValueError as exc:
                log.warning("Job %d: custom_ffmpeg_args parse error "
                            "(%s); ignoring user override", self.idx, exc)
                extra = []
            if extra:
                cmd = list(cmd[:-1]) + extra + [cmd[-1]]
                log.info("Job %d: spliced %d custom ffmpeg arg(s) "
                         "before output", self.idx, len(extra))
        log.debug("Job %d cmd: %s", self.idx, " ".join(repr(a) for a in cmd))
        # V14.3.0: CPU-slot jobs run with below-normal process priority
        # so they yield to the GUI thread and the OS scheduler under
        # contention. The system_resources helper returns the right
        # subprocess kwargs per platform — creationflags on Windows,
        # preexec_fn(os.nice +5) on Unix.
        extra_popen = {}
        if self.opts.get("_cpu_slot"):
            try:
                from .system_resources import low_priority_popen_kwargs
                extra_popen.update(low_priority_popen_kwargs())
            except Exception as exc:
                log.info("Job %d: low-prio kwargs unavailable: %s",
                         self.idx, exc)
        # Merge our existing CREATE_NO_WINDOW with whatever low-prio
        # added (Windows uses creationflags for both).
        if "creationflags" in extra_popen:
            extra_popen["creationflags"] |= CREATE_NO_WINDOW
        else:
            extra_popen["creationflags"] = CREATE_NO_WINDOW
        try:
            # V14.3.1 fix: bufsize=0 + binary mode bypasses Python's
            # text-mode io.TextIOWrapper buffer. With ``text=True,
            # bufsize=1`` (the previous setting), ffmpeg's progress
            # lines sat in Python's ~8 KB internal read-ahead buffer
            # until the buffer filled (~20 s of encoding) or ffmpeg
            # exited. Short encodes finished before the buffer filled,
            # so the user saw the per-row progress bar jump straight
            # from 0 % to 100 % at the end. Reading raw bytes via
            # ``readline()`` flushes per line.
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **extra_popen,
            )
        except OSError as e:
            return False, f"Could not start FFmpeg: {e}"

        last_pct = 0.0
        # V14.3.1: read bytes line-by-line. ``iter(readline, b'')``
        # stops on EOF; on each iteration we get one ffmpeg progress
        # line as soon as ffmpeg flushes it (which it does per
        # ``-progress`` block).
        for raw in iter(self._proc.stdout.readline, b""):
            if self._cancel:
                self._proc.terminate()
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    raw_pct = max(0.0, min(100.0,
                                       (us / 1_000_000.0) / total_seconds * 100.0))
                    pct = pct_offset + raw_pct * pct_scale
                    pct = max(0.0, min(100.0, pct))
                    if pct - last_pct >= 0.2 or pct >= 100:
                        last_pct = pct
                        self.progress.emit(self.idx, pct)
                        elapsed = time.monotonic() - self._t_start
                        if pct > 1.0:
                            eta = elapsed * (100.0 - pct) / pct
                            self.eta_update.emit(self.idx, eta)
                except ValueError:
                    pass
            elif line == "progress=end":
                self.progress.emit(self.idx, pct_offset + 100.0 * pct_scale)

        ret = self._proc.wait()
        err_text = ""
        try:
            # V14.3.1: stderr is now a bytes stream (we switched to
            # binary Popen so stdout could flush per line). Decode for
            # the error-message path below.
            raw_err = self._proc.stderr.read() or b""
            if isinstance(raw_err, bytes):
                err_text = raw_err.decode("utf-8", errors="replace")
            else:
                err_text = raw_err
        except Exception:
            pass
        self._proc = None

        if self._cancel:
            target = cancel_cleanup_target or self.dst
            try:
                if os.path.exists(target):
                    os.remove(target)
            except OSError:
                pass
            return False, "Cancelled"
        if ret != 0:
            return False, ("FFmpeg failed: " + err_text.strip())[:400]
        return True, "Done"

    # ---- V12.3: intro / outro concat -----------------------------

    def _concat_intro_outro(self, main_tmp: str, dst: str,
                            intro: str, outro: str):
        """V12.3: concatenate optional intro + main_tmp + optional outro
        into ``dst`` via the FFmpeg concat *filter* (forgiving — accepts
        any input format, auto-scales / re-samples to match the main
        output). Both ``intro`` and ``outro`` may be empty strings.

        The audio crossfade duration at each join is controlled by
        ``opts.merge_audio_fade_s`` (0 = hard cut). Implemented via
        ``acrossfade`` for non-zero values, falling back to plain concat
        when 0 (hard cut, identical to a straight cat).
        """
        from .ffmpeg import probe_resolution, probe_has_audio, probe_duration as _probe_d
        if not os.path.exists(main_tmp):
            return False, "main encode missing for concat"
        target_w, target_h = probe_resolution(self.ffprobe, main_tmp)
        if target_w <= 0 or target_h <= 0:
            # Fall back to the profile's declared output res.
            target_w = int(self.opts.get("out_w") or 1920)
            target_h = int(self.opts.get("out_h") or 1080)
        sources = []
        labels = []  # ordered list of (role, input_index) tuples
        if intro:
            sources.append(intro)
            labels.append(("intro", len(sources) - 1))
        sources.append(main_tmp)
        labels.append(("main", len(sources) - 1))
        if outro:
            sources.append(outro)
            labels.append(("outro", len(sources) - 1))

        # V12.3 audit fix (BUG-3): the main encode always produces audio
        # (we mux 0:a? + AAC stream), but a user-supplied intro / outro
        # may be a silent screencap or animation file with no audio
        # stream. Trying to tap [i:a] on such an input crashes the
        # filter graph. Probe each source up front; for sources without
        # audio, generate silence with anullsrc instead.
        has_audio_map = {}
        for role, i in labels:
            if role == "main":
                # main_tmp is always re-encoded by us with AAC audio.
                has_audio_map[role] = True
            else:
                has_audio_map[role] = probe_has_audio(self.ffprobe,
                                                       sources[i])

        # Build the filter graph: scale each input to (target_w x target_h),
        # set SAR=1, force a stable fps so concat doesn't choke on
        # mixed-fps inputs, and resample audio to 48 kHz stereo.
        chain = []
        v_labels = []
        a_labels = []
        for role, i in labels:
            chain.append(
                f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"setsar=1,fps=30,format=yuv420p[v{role}]"
            )
            if has_audio_map.get(role, False):
                chain.append(
                    f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{role}]"
                )
            else:
                # Synthesize silent stereo audio bounded to the input
                # video's duration so concat sees matched v/a lengths.
                # Fallback to 5s if probe fails (very small slice — the
                # concat filter clamps to the shorter of v/a per segment
                # so worst case is a short silent gap, never a crash).
                d = max(0.05, _probe_d(self.ffprobe, sources[i]) or 5.0)
                chain.append(
                    "anullsrc=channel_layout=stereo:sample_rate=48000,"
                    f"atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{role}]"
                )
            v_labels.append(f"[v{role}]")
            a_labels.append(f"[a{role}]")

        try:
            fade_s = float(self.opts.get("merge_audio_fade_s", 0.0) or 0.0)
        except (TypeError, ValueError):
            fade_s = 0.0
        n = len(labels)

        if fade_s > 0 and n >= 2:
            # Crossfade chain on audio (paired left-to-right);
            # video uses straight concat (visual cuts are fine, audio
            # clicks are the actual problem).
            chain.append(
                "".join(v_labels) + f"concat=n={n}:v=1:a=0[outv]"
            )
            # Pairwise acrossfade across all audio inputs. Each step
            # uses curve 'tri' (linear) which is the gentlest.
            cur = a_labels[0]
            for k in range(1, n):
                nxt = a_labels[k]
                out = "[ax]" if k < n - 1 else "[outa]"
                chain.append(
                    f"{cur}{nxt}acrossfade=d={fade_s:.3f}:c1=tri:c2=tri{out}"
                )
                cur = out
        else:
            # Hard-cut concat across video + audio together.
            interleaved = "".join(f"{v}{a}"
                                  for v, a in zip(v_labels, a_labels))
            chain.append(
                f"{interleaved}concat=n={n}:v=1:a=1[outv][outa]"
            )

        filtergraph = ";".join(chain)

        # Re-encode using the same encoder/bitrate/audio settings as the
        # main pass so the final output stays consistent.
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        for s in sources:
            cmd += ["-i", s]
        cmd += ["-filter_complex", filtergraph,
                "-map", "[outv]", "-map", "[outa]"]
        cmd += encoder_codec_args(
            self.opts.get("encoder", "libx264"),
            self.opts.get("speed_tier", "Balanced"),
            video_bitrate_kbps=self.opts.get("video_bitrate_kbps", 0))
        # V14.3.0: same CPU-slot thread cap applies to the concat
        # re-encode pass (intro/outro merge) when running on libx264/x265.
        cmd += self._cpu_threads_flag()
        # V12.3 audit fix (BUG-1): the main encode pass already applied
        # speed (atempo), loudnorm, fade_in / fade_out and audio fade
        # via -af. Re-applying them here would: a) re-compound atempo
        # (2x becomes 4x); b) re-normalize already-normalized audio;
        # c) lay a fresh fade-in at t=0 of the *intro*, not the user's
        # content. Pass a stripped opts dict to audio_codec_args so the
        # concat pass only emits -c:a / -b:a / -ac.
        concat_audio_opts = {
            "audio_bitrate_kbps": self.opts.get("audio_bitrate_kbps", 192),
            "force_stereo": self.opts.get("force_stereo", True),
            "loudnorm": False, "speed": 1.0,
            "fade_in": 0.0, "fade_out": 0.0,
        }
        cmd += audio_codec_args(concat_audio_opts, output_duration_s=0.0)
        cmd += ["-movflags", "+faststart",
                "-progress", "pipe:1", "-stats_period", "0.1", "-nostats",
                dst]
        # Rough progress denominator: main duration + intro/outro
        # durations (probed). Used only for the progress bar — accuracy
        # not critical.
        from .ffmpeg import probe_duration
        total = probe_duration(self.ffprobe, main_tmp)
        if intro:
            total += probe_duration(self.ffprobe, intro)
        if outro:
            total += probe_duration(self.ffprobe, outro)
        # V12.3 audit fix (EDGE-2): map this pass to 50-100% so the
        # per-row progress bar continues smoothly after the main encode.
        ok, msg = self._run_ffmpeg(cmd, max(total, 0.1),
                                    pct_offset=50.0, pct_scale=0.5)
        # Clean up the main temp regardless of outcome — we don't keep
        # it around (concat output IS the user's deliverable).
        try:
            if os.path.exists(main_tmp):
                os.remove(main_tmp)
        except OSError:
            pass
        return ok, msg


# ============================================================== BatchManager

class BatchManager(QObject):
    """Drives the queue, launching up to N JobRunners concurrently.

    All public outputs are Qt signals emitted on the thread that created the
    manager (typically the main thread), so they're safe to wire directly to
    UI updates.
    """

    # Maximum auto-retries per job after a non-cancel failure.
    MAX_RETRIES = 1

    file_started = pyqtSignal(int, str)
    file_progress = pyqtSignal(int, float)
    file_eta = pyqtSignal(int, float)
    file_finished = pyqtSignal(int, bool, str)
    file_retrying = pyqtSignal(int, int, str)  # idx, attempt_no (1-based), last_error
    batch_finished = pyqtSignal()
    paused_changed = pyqtSignal(bool)  # V12.2: emits True/False on pause/resume

    def __init__(self, jobs: list, max_concurrent: int,
                 ffmpeg: str, ffprobe: str, opts: dict, parent=None):
        super().__init__(parent)
        # Each job: (idx, src, dst, kind, visual_path, visual_kind)
        self.jobs = list(jobs)
        self.max_concurrent = max(1, min(2, int(max_concurrent or 1)))
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.opts = opts
        self._pending = list(range(len(jobs)))
        self._active = {}      # idx -> JobRunner
        # V14.3.0: which active jobs are running in the "CPU slot"
        # (the auxiliary slot opened by ``use_cpu_alongside_gpu``).
        # Tracked as a set of idx so a live toggle off can refuse to
        # spawn new ones while letting existing ones finish.
        self._active_cpu = set()
        self._cancelled = False
        # V12.2: pause/resume support. When ``_paused`` is True, no new
        # JobRunner threads start — but anything already encoding keeps
        # running to completion (so the user doesn't lose mid-job state).
        # ``resume()`` re-fills the active slots from ``_pending``.
        self._paused = False
        self._retry_count = {} # idx -> retries already used
        self._slot_for_idx = {j[0]: s for s, j in enumerate(self.jobs)}
        # V14.3.0: live toggle. Read from opts so the GUI's checkbox
        # propagates through. Can be flipped via set_use_cpu_slot().
        self._use_cpu_slot = bool(opts.get("use_cpu_alongside_gpu", False))

    def is_running(self) -> bool:
        return bool(self._active) or bool(self._pending)

    def is_paused(self) -> bool:
        """V12.2: True after ``pause()``, until ``resume()`` or
        ``cancel()`` is called."""
        return self._paused

    def pause(self):
        """V12.2: stop pulling new jobs from the pending queue. Jobs
        currently encoding finish normally; subsequent jobs wait until
        ``resume()`` or ``cancel()`` is called."""
        if self._cancelled or self._paused:
            return
        self._paused = True
        log.info("Batch PAUSE requested (active=%d pending=%d)",
                 len(self._active), len(self._pending))
        self.paused_changed.emit(True)

    def resume(self):
        """V12.2: clear the pause flag and refill empty slots from
        ``_pending`` so encoding continues."""
        if not self._paused or self._cancelled:
            return
        self._paused = False
        log.info("Batch RESUME requested (active=%d pending=%d)",
                 len(self._active), len(self._pending))
        self.paused_changed.emit(False)
        # V14.3.0: dispatch loop refills GPU + optional CPU slot to
        # the effective concurrency target.
        self._dispatch()

    # ------------------------------------------------------------------ V14.3.0

    HARD_CAP_CONCURRENT = 4

    def effective_concurrency(self) -> int:
        """Total simultaneous JobRunner threads we're willing to run.
        With the CPU slot enabled this is ``max_concurrent + 1``, but
        we hard-cap at :data:`HARD_CAP_CONCURRENT` to keep the system
        from thrashing regardless of what the user set."""
        n = self.max_concurrent + (1 if self._use_cpu_slot else 0)
        return min(self.HARD_CAP_CONCURRENT, n)

    def set_use_cpu_slot(self, enabled: bool):
        """V14.3.0: live toggle for the auxiliary CPU encoder slot.
        Safe to call mid-batch from the GUI thread:

        * ON  → at most one extra concurrent job is allowed; the next
          dispatch tick opens it. The current encoder runs at
          below-normal priority and the libx264/x265 ``-threads`` arg
          is capped.
        * OFF → stop spawning new CPU jobs; in-flight CPU jobs run to
          completion at their current priority (mid-encode you can't
          re-nice an ffmpeg process safely across platforms).
        """
        enabled = bool(enabled)
        if enabled == self._use_cpu_slot:
            return
        self._use_cpu_slot = enabled
        self.opts["use_cpu_alongside_gpu"] = enabled
        log.info("CPU slot toggle: %s (active=%d cpu_active=%d)",
                 "ON" if enabled else "OFF",
                 len(self._active), len(self._active_cpu))
        if enabled and not self._cancelled and not self._paused:
            # Try to top up immediately.
            self._dispatch()

    def add_jobs(self, new_jobs: list):
        """V14.3.0: append more jobs to a running (or paused) batch.

        New jobs go to the end of the pending queue. If the batch is
        running and there's a free slot, dispatch picks them up
        immediately. If the batch has already finished, this is a
        no-op — caller should start a fresh batch.
        """
        if self._cancelled or not new_jobs:
            return
        was_done = (not self._pending and not self._active)
        if was_done:
            log.info("add_jobs() called on a finished batch — no-op")
            return
        first_new_slot = len(self.jobs)
        for j in new_jobs:
            self.jobs.append(j)
        for s, j in enumerate(self.jobs[first_new_slot:],
                              start=first_new_slot):
            idx = j[0]
            self._slot_for_idx[idx] = s
            self._pending.append(s)
        log.info("add_jobs: +%d (pending=%d)", len(new_jobs),
                 len(self._pending))
        if not self._paused:
            self._dispatch()

    def _dispatch(self):
        """V14.3.0: refill empty slots up to ``effective_concurrency``.
        Replaces the inline single-shot ``_start_next`` calls that
        only knew about one fixed concurrency. ``_start_next`` is
        still the worker that pulls + starts one job at a time."""
        if self._cancelled or self._paused:
            return
        target = self.effective_concurrency()
        while (len(self._active) < target
               and self._pending
               and not self._cancelled and not self._paused):
            if not self._start_next():
                break

    # ------------------------------------------------------------------

    def start(self):
        if not self.jobs:
            self.batch_finished.emit()
            return
        log.info(
            "Batch START: %d job(s), gpu_concurrency=%d, cpu_slot=%s "
            "-> effective=%d",
            len(self.jobs), self.max_concurrent,
            "on" if self._use_cpu_slot else "off",
            self.effective_concurrency())
        self._dispatch()

    def cancel(self):
        log.info("Batch CANCEL requested")
        self._cancelled = True
        # V12.2: cancel beats pause — clear the pause flag so any UI
        # watching `paused_changed` updates the button label.
        was_paused = self._paused
        self._paused = False
        self._pending.clear()
        for r in list(self._active.values()):
            r.cancel()
        if was_paused:
            self.paused_changed.emit(False)

    def wait_all(self, timeout_ms: int = 5000):
        """Block until every active runner has exited (or timed out)."""
        for r in list(self._active.values()):
            try:
                r.wait(timeout_ms)
            except Exception:
                pass

    def _start_next(self) -> bool:
        """V14.3.0: return ``True`` if a job was launched, ``False`` if
        the dispatcher should stop trying (e.g. RAM watchdog blocked
        the CPU slot but the GPU slot was already filled). The boolean
        return lets ``_dispatch`` break the refill loop cleanly."""
        # V12.2: don't start a new job while paused; ``resume()`` will
        # call this method again to refill the active slots.
        if self._cancelled or self._paused or not self._pending:
            return False
        # V14.3.0: decide whether this dispatch fills the GPU slot
        # (always allowed when there's room) or the auxiliary CPU
        # slot (only if the toggle is on and the RAM watchdog says
        # we have headroom).
        gpu_filled = len(self._active) - len(self._active_cpu)
        is_cpu_slot = False
        if gpu_filled >= self.max_concurrent:
            # The GPU side is full — any further slot is the CPU one.
            if not self._use_cpu_slot:
                return False
            if not self._cpu_slot_safe_to_open():
                # RAM tight or psutil says don't spawn — wait for the
                # next dispatch tick.
                return False
            is_cpu_slot = True

        slot = self._pending.pop(0)
        # Job tuples are 6-tuples by default; an optional 7th element carries
        # a per-job opts override dict (used by the split-on-length feature
        # to encode a specific window of the source).
        job = self.jobs[slot]
        idx, src, dst, kind, visual_path, visual_kind = job[:6]
        per_job_opts = job[6] if len(job) >= 7 else None
        # V14.3.0: CPU-slot jobs swap the encoder for libx264/libx265
        # and set the ``_cpu_slot`` flag the JobRunner uses to lower
        # priority + cap the encoder thread count.
        if is_cpu_slot:
            try:
                from .system_resources import force_cpu_encoder
            except Exception:
                force_cpu_encoder = None
            override = dict(per_job_opts or {})
            override["_cpu_slot"] = True
            # Pick libx264/x265 to match the profile's codec family.
            if force_cpu_encoder is not None:
                override = {**override, **{
                    k: v for k, v in force_cpu_encoder(
                        self.opts, codec_hint=self.opts.get("encoder", "")
                    ).items() if k in ("encoder", "_cpu_slot")
                }}
            per_job_opts = override
            self._active_cpu.add(idx)
        runner = JobRunner(idx, src, dst, kind, visual_path, visual_kind,
                           self.ffmpeg, self.ffprobe, self.opts,
                           per_job_opts=per_job_opts)
        runner.progress.connect(self.file_progress)
        runner.eta_update.connect(self.file_eta)
        runner.job_finished.connect(self._on_finished)
        self._active[idx] = runner
        self.file_started.emit(idx, src)
        runner.start()
        return True

    def _cpu_slot_safe_to_open(self) -> bool:
        """V14.3.0: RAM watchdog. Returns False when free RAM is below
        the system_resources threshold so the dispatch loop skips the
        CPU slot for this tick. Fail-open if psutil isn't installed."""
        try:
            from .system_resources import enough_ram_for_cpu_job
            return enough_ram_for_cpu_job()
        except Exception:
            return True

    def _on_finished(self, idx, ok, msg):
        # Retry path: any non-cancel failure triggers up to MAX_RETRIES
        # additional attempts. The runner is finalized first, then the slot
        # is pushed back onto the pending queue.
        if (not ok and msg != "Cancelled" and not self._cancelled
                and self._retry_count.get(idx, 0) < self.MAX_RETRIES):
            self._retry_count[idx] = self._retry_count.get(idx, 0) + 1
            attempt = self._retry_count[idx] + 1
            log.info("Job %d retrying (attempt %d/%d) after: %s",
                     idx, attempt, self.MAX_RETRIES + 1, msg[:120])
            self.file_retrying.emit(idx, attempt, msg)
            runner = self._active.pop(idx, None)
            # V14.3.0: clear CPU-slot ownership when the runner exits.
            self._active_cpu.discard(idx)
            if runner:
                try:
                    runner.wait(50)
                except Exception:
                    pass
                runner.deleteLater()
            slot = self._slot_for_idx.get(idx)
            if slot is not None:
                self._pending.append(slot)
                self._dispatch()
            return

        self.file_finished.emit(idx, ok, msg)
        runner = self._active.pop(idx, None)
        self._active_cpu.discard(idx)
        if runner:
            try:
                runner.wait(50)
            except Exception:
                pass
            runner.deleteLater()
        # V14.3.0: ``_dispatch`` handles the cpu+gpu slot bookkeeping;
        # it short-circuits when paused so this is a cheap no-op then.
        # The batch is only considered "done" when there's nothing
        # pending AND nothing active.
        if not self._cancelled and self._pending and not self._paused:
            self._dispatch()
        elif not self._active and not self._pending:
            log.info("Batch END")
            self.batch_finished.emit()
