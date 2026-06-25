"""V14.5.0: opt-in crash reporter.

Catches unhandled exceptions via ``sys.excepthook`` and writes a
``crash_<timestamp>.txt`` to the log directory containing:

  - app version, Python version, platform string
  - the full traceback
  - the last ~200 lines of the active session log
  - paths sanitised so the user's name doesn't appear in the file
    (``C:\\Users\\Khurram\\Dropbox\\foo.mp4`` becomes
    ``C:\\Users\\<user>\\Dropbox\\foo.mp4``)

On next startup ``list_pending_reports()`` returns the crash files
that haven't been actioned yet. The UI then prompts the user (gated
on a QSettings opt-in) and, if the user accepts, opens a pre-filled
GitHub Issue URL via the default browser. **No automatic upload** —
the user reviews the content in their browser before submitting on
github.com, so the opt-in is true opt-in.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote


log = logging.getLogger("veloxa.crash")


# Cap how much of the URL we burn on the crash body. Most browsers
# accept very long URLs but GitHub's web form chokes well before
# the theoretical limit, and a chatty crash is annoying to read.
MAX_BODY_CHARS = 5800


def _sanitize_paths(text: str) -> str:
    """Replace the user's home directory in any path with ``<user>``
    so the crash report doesn't leak the username. Covers both
    Windows (``C:\\Users\\<name>``) and Unix (``/Users/<name>`` /
    ``/home/<name>``) forms.
    """
    home = os.path.expanduser("~")
    if not home or home == "~":
        return text
    parts = Path(home).parts
    if len(parts) < 2:
        return text
    username = parts[-1]
    if not username:
        return text
    out = text
    # Replace the verbatim home path first (covers both styles), then
    # any remaining bare ``<username>`` occurrences in path-like
    # contexts. The latter handles drive-letter-stripped paths from
    # third-party tools.
    for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        out = out.replace(variant, str(Path(parts[0]) / parts[1] / "<user>"))
    out = re.sub(
        r"(/Users/|\\Users\\|/home/)" + re.escape(username) + r"(?=[/\\\s'\"]|$)",
        r"\1<user>",
        out,
    )
    return out


def _tail(path: Path, n_lines: int = 200) -> str:
    """Return the last ``n_lines`` of the file, with username scrubbed."""
    if not path or not path.exists():
        return "(no log file)"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = "".join(lines[-n_lines:])
        return _sanitize_paths(tail)
    except OSError as exc:
        return f"(log read failed: {exc})"


def _crash_path(log_dir: Path) -> Path:
    return log_dir / f"crash_{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"


def write_crash_file(log_dir: Path, log_file: Optional[Path],
                     exc_type, exc_value, exc_tb,
                     app_version: str = "?") -> Optional[Path]:
    """Render a single crash report file. Returns the path on success."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        out = _crash_path(log_dir)
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        body = (
            f"Veloxa Video Editor crash report\n"
            f"================================\n"
            f"Version : {app_version}\n"
            f"Time    : {datetime.now().isoformat(timespec='seconds')}\n"
            f"Python  : {sys.version.split(chr(10))[0]}\n"
            f"Platform: {sys.platform}\n"
            f"\n--- Traceback ---\n{tb}\n"
            f"--- Last log lines ---\n{_tail(log_file) if log_file else '(no log file)'}\n"
        )
        out.write_text(_sanitize_paths(body), encoding="utf-8")
        log.warning("Crash report written: %s", out)
        return out
    except Exception as exc:
        log.exception("Could not write crash report: %s", exc)
        return None


def install_excepthook(log_dir: Path, log_file: Optional[Path],
                       app_version: str = "?") -> None:
    """Replace ``sys.excepthook`` so unhandled exceptions land in a
    crash file before the default handler tears the process down.

    Safe to call multiple times — only the last call's parameters take
    effect, and the original excepthook is always chained after our
    handler so default behaviour (printing the traceback) is preserved.
    """
    orig = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            write_crash_file(log_dir, log_file, exc_type, exc_value, exc_tb,
                             app_version)
        except Exception:
            # Swallow — never let the crash handler crash.
            pass
        try:
            orig(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _hook
    log.info("Crash reporter installed (log dir: %s)", log_dir)


def list_pending_reports(log_dir: Path) -> list:
    """Return crash files that haven't been actioned yet (``.txt``,
    not ``.reported`` or ``.dismissed``). Newest first."""
    if not log_dir or not log_dir.exists():
        return []
    try:
        files = list(log_dir.glob("crash_*.txt"))
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def mark_reported(crash_file: Path) -> None:
    _move_with_suffix(crash_file, ".reported")


def mark_dismissed(crash_file: Path) -> None:
    _move_with_suffix(crash_file, ".dismissed")


def _move_with_suffix(crash_file: Path, new_suffix: str) -> None:
    try:
        if crash_file.exists():
            crash_file.rename(crash_file.with_suffix(new_suffix))
    except OSError as exc:
        log.info("Could not rename crash file %s: %s", crash_file, exc)


def build_issue_url(github_repo: str, crash_file: Path,
                    app_version: str = "?") -> str:
    """Build a GitHub Issues new-issue URL pre-filled with the crash.

    Returns ``""`` when ``github_repo`` is missing or malformed (so the
    UI can disable the button rather than open a broken URL).
    """
    if not github_repo or "/" not in github_repo:
        return ""
    if not crash_file or not crash_file.exists():
        return ""
    try:
        raw = crash_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Already sanitised at write-time, but defence-in-depth.
    body = _sanitize_paths(raw)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n...(truncated)"
    # Wrap in a code block so GitHub renders the traceback monospaced.
    body_md = (
        f"**Crash report — V{app_version}**\n\n"
        "What were you doing when this happened?\n"
        "_(please add a short description above this line)_\n\n"
        f"```\n{body}\n```\n"
    )
    title = f"Crash report V{app_version} — {crash_file.stem}"
    return (
        f"https://github.com/{github_repo}/issues/new"
        f"?title={quote(title)}"
        f"&body={quote(body_md)}"
        f"&labels=crash,auto-reported"
    )
