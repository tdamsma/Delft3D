"""Shared helpers for the D-Flow FM macOS benchmark harness.

Kept dependency-free (standard library only) so the harness runs with any
Python 3.9+, not just the `baseline_tools/dfm-validation` validation venv.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# .dia timer parsing
# ---------------------------------------------------------------------------
#
# Real dflowfm runs on this machine write their per-run diagnostics to
# <workingDir>/dflowfmoutput/<mduBaseName>.dia (the OutputDir=dflowfmoutput
# setting in every example .mdu) -- NOT to a top-level "unstruc.dia" in the
# working directory. A handful of leftover debug run directories under
# baseline_runs/ (bin-snapshot smoke tests, crash-debug, release-verify,
# verification-macos) each contain a 4-line stub "unstruc.dia" next to the
# real .dia -- that stub is written before the .mdu is parsed and is never
# flushed with real content; it is not the diagnostics file. Anything that
# consumes dflowfm diagnostics should look under dflowfmoutput/.
#
# The timing block at the end of a completed .dia looks like (real excerpt
# from baseline_runs/release-verify/lake_at_rest/dflowfmoutput/lake_at_rest.dia):
#
#   ** INFO   : extra timer:Sethuau                                              0.0284280777
#   ** INFO   : nr of timesteps        ( )  :           398.0000000000
#   ** INFO   : total computation time (s)  :             0.1634209156
#   ** INFO   : time modelinit         (s)  :             0.0181639194
#   ** INFO   : time steps (+ plots)   (s)  :             0.1452569962
#   ** INFO   : time solve             (s)  :             0.0146598816
#   ** INFO   : time totalsolve        (s)  :             0.0100000000
#   ** INFO   : time transport         (s)  :             0.0210000000
#   ** INFO   : Computation started  at: 07:56:00, 11-07-2026
#   ** INFO   : Computation finished at: 07:56:01, 11-07-2026
#   ** INFO   : MPI    : no.
#   ** INFO   : OpenMP : yes.         #threads max : 1
#
# Every numeric "label (unit) : value" and "extra timer:label   value" line is
# captured generically below; the labels double as JSON keys ("Compute
# advection term" -> "extra_timer_compute_advection_term").

_INFO_PREFIX = re.compile(r"^\*\*\s*INFO\s*:\s*(.*)$")
_NUMERIC_LINE = re.compile(
    r"^(?P<label>.+?)\s{2,}(?P<value>[-+]?\d+\.\d+(?:[eE][-+]?\d+)?)\s*$"
)
_EXTRA_TIMER = re.compile(r"^extra timer:\s*(?P<label>.+?)\s{2,}(?P<value>[-+]?\d+\.\d+(?:[eE][-+]?\d+)?)\s*$")
_THREADS_LINE = re.compile(r"^OpenMP\s*:\s*(yes|no)\.\s*(?:#threads max\s*:\s*(\d+))?", re.IGNORECASE)
_MPI_LINE = re.compile(r"^MPI\s*:\s*(yes|no)\.", re.IGNORECASE)


def _slugify(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"\(.*?\)", " ", label)  # drop unit annotations, e.g. "(s)"
    label = re.sub(r"[^a-z0-9]+", "_", label)
    return label.strip("_")


def parse_dia_timers(dia_path: Path) -> dict[str, Any]:
    """Parse the step-loop / timing block out of a completed dflowfm .dia file.

    Returns a flat dict of slugified-label -> float, plus a few named fields
    (mpi_enabled, openmp_threads, computation_started/finished) pulled out
    specially. Silently returns {} if the file is missing or has no timers
    (e.g. a crashed run) -- callers should treat that as "timers unavailable"
    rather than an error, since a benchmark run that produced a wall time but
    no complete .dia should still be recorded.
    """
    if not dia_path.is_file():
        return {}

    timers: dict[str, float] = {}
    mpi_enabled: bool | None = None
    openmp_threads: int | None = None
    started_at: str | None = None
    finished_at: str | None = None

    text = dia_path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        m = _INFO_PREFIX.match(raw_line)
        if not m:
            continue
        content = m.group(1).rstrip()
        if not content:
            continue

        if content.startswith("Computation started"):
            started_at = content.split("at:", 1)[-1].strip()
            continue
        if content.startswith("Computation finished"):
            finished_at = content.split("at:", 1)[-1].strip()
            continue

        mpi_m = _MPI_LINE.match(content)
        if mpi_m:
            mpi_enabled = mpi_m.group(1).lower() == "yes"
            continue

        threads_m = _THREADS_LINE.match(content)
        if threads_m:
            if threads_m.group(2):
                openmp_threads = int(threads_m.group(2))
            continue

        extra_m = _EXTRA_TIMER.match(content)
        if extra_m:
            key = "extra_timer_" + _slugify(extra_m.group("label"))
            timers[key] = float(extra_m.group("value"))
            continue

        num_m = _NUMERIC_LINE.match(content)
        if num_m:
            label = num_m.group("label")
            # Skip the periodic "Sim. time done / Sim. time left / ..." progress
            # table rows -- they look like "0d  0:02:00   0d  0:58:00   ...   0.00000"
            # and would otherwise slugify into one long garbage key. Normal timer
            # lines have exactly one ':' (the "label (unit)  :  value" separator);
            # clock-style "H:MM:SS" tokens contribute two colons each, so >=2 total
            # reliably identifies a progress row instead.
            if label.count(":") >= 2 or len(label) > 60:
                continue
            key = _slugify(label)
            if key:
                timers[key] = float(num_m.group("value"))
            continue

    result: dict[str, Any] = {"fields": timers}
    if mpi_enabled is not None:
        result["mpi_enabled"] = mpi_enabled
    if openmp_threads is not None:
        result["openmp_threads"] = openmp_threads
    if started_at:
        result["computation_started_at"] = started_at
    if finished_at:
        result["computation_finished_at"] = finished_at
    return result


# ---------------------------------------------------------------------------
# /usr/bin/time -l parsing (BSD time, macOS)
# ---------------------------------------------------------------------------

_TIME_L_RSS = re.compile(r"^\s*(\d+)\s+maximum resident set size\s*$", re.MULTILINE)
_TIME_L_REAL = re.compile(r"^\s*([\d.]+)\s+real\s+([\d.]+)\s+user\s+([\d.]+)\s+sys\s*$", re.MULTILINE)
_TIME_L_INVOL_SWITCH = re.compile(r"^\s*(\d+)\s+involuntary context switches\s*$", re.MULTILINE)


def parse_time_dash_l(output: str) -> dict[str, Any]:
    """Parse the footer that BSD `/usr/bin/time -l` appends to stderr.

    macOS's `time -l` reports "maximum resident set size" in bytes (unlike
    Linux's GNU `time -v`, which reports kilobytes) -- verified empirically on
    this machine (see tools/benchmarks/README.md).
    """
    result: dict[str, Any] = {}
    m = _TIME_L_RSS.search(output)
    if m:
        result["max_rss_bytes"] = int(m.group(1))
    m = _TIME_L_REAL.search(output)
    if m:
        result["real_s"] = float(m.group(1))
        result["user_s"] = float(m.group(2))
        result["sys_s"] = float(m.group(3))
    m = _TIME_L_INVOL_SWITCH.search(output)
    if m:
        result["involuntary_context_switches"] = int(m.group(1))
    return result


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        return (out.stdout or "").strip() or (out.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"<error running {' '.join(cmd)}: {exc}>"


def _sysctl(name: str) -> str | None:
    try:
        out = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=5, check=False
        )
        value = out.stdout.strip()
        return value if out.returncode == 0 and value else None
    except (OSError, subprocess.SubprocessError):
        return None


def capture_thermal_pressure() -> str:
    """`pmset -g therm` output. Returns a compact string; macOS reports plain
    text, not JSON, so this is stored verbatim rather than parsed."""
    return _run(["pmset", "-g", "therm"])


def git_info(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    def git(*args: str) -> str:
        return _run(["git", "-C", str(repo_root), *args])

    dirty = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(dirty),
        "dirty_files": dirty.splitlines() if dirty else [],
    }


def resolve_mpirun(tier: dict | None = None) -> str:
    """Resolve the mpirun executable to invoke.

    Resolution order: the D3D_BENCH_MPIRUN environment variable (a
    machine-local override, for when `mpirun` isn't on PATH or a specific
    build needs to be selected), then the tier's own "mpirun" key (normally
    just the bare command name "mpirun", left to the OS to resolve via
    PATH -- this is deliberately not an absolute path so the harness isn't
    tied to one developer's install location), then "mpirun" bare as a
    final fallback. subprocess.Popen/run already do the PATH lookup for a
    bare command name, so no explicit `shutil.which` check is needed here.
    """
    override = os.environ.get("D3D_BENCH_MPIRUN")
    if override:
        return override
    if tier is not None and tier.get("mpirun"):
        return tier["mpirun"]
    return "mpirun"


def compiler_versions() -> dict[str, str]:
    versions = {}
    for name, cmd in (
        ("gfortran", ["gfortran", "--version"]),
        ("clang", ["clang", "--version"]),
        ("mpirun", [resolve_mpirun(), "--version"]),
    ):
        out = _run(cmd)
        versions[name] = out.splitlines()[0] if out else "<unavailable>"
    return versions


def capture_environment() -> dict[str, Any]:
    return {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sw_vers": {
            "product_name": _run(["sw_vers", "-productName"]),
            "product_version": _run(["sw_vers", "-productVersion"]),
            "build_version": _run(["sw_vers", "-buildVersion"]),
        },
        "sysctl": {
            "hw.model": _sysctl("hw.model"),
            "hw.ncpu": _sysctl("hw.ncpu"),
            "hw.memsize": _sysctl("hw.memsize"),
            "hw.perflevel0.physicalcpu": _sysctl("hw.perflevel0.physicalcpu"),
            "hw.perflevel1.physicalcpu": _sysctl("hw.perflevel1.physicalcpu"),
        },
        "python": platform.python_version(),
        "compilers": compiler_versions(),
        "git": git_info(),
    }


# ---------------------------------------------------------------------------
# Process-tree RSS polling (supplementary to /usr/bin/time -l; see README
# "Open issues" -- BSD time -l's rusage accounting for a process tree spawned
# by mpirun is not verified to include grandchildren, so this polls `ps`
# directly for the whole descendant tree as a cross-check).
# ---------------------------------------------------------------------------


def _ps_snapshot() -> dict[int, tuple[int, int]]:
    """pid -> (ppid, rss_kb) for every process currently visible to `ps`."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=5, check=False
    )
    table: dict[int, tuple[int, int]] = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            pid, ppid, rss_kb = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        table[pid] = (ppid, rss_kb)
    return table


def poll_tree_peak_rss_bytes(root_pid: int, stop_event, interval_s: float = 0.1) -> int:
    """Poll `ps` every interval_s while stop_event is unset; return the peak
    summed RSS (bytes) across root_pid and all of its live descendants at any
    single sampling instant. Runs in a background thread; intended to be
    started just before launching the benchmarked subprocess and stopped
    just after it exits."""
    peak_kb = 0
    while not stop_event.is_set():
        table = _ps_snapshot()
        if root_pid in table:
            # BFS over descendants using the ppid snapshot.
            children_of: dict[int, list[int]] = {}
            for pid, (ppid, _rss) in table.items():
                children_of.setdefault(ppid, []).append(pid)
            stack = [root_pid]
            seen = set()
            total_kb = 0
            while stack:
                pid = stack.pop()
                if pid in seen:
                    continue
                seen.add(pid)
                if pid in table:
                    total_kb += table[pid][1]
                stack.extend(children_of.get(pid, []))
            peak_kb = max(peak_kb, total_kb)
        stop_event.wait(interval_s)
    return peak_kb * 1024


# ---------------------------------------------------------------------------
# MPI rank-count override (rank-count scaling sweep)
# ---------------------------------------------------------------------------
#
# tiers.json's M-mpi tier ships with a placeholder ranks=3; run_benchmark.py
# and run_once.py both need to apply the same override (run_benchmark.py to
# drive the untimed partition step + compute the run's `ranks` field,
# run_once.py because it independently reloads the tier by name inside the
# hyperfine-invoked worker subprocess and must build the same `mpirun -np N`
# command line). Kept here, not duplicated, so both call sites agree.
# Rewriting the staged dimr_config.xml's <process> rank-id list is a separate
# step (run_benchmark.rewrite_dimr_config) since that file lives in the run
# dir, not in tiers.json, and only needs to happen once per staged run dir.


def apply_ranks_override(tier: dict, ranks: int) -> dict:
    """Return a deep copy of tier with ndomains=N (partition step) and -np N
    (mpirun) rewritten to the given rank count."""
    tier = json.loads(json.dumps(tier))  # deep copy
    tier["ranks"] = ranks

    partition = tier.get("partition")
    if partition:
        partition["args"] = [
            re.sub(r"ndomains=\d+", f"ndomains={ranks}", a) for a in partition["args"]
        ]

    mpirun_args = tier.get("mpirun_args")
    if mpirun_args and "-np" in mpirun_args:
        idx = mpirun_args.index("-np")
        mpirun_args[idx + 1] = str(ranks)

    return tier


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
