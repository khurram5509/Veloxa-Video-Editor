"""Main application window. Composes engine + UI for the Veloxa Video Editor app.

The window title / About dialog / update-check strings all interpolate
``app.updater.APP_VERSION`` so the running version is never hardcoded here.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QIcon, QKeySequence, QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QProgressDialog, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
)

from engine import (
    BatchManager, find_ffmpeg,
    cached_probe_duration, cached_probe_resolution,
    generate_preview, generate_visual_preview,
    generate_audio_template_preview,
    detect_available_encoders, ENCODER_LABELS, ENCODER_FOR_CODEC,
    AUTO_PRIORITY_H264, AUTO_PRIORITY_HEVC, AUTO_PRIORITY_AV1, SPEED_TIERS,
    CODEC_H264, CODEC_HEVC, CODEC_AV1, CPU_ENCODERS,
    # V12.3.1: quality-tier dropdowns replace raw bitrate spinboxes.
    VIDEO_QUALITY_TIERS, AUDIO_QUALITY_TIERS,
    VIDEO_QUALITY_DEFAULT, AUDIO_QUALITY_DEFAULT,
    resolve_video_bitrate_kbps, resolve_audio_bitrate_kbps,
    kbps_to_video_quality_tier, kbps_to_audio_quality_tier,
)
# V13.0: GitHub-Releases-driven auto-update.
from .updater import (
    APP_VERSION as VELOXA_APP_VERSION,
    GITHUB_REPO as VELOXA_GITHUB_REPO,
    UpdateChecker, UpdateInfo, DownloadWorker,
    launch_installer_and_quit,
)
# V13.1+: System / Light / Dark / OLED Dark theme switcher.
from .theme import (
    apply_theme, resolve_theme_mode,
    THEME_SYSTEM, THEME_LIGHT, THEME_DARK, THEME_OLED, THEME_MODES,
)


class PreviewWorker(QThread):
    """Generate one preview frame off the main thread.

    Each call carries a `seq` number; `MainWindow` keeps the latest seq it
    requested so it can ignore late-arriving results from superseded workers.
    """

    finished_with_path = pyqtSignal(str, bool, int)  # out_path, ok, seq

    def __init__(self, *, kind, ffmpeg, ffprobe, src, visual_path, visual_kind,
                 visual_duration, opts, out_path, time_s, src_w, src_h, seq):
        super().__init__()
        self.kind = kind
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.src = src
        self.visual_path = visual_path
        self.visual_kind = visual_kind
        self.visual_duration = visual_duration
        self.opts = opts
        self.out_path = out_path
        self.time_s = time_s
        self.src_w = src_w
        self.src_h = src_h
        self.seq = seq

    def run(self):
        try:
            if self.kind == "audio":
                # V14.3.2: when an audio-visual template is selected,
                # the visual is synthesised from the audio itself —
                # no user-supplied visual is involved. Route to the
                # template-aware preview generator so the pane shows
                # what the encode will actually produce.
                template_key = (self.opts.get("audio_template") or "").strip()
                if template_key and template_key != "none":
                    ok = generate_audio_template_preview(
                        self.ffmpeg, self.src, template_key, self.opts,
                        self.out_path, time_s=self.time_s)
                else:
                    ok = generate_visual_preview(
                        self.ffmpeg, self.visual_path, self.visual_kind,
                        self.visual_duration, self.opts, self.out_path,
                        time_s=self.time_s)
            else:
                ok = generate_preview(
                    self.ffmpeg, self.src, self.opts, self.out_path,
                    self.src_w, self.src_h, time_s=self.time_s)
        except Exception:
            ok = False
        self.finished_with_path.emit(self.out_path, ok, self.seq)

from . import widgets as widgets_mod
from .widgets import TrimSeekBar, DropList, QueueItemData
from .dialogs import (
    ProfileManagerDialog, WatchFolderDialog, ManageSavedDataDialog,
    show_info_dialog, NO_PROFILE, mirror_tooltips_to_accessibility,
)
from .watch_folder import FolderWatcher
from .docs import README_HTML, INSTALL_HTML, HELP_HTML, LICENSE_HTML
from .persistence import (
    save_queue_state, load_queue_state, clear_queue_state, log_dir,
    import_watermark_image,
)
from .profile_assets import (
    copy_assets_into_profile, delete_profile_assets,
)
from .theme import fmt_time, fmt_eta


log = logging.getLogger("veloxa.ui")


# ============================================================== Constants

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv",
              ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
ALL_INPUT_EXTS = VIDEO_EXTS | AUDIO_EXTS

# Make DropList aware of the accepted extensions.
widgets_mod.ALL_INPUT_EXTS = ALL_INPUT_EXTS

POSITION_PRESETS = ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right",
                    "Center"]

RESOLUTIONS = {
    "Match Source": None,
    "720p (1280x720)": (1280, 720),
    "1080p (1920x1080)": (1920, 1080),
    "1440p (2560x1440)": (2560, 1440),
    "4K (3840x2160)": (3840, 2160),
}

CODEC_LABELS = {
    CODEC_H264: "H.264 (AVC)",
    CODEC_HEVC: "H.265 (HEVC)",
    # V14.7.0: AV1 — ~30% smaller files at the same visual quality vs
    # H.264, but encode speed depends entirely on hardware: AV1 NVENC
    # (RTX 40-series+), AV1 QSV (Arc / 12th-gen+), AV1 AMF (RX 7000+),
    # or libsvtav1 on CPU (fast but not real-time on 1080p+). The
    # encoder dropdown only shows the variants that probed working.
    CODEC_AV1:  "AV1",
}
AUTO_ENCODER = "(auto)"


class ProfileCombo(QComboBox):
    """V14.10.0: combo that DISPLAYS profiles as ``N. Name`` (their
    sticky shortcut number) while keeping raw-name semantics for the
    Python API: ``currentText()`` and ``findText()`` operate on the raw
    profile name stored in ``UserRole``, so the many existing call
    sites that read/select by name keep working unchanged. Only
    ``currentTextChanged`` handlers see the display label (Qt emits the
    visible text) and must parse it via
    ``MainWindow._profile_name_from_label``."""

    def currentText(self) -> str:
        d = self.currentData(Qt.ItemDataRole.UserRole)
        return d if isinstance(d, str) else super().currentText()

    def findText(self, text, *args, **kwargs) -> int:
        for i in range(self.count()):
            raw = self.itemData(i, Qt.ItemDataRole.UserRole)
            if (raw if isinstance(raw, str) else self.itemText(i)) == text:
                return i
        return super().findText(text, *args, **kwargs)


# ============================================================== MainWindow

class MainWindow(QMainWindow):
    def __init__(self, app_icon: QIcon, log_file_path: Path):
        super().__init__()
        self.app_icon = app_icon
        self.log_file_path = log_file_path
        self.setWindowIcon(app_icon)
        self.setWindowTitle(f"Veloxa Video Editor V{VELOXA_APP_VERSION}")
        # V14.1: 1024x680 is the smallest sensible footprint where all
        # tabs are usable on a 1280x720 screen at 100% scaling. The
        # 1320x960 default still applies for fresh launches but the
        # window can no longer be dragged down below 1024x680 — the
        # bottom Start/Pause/Cancel bar was being clipped at smaller
        # sizes. saveGeometry/restoreGeometry then takes over on
        # subsequent launches (loaded in _load_settings).
        self.setMinimumSize(QSize(1024, 680))
        self.resize(1320, 960)
        self.setAcceptDrops(True)

        self.settings = QSettings("Veloxa-VD", "V10")
        self.ffmpeg, self.ffprobe = find_ffmpeg()
        self.batch = None

        # Rotating preview path so caches can never serve stale frames.
        self._preview_seq = 0
        self.preview_path = str(
            Path(tempfile.gettempdir()) / "veloxa_v10_preview_0.jpg")
        # V11.5 fix: a previous session's preview JPG could still be sitting
        # at any of the rotating slots. resizeEvent() fires at startup and
        # calls _render_preview_from_disk(), which would happily display
        # last session's leftover frame. Wipe all four slots up-front so
        # the disk has nothing to serve, and gate the renderer on a
        # "have we rendered anything *this* session" flag.
        for _i in range(4):
            _stale = (Path(tempfile.gettempdir())
                      / f"veloxa_v10_preview_{_i}.jpg")
            try:
                if _stale.exists():
                    _stale.unlink()
            except OSError:
                pass
        self._has_preview_this_session = False
        # PreviewWorker bookkeeping: previews run async on a worker thread;
        # only the latest seq's result is rendered, late results discarded.
        self._latest_preview_seq = 0
        self._preview_workers = []
        # Throttle UI label refreshes during high-frequency progress bursts.
        self._last_label_update = {}    # idx -> time.monotonic()
        self._last_overall_update = 0.0

        self.profiles = {}
        self.video_duration = 0.0
        self.seek_time = 0.0
        self._suppress_change = False
        self._text_color = "#ffffff"
        self._queue_locked = False
        # Total-batch ETA tracking: monotonic start time + count of finished
        # jobs (success or fail, but not retrying). avg_per_job * remaining
        # gives the estimate.
        self._batch_t_start = 0.0
        self._batch_completed = 0
        self._batch_total = 0
        # Per-row split-completion tally + runner-idx -> file_list-row map
        # (both populated when split-on-length is active).
        self._row_completed = {}
        self._runner_to_row = {}
        # Watch-folder daemon state.
        self._watcher = None
        self._watch_done_subfolder = "done"
        self._watch_buffer = []   # files seen but not yet queued
        self._watch_processed = 0  # for the user-facing counter

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        # 200ms feels noticeably more responsive when scrubbing the seek bar.
        self.preview_timer.setInterval(200)
        self.preview_timer.timeout.connect(self._refresh_preview)
        # Cache for source dimensions / codec info so the preview info label
        # doesn't re-probe on every paint.
        self._src_w = 0
        self._src_h = 0

        self.available_encoders = detect_available_encoders(self.ffmpeg)
        log.info("Detected encoders: %s", self.available_encoders)

        self._load_profiles()
        self._build_menu_bar()
        self._build_ui()
        self._wire_change_signals()
        self._install_shortcuts()
        self._build_tray()
        self._load_settings()
        self._refresh_profile_combo()
        self._update_trim_info()
        self._refresh_encoder_combo()
        self._update_profile_button_state()
        self._update_preview_info()
        self._maybe_restore_queue()

        if not self.ffmpeg:
            QMessageBox.warning(
                self, "FFmpeg Not Found",
                "FFmpeg was not found.\n\n"
                "Place ffmpeg.exe and ffprobe.exe in the 'ffmpeg' folder next "
                "to the app, or install FFmpeg and add it to your PATH.")

        # V14.4.1: surface the detected GPU(s) in the status bar so the
        # user can SEE what hardware acceleration is active on this PC
        # without digging through Settings → Output. The detection runs
        # at startup against this physical machine — never baked into
        # the build — so the message is always machine-specific.
        try:
            self.status_lbl.setText(self._describe_gpu_status())
        except Exception:
            pass

        # V13.0: GitHub-Releases auto-update. ``auto_update_check`` is
        # ON by default; the user can disable from the "Update available"
        # dialog. The check runs on a QThread so a slow / unreachable
        # API never blocks the window from showing.
        self._update_checker = None
        self._update_temp_path = None
        self._update_dl_worker = None
        QTimer.singleShot(1500, self._maybe_check_for_updates_on_startup)
        # V14.5.0: opt-in crash reporter. The excepthook in main.py
        # writes a ``crash_*.txt`` to the log dir on any unhandled
        # Python exception. On the next successful launch this scans
        # for unactioned crash files and (if the user has opted in)
        # offers to send them as pre-filled GitHub Issues. Scheduled
        # 3 s in so it doesn't pile on top of the auto-update modal
        # if there's also a pending update.
        QTimer.singleShot(3000, self._maybe_prompt_pending_crashes)
        # V14.8.0: first-launch onboarding tour. Pops 3 message boxes
        # over ~10 seconds highlighting Profiles, Audio Visuals, and
        # the GPU status line — the three features users most often
        # don't discover on their own. Gated on QSettings so it only
        # fires once per install; can be re-run via Help → Show
        # Onboarding Tour.
        QTimer.singleShot(2200, self._maybe_show_onboarding_tour)

        # Tooltip audit: tooltips only show on mouse hover, so assistive
        # technology (screen readers) never sees them. Mirror every
        # tooltip into the widget's accessibleDescription, which IS
        # announced on keyboard focus. One pass at startup covers all
        # statically-built widgets; widgets whose tooltip changes at
        # runtime (e.g. the Pause/Resume button) keep their initial
        # description, which stays accurate as a purpose summary.
        mirror_tooltips_to_accessibility(self)

    # ============================================================== UI build

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_queue(), 0)
        root.addWidget(self._build_middle(), 1)
        root.addWidget(self._build_bottom())

    def _build_header(self) -> QWidget:
        wrap = QFrame()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(2, 0, 2, 0)
        title = QLabel("Veloxa Video Editor")
        title.setProperty("role", "title")
        version = QLabel(f"V{VELOXA_APP_VERSION}")
        version.setProperty("role", "subtitle")
        h.addWidget(title)
        h.addWidget(version)
        h.addStretch()

        h.addWidget(QLabel("Profile:"))
        self.profile_combo = ProfileCombo()
        self.profile_combo.setToolTip(
            "Load a saved settings profile. Selecting one applies its "
            "Trim, Watermark, Audio Visuals, and Output settings to the "
            "whole window. The number before each name is its sticky "
            "shortcut: select queue rows and type that number to assign "
            "the profile to them.")
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        h.addWidget(self.profile_combo)
        save_btn = QPushButton("💾 Save As...")
        save_btn.setToolTip("Save current settings as a new profile (Ctrl+Shift+S)")
        save_btn.clicked.connect(self._save_as_profile)
        self.update_profile_btn = QPushButton("🔄 Update Profile")
        self.update_profile_btn.setObjectName("primary")
        self.update_profile_btn.setToolTip(
            "Save current main-window settings to the loaded profile, "
            "overwriting its previous contents (Ctrl+S). Disabled when no "
            "profile is loaded.")
        self.update_profile_btn.setEnabled(False)
        self.update_profile_btn.clicked.connect(self._update_current_profile)
        manage_btn = QPushButton("⚙ Manage...")
        manage_btn.setToolTip("Open the Profile Manager (Ctrl+M)")
        manage_btn.clicked.connect(self._open_profile_manager)
        del_btn = QPushButton("🗑 Delete")
        del_btn.setObjectName("danger")
        del_btn.setToolTip("Delete the currently loaded profile")
        del_btn.clicked.connect(self._delete_profile)
        h.addWidget(save_btn)
        h.addWidget(self.update_profile_btn)
        h.addWidget(manage_btn)
        h.addWidget(del_btn)
        return wrap

    def _build_queue(self) -> QWidget:
        box = QGroupBox("Queue (videos and audio)")
        v = QVBoxLayout(box)
        # V11.5: live one-liner with per-status counts.
        self.queue_stats_lbl = QLabel("0 files")
        self.queue_stats_lbl.setProperty("role", "muted")
        self.queue_stats_lbl.setToolTip(
            "Live queue stats: total / done / failed / pending / encoding.")
        v.addWidget(self.queue_stats_lbl)
        self.file_list = DropList()
        # UI-fix: a per-list objectName lets us target this QListWidget
        # (and ONLY this one) with tighter row padding, so the
        # selection-orange band sits flush around the row widget rather
        # than the chunky 6-8px Default.isl theme padding.
        self.file_list.setObjectName("queue_list")
        self.file_list.setStyleSheet(
            'QListWidget#queue_list::item { padding: 2px 4px; }')
        # Lower minimum so the user can shrink the window when they only
        # need a few rows visible. The maximum still allows ~17 rows when
        # the window is tall, and the natural sizeHint settles to ~6 rows
        # by default with stretch=0 in the parent layout.
        self.file_list.setMinimumHeight(100)
        self.file_list.setMaximumHeight(420)
        self.file_list.files_dropped.connect(self._add_files)
        self.file_list.currentRowChanged.connect(self._on_video_selected)
        # UI-fix: when selection changes, repaint per-row widgets so the
        # label can flip to white on the orange highlight (a child QLabel
        # of a setItemWidget overlay doesn't pick up
        # `QListWidget::item:selected color` automatically).
        self.file_list.itemSelectionChanged.connect(
            self._apply_row_selection_styles)
        self.file_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(
            self._on_queue_context_menu)
        # Persist the queue when row order changes (drag-reorder).
        # V11.5 fix (audit B3): drag-reorder serializes items to mime data
        # and reconstructs them at the new position; the per-row widget
        # set via setItemWidget is a view-side overlay and gets DESTROYED
        # in the move. We re-install widgets across all rows after a move
        # so the picker / row label survives drag-reorder.
        self.file_list.model().rowsMoved.connect(
            self._on_rows_moved)
        v.addWidget(self.file_list)

        row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add Files...")
        self.add_btn.clicked.connect(self._on_add_clicked)
        # V14.6.0: bulk-add from a folder (recursive). Picks a single
        # directory then walks it + all subfolders for any file whose
        # extension is in ALL_INPUT_EXTS. The collected paths flow
        # through the normal _add_files path so dedup, audio-visual
        # prompting (or auto-assign), watch-folder logic, and the
        # mid-batch add_jobs() hook all work without changes.
        self.add_folder_btn = QPushButton("📂 Add from Folder...")
        self.add_folder_btn.setToolTip(
            "Scan a folder (including all subfolders) and add every "
            "supported video / audio file to the queue. If the folder "
            "mixes several file formats you will be asked which ones to "
            "import.")
        self.add_folder_btn.clicked.connect(self._on_add_folder_clicked)
        self.remove_btn = QPushButton("− Remove Selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.remove_done_btn = QPushButton("✓ Remove Done")
        self.remove_done_btn.setToolTip(
            "Remove only successfully-completed items from the queue. "
            "Failed and cancelled rows stay so you can decide whether to "
            "retry or remove them manually.")
        self.remove_done_btn.clicked.connect(self._remove_done_only)
        self.clear_done_btn = QPushButton("✓ Remove Completed")
        self.clear_done_btn.setToolTip(
            "Remove all finished items (done + failed + cancelled).")
        self.clear_done_btn.clicked.connect(self._remove_completed)
        self.clear_btn = QPushButton("✕ Clear All")
        self.clear_btn.setToolTip(
            "Remove every item from the queue (asks for confirmation "
            "first). Source files on disk are never touched.")
        self.clear_btn.clicked.connect(self._clear_queue)
        hint = QLabel(
            "Drag-drop files. Click to select, Ctrl / Shift + click for "
            "multi. Drag rows to reorder. Right-click for more. Type a "
            "profile's number to assign it to the selected rows.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        row.addWidget(self.add_btn)
        row.addWidget(self.add_folder_btn)
        row.addWidget(self.remove_btn)
        row.addWidget(self.remove_done_btn)
        row.addWidget(self.clear_done_btn)
        row.addWidget(self.clear_btn)
        row.addStretch()
        row.addWidget(hint, 1)
        v.addLayout(row)
        return box

    def _set_queue_locked(self, locked: bool):
        # V14.3.0: Add Files stays enabled during a batch — newly-added
        # rows go to the end of the pending queue and are picked up by
        # the running BatchManager automatically. Destructive actions
        # (Remove, Remove Done, Remove Completed, Clear All) remain
        # disabled so the user can't pull the rug out from under the
        # encoder mid-job.
        self.add_btn.setEnabled(True)
        if hasattr(self, "add_folder_btn"):
            self.add_folder_btn.setEnabled(True)
        self.remove_btn.setEnabled(not locked)
        self.remove_done_btn.setEnabled(not locked)
        self.clear_done_btn.setEnabled(not locked)
        self.clear_btn.setEnabled(not locked)
        self.file_list.setDragDropMode(
            QListWidget.DragDropMode.NoDragDrop if locked
            else QListWidget.DragDropMode.InternalMove)
        # V11.5 fix (audit E2): grey out the per-row profile combos so
        # the user can't reassign profiles mid-batch (the change handler
        # already bounces these back, but disabling avoids the visual
        # snap-back surprise).
        for i in range(self.file_list.count()):
            wrap = self.file_list.itemWidget(self.file_list.item(i))
            if wrap is None:
                continue
            combo = getattr(wrap, "_combo", None)
            if combo is not None:
                combo.setEnabled(not locked)
        self._queue_locked = locked

    def _build_middle(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_preview_pane())
        splitter.addWidget(self._build_settings_pane())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([780, 480])
        # Stash so closeEvent can save its position and _load_settings can
        # restore it.
        self.middle_splitter = splitter
        return splitter

    def _build_preview_pane(self) -> QWidget:
        box = QGroupBox("Preview")
        v = QVBoxLayout(box)
        v.setSpacing(8)

        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("preview")
        # Lower minimum so the window can be made shorter; the preview
        # pixmap is rescaled to whatever space the frame actually has.
        self.preview_frame.setMinimumSize(QSize(360, 200))
        pf = QVBoxLayout(self.preview_frame)
        pf.setContentsMargins(2, 2, 2, 2)
        self.preview_label = QLabel(
            "Add a video or audio file. Drag the orange bars to set trim points.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "color: #8a8e96; background: transparent;")
        pf.addWidget(self.preview_label)

        # V14.0: source-metadata overlay floats in the top-left corner of
        # the preview frame. Shows live Source / Duration / Resolution /
        # Codec / Profile for the currently-selected row. Kept transparent
        # background-with-shadow-text so it reads against dark video.
        self.preview_overlay = QLabel(self.preview_frame)
        self.preview_overlay.setStyleSheet(
            "QLabel { "
            "  background: rgba(0, 0, 0, 160); "
            "  color: #f0f0f0; "
            "  padding: 6px 10px; "
            "  border-radius: 6px; "
            "  font-size: 9pt; "
            "}"
        )
        self.preview_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview_overlay.setText("")
        self.preview_overlay.hide()
        self.preview_overlay.move(10, 10)
        v.addWidget(self.preview_frame, 1)

        # V14.0: real video playback via QtMultimedia. The QVideoWidget
        # is parented to the preview frame and starts hidden — clicking
        # ▶ Play swaps the static thumbnail for the live player. Stop
        # restores the thumbnail.
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PyQt6.QtMultimediaWidgets import QVideoWidget
            self._mp_video_widget = QVideoWidget(self.preview_frame)
            self._mp_video_widget.setStyleSheet(
                "background: #000000; border-radius: 6px;")
            self._mp_video_widget.hide()
            self._mp_player = QMediaPlayer(self)
            self._mp_audio_out = QAudioOutput(self)
            self._mp_player.setAudioOutput(self._mp_audio_out)
            self._mp_player.setVideoOutput(self._mp_video_widget)
            self._mp_player.positionChanged.connect(self._mp_on_position)
            self._mp_player.durationChanged.connect(self._mp_on_duration)
            self._mp_player.playbackStateChanged.connect(
                self._mp_on_playback_state)
            self._mp_loaded_src = ""
            self._mp_available = True
        except ImportError as exc:
            log.info("QtMultimedia unavailable: %s", exc)
            self._mp_player = None
            self._mp_video_widget = None
            self._mp_available = False

        # Transport row (always created; buttons disabled if multimedia
        # didn't import).
        transport = QHBoxLayout()
        transport.setContentsMargins(0, 4, 0, 0)
        transport.setSpacing(6)
        self.mp_play_btn = QPushButton("▶")
        self.mp_play_btn.setToolTip("Play")
        self.mp_play_btn.setFixedWidth(32)
        self.mp_pause_btn = QPushButton("⏸")
        self.mp_pause_btn.setToolTip("Pause")
        self.mp_pause_btn.setFixedWidth(32)
        self.mp_stop_btn = QPushButton("■")
        self.mp_stop_btn.setToolTip("Stop")
        self.mp_stop_btn.setFixedWidth(32)
        self.mp_pos_lbl = QLabel("00:00 / 00:00")
        self.mp_pos_lbl.setProperty("role", "muted")
        self.mp_pos_lbl.setMinimumWidth(110)
        self.mp_pos_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        vol_lbl = QLabel("🔊")
        vol_lbl.setProperty("role", "muted")
        self.mp_volume = QSlider(Qt.Orientation.Horizontal)
        self.mp_volume.setRange(0, 100)
        self.mp_volume.setValue(80)
        self.mp_volume.setFixedWidth(90)
        self.mp_volume.setToolTip("Playback volume")
        self.mp_play_btn.clicked.connect(self._mp_play)
        self.mp_pause_btn.clicked.connect(self._mp_pause)
        self.mp_stop_btn.clicked.connect(self._mp_stop)
        self.mp_volume.valueChanged.connect(self._mp_set_volume)
        transport.addWidget(self.mp_play_btn)
        transport.addWidget(self.mp_pause_btn)
        transport.addWidget(self.mp_stop_btn)
        transport.addWidget(self.mp_pos_lbl)
        transport.addStretch()
        transport.addWidget(vol_lbl)
        transport.addWidget(self.mp_volume)
        v.addLayout(transport)
        if not self._mp_available:
            for b in (self.mp_play_btn, self.mp_pause_btn, self.mp_stop_btn,
                      self.mp_volume):
                b.setEnabled(False)
            self.mp_pos_lbl.setText("playback unavailable")

        self.seek_bar = TrimSeekBar()
        self.seek_bar.setToolTip(
            "Click or drag to preview any point in the file. Drag the "
            "orange handles to set the trim start / end visually.")
        self.seek_bar.seek_changed.connect(self._on_seek_changed)
        self.seek_bar.trim_changed.connect(self._on_trim_changed_from_bar)
        self.seek_bar.drag_finished.connect(self._refresh_preview)
        v.addWidget(self.seek_bar)

        time_row = QHBoxLayout()
        self.current_time_lbl = QLabel("00:00.00")
        self.current_time_lbl.setProperty("role", "muted")
        self.current_time_lbl.setMinimumWidth(70)
        self.duration_lbl = QLabel("00:00.00")
        self.duration_lbl.setProperty("role", "muted")
        self.duration_lbl.setMinimumWidth(70)
        self.duration_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.trim_info_lbl = QLabel("")
        self.trim_info_lbl.setProperty("role", "muted")
        self.trim_info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_row.addWidget(self.current_time_lbl)
        time_row.addWidget(self.trim_info_lbl, 1)
        time_row.addWidget(self.duration_lbl)
        v.addLayout(time_row)

        # Source -> Output transformation summary, refreshed whenever the
        # selected file or the output settings change.
        self.preview_info_lbl = QLabel("")
        self.preview_info_lbl.setProperty("role", "muted")
        self.preview_info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info_lbl.setWordWrap(True)
        v.addWidget(self.preview_info_lbl)
        return box

    def _build_settings_pane(self) -> QWidget:
        tabs = QTabWidget()
        # V14.3.8: wrap each tab in a QScrollArea so the natural content
        # height can exceed the tab pane height without rows overlapping.
        # This was a macOS-only bug: macOS native QComboBox / QSpinBox /
        # QPushButton are visibly taller than the Windows defaults, so on
        # a short window the Watermark tab's 18 rows of controls couldn't
        # all fit and the layout engine squished rows into each other,
        # producing a stacked / overlapped look (see V14.3.8 release).
        # Wrapping every tab keeps the fix consistent across platforms.
        tabs.addTab(self._wrap_in_scroll(self._build_trim_tab()), "Trim")
        tabs.addTab(self._wrap_in_scroll(self._build_watermark_tab()),
                    "Watermark")
        tabs.addTab(self._wrap_in_scroll(self._build_audio_visuals_tab()),
                    "Audio Visuals")
        tabs.addTab(self._wrap_in_scroll(self._build_output_tab()),
                    "Output")
        tabs.setTabToolTip(0, "Cut time off the start / end of each output.")
        tabs.setTabToolTip(1, "Overlay an image, video, or text watermark.")
        tabs.setTabToolTip(
            2, "Choose the visuals or animated template shown for "
               "audio-only inputs.")
        tabs.setTabToolTip(
            3, "Codec, quality, resolution, speed, intro / outro, and "
               "output filename settings.")
        return tabs

    def _describe_gpu_status(self) -> str:
        """V14.4.1: short, human-friendly summary of which GPU encoders
        were detected on this physical PC. Goes into the status bar on
        startup so the user knows what hardware acceleration is active
        without opening Settings → Output → Encoder.
        """
        gpus: list = []
        # Look at the detected encoder list (already runtime-probed
        # against the actual GPU on this machine).
        avail = set(getattr(self, "available_encoders", None) or [])
        # NVIDIA / AMD / Intel — by encoder family.
        if "h264_nvenc" in avail or "hevc_nvenc" in avail:
            tag = "NVIDIA NVENC"
            if "av1_nvenc" in avail:
                tag += " (incl. AV1)"
            gpus.append(tag)
        if "h264_amf" in avail or "hevc_amf" in avail:
            tag = "AMD AMF"
            if "av1_amf" in avail:
                tag += " (incl. AV1)"
            gpus.append(tag)
        if "h264_qsv" in avail or "hevc_qsv" in avail:
            tag = "Intel QSV"
            if "av1_qsv" in avail:
                tag += " (incl. AV1)"
            gpus.append(tag)
        # V14.7.0: surface the CPU AV1 encoder separately when no GPU
        # AV1 was found, so users see that AV1 is available at all on
        # this PC even if it'll be slower than h264/hevc.
        has_gpu_av1 = any(e in avail for e in
                          ("av1_nvenc", "av1_amf", "av1_qsv"))
        if "libsvtav1" in avail and not has_gpu_av1:
            gpus.append("SVT-AV1 (CPU)")
        if gpus:
            return ("GPU acceleration: " + " · ".join(gpus)
                    + " (auto-detected). "
                      "Settings → Output → Encoder lets you override.")
        return ("No GPU encoder detected on this PC — encoding will use "
                "CPU (libx264 / libx265). "
                "Tools → Re-detect GPU encoders to rerun the probe.")

    # ============================================================ crash reporter

    # Sentinel that the user has been asked whether to enable crash
    # reporting at least once. False on a fresh install — we'll prompt
    # on the first launch that finds a pending crash (or via the Tools
    # menu).
    _CRASH_OPT_IN_KEY = "crash_reports_opt_in"
    _CRASH_PROMPTED_KEY = "crash_reports_prompted"

    def _maybe_prompt_pending_crashes(self):
        """V14.5.0: scan the log dir for unactioned crash files. If
        any exist, prompt the user (per-file) to send / discard /
        defer. Honors the opt-in setting — if the user hasn't
        explicitly enabled crash reporting yet we ask them once before
        offering to send.
        """
        try:
            from .crash_reporter import list_pending_reports
            from .persistence import log_dir
        except Exception:
            return
        pending = list_pending_reports(log_dir())
        if not pending:
            return
        log.info("Found %d pending crash report(s)", len(pending))
        # First-launch opt-in: if the user hasn't been asked yet, ask
        # now. They can change it later via Tools → Crash reporting…
        if not bool(self.settings.value(self._CRASH_PROMPTED_KEY, False, bool)):
            r = QMessageBox.question(
                self, "Crash reports",
                "Veloxa noticed an unhandled error from a previous "
                "session.\n\nYou can help fix this kind of bug by "
                "sending a crash report. Crash reports include the "
                "error traceback and the last ~200 lines of the "
                "session log; the username is removed from any file "
                "paths.\n\n**No data is sent automatically** — the "
                "report opens in your browser pre-filled so you can "
                "review and remove anything before submitting on "
                "GitHub.\n\nEnable crash reporting?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No)
            self.settings.setValue(self._CRASH_PROMPTED_KEY, True)
            self.settings.setValue(
                self._CRASH_OPT_IN_KEY,
                r == QMessageBox.StandardButton.Yes)
        opted_in = bool(self.settings.value(
            self._CRASH_OPT_IN_KEY, False, bool))
        if not opted_in:
            # Sweep the pending files so we don't keep re-prompting
            # forever on every launch when the user said no.
            try:
                from .crash_reporter import mark_dismissed
                for p in pending:
                    mark_dismissed(p)
            except Exception:
                pass
            return
        # User is opted in — prompt for each unactioned crash file.
        for crash_path in pending:
            self._prompt_send_crash(crash_path)

    def _prompt_send_crash(self, crash_path):
        """One-shot dialog for a single crash file. The user picks:
        Send → opens a pre-filled GitHub Issue URL in the browser
        Discard → marks the file ``*.dismissed`` (no further prompts)
        Later → leaves the file in place; we ask again next launch.
        """
        from .crash_reporter import (
            build_issue_url, mark_reported, mark_dismissed,
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("Send crash report?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f"Veloxa caught an unhandled error in a previous session "
            f"({crash_path.name}).\n\nOpen GitHub in your browser to "
            f"send a pre-filled report? You can review and edit it "
            f"before submitting — nothing is sent until you click "
            f"\"Submit new issue\" on the GitHub page.")
        send_btn = msg.addButton(
            "Send report", QMessageBox.ButtonRole.AcceptRole)
        later_btn = msg.addButton(
            "Later", QMessageBox.ButtonRole.RejectRole)
        msg.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(send_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is send_btn:
            url = build_issue_url(
                VELOXA_GITHUB_REPO, crash_path, VELOXA_APP_VERSION)
            if not url:
                QMessageBox.warning(
                    self, "Send crash report",
                    "Could not build the issue URL — the GitHub repo "
                    "isn't configured.")
                return
            try:
                from PyQt6.QtGui import QDesktopServices
                from PyQt6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(url))
                mark_reported(crash_path)
            except Exception as exc:
                QMessageBox.warning(
                    self, "Send crash report",
                    f"Could not open the browser:\n\n{exc}")
        elif clicked is later_btn:
            return  # leave the file unactioned
        else:
            mark_dismissed(crash_path)

    def _report_a_problem_manual(self):
        """V14.5.0: build a crash-style report from the CURRENT session
        log (even though nothing crashed) and offer the same browser
        opt-in flow. Useful when the user hit a non-fatal weird thing
        and wants to file it.
        """
        from .crash_reporter import write_crash_file, build_issue_url
        from .persistence import log_dir
        # Synthesise a fake "exception" so write_crash_file has a
        # consistent body shape — the traceback is empty but the
        # log-tail and version block still go in.
        class _ManualReport(Exception):
            pass
        try:
            raise _ManualReport(
                "User-initiated report via Tools → Report a problem")
        except _ManualReport:
            exc_type, exc_value, exc_tb = sys.exc_info()
        crash_path = write_crash_file(
            log_dir(), self.log_file_path, exc_type, exc_value, exc_tb,
            VELOXA_APP_VERSION)
        if not crash_path:
            QMessageBox.warning(
                self, "Report a problem",
                "Could not write the report file. Open the log folder "
                "manually and attach the session log to a GitHub "
                "Issue instead.")
            return
        url = build_issue_url(
            VELOXA_GITHUB_REPO, crash_path, VELOXA_APP_VERSION)
        if not url:
            QMessageBox.information(
                self, "Report a problem",
                "Report file written to:\n\n"
                f"{crash_path}\n\nGitHub repo isn't configured, so "
                "attach it manually to an issue.")
            return
        try:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
            from .crash_reporter import mark_reported
            mark_reported(crash_path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Report a problem",
                f"Could not open the browser:\n\n{exc}\n\nReport file:\n"
                f"{crash_path}")

    def _crash_reporting_settings(self):
        """V14.5.0: toggle the opt-in for crash reports."""
        currently_on = bool(self.settings.value(
            self._CRASH_OPT_IN_KEY, False, bool))
        msg = QMessageBox(self)
        msg.setWindowTitle("Crash reporting")
        msg.setIcon(QMessageBox.Icon.Information)
        state = "ON" if currently_on else "OFF"
        msg.setText(
            f"Crash reporting is currently {state}.\n\n"
            "When ON: Veloxa watches for unhandled errors. On the next "
            "launch after a crash, it offers to open GitHub in your "
            "browser with a pre-filled report. No data is sent "
            "automatically — you review and submit on github.com.\n\n"
            "When OFF: crash files are written for your own logs but "
            "never surfaced.\n\n"
            "Toggle?")
        toggle_btn = msg.addButton(
            f"Turn {'OFF' if currently_on else 'ON'}",
            QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Keep as-is", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is toggle_btn:
            self.settings.setValue(
                self._CRASH_OPT_IN_KEY, not currently_on)
            self.settings.setValue(self._CRASH_PROMPTED_KEY, True)
            self.status_lbl.setText(
                f"Crash reporting: "
                f"{'ON' if not currently_on else 'OFF'}")

    def _redetect_gpu_encoders(self):
        """V14.4.1: force a fresh GPU-encoder probe and update the UI.

        The detection cache (``%APPDATA%\\Veloxa-VD\\encoder_cache.json``,
        keyed by FFmpeg version + machine ID) is bypassed via
        ``force_rescan=True``, then re-written with the new result. The
        encoder dropdown is refreshed so any newly-available GPU
        encoders appear immediately, and the user sees a summary
        dialog with the result.
        """
        if not self.ffmpeg:
            QMessageBox.information(
                self, "Re-detect GPU encoders",
                "FFmpeg isn't available — nothing to probe.")
            return
        self.status_lbl.setText("Re-detecting GPU encoders…")
        QApplication.processEvents()
        try:
            self.available_encoders = detect_available_encoders(
                self.ffmpeg, force_rescan=True)
            log.info("Re-detected encoders: %s", self.available_encoders)
        except Exception as exc:
            log.warning("Re-detect failed: %s", exc)
            QMessageBox.warning(
                self, "Re-detect GPU encoders",
                f"GPU re-detection failed:\n\n{exc}")
            return
        try:
            self._refresh_encoder_combo()
        except Exception:
            pass
        # Friendly summary in a dialog.
        summary = self._describe_gpu_status()
        # Also list every concrete encoder that survived the probe.
        listed = ", ".join(self.available_encoders) or "(none)"
        QMessageBox.information(
            self, "GPU encoders re-detected",
            f"{summary}\n\nFull list:\n{listed}")
        self.status_lbl.setText(summary)

    def _wrap_in_scroll(self, content: QWidget) -> QScrollArea:
        """V14.3.8: wrap a tab's content widget in a vertically-scrolling
        :class:`QScrollArea`. ``setWidgetResizable(True)`` lets the inner
        widget expand to fill the viewport horizontally (and only show
        a vertical scrollbar when the natural height exceeds the
        viewport). ``NoFrame`` keeps the visual chrome flush with the
        tab pane edges — the QSS already paints the pane background.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _build_trim_tab(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(14, 14, 14, 14)
        g.setVerticalSpacing(10)
        self.trim_start = QDoubleSpinBox()
        self.trim_start.setRange(0, 99999)
        self.trim_start.setDecimals(2); self.trim_start.setSuffix(" s")
        self.trim_start.setToolTip(
            "Seconds to cut from the beginning of the output. "
            "0 = keep the original start.")
        self.trim_end = QDoubleSpinBox()
        self.trim_end.setRange(0, 99999)
        self.trim_end.setDecimals(2); self.trim_end.setSuffix(" s")
        self.trim_end.setToolTip(
            "Seconds to cut from the end of the output. "
            "0 = keep the original end.")
        g.addWidget(QLabel("Trim from start:"), 0, 0)
        g.addWidget(self.trim_start, 0, 1)
        g.addWidget(QLabel("Trim from end:"), 1, 0)
        g.addWidget(self.trim_end, 1, 1)
        hint = QLabel(
            "Drag the orange handles on the seek bar for visual trimming, "
            "or type exact values here. 0 = no trim on that side.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        g.addWidget(hint, 2, 0, 1, 2)
        g.setRowStretch(3, 1)
        return w

    def _build_watermark_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(10)
        outer.addWidget(self._build_image_wm_group())
        outer.addWidget(self._build_video_wm_group())
        outer.addWidget(self._build_text_wm_group())
        outer.addStretch(1)
        return w

    def _build_image_wm_group(self) -> QWidget:
        box = QGroupBox("Image Watermark (optional)")
        g = QGridLayout(box)
        g.setVerticalSpacing(8)
        r = 0
        self.wm_path = QLineEdit()
        self.wm_path.setPlaceholderText("(no image watermark)")
        self.wm_path.setToolTip(
            "Path to the watermark image. PNG with transparency "
            "recommended. Leave empty for no image watermark.")
        wm_browse = QPushButton("📂 Browse...")
        wm_browse.setToolTip("Choose a watermark image file.")
        wm_browse.clicked.connect(self._pick_watermark)
        wm_clear = QPushButton("✕ Clear")
        wm_clear.setToolTip("Remove the image watermark.")
        wm_clear.clicked.connect(lambda: self.wm_path.setText(""))
        g.addWidget(QLabel("Image:"), r, 0)
        g.addWidget(self.wm_path, r, 1, 1, 2)
        g.addWidget(wm_browse, r, 3); g.addWidget(wm_clear, r, 4)
        r += 1

        self.wm_preset = QComboBox()
        self.wm_preset.addItems(POSITION_PRESETS)
        self.wm_preset.setCurrentText("Bottom-Right")
        self.wm_preset.setToolTip(
            "Corner or edge of the frame the watermark is anchored to. "
            "Fine-tune with Offset X / Y below.")
        g.addWidget(QLabel("Position:"), r, 0)
        g.addWidget(self.wm_preset, r, 1, 1, 4)
        r += 1

        self.wm_off_x = QSpinBox()
        self.wm_off_x.setRange(-4000, 4000); self.wm_off_x.setSuffix(" px")
        self.wm_off_x.setToolTip(
            "Horizontal shift from the anchored position, in pixels.")
        self.wm_off_y = QSpinBox()
        self.wm_off_y.setRange(-4000, 4000); self.wm_off_y.setSuffix(" px")
        self.wm_off_y.setToolTip(
            "Vertical shift from the anchored position, in pixels.")
        g.addWidget(QLabel("Offset X:"), r, 0); g.addWidget(self.wm_off_x, r, 1)
        g.addWidget(QLabel("Y:"), r, 2); g.addWidget(self.wm_off_y, r, 3)
        r += 1

        self.wm_padding = QSpinBox()
        self.wm_padding.setRange(0, 1000); self.wm_padding.setSuffix(" px")
        self.wm_padding.setValue(20)
        self.wm_padding.setToolTip(
            "Minimum gap kept between the watermark and the frame edges.")
        g.addWidget(QLabel("Edge padding:"), r, 0)
        g.addWidget(self.wm_padding, r, 1, 1, 4)
        r += 1

        self.wm_opacity = QSlider(Qt.Orientation.Horizontal)
        self.wm_opacity.setRange(0, 100); self.wm_opacity.setValue(100)
        self.wm_opacity.setToolTip(
            "Watermark opacity: 100% = solid, lower = more transparent.")
        self.wm_opacity_lbl = QLabel("100%")
        self.wm_opacity.valueChanged.connect(
            lambda v: self.wm_opacity_lbl.setText(f"{v}%"))
        g.addWidget(QLabel("Opacity:"), r, 0)
        g.addWidget(self.wm_opacity, r, 1, 1, 3)
        g.addWidget(self.wm_opacity_lbl, r, 4)
        r += 1

        self.wm_scale = QSlider(Qt.Orientation.Horizontal)
        self.wm_scale.setRange(1, 100); self.wm_scale.setValue(15)
        self.wm_scale.setToolTip(
            "Watermark width as a percentage of the output video width.")
        self.wm_scale_lbl = QLabel("15% of width")
        self.wm_scale.valueChanged.connect(
            lambda v: self.wm_scale_lbl.setText(f"{v}% of width"))
        g.addWidget(QLabel("Size:"), r, 0)
        g.addWidget(self.wm_scale, r, 1, 1, 3)
        g.addWidget(self.wm_scale_lbl, r, 4)
        return box

    def _build_video_wm_group(self) -> QWidget:
        box = QGroupBox("Video Watermark (optional)")
        g = QGridLayout(box)
        g.setVerticalSpacing(8)
        r = 0
        self.vid_wm_path = QLineEdit()
        self.vid_wm_path.setPlaceholderText("(no video watermark)")
        self.vid_wm_path.setToolTip(
            "Path to a video clip overlaid on the output (e.g. an "
            "animated logo). Leave empty for no video watermark.")
        vid_browse = QPushButton("📂 Browse...")
        vid_browse.setToolTip("Choose a video clip to overlay.")
        vid_browse.clicked.connect(self._pick_video_watermark)
        vid_clear = QPushButton("✕ Clear")
        vid_clear.setToolTip("Remove the video watermark.")
        vid_clear.clicked.connect(lambda: self.vid_wm_path.setText(""))
        g.addWidget(QLabel("Video:"), r, 0)
        g.addWidget(self.vid_wm_path, r, 1, 1, 2)
        g.addWidget(vid_browse, r, 3); g.addWidget(vid_clear, r, 4)
        r += 1

        note = QLabel(
            "If shorter than the main output, the video watermark loops "
            "automatically (-stream_loop -1).")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        g.addWidget(note, r, 0, 1, 5)
        r += 1

        self.vid_wm_preset = QComboBox()
        self.vid_wm_preset.addItems(POSITION_PRESETS)
        self.vid_wm_preset.setCurrentText("Top-Right")
        self.vid_wm_preset.setToolTip(
            "Corner or edge of the frame the video watermark is anchored "
            "to. Fine-tune with Offset X / Y below.")
        g.addWidget(QLabel("Position:"), r, 0)
        g.addWidget(self.vid_wm_preset, r, 1, 1, 4)
        r += 1

        self.vid_wm_off_x = QSpinBox()
        self.vid_wm_off_x.setRange(-4000, 4000); self.vid_wm_off_x.setSuffix(" px")
        self.vid_wm_off_x.setToolTip(
            "Horizontal shift from the anchored position, in pixels.")
        self.vid_wm_off_y = QSpinBox()
        self.vid_wm_off_y.setRange(-4000, 4000); self.vid_wm_off_y.setSuffix(" px")
        self.vid_wm_off_y.setToolTip(
            "Vertical shift from the anchored position, in pixels.")
        g.addWidget(QLabel("Offset X:"), r, 0); g.addWidget(self.vid_wm_off_x, r, 1)
        g.addWidget(QLabel("Y:"), r, 2); g.addWidget(self.vid_wm_off_y, r, 3)
        r += 1

        self.vid_wm_padding = QSpinBox()
        self.vid_wm_padding.setRange(0, 1000); self.vid_wm_padding.setSuffix(" px")
        self.vid_wm_padding.setValue(20)
        self.vid_wm_padding.setToolTip(
            "Minimum gap kept between the watermark and the frame edges.")
        g.addWidget(QLabel("Edge padding:"), r, 0)
        g.addWidget(self.vid_wm_padding, r, 1, 1, 4)
        r += 1

        self.vid_wm_opacity = QSlider(Qt.Orientation.Horizontal)
        self.vid_wm_opacity.setRange(0, 100); self.vid_wm_opacity.setValue(100)
        self.vid_wm_opacity.setToolTip(
            "Watermark opacity: 100% = solid, lower = more transparent.")
        self.vid_wm_opacity_lbl = QLabel("100%")
        self.vid_wm_opacity.valueChanged.connect(
            lambda v: self.vid_wm_opacity_lbl.setText(f"{v}%"))
        g.addWidget(QLabel("Opacity:"), r, 0)
        g.addWidget(self.vid_wm_opacity, r, 1, 1, 3)
        g.addWidget(self.vid_wm_opacity_lbl, r, 4)
        r += 1

        self.vid_wm_scale = QSlider(Qt.Orientation.Horizontal)
        self.vid_wm_scale.setRange(1, 100); self.vid_wm_scale.setValue(20)
        self.vid_wm_scale.setToolTip(
            "Watermark width as a percentage of the output video width.")
        self.vid_wm_scale_lbl = QLabel("20% of width")
        self.vid_wm_scale.valueChanged.connect(
            lambda v: self.vid_wm_scale_lbl.setText(f"{v}% of width"))
        g.addWidget(QLabel("Size:"), r, 0)
        g.addWidget(self.vid_wm_scale, r, 1, 1, 3)
        g.addWidget(self.vid_wm_scale_lbl, r, 4)
        return box

    def _pick_video_watermark(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Video Watermark",
            self.settings.value("last_vid_wm_dir", ""),
            "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v "
            "*.mpg *.mpeg *.ts *.3gp);;All Files (*.*)")
        if f:
            self.vid_wm_path.setText(f)
            self.settings.setValue("last_vid_wm_dir", str(Path(f).parent))

    def _build_text_wm_group(self) -> QWidget:
        box = QGroupBox("Text Watermark (optional)")
        g = QGridLayout(box)
        g.setVerticalSpacing(8)
        r = 0
        self.text_wm_text = QLineEdit()
        self.text_wm_text.setPlaceholderText("(no text watermark)")
        self.text_wm_text.setToolTip(
            "Text drawn onto every frame (e.g. a channel name or "
            "copyright line). Leave empty for no text watermark.")
        g.addWidget(QLabel("Text:"), r, 0)
        g.addWidget(self.text_wm_text, r, 1, 1, 4)
        r += 1

        self.text_wm_size = QSpinBox()
        self.text_wm_size.setRange(8, 400); self.text_wm_size.setValue(36)
        self.text_wm_size.setSuffix(" px")
        self.text_wm_size.setToolTip(
            "Font size of the text watermark, in pixels of the output "
            "frame.")
        g.addWidget(QLabel("Font size:"), r, 0)
        g.addWidget(self.text_wm_size, r, 1)

        self.text_wm_color_btn = QPushButton("🎨 Color...")
        self.text_wm_color_btn.setToolTip("Pick the text colour.")
        self.text_wm_color_btn.clicked.connect(self._pick_text_color)
        self.text_wm_color_swatch = QFrame()
        self.text_wm_color_swatch.setToolTip("Current text colour.")
        self.text_wm_color_swatch.setFixedSize(28, 22)
        self.text_wm_color_swatch.setStyleSheet(
            "background:#ffffff; border:1px solid #454952; border-radius:3px;")
        g.addWidget(QLabel("Color:"), r, 2)
        g.addWidget(self.text_wm_color_swatch, r, 3)
        g.addWidget(self.text_wm_color_btn, r, 4)
        r += 1

        self.text_wm_preset = QComboBox()
        self.text_wm_preset.addItems(POSITION_PRESETS)
        self.text_wm_preset.setCurrentText("Bottom-Left")
        self.text_wm_preset.setToolTip(
            "Corner or edge of the frame the text is anchored to. "
            "Fine-tune with Offset X / Y below.")
        g.addWidget(QLabel("Position:"), r, 0)
        g.addWidget(self.text_wm_preset, r, 1, 1, 4)
        r += 1

        self.text_wm_off_x = QSpinBox()
        self.text_wm_off_x.setRange(-4000, 4000); self.text_wm_off_x.setSuffix(" px")
        self.text_wm_off_x.setToolTip(
            "Horizontal shift from the anchored position, in pixels.")
        self.text_wm_off_y = QSpinBox()
        self.text_wm_off_y.setRange(-4000, 4000); self.text_wm_off_y.setSuffix(" px")
        self.text_wm_off_y.setToolTip(
            "Vertical shift from the anchored position, in pixels.")
        g.addWidget(QLabel("Offset X:"), r, 0); g.addWidget(self.text_wm_off_x, r, 1)
        g.addWidget(QLabel("Y:"), r, 2); g.addWidget(self.text_wm_off_y, r, 3)
        r += 1

        self.text_wm_padding = QSpinBox()
        self.text_wm_padding.setRange(0, 1000); self.text_wm_padding.setValue(20)
        self.text_wm_padding.setSuffix(" px")
        self.text_wm_padding.setToolTip(
            "Minimum gap kept between the text and the frame edges.")
        g.addWidget(QLabel("Edge padding:"), r, 0)
        g.addWidget(self.text_wm_padding, r, 1, 1, 4)
        r += 1

        self.text_wm_opacity = QSlider(Qt.Orientation.Horizontal)
        self.text_wm_opacity.setRange(0, 100); self.text_wm_opacity.setValue(100)
        self.text_wm_opacity.setToolTip(
            "Text opacity: 100% = solid, lower = more transparent.")
        self.text_wm_opacity_lbl = QLabel("100%")
        self.text_wm_opacity.valueChanged.connect(
            lambda v: self.text_wm_opacity_lbl.setText(f"{v}%"))
        g.addWidget(QLabel("Opacity:"), r, 0)
        g.addWidget(self.text_wm_opacity, r, 1, 1, 3)
        g.addWidget(self.text_wm_opacity_lbl, r, 4)
        return box

    # ====================================================== audio visuals tab (V11.5)

    def _build_audio_visuals_tab(self) -> QWidget:
        """V11.5: ordered list of images / videos that get assigned to
        audio inputs round-robin when the profile is active.

        Layout:
          [x] Use these visuals for audio inputs
          [ ListWidget                                     ]  [ Add... ]
          [                                                ]  [ Remove ]
          [                                                ]  [ Up    ]
          [                                                ]  [ Down  ]
          [ Help text                                                  ]
        """
        w = QWidget()
        outer = QVBoxLayout(w)

        # V14.0: real-time audio-visual template dropdown. Picks from
        # the registry of FFmpeg-filter-based visualisations (spectrum
        # bars / circular / waveform / neon ring / podcast layout /
        # spotify canvas). When set to anything other than "None", the
        # encode skips the visual-file pipeline entirely and synthesises
        # the picture frame-by-frame from the audio.
        tpl_row = QHBoxLayout()
        tpl_lbl = QLabel("Audio-visual template:")
        tpl_lbl.setMinimumWidth(140)
        self.audio_template_combo = QComboBox()
        from engine import audio_template_choices
        for key, name in audio_template_choices():
            self.audio_template_combo.addItem(name, userData=key)
        self.audio_template_combo.setCurrentIndex(0)
        self.audio_template_combo.setToolTip(
            "Real-time audio-reactive visual. When set, the visual is "
            "generated frame-by-frame from the audio — no image or "
            "video file required.\n\n"
            "Templates use FFmpeg's showspectrum / showcqt / showwaves "
            "filters and run at encode time.")
        tpl_row.addWidget(tpl_lbl)
        tpl_row.addWidget(self.audio_template_combo, 1)
        outer.addLayout(tpl_row)
        # V14.3.2: changing the template needs to refresh the preview
        # pane so the user can see what each template looks like before
        # starting the batch. ``_schedule_preview`` debounces by 200 ms
        # so rapid combo-box arrow-key scrolling doesn't spawn one
        # ffmpeg per row.
        self.audio_template_combo.currentIndexChanged.connect(
            self._schedule_preview)

        self.profile_visuals_enabled = QCheckBox(
            "Use these visuals for audio inputs (round-robin)")
        self.profile_visuals_enabled.setToolTip(
            "When ticked, audio inputs in the queue get a visual assigned "
            "from this list in order, wrapping around when the list is "
            "shorter than the queue. The position in the rotation is "
            "remembered per profile across sessions.\n\n"
            "Ignored when an audio-visual template is selected above — "
            "the template generates its own visuals.")
        # Toggling rotation re-renders the status line (counter, valid
        # count, warnings) so the user can see at a glance whether the
        # rotation will actually fire.
        self.profile_visuals_enabled.toggled.connect(
            lambda *_: self._pv_refresh_status())
        outer.addWidget(self.profile_visuals_enabled)

        row = QHBoxLayout()
        self.profile_visuals_list = QListWidget()
        self.profile_visuals_list.setMinimumHeight(180)
        self.profile_visuals_list.setToolTip(
            "Audio inputs in the queue cycle through this list in order: "
            "audio[0]→#1, audio[1]→#2, ..., audio[N]→#1 (wrap).\n"
            "Drag rows to reorder, or use the Move Up / Move Down "
            "buttons.")
        # V12.3: enable internal drag-reorder so the user can rearrange
        # visuals by dragging instead of (or in addition to) the
        # Move Up / Move Down buttons. The Move buttons stay for
        # keyboard / accessibility users.
        self.profile_visuals_list.setDragDropMode(
            QListWidget.DragDropMode.InternalMove)
        self.profile_visuals_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        # The model's rowsMoved fires after a drag-drop. We don't
        # explicitly persist (the list is read by ``_pv_to_list`` at
        # save-profile time, which walks rows in current order), but
        # nudging `_schedule_preview` lets a live preview reflect the
        # new rotation order if the user has an audio row selected.
        self.profile_visuals_list.model().rowsMoved.connect(
            lambda *_: self._schedule_preview())
        row.addWidget(self.profile_visuals_list, 1)

        col = QVBoxLayout()
        self.pv_add_btn = QPushButton("＋ Add...")
        self.pv_add_btn.setToolTip(
            "Add images or video clips to the visuals rotation.")
        self.pv_add_btn.clicked.connect(self._pv_add)
        col.addWidget(self.pv_add_btn)
        self.pv_remove_btn = QPushButton("− Remove")
        self.pv_remove_btn.setToolTip(
            "Remove the selected visual(s) from the rotation.")
        self.pv_remove_btn.clicked.connect(self._pv_remove)
        col.addWidget(self.pv_remove_btn)
        self.pv_up_btn = QPushButton("▲ Move Up")
        self.pv_up_btn.setToolTip(
            "Move the selected visual up. List order controls which "
            "visual each audio file receives (round-robin).")
        self.pv_up_btn.clicked.connect(lambda: self._pv_move(-1))
        col.addWidget(self.pv_up_btn)
        self.pv_down_btn = QPushButton("▼ Move Down")
        self.pv_down_btn.setToolTip(
            "Move the selected visual down. List order controls which "
            "visual each audio file receives (round-robin).")
        self.pv_down_btn.clicked.connect(lambda: self._pv_move(+1))
        col.addWidget(self.pv_down_btn)
        self.pv_reset_btn = QPushButton("🔄 Reset rotation")
        self.pv_reset_btn.setToolTip(
            "Set this profile's round-robin counter back to 1, so the "
            "next audio input gets the first visual in the list.")
        self.pv_reset_btn.clicked.connect(self._pv_reset_counter)
        col.addWidget(self.pv_reset_btn)
        col.addStretch()
        row.addLayout(col)
        outer.addLayout(row, 1)

        self.pv_status_lbl = QLabel("")
        self.pv_status_lbl.setProperty("role", "muted")
        outer.addWidget(self.pv_status_lbl)

        info = QLabel(
            "Tip: drop image (.png .jpg) or video (.mp4 .mov ...) files "
            "into the list with <b>Add...</b>. Order matters — that's the "
            "rotation order. Use this profile's name when saving / "
            "loading so the rotation counter is per-profile.")
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        outer.addWidget(info)
        return w

    # ---- profile visuals list helpers --------------------------

    PV_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    PV_VID_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

    def _pv_kind_for(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        if ext in self.PV_IMG_EXTS:
            return "image"
        if ext in self.PV_VID_EXTS:
            return "video"
        return ""

    def _pv_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add visuals (images and/or videos)", "",
            "Visuals (*.png *.jpg *.jpeg *.bmp *.webp *.mp4 *.mov *.mkv "
            "*.avi *.webm);;All (*.*)")
        if not paths:
            return
        for p in paths:
            kind = self._pv_kind_for(p)
            if not kind:
                continue
            it = QListWidgetItem(f"[{kind.upper():5}] {Path(p).name}")
            it.setData(Qt.ItemDataRole.UserRole,
                       {"path": p, "kind": kind})
            it.setToolTip(p)
            self.profile_visuals_list.addItem(it)
        self._pv_refresh_status()

    def _pv_remove(self):
        for it in self.profile_visuals_list.selectedItems():
            self.profile_visuals_list.takeItem(
                self.profile_visuals_list.row(it))
        self._pv_refresh_status()

    def _pv_move(self, delta: int):
        row = self.profile_visuals_list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self.profile_visuals_list.count():
            return
        it = self.profile_visuals_list.takeItem(row)
        self.profile_visuals_list.insertItem(new_row, it)
        self.profile_visuals_list.setCurrentRow(new_row)
        self._pv_refresh_status()

    def _pv_to_list(self) -> list:
        """Pull the list-widget rows back into a serializable list of dicts."""
        out = []
        for i in range(self.profile_visuals_list.count()):
            it = self.profile_visuals_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole) or {}
            path = (d.get("path") or "").strip()
            kind = d.get("kind") or self._pv_kind_for(path) or "image"
            if path:
                out.append({"path": path, "kind": kind})
        return out

    def _pv_apply(self, items: list):
        self.profile_visuals_list.clear()
        if isinstance(items, list):
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                path = (entry.get("path") or "").strip()
                kind = entry.get("kind") or self._pv_kind_for(path) or "image"
                if not path:
                    continue
                label = f"[{kind.upper():5}] {Path(path).name}"
                if not os.path.exists(path):
                    label += "  (missing)"
                it = QListWidgetItem(label)
                it.setData(Qt.ItemDataRole.UserRole,
                           {"path": path, "kind": kind})
                it.setToolTip(path)
                self.profile_visuals_list.addItem(it)
        self._pv_refresh_status()

    # ---- per-profile rotation counter (in QSettings) ----------

    def _pv_counter_key(self, profile_name: str) -> str:
        from .profile_assets import rotation_key_for
        return rotation_key_for(profile_name)

    def _pv_get_counter(self, profile_name: str) -> int:
        try:
            return int(self.settings.value(
                self._pv_counter_key(profile_name), 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _pv_set_counter(self, profile_name: str, value: int):
        self.settings.setValue(
            self._pv_counter_key(profile_name), int(max(0, value)))
        # V11.5 fix (audit A7): force a flush so a force-kill mid-batch
        # doesn't lose the rotation advance. Cheap on QSettings.
        try:
            self.settings.sync()
        except Exception:
            pass

    def _pv_reset_counter(self):
        name = self.profile_combo.currentText() or NO_PROFILE
        # V11.5 fix (audit A6): also support resetting the counter for
        # the no-profile case so users who run rotation in NO_PROFILE
        # mode can wind it back, just like a saved profile.
        self._pv_set_counter(name, 0)
        if name == NO_PROFILE:
            self.pv_status_lbl.setText(
                "Rotation counter reset (no profile selected).")
        else:
            self.pv_status_lbl.setText(
                f"Rotation counter reset to 1 for profile '{name}'.")
        self._pv_refresh_status()

    def _pv_refresh_status(self):
        """V11.5 (audit A1/B4): keep the Audio Visuals tab status label
        in sync — show live counter, list size, and any misconfiguration
        so the user can spot why their rotation isn't kicking in."""
        if not hasattr(self, "pv_status_lbl"):
            return
        n = self.profile_visuals_list.count()
        n_valid = 0
        for i in range(n):
            it = self.profile_visuals_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole) or {}
            p = (d.get("path") or "").strip()
            if p and os.path.exists(p):
                n_valid += 1
        enabled = self.profile_visuals_enabled.isChecked()
        name = self.profile_combo.currentText() or NO_PROFILE
        ctr = self._pv_get_counter(name)
        next_idx = (ctr % n_valid + 1) if n_valid > 0 else 0
        bits = []
        if enabled and n_valid == 0:
            bits.append("WARNING: rotation enabled but no usable visuals "
                        "in the list — audio rows will fall back to their "
                        "per-row visual.")
        if n != n_valid:
            bits.append(f"{n - n_valid} missing")
        bits.append(f"{n} visual(s), {n_valid} usable")
        if n_valid > 0 and enabled:
            bits.append(f"next: #{next_idx} (counter={ctr})")
        self.pv_status_lbl.setText("  ·  ".join(bits))

    def _build_output_tab(self) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(14, 14, 14, 14)
        g.setVerticalSpacing(10)
        r = 0

        self.out_codec = QComboBox()
        for k, v in CODEC_LABELS.items():
            self.out_codec.addItem(v, userData=k)
        self.out_codec.setCurrentText(CODEC_LABELS[CODEC_H264])
        self.out_codec.setToolTip(
            "Video codec of the output:\n"
            "  H.264 (AVC)  : plays everywhere (default)\n"
            "  H.265 (HEVC) : ~30% smaller files, wide modern support\n"
            "  AV1          : best compression; encoding is fast only "
            "on recent GPUs")
        self.out_codec.currentIndexChanged.connect(self._refresh_encoder_combo)
        g.addWidget(QLabel("Codec:"), r, 0)
        g.addWidget(self.out_codec, r, 1)
        r += 1

        self.out_encoder = QComboBox()
        self.out_encoder.setToolTip(
            "Encoder used for the chosen codec. 'Auto' picks the best "
            "one detected on this PC (GPU first, CPU fallback). GPU "
            "encoders (NVENC / QSV / AMF) are much faster; libx264 / "
            "libx265 / SVT-AV1 run on the CPU. Only encoders that "
            "probed working on this machine are listed.")
        g.addWidget(QLabel("Encoder:"), r, 0)
        g.addWidget(self.out_encoder, r, 1)
        r += 1

        # V12.3: Quality dropdown removed in favour of bitrate controls
        # below. ``self.out_quality`` is kept as a hidden QComboBox so
        # the rest of the codebase (and saved profiles' speed_tier
        # field) continues to work; the value is locked to "Balanced".
        self.out_quality = QComboBox()
        self.out_quality.addItems(SPEED_TIERS)
        self.out_quality.setCurrentText("Balanced")
        self.out_quality.setVisible(False)

        # V12.3.1: video quality dropdown. Replaces the raw-kbps spinbox
        # with five named tiers (Low / Medium / High / Best / Super
        # Best). The actual target bitrate is resolved at opts-build
        # time using ``resolve_video_bitrate_kbps(tier, out_w, out_h)``
        # so the same tier produces appropriate values at 720p vs 4K.
        # User can't mis-type a number — QComboBox is a closed list.
        self.video_quality = QComboBox()
        self.video_quality.addItems(VIDEO_QUALITY_TIERS)
        self.video_quality.setCurrentText(VIDEO_QUALITY_DEFAULT)
        self.video_quality.setToolTip(
            "Video quality preset. Maps to a target bitrate based on "
            "your output resolution:\n\n"
            "  Low        : small file, OK for previews / sharing\n"
            "  Medium     : web-friendly, balanced size & clarity\n"
            "  High       : streaming-grade (default)\n"
            "  Best       : pristine, larger files for archive\n"
            "  Super Best : near-lossless target, largest files\n\n"
            "Resolved bitrate (kbps) examples:\n"
            "  720p  :  1500 / 2500 / 4000 / 6000 / 10000\n"
            "  1080p :  3000 / 5000 / 8000 / 12000 / 20000\n"
            "  1440p :  6000 / 10000 / 15000 / 25000 / 40000\n"
            "  4K    : 15000 / 25000 / 40000 / 60000 / 90000")
        g.addWidget(QLabel("Video quality:"), r, 0)
        g.addWidget(self.video_quality, r, 1)
        r += 1
        # Inline hint label so the tier ladder is visible at a glance.
        self.video_quality_hint = QLabel("")
        self.video_quality_hint.setStyleSheet("color:#888; font-size:10px;")
        self.video_quality_hint.setWordWrap(True)
        g.addWidget(self.video_quality_hint, r, 1)
        r += 1
        # Refresh the hint whenever the tier OR the output resolution
        # changes — they jointly determine the resolved bitrate.
        self.video_quality.currentTextChanged.connect(
            self._refresh_video_quality_hint)

        # V12.3.1: audio quality dropdown. Same five-tier model.
        self.audio_quality = QComboBox()
        self.audio_quality.addItems(AUDIO_QUALITY_TIERS)
        self.audio_quality.setCurrentText(AUDIO_QUALITY_DEFAULT)
        self.audio_quality.setToolTip(
            "Audio (AAC) quality preset:\n\n"
            "  Low        :  96 kbps  — speech / podcast\n"
            "  Medium     : 128 kbps  — general voice + light music\n"
            "  High       : 192 kbps  — default, transparent mix\n"
            "  Best       : 256 kbps  — music / high-quality content\n"
            "  Super Best : 320 kbps  — AAC ceiling, archive-grade")
        g.addWidget(QLabel("Audio quality:"), r, 0)
        g.addWidget(self.audio_quality, r, 1)
        r += 1
        self.audio_quality_hint = QLabel("")
        self.audio_quality_hint.setStyleSheet("color:#888; font-size:10px;")
        self.audio_quality_hint.setWordWrap(True)
        g.addWidget(self.audio_quality_hint, r, 1)
        r += 1
        self.audio_quality.currentTextChanged.connect(
            self._refresh_audio_quality_hint)

        self.out_res = QComboBox()
        self.out_res.addItems(list(RESOLUTIONS.keys()))
        self.out_res.setCurrentText("4K (3840x2160)")
        self.out_res.setToolTip(
            "Output resolution. Sources are scaled to fit (aspect ratio "
            "preserved). 'Match Source' keeps each file's original "
            "size. Higher resolutions increase file size and encode "
            "time.")
        g.addWidget(QLabel("Resolution:"), r, 0)
        g.addWidget(self.out_res, r, 1)
        r += 1

        self.parallel_jobs = QSpinBox()
        self.parallel_jobs.setRange(1, 2); self.parallel_jobs.setValue(1)
        self.parallel_jobs.setSuffix("  job(s)")
        self.parallel_jobs.setToolTip(
            "How many queue items encode at the same time (1-2). GPU "
            "encoders usually gain nothing beyond 1 — leave at 1 unless "
            "encoding on CPU.")
        g.addWidget(QLabel("Parallel encoding:"), r, 0)
        g.addWidget(self.parallel_jobs, r, 1)
        r += 1

        self.force_stereo = QCheckBox("Force stereo audio (upmix mono inputs)")
        self.force_stereo.setChecked(True)
        self.force_stereo.setToolTip(
            "Outputs stereo audio. Mono inputs are duplicated to L+R; stereo "
            "and multi-channel inputs are downmixed to stereo.")
        g.addWidget(self.force_stereo, r, 0, 1, 2)
        r += 1

        self.loudnorm = QCheckBox(
            "Normalize audio loudness (EBU R128, -16 LUFS)")
        self.loudnorm.setChecked(False)
        self.loudnorm.setToolTip(
            "Single-pass loudness normalization to -16 LUFS / -1.5 dBTP / "
            "LRA 11 (streaming + podcast standard). Adds the FFmpeg "
            "loudnorm audio filter.")
        g.addWidget(self.loudnorm, r, 0, 1, 2)
        r += 1

        self.speed_value = QDoubleSpinBox()
        self.speed_value.setRange(0.1, 10.0)
        self.speed_value.setSingleStep(0.05)
        self.speed_value.setDecimals(2)
        self.speed_value.setValue(1.0)
        self.speed_value.setSuffix("x")
        self.speed_value.setToolTip(
            "Playback speed of the output. 1.0 = unchanged, 2.0 = double "
            "speed, 0.5 = half speed. Applied to both video (setpts) and "
            "audio (atempo, pitch-preserving).")
        g.addWidget(QLabel("Speed:"), r, 0)
        g.addWidget(self.speed_value, r, 1)
        r += 1

        # V14.8.1: removed the duplicate "Detected: ..." label that used
        # to live here. The same info is shown more accurately by the
        # status-bar GPU summary added in V14.4.1
        # (``_describe_gpu_status``), so two labels were repeating the
        # same content — and the Output-tab version had a stale bug
        # where V14.7.0's libsvtav1 (which isn't in CPU_ENCODERS)
        # rendered as "CPU + CPU" in the right-hand suffix.
        #
        # Single source of truth now: the bottom-of-window status bar.

        gpu_note = QLabel(
            "Tip: GPU encoders may not benefit from >1 concurrent job. "
            "Drop to 1 if encoding errors occur.")
        gpu_note.setProperty("role", "muted")
        gpu_note.setWordWrap(True)
        g.addWidget(gpu_note, r, 0, 1, 2)
        r += 1

        self.hw_decode = QCheckBox("Hardware decode (use GPU for source)")
        self.hw_decode.setChecked(True)
        self.hw_decode.setToolTip(
            "Decode the source video on the same GPU that encodes "
            "(NVENC -> CUDA, QSV -> QSV, AMF -> D3D11VA). Significant "
            "speed-up on high-resolution sources. Untick to force CPU "
            "decode if you hit driver-specific issues.")
        g.addWidget(self.hw_decode, r, 0, 1, 2)
        r += 1

        # V14.3.0: parallel CPU encoder slot. When ticked, the batch
        # opens ONE extra concurrent job slot whose encoder is forced
        # to libx264 / libx265 and runs at below-normal priority with
        # a thread-cap so the GPU job + GUI stay responsive. Safe to
        # toggle on/off mid-batch.
        self.use_cpu_alongside_gpu = QCheckBox(
            "Also use CPU encoder when GPU is busy (parallel slot)")
        self.use_cpu_alongside_gpu.setChecked(False)
        self.use_cpu_alongside_gpu.setToolTip(
            "Open an additional concurrent encoder slot that uses the "
            "CPU (libx264 / libx265) so a 2-file batch can encode in "
            "parallel: one on the GPU, one on the CPU. The CPU job is "
            "automatically threaded so the OS / GUI keep responding "
            "and is paused for any tick where free RAM drops below "
            "10%. Safe to flip on or off during a running batch — the "
            "in-flight CPU job finishes naturally.")
        self.use_cpu_alongside_gpu.toggled.connect(
            self._on_use_cpu_alongside_gpu_toggled)
        g.addWidget(self.use_cpu_alongside_gpu, r, 0, 1, 2)
        r += 1

        # V14.8.0: power-user FFmpeg-args passthrough. Anything typed
        # here is shlex-split and appended to every output encode cmd
        # just before the destination filename, so it can set things
        # like ``-profile:v high``, ``-x264-params keyint=120``,
        # ``-color_primaries bt709 -color_trc bt709 -colorspace bt709``,
        # or any other FFmpeg flag the GUI doesn't expose. Empty
        # means "no override" — the default behaviour every existing
        # user sees.
        self.custom_ffmpeg_args = QLineEdit()
        self.custom_ffmpeg_args.setPlaceholderText(
            "(empty)  e.g.  -profile:v high -bf 2")
        self.custom_ffmpeg_args.setToolTip(
            "Power-user FFmpeg flags appended to every output encode "
            "command just before the destination filename. Parsed with "
            "shlex (use quotes for values that contain spaces). Leave "
            "blank for default behaviour. Use only if you know what "
            "you're typing — malformed flags will fail the encode "
            "with FFmpeg's own error.")
        g.addWidget(QLabel("Extra FFmpeg flags:"), r, 0)
        g.addWidget(self.custom_ffmpeg_args, r, 1, 1, 4)
        r += 1

        # Audio fade in / out (post-trim, post-speed).
        self.fade_in = QDoubleSpinBox()
        self.fade_in.setRange(0.0, 30.0); self.fade_in.setDecimals(2)
        self.fade_in.setSingleStep(0.5); self.fade_in.setSuffix(" s")
        self.fade_in.setToolTip("Audio fade-in length at the start of the output.")
        g.addWidget(QLabel("Audio fade-in:"), r, 0)
        g.addWidget(self.fade_in, r, 1)
        r += 1
        self.fade_out = QDoubleSpinBox()
        self.fade_out.setRange(0.0, 30.0); self.fade_out.setDecimals(2)
        self.fade_out.setSingleStep(0.5); self.fade_out.setSuffix(" s")
        self.fade_out.setToolTip(
            "Audio fade-out length at the end of the output. "
            "0 = no fade-out.")
        g.addWidget(QLabel("Audio fade-out:"), r, 0)
        g.addWidget(self.fade_out, r, 1)
        r += 1

        # Split-on-length: cap each output's duration; oversized inputs
        # get cut into Part1, Part2, ...
        self.split_enabled = QCheckBox("Split when longer than:")
        self.split_enabled.setToolTip(
            "When enabled, any input whose post-trim duration exceeds the "
            "limit below is split into multiple parts at export time. "
            "Each part is named '<base>_Part1.mp4', '<base>_Part2.mp4', "
            "etc. (or include {part} / {parts} in the filename pattern "
            "for full control).")
        self.split_max_minutes = QDoubleSpinBox()
        self.split_max_minutes.setRange(0.1, 600.0)
        self.split_max_minutes.setDecimals(2)
        self.split_max_minutes.setSingleStep(1.0)
        self.split_max_minutes.setSuffix(" min")
        self.split_max_minutes.setValue(10.0)
        self.split_max_minutes.setToolTip(
            "Maximum length of each output part, in minutes.")
        g.addWidget(self.split_enabled, r, 0)
        g.addWidget(self.split_max_minutes, r, 1)
        r += 1

        # V12.3: intro / outro merge. Optional clips concatenated at
        # the start and end of the encoded main output via FFmpeg's
        # concat filter (re-encoded to match the profile's output
        # resolution + codec, so the input clips can be any format).
        self.intro_path = QLineEdit()
        self.intro_path.setPlaceholderText("(no intro)")
        self.intro_path.setReadOnly(True)
        self.intro_path.setToolTip(
            "Clip played before the main content. It is re-encoded to "
            "match the output settings, so any format works.")
        intro_browse = QPushButton("📂 Browse...")
        intro_browse.setToolTip("Choose an intro clip.")
        intro_browse.clicked.connect(lambda: self._pick_merge_file(
            self.intro_path, "Select intro video"))
        intro_clear = QPushButton("✕ Clear")
        intro_clear.setToolTip("Remove the intro clip.")
        intro_clear.clicked.connect(lambda: self.intro_path.setText(""))
        intro_row = QHBoxLayout()
        intro_row.addWidget(self.intro_path, 1)
        intro_row.addWidget(intro_browse)
        intro_row.addWidget(intro_clear)
        g.addWidget(QLabel("Intro video:"), r, 0)
        g.addLayout(intro_row, r, 1)
        r += 1

        self.outro_path = QLineEdit()
        self.outro_path.setPlaceholderText("(no outro)")
        self.outro_path.setReadOnly(True)
        self.outro_path.setToolTip(
            "Clip played after the main content. It is re-encoded to "
            "match the output settings, so any format works.")
        outro_browse = QPushButton("📂 Browse...")
        outro_browse.setToolTip("Choose an outro clip.")
        outro_browse.clicked.connect(lambda: self._pick_merge_file(
            self.outro_path, "Select outro video"))
        outro_clear = QPushButton("✕ Clear")
        outro_clear.setToolTip("Remove the outro clip.")
        outro_clear.clicked.connect(lambda: self.outro_path.setText(""))
        outro_row = QHBoxLayout()
        outro_row.addWidget(self.outro_path, 1)
        outro_row.addWidget(outro_browse)
        outro_row.addWidget(outro_clear)
        g.addWidget(QLabel("Outro video:"), r, 0)
        g.addLayout(outro_row, r, 1)
        r += 1

        self.merge_fade = QDoubleSpinBox()
        self.merge_fade.setRange(0.0, 2.0)
        self.merge_fade.setDecimals(2)
        self.merge_fade.setSingleStep(0.05)
        self.merge_fade.setSuffix(" s")
        self.merge_fade.setValue(0.0)
        self.merge_fade.setToolTip(
            "Audio crossfade duration at intro/main and main/outro joins.\n"
            "  Allowed range : 0.00 - 2.00 s\n"
            "  Default       : 0.00 (hard cut)\n\n"
            "Typical values:\n"
            "  0.00         = clean hard cut (no fade)\n"
            "  0.10 - 0.20  = eliminates click without being audible\n"
            "  0.30 - 0.50  = noticeable smooth fade\n"
            "  > 0.50       = stylistic / dramatic transition")
        g.addWidget(QLabel("Merge audio fade:"), r, 0)
        g.addWidget(self.merge_fade, r, 1)
        r += 1
        mf_hint = QLabel(
            "0 = hard cut · 0.10 - 0.20 s = de-click (recommended) · "
            "0.50 s = audible fade"
        )
        mf_hint.setStyleSheet("color:#888; font-size:10px;")
        mf_hint.setWordWrap(True)
        g.addWidget(mf_hint, r, 1)
        r += 1

        # Output filename pattern (replaces the old fixed "suffix" field).
        self.out_pattern = QLineEdit("{name}_edited")
        self.out_pattern.setToolTip(
            "Output filename template. Placeholders:\n"
            "  {name}       source filename without extension\n"
            "  {ext}        source extension (without dot)\n"
            "  {date}       today's date YYYYMMDD\n"
            "  {time}       current time HHMMSS\n"
            "  {codec}      h264 or hevc\n"
            "  {encoder}    libx264 / h264_nvenc / etc.\n"
            "  {quality}    fast / balanced / high_quality\n"
            "  {resolution} 1920x1080 / 3840x2160 / src\n"
            "  {n}          1-based index in the batch\n"
            "  {n:03d}      zero-padded index\n"
            "  {part}       1-based part number when split is on (else 1)\n"
            "  {parts}      total parts for this source (else 1)\n"
            "Examples:\n"
            "  {name}_edited                     -> foo_edited.mp4\n"
            "  {name}_{date}_{codec}             -> foo_20260507_h264.mp4\n"
            "  {date}_{n:03d}_{name}             -> 20260507_001_foo.mp4\n"
            "  {name}_Part{part}of{parts}        -> foo_Part1of3.mp4")
        g.addWidget(QLabel("Filename pattern:"), r, 0)
        g.addWidget(self.out_pattern, r, 1)
        r += 1

        info = QLabel("Output saved next to source. Hover the pattern field "
                      "for placeholders. ``.mp4`` is appended if missing.")
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        g.addWidget(info, r, 0, 1, 2)
        r += 1

        g.setRowStretch(r, 1)
        return w

    def _build_bottom(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(2, 2, 2, 2)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setMinimumWidth(220)
        self.total_eta_lbl = QLabel("")
        self.total_eta_lbl.setProperty("role", "muted")
        self.total_eta_lbl.setToolTip(
            "Estimated time remaining for the whole batch.")
        self.total_eta_lbl.setMinimumWidth(280)
        self.total_eta_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.start_btn = QPushButton("▶ Start Batch")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start_batch)
        # V12.3: pause/resume button. Toggles label between "⏸ Pause"
        # and "▶ Resume" based on the batch's pause state. Disabled
        # when no batch is running.
        self.pause_btn = QPushButton("⏸ Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setToolTip(
            "Pause the batch — anything currently encoding finishes, "
            "but no new jobs start until you Resume.")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.cancel_btn = QPushButton("■ Cancel")
        # V12.3 audit fix: red "danger" styling matches the destructive-
        # action button styling used in the Watch Folder + Profile
        # Manager dialogs, so Cancel reads as the abort path at a glance.
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        h.addWidget(self.status_lbl)
        h.addWidget(self.progress, 1)
        h.addWidget(self.total_eta_lbl)
        h.addWidget(self.start_btn)
        h.addWidget(self.pause_btn)
        h.addWidget(self.cancel_btn)
        return wrap

    def _on_pause_clicked(self):
        """V12.3: toggle the BatchManager between paused and running."""
        if not self.batch:
            return
        if self.batch.is_paused():
            self.batch.resume()
        else:
            self.batch.pause()
        # Button label / status flip in _on_paused_changed below.

    def _on_use_cpu_alongside_gpu_toggled(self, checked: bool):
        """V14.3.0: propagate the checkbox state to the running
        BatchManager (if any). ``set_use_cpu_slot`` accepts the change
        at any time — turning ON opens an extra slot on the next
        dispatch tick; turning OFF stops spawning new CPU jobs but
        lets the in-flight CPU job finish naturally."""
        if self.batch is not None:
            try:
                self.batch.set_use_cpu_slot(bool(checked))
            except Exception as exc:
                log.warning("set_use_cpu_slot failed: %s", exc)
        # Persist immediately so the toggle survives an app crash mid-batch.
        try:
            self.settings.setValue(
                "use_cpu_alongside_gpu", bool(checked))
        except Exception:
            pass

    def _on_paused_changed(self, paused: bool):
        """V12.3: react to BatchManager's pause-state signal."""
        if paused:
            self.pause_btn.setText("▶ Resume")
            self.pause_btn.setToolTip(
                "Resume the batch — start the next pending job.")
            self.status_lbl.setText("⏸ Paused")
        else:
            self.pause_btn.setText("⏸ Pause")
            self.pause_btn.setToolTip(
                "Pause the batch — anything currently encoding finishes, "
                "but no new jobs start until you Resume.")
            # Status text gets re-driven by the next file_started signal.

    def _wire_change_signals(self):
        for w in (self.trim_start, self.trim_end, self.wm_off_x, self.wm_off_y,
                  self.wm_padding, self.text_wm_off_x, self.text_wm_off_y,
                  self.text_wm_padding, self.text_wm_size,
                  self.vid_wm_off_x, self.vid_wm_off_y, self.vid_wm_padding):
            w.valueChanged.connect(self._schedule_preview)
        for w in (self.wm_opacity, self.wm_scale, self.text_wm_opacity,
                  self.vid_wm_opacity, self.vid_wm_scale):
            w.valueChanged.connect(self._schedule_preview)
        self.wm_preset.currentTextChanged.connect(self._schedule_preview)
        self.text_wm_preset.currentTextChanged.connect(self._schedule_preview)
        self.vid_wm_preset.currentTextChanged.connect(self._schedule_preview)
        self.wm_path.textChanged.connect(self._schedule_preview)
        self.text_wm_text.textChanged.connect(self._schedule_preview)
        self.vid_wm_path.textChanged.connect(self._schedule_preview)
        self.out_res.currentTextChanged.connect(self._schedule_preview)
        self.trim_start.valueChanged.connect(self._sync_seek_bar_trim)
        self.trim_end.valueChanged.connect(self._sync_seek_bar_trim)
        self.trim_start.valueChanged.connect(self._update_trim_info)
        self.trim_end.valueChanged.connect(self._update_trim_info)
        # Keep the source -> output one-liner in sync with the Output tab.
        self.out_codec.currentIndexChanged.connect(self._update_preview_info)
        self.out_encoder.currentIndexChanged.connect(self._update_preview_info)
        self.out_res.currentTextChanged.connect(self._update_preview_info)
        self.speed_value.valueChanged.connect(self._update_preview_info)
        self.loudnorm.toggled.connect(self._update_preview_info)
        self.force_stereo.toggled.connect(self._update_preview_info)
        # V12.3.1: video bitrate depends on (tier, resolution) — refresh
        # the hint label whenever resolution changes too.
        self.out_res.currentTextChanged.connect(self._refresh_video_quality_hint)
        # Initial hint paint.
        self._refresh_video_quality_hint()
        self._refresh_audio_quality_hint()

    def _build_tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.app_icon, self)
            self.tray.setToolTip(f"Veloxa Video Editor V{VELOXA_APP_VERSION}")
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

    def _on_tray_activated(self, reason):
        """Single-click or double-click on the tray icon brings the window
        back to the foreground (useful when the user has minimized it
        during a long batch and just wants a quick check)."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isMinimized():
                self.showNormal()
            else:
                self.show()
            self.raise_()
            self.activateWindow()

    def _install_shortcuts(self):
        """Window-level keyboard shortcuts. Each gets a one-line tooltip
        added to its companion button when one exists."""
        def sc(seq, slot, context=Qt.ShortcutContext.WindowShortcut):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(context)
            s.activated.connect(slot)
            return s

        sc(QKeySequence.StandardKey.Open, self._on_add_clicked)
        sc("Ctrl+Return", self._start_batch)
        sc("Ctrl+Enter", self._start_batch)
        sc("Esc", self._on_esc)
        sc(QKeySequence.StandardKey.Save, self._save_or_update_profile)
        sc("Ctrl+Shift+S", self._save_as_profile)
        sc("Ctrl+M", self._open_profile_manager)
        sc("F1", self._show_help)
        # Delete key removes selection from the queue when it has focus.
        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.file_list)
        del_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        del_sc.activated.connect(self._remove_selected)

        # V14.10.0: profile shortcut numbers. With queue rows selected,
        # typing a profile's sticky number assigns that profile to every
        # selected row. Digits accumulate in a short buffer so numbers
        # above 9 work: '1' waits ~700 ms in case '12' is coming; the
        # buffer applies immediately when no higher number could still
        # match. Scoped to the queue list so typing in text fields is
        # never hijacked.
        self._digit_buffer = ""
        self._digit_timer = QTimer(self)
        self._digit_timer.setSingleShot(True)
        self._digit_timer.setInterval(700)
        self._digit_timer.timeout.connect(self._apply_digit_buffer)
        for _d in "0123456789":
            ds = QShortcut(QKeySequence(_d), self.file_list)
            ds.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            ds.activated.connect(
                lambda dd=_d: self._on_profile_digit(dd))

        # Surface the new bindings on the most-used buttons.
        self.add_btn.setToolTip("Add files to the queue (Ctrl+O)")
        self.remove_btn.setToolTip("Remove selected items (Delete)")
        self.start_btn.setToolTip("Start the batch (Ctrl+Enter)")
        self.cancel_btn.setToolTip("Cancel the running batch (Esc)")

    def _on_esc(self):
        """Esc cancels a running batch; otherwise no-op so it doesn't
        interfere with normal widget Esc handling."""
        if self.batch and self.batch.is_running():
            self._cancel_batch()

    # ---------------------------------- V14.10.0 profile digit shortcut

    def _on_profile_digit(self, digit: str):
        """A digit was typed while the queue list had focus: accumulate
        it toward a profile shortcut number. Applies immediately when no
        longer number could still match (e.g. '4' with no #40+); else
        waits out the 700 ms timer so multi-digit numbers ('12') land."""
        if self._queue_locked:
            self.status_lbl.setText(
                "Profiles can't be changed while a batch is running.")
            return
        self._digit_buffer += digit
        buf = self._digit_buffer
        numbers = {str(self._profile_number(n))
                   for n in self.profiles
                   if self._profile_number(n) is not None}
        extendable = any(s.startswith(buf) and s != buf for s in numbers)
        if extendable:
            self.status_lbl.setText(
                f"Profile #{buf}… (keep typing, or pause to apply)")
            self._digit_timer.start()
        else:
            self._digit_timer.stop()
            self._apply_digit_buffer()

    def _apply_digit_buffer(self):
        buf, self._digit_buffer = self._digit_buffer, ""
        if not buf:
            return
        try:
            n = int(buf)
        except ValueError:
            return
        name = self._profile_by_number(n)
        if not name:
            self.status_lbl.setText(f"No profile has shortcut number {n}.")
            return
        items = self.file_list.selectedItems()
        if not items:
            self.status_lbl.setText(
                f"Select queue rows first, then type {n} to apply "
                f"'{name}'.")
            return
        self._apply_profile_to_items(items, name)
        self.status_lbl.setText(
            f"Profile #{n} '{name}' applied to {len(items)} item(s).")

    def _save_or_update_profile(self):
        """Ctrl+S: update the loaded profile if any, otherwise Save As."""
        name = self.profile_combo.currentText()
        if name != NO_PROFILE and name in self.profiles:
            self._update_current_profile()
        else:
            self._save_as_profile()

    def _build_menu_bar(self):
        """V14.4.0: menu items are now grouped into proper submenus
        (Tools / Help / Appearance). The previous V13–V14.3 layout
        called ``mb.addAction()`` directly on the menu bar, which works
        on Windows (flat action items render in the menubar) but NOT
        on macOS — the macOS native menubar expects every top-level
        entry to be a *menu*, not a flat action, and silently drops the
        ones that aren't. That left macOS users with ONLY the
        ``Appearance`` menu visible (the only one we used ``addMenu()``
        for) and no way to reach ``Check for Updates…``, the help
        docs, the log folder, or the watch-folder dialog.
        """
        mb = self.menuBar()

        # --- Tools menu (dialogs that operate on the app / queue) ---
        # Tooltip audit: QMenu does NOT show QAction tooltips unless
        # setToolTipsVisible(True) — same for Help / Appearance below.
        tools = mb.addMenu("Tools")
        tools.setToolTipsVisible(True)
        for label, slot, tip in [
            ("Watch Folder…", self._open_watch_dialog,
             "Automatically add files that appear in a chosen folder "
             "to the queue."),
            ("Manage Saved Data…", self._open_manage_data_dialog,
             "View and clear saved profiles, settings, and app data."),
            ("Open Log Folder", self._open_log_folder,
             "Open the folder containing Veloxa's log files."),
            # V14.4.1: force a fresh GPU-encoder probe.
            ("Re-detect GPU encoders…",
             self._redetect_gpu_encoders,
             "Clear the cached probe and re-detect which hardware "
             "encoders work on this PC (use after a driver update)."),
            # V14.5.0: opt-in crash reporter. "Report a problem" lets the
            # user file a GitHub Issue manually with the current log;
            # "Crash reporting settings" lets them toggle the opt-in.
            ("Report a problem…",
             self._report_a_problem_manual,
             "Open a pre-filled GitHub issue report in your browser, "
             "with the current log attached."),
            ("Crash reporting settings…",
             self._crash_reporting_settings,
             "Choose whether crash reports may be offered for sending "
             "after an error."),
        ]:
            act = QAction(label, self)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.setToolTip(tip)
            act.triggered.connect(slot)
            tools.addAction(act)

        # --- Help menu (docs + update check) ---
        help_menu = mb.addMenu("Help")
        help_menu.setToolTipsVisible(True)
        for label, slot, tip in [
            ("README", self._show_readme,
             "Overview of the app and its features."),
            ("Installation Guide", self._show_install_guide,
             "How to install, update, and uninstall on Windows and "
             "macOS."),
            ("User Guide", self._show_help,
             "Detailed help for every feature (F1)."),
            ("License", self._show_license,
             "View the software license."),
            # V14.8.0: lets the user re-run the first-launch tour any
            # time — useful when they brushed it off the first time
            # without reading.
            ("Show Onboarding Tour", self._run_onboarding_tour,
             "Replay the three-step introduction tour."),
        ]:
            act = QAction(label, self)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.setToolTip(tip)
            act.triggered.connect(slot)
            help_menu.addAction(act)
        help_menu.addSeparator()
        # V14.4.0: ``Check for Updates…`` — explicitly NoRole so Qt's
        # ``TextHeuristicRole`` doesn't auto-move it to the macOS Apple
        # menu (where the user can't find it). Stays in Help on both
        # platforms now.
        check_updates_act = QAction("Check for Updates…", self)
        check_updates_act.setMenuRole(QAction.MenuRole.NoRole)
        check_updates_act.setToolTip(
            "Check GitHub for a newer version and install it from "
            "inside the app.")
        check_updates_act.triggered.connect(self._check_for_updates_manual)
        help_menu.addAction(check_updates_act)

        # --- Appearance menu (theme picker) ---
        # V13.1: System / Light / Dark / OLED — wrapped in a
        # QActionGroup so the choices behave as mutually-exclusive
        # radio items. Default reads from QSettings (falls back to
        # "system" when no choice has been persisted yet).
        appearance = mb.addMenu("Appearance")
        appearance.setToolTipsVisible(True)
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_mode = self.settings.value("theme_mode", THEME_SYSTEM)
        if current_mode not in THEME_MODES:
            current_mode = THEME_SYSTEM
        for mode, label, tip in [
            (THEME_SYSTEM, "System (follow OS)",
             "Match the operating system's light / dark preference "
             "automatically."),
            (THEME_LIGHT,  "Light",
             "Always use the light theme."),
            (THEME_DARK,   "Dark",
             "Always use the dark theme."),
            (THEME_OLED,   "OLED Dark (pure black)",
             "Dark theme with a pure-black background — saves power "
             "on OLED displays."),
        ]:
            act = QAction(label, self, checkable=True)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.setToolTip(tip)
            act.setData(mode)
            act.setChecked(mode == current_mode)
            act.triggered.connect(
                lambda _checked=False, m=mode: self._set_theme_mode(m))
            self._theme_group.addAction(act)
            appearance.addAction(act)

    # ====================================================== V14.0 playback

    def _mp_current_src(self) -> str:
        """V14.0: source file of the currently-selected queue row, or
        ``""`` if nothing is selected."""
        d, _ = self._current_video()
        if not d or not d.src:
            return ""
        return d.src

    def _mp_load_if_needed(self) -> bool:
        if not self._mp_available:
            return False
        src = self._mp_current_src()
        if not src or not os.path.exists(src):
            return False
        if src == self._mp_loaded_src:
            return True
        from PyQt6.QtCore import QUrl
        self._mp_player.setSource(QUrl.fromLocalFile(src))
        self._mp_loaded_src = src
        # Resize the video widget to cover the preview frame each load.
        self._mp_resize_video_widget()
        return True

    def _mp_resize_video_widget(self):
        if not self._mp_video_widget:
            return
        margin = 4
        w = self.preview_frame.width() - 2 * margin
        h = self.preview_frame.height() - 2 * margin
        self._mp_video_widget.setGeometry(margin, margin, max(0, w), max(0, h))

    def _mp_play(self):
        if not self._mp_load_if_needed():
            self.status_lbl.setText(
                "Select a queue row with a valid source file to play.")
            return
        # Show the video widget over the static thumbnail.
        if self._mp_video_widget:
            self._mp_resize_video_widget()
            self._mp_video_widget.show()
            self._mp_video_widget.raise_()
            self.preview_overlay.raise_()
        self._mp_player.play()

    def _mp_pause(self):
        if self._mp_player:
            self._mp_player.pause()

    def _mp_stop(self):
        if self._mp_player:
            self._mp_player.stop()
        if self._mp_video_widget:
            self._mp_video_widget.hide()

    def _mp_set_volume(self, v: int):
        if self._mp_audio_out:
            self._mp_audio_out.setVolume(max(0.0, min(1.0, v / 100.0)))

    def _mp_on_position(self, pos_ms: int):
        dur = self._mp_player.duration() if self._mp_player else 0
        if dur > 0:
            self.mp_pos_lbl.setText(
                f"{fmt_time(pos_ms / 1000.0)} / {fmt_time(dur / 1000.0)}")
        else:
            self.mp_pos_lbl.setText(fmt_time(pos_ms / 1000.0))

    def _mp_on_duration(self, dur_ms: int):
        if dur_ms > 0:
            self.mp_pos_lbl.setText(
                f"00:00.00 / {fmt_time(dur_ms / 1000.0)}")

    def _mp_on_playback_state(self, state):
        # When playback ends naturally (StoppedState after EOF), hide the
        # video widget so the static thumbnail is visible again.
        try:
            from PyQt6.QtMultimedia import QMediaPlayer
            if state == QMediaPlayer.PlaybackState.StoppedState:
                if self._mp_video_widget and self._mp_player.position() >= max(
                        0, self._mp_player.duration() - 200):
                    self._mp_video_widget.hide()
        except Exception:
            pass

    # ====================================================== V13.1 theme

    def _set_theme_mode(self, mode: str):
        """Apply ``mode`` (one of THEME_SYSTEM/LIGHT/DARK) to the running
        QApplication and persist the choice. Triggered from the
        Appearance submenu."""
        if mode not in THEME_MODES:
            mode = THEME_SYSTEM
        app = QApplication.instance()
        if app is None:
            return
        apply_theme(app, mode)
        self.settings.setValue("theme_mode", mode)
        resolved = resolve_theme_mode(mode)
        if mode == THEME_SYSTEM:
            label = f"System ({resolved})"
        else:
            label = mode.capitalize()
        self.status_lbl.setText(f"Theme: {label}")

    # ====================================================== V13.0 auto-update

    def _maybe_check_for_updates_on_startup(self):
        """Fire a non-manual update check iff the user has opt-in on.
        Default is ON (the user picked that at install time). Silent if
        no update; silent on every error condition. Called once shortly
        after the main window shows so initial paint stays snappy.
        """
        if not VELOXA_GITHUB_REPO:
            # No repo configured at build time — feature disabled.
            return
        enabled = self.settings.value("auto_update_check", True)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")
        if not bool(enabled):
            return
        self._start_update_check(manual=False)

    def _check_for_updates_manual(self):
        """Menu entry. Always queries even if startup-check is disabled.
        Surfaces "you're up to date" / "couldn't reach GitHub" feedback
        so the user knows the click did something."""
        if not VELOXA_GITHUB_REPO:
            QMessageBox.information(
                self, "Updates not configured",
                "<b>Auto-update is not configured in this build.</b><br><br>"
                "The GitHub repository slug is empty in "
                "<code>app/updater.py::GITHUB_REPO</code>. Set it to "
                "<code>owner/repo</code> and rebuild to enable update "
                "checks.")
            return
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool):
        # V13.0.1 crash-fix: ``isRunning()`` on a wrapped-but-deleted
        # C++ QThread is a hard crash with no Python traceback. The
        # previous startup-check connected ``finished -> deleteLater``,
        # which destroys the C++ object but leaves ``self._update_checker``
        # pointing at the corpse. The next call (e.g. the user clicking
        # the menu) hit this line and crashed. Test+drop the stale ref
        # safely via the ``RuntimeError`` PyQt6 raises in that case.
        if self._update_checker is not None:
            try:
                still_running = self._update_checker.isRunning()
            except RuntimeError:
                # C++ object already deleted — drop the stale ref.
                still_running = False
                self._update_checker = None
            if still_running:
                if manual:
                    self.status_lbl.setText(
                        "Update check already in progress...")
                return
        if manual:
            self.status_lbl.setText("Checking for updates...")
        c = UpdateChecker(
            github_repo=VELOXA_GITHUB_REPO,
            local_version=VELOXA_APP_VERSION,
            manual=manual,
            parent=self,
        )
        c.found_update.connect(self._on_update_found)
        c.no_update.connect(self._on_no_update)
        # Order matters: clear the Python ref BEFORE asking Qt to delete
        # the C++ object, so any future _start_update_check call sees
        # ``self._update_checker is None`` and creates a fresh thread
        # rather than touching a dangling pointer.
        c.finished.connect(self._on_update_checker_finished)
        c.finished.connect(c.deleteLater)
        self._update_checker = c
        c.start()

    def _on_update_checker_finished(self):
        """V13.0.1: drop the Python reference to the QThread the moment
        it finishes, so a subsequent ``_start_update_check`` can't see a
        stale wrapper for a deleted C++ object."""
        self._update_checker = None

    def _on_no_update(self, manual: bool):
        if not manual:
            return  # silent on auto-check
        # V14.8.0: include an "Open Release Page" button so the user can
        # still browse the latest release notes / re-download even when
        # they're already current. Useful when they suspect their
        # current install is broken and want to reinstall.
        releases_url = f"https://github.com/{VELOXA_GITHUB_REPO}/releases"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Veloxa Video Editor")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            f"<b>You're up to date.</b><br><br>"
            f"Current version: <b>V{VELOXA_APP_VERSION}</b><br>"
            f"No newer release found at GitHub.<br><br>"
            f"Release page (all versions): <br>"
            f"<a href='{releases_url}'>{releases_url}</a><br><br>"
            f"<i>(If the check failed silently — offline, rate-limited, "
            f"private repo — this message looks the same as 'up to "
            f"date'. The Open Log Folder menu has the details.)</i>")
        ok_btn = msg.addButton(QMessageBox.StandardButton.Ok)
        open_btn = msg.addButton(
            "Open Release Page", QMessageBox.ButtonRole.AcceptRole)
        msg.setDefaultButton(ok_btn)
        msg.exec()
        if msg.clickedButton() is open_btn:
            self._open_url_in_browser(releases_url)
        self.status_lbl.setText("")

    # ============================================================ V14.8.0 helpers

    def _open_url_in_browser(self, url: str) -> bool:
        """V14.8.0: open ``url`` in the user's default browser. Safe to
        call from anywhere — never raises. Returns True on success.
        """
        if not url:
            return False
        try:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            return bool(QDesktopServices.openUrl(QUrl(url)))
        except Exception as exc:
            log.warning("Could not open browser to %s: %s", url, exc)
            return False

    def _open_update_in_browser(self, info):
        """V14.8.0: "Download in Browser" fallback. Opens the asset URL
        directly so the user's browser handles the transfer (with its
        own resume + retry behaviour). If asset_url isn't available,
        falls back to the release page so the user can grab whichever
        artefact they need."""
        url = (getattr(info, "asset_url", "") or info.html_url
               or f"https://github.com/{VELOXA_GITHUB_REPO}/releases/latest")
        if not self._open_url_in_browser(url):
            QMessageBox.information(
                self, "Open in browser",
                "Could not launch your browser automatically.\n\n"
                f"Direct download URL:\n{url}")
        else:
            self.status_lbl.setText(
                f"Opened V{info.version} download in your browser.")

    def _show_download_failed_dialog(self, info):
        """V14.8.0: replaces the V14.0.x plain-text "download failed"
        warning with an actionable dialog that has explicit
        Retry / Open Release Page / Direct Download Link / Cancel
        buttons. Shown after a stall (V14.6.0 user report) or any
        other download error — the URL is always one click away.
        """
        releases_url = (info.html_url
                        or f"https://github.com/{VELOXA_GITHUB_REPO}/releases")
        asset_url = getattr(info, "asset_url", "") or ""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Download failed")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            f"<b>V{info.version} could not be downloaded inside the app.</b>"
            f"<br><br>"
            f"This is usually a transient network or antivirus issue. "
            f"You can retry, or download the installer from your "
            f"browser instead — same file, same SHA.<br><br>"
            f"Release page (recommended):<br>"
            f"<a href='{releases_url}'>{releases_url}</a>"
            + (f"<br><br>Direct installer link:<br>"
               f"<a href='{asset_url}'>{asset_url}</a>"
               if asset_url else ""))
        retry_btn = msg.addButton(
            "Retry Download", QMessageBox.ButtonRole.AcceptRole)
        open_release_btn = msg.addButton(
            "Open Release Page", QMessageBox.ButtonRole.AcceptRole)
        direct_btn = None
        if asset_url:
            direct_btn = msg.addButton(
                "Direct Installer Link", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(open_release_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is retry_btn:
            self._run_update_install(info)
        elif clicked is open_release_btn:
            self._open_url_in_browser(releases_url)
        elif direct_btn is not None and clicked is direct_btn:
            self._open_url_in_browser(asset_url)

    def _on_update_found(self, info: UpdateInfo, manual: bool):
        # If the user previously chose "Skip this version" for THIS exact
        # version, suppress the auto-prompt. Manual checks always show.
        skipped = (self.settings.value("update_skip_version", "") or "").strip()
        if not manual and skipped and skipped == info.version:
            return
        self.status_lbl.setText("")
        self._show_update_available_dialog(info)

    def _show_update_available_dialog(self, info: UpdateInfo):
        """Modal dialog: Download & Install / Remind Me Later / Skip This
        Version. Also has a checkbox letting the user disable startup
        auto-checks — the most discoverable place to find it."""
        # Use rich text so release notes (markdown) render reasonably.
        # We render markdown as plain text since QMessageBox doesn't
        # do markdown — but newlines + simple lists are readable.
        notes = (info.body or "").strip()
        if len(notes) > 1600:
            notes = notes[:1600] + "\n\n[... see GitHub for full release notes]"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Update available")
        msg.setTextFormat(Qt.TextFormat.RichText)
        size_mb = (info.asset_size / 1_048_576) if info.asset_size else 0
        size_str = f" ({size_mb:.1f} MB)" if size_mb else ""
        msg.setText(
            f"<b>A new version of Veloxa Video Editor is available.</b>"
            f"<br><br>"
            f"Current: <b>V{VELOXA_APP_VERSION}</b><br>"
            f"Available: <b>V{info.version}</b>{size_str}<br><br>"
            f"<a href='{info.html_url}'>View release on GitHub</a>"
        )
        if notes:
            msg.setDetailedText(notes)

        download_btn = msg.addButton(
            "Download && Install", QMessageBox.ButtonRole.AcceptRole)
        # V14.8.0: explicit "Download in Browser" fallback for users
        # whose in-app download stalls (the V14.6.0 bug report —
        # corporate AV or aggressive CDN routing leaves the socket
        # open but silent). Opens the asset URL directly so the user's
        # browser handles the transfer, with all of its own resume +
        # retry behaviour.
        browser_btn = msg.addButton(
            "Download in Browser", QMessageBox.ButtonRole.AcceptRole)
        later_btn = msg.addButton(
            "Remind Me Later", QMessageBox.ButtonRole.RejectRole)
        skip_btn = msg.addButton(
            "Skip This Version", QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(download_btn)

        # Inline "auto-check on startup" toggle — the most visible place
        # to flip it without burying it in a Preferences dialog.
        auto = self.settings.value("auto_update_check", True)
        if isinstance(auto, str):
            auto = auto.lower() in ("true", "1", "yes")
        cb = QCheckBox("Check for updates on startup")
        cb.setChecked(bool(auto))
        msg.setCheckBox(cb)

        msg.exec()
        # Persist the auto-check choice regardless of which button was
        # clicked.
        self.settings.setValue("auto_update_check", bool(cb.isChecked()))

        clicked = msg.clickedButton()
        if clicked is download_btn:
            self._run_update_install(info)
        elif clicked is browser_btn:
            self._open_update_in_browser(info)
        elif clicked is skip_btn:
            self.settings.setValue("update_skip_version", info.version)
            self.status_lbl.setText(
                f"V{info.version} will not be offered again on startup.")
        # "Remind Me Later" = no-op (we'll re-prompt next launch).

    def _run_update_install(self, info: UpdateInfo):
        """V14.0.1: download the installer on a background QThread so
        the GUI stays responsive, then quit + launch the installer
        (which upgrades in-place via the stable AppId).

        Previous implementation ran the download synchronously on the
        GUI thread and pumped ``QApplication.processEvents()`` after
        every 64 KB chunk — that's both slow (6,300 event-loop spins
        for a 395 MB installer) and freezes the rest of the UI."""
        # If a batch is encoding, warn — the installer will lose progress.
        if self.batch and self.batch.is_running():
            r = QMessageBox.question(
                self, "Batch Running",
                "A batch is currently encoding. The installer will need "
                "to close the app and your in-progress jobs will be "
                "cancelled.<br><br>"
                "Continue with the update anyway?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return

        # Progress dialog. Tracks bytes / percent / transfer rate.
        prog = QProgressDialog(
            "Connecting...", "Cancel", 0, 1000, self)
        prog.setWindowTitle(f"Downloading V{info.version}")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        prog.show()

        worker = DownloadWorker(info, parent=self)
        self._update_dl_worker = worker  # keep a ref so it isn't GC'd

        def _on_progress(done: int, total: int, rate_bps: float):
            mb_done = done / 1_048_576
            rate_mbps = rate_bps / 1_048_576
            if total > 0:
                # 0..1000 range gives ~0.1% granularity in the bar so
                # users see movement even on the first MB.
                pct_x10 = int(done * 1000 / total)
                prog.setMaximum(1000)
                prog.setValue(min(1000, max(0, pct_x10)))
                mb_total = total / 1_048_576
                prog.setLabelText(
                    f"Downloading update... {mb_done:.1f} / "
                    f"{mb_total:.1f} MB  ·  {rate_mbps:.1f} MB/s")
            else:
                prog.setMaximum(0)  # indeterminate
                prog.setLabelText(
                    f"Downloading update... {mb_done:.1f} MB  ·  "
                    f"{rate_mbps:.1f} MB/s")

        def _on_finished(path: str, ok: bool):
            prog.close()
            self._update_dl_worker = None
            if not ok or not path:
                if prog.wasCanceled():
                    self.status_lbl.setText("Update cancelled.")
                else:
                    # V14.8.0: rather than just printing the URL, offer
                    # explicit "Open Release Page" / "Direct Download
                    # Link" buttons so the user can fall back to their
                    # browser. Default to the release page since that
                    # lets them see release notes + every asset.
                    self._show_download_failed_dialog(info)
                return

            self._update_temp_path = path
            log.info("Update installer downloaded to %s", path)
            # Confirm before quitting + launching the installer.
            r = QMessageBox.question(
                self, "Install update",
                f"<b>V{info.version} is ready to install.</b><br><br>"
                f"The app will close and the installer will launch. "
                f"Your settings, profiles, and queue state will be "
                f"preserved.",
                QMessageBox.StandardButton.Ok
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Ok)
            if r != QMessageBox.StandardButton.Ok:
                return
            launched = launch_installer_and_quit(
                path,
                quit_callback=lambda: QApplication.instance().quit())
            if not launched:
                QMessageBox.warning(
                    self, "Could not launch installer",
                    "<b>The installer downloaded but could not be "
                    "launched.</b><br><br>"
                    f"You can run it manually:<br><code>{path}</code>")

        # Wire signals; cancel button on the QProgressDialog flips the
        # worker's cancel flag (the worker polls it between chunks).
        worker.progress.connect(_on_progress)
        worker.finished_with_path.connect(_on_finished)
        worker.finished.connect(worker.deleteLater)
        prog.canceled.connect(worker.cancel)
        worker.start()

    # ====================================================== watch folder dialog

    def _open_watch_dialog(self):
        WatchFolderDialog(self).exec()

    def _open_manage_data_dialog(self):
        ManageSavedDataDialog(self).exec()
        # Reload profiles in case the dialog blanked any orphaned asset
        # paths so the live form reflects the change.
        cur = self.profile_combo.currentText()
        if cur != NO_PROFILE and cur in self.profiles:
            self._apply_settings_dict(self.profiles[cur])

    # ====================================================== watch folder

    def _start_watch(self, folder: str, done_subfolder: str):
        if self._watcher is not None:
            self._stop_watch()
        self._watch_done_subfolder = done_subfolder
        self._watch_processed = 0
        self._watcher = FolderWatcher(folder, ALL_INPUT_EXTS)
        self._watcher.file_ready.connect(self._on_watch_file_ready)
        self.status_lbl.setText(f"Watching: {folder}")
        log.info("Watch start: %s (done -> %s)", folder, done_subfolder)

    def _stop_watch(self):
        if self._watcher is None:
            return
        try:
            self._watcher.stop()
        except Exception:
            pass
        self._watcher = None
        self._watch_buffer.clear()
        self.status_lbl.setText("Watch stopped")
        log.info("Watch stop")

    def _on_watch_file_ready(self, path: str):
        """A file in the watched folder is fully written and ready to encode.
        Buffer it, then drain when the queue isn't locked."""
        self._watch_buffer.append(path)
        self._drain_watch_buffer()

    def _drain_watch_buffer(self):
        if self._queue_locked or not self._watch_buffer:
            return
        paths = self._watch_buffer
        self._watch_buffer = []
        self._add_files(paths)
        # Auto-start the batch if we're idle.
        if not self.batch or not self.batch.is_running():
            self._start_batch()

    def _move_watched_done_files(self):
        """After a batch, move any successfully-encoded sources that came
        from the watch folder into its ``done/`` subfolder so they don't
        get re-detected on next watch sweep."""
        if not self._watcher:
            return
        watch_root = Path(self._watcher.folder)
        target_dir = watch_root / self._watch_done_subfolder
        try:
            target_dir.mkdir(exist_ok=True)
        except OSError as exc:
            log.warning("Could not make watch done dir: %s", exc)
            return
        moved = 0
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if not d or d.status != "done":
                continue
            sp = Path(d.src)
            if sp.parent != watch_root:
                continue
            try:
                target = target_dir / sp.name
                # If a file with that name already exists in done, append
                # a numeric suffix so we don't clobber a previous run.
                if target.exists():
                    n = 2
                    while True:
                        cand = target_dir / f"{sp.stem}_{n}{sp.suffix}"
                        if not cand.exists():
                            target = cand
                            break
                        n += 1
                sp.rename(target)
                moved += 1
            except OSError as exc:
                log.warning("Could not move %s -> done: %s", sp, exc)
        if moved:
            self._watch_processed += moved
            log.info("Watch: moved %d source(s) to %s", moved, target_dir)

    def _open_profile_manager(self):
        ProfileManagerDialog(self).exec()
        # Profiles may have been deleted/renamed in the dialog; reflect
        # that on the header button.
        self._update_profile_button_state()

    def _update_profile_button_state(self):
        name = self.profile_combo.currentText()
        loaded = name != NO_PROFILE and name in self.profiles
        self.update_profile_btn.setEnabled(loaded)

    def _update_current_profile(self):
        name = self.profile_combo.currentText()
        if name == NO_PROFILE or name not in self.profiles:
            return
        r = QMessageBox.question(
            self, "Update Profile",
            f"Overwrite profile '{name}' with the current settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        # Copy any referenced image / video watermark files into the
        # profile's in-app asset folder so the profile keeps working even
        # if the originals get moved or deleted (V11.1).
        d = self._collect_settings_dict()
        d = copy_assets_into_profile(name, d)
        self._store_profile(name, d)
        self._save_profiles()
        # UI-fix: invalidate the per-batch row-opts cache so the next
        # Start picks up the newly-updated profile, and re-paint the
        # per-row combos in case a watermark / visual rename rewrote
        # paths shown in tooltips.
        self._row_opts_cache = {}
        try:
            self._refresh_all_row_widgets()
        except Exception:
            pass
        self.status_lbl.setText(f"Updated profile: {name}")
        log.info("Profile updated: %s", name)

    # ====================================================== help dialogs

    def _show_readme(self):
        show_info_dialog(self, "README", README_HTML)

    def _show_install_guide(self):
        show_info_dialog(self, "Installation Guide", INSTALL_HTML)

    def _show_help(self):
        show_info_dialog(self, "Help", HELP_HTML)

    def _show_license(self):
        show_info_dialog(self, "License", LICENSE_HTML)

    def _open_log_folder(self):
        # V14.2.0: cross-platform via platform_compat.
        from .platform_compat import open_in_file_manager
        open_in_file_manager(log_dir())

    # ====================================================== queue

    def _on_add_clicked(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Videos and / or Audio",
            self.settings.value("last_dir", ""),
            "All supported (videos + audio) "
            "(*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v *.mpg *.mpeg "
            "*.ts *.3gp *.mp3 *.wav *.m4a *.flac *.aac *.ogg *.opus *.wma);;"
            "Videos only (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v "
            "*.mpg *.mpeg *.ts *.3gp);;"
            "Audio only (*.mp3 *.wav *.m4a *.flac *.aac *.ogg *.opus *.wma);;"
            "All Files (*.*)")
        if files:
            self.settings.setValue("last_dir", str(Path(files[0]).parent))
            self._add_files(files)

    def _on_add_folder_clicked(self):
        """V14.6.0: pick a folder and bulk-add every supported file in
        it AND every subfolder. Walks via ``os.walk`` so deeply-nested
        media libraries (Audiobook / Podcast / Season / Episode trees)
        come in with one click. Filtering uses ``ALL_INPUT_EXTS`` so
        random sidecar files (``.srt``, ``.jpg`` artwork, ``.txt``
        notes, etc.) are ignored. The collected paths flow through
        ``_add_files`` so existing dedup, audio-visual auto-assign
        (V14.3.5), mid-batch ``add_jobs()`` (V14.3.0), and the queue
        persistence all work without changes.
        """
        start_dir = (self.settings.value("last_folder_add_dir", "")
                     or self.settings.value("last_dir", ""))
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder (subfolders included)", start_dir)
        if not folder:
            return
        self.settings.setValue("last_folder_add_dir", folder)
        # Show a "scanning…" status so a large tree doesn't look frozen.
        self.status_lbl.setText(
            f"Scanning {folder} for supported files…")
        QApplication.processEvents()
        try:
            collected = self._collect_supported_files(folder)
        except Exception as exc:
            log.warning("Folder scan failed for %s: %s", folder, exc)
            QMessageBox.warning(
                self, "Add from Folder",
                f"Could not read the folder:\n\n{exc}")
            self.status_lbl.setText("Folder scan failed.")
            return
        if not collected:
            QMessageBox.information(
                self, "Add from Folder",
                f"No supported video or audio files found in:\n\n"
                f"{folder}\n\n"
                f"Supported extensions: "
                f"{', '.join(sorted(ALL_INPUT_EXTS))}")
            self.status_lbl.setText("No supported files in folder.")
            return
        log.info("Folder scan of %s found %d supported file(s)",
                 folder, len(collected))

        # V14.9.0: multi-format picker. When the scan turns up more than
        # one unique extension (e.g. .mp4 + .mov + .mkv + .mp3), show a
        # checklist so the user can trim the import down to just the
        # formats they actually want. Optionally lets them PERMANENTLY
        # delete every non-chosen file from the folder tree — same
        # feature you get on a memory-card offloader when you want to
        # keep only the H.264 masters and dump the RAW / audio dupes.
        unique_exts = sorted({Path(p).suffix.lower() for p in collected})
        if len(unique_exts) > 1:
            chosen, delete_others = self._prompt_folder_format_picker(
                folder, collected, unique_exts)
            if chosen is None:
                # User cancelled the picker.
                self.status_lbl.setText("Folder import cancelled.")
                return
            if not chosen:
                # User unticked everything → nothing to import.
                self.status_lbl.setText(
                    "Folder import: no formats selected.")
                return
            chosen_set = {e.lower() for e in chosen}
            filtered = [p for p in collected
                        if Path(p).suffix.lower() in chosen_set]
            if delete_others:
                # NUCLEAR scope per user answer: delete every file in
                # the folder tree that isn't the chosen format(s),
                # including sidecar / non-media files. Confirmed once
                # more here with a scary explicit dialog.
                ok, n_deleted = self._delete_non_chosen_from_folder(
                    folder, chosen_set)
                if not ok:
                    # User backed out at the confirm step. Continue
                    # with the import anyway — we already have the
                    # filtered list.
                    log.info("Folder import: delete step cancelled; "
                             "proceeding with import only")
                else:
                    log.info("Folder import: permanently deleted %d "
                             "non-chosen file(s)", n_deleted)
            collected = filtered
            if not collected:
                self.status_lbl.setText(
                    "Folder import: no files matched the chosen "
                    "format(s).")
                return

        self.status_lbl.setText(
            f"Adding {len(collected)} file(s) from folder…")
        QApplication.processEvents()
        self._add_files(collected)

    def _prompt_folder_format_picker(self, folder: str,
                                     collected: list,
                                     unique_exts: list):
        """V14.9.0: dialog for the multi-format Add-from-Folder flow.

        Returns ``(chosen_extensions, delete_others)`` where:

        * ``chosen_extensions`` is a list of extension strings
          (``.mp4`` etc.) — every ext the user ticked. Empty list
          means "user unticked everything"; ``None`` means "user
          hit Cancel / closed the dialog".
        * ``delete_others`` is True iff the user ticked the "delete
          all other files" box AND accepted the confirm dialog. The
          confirm is fired inside this method so the caller can act
          on a clean boolean.
        """
        # Count how many files carry each extension so the checkbox
        # labels are informative ("mp4 (23 files)").
        counts: dict = {}
        for p in collected:
            e = Path(p).suffix.lower()
            counts[e] = counts.get(e, 0) + 1

        dlg = QDialog(self)
        dlg.setWindowTitle("Add from Folder — pick file formats")
        dlg.setModal(True)
        v = QVBoxLayout(dlg)
        v.setSpacing(10)
        header = QLabel(
            f"<b>Multiple file formats found</b> in:<br>"
            f"<code>{folder}</code><br><br>"
            f"Tick the format(s) you want to import into the queue. "
            f"Unchecked formats stay on disk but aren't added to the "
            f"queue (unless you also enable delete below).")
        header.setWordWrap(True)
        v.addWidget(header)

        # Checkbox per extension. Default: everything ticked (no
        # surprises on Enter).
        ext_boxes: list = []
        box_wrap = QGroupBox("Import which formats?")
        box_layout = QVBoxLayout(box_wrap)
        for ext in unique_exts:
            cb = QCheckBox(f"{ext}   ({counts[ext]} file"
                           f"{'s' if counts[ext] != 1 else ''})")
            cb.setChecked(True)
            ext_boxes.append((ext, cb))
            box_layout.addWidget(cb)
        v.addWidget(box_wrap)

        delete_box = QCheckBox(
            "⚠ Also PERMANENTLY DELETE every other file in the folder "
            "and its subfolders (including subtitles, thumbnails, "
            "notes, etc.)")
        delete_box.setToolTip(
            "Danger: this deletes real files from disk with os.remove — "
            "NOT to the Recycle Bin. You'll get one more explicit "
            "confirmation with the exact count before anything is "
            "removed.")
        v.addWidget(delete_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        mirror_tooltips_to_accessibility(dlg)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None, False

        chosen = [ext for ext, cb in ext_boxes if cb.isChecked()]
        return chosen, delete_box.isChecked()

    def _delete_non_chosen_from_folder(self, folder: str,
                                       chosen_ext_set: set) -> tuple:
        """V14.9.0: PERMANENTLY delete every file in ``folder`` and its
        subfolders whose extension is NOT in ``chosen_ext_set``.

        Two-step confirm:

        1. This method fires an explicit "delete N files permanently"
           dialog listing the count + first 5 example paths.
        2. Only if the user accepts do we call ``os.remove`` per file
           (per-file try/except so one permission-denied doesn't kill
           the run).

        Returns ``(user_confirmed, files_deleted_count)``. When the
        user cancels the confirm, returns ``(False, 0)`` and no file
        is touched.
        """
        # Enumerate the doomed files first so the confirm dialog can
        # show a count + samples. ``followlinks=False`` so a recursive
        # symlink can't blow up the walk (mirrors V14.6.0 scanner).
        doomed: list = []
        try:
            for root, dirs, files in os.walk(folder, followlinks=False):
                for name in files:
                    if Path(name).suffix.lower() in chosen_ext_set:
                        continue
                    doomed.append(os.path.join(root, name))
        except Exception as exc:
            log.warning("Folder walk for delete failed: %s", exc)
            QMessageBox.warning(
                self, "Add from Folder — delete",
                f"Could not enumerate files to delete:\n\n{exc}")
            return False, 0

        if not doomed:
            log.info("Folder import: no files to delete (folder only "
                     "contained the chosen formats)")
            return True, 0

        sample = "\n".join(f"  • {p}" for p in doomed[:5])
        more = (f"\n  … and {len(doomed) - 5} more"
                if len(doomed) > 5 else "")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Confirm permanent deletion")
        msg.setTextFormat(Qt.TextFormat.PlainText)
        msg.setText(
            f"About to PERMANENTLY DELETE {len(doomed)} file(s) from "
            f"{folder} and its subfolders.\n\n"
            f"This is NOT the Recycle Bin — files are removed with "
            f"os.remove and cannot be undone from within Veloxa.\n\n"
            f"Sample of files that will be deleted:\n{sample}{more}")
        del_btn = msg.addButton(
            f"Delete {len(doomed)} file(s) permanently",
            QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton(
            "Cancel — keep every file",
            QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(cancel_btn)
        msg.exec()
        if msg.clickedButton() is not del_btn:
            return False, 0

        # Actual deletion. Per-file try/except so one locked file
        # doesn't abort the sweep.
        n_deleted = 0
        n_failed = 0
        for p in doomed:
            try:
                os.remove(p)
                n_deleted += 1
            except OSError as exc:
                n_failed += 1
                log.info("Could not delete %s: %s", p, exc)
        if n_failed:
            self.status_lbl.setText(
                f"Deleted {n_deleted} file(s); {n_failed} could not "
                f"be removed (log has details).")
        else:
            self.status_lbl.setText(
                f"Deleted {n_deleted} file(s) permanently.")
        return True, n_deleted

    def _collect_supported_files(self, folder: str,
                                 max_files: int = 100000) -> list:
        """V14.6.0: walk ``folder`` recursively and return every file
        whose extension is in ``ALL_INPUT_EXTS``, in a stable
        depth-first sorted order so the queue reads predictably.

        Hard caps at ``max_files`` to keep a misclick on the root of
        a 4 TB drive from locking up the GUI for minutes. The cap is
        absurdly high (~100k) for any normal media library.
        """
        out: list = []
        for root, dirs, files in os.walk(folder, followlinks=False):
            # Sort children for deterministic queue order.
            dirs.sort(key=str.lower)
            for name in sorted(files, key=str.lower):
                if Path(name).suffix.lower() in ALL_INPUT_EXTS:
                    out.append(os.path.join(root, name))
                    if len(out) >= max_files:
                        log.info("Folder scan hit cap of %d files; "
                                 "stopping descent into %s",
                                 max_files, root)
                        return out
        return out

    def _kind_for_path(self, p: str) -> str:
        return "audio" if Path(p).suffix.lower() in AUDIO_EXTS else "video"

    def _visual_kind_for_path(self, p: str):
        ext = Path(p).suffix.lower()
        if ext in IMAGE_EXTS:
            return "image"
        if ext in VIDEO_EXTS:
            return "video"
        return None

    # ============================================================ V14.8.0 onboarding

    _ONBOARDING_SEEN_KEY = "onboarding_seen_v1"

    def _maybe_show_onboarding_tour(self):
        """V14.8.0: fire the 3-step tour on first launch only.
        ``onboarding_seen_v1`` flag persisted under QSettings; bumping
        the suffix in a future version forces a fresh tour if we add
        more steps."""
        if bool(self.settings.value(
                self._ONBOARDING_SEEN_KEY, False, bool)):
            return
        self._run_onboarding_tour()
        self.settings.setValue(self._ONBOARDING_SEEN_KEY, True)

    def _run_onboarding_tour(self):
        """V14.8.0: 3 message boxes pointing at the three features new
        users most often miss. Sequential so each box anchors on the
        previous one's dismissal — no risk of stacking and confusion.
        Each can be dismissed with Esc / OK without breaking the flow.
        """
        # Step 1 — Profiles.
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Welcome to Veloxa — 1 of 3")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            "<b>Profiles save reusable settings.</b><br><br>"
            "Set up trim, watermark, codec, and quality once, save it "
            "as a profile (header dropdown → Save…), then apply it to "
            "any future row with one click. Different rows in the "
            "same batch can use different profiles — drag-drop a 30-"
            "video TikTok batch alongside a 5-podcast batch, assign "
            "each its profile, hit Start.")
        ok = msg.addButton("Got it — next", QMessageBox.ButtonRole.AcceptRole)
        skip = msg.addButton("Skip tour", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(ok)
        msg.exec()
        if msg.clickedButton() is skip:
            return
        # Step 2 — Audio Visuals.
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Welcome to Veloxa — 2 of 3")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            "<b>Audio Visuals turn audio files into video automatically."
            "</b><br><br>"
            "The Audio Visuals tab has six built-in templates "
            "(Spectrum Bars, Waveform, Neon Audio Ring, Podcast "
            "Layout, Spotify Canvas Style, Circular Spectrum). Pick "
            "one and every audio file in your queue is converted to "
            "video with that visual synthesised from the audio itself "
            "— no per-row work. Or tick \"Use these visuals "
            "(round-robin)\" with your own image / video files for "
            "auto-assigned rotating backgrounds.")
        ok = msg.addButton("Got it — next", QMessageBox.ButtonRole.AcceptRole)
        skip = msg.addButton("Skip tour", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(ok)
        msg.exec()
        if msg.clickedButton() is skip:
            return
        # Step 3 — GPU status.
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Welcome to Veloxa — 3 of 3")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(
            "<b>Veloxa auto-detected your GPU encoders.</b><br><br>"
            "Look at the status bar at the bottom-right of this "
            "window. It tells you exactly which hardware "
            "accelerators (NVIDIA NVENC / AMD AMF / Intel QSV / AV1) "
            "are active on this PC — every install probes the local "
            "FFmpeg the first time it launches so the choice is "
            "always machine-specific. The (auto) encoder picks the "
            "fastest one available; Settings → Output → Encoder lets "
            "you override.<br><br>"
            "If you ever swap GPU or drivers, Tools → Re-detect GPU "
            "Encoders reruns the probe.")
        msg.addButton("Got it", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()

    def _has_audio_template_active(self) -> bool:
        """V14.3.5: True iff the Audio Visuals tab has a non-'none'
        template selected. When True the template synthesises the
        per-row visual from the audio itself, so no user-supplied
        ``visual_path`` is needed."""
        if not hasattr(self, "audio_template_combo"):
            return False
        try:
            key = self.audio_template_combo.currentData() or "none"
        except Exception:
            return False
        return bool(key) and key != "none"

    def _auto_assign_audio_visuals_for_new(
            self, audio_paths: list, active_profile: str) -> dict:
        """V14.3.5: when the user has the Audio Visuals tab's
        rotation checkbox ON and a non-empty list of visuals, round-
        robin assign one visual to each newly-added audio file at
        add-to-queue time. Mirrors the per-profile counter the existing
        batch-start rotation uses so the rotation continues seamlessly
        across both code paths.

        Returns a dict ``{audio_path: (visual_path, visual_kind,
        visual_duration)}`` covering ONLY the files we auto-assigned.
        Returns an empty dict (no-op) when:
          * No audio files were added.
          * An audio template is active (template synthesises visual).
          * The Profile Visuals rotation checkbox is OFF.
          * The Profile Visuals list is empty / has no usable entries.

        Persists the advanced counter via ``_pv_set_counter`` so the
        legacy batch-start rotation (in ``_build_jobs``) picks up
        where this method left off rather than double-advancing.
        """
        out: dict = {}
        if not audio_paths:
            return out
        # V14.3.9: log every reason auto-assign no-ops so the user can
        # diagnose from the log file without source access. Was silent
        # in V14.3.5–V14.3.8 — users reporting "auto-assign isn't
        # working on Mac" had no way to see which gate blocked it.
        if self._has_audio_template_active():
            log.info("Auto-assign: skipped (audio template active — "
                     "the template synthesises the visual from the "
                     "audio itself; no per-row visual needed)")
            return out
        if not hasattr(self, "profile_visuals_enabled"):
            log.info("Auto-assign: skipped (no profile_visuals_enabled "
                     "checkbox in this build)")
            return out
        if not self.profile_visuals_enabled.isChecked():
            log.info("Auto-assign: skipped (Audio Visuals tab's "
                     "'Use these visuals for audio inputs (round-robin)' "
                     "checkbox is OFF — tick it to enable auto-assign)")
            return out
        if not hasattr(self, "profile_visuals_list"):
            log.info("Auto-assign: skipped (no profile_visuals_list in "
                     "this build)")
            return out
        # Gather the list of usable visuals (path must exist on disk).
        pv_list = []
        missing_paths: list = []
        n_total = self.profile_visuals_list.count()
        for i in range(n_total):
            it = self.profile_visuals_list.item(i)
            d = it.data(Qt.ItemDataRole.UserRole) or {}
            p = (d.get("path") or "").strip()
            if not p:
                continue
            # ``os.path.exists`` honours macOS sandbox + permission rules
            # — if the user's Profile Visuals point at a Pictures /
            # Music folder the app wasn't granted access to, the entry
            # disappears here and we surface that in the log so the
            # user can grant the permission or repick the visual.
            if not os.path.exists(p):
                missing_paths.append(p)
                continue
            kind = (d.get("kind") or "image").lower()
            pv_list.append({"path": p, "kind": kind})
        if missing_paths:
            log.info("Auto-assign: %d Profile Visuals path(s) are "
                     "missing on disk (skipped in rotation): %s",
                     len(missing_paths),
                     ", ".join(missing_paths[:3])
                     + (f" (+{len(missing_paths) - 3} more)"
                        if len(missing_paths) > 3 else ""))
        if not pv_list:
            log.info("Auto-assign: skipped (Profile Visuals list has 0 "
                     "usable entries — list size=%d, on-disk-missing=%d)",
                     n_total, len(missing_paths))
            return out
        # Pick from the rotation, advancing the counter as we go. The
        # batch-start path consults the same counter; bumping it here
        # means each newly-added file gets a distinct visual AND the
        # next batch picks up where this add-call left off.
        counter = self._pv_get_counter(active_profile)
        for p in audio_paths:
            pick = pv_list[counter % len(pv_list)]
            vp = pick["path"]
            vk = pick["kind"]
            # Resolve duration for video visuals so the encode-time
            # loop-fill math has it ready (mirrors prompt path).
            vd = 0.0
            if vk == "video" and self.ffprobe:
                try:
                    vd = cached_probe_duration(self.ffprobe, vp) or 0.0
                except Exception:
                    vd = 0.0
            out[p] = (vp, vk, vd)
            counter += 1
        # Persist the advanced counter so the legacy rotation in
        # _build_jobs picks up from here.
        self._pv_set_counter(active_profile, counter)
        # Surface in the status label so the user sees the rotation
        # advanced (the existing pv_status_lbl reads from QSettings).
        try:
            self._pv_refresh_status()
        except Exception:
            pass
        log.info("Auto-assigned visuals to %d new audio file(s) "
                 "from profile '%s' (counter now %d)",
                 len(out), active_profile, counter)
        return out

    def _prompt_visual_for_audio(self, count: int = 1):
        """Two-button chooser then a focused file picker."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Visual for Audio")
        msg.setIcon(QMessageBox.Icon.Question)
        if count > 1:
            msg.setText(
                f"{count} audio file(s). Pick a visual for the output MP4:\n\n"
                "- Image: a still picture for the whole audio.\n"
                "- Video: a clip looped to fill the audio length.")
        else:
            msg.setText(
                "Pick a visual for the audio output:\n\n"
                "- Image: a still picture for the whole audio.\n"
                "- Video: a clip looped to fill the audio length.")
        img_btn = msg.addButton("Image...", QMessageBox.ButtonRole.AcceptRole)
        vid_btn = msg.addButton("Video...", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Skip (set later)", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(img_btn)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked is img_btn:
            f, _ = QFileDialog.getOpenFileName(
                self, "Select Image for Audio Visual",
                self.settings.value("last_audio_visual_dir", ""),
                "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)")
            if f:
                self.settings.setValue("last_audio_visual_dir",
                                       str(Path(f).parent))
                return f, "image", 0.0
        elif clicked is vid_btn:
            f, _ = QFileDialog.getOpenFileName(
                self, "Select Video for Audio Visual",
                self.settings.value("last_audio_visual_dir", ""),
                "Videos (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v "
                "*.mpg *.mpeg *.ts *.3gp);;All Files (*.*)")
            if f:
                self.settings.setValue("last_audio_visual_dir",
                                       str(Path(f).parent))
                dur = cached_probe_duration(self.ffprobe,f) if self.ffprobe else 0.0
                return f, "video", dur
        return None, None, 0.0

    def _add_files(self, paths):
        # V14.3.0: removed the queue-lock block on adding files.
        # New rows go to the end of the queue. If a batch is currently
        # running, the BatchManager picks them up via add_jobs at the
        # bottom of this method.
        existing = {self._item_data(self.file_list.item(i)).src
                    for i in range(self.file_list.count())}
        new_paths = [p for p in paths if p not in existing
                     and Path(p).suffix.lower() in ALL_INPUT_EXTS]
        if not new_paths:
            return

        audio_paths = [p for p in new_paths if self._kind_for_path(p) == "audio"]

        # V11.5: auto-assign the active header profile to every row that
        # comes in. The user can change it per-row later (right-click or
        # the per-row picker).
        active_profile = self.profile_combo.currentText() or NO_PROFILE

        # V14.3.5: auto-assign visuals from the Audio Visuals tab when
        # the user has the rotation enabled. Returns a dict keyed by
        # audio path so we can look up the per-row visual below. When
        # the dict is non-empty we SKIP the legacy single-prompt path
        # entirely (the user opted in to rotation, they don't want a
        # modal for every batch). When it returns empty — no template,
        # no enabled rotation, or no usable visuals — fall through to
        # the historical prompt so the existing UX is preserved.
        per_audio_visual = self._auto_assign_audio_visuals_for_new(
            audio_paths, active_profile)

        # Path A: nothing to auto-assign and we still have audio rows →
        # prompt the user once for a shared visual (legacy behaviour).
        # Path B: per_audio_visual has entries OR an audio template is
        # active (synthesised visual, no path needed) → skip the prompt.
        visual_for_audio = visual_kind_for_audio = None
        visual_duration_for_audio = 0.0
        if audio_paths and not per_audio_visual and not self._has_audio_template_active():
            visual_for_audio, visual_kind_for_audio, visual_duration_for_audio = (
                self._prompt_visual_for_audio(len(audio_paths)))

        for p in new_paths:
            kind = self._kind_for_path(p)
            if kind == "audio":
                # V14.3.5: prefer the auto-assigned visual when the
                # rotation fired; otherwise fall back to the shared
                # prompted visual.
                if p in per_audio_visual:
                    vp, vk, vd = per_audio_visual[p]
                    data = QueueItemData(
                        src=p, kind=kind,
                        visual_path=vp, visual_kind=vk,
                        visual_duration=vd,
                        profile_name=active_profile)
                else:
                    data = QueueItemData(
                        src=p, kind=kind,
                        visual_path=visual_for_audio,
                        visual_kind=visual_kind_for_audio,
                        visual_duration=visual_duration_for_audio,
                        profile_name=active_profile)
            else:
                data = QueueItemData(src=p, kind=kind,
                                     profile_name=active_profile)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, data)
            item.setToolTip(p)
            self._refresh_item_label(item)
            self.file_list.addItem(item)
            # V11.5: install the per-row widget that contains the
            # filename label + a profile-picker combo box.
            self._install_row_widget(item)
            log.info("Queue ADD: %s [%s] profile=%s",
                     p, kind, active_profile)

        if self.file_list.currentRow() < 0 and self.file_list.count() > 0:
            self.file_list.setCurrentRow(0)
        self._save_queue_state()
        # V11.5: row count just changed; refresh the queue-stats one-liner.
        if hasattr(self, "queue_stats_lbl"):
            self._refresh_queue_stats()
        # UI-fix: every newly-installed row gets its selection style
        # applied (matters mostly for the row that just became current).
        self._apply_row_selection_styles()
        # V14.3.0: if a batch is already running, hand the newly-added
        # rows to the BatchManager via add_jobs(). The dispatch loop
        # picks them up automatically when a slot frees, so the user
        # doesn't have to stop+restart the batch.
        if (self.batch and self.batch.is_running()
                and len(new_paths) > 0):
            try:
                opts = self._collect_opts()
                # Build job tuples for ONLY the rows we just added —
                # the last len(new_paths) items of self.file_list.
                start = self.file_list.count() - len(new_paths)
                tail_items = [self.file_list.item(start + i)
                              for i in range(len(new_paths))]
                jobs_tail = self._build_jobs_for_items(
                    tail_items, opts) if hasattr(
                    self, "_build_jobs_for_items") else []
                if jobs_tail:
                    self.batch.add_jobs(jobs_tail)
                    self.status_lbl.setText(
                        f"Added {len(jobs_tail)} file(s) to running batch.")
            except Exception as exc:
                log.warning("add_jobs during batch failed: %s", exc)

    def _item_data(self, item) -> QueueItemData:
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _refresh_item_label(self, item):
        d = self._item_data(item)
        if not d:
            return
        # UI-fix: replace pictographic kind / status glyphs with plain
        # ASCII tags. The original 🔊 / 🎞 / ⊘ codepoints are color-emoji
        # supplementary-plane glyphs that fall back to mojibake or
        # tofu-boxes on Windows fonts that lack proper emoji support,
        # making rows look "garbled". Plain ASCII is universally legible.
        kind_tag = "[A]" if d.kind == "audio" else "[V]"
        if d.status == "encoding":
            stat = f"  {d.progress:5.1f}%"
            if d.eta and d.eta > 0:
                stat += f"  ETA {fmt_eta(d.eta)}"
        elif d.status == "done":
            stat = "  DONE"
        elif d.status == "failed":
            stat = "  FAILED"
        elif d.status == "cancelled":
            stat = "  CANCELLED"
        else:
            stat = "  pending"
        name = Path(d.src).name
        visual_tag = ""
        if d.kind == "audio":
            if d.visual_path:
                if d.visual_kind == "video":
                    visual_tag = "  +video-visual"
                else:
                    visual_tag = "  +image-visual"
            elif self._has_audio_template_active():
                # V14.3.9: when an audio template is selected (Spectrum
                # Bars, Waveform, Neon Ring, etc.) the visual is
                # synthesised from the audio itself at encode time — no
                # per-row visual_path is needed. Previously the row label
                # showed "(visual needed)" here, which read as broken
                # configuration even though the encode would succeed.
                try:
                    tpl_name = (self.audio_template_combo.currentText()
                                or "template")
                except Exception:
                    tpl_name = "template"
                visual_tag = f"  +{tpl_name}"
            else:
                visual_tag = "  (visual needed)"
        # V11.5: filename label is rendered inside the per-row widget
        # (set via _install_row_widget). Update both the row's text (used
        # as a fallback / accessibility / drag preview) and the widget's
        # internal label.
        text = f"{kind_tag} {name}{visual_tag}{stat}"
        item.setText(text)
        item.setToolTip(d.src + (f"\n\nError: {d.error}" if d.error else ""))
        self._refresh_row_widget(item)

    def _install_row_widget(self, item):
        """V11.5: each queue row carries a small custom widget — the
        kind-tagged filename on the left, a profile-picker combo on the
        right. Updates to either flow back to the underlying
        :class:`QueueItemData`. Called once per row from ``_add_files`` /
        queue-restore, then refreshed on label / status changes via
        :meth:`_refresh_row_widget`.

        UI-fix iteration 2: don't put a stylesheet on the wrap (Fusion
        doesn't auto-fill QWidget background, so it's transparent by
        default — adding a stylesheet was inviting cascade weirdness on
        the inner QComboBox). Restore some breathing room and let the
        combo size itself; capping its height to 22 px on Windows
        prevented the dropdown chrome from rendering at all.
        """
        from PyQt6.QtWidgets import QSizePolicy
        d = self._item_data(item)
        if not d:
            return
        # Compose the custom row widget. The wrap is a plain QWidget
        # with no styling of its own — the QListWidgetItem's selection
        # background paints through. The inner label + combo are the
        # only visible content.
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(8)
        lbl = QLabel(item.text())
        lbl.setProperty("role", "queue-row-label")
        # Label has no background of its own (default for QLabel) so
        # the item's selection orange shows through.
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Preferred)
        h.addWidget(lbl, 1)

        # V12.3 improvement: per-row visual progress bar. Slim 110×12 px
        # bar that lives between the label and the combo. Shown only
        # while the row is encoding / done / failed / cancelled — hidden
        # by default for pending rows so the row stays visually clean
        # before encoding starts. Color is set from the row's status in
        # _refresh_row_widget so the bar reads at-a-glance: orange =
        # encoding, green = done, red = failed, grey = cancelled.
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(0)
        pb.setTextVisible(False)
        pb.setFixedWidth(110)
        pb.setFixedHeight(12)
        pb.setProperty("role", "queue-row-progress")
        pb.setVisible(False)
        h.addWidget(pb)

        pc = ProfileCombo()
        pc.setMinimumWidth(140)
        pc.setMaximumWidth(220)
        # NB no setMaximumHeight() here — Windows QComboBox needs ~26px
        # of vertical room for its dropdown arrow and frame. Capping it
        # tighter than that can leave the combo invisible.
        pc.setToolTip("Profile to use when this row is encoded.\n"
                      "Right-click any selected rows and use 'Apply "
                      "Profile…' to change many at once — or select "
                      "rows and type a profile's shortcut number.")
        # Populate with NO_PROFILE + saved names; current value = row's
        # profile_name (falling back to NO_PROFILE if unknown).
        self._populate_profile_combo(pc)
        target = d.profile_name or NO_PROFILE
        idx = pc.findText(target)
        if idx < 0:
            # Profile referenced by the row no longer exists — show it
            # as a sentinel so the user notices, but don't crash.
            pc.insertItem(1, target)
            idx = pc.findText(target)
        pc.setCurrentIndex(max(0, idx))

        # Connect AFTER setting the value, so the initial population
        # doesn't trigger a "user changed it" event.
        pc.currentTextChanged.connect(
            lambda new_name, it=item: self._on_row_profile_changed(it, new_name))
        h.addWidget(pc)
        # Stash the inner widgets on the wrap so _refresh_row_widget can
        # find them later (they're not attribute-accessible otherwise).
        wrap._lbl = lbl
        wrap._combo = pc
        wrap._progress = pb
        self.file_list.setItemWidget(item, wrap)
        # UI-fix: only constrain the row HEIGHT via setSizeHint — the
        # width is determined by the QListWidget's viewport. Use the
        # max of the wrap's own sizeHint and a sensible floor (28 px)
        # so QComboBox always has room for its drop-arrow chrome on
        # Windows. Width=0 lets the list paint full-width rows.
        from PyQt6.QtCore import QSize
        natural = wrap.sizeHint().height()
        item.setSizeHint(QSize(0, max(28, natural)))

    def _refresh_row_widget(self, item):
        """Sync the per-row widget's label + combo + progress bar with
        the current :class:`QueueItemData` (called after status /
        progress / profile changes)."""
        if item is None:
            return
        wrap = self.file_list.itemWidget(item)
        if wrap is None:
            return
        d = self._item_data(item)
        if not d:
            return
        lbl = getattr(wrap, "_lbl", None)
        if lbl is not None:
            lbl.setText(item.text())
        combo = getattr(wrap, "_combo", None)
        if combo is not None:
            target = d.profile_name or NO_PROFILE
            if combo.currentText() != target:
                idx = combo.findText(target)
                if idx < 0:
                    combo.insertItem(1, target)
                    idx = combo.findText(target)
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, idx))
                combo.blockSignals(False)
        # V12.3 improvement: per-row progress bar. Visible only once
        # the row has actually moved past "pending" — encoding shows
        # current %, terminal states (done / failed / cancelled) hold
        # the bar at full so the row reads at-a-glance after a batch.
        # Color is driven by the row's status via a dynamic property
        # the stylesheet keys off.
        pb = getattr(wrap, "_progress", None)
        if pb is not None:
            st = getattr(d, "status", "") or ""
            if st == "encoding":
                pb.setVisible(True)
                pb.setValue(int(max(0.0, min(100.0, d.progress or 0.0))))
                pb.setProperty("state", "encoding")
            elif st == "done":
                pb.setVisible(True)
                pb.setValue(100)
                pb.setProperty("state", "done")
            elif st == "failed":
                pb.setVisible(True)
                pb.setValue(int(max(1.0, d.progress or 0.0)))
                pb.setProperty("state", "failed")
            elif st == "cancelled":
                pb.setVisible(True)
                pb.setValue(int(max(0.0, d.progress or 0.0)))
                pb.setProperty("state", "cancelled")
            else:  # pending or anything else
                pb.setVisible(False)
                pb.setValue(0)
                pb.setProperty("state", "pending")
            # Force a stylesheet refresh whenever the state property
            # flips so the colour change actually paints.
            pb.style().unpolish(pb)
            pb.style().polish(pb)

    def _apply_row_selection_styles(self):
        """V14.3.6: drive the per-row label colour from the active QSS
        (was a hard-coded ``#e6e6e6`` / ``#ffffff`` inline stylesheet
        that worked on the dark theme but rendered as invisible-on-
        white in the light theme — see the v14.3.5 light-theme bug
        report). Now we just toggle a ``selected`` dynamic property
        on the label; ``QLabel[role="queue-row-label"][selected="..."]``
        rules in ``theme.py`` pick the right colour for each theme.
        """
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            wrap = self.file_list.itemWidget(it)
            if wrap is None:
                continue
            lbl = getattr(wrap, "_lbl", None)
            if lbl is None:
                continue
            sel = bool(it.isSelected())
            # Set as string so QSS attribute matching works.
            new_val = "true" if sel else "false"
            if lbl.property("selected") != new_val:
                lbl.setProperty("selected", new_val)
                # Re-polish so the new property triggers the QSS rule.
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
                lbl.update()

    def _populate_profile_combo(self, combo):
        """Fill a per-row profile picker with NO_PROFILE plus saved
        profile names sorted case-insensitively, displayed with their
        sticky shortcut numbers (V14.10.0)."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(NO_PROFILE, userData=NO_PROFILE)
        for name in sorted(self.profiles.keys(), key=str.lower):
            combo.addItem(self._profile_label(name), userData=name)
        combo.blockSignals(False)

    def _on_row_profile_changed(self, item, new_name: str):
        """User picked a different profile in a row's combo box.
        ``currentTextChanged`` emits the DISPLAY label ('N. Name') --
        map it back to the raw profile name first (V14.10.0)."""
        new_name = self._profile_name_from_label(new_name)
        if self._queue_locked:
            # Bounce back: the row was assigned at queue-build time; we
            # don't allow per-row changes mid-batch.
            self._refresh_row_widget(item)
            return
        d = self._item_data(item)
        if not d:
            return
        d.profile_name = new_name
        self._save_queue_state()
        # V12.3 fix: if the changed row is the currently-selected one,
        # the preview pane and info bar still reflect the OLD profile
        # until something else nudges them. Force a refresh so the
        # watermark / resolution / info-bar instantly track the row's
        # new profile.
        if item == self.file_list.currentItem():
            self._update_preview_info()
            self._schedule_preview()

    def _refresh_all_row_widgets(self):
        """Re-populate every per-row picker (e.g. after a profile is
        added / renamed / deleted)."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            wrap = self.file_list.itemWidget(item)
            if wrap is None:
                continue
            combo = getattr(wrap, "_combo", None)
            if combo is None:
                continue
            current = combo.currentText()
            self._populate_profile_combo(combo)
            # Restore the row's own profile_name (which may differ from
            # whatever was selected in the combo a moment ago).
            d = self._item_data(item)
            target = (d.profile_name if d else "") or current or NO_PROFILE
            idx = combo.findText(target)
            if idx < 0:
                combo.insertItem(1, target)
                idx = combo.findText(target)
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)

    def _rebase_queue_rows(self, renames: dict = None,
                           deleted: set = None) -> int:
        """V11.5 fix (audit B1/B2): rewrite queue-row ``profile_name``
        fields after profile rename / delete. Called from
        ``ProfileManagerDialog`` so a row pinned to "PodcastA" follows
        the profile through a rename to "PodcastB" instead of silently
        falling back to the live form.

        ``renames`` maps OLD name -> NEW name. ``deleted`` is a set of
        names that have been removed; rows pinned to them fall back to
        :data:`NO_PROFILE`. Returns the number of rows that were touched.
        """
        renames = renames or {}
        deleted = deleted or set()
        if not renames and not deleted:
            return 0
        cur = self.file_list.currentItem()
        cur_touched = False
        touched = 0
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            d = self._item_data(it)
            if not d:
                continue
            if d.profile_name in renames:
                d.profile_name = renames[d.profile_name]
                self._refresh_row_widget(it)
                touched += 1
                if it is cur:
                    cur_touched = True
            elif d.profile_name in deleted:
                d.profile_name = NO_PROFILE
                self._refresh_row_widget(it)
                touched += 1
                if it is cur:
                    cur_touched = True
        if touched:
            self._save_queue_state()
            # V12.3 audit fix (E4): a profile rename / delete may have
            # changed the dict in self.profiles; the per-batch row-opts
            # cache could be holding the stale entry. Wipe it so the
            # next preview / batch re-resolves from current state.
            self._row_opts_cache = {}
            # V12.3 audit fix (E2/E3): if the currently-selected row was
            # rebased, the preview pane and info bar still reflect the
            # OLD profile's render until something else nudges them.
            # Force a refresh so they switch to the new profile (or to
            # the live form for a deleted profile) immediately.
            if cur_touched:
                self._update_preview_info()
                self._schedule_preview()
            log.info("Rebased %d queue row(s): renames=%s deleted=%s",
                     touched, renames, deleted)
        return touched

    def _refresh_per_row_combos_only(self):
        """V11.5 fix (audit B4): repopulate every per-row profile combo
        from ``self.profiles`` (used after dialog operations that change
        the profile set without changing names — like Import / Duplicate).
        Distinct from :meth:`_refresh_all_row_widgets` only in name; this
        is the cross-module entry point so dialogs can call it explicitly.
        """
        self._refresh_all_row_widgets()

    def _on_rows_moved(self, *_):
        """V11.5 fix (audit B3): after drag-reorder, every row that lost
        its custom item-widget gets one re-installed. Cheap: a row that
        already has a widget short-circuits, so the typical case where
        only one row moved still touches ~2 rows.
        """
        for i in range(self.file_list.count()):
            it = self.file_list.item(i)
            if self.file_list.itemWidget(it) is None:
                self._install_row_widget(it)
        # UI-fix: drag-reorder repaints rows; reapply selection style.
        self._apply_row_selection_styles()
        self._save_queue_state()

    def _remove_selected(self):
        # The Delete keyboard shortcut hits this directly so the lock check
        # belongs here, not just on the disabled button.
        if self._queue_locked:
            return
        rows = sorted(
            {self.file_list.row(i) for i in self.file_list.selectedItems()},
            reverse=True)
        for r in rows:
            self.file_list.takeItem(r)
        self._save_queue_state()
        self._refresh_queue_stats()

    def _remove_completed(self):
        if self._queue_locked:
            return
        for i in range(self.file_list.count() - 1, -1, -1):
            d = self._item_data(self.file_list.item(i))
            if d and d.status in ("done", "failed", "cancelled"):
                self.file_list.takeItem(i)
        self._save_queue_state()
        self._refresh_queue_stats()

    def _remove_done_only(self):
        """Remove only successfully-completed (status == 'done') rows.

        Failed and cancelled items stay in the queue so the user can decide
        whether to retry them (re-running the batch picks failed items back
        up automatically) or remove them manually.
        """
        if self._queue_locked:
            return
        removed = 0
        for i in range(self.file_list.count() - 1, -1, -1):
            d = self._item_data(self.file_list.item(i))
            if d and d.status == "done":
                self.file_list.takeItem(i)
                removed += 1
        if removed:
            self._save_queue_state()
            self.status_lbl.setText(f"Removed {removed} completed item(s)")
        else:
            self.status_lbl.setText("No 'done' items to remove")
        self._refresh_queue_stats()

    def _clear_queue(self):
        if self._queue_locked:
            return
        if self.file_list.count() == 0:
            return
        r = QMessageBox.question(self, "Clear Queue",
                                 f"Remove all {self.file_list.count()} items?",
                                 QMessageBox.StandardButton.Yes
                                 | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.file_list.clear()
            self._save_queue_state()
            # V11.5 fix (audit B1): clearing the queue must also refresh
            # the stats one-liner; without this it kept showing the old
            # "N files" count until the next add/remove event.
            self._refresh_queue_stats()
            # V11.5 fix: also reset the preview so a later window resize
            # can't pull the last frame back off disk.
            self.preview_label.setText("Add a video or audio file. "
                                       "Drag the orange bars to set "
                                       "trim points.")
            self._has_preview_this_session = False

    def _on_queue_context_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item:
            return
        d = self._item_data(item)
        # All currently-selected rows (for bulk actions). If the
        # right-clicked row isn't in the selection, treat it as the only
        # target so right-click on an unselected row Just Works.
        selected_items = list(self.file_list.selectedItems())
        if item not in selected_items:
            selected_items = [item]
        n_sel = len(selected_items)

        menu = QMenu(self)
        # V14.0: jump preview to this row.
        act_preview = menu.addAction("▶ Preview This Row")
        if not d:
            act_preview.setEnabled(False)
        menu.addSeparator()
        act_open_src = menu.addAction("📂 Open Source Folder")
        act_open_dst = menu.addAction("📂 Open Output Folder")
        menu.addSeparator()
        # V14.0: row order shortcuts.
        act_to_top = menu.addAction(f"⬆ Move {n_sel} to Top")
        act_to_bot = menu.addAction(f"⬇ Move {n_sel} to Bottom")
        if self._queue_locked:
            act_to_top.setEnabled(False)
            act_to_bot.setEnabled(False)
        menu.addSeparator()
        # V14.0: duplicate + retry.
        act_duplicate = menu.addAction(f"➕ Duplicate {n_sel} Row(s)")
        act_retry = menu.addAction(f"↻ Retry {n_sel} Failed/Done Row(s)")
        if self._queue_locked:
            act_duplicate.setEnabled(False)
            act_retry.setEnabled(False)
        menu.addSeparator()

        # V11.5 (Feature 2c): Apply Profile submenu, populated from saved
        # profiles. Acts on every selected row.
        apply_menu = menu.addMenu(f"⚙ Apply Profile to {n_sel} item(s)")
        profile_actions = {}
        if self.profiles:
            for pname in sorted(self.profiles.keys(), key=str.lower):
                a = apply_menu.addAction(self._profile_label(pname))
                profile_actions[a] = pname
        else:
            empty = apply_menu.addAction("(no saved profiles)")
            empty.setEnabled(False)
        # Always allow assigning the (no profile) sentinel.
        apply_menu.addSeparator()
        act_apply_no_profile = apply_menu.addAction(NO_PROFILE)
        if self._queue_locked:
            apply_menu.setEnabled(False)

        menu.addSeparator()
        if d and d.kind == "audio":
            act_change_visual = menu.addAction("🖼 Change Visual...")
            if self._queue_locked:
                act_change_visual.setEnabled(False)
        else:
            act_change_visual = None
        act_remove = menu.addAction(f"− Remove {n_sel} from Queue")
        if self._queue_locked:
            act_remove.setEnabled(False)

        # V11.5 (Feature 1): Delete from disk. Shown in red-tinted style
        # by Qt automatically on Windows when the action's name contains
        # "Delete"; we also use the 🗑 prefix for visibility.
        act_delete_disk = menu.addAction(f"🗑 Delete {n_sel} from Disk...")
        if self._queue_locked:
            act_delete_disk.setEnabled(False)

        chosen = menu.exec(self.file_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_preview and d:
            # Select the clicked row to make it the current one — the
            # preview pane auto-syncs from the selection.
            self.file_list.setCurrentItem(item)
            self._refresh_preview()
            return
        if chosen == act_to_top:
            self._move_items_to(selected_items, position="top")
            return
        if chosen == act_to_bot:
            self._move_items_to(selected_items, position="bottom")
            return
        if chosen == act_duplicate:
            self._duplicate_items(selected_items)
            return
        if chosen == act_retry:
            self._retry_items(selected_items)
            return
        if chosen == act_open_src and d:
            self._open_in_explorer(Path(d.src).parent)
        elif chosen == act_open_dst and d:
            # V11.5 fix (audit E1): "Open Output Folder" must use the
            # row's profile when computing the path, otherwise the
            # explorer pops open a folder that's INCONSISTENT with where
            # the encode will actually write.
            row_opts = self._opts_for_row(d.profile_name, self._collect_opts())
            self._open_in_explorer(
                Path(self._dst_for(d.src, opts_override=row_opts)).parent)
        elif act_change_visual is not None and chosen == act_change_visual:
            self._change_visual_for(item)
        elif chosen == act_remove:
            for it in selected_items:
                self.file_list.takeItem(self.file_list.row(it))
            self._save_queue_state()
            self._refresh_queue_stats()
        elif chosen == act_delete_disk:
            self._delete_selected_from_disk(selected_items)
        elif chosen == act_apply_no_profile:
            self._apply_profile_to_items(selected_items, NO_PROFILE)
        elif chosen in profile_actions:
            self._apply_profile_to_items(
                selected_items, profile_actions[chosen])

    # ===================== V14.0 queue row context helpers

    def _move_items_to(self, items: list, *, position: str):
        """V14.0: move the given items to either ``"top"`` or
        ``"bottom"`` of the queue. Preserves the order *within* the
        moved selection."""
        if not items or self._queue_locked:
            return
        # Capture (data, widget) pairs in their current order so we can
        # restore them after take.
        captured = []
        for it in items:
            row = self.file_list.row(it)
            captured.append((row, it))
        captured.sort(key=lambda t: t[0])
        # Take them all out (highest row first so indices stay valid).
        taken = []
        for row, it in sorted(captured, key=lambda t: -t[0]):
            taken.insert(0, self.file_list.takeItem(row))
        # Re-insert at the target end.
        if position == "top":
            for offset, it in enumerate(taken):
                self.file_list.insertItem(offset, it)
                self._install_row_widget(it)
        else:
            for it in taken:
                self.file_list.addItem(it)
                self._install_row_widget(it)
        # Re-select to keep the user's selection intact.
        self.file_list.clearSelection()
        for it in taken:
            it.setSelected(True)
        self._save_queue_state()
        self._refresh_queue_stats()

    def _duplicate_items(self, items: list):
        """V14.0: clone selected rows. Each clone is appended right
        after the original with the same source, visual, and profile."""
        if not items or self._queue_locked:
            return
        # Walk in reverse-row order so inserting at row+1 doesn't shift
        # later targets.
        targets = sorted(items, key=lambda it: -self.file_list.row(it))
        for it in targets:
            d = self._item_data(it)
            if not d:
                continue
            new_d = QueueItemData(
                src=d.src,
                kind=d.kind,
                visual_path=d.visual_path,
                visual_kind=d.visual_kind,
                visual_duration=d.visual_duration,
                profile_name=d.profile_name,
            )
            insert_at = self.file_list.row(it) + 1
            new_item = QListWidgetItem()
            new_item.setData(Qt.ItemDataRole.UserRole, new_d)
            self.file_list.insertItem(insert_at, new_item)
            self._refresh_item_label(new_item)
            self._install_row_widget(new_item)
        self._save_queue_state()
        self._refresh_queue_stats()

    def _retry_items(self, items: list):
        """V14.0: reset the given rows back to ``pending`` so they get
        re-encoded on the next Start. Useful for failed / cancelled /
        previously-done rows the user wants to re-run."""
        if not items or self._queue_locked:
            return
        for it in items:
            d = self._item_data(it)
            if not d:
                continue
            d.status = "pending"
            d.progress = 0.0
            d.error = ""
            d.eta = -1.0
            it.setData(Qt.ItemDataRole.UserRole, d)
            self._refresh_item_label(it)
        self._save_queue_state()
        self._refresh_queue_stats()

    def _delete_selected_from_disk(self, items: list):
        """V11.5 (Feature 1): permanently delete the source files of the
        given queue items from disk, then drop them from the queue.
        Confirmation dialog mirrors the user-spec wording."""
        if not items:
            return
        srcs = []
        for it in items:
            d = self._item_data(it)
            if d and d.src:
                srcs.append(Path(d.src))
        if not srcs:
            return
        if len(srcs) == 1:
            msg = f"Delete '{srcs[0].name}' from disk? This cannot be undone."
        else:
            msg = f"Delete {len(srcs)} files from disk? This cannot be undone."
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete from disk")
        box.setText(msg)
        if len(srcs) > 1:
            # Show the full list as a tooltip-like detail / scrollable
            # pane so the user can review what they're about to nuke.
            box.setDetailedText("\n".join(str(p) for p in srcs))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        deleted = 0; failed = []
        for p in srcs:
            try:
                if p.exists():
                    p.unlink()
                deleted += 1
            except OSError as exc:
                failed.append(f"{p.name}: {exc}")
        # Drop the matching rows from the queue regardless; if the file
        # was already missing the user clearly wanted it gone.
        for it in items:
            row = self.file_list.row(it)
            if row >= 0:
                self.file_list.takeItem(row)
        self._save_queue_state()
        self._refresh_queue_stats()
        if failed:
            QMessageBox.warning(self, "Delete partially failed",
                                f"Deleted {deleted}.\nFailed:\n"
                                + "\n".join(failed[:10]))
        else:
            self.status_lbl.setText(
                f"Deleted {deleted} file(s) from disk")
        log.info("Delete-from-disk: %d files deleted, %d failed",
                 deleted, len(failed))

    def _apply_profile_to_items(self, items: list, profile_name: str):
        """V11.5 (Feature 2c): mark each selected row to use ``profile_name``
        when it gets encoded. Used by both the right-click submenu and
        the per-row picker (which calls this directly)."""
        if not items:
            return
        cur = self.file_list.currentItem()
        for it in items:
            d = self._item_data(it)
            if not d:
                continue
            d.profile_name = profile_name
            self._refresh_item_label(it)
            self._refresh_row_widget(it)
        self._save_queue_state()
        # V12.3 fix: if the bulk-update touched the currently-selected
        # row, refresh the preview so it switches to the new profile.
        if cur and cur in items:
            self._update_preview_info()
            self._schedule_preview()
        self.status_lbl.setText(
            f"Applied profile '{profile_name}' to {len(items)} item(s)")

    def _change_visual_for(self, item):
        d = self._item_data(item)
        if not d or d.kind != "audio":
            return
        path, kind, duration = self._prompt_visual_for_audio(1)
        if not path:
            return
        d.visual_path = path
        d.visual_kind = kind
        d.visual_duration = duration
        self._refresh_item_label(item)
        if item == self.file_list.currentItem():
            self._schedule_preview()
        self._save_queue_state()

    def _open_in_explorer(self, p: Path):
        """V14.2.0: delegated to platform_compat so macOS gets
        Finder via ``open`` rather than the Linux ``xdg-open``
        fallback that V14.1.x defaulted to."""
        from .platform_compat import open_in_file_manager
        open_in_file_manager(p)

    # ---- V12.3.1: quality-tier hint refreshers ---------------------------

    def _refresh_video_quality_hint(self, *_):
        """Update the small label under the video quality dropdown so the
        user sees what kbps the current (tier, resolution) selection
        actually resolves to."""
        try:
            tier = self.video_quality.currentText()
            res = RESOLUTIONS.get(self.out_res.currentText())
            if res:
                w, h = res
                kbps = resolve_video_bitrate_kbps(tier, w, h)
                label = f"{w}x{h}"
            else:
                # "Match Source" — we don't know source W/H here; show the
                # 1080p column as a representative value and label it as
                # "estimated".
                kbps = resolve_video_bitrate_kbps(tier, 0, 0)
                label = "match source"
            self.video_quality_hint.setText(
                f"{tier} @ {label}  ≈  {kbps} kbps"
            )
        except (AttributeError, KeyError):
            # Called too early in __init__ before all widgets exist.
            pass

    def _refresh_audio_quality_hint(self, *_):
        try:
            tier = self.audio_quality.currentText()
            kbps = resolve_audio_bitrate_kbps(tier)
            self.audio_quality_hint.setText(
                f"{tier}  =  {kbps} kbps (AAC)"
            )
        except (AttributeError, KeyError):
            pass

    def _pick_merge_file(self, line_edit, title: str):
        """V12.3: file picker for intro / outro videos. Accepts any
        video container the engine can re-encode (we'll auto-scale to
        the profile's output resolution at concat time). The path goes
        into ``line_edit`` and gets serialized + copied into the
        profile's asset folder on Save.

        V12.3 hardening: probe the picked file before accepting it.
        Empty audio is fine (engine synthesises silence at concat),
        but a file with no decodable video stream or zero duration
        would crash the concat filter at run time — reject those
        here with a clear message instead of letting the encode
        fail mid-batch.
        """
        f, _ = QFileDialog.getOpenFileName(
            self, title,
            self.settings.value("last_merge_dir", ""),
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv "
            "*.m4v *.mpg *.mpeg *.ts);;All Files (*.*)")
        if not f:
            return
        # Probe: must have a video stream + non-zero duration.
        w, h = cached_probe_resolution(self.ffprobe, f) if self.ffprobe else (0, 0)
        dur = cached_probe_duration(self.ffprobe, f) if self.ffprobe else 0.0
        if w <= 0 or h <= 0 or dur <= 0.05:
            QMessageBox.warning(
                self,
                "Invalid video file",
                f"<b>Veloxa can't use this file as an intro / outro.</b><br><br>"
                f"<code>{f}</code><br><br>"
                f"It has no decodable video stream (resolution "
                f"{w}x{h}, duration {dur:.2f}s).<br><br>"
                f"Pick a file with a valid video track — any common "
                f"format works (MP4, MOV, MKV, AVI, WebM, ...).")
            return
        self.settings.setValue("last_merge_dir", str(Path(f).parent))
        line_edit.setText(f)

    def _pick_watermark(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Watermark Image",
            self.settings.value("last_wm_dir", ""),
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)")
        if f:
            self.settings.setValue("last_wm_dir", str(Path(f).parent))
            # Copy the chosen image into the app's watermarks folder
            # (%APPDATA%\Veloxa-VD\watermarks\) so the path used by the
            # profile keeps working even if the original file is moved
            # or deleted. Same content -> same hash -> reuses the existing
            # copy.
            local_path = import_watermark_image(f)
            self.wm_path.setText(local_path)
            if local_path != f:
                log.info("Watermark image imported: %s -> %s", f, local_path)

    def _pick_text_color(self):
        c = QColorDialog.getColor(QColor(self._text_color), self,
                                  "Text Watermark Color")
        if c.isValid():
            self._text_color = c.name()
            self.text_wm_color_swatch.setStyleSheet(
                f"background:{self._text_color}; border:1px solid #454952; "
                f"border-radius:3px;")
            self._schedule_preview()

    # ====================================================== preview & seek

    def _current_video(self):
        item = self.file_list.currentItem()
        if not item:
            return None, None
        return self._item_data(item), item

    def _on_video_selected(self, *_):
        d, _item = self._current_video()
        if not d or not os.path.exists(d.src) or not self.ffprobe:
            self.video_duration = 0.0
            self._src_w = self._src_h = 0
            self.seek_bar.setDuration(0)
            self.duration_lbl.setText("00:00.00")
            self.current_time_lbl.setText("00:00.00")
            self.preview_label.setText("Select a file to preview")
            self.preview_info_lbl.setText("")
            # V14.0.2 fix: hide the preview metadata overlay so it
            # doesn't keep showing the previous selection's info after
            # the queue is emptied or the only row is removed.
            if hasattr(self, "preview_overlay") and self.preview_overlay:
                self.preview_overlay.hide()
            # Stop any playback so we don't leave a paused video frame
            # on screen after the queue is cleared.
            if getattr(self, "_mp_player", None) is not None:
                try:
                    self._mp_player.stop()
                except Exception:
                    pass
            if getattr(self, "_mp_video_widget", None) is not None:
                try:
                    self._mp_video_widget.hide()
                except Exception:
                    pass
            # V11.5 fix: also forget the last-rendered pixmap so a window
            # resize (which fires _render_preview_from_disk) can't bring
            # the previous selection's frame back.
            self._has_preview_this_session = False
            return
        dur = cached_probe_duration(self.ffprobe,d.src)
        self.video_duration = dur
        # Probe source resolution for the info label (cached until next select).
        if d.kind == "video":
            self._src_w, self._src_h = cached_probe_resolution(self.ffprobe,d.src)
        else:
            self._src_w = self._src_h = 0
        self.duration_lbl.setText(fmt_time(dur))
        self.seek_bar.setDuration(dur)
        self.seek_bar.setTrim(self.trim_start.value(), self.trim_end.value())
        start_t = min(self.trim_start.value(), dur) if dur > 0 else 0
        self.seek_bar.setSeek(start_t)
        self.seek_time = start_t
        self.current_time_lbl.setText(fmt_time(start_t))
        self._update_trim_info()
        self._schedule_preview()

    def _on_seek_changed(self, t: float):
        self.seek_time = t
        self.current_time_lbl.setText(fmt_time(t))
        # Refresh the preview frame WHILE the user is dragging the scrub
        # knob, not only on release. The 200ms debounce keeps this cheap.
        self._schedule_preview()

    def _on_trim_changed_from_bar(self, start: float, end_trim: float):
        self._suppress_change = True
        try:
            self.trim_start.setValue(round(start, 2))
            self.trim_end.setValue(round(end_trim, 2))
        finally:
            self._suppress_change = False
        self._update_trim_info()

    def _sync_seek_bar_trim(self):
        # Always mirror the spinboxes onto the seek bar; setTrim doesn't
        # re-emit trim_changed so this can't loop.
        self.seek_bar.setTrim(self.trim_start.value(), self.trim_end.value())

    def _update_trim_info(self, *_):
        if self.video_duration <= 0:
            self.trim_info_lbl.setText("")
            return
        s = self.trim_start.value()
        e_trim = self.trim_end.value()
        end_pos = max(0.0, self.video_duration - e_trim)
        final = max(0.0, end_pos - s)
        self.trim_info_lbl.setText(
            f"Cut: {fmt_time(s)} -> {fmt_time(end_pos)}   ({fmt_time(final)})")
        self._update_preview_info()

    def _update_preview_info(self):
        """Source -> Output one-liner shown beneath the seek bar."""
        d, _item = self._current_video()
        if not d:
            self.preview_info_lbl.setText("")
            # V14.0.2 fix: the V14.0 metadata overlay was left showing
            # stale info ("Source: previous_file.mp4 ...") after the
            # queue was emptied or the only row was removed, because the
            # early-return here skipped past the overlay block at the
            # bottom of this method. Hide it explicitly.
            if hasattr(self, "preview_overlay") and self.preview_overlay:
                self.preview_overlay.hide()
            return
        # V12.3 fix: same logic as _refresh_preview — show the row's
        # profile when it differs from the loaded one, so the info bar
        # describes what THIS row will encode to, not the live form.
        live_opts = self._collect_opts()
        active_profile = self.profile_combo.currentText()
        if (d.profile_name and d.profile_name != NO_PROFILE
                and d.profile_name != active_profile
                and d.profile_name in self.profiles):
            opts = self._opts_for_row(d.profile_name, live_opts)
            profile_tag = f"  [profile: {d.profile_name}]"
        else:
            opts = live_opts
            profile_tag = ""
        speed = opts.get("speed", 1.0) or 1.0
        speed_str = f", {speed:g}x" if abs(speed - 1.0) > 1e-3 else ""
        loud_str = ", loudnorm" if opts.get("loudnorm") else ""
        stereo_str = ", stereo" if opts.get("force_stereo", True) else ""
        # V12.3 fix: codec from row_opts (the saved profile's codec) when
        # the row is pinned to a non-active profile, falling back to the
        # live-form helper otherwise.
        # V12.3 audit fix (E1): the previous split("_")[0] returned
        # "LIBX264" / "LIBX265" for CPU encoders since they have no
        # underscore. Map encoder name -> display codec via a small table
        # so CPU and GPU encoders both show H264 / HEVC consistently.
        _enc = str(opts.get("encoder") or "").lower()
        if "hevc" in _enc or _enc == "libx265":
            codec = "HEVC"
        elif "h264" in _enc or _enc == "libx264":
            codec = "H264"
        else:
            codec = self._codec_value().upper()
        encoder = opts.get("encoder", "?")
        out_w = opts.get("out_w") or 0
        out_h = opts.get("out_h") or 0
        if d.kind == "audio":
            src_part = f"Audio: {fmt_time(self.video_duration)}"
            if d.visual_kind == "video":
                src_part += " + video visual"
            elif d.visual_kind == "image":
                src_part += " + image visual"
        else:
            res = (f"{self._src_w}x{self._src_h}"
                   if self._src_w and self._src_h else "?")
            src_part = f"Source: {res}, {fmt_time(self.video_duration)}"
        if out_w and out_h:
            out_res_str = f"{out_w}x{out_h}"
        else:
            out_res_str = "match source"
        out_part = (f"Output: {out_res_str} {codec} via {encoder}"
                    f"{speed_str}{loud_str}{stereo_str}{profile_tag}")
        self.preview_info_lbl.setText(f"{src_part}   ->   {out_part}")

        # V14.0: populate the in-preview overlay (top-left of the preview
        # frame) with the per-source metadata block the user asked for.
        # Hidden when there's no current row.
        if d:
            name = Path(d.src).name if d.src else "?"
            dur_str = fmt_time(self.video_duration) if self.video_duration > 0 else "?"
            res_str = (f"{self._src_w}x{self._src_h}"
                       if self._src_w and self._src_h else "?")
            prof = d.profile_name if d.profile_name else (self.profile_combo.currentText() or "—")
            self.preview_overlay.setText(
                f"<b>Source:</b> {name}<br>"
                f"<b>Duration:</b> {dur_str}<br>"
                f"<b>Resolution:</b> {res_str}<br>"
                f"<b>Codec:</b> {codec}<br>"
                f"<b>Profile:</b> {prof}"
            )
            self.preview_overlay.adjustSize()
            self.preview_overlay.move(12, 12)
            self.preview_overlay.show()
            self.preview_overlay.raise_()
        else:
            self.preview_overlay.hide()

    def _schedule_preview(self, *_):
        self.preview_timer.start()

    def _collect_opts(self) -> dict:
        res = RESOLUTIONS[self.out_res.currentText()]
        out_w, out_h = (res if res else (0, 0))
        wm = self.wm_path.text().strip()
        vid_wm = self.vid_wm_path.text().strip()
        vid_wm_path = vid_wm if vid_wm and os.path.exists(vid_wm) else None
        # Probe the watermark's own duration so the preview can wrap the
        # main scrub time inside it (e.g. a 10s WM at main_seek=25 shows
        # the WM's frame at 5s). Cached probes are essentially free on
        # repeat calls.
        vid_wm_duration = 0.0
        if vid_wm_path and self.ffprobe:
            vid_wm_duration = cached_probe_duration(self.ffprobe, vid_wm_path)
        return {
            "trim_start": self.trim_start.value(),
            "trim_end": self.trim_end.value(),
            "watermark_path": wm if wm and os.path.exists(wm) else None,
            "wm_preset": self.wm_preset.currentText(),
            "wm_offset_x": self.wm_off_x.value(),
            "wm_offset_y": self.wm_off_y.value(),
            "wm_padding": self.wm_padding.value(),
            "wm_opacity": self.wm_opacity.value() / 100.0,
            "wm_scale": self.wm_scale.value() / 100.0,
            "text_wm_text": self.text_wm_text.text(),
            "text_wm_size": self.text_wm_size.value(),
            "text_wm_color": self._text_color,
            "text_wm_preset": self.text_wm_preset.currentText(),
            "text_wm_offset_x": self.text_wm_off_x.value(),
            "text_wm_offset_y": self.text_wm_off_y.value(),
            "text_wm_padding": self.text_wm_padding.value(),
            "text_wm_opacity": self.text_wm_opacity.value() / 100.0,
            "out_w": out_w,
            "out_h": out_h,
            "encoder": self._resolve_encoder(),
            "speed_tier": self.out_quality.currentText(),
            "force_stereo": self.force_stereo.isChecked(),
            "loudnorm": self.loudnorm.isChecked(),
            "speed": float(self.speed_value.value()),
            "out_pattern": (self.out_pattern.text().strip()
                            or "{name}_edited"),
            "fade_in": float(self.fade_in.value()),
            "fade_out": float(self.fade_out.value()),
            "hw_decode": self.hw_decode.isChecked(),
            # V14.3.0: parallel CPU encoder slot toggle.
            "use_cpu_alongside_gpu":
                self.use_cpu_alongside_gpu.isChecked(),
            # V14.8.0: power-user FFmpeg-args passthrough. Plain string
            # — parsed via shlex.split at encode time in batch.py so
            # quoted values survive intact.
            "custom_ffmpeg_args":
                self.custom_ffmpeg_args.text().strip(),
            # Split-on-length: limit each output's duration; oversized inputs
            # become Part1 / Part2 / ... at job-build time.
            "split_enabled": self.split_enabled.isChecked(),
            "max_length_s": float(self.split_max_minutes.value()) * 60.0,
            # Profile audio visuals (V11.5): an ordered list of images and
            # videos used round-robin for audio inputs when enabled.
            "profile_visuals_enabled": self.profile_visuals_enabled.isChecked(),
            "profile_visuals": self._pv_to_list(),
            # V14.0: audio-visual template (key, not display name).
            "audio_template": self.audio_template_combo.currentData() or "none",
            # V12.3.1: video / audio quality is now a tier dropdown.
            # Resolve to the actual kbps the engine consumes; this also
            # depends on the chosen output resolution for video.
            "video_bitrate_kbps": resolve_video_bitrate_kbps(
                self.video_quality.currentText(), out_w, out_h),
            "audio_bitrate_kbps": resolve_audio_bitrate_kbps(
                self.audio_quality.currentText()),
            # Keep the labels in opts too so log lines / show-config dumps
            # are readable, and the CLI/headless path can introspect them.
            "video_quality": self.video_quality.currentText(),
            "audio_quality": self.audio_quality.currentText(),
            "intro_path": self.intro_path.text().strip() or "",
            "outro_path": self.outro_path.text().strip() or "",
            "merge_audio_fade_s": float(self.merge_fade.value()),
            # Video watermark
            "video_wm_path": vid_wm_path,
            "video_wm_duration": vid_wm_duration,
            "vid_wm_preset": self.vid_wm_preset.currentText(),
            "vid_wm_offset_x": self.vid_wm_off_x.value(),
            "vid_wm_offset_y": self.vid_wm_off_y.value(),
            "vid_wm_padding": self.vid_wm_padding.value(),
            "vid_wm_opacity": self.vid_wm_opacity.value() / 100.0,
            "vid_wm_scale": self.vid_wm_scale.value() / 100.0,
        }

    def _refresh_preview(self):
        # Stop any pending debounced refresh so a release-then-timer-fire
        # combo doesn't render the same frame twice.
        self.preview_timer.stop()
        if not self.ffmpeg:
            return
        d, _item = self._current_video()
        if not d or not os.path.exists(d.src):
            # V14.0.2 fix: empty queue / missing source — clear the
            # static thumbnail back to the placeholder, hide the V14.0
            # metadata overlay, and (if a video was loaded) stop
            # playback so the QVideoWidget doesn't keep the old frame
            # visible. Previously the preview pane silently held the
            # last-rendered thumbnail and the overlay stayed stale.
            try:
                self.preview_label.clear()
                self.preview_label.setText(
                    "Add a video or audio file. "
                    "Drag the orange bars to set trim points.")
            except Exception:
                pass
            if hasattr(self, "preview_overlay") and self.preview_overlay:
                self.preview_overlay.hide()
            # If a previously-loaded video is playing in the
            # QVideoWidget overlay, stop it so the user sees the
            # placeholder text rather than a paused frame.
            if getattr(self, "_mp_player", None) is not None:
                try:
                    self._mp_player.stop()
                except Exception:
                    pass
            if getattr(self, "_mp_video_widget", None) is not None:
                try:
                    self._mp_video_widget.hide()
                except Exception:
                    pass
            return

        # For audio rows, bail early if no visual AND no audio template
        # is set. V14.3.2 fix: audio templates (waveform, spectrum,
        # neon ring, etc.) synthesise the visual from the audio itself
        # so they don't need a user-supplied ``visual_path``. Without
        # this branch the pane stayed on the "Right-click ... Change
        # Visual" placeholder even when the user had picked a template.
        if d.kind == "audio":
            _live_tpl = (self.audio_template_combo.currentData()
                         if hasattr(self, "audio_template_combo") else "none")
            _has_template = bool(_live_tpl) and _live_tpl != "none"
            _has_visual = (d.visual_path and os.path.exists(d.visual_path)
                           and d.visual_kind is not None)
            if not _has_template and not _has_visual:
                self.preview_label.setText(
                    "Pick an Audio Visuals template, or right-click the "
                    "queue item -> Change Visual.")
                return

        self._preview_seq = (self._preview_seq + 1) % 4
        out_path = str(Path(tempfile.gettempdir())
                       / f"veloxa_v10_preview_{self._preview_seq}.jpg")
        self.preview_path = out_path

        self._latest_preview_seq += 1
        seq = self._latest_preview_seq
        # V12.3 fix: when the row is pinned to a profile that's NOT the
        # one currently loaded in the header, render the preview using
        # THAT profile's saved opts — otherwise the preview shows the
        # live form's watermark/resolution while the encode would
        # actually use the row's profile, which is exactly the bug
        # ("preview always shows the main profile"). When the row's
        # profile == the loaded profile (or NO_PROFILE), keep using
        # live opts so the user can preview their unsaved tweaks.
        live_opts = self._collect_opts()
        active_profile = self.profile_combo.currentText()
        if (d.profile_name and d.profile_name != NO_PROFILE
                and d.profile_name != active_profile
                and d.profile_name in self.profiles):
            opts = self._opts_for_row(d.profile_name, live_opts)
        else:
            opts = live_opts

        # Spawn the FFmpeg call on a worker thread so the main loop never
        # blocks for the ~70 ms it takes per preview frame. Late results
        # from superseded workers are discarded by seq comparison.
        worker = PreviewWorker(
            kind=d.kind, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe,
            src=d.src, visual_path=d.visual_path, visual_kind=d.visual_kind,
            visual_duration=d.visual_duration, opts=opts, out_path=out_path,
            time_s=self.seek_time, src_w=self._src_w, src_h=self._src_h,
            seq=seq,
        )
        worker.finished_with_path.connect(self._on_preview_done)
        self._preview_workers.append(worker)
        worker.start()

    def _on_preview_done(self, out_path: str, ok: bool, seq: int):
        sender = self.sender()
        if sender:
            try:
                self._preview_workers.remove(sender)
            except ValueError:
                pass
            sender.wait(50)
            sender.deleteLater()
        # Discard if a newer preview request has already been issued.
        if seq != self._latest_preview_seq:
            return
        if ok and out_path == self.preview_path:
            # V11.5 fix: only now is it safe for resizeEvent / explicit
            # refresh to load the JPG off disk. Set the flag *before*
            # calling _render_preview_from_disk so the renderer sees it.
            self._has_preview_this_session = True
            self._render_preview_from_disk()
        else:
            self.preview_label.setText("Preview failed")

    def _render_preview_from_disk(self):
        # V11.5 fix: refuse to load anything off disk until at least one
        # preview has actually been rendered *this* session. Without this
        # gate, resizeEvent() fires when the window first appears and
        # blindly displays last session's leftover JPG.
        if not getattr(self, "_has_preview_this_session", False):
            return
        if not self.preview_path or not os.path.exists(self.preview_path):
            return
        pm = QPixmap(self.preview_path)
        if pm.isNull():
            return
        target = self.preview_frame.size() - QSize(8, 8)
        self.preview_label.setPixmap(pm.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render_preview_from_disk()

    # ====================================================== drag & drop

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        paths = [p for p in paths if p and Path(p).suffix.lower() in ALL_INPUT_EXTS]
        if paths:
            self._add_files(paths)

    # ====================================================== profiles

    def _load_profiles(self):
        raw = self.settings.value("profiles", "{}")
        try:
            data = json.loads(raw) if isinstance(raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        self.profiles = data if isinstance(data, dict) else {}
        self._ensure_profile_numbers()

    # -------------------------------------------- V14.10.0 profile numbers

    def _ensure_profile_numbers(self) -> bool:
        """Every profile carries a sticky ``shortcut_number`` (int >= 1,
        unique). Profiles from older versions (or imports) that lack a
        valid number -- or collide with an existing one -- get the
        lowest free number, assigned in alphabetical order so migration
        is deterministic. Returns True when anything changed (caller
        may persist)."""
        used: set = set()
        changed = False
        for name in sorted(self.profiles.keys(), key=str.lower):
            d = self.profiles[name]
            if not isinstance(d, dict):
                continue
            n = d.get("shortcut_number")
            if isinstance(n, int) and n >= 1 and n not in used:
                used.add(n)
            else:
                n = 1
                while n in used:
                    n += 1
                d["shortcut_number"] = n
                used.add(n)
                changed = True
        return changed

    def _profile_number(self, name: str):
        d = self.profiles.get(name)
        n = d.get("shortcut_number") if isinstance(d, dict) else None
        return n if isinstance(n, int) and n >= 1 else None

    def _profile_by_number(self, n: int):
        for name, d in self.profiles.items():
            if isinstance(d, dict) and d.get("shortcut_number") == n:
                return name
        return None

    def _set_profile_number(self, name: str, n: int):
        """Assign sticky number ``n`` to ``name``. If another profile
        already holds ``n``, the two profiles swap numbers -- no gaps,
        no duplicates, fully predictable."""
        if name not in self.profiles or n < 1:
            return
        holder = self._profile_by_number(n)
        old = self._profile_number(name)
        if holder and holder != name and old is not None:
            self.profiles[holder]["shortcut_number"] = old
        self.profiles[name]["shortcut_number"] = n

    def _store_profile(self, name: str, d: dict):
        """Assign a (re)collected settings dict to ``name`` while
        preserving an existing sticky shortcut number -- fresh dicts
        from ``_collect_settings_dict`` never carry one, and updating a
        profile must not cost it its number."""
        prev = self._profile_number(name)
        if prev is not None:
            d["shortcut_number"] = prev
        self.profiles[name] = d

    def _profile_label(self, name: str) -> str:
        """Display label for combos / menus: ``N. Name`` (raw name when
        the profile has no number, e.g. the NO_PROFILE sentinel)."""
        n = self._profile_number(name)
        return f"{n}. {name}" if n is not None else name

    def _profile_name_from_label(self, label: str) -> str:
        """Inverse of :meth:`_profile_label` for currentTextChanged
        handlers (Qt emits the DISPLAY text). Exact profile names win
        first so a profile literally called '12. Foo' round-trips."""
        if label in self.profiles or label == NO_PROFILE:
            return label
        m = re.match(r"^(\d+)\.\s(.*)$", label)
        if m and m.group(2) in self.profiles:
            return m.group(2)
        return label

    def _save_profiles(self):
        self.settings.setValue("profiles", json.dumps(self.profiles))

    def _refresh_profile_combo(self):
        # V14.10.0: newly created / imported profiles pick up a sticky
        # shortcut number here -- every mutation path funnels through
        # this refresh, so numbering can never drift.
        if self._ensure_profile_numbers():
            self._save_profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(NO_PROFILE, userData=NO_PROFILE)
        for name in sorted(self.profiles.keys(), key=str.lower):
            self.profile_combo.addItem(self._profile_label(name),
                                       userData=name)
        last = self.settings.value("last_profile", NO_PROFILE)
        idx = self.profile_combo.findText(last)
        self.profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.profile_combo.blockSignals(False)
        # The combo's signal was blocked during refresh, so update the
        # "Update Profile" button explicitly to reflect the new selection.
        # Guarded because this runs once during __init__ before the button
        # exists.
        if hasattr(self, "update_profile_btn"):
            self._update_profile_button_state()

    def _on_profile_changed(self, name):
        if self._suppress_change:
            return
        # currentTextChanged emits the display label ('N. Name') --
        # map back to the raw profile name (V14.10.0).
        name = self._profile_name_from_label(name)
        # Always reflect dropdown state, even when "(no profile)" selected.
        self._update_profile_button_state()
        if name == NO_PROFILE or name not in self.profiles:
            # Even for NO_PROFILE the rotation status (counter, list
            # size) should reflect the new context.
            self._pv_refresh_status()
            return
        self._apply_settings_dict(self.profiles[name])
        self.settings.setValue("last_profile", name)
        self.status_lbl.setText(f"Loaded profile: {name}")
        log.info("Profile loaded: %s", name)

    def _save_as_profile(self):
        current = self.profile_combo.currentText()
        suggested = current if current != NO_PROFILE else ""
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:", text=suggested)
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.information(self, "Save Profile", "Name cannot be empty.")
            return
        if name == NO_PROFILE:
            QMessageBox.information(self, "Save Profile", "Reserved name.")
            return
        if name in self.profiles:
            r = QMessageBox.question(
                self, "Overwrite?",
                f"Profile '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        d = self._collect_settings_dict()
        # V11.1: copy referenced asset files (watermark image, watermark
        # video) into the profile's in-app asset folder so the profile
        # survives the user moving / deleting the originals.
        d = copy_assets_into_profile(name, d)
        self._store_profile(name, d)
        self._save_profiles()
        self._refresh_profile_combo()
        idx = self.profile_combo.findText(name)
        if idx >= 0:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentIndex(idx)
            self.profile_combo.blockSignals(False)
        self.settings.setValue("last_profile", name)
        # Also update the open form to reflect the rewritten in-app paths
        # so a subsequent "Update Profile" click doesn't see them as stale.
        self._apply_settings_dict(d)
        # V11.5: every per-row profile picker should now show the new
        # profile in its dropdown.
        self._refresh_all_row_widgets()
        self.status_lbl.setText(f"Saved profile: {name}")
        log.info("Profile saved: %s", name)

    def _delete_profile(self):
        name = self.profile_combo.currentText()
        if name == NO_PROFILE or name not in self.profiles:
            QMessageBox.information(self, "Delete Profile",
                                    "Select a profile to delete.")
            return
        r = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        del self.profiles[name]
        self._save_profiles()
        # V11.1: also wipe the on-disk asset folder for this profile so
        # we don't leave orphaned megabytes of watermark images sitting
        # in %APPDATA%.
        try:
            delete_profile_assets(name)
        except Exception as exc:
            log.warning("delete_profile_assets(%r) failed: %s", name, exc)
        # V11.5: also clear the per-profile audio-visual rotation counter
        # so a future profile re-using this name starts fresh at #1.
        try:
            self.settings.remove(self._pv_counter_key(name))
        except Exception:
            pass
        self._refresh_profile_combo()
        # V12.3 audit fix (E3): route through _rebase_queue_rows so the
        # current row's preview also refreshes after a header-bar delete
        # (the old inline loop only updated the row widget, leaving the
        # preview pane / info bar showing the deleted profile until the
        # user clicked something else).
        self._rebase_queue_rows(deleted={name})
        self._refresh_all_row_widgets()
        self.status_lbl.setText(f"Deleted profile: {name}")
        log.info("Profile deleted: %s", name)

    def _collect_settings_dict(self) -> dict:
        return {
            "trim_start": self.trim_start.value(),
            "trim_end": self.trim_end.value(),
            "wm_path": self.wm_path.text(),
            "wm_preset": self.wm_preset.currentText(),
            "wm_off_x": self.wm_off_x.value(),
            "wm_off_y": self.wm_off_y.value(),
            "wm_padding": self.wm_padding.value(),
            "wm_opacity": self.wm_opacity.value(),
            "wm_scale": self.wm_scale.value(),
            "text_wm_text": self.text_wm_text.text(),
            "text_wm_size": self.text_wm_size.value(),
            "text_wm_color": self._text_color,
            "text_wm_preset": self.text_wm_preset.currentText(),
            "text_wm_off_x": self.text_wm_off_x.value(),
            "text_wm_off_y": self.text_wm_off_y.value(),
            "text_wm_padding": self.text_wm_padding.value(),
            "text_wm_opacity": self.text_wm_opacity.value(),
            "out_codec": self._codec_value(),
            "out_encoder": self.out_encoder.currentText(),
            "out_quality": self.out_quality.currentText(),
            "out_res": self.out_res.currentText(),
            "parallel_jobs": self.parallel_jobs.value(),
            "force_stereo": self.force_stereo.isChecked(),
            "loudnorm": self.loudnorm.isChecked(),
            "speed": float(self.speed_value.value()),
            "out_pattern": self.out_pattern.text(),
            "fade_in": float(self.fade_in.value()),
            "fade_out": float(self.fade_out.value()),
            "hw_decode": self.hw_decode.isChecked(),
            # V14.8.0: power-user FFmpeg-args passthrough.
            "custom_ffmpeg_args":
                self.custom_ffmpeg_args.text().strip(),
            "split_enabled": self.split_enabled.isChecked(),
            "split_max_minutes": float(self.split_max_minutes.value()),
            "profile_visuals_enabled": self.profile_visuals_enabled.isChecked(),
            "profile_visuals": self._pv_to_list(),
            # V14.0: audio-visual template selection.
            "audio_template": self.audio_template_combo.currentData() or "none",
            # V12.3.1: quality stored as the dropdown label. The numeric
            # kbps is derived at job-build time from (tier, resolution)
            # so a profile saved at 1080p that gets used to encode a 4K
            # source picks the right bitrate automatically.
            "video_quality": self.video_quality.currentText(),
            "audio_quality": self.audio_quality.currentText(),
            "intro_path": self.intro_path.text().strip() or "",
            "outro_path": self.outro_path.text().strip() or "",
            "merge_audio_fade_s": float(self.merge_fade.value()),
            "vid_wm_path": self.vid_wm_path.text(),
            "vid_wm_preset": self.vid_wm_preset.currentText(),
            "vid_wm_off_x": self.vid_wm_off_x.value(),
            "vid_wm_off_y": self.vid_wm_off_y.value(),
            "vid_wm_padding": self.vid_wm_padding.value(),
            "vid_wm_opacity": self.vid_wm_opacity.value(),
            "vid_wm_scale": self.vid_wm_scale.value(),
        }

    def _apply_settings_dict(self, d: dict):
        self._suppress_change = True
        try:
            self.trim_start.setValue(float(d.get("trim_start", 0.0)))
            # V11.5 fix: default to 0.0, not 2.40. The old default silently
            # chopped 2.4s off the end of every output for any profile that
            # didn't explicitly carry trim_end (e.g. fresh launches and
            # legacy / minimal profiles), which looked like "trim from end
            # not working".
            self.trim_end.setValue(float(d.get("trim_end", 0.0)))
            self.wm_path.setText(d.get("wm_path", "") or "")
            self.wm_preset.setCurrentText(d.get("wm_preset", "Bottom-Right"))
            self.wm_off_x.setValue(int(d.get("wm_off_x", 0)))
            self.wm_off_y.setValue(int(d.get("wm_off_y", 0)))
            self.wm_padding.setValue(int(d.get("wm_padding", 20)))
            self.wm_opacity.setValue(int(d.get("wm_opacity", 100)))
            self.wm_scale.setValue(int(d.get("wm_scale", 15)))

            self.text_wm_text.setText(d.get("text_wm_text", "") or "")
            self.text_wm_size.setValue(int(d.get("text_wm_size", 36)))
            self._text_color = d.get("text_wm_color", "#ffffff") or "#ffffff"
            self.text_wm_color_swatch.setStyleSheet(
                f"background:{self._text_color}; border:1px solid #454952; "
                f"border-radius:3px;")
            self.text_wm_preset.setCurrentText(
                d.get("text_wm_preset", "Bottom-Left"))
            self.text_wm_off_x.setValue(int(d.get("text_wm_off_x", 0)))
            self.text_wm_off_y.setValue(int(d.get("text_wm_off_y", 0)))
            self.text_wm_padding.setValue(int(d.get("text_wm_padding", 20)))
            self.text_wm_opacity.setValue(int(d.get("text_wm_opacity", 100)))

            codec = d.get("out_codec", CODEC_H264)
            self._set_codec(codec)
            self._refresh_encoder_combo()
            enc = d.get("out_encoder", AUTO_ENCODER)
            if self.out_encoder.findText(enc) >= 0:
                self.out_encoder.setCurrentText(enc)
            else:
                self.out_encoder.setCurrentText(AUTO_ENCODER)
            self.out_quality.setCurrentText(d.get("out_quality", "Balanced"))
            self.out_res.setCurrentText(d.get("out_res", "4K (3840x2160)"))
            jobs = int(d.get("parallel_jobs", 1))
            self.parallel_jobs.setValue(max(1, min(2, jobs)))
            self.force_stereo.setChecked(bool(d.get("force_stereo", True)))
            self.loudnorm.setChecked(bool(d.get("loudnorm", False)))
            self.speed_value.setValue(float(d.get("speed", 1.0) or 1.0))
            # Pattern with back-compat: pre-V11 profiles have "out_suffix"
            # like "_edited"; build a pattern from it if no pattern is set.
            pattern = d.get("out_pattern", "")
            if not pattern:
                old_suffix = d.get("out_suffix", "_edited")
                pattern = "{name}" + old_suffix
            self.out_pattern.setText(pattern)
            self.fade_in.setValue(float(d.get("fade_in", 0.0) or 0.0))
            self.fade_out.setValue(float(d.get("fade_out", 0.0) or 0.0))
            self.hw_decode.setChecked(bool(d.get("hw_decode", True)))
            # V14.8.0: profile-level custom FFmpeg args passthrough.
            self.custom_ffmpeg_args.setText(
                d.get("custom_ffmpeg_args", "") or "")
            # V14.3.0: profile-level persistence of the parallel CPU slot.
            self.use_cpu_alongside_gpu.setChecked(
                bool(d.get("use_cpu_alongside_gpu", False)))
            self.split_enabled.setChecked(bool(d.get("split_enabled", False)))
            self.split_max_minutes.setValue(
                float(d.get("split_max_minutes", 10.0) or 10.0))
            # V11.5: profile audio visuals.
            self.profile_visuals_enabled.setChecked(
                bool(d.get("profile_visuals_enabled", False)))
            self._pv_apply(d.get("profile_visuals") or [])
            # V14.0: restore audio-visual template selection.
            template_key = d.get("audio_template") or "none"
            idx = self.audio_template_combo.findData(template_key)
            if idx < 0:
                idx = 0
            self.audio_template_combo.setCurrentIndex(idx)
            # V12.3.1: quality tier (string label). Back-compat: profiles
            # saved under the V12.3 numeric-bitrate UI carry
            # ``video_bitrate_kbps`` / ``audio_bitrate_kbps`` ints — map
            # those to the nearest tier label so loading an old profile
            # still selects something sensible.
            vq = d.get("video_quality")
            if not vq:
                vq = kbps_to_video_quality_tier(
                    int(d.get("video_bitrate_kbps", 0) or 0))
            if vq not in VIDEO_QUALITY_TIERS:
                vq = VIDEO_QUALITY_DEFAULT
            self.video_quality.setCurrentText(vq)
            aq = d.get("audio_quality")
            if not aq:
                aq = kbps_to_audio_quality_tier(
                    int(d.get("audio_bitrate_kbps", 0) or 0))
            if aq not in AUDIO_QUALITY_TIERS:
                aq = AUDIO_QUALITY_DEFAULT
            self.audio_quality.setCurrentText(aq)
            self.intro_path.setText(d.get("intro_path", "") or "")
            self.outro_path.setText(d.get("outro_path", "") or "")
            self.merge_fade.setValue(float(d.get("merge_audio_fade_s", 0.0) or 0.0))
            self.vid_wm_path.setText(d.get("vid_wm_path", "") or "")
            self.vid_wm_preset.setCurrentText(d.get("vid_wm_preset", "Top-Right"))
            self.vid_wm_off_x.setValue(int(d.get("vid_wm_off_x", 0)))
            self.vid_wm_off_y.setValue(int(d.get("vid_wm_off_y", 0)))
            self.vid_wm_padding.setValue(int(d.get("vid_wm_padding", 20)))
            self.vid_wm_opacity.setValue(int(d.get("vid_wm_opacity", 100)))
            self.vid_wm_scale.setValue(int(d.get("vid_wm_scale", 20)))
        finally:
            self._suppress_change = False

    # ====================================================== codec / encoder

    def _codec_value(self) -> str:
        return self.out_codec.currentData() or CODEC_H264

    def _set_codec(self, codec: str):
        for i in range(self.out_codec.count()):
            if self.out_codec.itemData(i) == codec:
                self.out_codec.setCurrentIndex(i)
                return

    def _refresh_encoder_combo(self):
        codec = self._codec_value()
        prev_choice = (self.out_encoder.currentText()
                       if self.out_encoder.count() else AUTO_ENCODER)
        self.out_encoder.blockSignals(True)
        self.out_encoder.clear()
        self.out_encoder.addItem(AUTO_ENCODER)
        valid = [e for e in ENCODER_FOR_CODEC[codec]
                 if e in self.available_encoders]
        seen_labels = set()
        for name in valid:
            label = ENCODER_LABELS.get(name, name)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            self.out_encoder.addItem(label, userData=name)
        idx = self.out_encoder.findText(prev_choice)
        self.out_encoder.setCurrentIndex(idx if idx >= 0 else 0)
        self.out_encoder.blockSignals(False)

    def _resolve_encoder(self) -> str:
        codec = self._codec_value()
        # V14.7.0: AV1 picks NVENC/AMF/QSV first then libsvtav1; the
        # CPU fallback is "libsvtav1" rather than libx26x because AV1
        # output requires an AV1 encoder. If no AV1 encoder is
        # available (older FFmpeg + no AV1 GPU), the encoder dropdown
        # won't have any usable item and (auto) silently degrades to
        # the H.264 default so the encode doesn't fail outright.
        if codec == CODEC_AV1:
            priority = AUTO_PRIORITY_AV1
            cpu_fallback = "libsvtav1"
        elif codec == CODEC_HEVC:
            priority = AUTO_PRIORITY_HEVC
            cpu_fallback = "libx265"
        else:
            priority = AUTO_PRIORITY_H264
            cpu_fallback = "libx264"
        if self.out_encoder.currentText() == AUTO_ENCODER:
            for name in priority:
                if name in self.available_encoders:
                    return name
            # AV1 has no guaranteed CPU fallback (libsvtav1 not in every
            # FFmpeg build) — drop to libx264 so the encode at least
            # produces a valid file, with a log line so support can
            # diagnose later.
            if cpu_fallback in self.available_encoders:
                return cpu_fallback
            log.warning("No %s encoder available on this PC; falling "
                        "back to libx264", codec)
            return "libx264"
        idx = self.out_encoder.currentIndex()
        data = self.out_encoder.itemData(idx)
        if data:
            return data
        return (cpu_fallback if cpu_fallback in self.available_encoders
                else "libx264")

    # ====================================================== batch encode

    def _dst_for(self, src: str, batch_idx: int = 0,
                 part_no: int = 1, n_parts: int = 1,
                 opts_override: dict = None) -> str:
        """Resolve the output filename for ``src`` using the user's pattern.

        Pattern placeholders: {name}, {ext}, {date}, {time}, {codec},
        {encoder}, {quality}, {resolution}, {n}, {part}, {parts}.
        Falls back to ``{name}_edited`` if the pattern is empty or
        malformed. When splitting is active and the pattern doesn't
        include ``{part}``, ``_PartN`` is appended automatically. ``.mp4``
        is appended if the pattern doesn't already end in it.

        V11.5: ``opts_override`` lets a caller (specifically
        :meth:`_build_jobs`) request the filename to be computed from a
        DIFFERENT profile's settings — used so a row pinned to a non-
        active profile picks up that profile's pattern and resolution
        placeholders, not the live form's.
        """
        from datetime import datetime
        sp = Path(src)
        if opts_override is not None:
            opts = opts_override
            pattern = (opts.get("out_pattern") or "").strip() or "{name}_edited"
        else:
            pattern = (self.out_pattern.text().strip() or "{name}_edited")
            opts = self._collect_opts()
        now = datetime.now()
        out_w = opts.get("out_w") or 0
        out_h = opts.get("out_h") or 0
        placeholders = {
            "name": sp.stem,
            "ext": sp.suffix.lstrip("."),
            "date": now.strftime("%Y%m%d"),
            "time": now.strftime("%H%M%S"),
            "codec": str(opts.get("encoder") or "").split("_")[0]
                     or self._codec_value(),
            "encoder": opts.get("encoder", "auto"),
            "quality": (opts.get("speed_tier") or "Balanced")
                       .lower().replace(" ", "_"),
            "resolution": (f"{out_w}x{out_h}" if out_w and out_h else "src"),
            "n": batch_idx + 1,
            "part": part_no,
            "parts": n_parts,
        }
        try:
            result = pattern.format_map(placeholders)
        except (KeyError, ValueError, IndexError):
            result = sp.stem + "_edited"
        # Auto-append _PartN when splitting is on and the user's pattern
        # doesn't already place the part number explicitly.
        if n_parts > 1 and "{part" not in pattern:
            if result.lower().endswith(".mp4"):
                result = result[:-4] + f"_Part{part_no}.mp4"
            else:
                result = result + f"_Part{part_no}"
        # Strip path separators the user accidentally put in the pattern.
        result = result.replace("/", "_").replace("\\", "_")
        if not result.lower().endswith(".mp4"):
            result += ".mp4"
        return str(sp.parent / result)

    def _opts_for_row(self, profile_name: str, live_opts: dict) -> dict:
        """V11.5: resolve the opts a queue row should encode with.

        ``profile_name`` is the row's per-row assignment. NO_PROFILE or
        an unknown name falls back to ``live_opts`` (the active form's
        opts). Saved profiles are translated through
        :func:`profile_to_opts` and cached on the call stack.
        """
        if not profile_name or profile_name == NO_PROFILE:
            return live_opts
        if profile_name not in self.profiles:
            log.info("Row pinned to unknown profile %r — using live form",
                     profile_name)
            return live_opts
        cache = getattr(self, "_row_opts_cache", None)
        if cache is None:
            cache = {}; self._row_opts_cache = cache
        if profile_name in cache:
            return cache[profile_name]
        from .profile_opts import profile_to_opts
        try:
            resolved = profile_to_opts(self.profiles[profile_name],
                                        self.available_encoders)
        except Exception as exc:
            log.warning("profile_to_opts failed for %r: %s", profile_name, exc)
            resolved = live_opts
        cache[profile_name] = resolved
        return resolved

    def _build_jobs(self, opts) -> list:
        jobs = []
        seen_dsts = set()  # number duplicates so we never silently overwrite
        batch_idx = 0
        next_runner_idx = 0
        # Map JobRunner idx -> file_list row, so signal handlers can find
        # the right list item when a single source becomes multiple jobs.
        self._runner_to_row = {}
        # Reset the per-row opts cache so a newly-saved profile is picked
        # up on the next Start (rather than stale opts from earlier).
        self._row_opts_cache = {}

        # V11.5: per-profile rotation counters. Each row's profile keeps
        # its own counter; many profiles in one batch -> many counters
        # advance independently, all persisted at the end.
        rotation_local = {}    # profile_name -> running advance
        rotation_seeded = {}   # profile_name -> bool

        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            d = self._item_data(item)
            if not d:
                continue
            # Skip already-completed items so re-running a partial batch
            # doesn't re-encode finished files.
            if d.status == "done":
                continue

            # V11.5: every setting (codec, trim, fades, watermark,
            # rotation, split, pattern…) should come from THIS row's
            # profile. Compute the resolved opts once per row.
            row_opts = self._opts_for_row(d.profile_name, opts)
            rot_key = d.profile_name or NO_PROFILE

            # Profile audio-visual rotation, computed from row_opts.
            pv_enabled = bool(row_opts.get("profile_visuals_enabled", False))
            pv_list = [v for v in (row_opts.get("profile_visuals") or [])
                       if isinstance(v, dict) and v.get("path")
                       and os.path.exists(v.get("path"))]
            if not rotation_seeded.get(rot_key):
                rotation_local[rot_key] = (
                    self._pv_get_counter(rot_key) if pv_list else 0)
                rotation_seeded[rot_key] = True

            # Pick visual from rotation when applicable.
            visual_path = d.visual_path
            visual_kind = d.visual_kind
            # V14.3.5: only rotate when the row has NO visual yet.
            # ``_auto_assign_audio_visuals_for_new`` may have already
            # filled in visual_path at add-time and advanced the counter
            # — running rotation again here would double-advance and
            # silently overwrite the user's just-assigned visual.
            already_has_visual = bool(
                visual_path and os.path.exists(visual_path))
            if (d.kind == "audio" and pv_enabled and pv_list
                    and not already_has_visual):
                idx_pick = rotation_local[rot_key]
                pick = pv_list[idx_pick % len(pv_list)]
                visual_path = pick.get("path")
                visual_kind = pick.get("kind") or "image"
                rotation_local[rot_key] = idx_pick + 1

            # Split-on-length: from row_opts so each row uses its own
            # profile's split settings.
            max_length_s = float(row_opts.get("max_length_s") or 0.0)
            split_enabled = (bool(row_opts.get("split_enabled", False))
                             and max_length_s > 0)

            parts = []
            if split_enabled and self.ffprobe and os.path.exists(d.src):
                try:
                    src_dur = cached_probe_duration(self.ffprobe, d.src)
                except Exception:
                    src_dur = 0.0
                trim_s = float(row_opts.get("trim_start", 0.0) or 0.0)
                trim_e = float(row_opts.get("trim_end", 0.0) or 0.0)
                usable = max(0.0, src_dur - trim_s - trim_e)
                if src_dur > 0 and usable > max_length_s:
                    n_parts = int(usable // max_length_s) + (
                        1 if (usable % max_length_s) > 0.05 else 0)
                    for k in range(n_parts):
                        off = trim_s + k * max_length_s
                        dur = min(max_length_s,
                                  max(0.0, src_dur - off - trim_e))
                        if dur > 0.05:
                            parts.append((off, dur))
            if not parts:
                parts = [(None, None)]

            n_parts_total = len(parts)
            for part_no, (clip_off, clip_dur) in enumerate(parts, start=1):
                # Use the row's profile opts when computing the dst, so
                # the filename pattern + resolution placeholders match
                # the encode that's about to run.
                dst = self._dst_for(d.src, batch_idx=batch_idx,
                                    part_no=part_no, n_parts=n_parts_total,
                                    opts_override=row_opts)
                batch_idx += 1
                if dst in seen_dsts:
                    from pathlib import Path as _P
                    base = _P(dst)
                    n = 2
                    while True:
                        cand = str(base.with_name(
                            f"{base.stem}_{n}{base.suffix}"))
                        if cand not in seen_dsts:
                            dst = cand
                            break
                        n += 1
                seen_dsts.add(dst)

                # V11.5: per-row override = (row's profile opts when
                # different from the live form) ∪ (clip override from
                # split). JobRunner does {**opts, **per_job_opts} so the
                # row's profile fully wins.
                per_job = None
                if (d.profile_name and d.profile_name != NO_PROFILE
                        and d.profile_name in self.profiles):
                    per_job = dict(row_opts)
                if clip_dur is not None:
                    if per_job is None:
                        per_job = {}
                    per_job["clip_offset_s"] = clip_off
                    per_job["clip_duration_s"] = clip_dur
                # V12.3: when split-on-length produces multiple parts,
                # the intro should ride only on Part 1 and the outro on
                # the LAST part so the series book-ends correctly. For
                # single-part rows (no split), both flags default to
                # True so the merge applies once.
                if n_parts_total > 1:
                    if per_job is None:
                        per_job = {}
                    per_job["apply_intro"] = (part_no == 1)
                    per_job["apply_outro"] = (part_no == n_parts_total)

                # JobRunner idx must be unique across the batch; the source
                # row index ``i`` is shared by all parts of the same input
                # so we use a separate counter and remember the mapping.
                self._runner_to_row[next_runner_idx] = i
                jobs.append((next_runner_idx, d.src, dst, d.kind,
                             visual_path, visual_kind, per_job))
                next_runner_idx += 1

        # V11.5: persist every per-profile rotation counter that
        # actually advanced this batch. Profiles whose rotation didn't
        # fire (no matching audio rows, or pv_enabled=False) are left
        # alone. This works in the multi-profile case too: row #1 in
        # profile A might advance A's counter while row #2 in profile B
        # advances B's, and both get saved.
        for pname, advanced in rotation_local.items():
            if not rotation_seeded.get(pname):
                continue
            # Only persist if the counter actually moved, to avoid
            # gratuitous QSettings churn for batches that touched no
            # audio rows under that profile.
            if advanced != self._pv_get_counter(pname):
                self._pv_set_counter(pname, advanced)
        return jobs

    def _build_jobs_for_items(self, items: list, opts: dict) -> list:
        """V14.3.0: build job tuples for a SUBSET of queue items, used
        by the "add files during batch" flow. Differences from the
        full :meth:`_build_jobs`:

        * Uses ``max(self._runner_to_row)+1`` as the starting runner
          index, so we don't collide with runners already in flight.
        * Does NOT advance per-profile audio-visual rotation counters
          (the running batch already seeded them; we just reuse the
          current count for newly-added rows).
        * Does NOT honour split-on-length for the new rows — if the
          user wants to split mid-batch additions they can stop +
          restart the batch. Keeps this helper trivially safe.

        Returns a list of job tuples in the same shape JobRunner /
        BatchManager expect.
        """
        if not items:
            return []
        existing_runner_idxs = list(getattr(self, "_runner_to_row", {}).keys())
        next_runner_idx = (max(existing_runner_idxs) + 1
                           if existing_runner_idxs else 0)
        if not hasattr(self, "_runner_to_row"):
            self._runner_to_row = {}
        jobs = []
        for item in items:
            d = self._item_data(item)
            if not d:
                continue
            if d.status == "done":
                continue
            row_opts = self._opts_for_row(d.profile_name, opts)
            dst = self._dst_for(d.src, batch_idx=0,
                                part_no=1, n_parts=1,
                                opts_override=row_opts)
            per_job = None
            if (d.profile_name and d.profile_name != NO_PROFILE
                    and d.profile_name in self.profiles):
                per_job = dict(row_opts)
            # Map runner idx -> file_list row index for signal routing.
            try:
                row = self.file_list.row(item)
            except Exception:
                row = -1
            self._runner_to_row[next_runner_idx] = row
            jobs.append((next_runner_idx, d.src, dst, d.kind,
                         d.visual_path, d.visual_kind, per_job))
            next_runner_idx += 1
        return jobs

    def _start_batch(self):
        # Ctrl+Enter shortcut bypasses the disabled Start button, so refuse
        # here when a batch is already in flight to avoid orphaning the
        # currently-running BatchManager.
        if self.batch and self.batch.is_running():
            self.status_lbl.setText("A batch is already running")
            return
        if not self.ffmpeg:
            QMessageBox.critical(self, "FFmpeg Missing",
                                 "FFmpeg is required.")
            return
        if self.file_list.count() == 0:
            QMessageBox.information(self, "No Files", "Add at least one file.")
            return

        # Audio jobs need a visual. V11.5: a row can also satisfy this
        # via its profile's rotation list, so consider that branch too
        # before flagging the row as missing.
        missing = []
        live_opts = self._collect_opts()
        # Rebuild the per-row opts cache fresh for this validation pass.
        self._row_opts_cache = {}
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if not (d and d.kind == "audio" and d.status != "done"):
                continue
            row_opts = self._opts_for_row(d.profile_name, live_opts)
            pv_enabled = bool(row_opts.get("profile_visuals_enabled", False))
            pv_list = [v for v in (row_opts.get("profile_visuals") or [])
                       if isinstance(v, dict) and v.get("path")
                       and os.path.exists(v.get("path"))]
            has_per_row = (d.visual_path
                           and os.path.exists(d.visual_path))
            has_rotation = pv_enabled and bool(pv_list)
            if not (has_per_row or has_rotation):
                missing.append(Path(d.src).name)
        if missing:
            QMessageBox.warning(
                self, "Missing Visual",
                "These audio files have no visual set:\n\n"
                + "\n".join(missing[:10])
                + ("\n..." if len(missing) > 10 else "")
                + "\n\nRight-click an item and pick 'Change Visual...' to set one.")
            return

        # Source files must exist (queue restore from a previous session can
        # leave stale entries pointing at moved/deleted files).
        missing_src = []
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if d and d.status != "done" and not os.path.exists(d.src):
                missing_src.append(d.src)
        if missing_src:
            QMessageBox.warning(
                self, "Missing Source Files",
                "These source files no longer exist on disk:\n\n"
                + "\n".join(Path(p).name for p in missing_src[:10])
                + ("\n..." if len(missing_src) > 10 else "")
                + "\n\nRemove them from the queue or restore them.")
            return

        # Watermark image: text in the box but file missing -> silently
        # encoding without the watermark would surprise the user.
        wm = self.wm_path.text().strip()
        if wm and not os.path.exists(wm):
            r = QMessageBox.question(
                self, "Watermark Image Missing",
                f"The watermark image is set but not found:\n\n{wm}\n\n"
                "Continue without the image watermark?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
            self.wm_path.setText("")

        vid_wm = self.vid_wm_path.text().strip()
        if vid_wm and not os.path.exists(vid_wm):
            r = QMessageBox.question(
                self, "Video Watermark Missing",
                f"The video watermark is set but not found:\n\n{vid_wm}\n\n"
                "Continue without the video watermark?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
            self.vid_wm_path.setText("")

        opts = self._collect_opts()
        jobs = self._build_jobs(opts)
        if not jobs:
            QMessageBox.information(
                self, "Nothing to do",
                "All items in the queue are already marked DONE. "
                "Use 'Remove Completed' to clear them, or add new files.")
            return

        clashes = [d for _, s, d, *_ in jobs
                   if Path(s).resolve() == Path(d).resolve()]
        if clashes:
            QMessageBox.critical(
                self, "Output Conflict",
                "Output filename matches the source for one or more files. "
                "Set a non-empty filename suffix.")
            return

        existing = [d for _, s, d, *_ in jobs if Path(d).exists()]
        if existing:
            r = QMessageBox.question(
                self, "Overwrite?",
                f"{len(existing)} output file(s) already exist. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return

        # Reset state for items that are about to run.
        running_indices = {idx for idx, *_ in jobs}
        for i in range(self.file_list.count()):
            if i not in running_indices:
                continue
            d = self._item_data(self.file_list.item(i))
            if d:
                d.status = "pending"
                d.progress = 0.0
                d.eta = -1.0
                d.error = ""
                self._refresh_item_label(self.file_list.item(i))

        self.batch = BatchManager(jobs, self.parallel_jobs.value(),
                                  self.ffmpeg, self.ffprobe, opts)
        self.batch.file_started.connect(self._on_file_started)
        self.batch.file_progress.connect(self._on_file_progress)
        self.batch.file_eta.connect(self._on_file_eta)
        self.batch.file_finished.connect(self._on_file_finished)
        self.batch.file_retrying.connect(self._on_file_retrying)
        self.batch.batch_finished.connect(self._on_batch_finished)
        # V12.3: keep the pause-button label / status synced with the
        # BatchManager's actual pause flag.
        self.batch.paused_changed.connect(self._on_paused_changed)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("⏸ Pause")
        self._set_queue_locked(True)
        self.progress.setValue(0)
        # Reset total-ETA tracking for this batch.
        self._batch_t_start = time.monotonic()
        self._batch_completed = 0
        self._batch_total = len(jobs)
        # Per-row split-completion tally (used to decide when a row goes
        # from "encoding" to "done" once all of its parts finish).
        self._row_completed = {}
        self.total_eta_lbl.setText("Total ETA: estimating...")
        self.status_lbl.setText(
            f"Encoding {len(jobs)} file(s) "
            f"({self.parallel_jobs.value()} parallel)...")
        self._save_queue_state()
        self.batch.start()

    def _cancel_batch(self):
        if self.batch:
            # V12.3 audit fix: disable the pause button immediately on
            # Cancel so the user can't click it during the brief window
            # between cancel() returning and _on_batch_finished firing
            # (the active runner takes a moment to actually exit). The
            # button gets re-enabled on the next _start_batch.
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.batch.cancel()
            self.status_lbl.setText("Cancelling...")

    def _row_for_runner(self, idx: int) -> int:
        """Map a JobRunner idx back to its file_list row. With the split-on-
        length feature one source may become multiple jobs, so this lookup
        replaces ``self.file_list.item(idx)`` everywhere.
        """
        m = getattr(self, "_runner_to_row", None) or {}
        return m.get(idx, idx)

    def _on_file_started(self, idx, _path):
        row = self._row_for_runner(idx)
        item = self.file_list.item(row)
        d = self._item_data(item)
        if d:
            d.status = "encoding"
            d.progress = 0.0
            d.error = ""
            self._refresh_item_label(item)
        self._save_queue_state()

    def _on_file_progress(self, idx, pct):
        row = self._row_for_runner(idx)
        item = self.file_list.item(row)
        d = self._item_data(item)
        if d:
            d.progress = pct
            # Throttle the per-row label refresh to ~7 Hz so a high-frequency
            # progress stream from FFmpeg doesn't spam QListWidget repaints.
            # The 100% landing always lands so the row settles correctly.
            now = time.monotonic()
            last = self._last_label_update.get(idx, 0.0)
            if pct >= 100.0 or now - last >= 0.15:
                self._last_label_update[idx] = now
                self._refresh_item_label(item)
        self._recompute_overall()

    def _on_file_eta(self, idx, eta):
        row = self._row_for_runner(idx)
        item = self.file_list.item(row)
        d = self._item_data(item)
        if d:
            d.eta = eta
            self._refresh_item_label(item)

    def _on_file_retrying(self, idx, attempt, last_err):
        row = self._row_for_runner(idx)
        item = self.file_list.item(row)
        d = self._item_data(item)
        if d:
            d.status = "pending"
            d.progress = 0.0
            d.eta = -1.0
            d.error = f"retrying after: {last_err[:80]}"
            self._refresh_item_label(item)
        log.info("UI: job %d retrying (attempt %d)", idx, attempt)
        self.status_lbl.setText(f"Retrying job {idx + 1} (attempt {attempt})")
        # Persist so a crash mid-retry leaves a recoverable state.
        self._save_queue_state()

    def _on_file_finished(self, idx, ok, msg):
        row = self._row_for_runner(idx)
        item = self.file_list.item(row)
        d = self._item_data(item)
        if d:
            # When splitting, a row goes through "encoding" multiple times
            # (once per part). Only mark "done" once every part has finished
            # successfully — otherwise keep the row in "encoding" so partial
            # failures still surface. With split off, _runner_to_row is a
            # 1:1 map and this collapses to the simple case.
            row_runners = [k for k, v in
                           (getattr(self, "_runner_to_row", None) or {}).items()
                           if v == row]
            if not row_runners:
                row_runners = [idx]
            self._row_completed = getattr(self, "_row_completed", {})
            self._row_completed.setdefault(row, {"ok": 0, "fail": 0,
                                                 "cancel": 0})
            if ok:
                self._row_completed[row]["ok"] += 1
            elif msg == "Cancelled":
                self._row_completed[row]["cancel"] += 1
            else:
                self._row_completed[row]["fail"] += 1
            tally = self._row_completed[row]
            seen_total = tally["ok"] + tally["fail"] + tally["cancel"]
            if tally["fail"] > 0:
                d.status = "failed"
                d.error = msg or d.error or "one or more parts failed"
            elif tally["cancel"] > 0 and seen_total == len(row_runners):
                d.status = "cancelled"
                d.error = ""
            elif tally["ok"] == len(row_runners):
                d.status = "done"
                d.progress = 100.0
                d.error = ""
            else:
                d.status = "encoding"
                # Mid-split: partial completion. Show progress as fraction
                # of parts done.
                d.progress = (tally["ok"] / len(row_runners)) * 100.0
            d.eta = -1.0
            self._refresh_item_label(item)
        # Bump the per-batch finish counter and refresh the total-ETA line.
        self._batch_completed += 1
        self._update_total_eta()
        self._recompute_overall()
        self._save_queue_state()

    def _update_total_eta(self):
        """Estimate when the whole batch will finish based on average
        per-file time so far. Shown as ``Total ETA: 47m | Finishes ~03:14``.
        """
        if self._batch_total <= 0 or self._batch_completed <= 0:
            return
        elapsed = time.monotonic() - self._batch_t_start
        avg = elapsed / self._batch_completed
        remaining = self._batch_total - self._batch_completed
        if remaining <= 0:
            self.total_eta_lbl.setText("")
            return
        eta_s = remaining * avg
        from datetime import datetime, timedelta
        finish = datetime.now() + timedelta(seconds=eta_s)
        self.total_eta_lbl.setText(
            f"Total ETA: {fmt_eta(eta_s)} | Finishes ~{finish.strftime('%H:%M')}"
        )

    def _recompute_overall(self):
        # Throttle the overall progress bar update to ~10 Hz; it's an
        # O(N) walk and a redundant repaint each call.
        now = time.monotonic()
        if now - self._last_overall_update < 0.1:
            return
        self._last_overall_update = now
        total = self.file_list.count()
        # V11.5: refresh the queue-stats one-liner whenever progress moves.
        self._refresh_queue_stats()
        if total == 0:
            self.progress.setValue(0)
            return
        acc = 0.0
        for i in range(total):
            d = self._item_data(self.file_list.item(i))
            if not d:
                continue
            if d.status == "done":
                acc += 100.0
            elif d.status == "encoding":
                acc += d.progress
            elif d.status in ("failed", "cancelled"):
                acc += 100.0
        self.progress.setValue(int(acc / total))

    def _refresh_queue_stats(self):
        """V11.5: keep the live ``queue_stats_lbl`` one-liner above the
        queue widget in sync with current row statuses.

        Counts every row by its status field; pending = anything that
        isn't done/failed/cancelled/encoding (covers idle + retrying).
        """
        if not hasattr(self, "queue_stats_lbl"):
            return
        total = self.file_list.count()
        if total == 0:
            self.queue_stats_lbl.setText("0 files")
            return
        n_done = n_failed = n_cancelled = n_encoding = n_pending = 0
        for i in range(total):
            d = self._item_data(self.file_list.item(i))
            if not d:
                n_pending += 1
                continue
            st = getattr(d, "status", "") or ""
            if st == "done":
                n_done += 1
            elif st == "failed":
                n_failed += 1
            elif st == "cancelled":
                n_cancelled += 1
            elif st == "encoding":
                n_encoding += 1
            else:
                n_pending += 1
        parts = [f"{total} files"]
        if n_done:
            parts.append(f"{n_done} done")
        if n_failed:
            parts.append(f"{n_failed} failed")
        if n_cancelled:
            parts.append(f"{n_cancelled} cancelled")
        if n_encoding:
            parts.append(f"{n_encoding} encoding")
        if n_pending:
            parts.append(f"{n_pending} pending")
        self.queue_stats_lbl.setText(" · ".join(parts))

    def _on_batch_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        # V12.3: disable + reset the pause button when the batch ends so
        # it doesn't sit there showing "Resume" after everything's done.
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ Pause")
        self._set_queue_locked(False)
        self.progress.setValue(100)
        # Total-ETA line was useful while encoding; clear it now.
        self.total_eta_lbl.setText("")
        # V11.5 fix (audit B2): the 10 Hz throttle on _recompute_overall
        # can swallow the final batch update, leaving the stats one-liner
        # showing stale "X encoding" after every job has finished.
        # Refresh unconditionally on batch end.
        self._refresh_queue_stats()
        n_done = n_fail = 0
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if not d:
                continue
            if d.status == "done":
                n_done += 1
            elif d.status in ("failed", "cancelled"):
                n_fail += 1
        msg = f"Done: {n_done} succeeded"
        if n_fail:
            msg += f", {n_fail} failed/cancelled"
        self.status_lbl.setText(msg)
        if self.tray:
            self.tray.showMessage(
                f"Veloxa Video Editor V{VELOXA_APP_VERSION}", msg,
                QSystemTrayIcon.MessageIcon.Information, 5000)
        log.info("Batch summary: %s", msg)
        self.batch = None
        self._save_queue_state()
        # Watch-folder cycle: if we're watching, move the just-completed
        # source files into the "done" subfolder, then drain any files
        # that arrived while the batch was running.
        if self._watcher:
            self._move_watched_done_files()
            self._drain_watch_buffer()

    # ====================================================== queue persistence

    def _save_queue_state(self):
        items = []
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if d:
                items.append(d.to_dict())
        save_queue_state(items)

    def _maybe_restore_queue(self):
        items = load_queue_state()
        # Only consider it worth restoring if there's at least one row that
        # isn't already done.
        actionable = [d for d in items
                      if d.get("status") not in ("done",)]
        if not actionable:
            clear_queue_state()
            return
        interrupted = sum(1 for d in items if d.get("status") == "encoding")
        crash_note = ""
        if interrupted:
            crash_note = (
                f"\n\n{interrupted} item(s) were interrupted mid-encode "
                "(likely from an unexpected close or crash) and will be "
                "re-queued from the start. Any partial output files from "
                "those encodes will be overwritten by FFmpeg's -y flag "
                "when you press Start.")
        # V14.5.0: three-way dialog — Restore & Start lets the user
        # pick up the interrupted batch with one click; Restore Only
        # leaves the queue ready for review; Discard wipes it.
        msg = QMessageBox(self)
        msg.setWindowTitle("Resume previous batch?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            f"Found {len(items)} item(s) from the previous session "
            f"({len(actionable)} unfinished).{crash_note}\n\n"
            f"Resume the queue?")
        start_btn = msg.addButton(
            "Resume && Start", QMessageBox.ButtonRole.AcceptRole)
        restore_btn = msg.addButton(
            "Restore only", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(start_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked not in (start_btn, restore_btn):
            clear_queue_state()
            return
        for raw in items:
            try:
                d = QueueItemData.from_dict(raw)
            except Exception:
                continue
            if not d.src:
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, d)
            item.setToolTip(d.src)
            self._refresh_item_label(item)
            self.file_list.addItem(item)
            # V11.5: install the per-row profile picker widget for each
            # restored row, the same way _add_files does.
            self._install_row_widget(item)
        if self.file_list.count() > 0 and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        log.info("Restored %d queue item(s) from previous session",
                 self.file_list.count())
        self._refresh_queue_stats()
        # UI-fix: paint selection styles on the restored rows.
        self._apply_row_selection_styles()
        # V14.5.0: auto-start if the user picked "Resume & Start".
        # Defer one event-loop tick so the queue widget has time to
        # finish laying out the freshly-installed rows before
        # _start_batch reads its current state.
        if clicked is start_btn:
            QTimer.singleShot(150, self._start_batch_if_pending)

    def _start_batch_if_pending(self):
        """V14.5.0: helper for the "Resume & Start" path. Only kicks
        off the batch if there's at least one pending row and no
        batch is already running — guards against double-clicks and
        races with the auto-update dialog."""
        if self.batch and self.batch.is_running():
            return
        any_pending = False
        for i in range(self.file_list.count()):
            d = self._item_data(self.file_list.item(i))
            if d and d.status == "pending":
                any_pending = True
                break
        if any_pending:
            try:
                self._start_batch()
            except Exception as exc:
                log.warning("Auto-start after resume failed: %s", exc)

    # ====================================================== persistence (settings)

    def _load_settings(self):
        s = self.settings
        self._suppress_change = True
        try:
            self.trim_start.setValue(float(s.value("trim_start", 0.0)))
            # V11.5 fix: default 0.0 (was 2.40 — silently chopped 2.4s
            # from every encode on first launch). See _apply_settings_dict.
            self.trim_end.setValue(float(s.value("trim_end", 0.0)))
            self.wm_path.setText(s.value("wm_path", "") or "")
            self.wm_preset.setCurrentText(s.value("wm_preset", "Bottom-Right"))
            self.wm_off_x.setValue(int(s.value("wm_off_x", 0)))
            self.wm_off_y.setValue(int(s.value("wm_off_y", 0)))
            self.wm_padding.setValue(int(s.value("wm_padding", 20)))
            self.wm_opacity.setValue(int(s.value("wm_opacity", 100)))
            self.wm_scale.setValue(int(s.value("wm_scale", 15)))

            self.text_wm_text.setText(s.value("text_wm_text", "") or "")
            self.text_wm_size.setValue(int(s.value("text_wm_size", 36)))
            self._text_color = s.value("text_wm_color", "#ffffff") or "#ffffff"
            self.text_wm_color_swatch.setStyleSheet(
                f"background:{self._text_color}; border:1px solid #454952; "
                f"border-radius:3px;")
            self.text_wm_preset.setCurrentText(
                s.value("text_wm_preset", "Bottom-Left"))
            self.text_wm_off_x.setValue(int(s.value("text_wm_off_x", 0)))
            self.text_wm_off_y.setValue(int(s.value("text_wm_off_y", 0)))
            self.text_wm_padding.setValue(int(s.value("text_wm_padding", 20)))
            self.text_wm_opacity.setValue(int(s.value("text_wm_opacity", 100)))

            self._set_codec(s.value("out_codec", CODEC_H264))
            self._refresh_encoder_combo()
            saved_enc = s.value("out_encoder", AUTO_ENCODER)
            if self.out_encoder.findText(saved_enc) >= 0:
                self.out_encoder.setCurrentText(saved_enc)
            else:
                self.out_encoder.setCurrentText(AUTO_ENCODER)
            self.out_quality.setCurrentText(s.value("out_quality", "Balanced"))
            self.out_res.setCurrentText(s.value("out_res", "4K (3840x2160)"))
            self.parallel_jobs.setValue(int(s.value("parallel_jobs", 1)))
            stereo_val = s.value("force_stereo", True)
            if isinstance(stereo_val, str):
                stereo_val = stereo_val.lower() in ("true", "1", "yes")
            self.force_stereo.setChecked(bool(stereo_val))
            loud_val = s.value("loudnorm", False)
            if isinstance(loud_val, str):
                loud_val = loud_val.lower() in ("true", "1", "yes")
            self.loudnorm.setChecked(bool(loud_val))
            try:
                self.speed_value.setValue(float(s.value("speed", 1.0)))
            except (TypeError, ValueError):
                self.speed_value.setValue(1.0)
            # Pattern with back-compat for V10.x suffix-based settings.
            saved_pattern = s.value("out_pattern", "")
            if not saved_pattern:
                old_suffix = s.value("out_suffix", "_edited")
                saved_pattern = "{name}" + (old_suffix or "_edited")
            self.out_pattern.setText(saved_pattern)
            try:
                self.fade_in.setValue(float(s.value("fade_in", 0.0)))
            except (TypeError, ValueError):
                self.fade_in.setValue(0.0)
            try:
                self.fade_out.setValue(float(s.value("fade_out", 0.0)))
            except (TypeError, ValueError):
                self.fade_out.setValue(0.0)
            hw_val = s.value("hw_decode", True)
            if isinstance(hw_val, str):
                hw_val = hw_val.lower() in ("true", "1", "yes")
            self.hw_decode.setChecked(bool(hw_val))
            # V14.8.0: restore custom FFmpeg-args passthrough.
            self.custom_ffmpeg_args.setText(
                s.value("custom_ffmpeg_args", "") or "")
            # V14.3.0: persisted parallel CPU encoder slot toggle.
            cpu_val = s.value("use_cpu_alongside_gpu", False)
            if isinstance(cpu_val, str):
                cpu_val = cpu_val.lower() in ("true", "1", "yes")
            self.use_cpu_alongside_gpu.setChecked(bool(cpu_val))
            # V12.3.1: persisted quality tier + intro/outro. Back-compat:
            # if QSettings carries an int from the V12.3 numeric UI under
            # ``video_bitrate_kbps`` / ``audio_bitrate_kbps``, map it to
            # the nearest tier so the dropdown lands on something sane.
            vq = s.value("video_quality", "") or ""
            if not vq:
                try:
                    vq = kbps_to_video_quality_tier(
                        int(s.value("video_bitrate_kbps", 0)))
                except (TypeError, ValueError):
                    vq = VIDEO_QUALITY_DEFAULT
            if vq not in VIDEO_QUALITY_TIERS:
                vq = VIDEO_QUALITY_DEFAULT
            self.video_quality.setCurrentText(vq)
            aq = s.value("audio_quality", "") or ""
            if not aq:
                try:
                    aq = kbps_to_audio_quality_tier(
                        int(s.value("audio_bitrate_kbps", 0)))
                except (TypeError, ValueError):
                    aq = AUDIO_QUALITY_DEFAULT
            if aq not in AUDIO_QUALITY_TIERS:
                aq = AUDIO_QUALITY_DEFAULT
            self.audio_quality.setCurrentText(aq)
            self.intro_path.setText(s.value("intro_path", "") or "")
            self.outro_path.setText(s.value("outro_path", "") or "")
            try:
                self.merge_fade.setValue(float(s.value("merge_audio_fade_s", 0.0)))
            except (TypeError, ValueError):
                self.merge_fade.setValue(0.0)
            self.vid_wm_path.setText(s.value("vid_wm_path", "") or "")
            self.vid_wm_preset.setCurrentText(
                s.value("vid_wm_preset", "Top-Right"))
            self.vid_wm_off_x.setValue(int(s.value("vid_wm_off_x", 0)))
            self.vid_wm_off_y.setValue(int(s.value("vid_wm_off_y", 0)))
            self.vid_wm_padding.setValue(int(s.value("vid_wm_padding", 20)))
            self.vid_wm_opacity.setValue(int(s.value("vid_wm_opacity", 100)))
            self.vid_wm_scale.setValue(int(s.value("vid_wm_scale", 20)))

            # Window size / position / maximized state and the preview vs
            # settings splitter handle position. QByteArray-typed values
            # (saved via QWidget.saveGeometry / QSplitter.saveState).
            geom = s.value("window_geometry")
            if geom:
                try:
                    self.restoreGeometry(geom)
                except Exception:
                    pass
            split = s.value("middle_splitter")
            if split and hasattr(self, "middle_splitter"):
                try:
                    self.middle_splitter.restoreState(split)
                except Exception:
                    pass
        finally:
            self._suppress_change = False

    def closeEvent(self, e):
        # Confirm before closing if a batch is in progress.
        if self.batch and self.batch.is_running():
            r = QMessageBox.question(
                self, "Batch Running",
                "A batch is currently encoding. Cancel it and close?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return

        s = self.settings
        s.setValue("trim_start", self.trim_start.value())
        s.setValue("trim_end", self.trim_end.value())
        s.setValue("wm_path", self.wm_path.text())
        s.setValue("wm_preset", self.wm_preset.currentText())
        s.setValue("wm_off_x", self.wm_off_x.value())
        s.setValue("wm_off_y", self.wm_off_y.value())
        s.setValue("wm_padding", self.wm_padding.value())
        s.setValue("wm_opacity", self.wm_opacity.value())
        s.setValue("wm_scale", self.wm_scale.value())
        s.setValue("text_wm_text", self.text_wm_text.text())
        s.setValue("text_wm_size", self.text_wm_size.value())
        s.setValue("text_wm_color", self._text_color)
        s.setValue("text_wm_preset", self.text_wm_preset.currentText())
        s.setValue("text_wm_off_x", self.text_wm_off_x.value())
        s.setValue("text_wm_off_y", self.text_wm_off_y.value())
        s.setValue("text_wm_padding", self.text_wm_padding.value())
        s.setValue("text_wm_opacity", self.text_wm_opacity.value())
        s.setValue("out_codec", self._codec_value())
        s.setValue("out_encoder", self.out_encoder.currentText())
        s.setValue("out_quality", self.out_quality.currentText())
        s.setValue("out_res", self.out_res.currentText())
        s.setValue("parallel_jobs", self.parallel_jobs.value())
        s.setValue("force_stereo", self.force_stereo.isChecked())
        s.setValue("loudnorm", self.loudnorm.isChecked())
        s.setValue("speed", float(self.speed_value.value()))
        s.setValue("out_pattern", self.out_pattern.text())
        s.setValue("fade_in", float(self.fade_in.value()))
        s.setValue("fade_out", float(self.fade_out.value()))
        s.setValue("hw_decode", self.hw_decode.isChecked())
        # V14.8.0: persist custom FFmpeg-args passthrough.
        s.setValue("custom_ffmpeg_args",
                   self.custom_ffmpeg_args.text().strip())
        # V14.3.0: persist the CPU-slot toggle across sessions.
        s.setValue("use_cpu_alongside_gpu",
                   self.use_cpu_alongside_gpu.isChecked())
        # V12.3.1: persist quality tier + intro/outro across sessions.
        # We save the tier label (the dropdown selection). The legacy
        # ``video_bitrate_kbps`` / ``audio_bitrate_kbps`` keys are kept
        # in QSettings too, holding the *resolved* kbps for the current
        # output resolution, so downstream tools that inspect the
        # registry directly still see a usable value.
        s.setValue("video_quality", self.video_quality.currentText())
        s.setValue("audio_quality", self.audio_quality.currentText())
        try:
            res = RESOLUTIONS.get(self.out_res.currentText())
            _w, _h = (res if res else (0, 0))
            s.setValue("video_bitrate_kbps", int(resolve_video_bitrate_kbps(
                self.video_quality.currentText(), _w, _h)))
        except Exception:
            pass
        s.setValue("audio_bitrate_kbps", int(resolve_audio_bitrate_kbps(
            self.audio_quality.currentText())))
        s.setValue("intro_path", self.intro_path.text())
        s.setValue("outro_path", self.outro_path.text())
        s.setValue("merge_audio_fade_s", float(self.merge_fade.value()))
        s.setValue("vid_wm_path", self.vid_wm_path.text())
        s.setValue("vid_wm_preset", self.vid_wm_preset.currentText())
        s.setValue("vid_wm_off_x", self.vid_wm_off_x.value())
        s.setValue("vid_wm_off_y", self.vid_wm_off_y.value())
        s.setValue("vid_wm_padding", self.vid_wm_padding.value())
        s.setValue("vid_wm_opacity", self.vid_wm_opacity.value())
        s.setValue("vid_wm_scale", self.vid_wm_scale.value())

        # Window geometry (size + position + maximized state) and the
        # preview/settings splitter position so the layout persists across
        # sessions.
        s.setValue("window_geometry", self.saveGeometry())
        if hasattr(self, "middle_splitter"):
            s.setValue("middle_splitter", self.middle_splitter.saveState())
        s.setValue("last_profile", self.profile_combo.currentText())

        self._save_queue_state()

        # Wait briefly for any preview worker still in flight so we don't
        # warn about destroyed running QThreads.
        for w in list(self._preview_workers):
            try:
                w.wait(500)
            except Exception:
                pass

        if self.batch and self.batch.is_running():
            self.batch.cancel()
            self.batch.wait_all(timeout_ms=3000)
        # Tear down the folder watcher so the underlying QFileSystemWatcher
        # threads don't outlive the window.
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                pass
            self._watcher = None
        log.info(f"Veloxa Video Editor V{VELOXA_APP_VERSION} session end")
        e.accept()
