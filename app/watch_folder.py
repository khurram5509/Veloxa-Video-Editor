"""Folder-watching daemon: emits ``file_ready`` once a new file in the
watched directory has been stable in size for ``settle_seconds``.

Fully decoupled from the UI — the main window connects to ``file_ready``
and decides what to do (typically: add to queue, kick off a batch).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QFileSystemWatcher, QTimer, pyqtSignal


log = logging.getLogger("veloxa.watch")


class FolderWatcher(QObject):
    """Watch a directory for new files matching ``exts``.

    A file is considered "ready" only when its size has stayed unchanged
    across two checks ``settle_seconds`` apart. This avoids handing a
    half-written recording to the encoder while OBS / a phone sync / a
    file copy is still in progress.

    Existing files at start-up are skipped — they're added to ``seen``
    immediately so the watcher only acts on files that genuinely arrive
    after it starts.
    """

    file_ready = pyqtSignal(str)

    def __init__(self, folder: str, exts: set, settle_seconds: float = 2.0):
        super().__init__()
        self.folder = Path(folder)
        self.exts = {e.lower() for e in exts}
        self.settle_seconds = settle_seconds
        self._poll_ms = max(500, int(settle_seconds * 1000) + 200)

        self.watcher = QFileSystemWatcher([str(self.folder)])
        self.watcher.directoryChanged.connect(self._scan)

        self.seen = set()
        self.pending = {}  # path -> last_size
        self._scan_existing()

        # Polling fallback. QFileSystemWatcher misses some changes on Windows
        # network shares and certain cloud-synced folders, so we also
        # re-scan periodically.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self._poll_ms)
        self._poll_timer.timeout.connect(self._scan)
        self._poll_timer.start()

    def _scan_existing(self):
        try:
            for p in self.folder.iterdir():
                if p.is_file():
                    self.seen.add(str(p))
        except OSError as e:
            log.warning("Could not scan watch folder: %s", e)

    def _scan(self, _path=None):
        try:
            for p in self.folder.iterdir():
                sp = str(p)
                if sp in self.seen or not p.is_file():
                    continue
                if p.suffix.lower() not in self.exts:
                    continue
                self._consider(p)
        except OSError:
            pass

    def _consider(self, p: Path):
        try:
            size = p.stat().st_size
        except OSError:
            return
        sp = str(p)
        # First time we've seen this file — record the size, schedule
        # the stability check.
        self.pending[sp] = size
        QTimer.singleShot(self._poll_ms, lambda p=p: self._check(p))

    def _check(self, p: Path):
        sp = str(p)
        if sp in self.seen:
            self.pending.pop(sp, None)
            return
        try:
            size = p.stat().st_size
        except OSError:
            self.pending.pop(sp, None)
            return
        last = self.pending.get(sp)
        if last is None:
            return
        if size == last and size > 0:
            self.seen.add(sp)
            self.pending.pop(sp, None)
            log.info("Watch: file ready %s", sp)
            self.file_ready.emit(sp)
        else:
            # Still growing — record new size and re-check.
            self.pending[sp] = size
            QTimer.singleShot(self._poll_ms, lambda p=p: self._check(p))

    def stop(self):
        try:
            self._poll_timer.stop()
        except Exception:
            pass
        try:
            dirs = self.watcher.directories()
            if dirs:
                self.watcher.removePaths(dirs)
        except Exception:
            pass
