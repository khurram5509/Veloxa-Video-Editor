"""Profile asset storage (V11.1, extended in V11.3).

Saves the binary assets a profile depends on (image watermark, video
watermark, future fonts/LUTs/etc.) into a per-profile folder under
``%APPDATA%\\Veloxa-VD\\profile_assets\\<profile>\\`` so the profile
keeps working when:

* the original source files are moved or deleted,
* the project is opened on another machine,
* the source files live on a network share that's currently offline.

On profile *save*, ``copy_assets_into_profile`` mirrors each referenced
asset into the profile's asset folder and rewrites the path in the
profile dict to point at the in-app copy. On profile *delete*, the
matching asset folder is wiped via ``delete_profile_assets``.

A simple introspection API (``profile_asset_summary``,
``delete_all_profile_assets``) backs the "Manage Saved Data" dialog.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from pathlib import Path

log = logging.getLogger("veloxa.assets")


# Keys in a profile dict that point at on-disk files. Each entry is the
# (key_name, asset_basename_stem) pair used by ``copy_assets_into_profile``
# to figure out where to put the copy. The basename is fixed per-key so we
# don't accumulate stale copies across saves.
ASSET_KEYS = [
    ("wm_path",     "wm_image"),
    ("vid_wm_path", "wm_video"),
    # V12.3: optional intro / outro videos that get concatenated at
    # encode time. Stored next to the profile's watermarks under
    # %APPDATA%\Veloxa-VD\profile_assets\<name>\ so the profile keeps
    # working when the user moves or renames the originals.
    ("intro_path",  "intro_video"),
    ("outro_path",  "outro_video"),
]

# V11.3: profile-level audio visuals. The profile dict carries an ordered
# list under this key; each entry is a dict ``{"path": "...",
# "kind": "image"|"video"}``. Each entry's path is copied into the
# profile asset folder under a unique basename so we can tell them apart
# (``visual_001.png``, ``visual_002.mp4``, ...). On save we rewrite each
# entry's ``path`` to point at the in-app copy.
PROFILE_VISUALS_KEY = "profile_visuals"


def assets_root() -> Path:
    """Return the root folder all profile-asset bundles live under.

    On Windows this is ``%APPDATA%\\Veloxa-VD\\profile_assets``; on other
    platforms it falls back to ``~/.veloxa-vd/profile_assets``.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.veloxa-vd")
    root = Path(base) / "Veloxa-VD" / "profile_assets"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create profile assets root %s: %s", root, exc)
    return root


def safe_profile_name(name: str) -> str:
    """Sanitize a profile name for use as a folder / settings-key
    component. Public (V11.3) — used by both the CLI rotation key and
    the GUI rotation key plus the asset folder layout, so promote it
    out of the leading-underscore name-mangled namespace.
    """
    if not name:
        return "_unnamed"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", str(name).strip())
    cleaned = cleaned.strip(". ")  # Windows hates trailing dots / spaces
    return cleaned or "_unnamed"


# Back-compat alias so callers that imported the private name keep working.
_safe_name = safe_profile_name


def rotation_key_for(profile_name: str) -> str:
    """V11.3: QSettings key that holds the per-profile audio-visual
    round-robin counter."""
    return f"profile_visual_rotation/{safe_profile_name(profile_name or '_global')}"


def assets_dir_for(name: str) -> Path:
    return assets_root() / safe_profile_name(name)


def is_internal_asset(path: str) -> bool:
    """``True`` if ``path`` is already inside the profile-assets folder
    tree (i.e. a previously-saved copy)."""
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(assets_root().resolve())
    except (OSError, AttributeError, ValueError):
        # is_relative_to is 3.9+; fall back to string prefix on older
        try:
            return str(Path(path).resolve()).startswith(
                str(assets_root().resolve()))
        except OSError:
            return False


def copy_assets_into_profile(name: str, profile: dict) -> dict:
    """Mutate ``profile`` to reference internal copies of every asset key
    listed in :data:`ASSET_KEYS`. Returns the same dict for convenience.

    Behaviour:
      * Each external file is copied into ``assets_dir_for(name)``.
      * The profile path is rewritten to the copied path.
      * If a key already points at an internal copy, it's left alone.
      * If the source path is empty / missing, the key is left as-is.
      * If a copy fails, the key keeps the original (external) path so
        the profile is still usable.
    """
    if not isinstance(profile, dict):
        return profile

    target = assets_dir_for(name)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create profile asset dir %s: %s", target, exc)
        return profile

    for key, basename_stem in ASSET_KEYS:
        src = (profile.get(key) or "").strip()
        if not src:
            # V12.3 audit fix (EDGE-1): the user cleared this asset
            # (e.g. removed an intro/outro). Sweep any prior in-app copy
            # so the profile asset folder doesn't accumulate stale
            # intro_video.* / outro_video.* / wm_image.* files.
            try:
                for stale in target.glob(f"{basename_stem}.*"):
                    try:
                        stale.unlink()
                        log.info("Profile %r: pruned cleared asset %s",
                                 name, stale)
                    except OSError:
                        pass
            except OSError:
                pass
            continue
        if is_internal_asset(src) and Path(src).exists():
            # Already a saved copy — nothing to do.
            continue
        if not os.path.exists(src):
            log.info("Profile %r: asset for %s missing on disk: %s",
                     name, key, src)
            continue
        ext = Path(src).suffix or ""
        dst = target / f"{basename_stem}{ext}"
        try:
            # Clean up any prior copy with a different extension before
            # writing the new one.
            for stale in target.glob(f"{basename_stem}.*"):
                if stale != dst:
                    try:
                        stale.unlink()
                    except OSError:
                        pass
            shutil.copyfile(src, dst)
            profile[key] = str(dst)
            log.info("Profile %r: saved asset %s -> %s", name, key, dst)
        except OSError as exc:
            log.warning("Profile %r: could not copy %s -> %s: %s",
                        name, src, dst, exc)

    # ---- V11.3: profile_visuals (ordered list of audio-visual sources)
    visuals = profile.get(PROFILE_VISUALS_KEY)
    if isinstance(visuals, list):
        # V12.3.4 bugfix: re-ordering visuals + saving used to corrupt the
        # data. The old loop did ``copy(src, tmp); replace(tmp, final)`` in
        # iteration order, with ``final = visual_<i>``. When the user dragged
        # B before A and saved, the in-memory list was
        # ``[B@visual_002, A@visual_001]`` -- iteration 1 copied B over
        # visual_001 (destroying A) BEFORE iteration 2 read visual_001 for
        # A, so the second slot also ended up with B's content. Both files
        # ended up identical and A was lost.
        #
        # The fix is a strict 2-phase swap:
        #   A) Copy every source to a uniquely-named staging temp
        #      (``.staging_<token>_<i>.<ext>``) that cannot collide with
        #      any ``visual_NNN.<ext>`` source. All reads happen before
        #      any writes to final slots.
        #   B) Now that every input has been read, atomically rename each
        #      staging temp into its ``visual_NNN`` slot.
        #   C) Prune stale ``visual_*.*`` files no longer referenced.
        stage_token = uuid.uuid4().hex[:8]
        kept_paths = set()
        # ``slot_entries`` collects (i, entry_dict) tuples so we can
        # rebuild ``profile_visuals`` in user-chosen order at the end
        # regardless of which phase each entry was finalised in.
        slot_entries = []
        staged = []  # [(stage_dst, final_dst, kind, i), ...]

        # ---- Phase A: read sources into staging (no final-slot writes yet)
        for i, entry in enumerate(visuals, start=1):
            if not isinstance(entry, dict):
                continue
            src = (entry.get("path") or "").strip()
            kind = entry.get("kind") or ""
            if not src:
                continue
            if not os.path.exists(src):
                log.info("Profile %r: visual #%d missing on disk: %s",
                         name, i, src)
                # Keep the entry so the user sees what's missing.
                slot_entries.append((i, {"path": src, "kind": kind}))
                continue
            ext = Path(src).suffix or ""
            final_dst = target / f"visual_{i:03d}{ext}"
            # No-op re-save: source IS already at this slot's final
            # destination. Skip the copy.
            try:
                same = Path(src).resolve() == final_dst.resolve()
            except OSError:
                same = False
            if same:
                slot_entries.append(
                    (i, {"path": str(final_dst), "kind": kind}))
                kept_paths.add(str(final_dst.resolve()))
                continue
            stage_dst = target / f".staging_{stage_token}_{i:03d}{ext}"
            try:
                shutil.copyfile(src, stage_dst)
                staged.append((stage_dst, final_dst, kind, i))
            except OSError as exc:
                log.warning(
                    "Profile %r: could not stage visual #%d (%s): %s",
                    name, i, src, exc)
                slot_entries.append((i, {"path": src, "kind": kind}))
                try:
                    stage_dst.unlink()
                except OSError:
                    pass

        # ---- Phase B: swap stages into final slots (now safe to write)
        for stage_dst, final_dst, kind, i in staged:
            try:
                if final_dst.exists():
                    try:
                        final_dst.unlink()
                    except OSError:
                        pass
                stage_dst.replace(final_dst)
                slot_entries.append(
                    (i, {"path": str(final_dst), "kind": kind}))
                kept_paths.add(str(final_dst.resolve()))
                log.info("Profile %r: saved visual #%d -> %s",
                         name, i, final_dst)
            except OSError as exc:
                log.warning(
                    "Profile %r: could not place visual #%d -> %s: %s",
                    name, i, final_dst, exc)
                slot_entries.append((i, {"path": str(stage_dst), "kind": kind}))

        # ---- Phase C: prune stale visual_* + any orphaned staging temps
        try:
            for stale in target.glob("visual_*.*"):
                if str(stale.resolve()) not in kept_paths:
                    try:
                        stale.unlink()
                    except OSError:
                        pass
            for orphan in target.glob(f".staging_{stage_token}_*"):
                try:
                    orphan.unlink()
                except OSError:
                    pass
        except OSError:
            pass

        # Restore user-chosen order (slot_entries can interleave Phase A
        # immediate-appends with Phase B late-appends).
        slot_entries.sort(key=lambda t: t[0])
        profile[PROFILE_VISUALS_KEY] = [entry for _, entry in slot_entries]

    return profile


def delete_profile_assets(name: str) -> bool:
    """Remove the assets folder for ``name``. Returns ``True`` if anything
    was deleted, ``False`` if nothing was there to begin with."""
    target = assets_dir_for(name)
    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        log.info("Deleted profile assets folder: %s", target)
        return True
    except OSError as exc:
        log.warning("Could not delete %s: %s", target, exc)
        return False


def delete_all_profile_assets() -> int:
    """Wipe every per-profile asset folder. Returns the number of folders
    actually removed."""
    root = assets_root()
    removed = 0
    if not root.exists():
        return 0
    for child in root.iterdir():
        if child.is_dir():
            try:
                shutil.rmtree(child)
                removed += 1
            except OSError as exc:
                log.warning("Could not delete %s: %s", child, exc)
    return removed


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def profile_asset_summary() -> list[dict]:
    """Return one entry per profile-asset folder, with file count and size,
    sorted by name. Used by the Manage-Saved-Data dialog.
    """
    root = assets_root()
    rows = []
    if not root.exists():
        return rows
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        files = [p for p in child.rglob("*") if p.is_file()]
        rows.append({
            "name": child.name,
            "path": str(child),
            "file_count": len(files),
            "size_bytes": _dir_size_bytes(child),
        })
    return rows
