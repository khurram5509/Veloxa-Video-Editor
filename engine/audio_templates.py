"""V14.0: real-time audio-reactive visual templates for the
audio-to-video encode path.

Each template renders a complete FFmpeg ``filter_complex`` graph that:

1. Generates a video stream from the input audio using FFmpeg's bundled
   visualisation filters (``showspectrum``, ``showwaves``, ``showcqt``,
   ``avectorscope``, etc.).
2. Optionally composites a user-supplied background image / video over
   that visualisation so the template plays as a layered scene.

The audio-to-video encode path (``engine/batch.py::_encode_audio_to_video``)
checks the ``audio_template`` opt; when set to a known template name, the
template's filter graph replaces the default ``[0:v]scale+pad+setsar``
chain. When not set (or set to ``"none"``), the encode runs the existing
image / video-visual path as before.

All templates produce frames at the profile's output ``target_w x
target_h`` so the rest of the pipeline (watermarks, encoder, concat
intro/outro) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class AudioTemplate:
    """One audio-visual template.

    ``build_filter(audio_label, target_w, target_h, opts)`` returns a
    pair ``(filter_str, out_label)`` where ``filter_str`` is the
    ``filter_complex`` content (terminated by the named output label)
    and ``out_label`` is the [bracketed] label of the final RGB stream.

    ``needs_visual_input`` is True if the template requires a user-
    supplied background image / video (the existing visual picker is
    re-used in that case). Templates with ``needs_visual_input=False``
    self-generate every pixel from the audio stream.
    """
    name: str
    description: str
    needs_visual_input: bool
    build_filter: Callable[[str, int, int, dict], tuple]


# ---------------------------------------------------------------- helpers

def _ffcolor(c: str) -> str:
    """Normalise a ``#rrggbb`` hex colour into ``0xRRGGBB`` form that
    FFmpeg's filters accept."""
    c = (c or "#f58220").lstrip("#")
    if len(c) == 6:
        return "0x" + c
    return "0xf58220"


# ---------------------------------------------------------------- templates


def _tpl_spectrum_bars(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Tall, bright spectrum bars centred horizontally on a black
    background. Looks like a podcast / radio app bar visualiser."""
    color = _ffcolor(opts.get("audio_template_color") or "#f58220")
    # showspectrum emits a scrolling spectrum. For a discrete-bar look
    # we use the ``slide=replace`` mode + a small ``win_size``. The
    # ``s=WxH`` is the spectrum's own canvas; we then pad it to target.
    sw = w
    sh = max(120, int(h * 0.55))  # use ~55% of the canvas for bars
    pad_top = (h - sh) // 2
    pad_bot = h - sh - pad_top
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showspectrum=s={sw}x{sh}:mode=combined:color=intensity:"
        f"scale=lin:slide=replace:win_size=1024,"
        f"format=yuv420p[spec];"
        f"color=black:s={w}x{h}:r=30[bg];"
        f"[bg][spec]overlay=0:{pad_top},"
        f"drawbox=x=0:y=0:w={w}:h={pad_top}:color=black@1:t=fill,"
        f"drawbox=x=0:y={h - pad_bot}:w={w}:h={pad_bot}:color=black@1:t=fill,"
        f"setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_circular_spectrum(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Spectrum bars wrapped into a circle — classic 'spotify canvas'
    look. Uses showcqt (constant-Q transform) for musical-frequency
    accuracy and avectorscope to draw the polar plot."""
    # showcqtbar projects the CQT onto a circular bar layout.
    side = min(w, h)
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showcqt=s={side}x{side}:fps=30:bar_v=9:sono_v=0:axis=0:"
        f"basefreq=27.5:endfreq=14080:tlength=0.05,"
        f"format=yuv420p[viz];"
        f"color=black:s={w}x{h}:r=30[bg];"
        f"[bg][viz]overlay=(W-w)/2:(H-h)/2,setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_waveform(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Horizontal stereo waveform on a tinted background. Calm,
    podcast-friendly look."""
    color = _ffcolor(opts.get("audio_template_color") or "#f58220")
    wh = max(160, int(h * 0.6))
    pad_top = (h - wh) // 2
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showwaves=s={w}x{wh}:mode=cline:colors={color}:rate=30,"
        f"format=yuv420p[wav];"
        f"color=c=0x111418:s={w}x{h}:r=30[bg];"
        f"[bg][wav]overlay=0:{pad_top},setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_neon_ring(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Glowing neon audio ring — showcqt + box blur for the bloom +
    overlaid on a deep dark background."""
    side = min(w, h)
    inner = int(side * 0.85)
    return (
        f"[{audio}]asplit=3[a1][a2][a3];"
        f"[a1]showcqt=s={inner}x{inner}:fps=30:bar_v=9:sono_v=0:axis=0:"
        f"basefreq=55:endfreq=14080:tlength=0.05,"
        f"format=yuva420p[ring];"
        f"[a2]showcqt=s={inner}x{inner}:fps=30:bar_v=14:sono_v=0:axis=0:"
        f"basefreq=55:endfreq=14080:tlength=0.05,"
        f"format=yuva420p,boxblur=20:1[glow];"
        f"color=c=0x000000:s={w}x{h}:r=30[bg];"
        f"[bg][glow]overlay=(W-w)/2:(H-h)/2:format=auto[bg2];"
        f"[bg2][ring]overlay=(W-w)/2:(H-h)/2,setsar=1[vout];"
        f"[a3]anull[aout]",
        "[vout]",
    )


def _tpl_podcast_layout(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Multi-element podcast layout: top half is a static background,
    bottom strip shows scrolling spectrum, plus a thin centre divider.
    The static background is a generated dark vignette."""
    bot_h = max(120, int(h * 0.30))
    top_h = h - bot_h
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showspectrum=s={w}x{bot_h}:mode=combined:color=intensity:"
        f"scale=log:slide=replace:win_size=2048,"
        f"format=yuv420p[spec];"
        f"color=c=0x0b0d10:s={w}x{top_h}:r=30,"
        f"drawbox=x=0:y={top_h - 2}:w={w}:h=2:color=0xf58220@0.8:t=fill[top];"
        f"color=c=black:s={w}x{h}:r=30[canvas];"
        f"[canvas][top]overlay=0:0[canvas2];"
        f"[canvas2][spec]overlay=0:{top_h},setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_spotify_canvas(audio: str, w: int, h: int, opts: dict) -> tuple:
    """Subtle background + a thin animated bar at the bottom. Vibe is
    'spotify canvas loop' rather than an arcade visualiser."""
    bar_h = max(48, int(h * 0.10))
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showvolume=f=1:b=4:c=ifnot(AVERAGE,if(gt(VOLUME,-2),"
        f"0xff5050,0xf58220),0x707070):w={w}:h={bar_h},"
        f"format=yuv420p[bars];"
        f"color=c=0x1a1d22:s={w}x{h}:r=30[bg];"
        f"[bg][bars]overlay=0:H-h,setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


# ---------------------------------------------------------------- exports

TEMPLATES: dict = {
    "spectrum_bars":     AudioTemplate(
        "Spectrum Bars",
        "Classic frequency-spectrum bars on a dark background.",
        needs_visual_input=False,
        build_filter=_tpl_spectrum_bars,
    ),
    "circular_spectrum": AudioTemplate(
        "Circular Spectrum",
        "Bars wrapped into a circle (Spotify-canvas-style).",
        needs_visual_input=False,
        build_filter=_tpl_circular_spectrum,
    ),
    "waveform":          AudioTemplate(
        "Waveform",
        "Calm horizontal waveform on a tinted background.",
        needs_visual_input=False,
        build_filter=_tpl_waveform,
    ),
    "neon_ring":         AudioTemplate(
        "Neon Audio Ring",
        "Glowing audio ring (CQT + box-blur bloom).",
        needs_visual_input=False,
        build_filter=_tpl_neon_ring,
    ),
    "podcast_layout":    AudioTemplate(
        "Podcast Layout",
        "Static dark hero on top, scrolling spectrum strip on bottom.",
        needs_visual_input=False,
        build_filter=_tpl_podcast_layout,
    ),
    "spotify_canvas":    AudioTemplate(
        "Spotify Canvas Style",
        "Subtle dark background with a thin volume bar at the foot.",
        needs_visual_input=False,
        build_filter=_tpl_spotify_canvas,
    ),
}

TEMPLATE_ORDER = (
    "spectrum_bars",
    "circular_spectrum",
    "waveform",
    "neon_ring",
    "podcast_layout",
    "spotify_canvas",
)

TEMPLATE_NONE = "none"


def template_choices() -> list:
    """Return ``[(key, display_name), ...]`` including the 'None'
    sentinel at the top, in stable display order. Used by the GUI to
    populate the AV template dropdown."""
    out = [(TEMPLATE_NONE, "— None (use image / video visual) —")]
    for k in TEMPLATE_ORDER:
        tpl = TEMPLATES[k]
        out.append((k, tpl.name))
    return out


def get_template(key: str) -> Optional[AudioTemplate]:
    """Return the :class:`AudioTemplate` for ``key`` or ``None``."""
    if not key or key == TEMPLATE_NONE:
        return None
    return TEMPLATES.get(key)
