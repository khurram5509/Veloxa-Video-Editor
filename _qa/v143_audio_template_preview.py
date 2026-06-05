"""V14.3.2 unit test: audio-template preview pane.

Verifies that ``generate_audio_template_preview`` produces a valid JPG
frame for every registered template, given a real audio source.

Reproduces the user's bug ("audio visuals not showing on preview pane")
by exercising the same code path the GUI uses when the user picks a
template from the Audio Visuals tab.
"""
import os, sys, tempfile, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import (
    generate_audio_template_preview,
    AUDIO_TEMPLATES, AUDIO_TEMPLATE_ORDER,
)

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


ffmpeg = str(ROOT / "ffmpeg" / "ffmpeg.exe")
if not os.path.exists(ffmpeg):
    ffmpeg = str(ROOT / "ffmpeg" / "ffmpeg")
if not os.path.exists(ffmpeg):
    print("FAIL: no ffmpeg in repo")
    sys.exit(1)

tmpdir = Path(tempfile.mkdtemp(prefix="veloxa_v143_audio_tpl_"))
audio_src = tmpdir / "sample.wav"

# Build a 5-second audio source with energy across the spectrum so
# every template (spectrum/waveform/cqt) has something to draw.
print("Generating audio source (5s 440 Hz sine + 880 Hz harmonic) ...")
gen = subprocess.run([
    ffmpeg, "-y",
    "-f", "lavfi", "-i",
    "sine=frequency=440:duration=5,asplit=2[a][b];"
    "[b]asplit=1[b1];sine=frequency=880:duration=5[s2];"
    "[a][s2]amix=inputs=2",
    "-ac", "2", "-ar", "44100", str(audio_src),
], capture_output=True, text=True, timeout=30)
if gen.returncode != 0 or not audio_src.exists():
    # Fallback: simpler source.
    subprocess.run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-ac", "2", "-ar", "44100", str(audio_src),
    ], capture_output=True, text=True, timeout=30, check=True)
print(f"Audio source: {audio_src} ({os.path.getsize(audio_src)} bytes)")

# Standard opts the GUI would pass.
opts = {
    "out_w": 1280,
    "out_h": 720,
    "video_quality": "Balanced",
}

print()
print("=" * 72)
print("V14.3.2: per-template preview generation")
print("=" * 72)
print()

for key in AUDIO_TEMPLATE_ORDER:
    tpl = AUDIO_TEMPLATES[key]
    out_path = tmpdir / f"preview_{key}.jpg"
    ok = generate_audio_template_preview(
        ffmpeg, str(audio_src), key, opts, str(out_path), time_s=2.0)
    if ok and out_path.exists():
        size = os.path.getsize(out_path)
        check(f"{key:20s} -> preview frame produced ({size} bytes)",
              size > 1000)
        # Sanity-check the JPG magic bytes.
        with open(out_path, "rb") as f:
            head = f.read(3)
        check(f"{key:20s} -> output is a JPEG (magic ff d8 ff)",
              head[:2] == b"\xff\xd8")
    else:
        check(f"{key:20s} -> preview frame produced",
              False, f"ok={ok}, exists={out_path.exists()}")

# Negative case: unknown template key -> False.
unk = generate_audio_template_preview(
    ffmpeg, str(audio_src), "this_does_not_exist", opts,
    str(tmpdir / "no.jpg"))
check("unknown template key -> False (no crash)", unk is False)

# Negative case: empty template key -> False.
empty = generate_audio_template_preview(
    ffmpeg, str(audio_src), "", opts, str(tmpdir / "no.jpg"))
check("empty template key -> False", empty is False)

# Negative case: sentinel 'none' -> False.
none_ = generate_audio_template_preview(
    ffmpeg, str(audio_src), "none", opts, str(tmpdir / "no.jpg"))
check("'none' sentinel -> False", none_ is False)

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" — {d}" if d else ""))
    sys.exit(1)
print("All audio-template preview checks PASS.")
sys.exit(0)
