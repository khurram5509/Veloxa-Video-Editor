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
    """V14.3.3: bright spectrogram filling the FULL canvas.

    Uses ``showspectrum`` with ``slide=replace`` — fills the canvas
    bottom-up (bright energy at the bottom) and scrolls left-to-right
    over time. With enough audio fed in (~26 s for an 800-pixel-wide
    canvas), the spectrum reaches the right edge so every pixel
    carries data. For the preview pane we feed 30 s of audio at the
    generator level so the rendered frame fills the canvas.
    """
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showspectrum=s={w}x{h}:mode=combined:color=intensity:"
        f"scale=lin:slide=replace,"
        f"format=yuv420p,setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_circular_spectrum(audio: str, w: int, h: int, opts: dict) -> tuple:
    """V14.3.3: rainbow log-scale spectrogram filling the FULL canvas.

    Was a small circular CQT centred on a black surround; the polar
    layout can't be made to fill non-square canvases cleanly, so it's
    been replaced with a rainbow-palette log-scale spectrogram that
    covers every pixel.
    """
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showspectrum=s={w}x{h}:mode=combined:color=rainbow:"
        f"scale=log:slide=replace,"
        f"format=yuv420p,setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_waveform(audio: str, w: int, h: int, opts: dict) -> tuple:
    """V14.3.3: stereo waveform rendered at the FULL canvas height.

    Calm, podcast-friendly horizontal waveform spanning every pixel,
    on a tinted dark gradient. ``mode=cline`` draws a centred line
    that breathes with the audio level.
    """
    color = _ffcolor(opts.get("audio_template_color") or "#f58220")
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showwaves=s={w}x{h}:mode=cline:colors={color}:rate=30,"
        f"format=yuv420p[wav];"
        # Background gradient: vertical fade so the waveform sits on a
        # subtle tinted field instead of pure flat black.
        f"color=c=0x111418:s={w}x{h}:r=30,"
        f"geq=r='r(X,Y)+(Y/{h})*15':g='g(X,Y)+(Y/{h})*18':"
        f"b='b(X,Y)+(Y/{h})*24'[bg];"
        f"[bg][wav]overlay=0:0:format=auto,setsar=1[vout];"
        f"[a2]anull[aout]",
        "[vout]",
    )


def _tpl_neon_ring(audio: str, w: int, h: int, opts: dict) -> tuple:
    """V14.3.3: glowing neon spectrogram filling the FULL canvas.

    Was a small CQT ring centred on black; the polar layout can't fill
    non-square canvases. Replaced with a fire-palette separate-channel
    spectrogram + box-blur bloom layered underneath for the neon glow
    feel, with every pixel carrying audio data.
    """
    return (
        f"[{audio}]asplit=3[a1][a2][a3];"
        # Bottom: heavy-blurred spectrogram as glow.
        f"[a1]showspectrum=s={w}x{h}:mode=separate:color=fire:"
        f"scale=log:slide=replace,"
        f"format=yuv420p,boxblur=30:2[glow];"
        # Top: sharp spectrogram, overlaid additively-ish.
        f"[a2]showspectrum=s={w}x{h}:mode=separate:color=fire:"
        f"scale=log:slide=replace,"
        f"format=yuv420p[sharp];"
        f"[glow][sharp]blend=all_mode=screen:all_opacity=0.8,"
        f"setsar=1[vout];"
        f"[a3]anull[aout]",
        "[vout]",
    )


def _tpl_podcast_layout(audio: str, w: int, h: int, opts: dict) -> tuple:
    """V14.3.3: full-canvas frequency-bar spectrum behind a centred
    waveform band. Every pixel carries audio data — was a 70/30 split
    that left most of the canvas inert.

    Background = full-canvas ``showfreqs`` bars (frequency on x-axis
    so the canvas fills instantly without scroll-fill lag).
    Centre band ≈ 30% h = bright stereo waveform overlay.
    """
    color = _ffcolor(opts.get("audio_template_color") or "#f58220")
    band_h = max(120, int(h * 0.30))
    band_y = (h - band_h) // 2
    return (
        f"[{audio}]asplit=3[a1][a2][a3];"
        # Full-canvas frequency bars background.
        f"[a1]showfreqs=s={w}x{h}:mode=bar:cmode=combined:"
        f"colors=0x4060c0:fscale=log:ascale=log:rate=30,"
        f"format=yuv420p,eq=brightness=-0.10:saturation=0.8[bg];"
        # Centre-band waveform overlay.
        f"[a2]showwaves=s={w}x{band_h}:mode=cline:colors={color}:rate=30,"
        f"format=yuva420p[band];"
        # Composite + thin top / bottom divider lines on the band so the
        # waveform reads as a distinct overlay.
        f"[bg][band]overlay=0:{band_y}:format=auto,"
        f"drawbox=x=0:y={band_y - 1}:w={w}:h=2:color={color}@0.85:t=fill,"
        f"drawbox=x=0:y={band_y + band_h - 1}:w={w}:h=2:"
        f"color={color}@0.85:t=fill,"
        f"setsar=1[vout];"
        f"[a3]anull[aout]",
        "[vout]",
    )


def _tpl_spotify_canvas(audio: str, w: int, h: int, opts: dict) -> tuple:
    """V14.3.3: showwaves at the FULL canvas height (was a tiny 10 % strip
    at the bottom). Subtle dark gradient behind for that 'canvas loop'
    feel, but every pixel now carries audio information.
    """
    color = _ffcolor(opts.get("audio_template_color") or "#f58220")
    return (
        f"[{audio}]asplit=2[a1][a2];"
        f"[a1]showwaves=s={w}x{h}:mode=p2p:colors={color}:rate=30,"
        f"format=yuva420p[bars];"
        # Subtle radial-ish dark gradient: dark blue-grey lifting slightly
        # toward the middle so the waveform pops.
        f"color=c=0x1a1d22:s={w}x{h}:r=30,"
        f"geq=r='r(X,Y)+8':g='g(X,Y)+10':b='b(X,Y)+16'[bg];"
        f"[bg][bars]overlay=0:0:format=auto,setsar=1[vout];"
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
