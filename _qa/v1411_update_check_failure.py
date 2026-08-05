"""V14.11.1: a FAILED update check must never be reported as
"You're up to date."

Reported from the field: a V14.10.0 install showed "You're up to date"
while V14.11.0 was live on GitHub. Root cause -- check_for_updates()
returned a bare None for BOTH "already current" AND every failure
(offline / rate limited / 404 / bad JSON), and the UI rendered that
single None as success. A real update stayed invisible.

These probes lock in the three-way outcome: update available /
genuinely current / check failed.
"""
import io
import os
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app.updater as u

PASS, FAIL = [], []
def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f": {detail}" if detail and not ok else ""))


def _http_error(code, headers=None, msg="err"):
    return urllib.error.HTTPError(
        "https://api.github.com/x", code, msg, headers or {},
        io.BytesIO(b""))


print()
print("=" * 72)
print("V14.11.1 -- failed update check must not read as 'up to date'")
print("=" * 72)

print()
print("[1] HTTP errors are classified into actionable messages")
rl = _http_error(403, {"X-RateLimit-Remaining": "0",
                       "X-RateLimit-Reset": "1900000000"})
rl_msg = u._describe_http_error(rl)
check("rate limit names the cause", "hourly API limit" in rl_msg, rl_msg)
check("rate limit suggests when to retry", "Try again after" in rl_msg,
      rl_msg)
check("plain 403 is distinguishable",
      "403" in u._describe_http_error(_http_error(403, {})))
check("404 explains a missing/private repo",
      "not found" in u._describe_http_error(_http_error(404)).lower())
check("unknown code still yields a message",
      "500" in u._describe_http_error(_http_error(500)))

print()
print("[2] detailed() separates 'failed' from 'up to date'")
info, err = u.check_for_updates_detailed(github_repo="",
                                         local_version="1.0")
check("unconfigured repo reports an ERROR (not silent success)",
      info is None and bool(err), f"err={err!r}")

import urllib.request as _ur

def _boom(*a, **k):
    raise _http_error(403, {"X-RateLimit-Remaining": "0"})

_saved = _ur.urlopen
try:
    _ur.urlopen = _boom
    info, err = u.check_for_updates_detailed(
        github_repo="owner/repo", local_version="14.10.0")
    check("rate-limited check returns (None, error)",
          info is None and "hourly API limit" in err, f"err={err!r}")

    def _offline(*a, **k):
        raise urllib.error.URLError("getaddrinfo failed")
    _ur.urlopen = _offline
    info, err = u.check_for_updates_detailed(
        github_repo="owner/repo", local_version="14.10.0")
    check("offline check returns (None, error)",
          info is None and "Could not reach GitHub" in err, f"err={err!r}")

    def _garbage(*a, **k):
        class R:
            def read(self): return b"<html>not json</html>"
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    _ur.urlopen = _garbage
    info, err = u.check_for_updates_detailed(
        github_repo="owner/repo", local_version="14.10.0")
    check("malformed JSON returns (None, error)",
          info is None and bool(err), f"err={err!r}")

    def _current(*a, **k):
        class R:
            def read(self):
                return (b'{"tag_name":"v14.10.0","assets":'
                        b'[{"name":"x-Setup.exe","browser_download_url":'
                        b'"http://x/x.exe","size":1}]}')
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    _ur.urlopen = _current
    info, err = u.check_for_updates_detailed(
        github_repo="owner/repo", local_version="14.10.0")
    check("genuinely up to date returns (None, '') -- NO error",
          info is None and err == "", f"err={err!r}")

    def _newer(*a, **k):
        class R:
            def read(self):
                return (b'{"tag_name":"v14.11.0","name":"n","body":"b",'
                        b'"html_url":"http://x","assets":[]}')
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()
    _ur.urlopen = _newer
    info, err = u.check_for_updates_detailed(
        github_repo="owner/repo", local_version="14.10.0")
    check("newer release with no platform asset reports an error",
          info is None and "no installer" in err.lower(), f"err={err!r}")
finally:
    _ur.urlopen = _saved

print()
print("[3] The exact field regression: 14.10.0 must see 14.11.0")
check("is_newer('14.11.0','14.10.0')", u.is_newer("14.11.0", "14.10.0"))
check("is_newer('14.10.0','14.9.1') -- two-digit minor",
      u.is_newer("14.10.0", "14.9.1"))
check("not is_newer('14.10.0','14.11.0')",
      not u.is_newer("14.10.0", "14.11.0"))

print()
print("[4] Wiring: a distinct failure path exists end to end")
up_src = (ROOT / "app" / "updater.py").read_text(encoding="utf-8")
check("UpdateChecker exposes check_failed signal",
      "check_failed = pyqtSignal(str, bool)" in up_src)
check("run() routes errors to check_failed, not no_update",
      "self.check_failed.emit(error, self._manual)" in up_src)
check("check_for_updates kept for backward compatibility",
      "def check_for_updates(" in up_src)
mw_src = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
check("main_window connects check_failed",
      "c.check_failed.connect(self._on_update_check_failed)" in mw_src)
check("failure dialog exists",
      "def _on_update_check_failed" in mw_src)
# NB the sentence is split across two f-string literals in the source,
# so match the distinctive fragment rather than the rendered sentence.
check("failure dialog says it is NOT a clean bill of health",
      "<i>not</i> mean you're up to date" in mw_src)
check("failure dialog offers Retry",
      '"Retry"' in mw_src)
check("stale 'looks the same as up to date' disclaimer removed",
      "looks the same as 'up to" not in mw_src)

print()
print("=" * 72)
print(f"Total: {len(PASS)+len(FAIL)}    Pass: {len(PASS)}    Fail: {len(FAIL)}")
if FAIL:
    print()
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f" -- {d}" if d else ""))
    sys.exit(1)
print("All V14.11.1 update-check-failure checks PASS.")
sys.exit(0)
