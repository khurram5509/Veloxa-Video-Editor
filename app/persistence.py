"""File logging setup and queue-state persistence (`%APPDATA%\\Veloxa-VD\\V10\\`)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------- paths

def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "Veloxa-VD" / "V10"
    d.mkdir(parents=True, exist_ok=True)
    return d


def watermarks_dir() -> Path:
    """Central location for image watermarks copied into the app's data dir.

    Lives one level above the V10 folder so it's shared across versions.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "Veloxa-VD" / "watermarks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def import_watermark_image(src_path: str) -> str:
    """Copy a user-picked image into the app's watermarks folder, returning
    the local path.

    Dedupes by content hash, so re-picking the same file (or any file with
    identical content) reuses the existing copy rather than creating a
    duplicate. The original file is left untouched.

    Returns the original path on any failure (unreadable file, copy error,
    unsupported extension) so the caller can still proceed.
    """
    if not src_path or not os.path.exists(src_path):
        return src_path or ""

    valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    suffix = Path(src_path).suffix.lower()
    if suffix not in valid_exts:
        return src_path

    try:
        h = hashlib.sha256()
        with open(src_path, "rb") as fp:
            for chunk in iter(lambda: fp.read(65536), b""):
                h.update(chunk)
        digest = h.hexdigest()[:16]
    except OSError:
        return src_path

    dst = watermarks_dir() / f"wm_{digest}{suffix}"
    if not dst.exists():
        try:
            shutil.copy2(src_path, dst)
        except OSError as e:
            logging.getLogger("veloxa.persistence").warning(
                "Could not copy watermark to app folder: %s", e)
            return src_path
    return str(dst)


def queue_state_path() -> Path:
    return app_data_dir() / "queue_state.json"


def log_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- logging

def setup_logging() -> Path:
    """Configure the ``veloxa`` logger to write to a per-session file.

    Returns the log file path so the UI can show / open it.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir() / f"session-{timestamp}.log"

    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger("veloxa")
    root.setLevel(logging.INFO)
    # Avoid duplicating handlers if setup_logging runs twice.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)

    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        root.addHandler(console)

    root.info("Veloxa Video Editor V12.3 session start; logging to %s", log_file)
    return log_file


def prune_old_logs(keep: int = 30):
    """Keep only the most recent ``keep`` session logs."""
    try:
        files = sorted(
            log_dir().glob("session-*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for f in files[keep:]:
            try:
                f.unlink()
            except OSError:
                pass
    except OSError:
        pass


# ---------------------------------------------------------------- queue state

def save_queue_state(items: list) -> None:
    """Atomically persist the queue. ``items`` is a list of dicts (use
    ``QueueItemData.to_dict()``)."""
    payload = {
        "veloxa_version": "V10",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    target = queue_state_path()
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as e:
        logging.getLogger("veloxa.persistence").warning(
            "Could not save queue state: %s", e)


def load_queue_state() -> list:
    """Return the previous session's queue items as a list of dicts (or [])."""
    p = queue_state_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("items", [])
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def clear_queue_state() -> None:
    p = queue_state_path()
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
