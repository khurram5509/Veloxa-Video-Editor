"""Custom Qt widgets and per-row queue data."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PyQt6.QtWidgets import QListWidget, QWidget

from .theme import BRAND_ACCENT, BRAND_HANDLE


# Set in main_window once we know the app's accepted extensions.
ALL_INPUT_EXTS: set = set()


# ============================================================== Trim seek bar

class TrimSeekBar(QWidget):
    """Custom slider with two trim handles + a scrubber knob.

    Drag the orange bars to set trim start / end. Drag the white knob (or
    click on the track) to scrub the preview. Trim handles can't cross —
    they hold a 0.1 s minimum gap.
    """

    seek_changed = pyqtSignal(float)            # current scrub time (s)
    trim_changed = pyqtSignal(float, float)     # trim_start, trim_end (s from end)
    drag_finished = pyqtSignal()

    HANDLE_HALF_W = 4
    HIT_TOLERANCE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMaximumHeight(46)
        self.setMouseTracking(True)
        self.duration = 0.0
        self.seek_pos = 0.0
        self.trim_start = 0.0
        self.trim_end = 0.0
        self._dragging = None

    def setDuration(self, d: float):
        self.duration = max(0.0, float(d))
        self.seek_pos = max(0.0, min(self.seek_pos, self.duration))
        self.update()

    def setSeek(self, t: float):
        new = max(0.0, min(self.duration, float(t)))
        if abs(new - self.seek_pos) > 1e-6:
            self.seek_pos = new
            self.update()

    def setTrim(self, start: float, end_trim: float):
        self.trim_start = max(0.0, min(self.duration, float(start)))
        self.trim_end = max(0.0, min(self.duration, float(end_trim)))
        self.update()

    @property
    def _left_pad(self):
        return 12

    @property
    def _track_w(self):
        return max(1, self.width() - 24)

    def _x_for_time(self, t: float) -> int:
        if self.duration <= 0:
            return self._left_pad
        return self._left_pad + int(t / self.duration * self._track_w)

    def _time_for_x(self, x: float) -> float:
        if self.duration <= 0 or self._track_w <= 0:
            return 0.0
        clamped = max(self._left_pad, min(self._left_pad + self._track_w, x))
        return (clamped - self._left_pad) / self._track_w * self.duration

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        track_top = h // 2 - 4
        track_h = 8

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#454952"))
        p.drawRoundedRect(self._left_pad, track_top, self._track_w, track_h, 4, 4)

        if self.duration <= 0:
            return

        start_x = self._x_for_time(self.trim_start)
        end_x = self._x_for_time(self.duration - self.trim_end)
        seek_x = self._x_for_time(self.seek_pos)

        # Active region (between trim handles)
        if end_x > start_x:
            p.setBrush(QColor(BRAND_ACCENT))
            p.drawRoundedRect(start_x, track_top, end_x - start_x, track_h, 4, 4)

        # Trim handle bars
        p.setBrush(QColor(BRAND_HANDLE))
        bar_w = self.HANDLE_HALF_W * 2
        p.drawRoundedRect(start_x - self.HANDLE_HALF_W, 4, bar_w, h - 8, 2, 2)
        p.drawRoundedRect(end_x - self.HANDLE_HALF_W, 4, bar_w, h - 8, 2, 2)

        # Scrub knob
        p.setPen(QPen(QColor(BRAND_ACCENT), 2))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(seek_x, h / 2), 8, 8)

    def mousePressEvent(self, e):
        if self.duration <= 0:
            return
        x = e.position().x()
        start_x = self._x_for_time(self.trim_start)
        end_x = self._x_for_time(self.duration - self.trim_end)
        seek_x = self._x_for_time(self.seek_pos)
        candidates = sorted([
            (abs(x - start_x), 0, "start"),
            (abs(x - end_x), 1, "end"),
            (abs(x - seek_x), 2, "seek"),
        ])
        if candidates[0][0] <= self.HIT_TOLERANCE:
            self._dragging = candidates[0][2]
            if self._dragging == "seek":
                t = self._time_for_x(x)
                self.seek_pos = t
                self.seek_changed.emit(t)
                self.update()
        else:
            self._dragging = "seek"
            t = self._time_for_x(x)
            self.seek_pos = t
            self.seek_changed.emit(t)
            self.update()

    def mouseMoveEvent(self, e):
        if not self._dragging or self.duration <= 0:
            return
        t = self._time_for_x(e.position().x())
        if self._dragging == "seek":
            self.seek_pos = t
            self.seek_changed.emit(t)
        elif self._dragging == "start":
            max_t = max(0.0, self.duration - self.trim_end - 0.1)
            self.trim_start = max(0.0, min(t, max_t))
            self.seek_pos = self.trim_start
            self.trim_changed.emit(self.trim_start, self.trim_end)
            self.seek_changed.emit(self.seek_pos)
        elif self._dragging == "end":
            min_t = self.trim_start + 0.1
            new_end_trim = max(0.0, self.duration - max(t, min_t))
            self.trim_end = new_end_trim
            self.seek_pos = self.duration - self.trim_end
            self.trim_changed.emit(self.trim_start, self.trim_end)
            self.seek_changed.emit(self.seek_pos)
        self.update()

    def mouseReleaseEvent(self, _e):
        if self._dragging:
            self._dragging = None
            self.drag_finished.emit()


# ============================================================== Queue list

class DropList(QListWidget):
    """Queue list that accepts external drops AND supports internal drag-reorder."""

    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e: QDropEvent):
        if e.mimeData().hasUrls():
            paths = []
            for url in e.mimeData().urls():
                p = url.toLocalFile()
                if p and Path(p).suffix.lower() in ALL_INPUT_EXTS:
                    paths.append(p)
            if paths:
                self.files_dropped.emit(paths)
                e.acceptProposedAction()
                return
        super().dropEvent(e)


# ============================================================== Queue item data

class QueueItemData:
    """One row in the queue. Stored on its QListWidgetItem via UserRole."""

    __slots__ = (
        "src", "kind",
        "visual_path", "visual_kind", "visual_duration",
        "status", "progress", "eta", "error",
        "profile_name",  # V11.5: per-row profile assignment
    )

    def __init__(self, src: str, kind: str,
                 visual_path: str = None, visual_kind: str = None,
                 visual_duration: float = 0.0,
                 profile_name: str = ""):
        self.src = src
        self.kind = kind                       # 'video' or 'audio'
        self.visual_path = visual_path         # for audio: image OR video file
        self.visual_kind = visual_kind         # 'image' | 'video' | None
        self.visual_duration = visual_duration # seconds, only for video visuals
        self.status = "pending"                # pending|encoding|done|failed|cancelled
        self.progress = 0.0
        self.eta = -1.0
        self.error = ""                        # last failure message, if any
        # V11.5: name of the profile to use when encoding THIS row. Set
        # at add-time to whatever profile is active in the header
        # dropdown (or "(no profile)" for live-form settings). The user
        # can change it via the per-row picker or the right-click menu.
        self.profile_name = profile_name or ""

    def to_dict(self) -> dict:
        """Serialize for queue persistence."""
        return {
            "src": self.src,
            "kind": self.kind,
            "visual_path": self.visual_path,
            "visual_kind": self.visual_kind,
            "visual_duration": self.visual_duration,
            "status": self.status,
            "error": self.error,
            "profile_name": self.profile_name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueueItemData":
        item = cls(
            src=d.get("src", ""),
            kind=d.get("kind", "video"),
            visual_path=d.get("visual_path"),
            visual_kind=d.get("visual_kind"),
            visual_duration=float(d.get("visual_duration", 0.0) or 0.0),
            profile_name=d.get("profile_name", "") or "",
        )
        # Reset in-progress state from a previous session — that work is gone.
        st = d.get("status", "pending")
        item.status = "pending" if st == "encoding" else st
        item.error = d.get("error", "") or ""
        return item
