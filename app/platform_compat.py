"""V14.2.0: cross-platform thin wrappers.

Centralises the half-dozen places where Windows-only APIs leaked into
the rest of the app:

* opening a folder in the system file manager (``startfile`` on
  Windows, ``open`` on macOS, ``xdg-open`` on Linux)
* picking the right installer asset off a GitHub release (``.exe`` on
  Windows, ``.dmg`` on macOS, ``.AppImage`` on Linux)
* launching an installer / DMG and asking the running app to quit so
  the install can replace its files

Keeping this module Qt-free so it can be imported by the engine + CLI
layers too.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("veloxa.platform")


IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------- file manager

def open_in_file_manager(path) -> bool:
    """Open ``path`` in the platform's file manager.

    * Windows: ``os.startfile`` (Explorer)
    * macOS: ``open`` (Finder)
    * Linux: ``xdg-open`` (whatever the user's default is)

    Returns ``True`` on apparent success. Best-effort — swallows
    OSError so a broken file association can't crash the GUI.
    """
    p = str(path)
    try:
        if IS_WIN:
            os.startfile(p)  # type: ignore[attr-defined]
            return True
        if IS_MAC:
            subprocess.Popen(["open", p])
            return True
        # Linux / other.
        subprocess.Popen(["xdg-open", p])
        return True
    except (OSError, FileNotFoundError) as exc:
        log.info("open_in_file_manager failed for %r: %s", p, exc)
        return False


# ---------------------------------------------------------------- asset picker

def pick_release_asset(assets: list) -> Optional[dict]:
    """Choose the right installer asset for this platform from a
    GitHub release's ``assets`` array.

    Preference order (case-insensitive):

    * Windows: ``*Setup*.exe`` → ``*Installer*.exe`` → any ``*.exe``
    * macOS:   any ``*.dmg`` → ``*.pkg`` → ``*.zip`` (last resort)
    * Linux:   ``*.AppImage`` → ``*.deb`` → ``*.tar.gz``

    Returns ``None`` if no suitable asset is found.
    """
    if not assets:
        return None
    if IS_WIN:
        setup, installer, generic = [], [], []
        for a in assets:
            name = (a.get("name") or "").lower()
            if not name.endswith(".exe"):
                continue
            if "setup" in name:
                setup.append(a)
            elif "installer" in name:
                installer.append(a)
            else:
                generic.append(a)
        for bucket in (setup, installer, generic):
            if bucket:
                return bucket[0]
        return None
    if IS_MAC:
        for ext in (".dmg", ".pkg", ".zip"):
            for a in assets:
                name = (a.get("name") or "").lower()
                if name.endswith(ext):
                    return a
        return None
    # Linux / other.
    for ext in (".appimage", ".deb", ".tar.gz"):
        for a in assets:
            name = (a.get("name") or "").lower()
            if name.endswith(ext):
                return a
    return None


# ---------------------------------------------------------------- installer

def launch_installer(installer_path: str) -> bool:
    """Spawn the downloaded installer and detach.

    * Windows: ``Veloxa-Video-Editor-V*-Setup.exe`` — run directly,
      the wizard takes over. The CREATE_NEW_PROCESS_GROUP +
      DETACHED_PROCESS flags ensure the installer survives our app
      exit.
    * macOS: ``.dmg`` — call ``open`` which mounts the disk image
      and shows the install drag-window in Finder. The user drags
      Veloxa.app to /Applications.
    * Linux: ``.AppImage`` — run directly.
    """
    if not installer_path or not os.path.exists(installer_path):
        return False
    try:
        if IS_WIN:
            flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                     | getattr(subprocess, "DETACHED_PROCESS", 0))
            subprocess.Popen([installer_path], close_fds=True,
                             creationflags=flags)
            return True
        if IS_MAC:
            subprocess.Popen(["open", installer_path], close_fds=True)
            return True
        # Linux.
        # Make it executable in case GitHub asset metadata stripped the
        # +x bit (zip / artifact handling sometimes does).
        try:
            os.chmod(installer_path, 0o755)
        except OSError:
            pass
        subprocess.Popen([installer_path], close_fds=True)
        return True
    except OSError as exc:
        log.warning("launch_installer failed: %s", exc)
        return False


# ---------------------------------------------------------------- FFmpeg locator

def find_bundled_ffmpeg() -> tuple:
    """Return (ffmpeg_path, ffprobe_path) for a bundled binary, or
    (None, None) if not found. Uses different conventions per
    platform:

    * Windows: ``<exe_dir>/ffmpeg/ffmpeg.exe`` or ``_MEIPASS/ffmpeg``
    * macOS:   ``Veloxa.app/Contents/Resources/ffmpeg`` (PyInstaller
      onedir bundles put data alongside the binary) OR
      ``_MEIPASS/ffmpeg`` for onefile.
    * Linux:   ``<exe_dir>/ffmpeg/ffmpeg``

    Engine code should call this BEFORE falling back to ``shutil.which``.
    """
    ff_name = "ffmpeg.exe" if IS_WIN else "ffmpeg"
    fp_name = "ffprobe.exe" if IS_WIN else "ffprobe"
    dirs = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # Windows / Linux: ffmpeg/ alongside the EXE.
        dirs.append(exe_dir / "ffmpeg")
        # macOS .app bundle: Contents/MacOS/Veloxa is sys.executable,
        # so Contents/Resources/ffmpeg is the bundled-data location.
        if IS_MAC:
            dirs.append(exe_dir.parent / "Resources" / "ffmpeg")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass) / "ffmpeg")
    else:
        dirs.append(Path(__file__).resolve().parent.parent / "ffmpeg")
    for d in dirs:
        ff = d / ff_name
        fp = d / fp_name
        if ff.exists() and fp.exists():
            return str(ff), str(fp)
    # Fall back to PATH.
    return shutil.which("ffmpeg"), shutil.which("ffprobe")


# ---------------------------------------------------------------- platform tag

def platform_tag() -> str:
    """One-word platform label used in logs and version strings."""
    if IS_WIN:
        return "windows"
    if IS_MAC:
        return "macos"
    if IS_LINUX:
        return "linux"
    return sys.platform
