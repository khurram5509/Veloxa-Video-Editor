"""V14.3.4 verification: pick_release_asset must NEVER return the
opposite platform's installer.

Critical: a macOS user must never receive a ``Setup.exe`` and a Windows
user must never receive a ``.dmg``. Tests both branches by
monkey-patching ``app.platform_compat.IS_WIN`` and ``IS_MAC`` directly.

Uses the actual V14.3.3 release asset names and a battery of
adversarial near-miss filenames that try to fool the picker.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import platform_compat as _pc

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


def asset(name, url=None):
    return {
        "name": name,
        "browser_download_url": url or f"https://example.com/{name}",
        "size": 100,
    }


# Save real platform flags so we can restore.
SAVED_WIN, SAVED_MAC, SAVED_LINUX = (
    _pc.IS_WIN, _pc.IS_MAC, _pc.IS_LINUX)


def set_platform(win=False, mac=False, linux=False):
    _pc.IS_WIN = win
    _pc.IS_MAC = mac
    _pc.IS_LINUX = linux


def restore_platform():
    _pc.IS_WIN, _pc.IS_MAC, _pc.IS_LINUX = SAVED_WIN, SAVED_MAC, SAVED_LINUX


# ===========================================================================
# Test cases
# ===========================================================================

print()
print("=" * 72)
print("V14.3.4 -- platform-asset routing")
print("=" * 72)

# Actual V14.3.3 release shape.
v143 = [
    asset("Veloxa-Video-Editor-V14.3.3-Setup.exe"),
    asset("Veloxa-Video-Editor-V14.3.3-macOS.dmg"),
]

# ---- Windows must pick the .exe -------------------------------------------
print()
print("[1] Windows: must always pick the Setup.exe, NEVER the .dmg")
try:
    set_platform(win=True)
    picked = _pc.pick_release_asset(v143)
    check("Win picks an asset",
          picked is not None)
    check("Win-picked asset name ends in .exe",
          picked["name"].lower().endswith(".exe"))
    check("Win-picked asset is NOT the .dmg",
          not picked["name"].lower().endswith(".dmg"))
    check("Win-picked asset contains 'setup'",
          "setup" in picked["name"].lower())
    # Reversed asset order -- still picks .exe.
    picked2 = _pc.pick_release_asset(list(reversed(v143)))
    check("Win picks .exe regardless of asset order",
          picked2["name"].lower().endswith(".exe"))
    # Only DMG present (corrupt release) -- Win returns None, NOT .dmg.
    only_dmg = [asset("Veloxa-Video-Editor-V14.3.3-macOS.dmg")]
    picked3 = _pc.pick_release_asset(only_dmg)
    check("Win refuses to serve a .dmg as fallback (returns None)",
          picked3 is None)
finally:
    restore_platform()


# ---- macOS must pick the .dmg ---------------------------------------------
print()
print("[2] macOS: must always pick the .dmg, NEVER the Setup.exe")
try:
    set_platform(mac=True)
    picked = _pc.pick_release_asset(v143)
    check("Mac picks an asset",
          picked is not None)
    check("Mac-picked asset name ends in .dmg",
          picked["name"].lower().endswith(".dmg"))
    check("Mac-picked asset is NOT the .exe",
          not picked["name"].lower().endswith(".exe"))
    check("Mac-picked asset contains 'macOS'",
          "macos" in picked["name"].lower())
    # Reversed order -- still picks .dmg.
    picked2 = _pc.pick_release_asset(list(reversed(v143)))
    check("Mac picks .dmg regardless of asset order",
          picked2["name"].lower().endswith(".dmg"))
    # Only EXE present (corrupt release) -- Mac returns None, NOT .exe.
    only_exe = [asset("Veloxa-Video-Editor-V14.3.3-Setup.exe")]
    picked3 = _pc.pick_release_asset(only_exe)
    check("Mac refuses to serve a .exe as fallback (returns None)",
          picked3 is None)
finally:
    restore_platform()


# ---- Adversarial: filenames designed to fool the picker -------------------
print()
print("[3] Adversarial filenames -- should never mix platforms")

adversarial = [
    asset("Veloxa-macOS-Setup.exe"),     # Win pick OK (it's the exe, "macOS" in name)
    asset("Veloxa-windows-Setup.dmg"),   # Mac pick OK (it's the dmg, "windows" in name)
    asset("README.dmg"),                 # noise -- Mac may consider
    asset("CHANGELOG.exe"),              # noise -- Win may consider
    asset("Veloxa-V14.3.3-Setup.exe"),   # the real one
    asset("Veloxa-V14.3.3-macOS.dmg"),   # the real one
]

try:
    set_platform(win=True)
    picked = _pc.pick_release_asset(adversarial)
    check("Win (adversarial): picks an .exe",
          picked["name"].lower().endswith(".exe"))
    check("Win (adversarial): picks a 'setup' .exe (real installer)",
          "setup" in picked["name"].lower())
finally:
    restore_platform()

try:
    set_platform(mac=True)
    picked = _pc.pick_release_asset(adversarial)
    check("Mac (adversarial): picks a .dmg",
          picked["name"].lower().endswith(".dmg"))
finally:
    restore_platform()


# ---- Empty asset list returns None, not garbage --------------------------
print()
print("[4] Empty / malformed asset list")
try:
    set_platform(win=True)
    check("Win on []: None",
          _pc.pick_release_asset([]) is None)
    check("Win on None: None",
          _pc.pick_release_asset(None) is None)
finally:
    restore_platform()
try:
    set_platform(mac=True)
    check("Mac on []: None",
          _pc.pick_release_asset([]) is None)
    check("Mac on None: None",
          _pc.pick_release_asset(None) is None)
finally:
    restore_platform()


# ---- Real GitHub-shaped asset object goes through check_for_updates ------
print()
print("[5] check_for_updates uses pick_release_asset internally")
import inspect
from app import updater as _u
# V14.11.1: the body moved into check_for_updates_detailed; the old
# name is now a thin wrapper that delegates to it.
src = inspect.getsource(_u.check_for_updates_detailed)
check("check_for_updates imports pick_release_asset",
      "pick_release_asset" in src)
# The asset-selection logic must NOT contain a hardcoded ``.exe``
# comparison (``endswith(".exe")`` or ``"setup" in name``) anywhere
# between the function definition and the ``return UpdateInfo``. Comments
# / fallback filenames are stripped first so they don't trip the check.
import re as _re
_logic_lines = [
    ln for ln in src.splitlines()
    # Drop comments AND drop string literals that look like fallback
    # filenames (asset_name=... defaults).
    if not ln.lstrip().startswith("#")
    and "asset_name=" not in ln
]
_logic_only = "\n".join(_logic_lines)
check("check_for_updates has no hardcoded .exe filter logic",
      'endswith(".exe")' not in _logic_only
      and "'setup' in" not in _logic_only.lower()
      and '"setup" in' not in _logic_only.lower())

# launch_installer must dispatch by platform too.
src2 = inspect.getsource(_pc.launch_installer)
check("launch_installer branches on IS_WIN/IS_MAC",
      "IS_WIN" in src2 and "IS_MAC" in src2)


# ---- Live (actual) GitHub release: do platform-specific lookups return
# the right asset for the v14.3.3 release? Network-conditional.
print()
print("[6] Live GitHub release lookup (network) -- best-effort")
import urllib.request, urllib.error, json
try:
    req = urllib.request.Request(
        "https://api.github.com/repos/khurram5509/Veloxa-Video-Editor/"
        "releases/tags/v14.3.3",
        headers={"User-Agent": "veloxa-asset-routing-test/1.0",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        live = json.loads(resp.read().decode("utf-8"))
    live_assets = live.get("assets") or []
    if len(live_assets) >= 2:
        try:
            set_platform(win=True)
            wp = _pc.pick_release_asset(live_assets)
            check("LIVE Win: picks .exe asset",
                  wp and wp["name"].endswith(".exe"))
            check("LIVE Win: picked asset URL ends in .exe",
                  wp and wp.get(
                      "browser_download_url", "").endswith(".exe"))
        finally:
            restore_platform()
        try:
            set_platform(mac=True)
            mp = _pc.pick_release_asset(live_assets)
            check("LIVE Mac: picks .dmg asset",
                  mp and mp["name"].endswith(".dmg"))
            check("LIVE Mac: picked asset URL ends in .dmg",
                  mp and mp.get(
                      "browser_download_url", "").endswith(".dmg"))
        finally:
            restore_platform()
    else:
        check("LIVE release has both assets attached",
              False, f"only {len(live_assets)} asset(s) found")
except (urllib.error.URLError, urllib.error.HTTPError,
        TimeoutError, OSError) as exc:
    print(f"  SKIP  Live lookup skipped (offline): {exc}")


# ---- Summary --------------------------------------------------------------
print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All platform-asset-routing checks PASS.")
print("Mac users -> .dmg only. Windows users -> .exe only. No mixing.")
sys.exit(0)
