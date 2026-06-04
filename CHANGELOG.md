# Veloxa Video Editor — V14.1.1

**Hot-fix.** The V14.1.0 single-instance guard misfired immediately after an in-app update.

## Fixed

V14.1.0 added single-instance enforcement via a Qt named pipe. After the in-app updater quit V14.0.x and launched V14.1.0, the new EXE sometimes started **while the old process was still tearing down**. It saw the old EXE's named pipe still open, treated it as a live primary, and exited with an *"already running"* message. The user had to close that dialog and launch again — second launch worked because the old process was fully dead by then.

### Fix: ACK-based liveness handshake

- The primary instance now **writes an `OK` byte back** after running the activation callback.
- A new instance writes `activate`, then **waits up to 1.5 s for the ACK** before deciding it's a duplicate.
- If no ACK arrives, the primary is dead or wedged. The new instance promotes itself, takes over the pipe, and starts normally.

This means:
- A real second launch still gets the "already running" path: existing window comes to the front, second exits cleanly.
- An update-relaunch where the old EXE's pipe is briefly still up: the new EXE notices the silence, takes over, and starts normally. **No more "already running" dialog after update.**

## Also fixed

- **Session-start log** in `app/persistence.py` was hardcoded to *"V13.0"* — every release since V13.0 reported the wrong version in `%APPDATA%\Veloxa-VD\V10\logs\*.log`. Now reads `APP_VERSION` from `app/updater.py` dynamically; future bumps only need to touch the one constant.

---

# Veloxa Video Editor — V14.1.0

**Minor release.** Single-instance enforcement + HiDPI awareness + responsive-window hardening.

## Single-instance application

Launching Veloxa while another instance is already running no longer opens a duplicate window. The second launch:

1. Detects the existing primary via a per-user Qt named pipe (`VeloxaVideoEditor-<username>`).
2. Pings the primary, which raises + focuses + activates its window (handles minimised, hidden-behind-other-window, and minimised-to-tray states).
3. Shows a brief "Veloxa Video Editor is already running" toast that auto-closes after 2 seconds.
4. Exits cleanly without holding any resources.

Survives sleep / hibernation / user-session changes — the pipe is per-user and a stale endpoint from a previously-crashed primary is cleaned up automatically on next start. If the named pipe is in an unusable state (file-system permissions, AV interference), the app degrades open and starts normally rather than blocking startup.

## HiDPI awareness

Enabled before `QApplication` is constructed:

- `Qt.HighDpiScaleFactorRoundingPolicy.PassThrough` so fractional scale factors (125 %, 150 %, 175 %) are preserved instead of being rounded to nearest integer multiple. This is critical on Windows laptops where 150 % is the default and rounding to 100 % or 200 % produces blurry/cut-off output.
- `QT_ENABLE_HIGHDPI_SCALING` and `QT_AUTO_SCREEN_SCALE_FACTOR` env vars set as defensive defaults.

Combined with the existing Qt layout managers (every widget already lives in a `QHBoxLayout` / `QVBoxLayout` / `QGridLayout`), the app now renders correctly at:

- HD (1280×720), Full HD (1920×1080), QHD (2560×1440), 4K (3840×2160), 5K+
- Windows display scaling 100 %, 125 %, 150 %, 175 %, 200 %, 250 %, 300 %
- Multi-monitor environments — window geometry is restored per the saved state in `QSettings`; moving the window between displays with different scaling settings is handled natively by Qt.

## Window-sizing hardening

`setMinimumSize(1024, 680)` so the window can't be dragged small enough to clip the bottom Start/Pause/Cancel bar. The 1320×960 default still applies for fresh launches. Existing user window state (`saveGeometry` / `restoreGeometry` via `QSettings`) carries across upgrades.

## Reliability

V14.0.x download-speed regression is folded in: 64 KB chunks (was 1 MB) — back to ~12 MB/s against the GitHub release CDN.

---

# Veloxa Video Editor — V14.0.3

**Hot-fix.** Download speed regression in V14.0.1 / V14.0.2 reverted.

## Fixed

V14.0.1's switch from 64 KB chunks → 1 MB chunks was made on the wrong mental model ("fewer Python iterations = faster"). In practice `urllib.request`'s `resp.read(N)` blocks waiting for N bytes, while GitHub's release CDN delivers in smaller TCP frames — so the 1 MB read stalls waiting for partial buffers and *reduces* throughput.

### Measured against the live V14.0.2 release URL:

| Chunk size | Throughput |
|---|---|
| **64 KB** (V14.0.0 + V14.0.3+)| **12.3 MB/s** ⭐ |
| 256 KB | 9.9 MB/s |
| 1 MB (V14.0.1 + V14.0.2) | 8.4 MB/s |
| 4 MB | 0.3 MB/s (catastrophic) |

For the 395 MB installer that's the difference between **~32 s** (V14.0.3) and **~47 s** (V14.0.2) on the same connection — plus the OS / antivirus overhead the user actually experienced was much worse than the in-lab measurement.

The throttled progress signal (~10/sec) in `DownloadWorker` decouples GUI repaint frequency from chunk size, so we get the 64 KB throughput without spamming the event queue.

### What V14.0.1 got right, kept

- `DownloadWorker(QThread)` runs the download off the GUI thread → still in place.
- Throttled progress signals (~10/sec) → still in place.
- Live transfer-rate read-out (MB/s) → still in place.
- Cancel routes to worker.cancel() with chunk-boundary polling → still in place.

---

# Veloxa Video Editor — V14.0.2

**Hot-fix release.** Three real bugs the V14.0.1 user reported.

## Fixed

- **Old versions stayed installed alongside the new one.** Every release dropped a versioned EXE (`Veloxa-Video-Editor-V13.1.0.exe`, `Veloxa-Video-Editor-V14.0.0.exe`, …) into the same folder and a versioned shortcut (`Veloxa Video Editor V13.1.0`, …) into the Start Menu, so users ended up with multiple side-by-side shortcuts and EXEs — and clicking the old shortcut still launched the old EXE. The installer now uses a single fixed EXE name (`Veloxa-Video-Editor.exe`) and a single fixed shortcut name (`Veloxa Video Editor`). An `[InstallDelete]` block sweeps the legacy versioned files from previous V11..V14.0.1 installs on first run of V14.0.2.
- **Preview metadata overlay stayed visible after the queue was emptied.** The top-left overlay showing *Source / Duration / Resolution / Codec / Profile* didn't clear when the last queue row was removed — so it kept showing info from the deleted file. Fixed in all three relevant code paths (`_update_preview_info`, `_refresh_preview`, `_on_video_selected`). The preview thumbnail now also resets to the placeholder text on empty, and any in-flight playback is stopped.
- **Setup EXE icon was missing.** Added `VersionInfoCompany` / `VersionInfoProductName` / `VersionInfoProductVersion` to the Inno Setup script so the Setup EXE shows the Veloxa orange-V icon in Windows Explorer / Downloads.

## Verified working (no fix needed)

- **Keyboard shortcuts** — Ctrl+O / Ctrl+Enter / Esc / Ctrl+S / Ctrl+Shift+S / Ctrl+M / F1 / Delete all wired in `_install_shortcuts` and tested.

---

# Veloxa Video Editor — V14.0.1

**Hot-fix release.** Speeds up the in-app update download and unfreezes the GUI during it.

## Fixed

The V14.0.0 update download was slow and made the rest of the app feel frozen for the entire 395 MB transfer. Two root causes:

1. The download ran **synchronously on the GUI thread** and called `QApplication.processEvents()` after every 64 KB chunk — that's ~6,300 event-loop spins for a 400 MB installer, each one pumping paint events. The GUI couldn't actually move.
2. The 64 KB chunk size meant ~6,300 Python `read()` iterations per installer. Bumping to 1 MB chunks cuts that to ~400.

### What changed

- **New `DownloadWorker` (QThread)** in `app/updater.py`. The download now runs entirely off the GUI thread; signals update the progress dialog. The rest of the app stays fully responsive — you can scrub, browse profiles, queue more files while the download is in flight.
- **1 MB chunks** (was 64 KB). Roughly 16× fewer Python loop iterations per MB.
- **Progress signals throttled to ~10/sec** (was per-chunk). Smooth bar updates without overwhelming the event queue.
- **Progress bar uses 0..1000 range** so sub-percent movement is visible early in the download — no more "stuck at 0%" feel.
- **Transfer-rate display** (e.g. *3.6 / 395.1 MB · 4.7 MB/s*) so the user has live feedback about throughput.
- **Cancel button is wired to the worker** — clicking it sets a flag the worker polls between chunks, so cancel takes effect within ~100 KB at most.

---

# Veloxa Video Editor — V14.0.0

**Major release.** Big feature push across queue UX, preview, audio-visual templates, and theming.

## Queue right-click menu

- **▶ Preview This Row** — jump the preview pane to the clicked row.
- **⬆ Move N to Top** / **⬇ Move N to Bottom** — bulk reorder.
- **➕ Duplicate N Row(s)** — clone selected rows in place (same source, visual, profile).
- **↻ Retry N Failed/Done Row(s)** — reset rows to pending so the next Start re-runs them.
- The existing actions (Open source / Open output / Apply Profile / Change Visual / Remove / Delete from Disk) all stay.

## Preview

- **Source / Duration / Resolution / Codec / Profile** overlay in the top-left of the preview frame, semi-transparent dark backdrop, updates live with the selection.
- **Real video playback** via QtMultimedia — Play / Pause / Stop transport, volume slider, position read-out. The video widget overlays the preview frame when you press ▶; the static thumbnail comes back on Stop. Requires the bundled Qt6Multimedia DLLs (auto-bundled by PyInstaller).

## Audio-visual templates (real-time, no visual file needed)

A new dropdown in the **Audio Visuals** tab lets you pick a real-time visualisation that's synthesised frame-by-frame from the audio at encode time — no PNG / MP4 visual required:

- **Spectrum Bars** — classic frequency-spectrum bars on a dark background.
- **Circular Spectrum** — Spotify-canvas-style polar bars.
- **Waveform** — calm horizontal waveform on a tinted background.
- **Neon Audio Ring** — glowing audio ring (CQT + bloom).
- **Podcast Layout** — static dark hero on top, scrolling spectrum strip on bottom.
- **Spotify Canvas Style** — subtle dark background with a thin volume bar at the foot.

Set **— None —** (the default) to use the existing image / video visual pipeline.

## Themes

- **OLED Dark** — pure-`#000000` variant of the dark theme, picked from the same **Appearance** menu as System / Light / Dark. Designed for OLED panels where dark mode burns less power.

## Engine

- New `engine/audio_templates.py` module with the template registry. Each template renders a complete FFmpeg `filter_complex` from a single `[0:a]` input. Templates use `showspectrum`, `showcqt`, `showwaves`, `showvolume`, and `boxblur` — all bundled in the included FFmpeg essentials build.
- `JobRunner._encode_audio_with_template` is a parallel pipeline that runs alongside the existing `_encode_audio_to_video`. The intro/outro concat, bitrate / fade / loudnorm options, and output dimensions all work unchanged.

## Notes

- Visual-timeline zoom + frame-precision trimming was scoped out of V14.0 (the existing draggable seek-bar handles already provide visual trimming). Scheduled for V14.1.
- License dashboard + usage analytics intentionally not included — Veloxa stays free / open-source.

---

# Veloxa Video Editor — V13.1.1

**Patch release.** Real visual depth for the light theme.

## Fixed

The V13.1.0 light theme was too flat — all panels were the same plain white with thin gray borders, so the queue, preview, tabs, and bottom bar blurred into one big surface. This release re-does the light theme with proper visual hierarchy:

- **Tinted off-white main background** (`#eef0f4`) so the white "cards" (group boxes, lists, tab pane, text browsers) visibly pop.
- **Subtle vertical gradients** on buttons and inputs give a "raised" feel without leaving the flat-modern aesthetic.
- **Bigger card radius** (12 px on group boxes, 10 px on tab pane) for a more refined look.
- **Selected tab** now gets a 2 px brand-orange underline (replacing the previous flat highlight).
- **Focus rings** are 2 px (was 1 px) so the active input is unambiguous.
- **Alternating row colours** in queue list for easier scanning.
- **Polished primary button** (orange gradient + 1 px shadow line) and matching danger button.
- **Dark-on-light tooltip** (was white-on-white-with-border) for better legibility.
- **Refined slider handle** (16 px, 2 px orange ring) and **fatter progress bar** (20 px) with gradient chunk.

Dark theme is unchanged.

---

# Veloxa Video Editor — V13.1.0

**Minor release.** Design refresh + new System / Light / Dark theme switcher.

## New: theme switcher

A new **Appearance** submenu in the menu bar lets you pick:

- **System (follow Windows)** — the default. Reads Windows' `AppsUseLightTheme` registry key and picks the matching theme. Switches automatically if you toggle Windows light/dark mode while the app is open (on next launch).
- **Light** — bright, neutral warm-gray surfaces with the same orange accent. Designed for daytime / shared-screen editing where dark mode looks too dramatic.
- **Dark** — refreshed version of the V13.x dark look: softer borders, accent-coloured focus rings on inputs, calmer button states, refined tab look.

Your choice is persisted across sessions. The brand orange accent stays consistent in both modes so screenshots and on-screen indicators read the same.

## Design refresh (applies to both themes)

- Group boxes get bigger border radius (10px) and a wider title gutter for visual breathing room.
- Inputs and buttons share a 6px radius — previously a mix of 5px and varied amounts.
- Focus rings: every editable widget (`QLineEdit`, `QSpinBox`, `QDoubleSpinBox`, `QComboBox`) shows the brand orange when focused.
- Refined scrollbars (12 px, rounded handles, hover state).
- Refined `QToolTip` (compact 4 px radius, padded).
- Refined `QMenu` with separator styling.
- Better tab look — selected tab has a font-weight bump and an accent-coloured label.

---

# Veloxa Video Editor — V13.0.1

**Hot-fix release.** Patches the V13.0 auto-update crash and the missed version strings in the title bar / tray tooltip / session log.

## Bugs fixed

- **Update check crashed the app the second time it was invoked.** The startup auto-check connected `QThread.finished -> deleteLater`, which destroys the C++ QThread but leaves a Python wrapper pointing at it. The next call (e.g. clicking `Help → Check for Updates...`) hit `self._update_checker.isRunning()` on the dead object and the app crashed with no Python traceback. Fixed by trapping `RuntimeError` on the stale wrapper and clearing the Python reference the moment the thread finishes, *before* `deleteLater` runs.
- **Title bar, tray tooltip, header version label, and session-log lines still said "V12.3"** even on the V13.0 build because the strings were hardcoded in `app/main_window.py` and `app/persistence.py`. All now read from `app/updater.py::APP_VERSION` so future bumps only need to touch one constant.

## How to get this patch

V13.0 users: **the in-app updater is unsafe on your build** — the crash blocks it. Please download the V13.0.1 installer asset below and run it manually. The installer's stable AppId upgrades V13.0 in place, preserving profiles, settings, and queue state.

From V13.0.1 onwards, auto-update works for every future release.

---

# Veloxa Video Editor — V13.0

**Major release.** Adds GitHub-Releases-driven auto-update plus a large run of accumulated fixes and performance work from the V12.3.x patch storm.

## Headline feature: Auto-update via GitHub

- New `Help → Check for Updates...` menu item — always available.
- Opt-in startup check, **ON by default**. Silent if no update found; silent on any error (offline, rate-limited, etc.) so the app never nags.
- "Update available" dialog shows current vs. available version, release notes, download size, and a link to the GitHub release.
- Buttons: **Download & Install** / **Remind Me Later** / **Skip This Version**.
- The dialog has an inline `Check for updates on startup` checkbox so users can disable the auto-check without hunting in settings.
- Download streams to `%TEMP%` with a progress bar + cancel. Veloxa quits and launches the installer; the stable installer `AppId` upgrades in place, preserving profiles, settings, and queue state.
- Warning prompt if a batch is encoding when the user clicks Install.

## Output / encode improvements

- **Default quality is now "Best"** for video and audio (V12.3.5+).
- **Image-visual pre-scale (V12.3.5)** — image visuals are scaled to target dimensions once before the encode instead of every frame. Eliminates a per-frame CPU filter bottleneck; NVENC / QSV / AMF can now run closer to their rated throughput.
- **Hardware decode on audio-to-video path (V12.3.3)** — the looping video-visual now decodes on the GPU when a hwaccel encoder is in use, ending the CPU-decode bottleneck.
- **Output frame size always matches the user's selected resolution (V12.3.2)** — aspect-preserving scale + pad (letterbox/pillarbox) replaces the old straight stretch. `setsar=1` ensures square pixels so players show the correct DAR.
- **Profile_visuals re-order safety (V12.3.4)** — strict two-phase stage-then-swap. Re-ordering visuals + saving no longer destroys data.
- **Quality tier dropdowns (V12.3.1)** — Low / Medium / High / Best / Super Best replace raw kbps spinboxes. Tier resolves to a kbps target sized to the output resolution.
- **Audio fade / loudnorm / atempo not double-applied** in the intro/outro concat pass.
- **Main_tmp leak fixed** on encode cancel / failure in the intro/outro path.
- **Silent intro/outro inputs** are now padded with synthesised silence instead of crashing the concat filter.
- **Stale intro/outro asset files pruned** when the user clears the path in the profile.
- **Progress bar split** 0-50% main / 50-100% concat for the intro/outro pass, no more jump to 0%.

## Compatibility

- **Installer AppId preserved across V11.x → V12.x → V13.0.** Upgrading from any previous Veloxa Video Editor install replaces it in place.
- QSettings registry path is unchanged (`HKCU\Software\Veloxa-VD\V10`). Your profiles, watermark folders, and queue state all carry over.

## Requirements

- Windows 10 / 11 (64-bit)
- ~500 MB free disk
- Optional: NVIDIA / Intel / AMD GPU for hardware encoding (auto-detected)

## Asset

The Windows installer below upgrades any previous V11.x / V12.x install in place. Run it and the existing app is replaced; settings and profiles are preserved.
