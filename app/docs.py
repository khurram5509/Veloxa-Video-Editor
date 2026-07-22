"""HTML content for the README / Install / Help / License menu dialogs.

The version literal shown in the dialog titles + CLI examples is sourced
from ``app.updater.APP_VERSION`` so the docs never drift from the running
build. Historic version tags on individual bullet points (``(V12.3.1)``,
``(V14.6.0)``, ...) are the ship-version of that feature, not the current
version — those stay literal so the reader knows when each shipped.
"""
from __future__ import annotations

from .updater import APP_VERSION

# Convenience alias used across the HTML blocks below.
_V = f"V{APP_VERSION}"


README_HTML = f"""
<h1 style="color:#f58220; margin-bottom:4px;">Veloxa Video Editor {_V}</h1>
<p style="color:#aaa; margin-top:0;">Bulk video editor for Windows &amp; macOS. Part of the VeloxaLAB toolkit.</p>

<h2>What it does</h2>
<p>Trim, watermark, and convert videos and audio files to MP4. Designed for
fast unattended bulk work: queue many files, apply a single set of settings,
walk away. Settings live in named profiles; a session log records every job;
the queue survives app restarts and crashes.</p>

<h2>Features at a glance</h2>
<ul>
  <li><b>Profile shortcut numbers (V14.10.0)</b> — every profile carries a sticky number (shown as <code>3. MyProfile</code> in every dropdown). Select queue rows and type the number to assign that profile to all of them — multi-digit numbers work (type <code>1</code>&nbsp;<code>2</code> for profile 12; single digits apply instantly when no longer number could match, otherwise after a ~0.7 s pause). Reassign numbers via <i>Profile Manager → Set Number</i> (swaps with the current holder on conflict). Numbers survive renames and profile updates; duplicates and imports never steal an existing number.</li>
  <li><b>Add from Folder multi-format picker (V14.9.0)</b> — when the recursive scan finds more than one file extension in the chosen folder, a picker dialog lists each unique extension (checkbox per extension, all ticked by default). Only ticked extensions get imported. Optional second checkbox permanently deletes every non-chosen file in the folder tree — with an explicit second confirmation dialog showing the exact count + sample paths before anything is removed.</li>
  <li><b>Updater stall detection + Download in Browser (V14.8.0)</b> — the in-app installer download now has a 15 s per-read timeout and a 30 s zero-bytes inactivity detector, so it fails fast with a clear dialog instead of hanging forever behind an aggressive AV or CDN. The update-available dialog gained a fourth <i>Download in Browser</i> button that skips the in-app downloader entirely.</li>
  <li><b>Custom FFmpeg flags + first-launch tour (V14.8.0)</b> — an <b>Extra FFmpeg flags</b> field in the Output tab appends any ``shlex``-parsed arguments to every encode command. A three-step onboarding tour fires ~2 s after first launch (gated by <code>QSettings.onboarding_seen_v1</code>, replayable via Help menu).</li>
  <li><b>AV1 codec support (V14.7.0)</b> — four AV1 encoders auto-detected at runtime: <code>libsvtav1</code> (CPU), <code>av1_nvenc</code> (NVIDIA RTX 4000+), <code>av1_qsv</code> (Intel Arc / newer iGPUs), and <code>av1_amf</code> (AMD RDNA 3+). Priority-picker degrades gracefully when none is available.</li>
  <li><b>Add from Folder (V14.6.0)</b> — pick a folder and every supported media file inside (recursive) lands in the queue. Skips symlinks, respects the supported-extensions list.</li>
  <li><b>Batch resume + opt-in crash reporter (V14.5.0)</b> — an interrupted batch offers to resume from the exact row where it stopped on next launch. Opt-in crash reporter builds a pre-filled GitHub issue URL after an unhandled exception.</li>
  <li><b>CPU + GPU parallel encoder slot (V14.3.0)</b> — the BatchManager can now open a second slot that force-CPUs (libx264/libx265/libsvtav1) while the GPU slot keeps running its NVENC/QSV/AMF pipeline. Guarded by a per-machine thread cap, process-priority nudge, and a RAM watchdog that vetoes a second slot when memory is tight.</li>
  <li><b>macOS support (V14.2.0)</b> — full source-level parity: platform-aware paths, FFmpeg locator, DMG installer, GitHub Actions workflow that ad-hoc-signs the .app on every tag push.</li>
  <li><b>Single-instance + HiDPI (V14.1.0)</b> — a second double-click on the EXE hands off to the running instance instead of spawning a duplicate. HiDPI-aware layout, minimum window size guard.</li>
  <li><b>Queue tree widget + live preview + audio visual templates (V14.0.0)</b> — the queue is a multi-column QTreeWidget (name / codec / resolution / status / progress) with right-click actions. The preview pane runs a real <code>QMediaPlayer</code>+<code>QVideoWidget</code> for play/pause/scrub, with a Source→Output info overlay. Audio inputs can be encoded against one of 6 real-time FFmpeg audio-visual templates (spectrum bars, circular spectrum, waveform, neon ring, podcast layout, Spotify canvas).</li>
  <li><b>System / Light / Dark theme picker (V13.1.0)</b> — pick from the menu bar, choice persists across launches. <i>System</i> follows the current OS setting; Light and Dark are hand-designed with matching brand accent, focus rings, and disabled-state visibility.</li>
  <li><b>Auto-update via GitHub (V13.0)</b> — checks the configured GitHub repo's Releases on startup (opt-in, ON by default), surfaces new versions with release notes, and runs the in-place installer with one click. Manual <i>Check for Updates...</i> menu item always works regardless of the setting. macOS installs get the .dmg; Windows installs get the .exe — never mixed.</li>
  <li><b>Quality tier dropdowns (V12.3.1)</b> — Video Quality and Audio Quality each pick from Low / Medium / High / Best / Super Best. The dropdown resolves to a kbps target sized to the output resolution (same tier scales appropriately at 720p vs 4K). Default is <b>Best</b>.</li>
  <li><b>Image-visual pre-scale (V12.3.5)</b> — for audio + image-visual encodes, the image is scaled to target dimensions once before the encode instead of every frame. Eliminates a per-frame CPU filter bottleneck so NVENC / QSV / AMF can run at much higher utilisation.</li>
  <li><b>Bulk processing engine</b> — sequential or parallel (1-2 concurrent jobs), with one auto-retry on transient failures.</li>
  <li><b>Intro / Outro merge (V12.3)</b> — each profile can carry an optional intro and outro video. Any format works (auto re-encoded and scaled). User-controlled audio crossfade at the joins. With split-on-length: intro on Part 1, outro on the last part.</li>
  <li><b>Pause / Resume mid-batch (V12.2)</b> — hit ⏸ Pause and the BatchManager finishes the in-flight job, then waits. Hit ▶ Resume to continue. Cancel still nukes the whole batch.</li>
  <li><b>Per-row visual progress (V12.2)</b> — every queue row shows a slim status-coloured progress bar (orange while encoding, green when done, red on failure, grey on cancel), so a 50-file batch is scannable at a glance.</li>
  <li><b>Drag-reorder Audio Visuals (V12.2)</b> — the audio-visual rotation list now supports drag-drop reordering; the Move Up / Move Down buttons stay for keyboard users.</li>
  <li><b>Rebranded to Veloxa Video Editor (V12.1)</b> — same engine, same data, fresh name.</li>
  <li><b>Preview matches the row's profile (V12.1)</b> — selecting a queue row pinned to a different profile now updates the preview pane (watermarks, resolution, info bar) to reflect THAT profile, not the live form.</li>
  <li><b>Per-row profile assignment (V11.5)</b> — every queue item carries its own profile. A single batch can mix profiles: row 1 uses "Podcast-A", row 2 uses "YouTube-Short", row 3 uses "Archive". Each row picks its profile via the in-row combo, or right-click any selected rows &rarr; <i>Apply Profile to N item(s)</i> for bulk update.</li>
  <li><b>Delete from disk (V11.5)</b> — right-click any selected queue rows &rarr; <i>Delete from Disk...</i> to permanently delete the source files (with confirmation).</li>
  <li><b>Unicode button icons (V11.5)</b> — every button across the app is prefixed with a glyph (▶ ■ ＋ − ✕ 🗑 ⚙ 📂 💾 🔄 🎨 ▲ ▼ ↶ ↷ ⬇ ⬆) for at-a-glance recognition.</li>
  <li><b>Stale-preview fix (V11.4)</b> — first launch no longer briefly shows the previous session's last preview frame in the preview pane.</li>
  <li><b>Queue stats one-liner (V11.3)</b> — live counts above the queue: total / done / failed / pending / encoding.</li>
  <li><b>Profile audio visuals (V11.3)</b> — a profile can carry an ordered list of images and videos; when an audio input is encoded, visuals are assigned round-robin from the list. The rotation counter persists across sessions per profile.</li>
  <li><b>Trim-from-end fix (V11.2)</b> — fresh launches and minimal profiles no longer silently chop 2.4&nbsp;s off the output; <i>Trim from end</i> now defaults to 0&nbsp;s.</li>
  <li><b>Saved profile assets (V11.1)</b> — image and video watermarks referenced by a profile are copied into the app on Save, so the profile keeps working even if the originals get moved or deleted. Use <i>File &rarr; Manage Saved Data...</i> to inspect or wipe.</li>
  <li><b>Split on length (V11)</b> — cap each output at N minutes; oversized inputs auto-split into Part1, Part2, ...</li>
  <li><b>Watch folder mode</b> — point the app at a folder; new files land &rarr; auto-encode &rarr; move source to <code>done/</code>. True fire-and-forget.</li>
  <li><b>Output filename pattern</b> — flexible placeholders (<code>{{name}}</code>, <code>{{date}}</code>, <code>{{codec}}</code>, <code>{{n:03d}}</code> ...) instead of a fixed suffix.</li>
  <li><b>Total batch ETA</b> — estimated remaining time + projected finish clock-time, updates as jobs complete.</li>
  <li><b>Hardware decode</b> — main video decoded on the same GPU that encodes (CUDA / QSV / D3D11VA), ~2&times; throughput on 4K source.</li>
  <li><b>Audio fade-in / fade-out</b> — independently configurable, applied after speed change.</li>
  <li><b>CLI / headless mode</b> — drive the engine from cmd / PowerShell / Task Scheduler via <code>--cli</code>.</li>
  <li><b>Live preview</b> — frame-accurate seek with watermark composited; updates while you scrub.</li>
  <li><b>Source &rarr; Output info bar</b> — one-liner under the seek bar showing exactly what the next encode will produce.</li>
  <li><b>Visual trimming</b> — drag the orange handles on the seek bar; spinboxes for exact values.</li>
  <li><b>Image, video &amp; text watermarks</b> — all three optional and stackable; the video watermark loops automatically if shorter than the output.</li>
  <li><b>MP3 &rarr; MP4</b> — turn audio into video using either a still image OR a looping video as the visual.</li>
  <li><b>Codecs</b> — H.264 (AVC) and H.265 (HEVC, ~40% smaller files).</li>
  <li><b>GPU encoding</b> — NVIDIA NVENC, Intel QSV, AMD AMF (auto-detected, cached).</li>
  <li><b>Force stereo audio</b> — upmixes mono inputs by default.</li>
  <li><b>Audio loudness normalization</b> — single-pass EBU R128 (-16 LUFS) via the loudnorm filter.</li>
  <li><b>Speed change</b> — 0.1x to 10x; pitch-preserving audio (atempo) + frame-accurate video (setpts).</li>
  <li><b>Profile manager</b> — search, undo/redo, create / edit / rename / duplicate / delete, import &amp; export, "create from image" shortcut.</li>
  <li><b>Update-loaded-profile</b> — header button updates the currently-loaded profile in one click.</li>
  <li><b>Crash-safe queue resume</b> — auto-saves state on every change; restore prompt on next launch with interrupted-item count.</li>
  <li><b>Confirm-before-close</b> — closing the window mid-batch asks before tearing down.</li>
  <li><b>Keyboard shortcuts</b> — Ctrl+O / Ctrl+Enter / Ctrl+S / Esc / F1 / Ctrl+M and more.</li>
  <li><b>Session logging</b> — every job recorded to a file for unattended-run audit trails.</li>
</ul>

<h2>Architecture</h2>
<p>Modular: a pure <code>engine</code> package (FFmpeg I/O, encoders,
filters, batch orchestration) and an <code>app</code> package (theme,
widgets, dialogs, main window, persistence, CLI). Bundles FFmpeg + ffprobe
inside the EXE — no separate install needed. The same EXE runs the GUI
when double-clicked and the CLI when launched with <code>--cli</code>.</p>
"""


INSTALL_HTML = f"""
<h1 style="color:#f58220;">Installation Guide</h1>

<h2>Quick start — Windows</h2>
<p>Run <code>Veloxa-Video-Editor-{_V}-Setup.exe</code>. The installer places the app under
<code>C:\\Program Files\\Veloxa Video Editor\\</code>, creates Start Menu + Desktop shortcuts,
and registers an uninstaller. Since V14.8.1 the installer uses PyInstaller's
<code>--onedir</code> bundle layout, so launches are instant (no
<code>%TEMP%\\_MEI</code> extract-and-scan race with Windows Defender).</p>

<h2>Quick start — macOS</h2>
<p>Open <code>Veloxa-Video-Editor-{_V}-macOS.dmg</code> and drag <b>Veloxa Video Editor.app</b>
into <code>/Applications</code>. The .app is ad-hoc signed by GitHub Actions on every tag push.
On first launch macOS will show a Gatekeeper prompt — right-click the app &rarr; Open &rarr; Open
to authorize once, and it launches normally after that.</p>

<h2>Optional convenience (Windows)</h2>
<ul>
  <li>The installer already creates a Desktop shortcut (tick the box on the final page).</li>
  <li><b>Pin to Start / Taskbar:</b> right-click the Start Menu entry &rarr; Pin.</li>
</ul>

<h2>System requirements</h2>
<ul>
  <li>Windows 10/11 (64-bit) <b>or</b> macOS 12+ (Intel / Apple Silicon).</li>
  <li>~700 MB free disk space (the installer is ~270 MB on Windows / ~90 MB on macOS; installed footprint is larger because of the --onedir bundle layout on Windows).</li>
  <li>For GPU acceleration: NVIDIA GTX 600+ / RTX, Intel iGPU (Skylake+), or AMD GPU. Auto-detected on first launch and cached per-machine (the cache key includes a machine ID so it doesn't leak between installs).</li>
</ul>

<h2>Where state is stored</h2>
<ul>
  <li>Settings &amp; profiles: Windows Registry, <code>HKCU\\Software\\Veloxa-VD\\V10</code></li>
  <li>Encoder cache: <code>%APPDATA%\\Veloxa-VD\\encoder_cache.json</code></li>
  <li>Session logs: <code>%APPDATA%\\Veloxa-VD\\V10\\logs\\</code></li>
  <li>Queue state: <code>%APPDATA%\\Veloxa-VD\\V10\\queue_state.json</code></li>
</ul>

<h2>Uninstall</h2>
<p><b>Windows:</b> Settings &rarr; Apps &rarr; Veloxa Video Editor &rarr; Uninstall (or use
the Start Menu <i>Uninstall Veloxa Video Editor</i> entry the installer creates). To also
wipe your saved profiles + queue state, delete the registry path above and the
<code>%APPDATA%\\Veloxa-VD</code> folder afterward.</p>
<p><b>macOS:</b> drag <b>Veloxa Video Editor.app</b> from Applications to the Trash.
Saved settings live under <code>~/Library/Preferences/com.veloxa.videoeditor.plist</code>
and per-profile assets under <code>~/Library/Application Support/Veloxa-VD/</code>.</p>
"""


HELP_HTML = f"""
<h1 style="color:#f58220;">Help</h1>

<h2>Adding files to the queue</h2>
<p>Three ways:</p>
<ul>
  <li>Click <b>Add Files...</b> in the Queue area.</li>
  <li>Drag-and-drop files anywhere in the window.</li>
  <li>Drag-and-drop directly onto the Queue list.</li>
</ul>
<p><b>Supported video:</b> MP4, MOV, MKV, AVI, WebM, FLV, WMV, M4V, MPG, MPEG, TS, 3GP.<br>
<b>Supported audio:</b> MP3, WAV, M4A, FLAC, AAC, OGG, OPUS, WMA.</p>

<h2>Trimming</h2>
<p>Drag the orange bars on the seek bar to set trim start and end. The white
knob is the preview scrubber &mdash; click anywhere on the track to jump.
Spinboxes in the Trim tab give exact values; bar and spinboxes stay in sync.
The cut summary under the seek bar shows the final clip range and length.</p>

<h2>Live preview</h2>
<p>The preview pane refreshes 200 ms after the last setting change.
Scrubbing the seek bar updates the preview frame in real time, not only
on release. The <b>Source &rarr; Output</b> info bar under the seek bar
summarises exactly what will be encoded: source resolution and duration on
the left, output resolution / codec / encoder / speed / loudnorm / stereo
status on the right.</p>

<h2>Watermarks</h2>
<p>All three watermark types (image, video, text) are <b>optional</b> and
can be combined &mdash; layered in this order so a video watermark sits on
top of an image watermark, with text on top of both.</p>
<ul>
  <li><b>Image:</b> any PNG / JPG / BMP / WEBP. Position (presets + X/Y
      offsets + edge padding), size as % of video width, opacity 0&ndash;100%.
      The chosen image is automatically <b>copied into the app's watermark
      folder</b> (<code>%APPDATA%\\Veloxa-VD\\watermarks\\</code>) so the
      profile keeps working even if the original file is moved or deleted.
      Identical images dedupe by content hash &mdash; picking the same
      image twice doesn't make two copies.</li>
  <li><b>Video:</b> any video file. Same position / size / opacity controls
      as image. If the watermark video is shorter than the main output it
      <b>loops automatically</b> via FFmpeg's <code>-stream_loop -1</code>.
      Useful for animated logos, looping countdowns, lower-thirds.</li>
  <li><b>Text:</b> any string, font size, color (picker), position. A drop
      shadow is applied automatically for legibility.</li>
</ul>

<h2>MP3 &rarr; MP4 conversion</h2>
<p>When you add an audio file, a two-button prompt asks for the visual:</p>
<ul>
  <li><b>Image</b> &mdash; .png, .jpg, .bmp, .webp. Shown as a still throughout.</li>
  <li><b>Video</b> &mdash; .mp4, .mov, etc. Looped to fill the audio length.
      The visual video's own audio is ignored.</li>
</ul>
<p>Right-click any audio queue row &rarr; <b>Change Visual...</b> to swap.</p>

<h2>Output settings</h2>
<ul>
  <li><b>Codec:</b> H.264 (universal) or H.265 / HEVC (~40% smaller files).</li>
  <li><b>Encoder:</b> <code>(auto)</code> picks the best available, or pick one explicitly.</li>
  <li><b>Video bitrate (V12.3):</b> kbps target for the video stream. <code>0</code> means "match source" — the encoder falls back to its CRF / CQP quality mode (visually transparent, variable bitrate). Any non-zero value switches the encoder into native VBR mode at the requested bitrate.</li>
  <li><b>Audio bitrate (V12.3):</b> kbps target for the AAC audio stream. Default <code>192</code>. Clamped to [32, 512].</li>
  <li><b>Resolution:</b> Match Source / 720p / 1080p / 1440p / 4K.</li>
  <li><b>Intro / Outro merge (V12.3):</b> per-profile optional video files concatenated before and after the main encode. Forgiving — any format works (auto re-encoded to match output resolution, fps and audio layout). Silent intros/outros are handled automatically. Audio join behaviour is controlled by <b>Merge audio fade (s)</b>: <code>0</code> = hard cut, &gt;0 = <code>acrossfade</code> at each join. With split-on-length: intro is prepended only to Part 1, outro only to the final part. Intro/outro files are stored alongside watermarks under <code>%APPDATA%\\Veloxa-VD\\profile_assets\\</code>.</li>
  <li><b>Parallel encoding:</b> 1 or 2 simultaneous jobs.</li>
  <li><b>Force stereo audio:</b> on by default; upmixes mono.</li>
  <li><b>Normalize audio loudness:</b> EBU R128 single-pass to -16 LUFS / -1.5 dBTP / LRA 11. Streaming &amp; podcast standard.</li>
  <li><b>Speed:</b> 0.1x &ndash; 10x. Pitch-preserving for audio (chained <code>atempo</code>); frame-accurate for video (<code>setpts</code>).</li>
  <li><b>Filename pattern:</b> placeholders like <code>{{name}}</code>, <code>{{date}}</code>, <code>{{codec}}</code>, <code>{{n:03d}}</code>. Default <code>{{name}}_edited</code>.</li>
</ul>

<h2>Headless CLI mode</h2>
<p>Run the executable from cmd / PowerShell with <code>--cli</code> to drive the
engine without the GUI &mdash; ideal for Task Scheduler, build pipelines, or remote use.</p>
<pre>Veloxa-Video-Editor-{_V}.exe --cli --list-profiles
Veloxa-Video-Editor-{_V}.exe --cli --profile youtube --input "C:/videos/foo.mp4"
Veloxa-Video-Editor-{_V}.exe --cli --profile yt --input "C:/videos/" --output-dir "C:/encoded/" --parallel 2
Veloxa-Video-Editor-{_V}.exe --cli --input music.mp3 --visual cover.jpg</pre>
<p>Supports a folder as <code>--input</code> (recursive scan), <code>--output-dir</code>,
<code>--parallel</code>, <code>--visual</code> for audio jobs, and <code>--no-overwrite</code>.
Use <code>--show-config</code> to dump the resolved engine options as JSON, or
<code>--help</code> for full usage.</p>

<h2>Auto-retry</h2>
<p>If a job fails for any reason other than user-cancellation, the engine
automatically retries it <b>once</b>. Common transient failures (file briefly
locked, GPU driver glitch, disk hiccup) recover on the second attempt without
manual intervention &mdash; useful for long unattended runs.</p>

<h2>Auto-update (V13.0, hardened in V14.0.1 &amp; V14.8.0)</h2>
<p>On launch, Veloxa polls the configured GitHub Releases endpoint for a
newer version. The check is <b>opt-in and ON by default</b>; you can disable it
from the "Update available" dialog (look for the
<i>Check for updates on startup</i> tickbox). The check is silent if no update
is found, fails silently if the API is unreachable, and never blocks the UI.
Windows installs are offered the <code>.exe</code>; macOS installs are offered
the <code>.dmg</code> &mdash; never mixed.</p>
<p>When a newer version is found, a dialog shows:</p>
<ul>
  <li><b>Current</b> and <b>available</b> version, with release-notes preview.</li>
  <li><b>Download &amp; Install</b> &mdash; the download runs on a background
      QThread (V14.0.1) with a 15 s per-read socket timeout and a 30 s
      zero-bytes inactivity detector (V14.8.0), so a stalled connection
      surfaces a clear error dialog within 30 s instead of hanging forever.
      When the transfer finishes Veloxa quits and launches the installer.
      The installer keeps the same <code>AppId</code> as previous versions,
      so settings, profiles, and queue state survive the upgrade.</li>
  <li><b>Download in Browser (V14.8.0)</b> &mdash; skips the in-app downloader
      entirely and opens the installer link so your browser handles the
      transfer with its own resume/retry behaviour. Recommended fallback if
      an aggressive AV or corporate proxy keeps stalling the in-app download.</li>
  <li><b>Remind Me Later</b> &mdash; re-prompted next launch.</li>
  <li><b>Skip This Version</b> &mdash; no auto-prompt for this exact
      version; future versions still prompt. The <i>Check for Updates...</i>
      menu item still works on demand.</li>
</ul>
<p>The manual "You're up to date" dialog (V14.8.0) now shows the current
version + a clickable Release Page link, handy when you want to reinstall
the same version or look at previous release notes.</p>

<h2>Add from Folder (V14.6.0, multi-format picker V14.9.0)</h2>
<p>Click <b>Add from Folder</b> in the Queue area and pick a folder — every supported
media file inside gets added to the queue (recursive, symlinks skipped).</p>
<p>Since V14.9.0, if the folder holds more than one file extension a picker dialog
lists each unique extension found with a checkbox (all ticked by default). Only ticked
extensions get imported. Case-insensitive matching (<code>.mp4</code> also matches <code>.MP4</code>).</p>
<p>Underneath is a second, <b>unticked</b>-by-default checkbox: <i>"After import, PERMANENTLY
DELETE every other file in the folder."</i> Tick it and hit OK to get an explicit second
confirmation dialog with the exact count + a sample of up to 5 doomed paths + a red
<i>Delete N file(s) permanently</i> button (default focus is Cancel). Only after clicking
the red button does the sweep run. Deletion is permanent (<code>os.remove()</code>, not
Recycle Bin) and nuclear-scope: everything that isn't a ticked extension goes, including
<code>.srt</code>, <code>.jpg</code>, <code>.docx</code>, camera <code>.thm</code> sidecars.
Per-file failures are isolated so one locked file doesn't kill the sweep.</p>

<h2>Profiles</h2>
<p>A profile is a snapshot of every setting in the Trim, Watermark, and
Output tabs. Header actions:</p>
<ul>
  <li><b>Profile dropdown</b> — load a saved profile.</li>
  <li><b>Save As...</b> &mdash; <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> &mdash; save the current settings under a new name.</li>
  <li><b>Update Profile</b> &mdash; <kbd>Ctrl</kbd>+<kbd>S</kbd> when a profile is loaded &mdash;
      overwrite the loaded profile with the current settings (the streamlined edit-and-save flow).</li>
  <li><b>Manage...</b> &mdash; <kbd>Ctrl</kbd>+<kbd>M</kbd> &mdash; opens the full Profile Manager.</li>
  <li><b>Delete</b> &mdash; remove the loaded profile.</li>
</ul>
<p>The <b>Profile Manager</b> dialog has:</p>
<ul>
  <li><b>Search box</b> &mdash; <kbd>Ctrl</kbd>+<kbd>F</kbd> &mdash; case-insensitive substring filter.</li>
  <li><b>List + details panel</b> &mdash; selecting a profile shows its codec / encoder / quality / resolution / trim / watermark / stereo / speed / loudness settings.</li>
  <li><b>New from Current</b>, <b>Edit Selected</b>, <b>Rename</b>, <b>Set Number</b>, <b>Duplicate</b>, <b>Delete</b>.</li>
  <li><b>Undo / Redo</b> &mdash; <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Y</kbd> &mdash; reverse any profile mutation. 50-step history.</li>
  <li><b>Import / Export</b> &mdash; share profiles between machines as <code>.vvprof</code> JSON files. Export Selected for a single profile, Export All for a bundle.</li>
  <li><b>Quick: create profile from a watermark image</b> &mdash; pick an image, name the profile, done.</li>
  <li><b>Load Selected</b> &mdash; apply the chosen profile and close the dialog.</li>
</ul>
<p><b>Edit workflow:</b> click <b>Edit Selected</b> in the manager &rarr; the
profile loads into the main window and the manager closes &rarr; tweak any
settings &rarr; click <b>Update Profile</b> in the header (or <kbd>Ctrl</kbd>+<kbd>S</kbd>) to save changes back.</p>

<h3>Profile shortcut numbers (V14.10.0)</h3>
<p>Every profile has a sticky <b>shortcut number</b>, shown as a prefix in every
profile dropdown (<code>3. MyProfile</code>). To bulk-assign a profile:
select one or more queue rows and <b>type the number</b> while the queue has
focus. Single digits apply instantly when no longer number could follow;
otherwise the app waits ~0.7&nbsp;s for a second digit (so profile 12 is
typed as <kbd>1</kbd>&nbsp;<kbd>2</kbd>). Numbers above 10 are fully
supported. Reassign a number with <b>Set Number</b> in the Profile Manager
&mdash; if the number is taken, the two profiles swap. Numbers survive
renames and updates; duplicates and imports get fresh numbers instead of
stealing existing ones.</p>

<h2>Queue management</h2>
<ul>
  <li><b>Reorder:</b> drag rows up or down (disabled while a batch is running).</li>
  <li><b>Right-click a row:</b> Open Source Folder, Open Output Folder, Change Visual
      (audio only), Apply Profile, Remove, Delete from Disk.</li>
  <li><b>Assign by number:</b> select rows and type a profile's shortcut
      number (see <i>Profile shortcut numbers</i> above).</li>
  <li><b>Resume:</b> if the app was closed mid-batch, on next launch you're asked
      whether to restore the previous queue.</li>
  <li><b>Pause / Resume mid-batch (V12.2):</b> click <b>⏸ Pause</b> in the bottom
      bar to stop launching new jobs — anything currently encoding finishes
      naturally. Click <b>▶ Resume</b> to continue. <b>■ Cancel</b> always
      kills the whole batch (and clears any pause state).</li>
  <li><b>Per-row progress (V12.2):</b> each queue row shows a slim status-coloured
      bar — orange while encoding, green when done, red on failure, grey on cancel.</li>
</ul>

<h2>Audio Visuals tab</h2>
<p>For audio inputs, the active profile can carry an ordered list of images and
videos that are assigned round-robin (audio[0]&rarr;visual[0], audio[1]&rarr;visual[1],
&hellip;, wrapping). The rotation counter is per-profile and persists across
sessions.</p>
<ul>
  <li><b>Drag-reorder (V12.2):</b> drag rows in the visuals list to rearrange the
      cycle. Multi-select with Shift-click or Ctrl-click. Move Up / Move Down
      buttons remain available for keyboard users.</li>
  <li><b>Reset rotation</b> sends the next audio input back to visual #1.</li>
</ul>

<h2>GPU encoding</h2>
<p>On first launch the app probes which GPU encoders work and caches the result.
The Output tab shows what was detected. Set Encoder to <code>(auto)</code> for
NVIDIA &rarr; AMD &rarr; Intel &rarr; CPU priority.</p>

<h2>Keyboard shortcuts</h2>
<table cellspacing="4">
  <tr><td><kbd>Ctrl</kbd>+<kbd>O</kbd></td><td>Add files to the queue</td></tr>
  <tr><td><kbd>Delete</kbd></td><td>Remove selected queue rows (when queue is focused)</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>Enter</kbd></td><td>Start the batch</td></tr>
  <tr><td><kbd>Esc</kbd></td><td>Cancel the running batch</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>S</kbd></td><td>Update the loaded profile (or Save As if none loaded)</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd></td><td>Save current settings as a new profile</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>M</kbd></td><td>Open the Profile Manager</td></tr>
  <tr><td><kbd>F1</kbd></td><td>This help dialog</td></tr>
</table>
<p>Inside the Profile Manager:</p>
<table cellspacing="4">
  <tr><td><kbd>Ctrl</kbd>+<kbd>F</kbd></td><td>Focus the search box</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Y</kbd></td><td>Undo / Redo last profile change</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>N</kbd></td><td>New profile from current settings</td></tr>
  <tr><td><kbd>F2</kbd></td><td>Rename selected</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>D</kbd></td><td>Duplicate selected</td></tr>
  <tr><td><kbd>Delete</kbd></td><td>Delete selected (when list focused)</td></tr>
  <tr><td><kbd>Ctrl</kbd>+<kbd>I</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd></td><td>Import / Export selected</td></tr>
</table>

<h2>Confirm-before-close</h2>
<p>If a batch is in flight when you close the window, the app asks before
tearing down: <i>"A batch is currently encoding. Cancel it and close?"</i>
The default answer is <b>No</b>, so an accidental close (e.g. fat-fingered
<kbd>Alt</kbd>+<kbd>F4</kbd>) won't kill long-running work.</p>

<h2>Crash-safe queue resume</h2>
<p>The queue auto-saves to disk on every meaningful change &mdash; add,
remove, reorder, status update, retry. If the app is closed unexpectedly
mid-batch (crash, power loss, force-kill, OS reboot), launching again
offers to restore the queue, with a notice about how many items were
interrupted mid-encode and will be re-attempted. Items already marked
<i>done</i> are <b>skipped</b> on resume so a 100-file run that died at
file 60 picks up at 61.</p>

<h2>Logging</h2>
<p>Every session writes a log file to
<code>%APPDATA%\\Veloxa-VD\\V10\\logs\\session-YYYYMMDD-HHMMSS.log</code> with
each job's start, end, duration, and any errors &mdash; useful for unattended
overnight runs.</p>
"""


LICENSE_HTML = """
<h1 style="color:#f58220;">License</h1>

<p>Copyright &copy; 2026 Veloxa Video Editor. All rights reserved.</p>
<p>This software is provided <b>"as is"</b>, without warranty of any kind,
express or implied.</p>

<h2>Bundled third-party software</h2>
<ul>
  <li><b>FFmpeg</b> &mdash; multimedia framework. Bundled binaries from the
      gyan.dev "essentials" build
      (<a href="https://www.gyan.dev/ffmpeg/builds/">https://www.gyan.dev/ffmpeg/builds/</a>).
      FFmpeg is licensed under the LGPL v2.1+ / GPL v2+. See
      <a href="https://ffmpeg.org/legal.html">https://ffmpeg.org/legal.html</a>.<br>
      Source code is available at <a href="https://ffmpeg.org">https://ffmpeg.org</a>.</li>
  <li><b>Python</b> &mdash; Python Software Foundation License.</li>
  <li><b>PyQt6</b> &mdash; GPL v3 (or commercial license).</li>
  <li><b>Pillow</b> (build-time only) &mdash; HPND License.</li>
</ul>

<h2>FFmpeg notice</h2>
<p>This software uses libraries from the FFmpeg project under the LGPL/GPL.
Source code for FFmpeg is freely available from
<a href="https://ffmpeg.org">https://ffmpeg.org</a>.</p>
<p>The bundled FFmpeg build includes GPL components (e.g. libx264, libx265).
When redistributing this application, ensure you comply with the GPL terms.</p>

<h2>Disclaimer</h2>
<p>The user is responsible for ensuring that any media processed with this
software is owned by them or used with permission. The authors take no
responsibility for misuse, including copyright infringement.</p>
"""
