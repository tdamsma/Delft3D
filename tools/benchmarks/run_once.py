#!/usr/bin/env python3
"""Single-invocation worker for the D-Flow FM benchmark harness.

This is the command hyperfine repeats (warm-up + N timed runs). Each
invocation:

1. builds the tier's dflowfm/dimr+mpirun command line from tiers.json,
2. runs it wrapped in `/usr/bin/time -l` (peak RSS, macOS BSD `time`),
3. concurrently polls the whole process tree via `ps` for a supplementary
   peak-RSS cross-check (see README "Open issues" -- BSD time -l's rusage
   accounting for a tree of processes spawned by mpirun is not verified to
   include grandchildren the way GNU time on Linux does),
4. writes a small per-repeat metadata JSON file under
   <run_dir>/.bench_meta/repeat-<n>.json,
5. exits with the wrapped command's exit code so hyperfine can detect
   failures.

Not meant to be run standalone for anything but debugging a single repeat;
`run_benchmark.py` is the orchestrator that drives hyperfine and aggregates
results across repeats.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import bench_lib

REPO_ROOT = bench_lib.REPO_ROOT


def load_tier(tier_name: str, ranks: int | None = None) -> dict:
    tiers = json.loads((Path(__file__).parent / "tiers.json").read_text())["tiers"]
    if tier_name not in tiers:
        raise SystemExit(f"unknown tier {tier_name!r}; known: {sorted(tiers)}")
    tier = tiers[tier_name]
    if ranks is not None:
        tier = bench_lib.apply_ranks_override(tier, ranks)
    return tier


def next_repeat_index(run_dir: Path) -> int:
    meta_dir = run_dir / ".bench_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    counter_file = meta_dir / "repeat_index"
    current = 0
    if counter_file.is_file():
        try:
            current = int(counter_file.read_text().strip())
        except ValueError:
            current = 0
    current += 1
    counter_file.write_text(str(current))
    return current


def build_command(tier: dict, run_dir: Path) -> tuple[list[str], Path, dict]:
    """Returns (argv, cwd, extra_env) for the tier's benchmarked invocation."""
    case_dir = run_dir / tier["case_subdir"]
    env = os.environ.copy()

    if tier["mode"] == "sequential":
        binary = str(REPO_ROOT / tier["binary"])
        args = [a.format(mdu=tier["mdu"]) for a in tier["args"]]
        return [binary, *args], case_dir, env

    if tier["mode"] == "mpi":
        # OMP_NUM_THREADS defaults to 1 here too (mirroring the mpi_direct
        # fix below): this path goes through dimr, which dlopen()s
        # libdflowfm.dylib into its own
        # process -- each of the N dimr ranks still hosts dflowfm's OpenMP
        # runtime, so leaving OMP_NUM_THREADS unset lets each rank spawn
        # omp_get_num_procs() (32 on this machine) compute threads on top of
        # the N MPI processes, exactly the oversubscription bug found on the
        # L tier. Honor an operator-supplied OMP_NUM_THREADS via setdefault
        # rather than overwriting it.
        env.setdefault("OMP_NUM_THREADS", "1")
        mpirun = bench_lib.resolve_mpirun(tier)
        dimr = str(REPO_ROOT / tier["dimr_binary"])
        dflowfm_lib_dir = str(REPO_ROOT / tier["dflowfm_lib_dir"])
        env["DYLD_LIBRARY_PATH"] = dflowfm_lib_dir + os.pathsep + env.get("DYLD_LIBRARY_PATH", "")
        argv = [mpirun, *tier["mpirun_args"], dimr, tier["dimr_config"]]
        return argv, run_dir, env

    if tier["mode"] == "mpi_direct":
        # Direct dflowfm-under-MPI path, no dimr (see tiers.json L-mpi
        # _comment). dflowfm auto-loads the partitioned l_tier_NNNN.mdu
        # files itself from the plain mdu name on argv; no
        # DYLD_LIBRARY_PATH needed since the standalone binary's @rpath
        # entries are baked in absolute (same as the sequential tiers).
        #
        # OMP_NUM_THREADS defaults to 1 here: left unset, each rank's own
        # OpenMP runtime defaults to omp_get_num_procs() (32 on this
        # machine) -- so an N-rank run silently becomes N*32 compute
        # threads fighting over 32 cores on top of the N MPI processes
        # themselves. This was the actual cause of an 8-24-rank
        # "spin-wait valley" measured during tuning, not an inherent Open
        # MPI/macOS scheduling wall: fixing just this one
        # env var turned the 24-rank L-tier point from 68.8s (worse than
        # sequential) into ~3.6s step-loop time, making 24 ranks the fastest
        # point in the whole scan (beating 32). Honor an operator-supplied
        # OMP_NUM_THREADS (e.g. for a deliberate hybrid MPI+OMP scan) via
        # setdefault rather than overwriting it.
        env.setdefault("OMP_NUM_THREADS", "1")
        mpirun = bench_lib.resolve_mpirun(tier)
        binary = str(REPO_ROOT / tier["binary"])
        args = [a.format(mdu=tier["mdu"]) for a in tier["args"]]
        argv = [mpirun, *tier["mpirun_args"], binary, *args]
        return argv, case_dir, env

    raise SystemExit(f"unknown tier mode {tier['mode']!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--ranks", type=int, default=None, help="MPI rank-count override (see bench_lib.apply_ranks_override)"
    )
    args = parser.parse_args()

    tier = load_tier(args.tier, ranks=args.ranks)
    run_dir = args.run_dir.resolve()
    argv, cwd, env = build_command(tier, run_dir)

    idx = next_repeat_index(run_dir)
    meta_dir = run_dir / ".bench_meta"
    log_path = meta_dir / f"repeat-{idx:03d}.log"

    # /usr/bin/time is an Apple SIP-restricted system binary: dyld strips all
    # DYLD_* environment variables before executing anything through it --
    # confirmed empirically (2026-07-11): `DYLD_LIBRARY_PATH=... /usr/bin/time
    # -l python3 -c "print(os.environ.get('DYLD_LIBRARY_PATH'))"` prints None,
    # while the same check without the `time` wrapper (or with a non-SIP
    # binary such as Homebrew's own python3) sees the variable correctly. The
    # M-mpi3 tier needs DYLD_LIBRARY_PATH forwarded through to dimr (see
    # tiers.json _dyld_comment), so it cannot be wrapped in `time -l` -- doing
    # so would silently break the DYLD_LIBRARY_PATH propagation and dimr would
    # abort with "Cannot load component library libdflowfm.dylib". For MPI
    # runs, peak RSS therefore comes only from the process-tree `ps` poll
    # below, not from `time -l`; see README "Open issues".
    use_time_dash_l = tier["mode"] != "mpi"
    wrapped = ["/usr/bin/time", "-l", *argv] if use_time_dash_l else list(argv)

    stop_poll = threading.Event()
    tree_peak_kb_holder: dict[str, int] = {"peak_bytes": 0}

    start = time.monotonic()
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(wrapped, cwd=cwd, env=env, stdout=log_file, stderr=log_file)

        def poll() -> None:
            tree_peak_kb_holder["peak_bytes"] = bench_lib.poll_tree_peak_rss_bytes(
                proc.pid, stop_poll, interval_s=0.1
            )

        poll_thread = threading.Thread(target=poll, daemon=True)
        poll_thread.start()
        returncode = proc.wait()
        stop_poll.set()
        poll_thread.join(timeout=2.0)
    wall_s = time.monotonic() - start

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    time_stats = bench_lib.parse_time_dash_l(log_text)

    metadata = {
        "repeat_index": idx,
        "command": wrapped,
        "cwd": str(cwd),
        "exit_code": returncode,
        "wall_s_internal": wall_s,
        "time_dash_l_used": use_time_dash_l,
        "time_dash_l": time_stats,
        "tree_peak_rss_bytes": tree_peak_kb_holder["peak_bytes"],
        "log_path": str(log_path),
    }
    (meta_dir / f"repeat-{idx:03d}.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))

    return returncode


if __name__ == "__main__":
    sys.exit(main())
