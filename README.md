# Veloxa Video Editor

Bulk video editor for Windows. Trim, watermark, and convert videos and audio files to MP4. Designed for fast unattended bulk work: queue many files, apply a single set of settings, walk away.

Settings live in named profiles; a session log records every job; the queue survives app restarts and crashes. Built on FFmpeg + PyQt6, packaged as a single self-contained Windows installer.

## Download

The latest Windows installer is published in this repo's [Releases](../../releases). The installer keeps a stable `AppId` across versions, so upgrades replace the existing install in place — your profiles, settings, watermark folder, and queue state survive untouched.

## Auto-update

V13.0+ checks this repo's Releases API on startup (opt-in, ON by default). When a newer release is published, a dialog appears with the release notes and one-click Download & Install. The check is silent if no update is found, silent on errors (offline, rate-limited), and never blocks the UI.

You can disable the startup check via the checkbox in the "Update available" dialog. The `Help → Check for Updates...` menu item always works regardless of the setting.

## Features

- Bulk processing engine — sequential or parallel (1-2 concurrent jobs), one auto-retry on transient failures.
- Quality tier dropdowns (Low / Medium / High / Best / Super Best) — resolves to bitrate sized to the output resolution.
- Per-profile intro / outro video merge with audio crossfade — any input format auto re-encoded.
- Image + video + text watermarks, all optional and stackable.
- MP3 → MP4 with image or looping video as the visual.
- H.264 / HEVC (CPU x264/x265 + NVIDIA NVENC / Intel QSV / AMD AMF, auto-detected).
- Hardware decode + encode for max throughput.
- Audio loudness normalisation (EBU R128 -16 LUFS), force-stereo upmix, fade-in / fade-out, atempo speed change.
- Per-profile audio visuals (round-robin rotation for podcast batches).
- Split-on-length: cap each output at N minutes; oversized inputs auto-split into Part1 / Part2 / …
- Watch folder mode: drop files into a folder → auto-encode → move source to `done/`.
- Output filename pattern with placeholders (`{name}`, `{date}`, `{codec}`, `{n:03d}`, …).
- Live preview with watermarks composited.
- Crash-safe queue resume.
- CLI / headless mode for unattended runs.

## Build from source

```powershell
.\build.ps1
```

Requires:
- Python 3.11+
- ffmpeg.exe + ffprobe.exe in the `ffmpeg/` folder (download from [gyan.dev essentials build](https://www.gyan.dev/ffmpeg/builds/))
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer (optional)

The build script creates a virtualenv, installs requirements, runs PyInstaller, and emits `dist\Veloxa-Video-Editor-V13.0.exe`. To then produce the installer:

```powershell
& "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

## License

See [LICENSE](LICENSE) and the License panel inside the app for bundled-component notices (FFmpeg LGPL/GPL, PyQt6 GPL/commercial).
