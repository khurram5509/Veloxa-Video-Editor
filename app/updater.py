"""V13.0: GitHub-Releases-driven auto-update.

Polls the GitHub Releases API for newer versions of this app and offers to
download + run the installer in-place. Stays offline-friendly: any failure
to reach the API is silent — no popups, no nag.

Configure ``GITHUB_REPO`` below with your ``owner/repo`` slug; until that
is set, all update checks short-circuit to "no update found" so a clean
fresh build never tries to phone home.

Architecture:

* ``check_for_updates(...)`` is a pure function that calls the GitHub API
  with ``urllib`` (stdlib) and returns an :class:`UpdateInfo` or ``None``.
  Strict timeout, never raises (returns ``None`` on any failure).
* ``UpdateChecker(QThread)`` wraps the call so the GUI never blocks.
* ``download_installer(...)`` streams the asset to a temp file with
  progress callbacks.
* ``launch_installer_and_quit(...)`` spawns the installer and asks the
  Qt app to quit so the installer can replace the EXE in-place. Relies
  on the installer's stable ``AppId`` for upgrade-without-uninstall.

Settings keys (in the GUI ``QSettings``):
    ``auto_update_check`` (bool, default True)
        Whether to poll on startup.
    ``update_skip_version`` (str)
        If equal to the latest version's tag, the GUI suppresses the
        "update available" dialog. Cleared by the user clicking
        "Check for Updates..." manually, or by a newer release than
        the one skipped showing up.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("veloxa.updater")


# ---------------------------------------------------------------- config

# Single source of truth for the application version. Imported by
# ``app/docs.py``, ``app/main_window.py`` title bar, and the regression
# tests. Bump this when cutting a new release.
APP_VERSION = "14.5.0"

# GitHub repo to poll for releases. Format: ``owner/repo`` (no leading
# slash, no trailing slash). Set to ``""`` to disable update checks
# entirely.
GITHUB_REPO = "khurram5509/Veloxa-Video-Editor"

# Per-request user-agent. GitHub's API rejects requests without one.
USER_AGENT = f"VeloxaVideoEditor/{APP_VERSION}"

# Hard ceiling on the HTTP request — auto-update should never block the
# GUI for more than a few seconds, online or offline.
HTTP_TIMEOUT_S = 8

# Bound the asset download similarly — installer is ~400 MB today, allow
# headroom for future growth. Failure surfaces to the user as a dialog,
# not a frozen progress bar.
DOWNLOAD_TIMEOUT_S = 600


# ---------------------------------------------------------------- model

@dataclass
class UpdateInfo:
    """Information about a newer release found on GitHub."""
    version: str           # tag_name stripped of leading 'v', e.g. "13.0"
    tag: str               # original tag_name as returned by GitHub
    name: str              # release.name (display title)
    body: str              # release notes (markdown, may be empty)
    html_url: str          # release page on github.com
    asset_url: str         # direct download URL for the Windows installer
    asset_name: str        # asset's filename
    asset_size: int        # size in bytes, 0 if unknown


# ---------------------------------------------------------------- version utils

_VERSION_PART = re.compile(r"\d+")


def parse_version(s: str) -> tuple:
    """Convert ``"V12.3.1"``, ``"v12.3"``, ``"13.0.0"`` etc. into a tuple
    of ints for comparison. Non-numeric parts are dropped. An empty
    string yields ``(0,)`` so ``parse_version("") < parse_version("0.0.1")``.
    """
    if not s:
        return (0,)
    parts = _VERSION_PART.findall(str(s))
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def version_compare(a: str, b: str) -> int:
    """Return ``-1`` if ``a < b``, ``1`` if ``a > b``, ``0`` if equal.
    Tolerant: ``v1.2`` == ``1.2`` == ``V1.2.0``.
    """
    pa = parse_version(a)
    pb = parse_version(b)
    # Pad to same length so trailing zeros compare equal.
    n = max(len(pa), len(pb))
    pa = pa + (0,) * (n - len(pa))
    pb = pb + (0,) * (n - len(pb))
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    """Convenience wrapper. ``True`` iff ``remote > local``."""
    return version_compare(remote, local) > 0


# ---------------------------------------------------------------- API call

def _pick_windows_asset(assets: list) -> Optional[dict]:
    """Choose the Windows installer asset from a GitHub release's
    ``assets`` array. Preference order: ``*Setup*.exe`` >
    ``*Installer*.exe`` > any ``*.exe`` > ``None``. Case-insensitive.

    V14.2.0: kept under the original name for back-compat with the
    regression suite; for cross-platform asset selection use
    :func:`app.platform_compat.pick_release_asset` instead.
    """
    if not assets:
        return None
    setup_assets = []
    installer_assets = []
    other_exe = []
    for a in assets:
        name = (a.get("name") or "").lower()
        if not name.endswith(".exe"):
            continue
        if "setup" in name:
            setup_assets.append(a)
        elif "installer" in name:
            installer_assets.append(a)
        else:
            other_exe.append(a)
    for bucket in (setup_assets, installer_assets, other_exe):
        if bucket:
            return bucket[0]
    return None


def check_for_updates(github_repo: str = GITHUB_REPO,
                      local_version: str = APP_VERSION,
                      timeout: float = HTTP_TIMEOUT_S
                      ) -> Optional[UpdateInfo]:
    """Query GitHub for the latest release of ``github_repo``. Returns
    an :class:`UpdateInfo` iff that release is strictly newer than
    ``local_version``. Returns ``None`` for every error condition
    (network unreachable, 404, rate-limit, malformed JSON, no Windows
    asset, repo not configured...). Never raises.
    """
    if not github_repo or "/" not in github_repo:
        return None
    url = f"https://api.github.com/repos/{github_repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError) as exc:
        log.info("Update check: API unreachable: %s", exc)
        return None
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("Update check: malformed JSON: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return None
    # Strip a leading 'v' / 'V' for display, but keep the raw tag for the
    # asset URL.
    display_version = tag.lstrip("vV")
    if not is_newer(display_version, local_version):
        return None
    # V14.2.0: pick platform-appropriate asset (.exe on Windows,
    # .dmg on macOS, .AppImage on Linux). The legacy
    # _pick_windows_asset is kept for the regression suite + as the
    # implementation of the Windows branch.
    from .platform_compat import pick_release_asset
    asset = pick_release_asset(data.get("assets") or [])
    if not asset:
        # V14.3.4: platform-agnostic log message — was "no .exe asset"
        # which read as a Windows-specific failure even when running on
        # macOS (where the picker is looking for a .dmg).
        log.info("Update check: release %s has no installer asset "
                 "for this platform", tag)
        return None
    return UpdateInfo(
        version=display_version,
        tag=tag,
        name=(data.get("name") or tag),
        body=(data.get("body") or ""),
        html_url=(data.get("html_url") or ""),
        asset_url=(asset.get("browser_download_url") or ""),
        asset_name=(asset.get("name") or "VeloxaVideoEditor-Setup.exe"),
        asset_size=int(asset.get("size") or 0),
    )


# ---------------------------------------------------------------- Qt thread

class UpdateChecker(QThread):
    """Off-the-main-thread wrapper around :func:`check_for_updates`."""

    # found_update(info, manual_trigger)
    found_update = pyqtSignal(object, bool)
    # no_update(manual_trigger) — emitted both on "you're up to date" AND
    # on "API unreachable" so a manual click always gets feedback.
    no_update = pyqtSignal(bool)

    def __init__(self, *, github_repo: str = GITHUB_REPO,
                 local_version: str = APP_VERSION,
                 manual: bool = False,
                 parent=None):
        super().__init__(parent)
        self._github_repo = github_repo
        self._local_version = local_version
        self._manual = manual

    def run(self):
        info = check_for_updates(
            github_repo=self._github_repo,
            local_version=self._local_version,
        )
        if info:
            self.found_update.emit(info, self._manual)
        else:
            self.no_update.emit(self._manual)


# ---------------------------------------------------------------- download

def download_installer(info: UpdateInfo,
                       progress_cb: Optional[Callable[[int, int], None]] = None,
                       cancel_cb: Optional[Callable[[], bool]] = None,
                       timeout: float = DOWNLOAD_TIMEOUT_S
                       ) -> Optional[str]:
    """Download ``info.asset_url`` to a temp file and return the path,
    or ``None`` on error / cancel.

    ``progress_cb(downloaded_bytes, total_bytes)`` is called periodically.
    ``cancel_cb() -> bool`` is polled between chunks; returning ``True``
    aborts and deletes the partial file.

    V14.0.3 perf-fix: chunk size REVERTED to 64 KB (was 1 MB in V14.0.1
    + V14.0.2). The V14.0.1 change to 1 MB chunks was based on the
    wrong mental model — "fewer Python iterations = faster". In
    practice ``urllib`` `resp.read(N)` blocks waiting for N bytes,
    while GitHub's release CDN delivers in smaller TCP frames. Larger
    Python-level reads stall on partial buffers. Empirical measurement
    against the live release URL:

      64 KB chunks   -> 12.3 MB/s   (Python max)
      256 KB chunks  ->  9.9 MB/s
      1 MB chunks    ->  8.4 MB/s   (V14.0.1's slower regression)
      4 MB chunks    ->  0.3 MB/s   (catastrophic)
      shutil.copyfileobj/8 MB -> 12.7 MB/s

    The throttled progress signal (~10/sec) in DownloadWorker
    decouples GUI repaint frequency from chunk size, so we can take
    the 64 KB throughput without spamming the event queue.
    """
    if not info or not info.asset_url:
        return None
    req = urllib.request.Request(
        info.asset_url,
        headers={"User-Agent": USER_AGENT},
    )
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f"veloxa_update_{os.getpid()}_",
        suffix=".exe")
    chunk_size = 64 * 1024  # V14.0.3: 64 KB — fastest for GitHub CDN.
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = info.asset_size or int(
                resp.headers.get("Content-Length") or 0)
            done = 0
            with os.fdopen(tmp_fd, "wb") as fout:
                while True:
                    if cancel_cb and cancel_cb():
                        raise InterruptedError("User cancelled")
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fout.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(done, total)
                        except Exception:
                            pass
        # Sanity check: the file should be non-empty and (when GitHub
        # told us the size) match the declared size.
        actual = os.path.getsize(tmp_path)
        if actual <= 0:
            raise OSError("Downloaded zero bytes")
        if info.asset_size and abs(actual - info.asset_size) > 1024:
            log.warning("Update download size mismatch: got %d, expected %d",
                        actual, info.asset_size)
        return tmp_path
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, InterruptedError) as exc:
        log.warning("Update download failed: %s", exc)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None


# ---------------------------------------------------------------- worker

class DownloadWorker(QThread):
    """V14.0.1: runs :func:`download_installer` on a background thread
    so the GUI stays responsive (no more 6,300 ``processEvents()`` calls
    on the main thread blocking paint events).

    Signals:
      progress(done_bytes, total_bytes, rate_bps) — emitted at most
        ``progress_throttle_hz`` times per second so the UI doesn't
        repaint on every chunk.
      finished_with_path(path_or_empty, success) — emitted exactly once
        on thread exit. ``path`` is the temp file (or ``""`` on failure).
    """

    progress = pyqtSignal(int, int, float)
    finished_with_path = pyqtSignal(str, bool)

    progress_throttle_hz = 10  # max progress signals per second

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancel = False
        self._t_start = 0.0
        self._last_emit_t = 0.0
        self._last_emit_done = 0

    def cancel(self):
        self._cancel = True

    def _on_progress(self, done: int, total: int):
        import time as _t
        now = _t.monotonic()
        # Always emit the very first progress and after each min-interval.
        min_interval = 1.0 / max(1, self.progress_throttle_hz)
        if (now - self._last_emit_t) < min_interval and done < total:
            return
        elapsed = max(1e-6, now - self._t_start)
        rate_bps = done / elapsed
        self._last_emit_t = now
        self._last_emit_done = done
        self.progress.emit(done, total, rate_bps)

    def _cancel_cb(self) -> bool:
        return self._cancel

    def run(self):
        import time as _t
        self._t_start = _t.monotonic()
        self._last_emit_t = self._t_start
        path = download_installer(
            self._info,
            progress_cb=self._on_progress,
            cancel_cb=self._cancel_cb,
        )
        ok = bool(path)
        self.finished_with_path.emit(path or "", ok)


# ---------------------------------------------------------------- launch

def launch_installer_and_quit(installer_path: str,
                              quit_callback: Optional[Callable[[], None]] = None
                              ) -> bool:
    """Spawn the downloaded installer and call ``quit_callback`` (the
    GUI quitter). On Windows the installer reuses our stable ``AppId``
    to upgrade in place. On macOS the ``.dmg`` is mounted via ``open``
    and the user drags Veloxa.app to /Applications. Returns ``True``
    on successful spawn.

    V14.2.0: delegated to :func:`app.platform_compat.launch_installer`
    so the per-OS quirks (DETACHED_PROCESS on Windows, ``open`` on
    macOS, +x bit on Linux) live in one place.
    """
    from .platform_compat import launch_installer
    if not launch_installer(installer_path):
        return False
    if quit_callback:
        try:
            quit_callback()
        except Exception:
            pass
    return True
