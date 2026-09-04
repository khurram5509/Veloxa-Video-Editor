"""V14.11.0: Save Progress — named draft storage.

A *draft* is a complete snapshot of a work session: the queue (every
row, its per-row profile assignment, and its done/pending status) plus
the whole main-window settings dict (Trim / Watermark / Audio Visuals /
Output). Drafts let the user stop at any point, come back later, and
resume, edit, start, or delete the saved work.

Storage: one JSON file per draft under
``%APPDATA%\\Veloxa-VD\\V10\\drafts\\<id>.json`` (``~/Library/...`` on
macOS via :func:`app.persistence.app_data_dir`). Writes are atomic
(temp file + ``os.replace``) so a crash mid-save can never truncate an
existing draft.

Two ids are reserved:
  ``autosave``      -- the rolling auto-save slot used when no named
                       draft is open.
  ``last_session``  -- mirrors the crash-recovery queue state, so the
                       previous session shows up in the drafts list
                       alongside everything else.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from .persistence import app_data_dir

log = logging.getLogger("veloxa.drafts")

DRAFT_FORMAT_VERSION = 1

AUTOSAVE_ID = "autosave"
LAST_SESSION_ID = "last_session"
RESERVED_IDS = (AUTOSAVE_ID, LAST_SESSION_ID)

# Reserved drafts are maintained by the app, not the user: they can be
# opened and deleted like any other draft, but they aren't renamed and
# they're labelled distinctly in the manager.
RESERVED_LABELS = {
    AUTOSAVE_ID: "Autosave (latest)",
    LAST_SESSION_ID: "Last session",
}


def drafts_dir() -> Path:
    d = app_data_dir() / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _draft_path(draft_id: str) -> Path:
    return drafts_dir() / f"{draft_id}.json"


def new_draft_id() -> str:
    return f"d_{uuid.uuid4().hex[:12]}"


def _safe_id(draft_id: str) -> bool:
    """Guard against path traversal via a crafted id."""
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", draft_id or ""))


def make_draft(name: str, items: list, settings: dict,
               draft_id: str = "", kind: str = "manual") -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "veloxa_draft_version": DRAFT_FORMAT_VERSION,
        "id": draft_id or new_draft_id(),
        "name": name or "Untitled draft",
        "kind": kind,                 # manual | autosave | last_session
        "created_at": now,
        "updated_at": now,
        "items": items or [],
        "settings": settings or {},
    }


def save_draft(draft: dict) -> str:
    """Persist ``draft`` atomically, refreshing ``updated_at``. Returns
    the draft id, or "" on failure (never raises -- a failed save must
    not take the app down mid-batch)."""
    draft_id = str(draft.get("id") or "")
    if not _safe_id(draft_id):
        log.warning("Refusing to save draft with unsafe id: %r", draft_id)
        return ""
    draft["updated_at"] = datetime.now().isoformat(timespec="seconds")
    draft.setdefault("veloxa_draft_version", DRAFT_FORMAT_VERSION)
    target = _draft_path(draft_id)
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return draft_id
    except (OSError, TypeError, ValueError) as e:
        log.warning("Could not save draft %s: %s", draft_id, e)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return ""


def load_draft(draft_id: str) -> dict | None:
    if not _safe_id(draft_id):
        return None
    p = _draft_path(draft_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read draft %s: %s", draft_id, e)
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", draft_id)
    data.setdefault("name", "Untitled draft")
    data.setdefault("kind", "manual")
    if not isinstance(data.get("items"), list):
        data["items"] = []
    if not isinstance(data.get("settings"), dict):
        data["settings"] = {}
    return data


def list_drafts() -> list:
    """Every saved draft, newest-updated first. Corrupt files are
    skipped rather than breaking the whole listing."""
    out = []
    try:
        paths = list(drafts_dir().glob("*.json"))
    except OSError:
        return out
    for p in paths:
        d = load_draft(p.stem)
        if d is None:
            continue
        items = d.get("items", [])
        out.append({
            "id": d["id"],
            "name": d["name"],
            "kind": d.get("kind", "manual"),
            "created_at": d.get("created_at", ""),
            "updated_at": d.get("updated_at", ""),
            "n_items": len(items),
            "n_done": sum(1 for it in items
                          if isinstance(it, dict)
                          and it.get("status") == "done"),
        })
    out.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
    return out


def delete_draft(draft_id: str) -> bool:
    if not _safe_id(draft_id):
        return False
    p = _draft_path(draft_id)
    try:
        if p.exists():
            p.unlink()
        return True
    except OSError as e:
        log.warning("Could not delete draft %s: %s", draft_id, e)
        return False


def rename_draft(draft_id: str, new_name: str) -> bool:
    d = load_draft(draft_id)
    if d is None:
        return False
    d["name"] = (new_name or "").strip() or d.get("name", "Untitled draft")
    return bool(save_draft(d))


def display_name(meta: dict) -> str:
    """Manager-facing label: reserved drafts get their fixed label so
    the user can tell app-maintained entries from their own."""
    did = meta.get("id", "")
    if did in RESERVED_LABELS:
        return RESERVED_LABELS[did]
    return meta.get("name") or "Untitled draft"


def rebase_profile_names(renames: dict = None, deleted: set = None,
                         fallback: str = "") -> int:
    """V14.11.3: keep saved drafts in step with profile renames/deletes.

    The live queue is rebased by ``MainWindow._rebase_queue_rows``; this
    does the same for every draft ON DISK, whose rows would otherwise be
    left pinned to a name that no longer exists. Such a row silently
    falls back to the live form at encode time (see ``_opts_for_row``),
    i.e. the user encodes with the wrong settings and no error -- the
    exact failure the live-queue rebase was added to prevent.

    ``renames`` maps OLD -> NEW; rows pinned to a name in ``deleted``
    are set to ``fallback`` (the caller passes NO_PROFILE). Returns the
    number of rows rewritten across all drafts. Never raises.
    """
    renames = renames or {}
    deleted = deleted or set()
    if not renames and not deleted:
        return 0
    touched = 0
    for meta in list_drafts():
        d = load_draft(meta["id"])
        if not d:
            continue
        changed = 0
        for it in d.get("items", []):
            if not isinstance(it, dict):
                continue
            pn = it.get("profile_name") or ""
            if pn in renames:
                it["profile_name"] = renames[pn]
                changed += 1
            elif pn in deleted:
                it["profile_name"] = fallback
                changed += 1
        if changed:
            if save_draft(d):
                touched += changed
                log.info("Rebased %d row(s) in draft %s", changed, d["id"])
    return touched
