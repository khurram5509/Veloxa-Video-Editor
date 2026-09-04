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

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("veloxa.updater")

# V14.11.3 (security): the auto-updater downloads an installer and then
# EXECUTES it, so the download URL must be a GitHub host reached over
# HTTPS. GitHub serves release assets from github.com and redirects to
# its object CDN (objects.githubusercontent.com / *.githubusercontent
# .com / release-assets.githubusercontent.com). Anything else is refused.
_TRUSTED_DOWNLOAD_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)


def is_trusted_download_url(url: str) -> bool:
    """True iff ``url`` is an HTTPS URL on a known GitHub download host.
    Used to gate what the auto-updater is willing to fetch-and-run."""
    if not url:
        return False
    try:
        p = urllib.parse.urlparse(url)
    except (ValueError, TypeError):
        return False
    if p.scheme != "https":
        return False
    host = (p.hostname or "").lower()
    return (host in _TRUSTED_DOWNLOAD_HOSTS
            or host.endswith(".githubusercontent.com"))


def sha256_of_file(path: str, chunk: int = 1 << 20) -> str:
    """Hex SHA-256 of a file, streamed so large installers don't load
    into memory. Returns "" on any read error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fp:
            for block in iter(lambda: fp.read(chunk), b""):
                h.update(block)
    except OSError:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------- config

# Single source of truth for the application version. Imported by
# ``app/docs.py``, ``app/main_window.py`` title bar, and the regression
# tests. Bump this when cutting a new release.
APP_VERSION = "14.11.3"

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
    # V14.11.3 (security): GitHub computes a per-asset SHA-256 server-side
    # and returns it as ``digest`` ("sha256:<hex>"). We verify the
    # downloaded bytes against it before the installer is ever launched,
    # so a corrupted or CDN-tampered download can't be executed. Empty
    # when the release predates GitHub's digest field.
    asset_digest: str = ""  # "sha256:<hex>" or "" if unknown


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


def _describe_http_error(exc) -> str:
    """Turn an HTTPError from the releases API into something a user can
    act on. GitHub's unauthenticated limit is 60 requests/hour per IP,
    and it answers 403 (or 429) with ``X-RateLimit-Remaining: 0`` --
    common on shared / office IPs, and the single most likely reason a
    check fails on an otherwise healthy connection."""
    code = getattr(exc, "code", 0)
    headers = getattr(exc, "headers", None) or {}
    try:
        remaining = int(headers.get("X-RateLimit-Remaining", "") or -1)
    except (TypeError, ValueError):
        remaining = -1
    if code in (403, 429) and remaining == 0:
        when = ""
        try:
            reset = int(headers.get("X-RateLimit-Reset", "") or 0)
            if reset:
                when = (" Try again after "
                        + time.strftime("%H:%M", time.localtime(reset))
                        + ".")
        except (TypeError, ValueError):
            pass
        return ("GitHub's hourly API limit was reached for your network, "
                "so Veloxa couldn't check for a new version." + when)
    if code == 403:
        return ("GitHub refused the update check (HTTP 403). This is "
                "usually a rate limit or a network policy.")
    if code == 404:
        return ("The update repository was not found (HTTP 404). It may "
                "have been renamed or made private.")
    return f"GitHub returned HTTP {code} for the update check."


def check_for_updates(github_repo: str = GITHUB_REPO,
                      local_version: str = APP_VERSION,
                      timeout: float = HTTP_TIMEOUT_S
                      ) -> Optional[UpdateInfo]:
    """Backward-compatible wrapper: returns the :class:`UpdateInfo` when a
    newer release exists, else ``None``. Callers that need to tell "you're
    up to date" apart from "the check failed" must use
    :func:`check_for_updates_detailed` instead."""
    info, _err = check_for_updates_detailed(
        github_repo=github_repo, local_version=local_version,
        timeout=timeout)
    return info


def check_for_updates_detailed(github_repo: str = GITHUB_REPO,
                               local_version: str = APP_VERSION,
                               timeout: float = HTTP_TIMEOUT_S
                               ) -> tuple:
    """Query GitHub for the latest release of ``github_repo``.

    Returns ``(info, error)``:
      * ``(UpdateInfo, "")``  -- a strictly newer release is available
      * ``(None, "")``        -- checked successfully, already current
      * ``(None, "<reason>")``-- the check itself FAILED (offline, rate
                                 limited, 404, malformed JSON...)

    V14.11.1: the old API collapsed "up to date" and "check failed" into
    a bare ``None``, so a rate-limited or offline check was reported to
    the user as "You're up to date." -- actively misleading, since a
    genuinely available update stayed invisible. The error string lets
    the UI say what actually happened. Never raises.
    """
    if not github_repo or "/" not in github_repo:
        return None, "No update repository is configured in this build."
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
    except urllib.error.HTTPError as exc:
        reason = _describe_http_error(exc)
        log.info("Update check failed: %s", reason)
        return None, reason
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.info("Update check failed: API unreachable: %s", exc)
        return None, ("Could not reach GitHub. Check your internet "
                      "connection, VPN, or firewall.")
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("Update check: malformed JSON: %s", exc)
        return None, "GitHub returned a response Veloxa couldn't read."
    if not isinstance(data, dict):
        return None, "GitHub returned an unexpected response."
    tag = (data.get("tag_name") or "").strip()
    if not tag:
        return None, "GitHub returned a release with no version tag."
    # Strip a leading 'v' / 'V' for display, but keep the raw tag for the
    # asset URL.
    display_version = tag.lstrip("vV")
    if not is_newer(display_version, local_version):
        return None, ""            # checked OK, genuinely up to date
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
        return None, (f"Release {tag} is available but has no installer "
                      "for this platform yet. Try the release page.")
    asset_url = asset.get("browser_download_url") or ""
    # V14.11.3 (security): the download URL comes from the GitHub JSON.
    # Refuse anything that isn't an HTTPS GitHub host, so a manipulated
    # response can't redirect the auto-updater to fetch and execute an
    # installer from an arbitrary server.
    if not is_trusted_download_url(asset_url):
        log.warning("Update check: asset URL failed host allowlist: %r",
                    asset_url)
        return None, ("The update download URL didn't come from GitHub "
                      "and was blocked for safety. Use the release page.")
    return UpdateInfo(
        version=display_version,
        tag=tag,
        name=(data.get("name") or tag),
        body=(data.get("body") or ""),
        html_url=(data.get("html_url") or ""),
        asset_url=asset_url,
        asset_name=(asset.get("name") or "VeloxaVideoEditor-Setup.exe"),
        asset_size=int(asset.get("size") or 0),
        asset_digest=(asset.get("digest") or ""),
    ), ""


# ---------------------------------------------------------------- Qt thread

class UpdateChecker(QThread):
    """Off-the-main-thread wrapper around :func:`check_for_updates`."""

    # found_update(info, manual_trigger)
    found_update = pyqtSignal(object, bool)
    # no_update(manual_trigger) — the check SUCCEEDED and this build is
    # already current. V14.11.1: failures no longer come through here.
    no_update = pyqtSignal(bool)
    # check_failed(reason, manual_trigger) — the check itself could not
    # complete (offline, rate limited, 404...). Previously these were
    # reported to the user as "You're up to date", hiding real updates.
    check_failed = pyqtSignal(str, bool)

    def __init__(self, *, github_repo: str = GITHUB_REPO,
                 local_version: str = APP_VERSION,
                 manual: bool = False,
                 parent=None):
        super().__init__(parent)
        self._github_repo = github_repo
        self._local_version = local_version
        self._manual = manual

    def run(self):
        info, error = check_for_updates_detailed(
            github_repo=self._github_repo,
            local_version=self._local_version,
        )
        if info:
            self.found_update.emit(info, self._manual)
        elif error:
            self.check_failed.emit(error, self._manual)
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
    # V14.8.0: stall detection. Prior versions had NO per-read timeout
    # and NO inactivity detector, so an antivirus that pauses the
    # connection mid-stream or a flaky CDN redirect that leaves the
    # socket open-but-silent would hang the dialog forever at e.g.
    # 0.6 / 270 MB at 0.0 MB/s (user's V14.6.0 download bug report).
    # Two layers of defence:
    #   1) socket-level recv timeout — if a single read blocks > N
    #      seconds with zero bytes, OSError raises and we abort.
    #   2) loop-level inactivity detector — if no bytes have moved
    #      for STALL_ABORT_S seconds (across multiple recvs), abort
    #      with a friendly error.
    STALL_ABORT_S = 30
    PER_READ_TIMEOUT_S = 15
    import time as _t
    last_byte_at = _t.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Per-recv socket timeout — applies to every chunk read.
            try:
                resp.fp.raw._sock.settimeout(PER_READ_TIMEOUT_S)
            except Exception:
                # Older urllib internals; fall back to the loop-level
                # detector alone (still catches the stall, just later).
                pass
            total = info.asset_size or int(
                resp.headers.get("Content-Length") or 0)
            done = 0
            with os.fdopen(tmp_fd, "wb") as fout:
                while True:
                    if cancel_cb and cancel_cb():
                        raise InterruptedError("User cancelled")
                    try:
                        chunk = resp.read(chunk_size)
                    except (TimeoutError, OSError) as exc:
                        # Per-recv timeout fired OR the socket closed
                        # abnormally — treat as a stall and bubble up
                        # with a clearer message than urllib's default.
                        raise OSError(
                            f"Download stalled: no data after "
                            f"{PER_READ_TIMEOUT_S}s ({exc})")
                    if not chunk:
                        break
                    fout.write(chunk)
                    done += len(chunk)
                    last_byte_at = _t.monotonic()
                    if progress_cb:
                        try:
                            progress_cb(done, total)
                        except Exception:
                            pass
                    # Defence-in-depth: small recvs that aren't quite
                    # empty but trickle in below a useful rate.
                    if _t.monotonic() - last_byte_at > STALL_ABORT_S:
                        raise OSError(
                            f"Download stalled: no progress for "
                            f"{STALL_ABORT_S}s")
        # Sanity check: the file should be non-empty and (when GitHub
        # told us the size) match the declared size.
        actual = os.path.getsize(tmp_path)
        if actual <= 0:
            raise OSError("Downloaded zero bytes")
        if info.asset_size and abs(actual - info.asset_size) > 1024:
            log.warning("Update download size mismatch: got %d, expected %d",
                        actual, info.asset_size)
        # V14.11.3 (security): verify the downloaded bytes against the
        # SHA-256 GitHub computed server-side. This is the gate that
        # decides whether the file may be launched: a corrupted or
        # CDN-tampered download will not match and is rejected here,
        # before ``launch_installer`` ever runs it. Releases predating
        # GitHub's digest field carry no hash — we proceed but log that
        # the download was unverified rather than silently trusting it.
        expected = (info.asset_digest or "").strip().lower()
        if expected.startswith("sha256:"):
            want = expected.split(":", 1)[1]
            got = sha256_of_file(tmp_path)
            if not got or got != want:
                raise OSError(
                    "Downloaded installer failed SHA-256 verification "
                    f"(expected {want[:12]}..., got {got[:12] or '??'}...). "
                    "The file was not what GitHub published and will not "
                    "be run.")
            log.info("Update download SHA-256 verified OK (%s...)", got[:12])
        else:
            log.warning("Update download has no publisher checksum; "
                        "proceeding UNVERIFIED for %s", info.asset_name)
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
