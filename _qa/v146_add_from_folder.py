"""V14.6.0 unit test: recursive folder scan for the new
'Add from Folder' button.

Builds a temp directory tree with a mix of supported and unsupported
files at multiple nesting levels, then drives
``MainWindow._collect_supported_files`` (bound to a stub) and checks
that the returned list contains the right paths in deterministic
sorted order.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main_window import MainWindow, ALL_INPUT_EXTS

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f": {detail}" if detail and not ok else ""))


# ---- Build the fixture tree ----------------------------------------------
fixt = Path(tempfile.mkdtemp(prefix="veloxa_addfolder_"))
# Root: 1 video + 1 audio + 1 non-supported (sidecar .srt).
(fixt / "01_root_video.mp4").write_bytes(b"\0" * 100)
(fixt / "02_root_audio.mp3").write_bytes(b"\0" * 100)
(fixt / "notes.srt").write_text("sub", encoding="utf-8")
# Subfolder season01: 2 videos + 1 image (image must be ignored at
# folder-add — it's not in ALL_INPUT_EXTS).
s1 = fixt / "Season01"
s1.mkdir()
(s1 / "ep01.mkv").write_bytes(b"\0" * 100)
(s1 / "ep02.mkv").write_bytes(b"\0" * 100)
(s1 / "thumbnail.jpg").write_bytes(b"\0" * 100)
# Nested subfolder: 1 audio + 1 video, plus an unsupported extension.
nested = fixt / "Season01" / "extras"
nested.mkdir()
(nested / "interview.wav").write_bytes(b"\0" * 100)
(nested / "behind_the_scenes.mov").write_bytes(b"\0" * 100)
(nested / "credits.docx").write_bytes(b"\0" * 100)
# Empty subfolder — must not break the walk.
(fixt / "empty_dir").mkdir()


# ---- Stub the method off MainWindow without instantiating the window ------
# _collect_supported_files only touches os.walk + Path; no Qt state.
class _Stub:
    pass
stub = _Stub()
collect = MainWindow._collect_supported_files.__get__(stub)


print()
print("=" * 72)
print("V14.6.0 — Add from Folder (recursive scan)")
print("=" * 72)


# ---- 1. Basic collection -------------------------------------------------
print()
print("[1] Recursive collection picks only supported extensions")
result = collect(str(fixt))
expected_basenames = {
    "01_root_video.mp4", "02_root_audio.mp3",
    "ep01.mkv", "ep02.mkv",
    "interview.wav", "behind_the_scenes.mov",
}
got_basenames = {Path(p).name for p in result}
check("All 6 supported files collected",
      got_basenames == expected_basenames,
      f"got={sorted(got_basenames)}")
check("Sidecar .srt was skipped",
      not any(p.endswith(".srt") for p in result))
check("Thumbnail .jpg was skipped",
      not any(p.endswith(".jpg") for p in result))
check("Notes .docx was skipped",
      not any(p.endswith(".docx") for p in result))
check("Empty subfolder didn't break the walk",
      "empty_dir" not in " ".join(result))


# ---- 2. Deterministic sort order ----------------------------------------
print()
print("[2] Output order is deterministic (case-insensitive sort per dir)")
# Each result should be sorted within its parent directory, depth-
# first via os.walk's dirs.sort + files.sort.
# Build the expected order:
expected_order = [
    str(fixt / "01_root_video.mp4"),
    str(fixt / "02_root_audio.mp3"),
    str(fixt / "Season01" / "ep01.mkv"),
    str(fixt / "Season01" / "ep02.mkv"),
    str(fixt / "Season01" / "extras" / "behind_the_scenes.mov"),
    str(fixt / "Season01" / "extras" / "interview.wav"),
]
check("Result matches expected depth-first sorted order",
      result == expected_order,
      f"got={result}")


# ---- 3. max_files cap ----------------------------------------------------
print()
print("[3] max_files cap stops the walk early")
capped = collect(str(fixt), max_files=3)
check("Cap returns exactly max_files entries",
      len(capped) == 3, f"got {len(capped)}")
check("Capped result is the first 3 of the full result",
      capped == result[:3])


# ---- 4. Missing folder is graceful (no exception, empty list) ------------
print()
print("[4] Missing folder returns []")
missing = collect(str(fixt / "does_not_exist"))
check("Missing folder returns empty list (no exception)",
      missing == [])


# ---- 5. Folder with zero supported files returns []
print()
print("[5] Folder with no supported files returns []")
empty_fixt = Path(tempfile.mkdtemp(prefix="veloxa_addfolder_empty_"))
(empty_fixt / "notes.txt").write_text("nope", encoding="utf-8")
(empty_fixt / "image.png").write_bytes(b"\0" * 4)
result_empty = collect(str(empty_fixt))
check("Returns [] when nothing in folder is supported",
      result_empty == [])


# ---- 6. Source-level wiring -----------------------------------------------
print()
print("[6] Source-level wiring of the new button + handler")
import inspect
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("MainWindow defines _on_add_folder_clicked",
      "def _on_add_folder_clicked" in mw_src)
check("MainWindow defines _collect_supported_files",
      "def _collect_supported_files" in mw_src)
check("'Add from Folder' button wired to _on_add_folder_clicked",
      "self.add_folder_btn" in mw_src
      and "_on_add_folder_clicked" in mw_src)
check("add_folder_btn stays enabled mid-batch (mirrors add_btn)",
      "add_folder_btn.setEnabled(True)" in mw_src)


# ---- 7. _on_add_folder_clicked routes through _add_files ----------------
_handler_src = mw_src.split(
    "def _on_add_folder_clicked")[1].split("def ")[0]
check("Handler funnels collected paths through self._add_files()",
      "self._add_files(collected)" in _handler_src)
check("Handler uses QFileDialog.getExistingDirectory",
      "getExistingDirectory" in _handler_src)
check("Handler persists the chosen folder under last_folder_add_dir",
      'last_folder_add_dir' in _handler_src)


print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" — {d}" if d else ""))
    sys.exit(1)
print("All Add-from-Folder checks PASS.")
sys.exit(0)
