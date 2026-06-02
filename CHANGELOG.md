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
