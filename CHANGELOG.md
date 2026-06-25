# Veloxa Video Editor — V14.8.0

**Features.** Three features + a critical updater fix (the V14.6.0 download stall report).

## 1. In-app updater no longer stalls forever (your V14.6.0 bug report)

**Symptom:** progress dialog frozen at e.g. ``0.6 / 270.6 MB · 0.0 MB/s`` for minutes — no progress, no error. Internet is fine, GitHub release page loads in the browser. Closing the dialog is the only escape.

**Root cause:** ``app/updater.py::download_installer`` had **no per-read timeout and no inactivity detector**. If antivirus or aggressive CDN routing held the socket open with zero bytes flowing, ``resp.read()`` blocked forever. The dialog had no way to know the download was dead.

**Fix:** two layers of defence.

- **Socket-level recv timeout** (15 s). If any single read blocks longer than that with zero bytes, ``OSError`` raises and the download aborts with a clear "Download stalled" error.
- **Loop-level inactivity detector** (30 s). If no bytes have arrived across multiple reads for 30 s, abort the same way.

Replaces the previous "download failed silently after some unknowable amount of time" with "you get a clear failure dialog within 30 s of the connection going dead, with three useful buttons."

### New failure dialog

Replaces the V14.0.x plain-text "download failed" warning. Three buttons:

| Button | What it does |
|---|---|
| **Retry Download** | Re-attempts the in-app download. Useful for transient network blips. |
| **Open Release Page** | Opens ``github.com/.../releases/tag/vN.N.N`` in your browser. Pick whichever asset you need, see the release notes. |
| **Direct Installer Link** | Opens the asset URL directly, so your browser handles the transfer with its own resume + retry behaviour. **This is the recommended fallback** when the in-app downloader keeps stalling — your browser, your antivirus, all the proxy / VPN settings you already configured. |

### New "Download in Browser" option in the main update dialog

The update-available dialog now has a fourth button next to Download & Install / Remind Me Later / Skip: **Download in Browser**. Skips the in-app download entirely and opens the installer link directly so corporate-AV-paranoid users can route the transfer through their browser from the start.

### "You're up to date" now lists the release page

The manual ``Help → Check for Updates…`` dialog when you're current now includes both the current version (V14.8.0) and a clickable Release Page link — handy when you want to reinstall the same version or look at release notes for previous versions.

## 2. Custom FFmpeg-args passthrough (power users)

New **Extra FFmpeg flags** field in **Output**. Anything typed there is ``shlex.split``-parsed and appended to every output encode command just before the destination filename. Use it to set things like:

- ``-profile:v high`` (set H.264 profile to high)
- ``-x264-params keyint=120`` (force GOP size)
- ``-color_primaries bt709 -color_trc bt709 -colorspace bt709`` (mark colour metadata)
- ``-metadata title="My Title"`` (embed file metadata)

Empty = no override. Malformed flags are logged and ignored — never crash the encode. Verified end-to-end with a real encode setting ``-metadata title=v148_splice_test``, then reading it back via ``ffprobe``.

## 3. First-launch onboarding tour

Three message boxes triggered ~2 s after the first launch (gated by ``QSettings.onboarding_seen_v1``), highlighting the features new users most often miss:

1. **Profiles** — save reusable trim / watermark / codec / quality settings, apply with one click, mix-and-match per row.
2. **Audio Visuals** — six built-in templates that synthesise video from audio (Spectrum Bars, Waveform, Neon Ring, etc.), or auto-rotating user-supplied backgrounds via "Use these visuals".
3. **GPU status** — the status bar's GPU summary (per-machine auto-detection), and the Tools → Re-detect GPU Encoders menu item.

Each box has Skip Tour, so users who already know the app skip in one click. Re-run any time via **Help → Show Onboarding Tour**.

## 4. EBU R128 loudness normalisation (verified)

Already shipped in earlier versions — kept as-is. The checkbox **Normalize audio loudness (EBU R128, -16 LUFS)** in the Output tab applies ``loudnorm=I=-16:TP=-1.5:LRA=11`` (streaming + podcast standard). V14.8.0 ships a regression-guard test that verifies the filter is applied when ticked and absent when not.

## Full module inventory (per your request)

Organised by the categories you asked for:

### Entry & bootstrap
- ``main.py`` — CLI dispatch, HiDPI init, logging, crash-reporter install, single-instance guard, theme apply, ``MainWindow`` construction.
- ``make_icon.py`` — generates ``app.ico`` from canvas drawing.

### Core — processing
- ``engine/batch.py`` — ``JobRunner`` (single-encode QThread with FFmpeg progress parsing, V14.3.1 binary-mode I/O, V14.8.0 custom-args splice) + ``BatchManager`` (multi-job orchestrator, pause/resume, V14.3.0 parallel CPU slot, mid-batch ``add_jobs``, RAM watchdog, hard cap).
- ``engine/encoders.py`` — encoder catalogue (V14.7.0 AV1 + V14.4.1 runtime probe + machine-keyed cache), CLI arg builders, quality-tier tables, bitrate ↔ tier mapping.
- ``engine/filters.py`` — FFmpeg filter-graph construction for trim, fade, watermark, text watermark, video watermark, scale/pad, speed, audio normalisation, loudnorm.
- ``engine/ffmpeg.py`` — FFmpeg/ffprobe locator + probe helpers + preview generators (image, audio-template, audio-with-visual).
- ``engine/audio_templates.py`` — six audio-visual templates (Spectrum Bars, Circular Spectrum, Waveform, Neon Audio Ring, Podcast Layout, Spotify Canvas Style).
- ``engine/system_resources.py`` — parallel CPU slot helpers (priority drop, thread cap, RAM watchdog, encoder swap).

### Core — supporting services
- ``app/persistence.py`` — app data dir, log dir, ``setup_logging``, queue state save/load/clear, watermark hash-import.
- ``app/updater.py`` — GitHub Releases poller (``UpdateChecker``), background downloader (``DownloadWorker``, V14.8.0 stall detection), ``launch_installer_and_quit``.
- ``app/platform_compat.py`` — Win/Mac/Linux flags, ``pick_release_asset`` (V14.3.4 routing guarantee), open-in-file-manager, FFmpeg locator.
- ``app/crash_reporter.py`` — V14.5.0 ``sys.excepthook``, ``write_crash_file`` (with username scrubbing), ``build_issue_url``.
- ``app/single_instance.py`` — V14.1.0/V14.1.1 QLocalServer + QLocalSocket + ACK handshake.
- ``app/watch_folder.py`` — ``FolderWatcher`` (filesystem watcher that auto-adds new files to the queue).
- ``app/profile_assets.py`` — per-profile asset folder management.
- ``app/cli.py`` — headless ``--cli`` mode entry.

### UI — shell & pages
- ``app/main_window.py`` — ``MainWindow``: queue + preview pane + settings tabs (Trim / Watermark / Audio Visuals / Output) + menu bar + batch controls + status bar.
- ``app/dialogs.py`` — ``ProfileManagerDialog``, ``WatchFolderDialog``, ``ManageSavedDataDialog``, ``show_info_dialog``, ``NO_PROFILE``.

### UI — components
- ``app/widgets.py`` — ``QueueItemData`` dataclass (serialisable for V14.5.0 resume), ``TrimSeekBar``, ``DropList``.
- ``app/theme.py`` — ``DARK_QSS`` / ``LIGHT_QSS`` / ``OLED_QSS`` stylesheets, ``apply_theme()``, system-theme detector, ``make_runtime_icon()``, time formatters.
- ``app/docs.py`` — in-app HTML docs (README, INSTALL, HELP, LICENSE).

### Cross-cutting / infrastructure
- ``requirements.txt`` — pinned runtime deps (``PyQt6>=6.6``, ``psutil>=5.9``).
- ``build.ps1`` — Windows PyInstaller ``--onedir`` build script (V14.3.7+).
- ``installer.iss`` — Inno Setup script for the Windows installer.
- ``.github/workflows/build_macos.yml`` — GitHub Actions: builds ``.app`` via PyInstaller ``--onedir``, ad-hoc signs, packs as ``.dmg`` with create-dmg, uploads to release.
- ``_qa/`` — 9 test suites: master regression (``regress_v12_3.py``), end-to-end encodes (``encode_e2e.py``, real FFmpeg), dispatch invariants (``v143_dispatch_unit.py``), audio templates (``v143_audio_template_preview.py``), auto-assign (``v143_auto_assign_visuals.py``), platform routing (``v143_platform_asset_routing.py``), crash reporter (``v145_crash_reporter.py``), folder import (``v146_add_from_folder.py``), V14.8.0 features (``v148_features.py``).

## Tests

**Every suite green, with the V14.8.0 changes:**

| Suite | Result |
|---|---|
| Main regression (``regress_v12_3.py``) | 426 / 426 |
| End-to-end encodes (``encode_e2e.py``, real FFmpeg) | 99 / 99 |
| Dispatch unit (``v143_dispatch_unit.py``) | 33 / 33 |
| Audio-template preview (``v143_audio_template_preview.py``) | 15 / 15 |
| Auto-assign visuals (``v143_auto_assign_visuals.py``) | 24 / 24 |
| Platform-asset routing (``v143_platform_asset_routing.py``) | 26 / 26 |
| Crash reporter (``v145_crash_reporter.py``) | 22 / 22 |
| Add-from-Folder (``v146_add_from_folder.py``) | 17 / 17 |
| V14.8.0 features (``v148_features.py``, new) | 30 / 30 |
| **Total** | **692 / 692** |

EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** ``Veloxa-Video-Editor-V14.8.0-Setup.exe`` (271 MB, --onedir)
- **macOS:** ``Veloxa-Video-Editor-V14.8.0-macOS.dmg`` (~88 MB, ad-hoc signed)

> **If you're stuck on V14.6.0 / V14.7.0 and the in-app downloader keeps stalling at 0.0 MB/s,** you can grab V14.8.0 directly from this release page and run it. The new installer overwrites the existing install in place — your profiles, queue, and settings are preserved. After V14.8.0 the new stall detection + Download-in-Browser button will prevent this from happening again.

Direct installer link (right-click → Save link as…): ``https://github.com/khurram5509/Veloxa-Video-Editor/releases/download/v14.8.0/Veloxa-Video-Editor-V14.8.0-Setup.exe``

---

# Veloxa Video Editor — V14.7.0

**Feature.** **AV1 codec support** — ~30 % smaller files at the same visual quality vs H.264, with automatic GPU acceleration on supported cards.

## What ships

Output → Codec dropdown gains **AV1** as a third option alongside H.264 (AVC) and H.265 (HEVC). Four AV1 encoders are now in the catalog, picked automatically per machine via the V14.4.1 runtime probe:

| Encoder | Hardware required | Picked first when… |
|---|---|---|
| ``av1_nvenc`` (NVIDIA NVENC AV1) | RTX 40-series (Ada) or newer | NVIDIA AV1 hardware found |
| ``av1_amf`` (AMD AMF AV1) | RX 7000-series (RDNA 3) or newer | AMD AV1 hardware found |
| ``av1_qsv`` (Intel QSV AV1) | Arc / 12th-gen Core or newer | Intel AV1 hardware found |
| ``libsvtav1`` (SVT-AV1 on CPU) | Any (in modern FFmpeg builds) | No GPU AV1 found |

Each encoder has Fast / Balanced / High Quality presets tuned per vendor (NVENC ``p3/p5/p7``, QSV ``faster/medium/slower``, AMF ``speed/balanced/quality``, SVT-AV1 preset ``8/6/4``).

CRF defaults are calibrated to the AV1 quality scale: SVT-AV1 ``crf 30`` ≈ libx264 ``crf 18`` visually. Bitrate mode (``-b:v Nk``) works the same as on H.264 / HEVC for users who want explicit file-size targets.

## How the existing GPU detection picks AV1

The V14.4.1 runtime probe at app launch now also tests ``av1_nvenc``, ``av1_amf``, ``av1_qsv``, and ``libsvtav1`` — same FFmpeg probe (``-f lavfi -i color … -c:v <enc> -frames:v 1 -f null -``), same machine-keyed cache. Encoder cache schema bumped 3 → 4 so every PC re-probes once on first launch after upgrading.

The status bar on launch now reads e.g. ``GPU acceleration: NVIDIA NVENC (incl. AV1) (auto-detected). Settings → Output → Encoder lets you override.`` — instantly visible whether your card supports AV1.

The Output → Encoder dropdown only shows the AV1 variants that actually work on your machine, so a Ryzen 5800 laptop with no AV1 hardware sees just ``CPU (SVT-AV1)``, while an RTX 4090 sees ``NVIDIA NVENC (AV1) · CPU (SVT-AV1)``.

## Tested with the build PC

The build PC has an older NVIDIA card without AV1 NVENC. The probe correctly detected its capabilities:

```
GPU acceleration: NVIDIA NVENC · SVT-AV1 (CPU) (auto-detected).
```

A real AV1 encode through the production code path produced a valid AV1-in-MP4 output (``Video: av1 (libdav1d) … (av01 / 0x31307661)``) with exit code 0 — proving the args + cache + dropdown wiring all work end-to-end.

## Tests

- **426 / 426** main regression probes pass (**31 new V14.7.0 probes** verify the four AV1 encoders are in the catalog, ``ENCODER_FOR_CODEC[CODEC_AV1]`` is correct, ``AUTO_PRIORITY_AV1`` follows the NVIDIA → AMD → Intel → CPU pattern, ``encoder_codec_args`` produces the right ``-c:v`` flags + CRF / QP / bitrate args for each, the GUI wiring routes AV1 through the right priority list, and ``_describe_gpu_status`` flags AV1 hardware separately from H.264 / HEVC).
- Behavioural smoke: real AV1 encode succeeded on the build PC via ``libsvtav1``.
- EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** ``Veloxa-Video-Editor-V14.7.0-Setup.exe`` (271 MB, --onedir)
- **macOS:** ``Veloxa-Video-Editor-V14.7.0-macOS.dmg`` (~88 MB, ad-hoc signed; uses Apple VideoToolbox where the hardware exposes AV1)

Existing V14.x users will be offered V14.7.0 via Help → Check for Updates… — Mac users get the .dmg, Windows users get the .exe (per V14.3.4 routing guarantee). The cache will re-probe on first launch so AV1 lights up automatically on supported hardware.

---

# Veloxa Video Editor — V14.6.0

**Feature.** New **📂 Add from Folder…** button — pick a folder and the app pulls in every supported video / audio file in it AND every subfolder, in one click.

## How it works

The queue toolbar has a new button next to **＋ Add Files…**. Clicking it:

1. Opens a folder picker (the last-used folder is remembered separately from the last-used file folder).
2. Walks the chosen folder + every subfolder via ``os.walk`` — depth-first, deterministic case-insensitive sort within each directory.
3. Picks every file whose extension is in ``ALL_INPUT_EXTS`` (videos: ``.mp4 .mov .mkv .avi .webm .flv .wmv .m4v .mpg .mpeg .ts .3gp``; audio: ``.mp3 .wav .m4a .flac .aac .ogg .opus .wma``). Sidecar ``.srt``, ``.jpg`` artwork, ``.docx`` notes, etc. are skipped.
4. Funnels the collected paths through the existing ``_add_files`` so dedup, audio-visual auto-assign (V14.3.5), the mid-batch ``add_jobs()`` hook (V14.3.0), and the queue persistence (V14.5.0 resume) all work without changes.

The button stays enabled mid-batch — newly-discovered files append to the running queue's tail like a manual Add Files would.

## Edge cases handled

- **Misclick on a 4 TB drive root**: hard cap at 100 000 files keeps the GUI responsive. The user sees a status update + log line if the cap is hit.
- **Empty folder / no supported files**: friendly dialog listing the supported extensions instead of silently doing nothing.
- **Unreadable subfolder** (permission denied): walk continues; failure surfaces as a warning dialog.
- **Symlinks**: ``followlinks=False`` so a recursive symlink can't blow up the walk.
- **Empty subfolders**: the walk skips them cleanly.

## Tests

- 395 / 395 main regression probes pass (7 new V14.6.0 probes verify the button wiring, the new handler, the collector function, mid-batch enabled state, and a behavioural smoke that scans a temp fixture tree).
- 17 / 17 dedicated folder-scan unit tests (``_qa/v146_add_from_folder.py``) — covering the happy path, .srt / .jpg / .docx skipping, deterministic sort order, the max_files cap, missing folders, and empty-result folders.
- EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** ``Veloxa-Video-Editor-V14.6.0-Setup.exe`` (271 MB, --onedir)
- **macOS:** ``Veloxa-Video-Editor-V14.6.0-macOS.dmg`` (~88 MB, ad-hoc signed)

---

# Veloxa Video Editor — V14.5.0

**Features.** Resume interrupted batches with one click + opt-in crash reporter that sends a pre-filled GitHub Issue.

## 1. Resume interrupted batches

If the app or the PC dies mid-batch (power loss, crash, accidental close), the queue state has always been persisted to ``%APPDATA%\Veloxa-VD\V10\queue_state.json``. The restore dialog now has a third button:

- **Resume & Start** — restores the queue and immediately fires Start Batch. One click and the unfinished encodes pick up where they left off.
- **Restore only** — restores the queue but doesn't start (the previous "Yes" behaviour). Lets the user inspect rows before re-running.
- **Discard** — wipes the saved state (was "No").

Interrupted rows (``status == "encoding"`` at crash time) are reset to ``pending`` so the BatchManager picks them up on Start. Any partial output files from the killed encodes are overwritten by FFmpeg's ``-y`` flag — no manual cleanup needed.

## 2. Opt-in crash reporter

A new ``sys.excepthook`` installed in ``main.py`` (BEFORE Qt starts so even a ``MainWindow`` constructor exception is captured) writes a ``crash_<timestamp>.txt`` to ``%APPDATA%\Veloxa-VD\V10\logs\`` containing:

- App version, Python version, platform string
- The full traceback
- The last ~200 lines of the active session log
- **Username scrubbed from any path** that appears in the report (``C:\Users\Khurram\…`` → ``C:\Users\<user>\…``)

On the next successful launch the GUI scans for unactioned crash files and (once you've opted in) offers three choices per crash:

- **Send report** — opens a **pre-filled GitHub Issue** in your default browser, with the title and body already populated. **No data is sent automatically** — you review and submit on github.com.
- **Later** — leaves the file in place; we ask again next launch.
- **Discard** — marks the file ``*.dismissed`` so we never prompt about it again.

### Opt-in flow

On the first launch that finds a pending crash, you get a one-time dialog explaining what's in a report and asking whether to enable. Your choice is persisted under QSettings (``crash_reports_opt_in``) — you can flip it any time via **Tools → Crash reporting settings…**.

### Manual reports

**Tools → Report a problem…** lets you file a GitHub Issue with the *current* session log even when nothing crashed (useful for "weird behaviour but the app didn't die" reports).

## Files

- New: ``app/crash_reporter.py`` — excepthook installer, write_crash_file, list_pending_reports, mark_reported / mark_dismissed, build_issue_url, _sanitize_paths.
- New: ``_qa/v145_crash_reporter.py`` — 22 unit probes covering sanitisation, file IO, URL building, and excepthook chaining.
- ``main.py`` — installs the excepthook right after ``setup_logging()`` so MainWindow construction errors are captured too.
- ``app/main_window.py`` — startup scans for pending crashes (3 s after launch so the auto-update dialog gets first dibs); Tools menu gains **Report a problem…** and **Crash reporting settings…**; resume dialog reworked to 3-way (Resume & Start / Restore only / Discard).

## Tests

- 388 / 388 main regression probes pass (23 new V14.5.0 probes verify the crash reporter API surface, sanitisation, main.py wiring, MainWindow handlers, the three-way resume dialog, and the auto-start helper).
- 22 / 22 dedicated crash-reporter unit tests (``_qa/v145_crash_reporter.py``).

## Downloads

- **Windows:** ``Veloxa-Video-Editor-V14.5.0-Setup.exe`` (271 MB, --onedir)
- **macOS:** ``Veloxa-Video-Editor-V14.5.0-macOS.dmg`` (~88 MB, ad-hoc signed)

---

# Veloxa Video Editor — V14.4.1

**Feature.** GPU encoders are explicitly **detected per physical PC**, with a visible status line and a Tools menu item to force a re-probe.

## What this confirms (and what's new)

> *"If the GPU is there can you use the GPU for fast processing? Not for one machine — detect the GPU and act accordingly if it's installed to some other PC."*

GPU acceleration has been working since V12.x. The detection has always been runtime — at every launch the app spawns a real FFmpeg encode against each GPU encoder candidate (`h264_nvenc`, `hevc_nvenc`, `h264_amf`, `hevc_amf`, `h264_qsv`, `hevc_qsv`) and only keeps the ones that return exit code 0 on **this** machine. Nothing about your GPU is baked into the build.

The `(auto)` encoder option picks the fastest available in this order:

| Priority | Encoder | Vendor |
|---|---|---|
| 1 | `h264_nvenc` / `hevc_nvenc` | NVIDIA NVENC |
| 2 | `h264_amf` / `hevc_amf` | AMD AMF |
| 3 | `h264_qsv` / `hevc_qsv` | Intel QSV |
| 4 (fallback) | `libx264` / `libx265` | CPU |

So an install on a workstation with a GeForce RTX picks NVENC, the same installer on a Ryzen-only laptop picks AMF, an Intel ultrabook picks QSV, and a NUC with no GPU drops to CPU — without any user action.

## What's new in V14.4.1

### 1. Cache is now machine-keyed

The runtime probe is cached at `%APPDATA%\Veloxa-VD\encoder_cache.json` so repeat launches are instant. Up through V14.4.0 the cache key was the FFmpeg version string only — meaning if your `%APPDATA%` was synced across PCs via OneDrive, a roaming profile, or a manual `xcopy`, an NVENC-detected cache would silently apply on a different AMD-only machine and every encode would fail.

V14.4.1 adds a **machine ID** (a hash of hostname + first MAC address, via `platform.node()` + `uuid.getnode()`) to the cache key. The schema bumped to **3**, so any existing cache from V14.3.x / V14.4.0 is ignored automatically — every PC re-runs detection once on first launch.

### 2. Status bar shows what was detected

On every launch the status bar (bottom of the window) now reads one of:

- `GPU acceleration: NVIDIA NVENC (auto-detected). Settings → Output → Encoder lets you override.`
- `GPU acceleration: AMD AMF · Intel QSV (auto-detected). Settings → Output → Encoder lets you override.`
- `No GPU encoder detected on this PC — encoding will use CPU (libx264 / libx265). Tools → Re-detect GPU encoders to rerun the probe.`

…so you can see at a glance what's active without opening Settings.

### 3. Tools → Re-detect GPU encoders

A new menu item under **Tools** that bypasses the cache (`force_rescan=True`), reruns the probe, refreshes the encoder dropdown, and shows a summary dialog with the result. Use it when:

- You just installed or updated GPU drivers and want the app to pick up new hardware capabilities
- You swapped GPUs on the same physical PC
- The encoder dropdown looks wrong (e.g. NVENC isn't listed even though you have a GeForce card)

## Tests

365 / 365 main regression probes pass (13 new V14.4.1 probes verify the schema bump, the machine-ID helper, that the cache reads / writes the new field, that detect_available_encoders accepts the new `force_rescan` kwarg, the Tools menu wiring, the status-bar GPU summary, and that the function still degrades gracefully when FFmpeg is missing).

Behavioural check on the build PC: `detect_available_encoders` correctly probed and returned `libx264, libx265, h264_nvenc, hevc_nvenc`.

## Downloads

- **Windows:** `Veloxa-Video-Editor-V14.4.1-Setup.exe` (271 MB, --onedir)
- **macOS:** `Veloxa-Video-Editor-V14.4.1-macOS.dmg` (~88 MB, ad-hoc signed; uses Apple `VideoToolbox` when the hardware supports it via FFmpeg's existing probe path)

---

# Veloxa Video Editor — V14.4.0

**Feature / hot-fix.** macOS menubar now shows **Tools / Help / Appearance** — previously only Appearance was visible, leaving no way to reach the update checker, the logs, the watch folder, or the docs.

## What was broken (your report)

> *"In MAC top bar are not complete is should be same appearance option only, on mac its not showing the auto update option and to update"*

On macOS the app's menubar at the top of the screen only had ``Appearance``. ``Check for Updates…``, ``README``, ``Installation Guide``, ``User Guide``, ``License``, ``Watch Folder…``, ``Manage Saved Data…``, and ``Open Log Folder`` were all silently dropped — you had no way to reach them from the menubar. On Windows the same items rendered fine, so the bug only showed on Mac.

## Root cause

The V13–V14.3 menubar code used ``mb.addAction(act)`` to put each of those entries directly on the menu bar as a flat action. On Windows that renders as a clickable menubar item. **On macOS the native menubar silently drops top-level QAction items** — only proper ``QMenu`` submenus (added via ``mb.addMenu(name)``) are shown. ``Appearance`` was the only menu we built that way, which is why it was the only thing the macOS menubar displayed.

There was a second, related landmine: if Qt did display a flat action whose text matches a macOS reserved name (``About``, ``Quit``, ``Preferences``, ``Check for Updates``, etc.) it auto-moves the item into the *Apple menu* (top-left of the screen, easy to miss) via Qt's ``TextHeuristicRole``.

## Fix

`app/main_window.py::_build_menu_bar` — restructured into three proper submenus, with every action's ``MenuRole`` explicitly set to ``NoRole`` so Qt's auto-move can't relocate them on macOS:

| Menu | Contents |
|---|---|
| **Tools** | Watch Folder… · Manage Saved Data… · Open Log Folder |
| **Help** | README · Installation Guide · User Guide · License · ─── · **Check for Updates…** |
| **Appearance** | System (follow OS) · Light · Dark · OLED Dark (pure black) |

Same wire-up on both platforms — Windows users see the same three-menu structure, and the items they were finding under the old flat layout are all still there, just one click deeper.

## Notable detail: ``Check for Updates…``

Explicit ``MenuRole.NoRole`` keeps the item in the **Help** menu on macOS. Without it, Qt's ``TextHeuristicRole`` would have auto-moved it into the *Apple menu* (under ``Veloxa Video Editor → Check for Updates…``), which is more native macOS-y but easy to overlook. Help → Check for Updates is the place every user already expects.

Also relabeled ``System (follow Windows)`` → ``System (follow OS)`` in the Appearance menu since the app is now cross-platform.

## Tests

352 / 352 main regression probes pass (11 new V14.4.0 probes verify the three submenus, that every menu item uses ``MenuRole.NoRole``, that ``Check for Updates`` lives in Help, that no flat ``mb.addAction`` survives, and that every previous menu entry has a home in the new structure).

24 / 24 auto-assign probes still green. EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** ``Veloxa-Video-Editor-V14.4.0-Setup.exe`` (271 MB, --onedir)
- **macOS:** ``Veloxa-Video-Editor-V14.4.0-macOS.dmg`` (~88 MB, ad-hoc signed)

Existing V14.3.x users will be offered V14.4.0 via Help → Check for Updates… — Mac users get the .dmg, Windows users get the .exe (per V14.3.4 routing guarantee).

---

# Veloxa Video Editor — V14.3.9

**Hot-fix.** Audio rows no longer show **"(visual needed)"** when an Audio Visuals template is selected.

## What was broken (your report)

User report (macOS): *"on MAC it's not selecting the visuals from the Audio Visual auto, it shows 'visual pending'"*.

Symptom: even with an Audio Visuals template selected (Spectrum Bars, Waveform, Neon Audio Ring, Podcast Layout, Spotify Canvas, etc.), every audio row in the queue showed the **"(visual needed)"** tag — the same tag the queue uses to flag *"you forgot to assign a visual to this row"*. The encode actually worked correctly (the template synthesised the visual at encode time), but the label was lying.

## Root cause

In V14.3.5–V14.3.8 the audio-row label only knew about two states:

| `d.visual_path` set? | Label suffix |
|---|---|
| Yes (image) | `+image-visual` |
| Yes (video) | `+video-visual` |
| No | `(visual needed)` |

There was no third branch for *"no per-row visual is set, but an audio template is active so one is being synthesised from the audio"*. The auto-assign function in V14.3.5 correctly no-ops when a template is active (templates and per-row visuals are mutually exclusive by design — see the V14.3.5 decision matrix), and the modal prompt is also correctly skipped. But the row data ended up with `visual_path=None`, which the label code treated as a misconfiguration.

## Fix

`app/main_window.py::_refresh_item_label` — the label now branches on `_has_audio_template_active()` and shows the active template's display name when no per-row visual is set:

| Per-row `visual_path` set? | Template active? | Label suffix |
|---|---|---|
| Yes (image) | — | `+image-visual` |
| Yes (video) | — | `+video-visual` |
| **No** | **Yes** | **`+Spectrum Bars`** *(or whichever template is picked)* |
| No | No | `(visual needed)` |

The fourth row is the only state that should ever read as a misconfiguration — and it now correctly does, since it only fires when the user has *neither* a per-row visual *nor* a template selected.

## Bonus: diagnostic logging

`_auto_assign_audio_visuals_for_new` now writes a log line for every gate it hits:

- `Auto-assign: skipped (audio template active — ...)` — template selected, per-row rotation correctly bypassed
- `Auto-assign: skipped ('Use these visuals for audio inputs (round-robin)' checkbox is OFF — tick it to enable auto-assign)`
- `Auto-assign: %d Profile Visuals path(s) are missing on disk: ...` — paths in the list don't resolve on this machine (common when settings carry over from a different OS)
- `Auto-assign: skipped (Profile Visuals list has 0 usable entries — list size=N, on-disk-missing=M)`
- `Auto-assigned visuals to N new audio file(s) from profile 'P' (counter now C)` — success

If auto-assign isn't working, the log file (Help → Open Log Folder) now spells out exactly which gate blocked it instead of being silent.

## Tests

- 341 / 341 main regression probes (7 new V14.3.9 probes verify the label branches on template state, keeps the "(visual needed)" fallback, uses the template's display name as the tag, and that each diagnostic log line is present).
- 24 / 24 auto-assign behavioural probes still green.
- EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** `Veloxa-Video-Editor-V14.3.9-Setup.exe` (271 MB, --onedir)
- **macOS:** `Veloxa-Video-Editor-V14.3.9-macOS.dmg` (~88 MB, ad-hoc signed)

---

# Veloxa Video Editor — V14.3.8

**Hot-fix.** macOS — the Watermark / Audio Visuals / Output settings tabs no longer render with overlapping rows.

## What was broken

On macOS, the Settings → **Watermark** tab (and the other settings tabs to a smaller degree) rendered with row labels stacked on top of their controls — the `Image:` label sat over the file-picker line edit, `Position:` sat over the position combo, etc. Every control was technically present but visually layered.

## Root cause

Settings tabs use a `QGridLayout` inside each `QGroupBox` (Image Watermark / Video Watermark / Text Watermark). The natural content height of those three group boxes stacked vertically is around 750-800 px on macOS, where the native `QComboBox` / `QSpinBox` / `QPushButton` controls are noticeably taller than the Windows defaults.

On a window that's shorter than the natural content height, Qt's layout engine has two options: scroll, or squish the rows to fit. There was **no `QScrollArea` wrapping the tab content**, so Qt squished every row by ~10-15 px, which is enough to push the controls visually behind the previous row's label. On Windows the natural height fit, so nobody saw the bug there.

## Fix

`app/main_window.py`:

- New `MainWindow._wrap_in_scroll(content)` helper — wraps a widget in a `QScrollArea` with `setWidgetResizable(True)`, no frame, and the horizontal scrollbar disabled.
- `_build_settings_pane` wraps **all four** tabs (Trim, Watermark, Audio Visuals, Output) so the same bug can't show up on a different tab when controls are added later.

`app/theme.py`:

- Both `DARK_QSS` and `LIGHT_QSS` style `QScrollArea` flat (transparent background, no border) so it reads as part of the tab pane.
- Both QSS files style `QScrollBar:vertical` so the new vertical scrollbar matches the theme (thin, rounded, brand-accent on hover).

## What you'll see now

If the window is tall enough, the tab looks exactly as before — no scrollbar appears. If the window is short, a slim vertical scrollbar appears on the right side of the tab content and you can scroll to reach the rows that fell off the bottom. No more overlap on any platform.

## Tests

- 334 / 334 main regression probes pass (8 new V14.3.8 probes verify the wrap helper, the import, all four tabs wrapped, and the QSS styling in both themes).
- EXE smoke launch on Windows: clean.

## Downloads

- **Windows:** `Veloxa-Video-Editor-V14.3.8-Setup.exe`
- **macOS:** `Veloxa-Video-Editor-V14.3.8-macOS.dmg` (ad-hoc signed)

---

# Veloxa Video Editor — V14.3.7

**Hot-fix.** First launch after an update no longer fails with **"Failed to load Python DLL ... python314.dll. LoadLibrary: The specified module could not be found."** — you no longer have to close and re-open the app.

## What was happening (the issue)

Up through V14.3.6 the Windows build was produced with PyInstaller's `--onefile` flag — a single 400 MB EXE that, at every launch, extracts its entire bundled payload (Python, Qt, FFmpeg, every DLL we depend on) to a random `%TEMP%\_MEI{N}` directory and then `LoadLibrary`'s `python314.dll` from that directory.

Right after an in-app update, three things were happening simultaneously:

1. The installer had just written a 400 MB EXE to `C:\Program Files\Veloxa Video Editor\`.
2. Windows Defender's real-time scanner was working through that fresh file, holding open file handles on it (and on the bundled DLLs it streams through the extractor).
3. The installer's "Launch Veloxa Video Editor V14.x" checkbox launched the new EXE *immediately* — while Defender was still scanning.

The `--onefile` bootloader extracted into `_MEI{N}` and then tried to load `python314.dll` from there, but the loader couldn't satisfy the LoadLibrary call because Defender was holding the bytes. Windows reported it as the generic "specified module could not be found" error. Closing the dialog and re-launching from the Start Menu worked because by then Defender had finished scanning.

## Fix

The Windows build was switched from `--onefile` to `--onedir` (the macOS build has used `--onedir` since V14.2.0). With `--onedir`:

- `python314.dll`, `Qt6Core.dll`, and every other support file live permanently in `C:\Program Files\Veloxa Video Editor\_internal\`.
- There is **no extraction** at launch. The bootloader is a tiny 2.4 MB launcher that just calls Python directly.
- The launcher loads `_internal\python314.dll` once, from disk. Defender has long since finished scanning that file (installs leave files in place; the next launch is reading bytes the OS already cached).

Side benefits:

- **Faster launch.** No more 2-5 s extraction wait per cold start.
- **Smaller installer.** 271 MB (was 396 MB) — many small files compress better than one 400 MB blob inside the Inno Setup bottle.
- **No more `_MEI*` clutter in `%TEMP%`.** Old builds would leave orphaned `_MEI{N}\` directories behind on crashes; that's gone.

## Implementation

- `build.ps1`: `--onefile` → `--onedir`.
- `installer.iss`: `[Files]` now copies both the launcher EXE *and* the `_internal\` subtree, with `recursesubdirs createallsubdirs`. `[InstallDelete]` now sweeps `{app}\_internal` before each install so a removed-dependency DLL from an older V14.3.7+ build can't linger.
- `[Icons]` / `[Run]` keep pointing at the unversioned `Veloxa-Video-Editor.exe`, so all the existing shortcuts and the in-app updater still work without changes.

## Tests

326 / 326 main regression probes pass — 5 new V14.3.7 probes verify the build mode flip in `build.ps1` and the installer's `[Files]` / `[InstallDelete]` changes. Local install + launch round-trip confirmed: kill old, run installer, launch from Start Menu — instant, no DLL error.

## Downloads

- **Windows:** `Veloxa-Video-Editor-V14.3.7-Setup.exe` (271 MB, was 396 MB)
- **macOS:** `Veloxa-Video-Editor-V14.3.7-macOS.dmg` (~88 MB, unchanged, ad-hoc signed)

Existing V14.3.x users will be offered V14.3.7 via Help → Check for Updates… — Mac users get the .dmg, Windows users get the .exe (per V14.3.4 routing guarantee).

---

# Veloxa Video Editor — V14.3.6

**Hot-fix.** Light theme: queue-row filename text is readable again.

## What was broken

In the V14.3.5 light theme, the queue list rendered like this:

> [V] BIA_Dual_Standard_Masterclass.mp4  DONE

…with the filename text drawn in **`#e6e6e6`** (almost-white) on the light/cream row backgrounds. The labels were effectively invisible. Selected rows had **`#ffffff`** (pure white) text on the **`#ffe1c2`** light-orange selection band — same problem.

## Root cause

`main_window._apply_row_selection_styles` was hard-coding the inline label colour to `#ffffff` / `#e6e6e6` — values that work on the dark theme's dark row backgrounds but become invisible-on-cream in the light theme. The colour didn't react to the active theme at all.

## Fix

Two changes:

1. Both `DARK_QSS` and `LIGHT_QSS` (in `app/theme.py`) now carry an explicit `QLabel[role="queue-row-label"]` rule with theme-appropriate text colours and a `[selected="true"]` variant.
2. `main_window._apply_row_selection_styles` drops the inline stylesheet and instead toggles a `selected` dynamic property on the label. The QSS picks up the change after a re-polish, so the label colour now tracks the active theme:

| Theme | Unselected row text | Selected row text |
|---|---|---|
| Light | `#1c2128` (dark on white) | `#1c2128` bold (dark on light orange) |
| Dark / OLED | `#e6e6e6` (light grey on dark) | `#ffffff` bold (white on dark orange) |

## Tests

321 / 321 main regression probes (6 new V14.3.6 probes covering: rule presence in both QSS files, correct colour values per theme, presence of the `[selected="true"]` variant, removal of the hard-coded inline colours, and that the apply-styles helper re-polishes after the property change).

## Downloads

- **Windows:** `Veloxa-Video-Editor-V14.3.6-Setup.exe`
- **macOS:** `Veloxa-Video-Editor-V14.3.6-macOS.dmg` (ad-hoc signed)

---

# Veloxa Video Editor — V14.3.5

**Feature.** Audio files added to the queue can now be auto-assigned visuals from the Audio Visuals tab — one-by-one in round-robin order — so the user doesn't have to right-click each row to set its visual.

## How it works

When you tick **Audio Visuals → "Use these visuals for audio inputs (round-robin)"** and have at least one visual in the Profile Visuals list, every audio file added to the queue (drag-drop OR the Add Files button) is assigned the next visual in the list. The per-profile rotation counter persists across batches and sessions exactly like the existing batch-start rotation — adding 3 audio files followed by another 2 picks visuals 1, 2, 3, then 4, 5 (wrapping when the list runs out).

If an Audio Visuals template (Spectrum Bars, Waveform, Neon Audio Ring, etc.) is selected, the auto-assign is a no-op — the template synthesises its own visual from the audio, no list assignment needed.

## Decision matrix

| Audio template | "Use these visuals" | What happens on add |
|---|---|---|
| Selected (e.g. Spectrum Bars) | either | Template synthesises visual, no per-row visual assigned, no modal prompt. |
| None | OFF | Legacy modal prompt — pick one shared visual for all newly-added audio files. |
| None | ON, list empty | Legacy modal prompt (rotation can't fire without entries). |
| None | ON, list non-empty | **Auto-assign** rotates through the list; no modal. |

## Implementation

- New `MainWindow._has_audio_template_active()` and `MainWindow._auto_assign_audio_visuals_for_new(audio_paths, profile)` in `app/main_window.py`.
- `_add_files` consults the auto-assign first; if it returned any entries OR a template is active, the legacy "pick one visual for all audio files" modal is skipped.
- `_build_jobs` now skips the batch-start rotation when the row already has a `visual_path` set — so the auto-assign counter advance at add-time isn't double-applied at batch-start.
- Only newly-added files are touched. Existing pending audio rows with no visual stay untouched (no surprise mutation).
- Rotation counter (`_pv_get_counter` / `_pv_set_counter`) is shared with the legacy batch-start path so both code paths advance the same per-profile sequence in QSettings, persisted on every change.

## Tests

- New `_qa/v143_auto_assign_visuals.py` — 24 probes covering: template-active no-op, checkbox-OFF no-op, empty-list no-op, no-audio no-op, happy-path 4-file rotation with wrap-around, counter persistence across calls, missing-file filtering, `_build_jobs` doesn't double-advance, `_has_audio_template_active` reflects combo state, and `_add_files` wiring.
- 10 new probes in the main regression suite covering the same source-level invariants.
- **312 / 312** regression probes + **33 / 33** dispatch + **26 / 26** platform routing + **24 / 24** auto-assign + **15 / 15** audio-template preview + **99 / 99** e2e encode = **509 / 509 PASS**.

---

# Veloxa Video Editor — V14.3.4

**Hot-fix.** Hardened the platform-asset selector and added an
adversarial test suite so a Mac user can NEVER receive a Windows
``Setup.exe`` and a Windows user can NEVER receive a macOS ``.dmg``
via the in-app updater.

## What this fixes

The selector in ``app.platform_compat.pick_release_asset`` was already
platform-aware since V14.2.0, but two ergonomic gaps remained:

1. The "no asset found" log line in ``check_for_updates`` read "release
   X has no .exe asset" — which on macOS sounded like a Windows-only
   failure even when the picker had correctly determined the release
   was missing a ``.dmg``. Updated to "release X has no installer
   asset for this platform".
2. There was no explicit regression coverage that asserted the picker
   refuses to fall back to the *other* platform's installer when only
   one is present (e.g. if the macOS workflow failed and the release
   only has a ``.exe``, a Mac user should see "no update available",
   not be offered a ``.exe`` they can't run).

## Routing guarantees, verified by tests

| Running on | Updater offers | Updater refuses |
|---|---|---|
| Windows | ``*Setup*.exe`` → ``*Installer*.exe`` → any ``.exe`` | Anything that isn't ``.exe`` (returns None) |
| macOS | ``.dmg`` → ``.pkg`` → ``.zip`` | Anything that isn't a Mac container (returns None) |
| Linux | ``.AppImage`` → ``.deb`` → ``.tar.gz`` | Mismatched OS containers (returns None) |

New ``_qa/v143_platform_asset_routing.py`` exercises:

- Both platforms with the actual V14.3.3 release shape (asset order randomised).
- Both platforms with corrupt releases (only the *other* OS's asset present).
- Adversarial filenames designed to confuse the matcher (``Veloxa-macOS-Setup.exe``, ``Veloxa-windows-Setup.dmg``, ``README.dmg``, ``CHANGELOG.exe``).
- Empty / None asset lists.
- A LIVE GitHub API call against the published ``v14.3.3`` release that confirms the picker's output URL ends in ``.exe`` for Windows and ``.dmg`` for macOS.

## Test totals

302 / 302 regression probes (7 new V14.3.4 routing probes) + 33 / 33 dispatch + 26 / 26 platform-routing + 15 / 15 audio-template preview + 99 / 99 e2e encode = **475 / 475 PASS**.

---

# Veloxa Video Editor — V14.3.3

**Hot-fix.** Audio Visuals now fill 100 % of the canvas.

## What was broken

Every audio-visual template had unused black space:

- **Spectrum Bars** — 55 % height + black bars top / bottom; only ~25 % horizontal coverage in short audio because the spectrogram scrolls.
- **Circular Spectrum** — small centred square ring on a wide black surround.
- **Waveform** — 60 % height waveform with black bands above / below.
- **Neon Audio Ring** — tiny centred ring + glow on a mostly-black background.
- **Podcast Layout** — 70 % dark hero with only a 30 % spectrum strip at the bottom.
- **Spotify Canvas Style** — flat dark canvas with a 10 %-tall bar at the foot.

The user shouldn't see flat black voids — they picked a visual, they expect a visual.

## Fix

Every template rewritten to fill every pixel of the output:

- **Spectrum Bars** — full-canvas `showspectrum` with `mode=combined`, `color=intensity`, `scale=lin`.
- **Circular Spectrum** — full-canvas `showspectrum` with `mode=combined`, `color=rainbow`, `scale=log` (the polar layout can't fill non-square canvases cleanly so the visual style was reinterpreted as a vivid rainbow spectrogram).
- **Waveform** — `showwaves` at full canvas dimensions.
- **Neon Audio Ring** — full-canvas fire-palette `mode=separate` spectrogram + a heavily-blurred copy blended in screen mode for the neon-glow feel.
- **Podcast Layout** — full-canvas spectrogram background with a centred waveform band overlaid; thin accent lines top / bottom of the band frame the overlay.
- **Spotify Canvas Style** — `showwaves` at full canvas height (was a 10 % strip) on a subtle dark gradient.

Also in `engine/ffmpeg.py::generate_audio_template_preview`: the preview generator now feeds **30 s of audio** instead of 5 s before grabbing the last frame, so spectrum-based templates that scroll left-to-right have time to fill the canvas before the preview JPG is captured.

15 / 15 audio-template preview tests + 295 / 295 regression probes + 99 / 99 e2e encode tests all pass. The Audio Visuals dropdown is wired to refresh the preview within 200 ms of each template switch so the user can flip through the 6 templates and watch them update live.

---

# Veloxa Video Editor — V14.3.2

**Hot-fix.** Audio Visuals templates now render in the preview pane.

## Fixed

Selecting an Audio Visuals template (Spectrum Bars, Waveform, Neon Audio Ring, Spotify Canvas Style, etc.) with an audio file in the queue would leave the preview pane stuck on a "Right-click ... Change Visual" message. The actual encode worked — the template ran at batch time — but the user couldn't see what the result would look like before pressing Start.

### Root cause

Two compounding issues:

1. **`_refresh_preview` bailed early on any audio row that had no user-supplied `visual_path`.** It didn't know the user had picked an audio template, which generates the visual from the audio itself. The placeholder message hid the real preview.
2. **No preview generator existed for audio templates.** `engine.generate_visual_preview` only handled image/video visuals. Even if the GUI had reached the preview step, the worker had no way to render a template frame.

### Fix

- **New `engine.generate_audio_template_preview(ffmpeg, audio_path, template_key, opts, out_path, time_s)`** in `engine/ffmpeg.py`. Builds the template's filter graph against the actual audio source, appends `[aout]anullsink` to absorb the audio tail (ffmpeg refuses unmapped filter outputs), feeds 5 s of audio, and writes the last frame to disk via `-update 1 -frames:v 150` so the spectrum / waveform / CQT buffers have time to fully develop before the frame is captured.
- **`PreviewWorker.run`** now branches on `opts["audio_template"]`: if a template is selected, route to the new generator. Falls back to `generate_visual_preview` for traditional image/video visuals.
- **`_refresh_preview`** no longer bails when only a template is set. The placeholder message now reads "Pick an Audio Visuals template, or right-click the queue item -> Change Visual."
- **Audio Visuals combo** is wired to `_schedule_preview` so switching between Waveform, Spectrum Bars, Neon Ring, etc. live-refreshes the pane within 200 ms.

15 new probes (`_qa/v143_audio_template_preview.py`) verify every registered template (`spectrum_bars`, `circular_spectrum`, `waveform`, `neon_ring`, `podcast_layout`, `spotify_canvas`) produces a valid JPEG. Negative cases (unknown key, empty key, `none` sentinel) all return False without crashing.

---

# Veloxa Video Editor — V14.3.1

**Hot-fix.** Per-row progress bar no longer stays at 0 % during short encodes.

## Fixed

Users reported that the first (and any short) encoding video would sit at 0 % the entire time, then jump straight to 100 % when the file finished. Reproduced and traced to two compounding issues:

1. **FFmpeg's progress emission was too coarse.** Without an explicit `-stats_period`, FFmpeg emits a progress block every 0.5 s of wall time. A 1-second transcode therefore only produces 2 blocks — the first after ~78 % of the encode had completed. The progress bar visibly stayed at 0 % until the very end.

2. **Python's text-mode pipe was buffering progress lines.** `subprocess.Popen(stdout=PIPE, text=True, bufsize=1)` wraps the pipe in an `io.TextIOWrapper`, and on Windows the underlying buffered reader holds ~8 KB of stdout before yielding the first line. For short encodes the buffer never filled mid-encode; lines only arrived when the pipe closed at process exit.

### Fix

`engine/batch.py::JobRunner._run_ffmpeg`:

- Inject `-stats_period 0.1` into every FFmpeg command alongside `-progress pipe:1`, so FFmpeg emits a fresh `out_time_us=` line every 100 ms.
- Switch `subprocess.Popen` to `bufsize=0` (no Python-side buffer) and read raw bytes via `iter(stdout.readline, b"")`, decoding per line. The reader returns the moment FFmpeg flushes its progress block.

### Result

Same 1-second transcode that previously emitted 3 progress events (first at 78 %) now emits 8 events evenly distributed from 24 % → 100 %. A 7-second transcode emits 56 events. The per-row bar visibly moves throughout the encode on both short and long files, on Windows and macOS.

---

# Veloxa Video Editor — V14.3.0

**Minor release.** Optional parallel CPU encoder slot + add-files-while-batch-runs.

## New: "Also use CPU encoder when GPU is busy"

Settings → Output → new checkbox **"Also use CPU encoder when GPU is busy (parallel slot)"** (default OFF). When enabled, the BatchManager opens *one extra* concurrent slot beyond your existing GPU-slot count and runs that slot through `libx264` or `libx265` (matched to the codec family you picked). Net effect: instead of N parallel GPU jobs, you get N GPU + 1 CPU jobs at the same time, with the CPU job's output written to the same queue with no extra wiring.

- **Live toggle.** The checkbox accepts changes at any time — including mid-batch. Turning it ON spawns a CPU job on the next dispatch tick (within seconds). Turning it OFF stops opening new CPU slots immediately, but the in-flight CPU job is allowed to finish (no way to safely re-nice a running FFmpeg).
- **Hard cap.** Total concurrent jobs are capped at **4** regardless of slider + CPU-slot math. Protects the machine from runaway counts on high-core systems.
- **Belt-and-braces safety** so the system can't hang:
    - **Process priority drop.** CPU FFmpeg processes start at `BELOW_NORMAL_PRIORITY_CLASS` on Windows (Popen creationflags) and `nice +5` on macOS / Linux (Popen preexec_fn). The interactive UI never starves.
    - **Thread cap.** CPU FFmpeg gets `-threads max(1, (cpu_count - 2) // 2)` so it can't saturate every core when a GPU job is also running.
    - **RAM watchdog.** Before opening a CPU slot, the BatchManager checks free system RAM via `psutil`. If less than 10% is free, the CPU slot is skipped this dispatch tick — the GPU jobs still run, the CPU slot just stays closed until RAM frees up. Fails open if `psutil` isn't installed.

## New: add files while a batch is rendering

The **Add Files** button is now ALWAYS enabled — even mid-batch. The Remove / Delete / Clear buttons stay locked while a batch is running (touching the active queue mid-render would break rotation indices).

When you add files during a running batch, they're appended to the end of the BatchManager's pending queue via the new `BatchManager.add_jobs()` API and picked up the moment a slot frees. The status bar shows e.g. *"Added 3 file(s) to running batch."*

## Files / APIs

New:
- `engine/system_resources.py` — `low_priority_popen_kwargs()`, `cpu_encoder_thread_count()`, `enough_ram_for_cpu_job()`, `force_cpu_encoder()`.
- `BatchManager.HARD_CAP_CONCURRENT = 4`
- `BatchManager.set_use_cpu_slot(enabled)` — live toggle.
- `BatchManager.add_jobs(new_jobs)` — append to the running queue.
- `BatchManager.effective_concurrency()` — computed limit (GPU slots + optional CPU slot, clamped to HARD_CAP).
- `JobRunner._cpu_threads_flag()` — emits `-threads N` only on CPU-slot jobs using libx264/libx265.

Modified:
- `JobRunner._run_ffmpeg` — wraps `subprocess.Popen` with low-priority creationflags/preexec_fn when `opts["_cpu_slot"]` is set.
- `main_window._add_files` — no longer blocked when the batch is running; tail items go through `_build_jobs_for_items` and `BatchManager.add_jobs()`.
- `main_window._set_queue_locked` — `add_btn` is left enabled at all times.
- `requirements.txt` — adds `psutil>=5.9` (used by the RAM watchdog; fails open if missing).

## How to try it

1. Update to V14.3.0 (Help → Check for Updates…).
2. Open Settings → Output → tick **"Also use CPU encoder when GPU is busy (parallel slot)"**.
3. Queue a few files, hit **Start Batch**. You'll see one extra concurrent job firing at lower priority. Open Task Manager / Activity Monitor — the FFmpeg using `libx264`/`libx265` is the CPU slot.
4. Mid-render, click **Add Files** — the new items append to the queue and run after current jobs.
5. Toggle the checkbox during the render — turning it OFF stops opening new CPU slots; the current one finishes.

---

# Veloxa Video Editor — V14.2.0

**Minor release.** First macOS build.

## New: macOS support

- **GitHub Actions workflow** (`.github/workflows/build_macos.yml`) builds a `.app` + `.dmg` on every `v*` tag push, using a free `macos-latest` runner. The `.dmg` is ad-hoc signed and attached to the matching GitHub release alongside the Windows `.exe` installer.
- **Ad-hoc signed**: macOS users will see *"app from unidentified developer"* on first launch. Right-click → Open bypasses Gatekeeper once and then it opens normally forever. (Full Developer-ID signing + notarisation requires an Apple Developer account — out of scope for V14.2.)
- **In-app updater is now platform-aware**: on macOS it picks the `.dmg` asset from the release page; on Windows it still picks `*Setup*.exe`. The download flow, transfer-rate read-out, cancel handling, and progress dialog are all identical across platforms.

## Source-level refactor (`app/platform_compat.py`)

New module centralising the Windows-only patches that had leaked into the rest of the app. Single source of truth for:

- `open_in_file_manager(path)` — `os.startfile` on Windows, `open` on macOS, `xdg-open` on Linux.
- `pick_release_asset(assets)` — `*Setup*.exe` on Windows, `*.dmg` on macOS, `*.AppImage` / `*.deb` / `*.tar.gz` on Linux.
- `launch_installer(path)` — Win runs `.exe` detached; Mac runs `open` to mount the DMG and show the drag-window in Finder.
- `find_bundled_ffmpeg()` — knows the `Veloxa.app/Contents/Resources/ffmpeg` layout in addition to the Windows `<exe_dir>/ffmpeg/` convention.

Existing Windows users are completely unaffected — the platform branches all resolve to the same paths they did before.

## How macOS users get it

1. Download `Veloxa-Video-Editor-V14.2.0-macOS.dmg` from the GitHub release.
2. Double-click to mount.
3. Drag **Veloxa Video Editor** to **Applications**.
4. First launch: right-click → Open (Gatekeeper warning, one-time bypass).
5. From V14.2.0 onward the in-app updater handles future versions automatically.

## How Windows users get it

Same as always — `Help → Check for Updates...` or wait for the startup auto-check.

---

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
