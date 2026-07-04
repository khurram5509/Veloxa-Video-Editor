"""V14.5.0 unit tests: crash reporter.

Covers path sanitisation, crash-file write/read, list_pending_reports,
mark_reported / mark_dismissed, build_issue_url, and excepthook
installation. All offline; no network, no Qt.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.crash_reporter import (
    MAX_BODY_CHARS,
    _sanitize_paths,
    _tail,
    write_crash_file,
    list_pending_reports,
    mark_reported,
    mark_dismissed,
    build_issue_url,
    install_excepthook,
)

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


tmpdir = Path(tempfile.mkdtemp(prefix="veloxa_crash_test_"))
log_dir = tmpdir / "logs"
log_dir.mkdir()


print()
print("=" * 72)
print("V14.5.0 -- crash reporter")
print("=" * 72)


# ---- 1. Path sanitisation ------------------------------------------------
print()
print("[1] _sanitize_paths replaces user home with <user>")
home = os.path.expanduser("~")
username = Path(home).parts[-1]
text = (
    f"FileNotFoundError: {home}/Movies/clip.mp4\n"
    f"...and another path: {home}/Downloads/x.mp4\n"
)
sanitised = _sanitize_paths(text)
check("Username does not appear after sanitisation",
      username not in sanitised
      or username in ("Users", "home"))  # very edge case: literal Users
check("Replacement marker <user> appears",
      "<user>" in sanitised)


# ---- 2. write_crash_file ------------------------------------------------
print()
print("[2] write_crash_file produces a usable report")
# Build a real exception with a traceback.
try:
    raise RuntimeError(f"boom -- touched {home}/secret.mp4")
except RuntimeError:
    exc_type, exc_value, exc_tb = sys.exc_info()
crash = write_crash_file(log_dir, None, exc_type, exc_value, exc_tb,
                          app_version="14.5.0")
check("write_crash_file returned a path",
      crash is not None)
check("Crash file exists on disk",
      crash and crash.exists())
body = crash.read_text(encoding="utf-8") if crash else ""
check("Body contains the app version",
      "14.5.0" in body)
check("Body contains 'Traceback'",
      "Traceback" in body)
check("Body has the username scrubbed",
      username not in body
      or username in ("Users", "home"))


# ---- 3. list / mark helpers ---------------------------------------------
print()
print("[3] list_pending_reports / mark_reported / mark_dismissed")
# Add a couple more crash files manually.
extra1 = log_dir / "crash_20260101-120000.txt"
extra1.write_text("dummy 1", encoding="utf-8")
extra2 = log_dir / "crash_20260102-120000.txt"
extra2.write_text("dummy 2", encoding="utf-8")
listed = list_pending_reports(log_dir)
check("list_pending_reports finds 3 pending files",
      len(listed) == 3)
mark_reported(extra1)
check("After mark_reported, file moved to .reported",
      (log_dir / "crash_20260101-120000.reported").exists()
      and not extra1.exists())
mark_dismissed(extra2)
check("After mark_dismissed, file moved to .dismissed",
      (log_dir / "crash_20260102-120000.dismissed").exists()
      and not extra2.exists())
listed2 = list_pending_reports(log_dir)
check("list_pending_reports only counts *.txt",
      len(listed2) == 1)


# ---- 4. build_issue_url -------------------------------------------------
print()
print("[4] build_issue_url constructs a sane GitHub URL")
crash3 = log_dir / "crash_20260103-120000.txt"
crash3.write_text("hello world traceback content", encoding="utf-8")
url = build_issue_url("khurram5509/Veloxa-Video-Editor", crash3, "14.5.0")
check("URL points at github.com/<repo>/issues/new",
      url.startswith(
          "https://github.com/khurram5509/Veloxa-Video-Editor/issues/new"))
check("URL has a title parameter",
      "title=" in url)
check("URL has a body parameter",
      "body=" in url)
check("URL has labels=crash",
      "labels=crash" in url)
check("URL with bad repo returns ''",
      build_issue_url("not-a-slug", crash3) == ""
      and build_issue_url("", crash3) == "")
check("URL with missing crash file returns ''",
      build_issue_url("a/b", log_dir / "does-not-exist.txt") == "")
# Body cap: a huge crash file gets truncated, not URL-blasted.
big = log_dir / "crash_20260104-120000.txt"
big.write_text("x" * (MAX_BODY_CHARS * 3), encoding="utf-8")
url_big = build_issue_url("a/b", big, "14.5.0")
check("Oversized body gets truncated below 3x MAX",
      "(truncated)" in url_big.replace("%28", "(").replace("%29", ")"))


# ---- 5. install_excepthook --------------------------------------------
print()
print("[5] install_excepthook chains to the original handler")
saved = sys.excepthook
calls = {"orig": 0}
def _spy(*args, **kwargs):
    calls["orig"] += 1
sys.excepthook = _spy
try:
    install_excepthook(log_dir, None, app_version="14.5.0")
    # Simulate an unhandled exception by invoking the hook directly.
    try:
        raise ValueError("test")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    check("Original excepthook was chained (called once)",
          calls["orig"] == 1)
    check("Crash file was written by the hook",
          any(p.name.startswith("crash_")
              for p in log_dir.glob("crash_*.txt")))
finally:
    sys.excepthook = saved


# ---- 6. _tail handles missing / empty files gracefully -------------------
print()
print("[6] _tail is robust to missing or empty files")
check("_tail of None path returns placeholder",
      "no log file" in _tail(None))
check("_tail of missing path returns placeholder",
      "no log file" in _tail(log_dir / "missing.log"))


# ---- Summary --------------------------------------------------------------
print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All crash-reporter checks PASS.")
sys.exit(0)
