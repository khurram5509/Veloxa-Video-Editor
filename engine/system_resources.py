"""V14.3.0: process-priority + thread-cap + RAM-watchdog helpers.

Used by ``JobRunner`` when running the auxiliary CPU encoder
("Also use CPU encoder when GPU is busy" toggle in the GUI). The
goal is: the parallel CPU job should make the encode faster when
the system has slack, but it must NEVER cause the OS / GUI / other
apps to become unresponsive.

Public surface:

* :func:`low_priority_popen_kwargs` — extra ``subprocess.Popen``
  kwargs that drop the child to below-normal priority on Windows
  (``BELOW_NORMAL_PRIORITY_CLASS``) and use ``os.nice(+5)`` on macOS
  / Linux. Apply ONLY to CPU jobs so the GPU job keeps normal
  priority (its bottleneck is the hardware encoder anyway).
* :func:`cpu_encoder_thread_count` — the ``-threads`` value to
  pass to ``libx264`` / ``libx265``. Caps at ``cpu_count - 2`` so
  the OS scheduler always has 2 cores worth of headroom for the
  UI thread and the OS.
* :func:`enough_ram_for_cpu_job` — psutil-backed watchdog. Returns
  ``False`` if free RAM is below ``MIN_FREE_RAM_FRACTION``. The
  caller (BatchManager) skips the CPU slot for one tick when this
  is False; the in-flight CPU job (if any) finishes normally.
* :func:`probe_system_load` — returns ``(cpu_percent, ram_percent)``
  for telemetry / future enhancements. Cached for ``LOAD_CACHE_S``
  to avoid hammering psutil.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import Optional

log = logging.getLogger("veloxa.resources")


# How much RAM must be free before the BatchManager will spawn a
# new CPU job. 10 % free on a 4 GB box is ~400 MB — tight but
# survivable. Below that we skip the CPU slot for one tick.
MIN_FREE_RAM_FRACTION = 0.10

# psutil cpu/mem snapshot is reused this many seconds before re-probing.
LOAD_CACHE_S = 2.0


# ---------------------------------------------------------------- priority

def low_priority_popen_kwargs() -> dict:
    """Return ``subprocess.Popen`` kwargs that lower the child's
    priority on Windows / Unix.

    On Windows, ``creationflags |= BELOW_NORMAL_PRIORITY_CLASS`` (which
    is ``0x4000``). On macOS / Linux, a ``preexec_fn`` calls
    ``os.nice(+5)`` after fork, before exec. Merge into your existing
    Popen kwargs (e.g. add the returned ``creationflags`` to whatever
    flags you were already passing).
    """
    if sys.platform == "win32":
        # BELOW_NORMAL_PRIORITY_CLASS is 0x00004000.
        return {"creationflags": getattr(
            subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)}
    # macOS / Linux: nice(+5) via preexec_fn. preexec_fn is documented
    # as unsafe in multi-threaded apps because the child inherits the
    # forked address space; in practice nice() is a single syscall and
    # is safe to call from preexec_fn even when the parent has many
    # threads. The alternative — setting priority post-spawn via
    # psutil — leaves a window where the child runs at normal priority.
    def _drop_prio():
        try:
            os.nice(5)
        except (OSError, AttributeError):
            pass
    return {"preexec_fn": _drop_prio}


# ---------------------------------------------------------------- thread cap

def cpu_encoder_thread_count(parallel_gpu_running: bool = True) -> int:
    """Return the ``-threads N`` value for ``libx264`` / ``libx265``
    when running as the parallel CPU job.

    Cap is ``cpu_count - 2`` to leave 2 cores worth of headroom for
    the GUI + OS. If a GPU job is also running in parallel, halve
    the cap so the GPU job still gets some CPU time for the FFmpeg
    filter / mux pipeline (which runs on CPU even when the encode
    is on GPU).

    Always returns >= 1.
    """
    try:
        n = os.cpu_count() or 4
    except Exception:
        n = 4
    cap = max(1, n - 2)
    if parallel_gpu_running:
        cap = max(1, cap // 2)
    return cap


# ---------------------------------------------------------------- RAM watchdog

_load_cache: dict = {"t": 0.0, "cpu": 0.0, "ram": 0.0}


def _probe_now() -> tuple:
    """Best-effort psutil snapshot. Returns (cpu_pct, ram_pct) or
    (0.0, 0.0) if psutil isn't available or errors out."""
    try:
        import psutil  # type: ignore
    except ImportError:
        return 0.0, 0.0
    try:
        cpu = float(psutil.cpu_percent(interval=None))
        ram = float(psutil.virtual_memory().percent)
        return cpu, ram
    except Exception as exc:
        log.info("psutil probe failed: %s", exc)
        return 0.0, 0.0


def probe_system_load() -> tuple:
    """Cached ``(cpu_percent, ram_percent)``. Refreshes every
    ``LOAD_CACHE_S`` seconds. Returns ``(0.0, 0.0)`` if psutil
    isn't installed (we fail-open rather than block encoding)."""
    now = time.monotonic()
    if now - _load_cache["t"] >= LOAD_CACHE_S:
        cpu, ram = _probe_now()
        _load_cache["t"] = now
        _load_cache["cpu"] = cpu
        _load_cache["ram"] = ram
    return _load_cache["cpu"], _load_cache["ram"]


def enough_ram_for_cpu_job() -> bool:
    """Watchdog: True iff free RAM is above ``MIN_FREE_RAM_FRACTION``.

    Used by the BatchManager dispatch loop: before opening the CPU
    slot, check this. If False, skip the CPU slot for the current
    tick (the BatchManager will re-check on the next dispatch).
    Fail-open if psutil isn't installed (we don't want missing
    optional dependencies to gate encoding).
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        return True
    try:
        vm = psutil.virtual_memory()
        free_fraction = (vm.total - vm.used) / max(1, vm.total)
        ok = free_fraction >= MIN_FREE_RAM_FRACTION
        if not ok:
            log.info("CPU job skipped: free RAM %.1f%% < %.1f%%",
                     free_fraction * 100, MIN_FREE_RAM_FRACTION * 100)
        return ok
    except Exception as exc:
        log.info("RAM watchdog failed open: %s", exc)
        return True


# ---------------------------------------------------------------- encoder check

CPU_ENCODER_NAMES = ("libx264", "libx265")


def force_cpu_encoder(opts: dict, codec_hint: str = "") -> dict:
    """Mutate-and-return a copy of ``opts`` with ``encoder`` forced to
    ``libx264`` or ``libx265`` (matching ``codec_hint`` / the existing
    encoder family). Used by the BatchManager when it's about to
    spawn a job into the CPU slot."""
    new = dict(opts)
    cur = (new.get("encoder") or "").lower()
    # Honour HEVC if the source profile asked for HEVC, otherwise
    # default to libx264.
    if "265" in cur or "hevc" in cur or "265" in (codec_hint or "").lower():
        new["encoder"] = "libx265"
    else:
        new["encoder"] = "libx264"
    # Flag for JobRunner — it uses this to decide priority + thread cap.
    new["_cpu_slot"] = True
    return new
