#!/usr/bin/env python3
"""D-Flow FM macOS benchmark harness (Delft3D macOS port).

Runs one benchmark tier (see tiers.json: S, M-seq, M-mpi3, M-mpi, L, or L-mpi)
from a disposable copy of the pristine example sources, using hyperfine for
wall-time repeats + warm-up, `/usr/bin/time -l` for peak RSS, a supplementary
process-tree RSS poll for MPI honesty, and the dflowfm `.dia` diagnostics for
the internal step-loop timing breakdown. Writes one JSON result file.

Usage:

    python3 tools/benchmarks/run_benchmark.py --tier S
    python3 tools/benchmarks/run_benchmark.py --tier M-seq --repeats 5
    python3 tools/benchmarks/run_benchmark.py --tier M-mpi3 --repeats 5 \\
        --conditions baseline --json-out baseline_logs/benchmarks/M-mpi3.json

See README.md for the noise policy (relative sigma < 2% on the M tier) and
the profiling recipes this harness feeds into.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import bench_lib

REPO_ROOT = bench_lib.REPO_ROOT
HERE = Path(__file__).resolve().parent


def load_tiers() -> dict:
    return json.loads((HERE / "tiers.json").read_text())["tiers"]


def stage_run_dir(tier: dict, tier_name: str, base_output_dir: Path) -> Path:
    if not tier.get("source_dir"):
        raise SystemExit(
            f"tier {tier_name!r} has no source_dir configured yet (status={tier.get('status')!r}); "
            "see tiers.json for the placeholder note."
        )
    source_dir = REPO_ROOT / tier["source_dir"]
    if not source_dir.is_dir():
        raise SystemExit(f"tier {tier_name!r} source_dir does not exist: {source_dir}")

    stamp = time.strftime("%Y%m%dT%H%M%S")
    run_dir = base_output_dir / tier_name / f"run-{stamp}"
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, run_dir)
    return run_dir


def rewrite_dimr_config(tier: dict, run_dir: Path, ranks: int) -> None:
    """Rewrite the staged dimr_config.xml's <process>0 1 2</process> rank-id
    list to match an overridden rank count (see apply_ranks_override). The
    example ships this hardcoded for 3 ranks; a rank sweep needs 0..N-1."""
    # dimr_config.xml lives at the run_dir root (sibling of case_subdir), not
    # inside case_subdir -- matches tiers.json's M-mpi3/M-mpi layout.
    config_path = run_dir / tier["dimr_config"]
    text = config_path.read_text(encoding="utf-8")
    new_process = " ".join(str(i) for i in range(ranks))
    new_text, n = re.subn(r"<process>[^<]*</process>", f"<process>{new_process}</process>", text)
    if n != 1:
        raise SystemExit(
            f"expected exactly one <process> element in {config_path}, found {n}"
        )
    config_path.write_text(new_text, encoding="utf-8")


def run_partition_step(tier: dict, run_dir: Path) -> None:
    partition = tier["partition"]
    case_dir = run_dir / tier["case_subdir"]
    binary = str(REPO_ROOT / partition["binary"])
    args = [a.format(mdu=tier["mdu"]) for a in partition["args"]]
    log_path = run_dir / ".bench_meta" / "partition.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log_file:
        result = subprocess.run([binary, *args], cwd=case_dir, stdout=log_file, stderr=log_file)
    if result.returncode != 0:
        raise SystemExit(
            f"partition step failed (exit {result.returncode}); see {log_path} for details"
        )


def run_hyperfine(
    tier_name: str,
    run_dir: Path,
    repeats: int,
    warmup: int,
    hyperfine_bin: str,
    ranks: int | None = None,
) -> dict:
    tier = load_tiers()[tier_name]
    case_dir = run_dir / tier["case_subdir"]
    output_dir = case_dir / "dflowfmoutput"
    prepare_cmd = f"rm -rf {shlex.quote(str(output_dir))}"
    worker_cmd = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'run_once.py'))} "
        f"--tier {shlex.quote(tier_name)} --run-dir {shlex.quote(str(run_dir))}"
    )
    if ranks is not None:
        worker_cmd += f" --ranks {ranks}"
    export_json = run_dir / ".bench_meta" / "hyperfine.json"
    export_json.parent.mkdir(parents=True, exist_ok=True)

    argv = [
        hyperfine_bin,
        "--warmup",
        str(warmup),
        "--runs",
        str(repeats),
        "--prepare",
        prepare_cmd,
        "--export-json",
        str(export_json),
        worker_cmd,
    ]
    result = subprocess.run(argv, cwd=run_dir, capture_output=True, text=True)
    hyperfine_log = run_dir / ".bench_meta" / "hyperfine.stdout.log"
    hyperfine_log.parent.mkdir(parents=True, exist_ok=True)
    hyperfine_log.write_text(result.stdout + "\n---stderr---\n" + result.stderr)
    if result.returncode != 0 or not export_json.is_file():
        raise SystemExit(
            f"hyperfine failed (exit {result.returncode}); see {hyperfine_log} "
            f"and per-repeat logs under {run_dir / '.bench_meta'}"
        )
    return json.loads(export_json.read_text())


def collect_repeat_metadata(run_dir: Path) -> list[dict]:
    meta_dir = run_dir / ".bench_meta"
    repeats = []
    for path in sorted(meta_dir.glob("repeat-*.json")):
        repeats.append(json.loads(path.read_text()))
    return repeats


def aggregate_rss(repeats: list[dict]) -> dict:
    time_l_bytes = [
        r["time_dash_l"]["max_rss_bytes"]
        for r in repeats
        if "max_rss_bytes" in r.get("time_dash_l", {})
    ]
    tree_bytes = [r["tree_peak_rss_bytes"] for r in repeats if r.get("tree_peak_rss_bytes")]
    result = {}
    if time_l_bytes:
        result["time_dash_l"] = {
            "max_bytes": max(time_l_bytes),
            "mean_bytes": statistics.mean(time_l_bytes),
            "per_repeat_bytes": time_l_bytes,
        }
    if tree_bytes:
        result["process_tree"] = {
            "max_bytes": max(tree_bytes),
            "mean_bytes": statistics.mean(tree_bytes),
            "per_repeat_bytes": tree_bytes,
            "_note": (
                "Supplementary cross-check: sums RSS across the whole process tree "
                "(root + descendants) sampled every 100ms via `ps`. For sequential "
                "runs this should closely track time_dash_l; for MPI (mpirun + N "
                "dimr processes) it is expected to exceed time_dash_l's single-process "
                "reading substantially and is the more trustworthy number -- see "
                "README 'Open issues'."
            ),
        }
    return result


def any_failed_repeat(repeats: list[dict]) -> bool:
    return any(r.get("exit_code", 0) != 0 for r in repeats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", required=True, help="any tier key defined in tiers.json (e.g. S, M-seq, M-mpi3, L-mpi-long)")
    parser.add_argument(
        "--ranks",
        type=int,
        default=None,
        help=(
            "override the tier's MPI rank count (mode=mpi/mpi_direct tiers only, e.g. M-mpi, L-mpi). "
            "Rewrites ndomains=N in the partition step, -np N for mpirun, and the "
            "staged dimr_config.xml's <process> rank-id list. Used for rank-count scaling sweeps."
        ),
    )
    parser.add_argument("--repeats", type=int, default=5, help="timed repeats (default: 5)")
    parser.add_argument("--warmup", type=int, default=1, help="warm-up runs before timing (default: 1)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "baseline_runs" / "benchmarks",
        help="base directory for disposable run dirs (default: baseline_runs/benchmarks)",
    )
    parser.add_argument("--json-out", type=Path, help="write the result JSON here as well as stdout")
    parser.add_argument(
        "--conditions",
        default="baseline",
        help=(
            "free-text label stored in the result JSON's conditions field, e.g. "
            "'baseline' for a real measurement session or "
            "'validation-plumbing-check' when just proving the harness works "
            "under load from other concurrent work -- NOT a publishable number."
        ),
    )
    parser.add_argument("--hyperfine-bin", default="hyperfine")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove the disposable run dir after writing the result JSON",
    )
    args = parser.parse_args()

    tiers = load_tiers()
    if args.tier not in tiers:
        raise SystemExit(f"unknown tier {args.tier!r}; known: {sorted(tiers)}")
    tier = tiers[args.tier]

    if args.ranks is not None:
        if tier["mode"] not in ("mpi", "mpi_direct"):
            raise SystemExit(f"--ranks only applies to mode=mpi/mpi_direct tiers, {args.tier!r} is {tier['mode']!r}")
        tier = bench_lib.apply_ranks_override(tier, args.ranks)

    thermal_before = bench_lib.capture_thermal_pressure()
    environment_before = bench_lib.capture_environment()

    run_dir = stage_run_dir(tier, args.tier, args.output_dir)
    print(f"[run_benchmark] staged {args.tier} at {run_dir}", file=sys.stderr)

    if tier["mode"] in ("mpi", "mpi_direct"):
        if args.ranks is not None and tier.get("dimr_config"):
            rewrite_dimr_config(tier, run_dir, args.ranks)
        print("[run_benchmark] running untimed partition step...", file=sys.stderr)
        run_partition_step(tier, run_dir)

    print(
        f"[run_benchmark] hyperfine: warmup={args.warmup} runs={args.repeats}",
        file=sys.stderr,
    )
    hyperfine_result = run_hyperfine(
        args.tier, run_dir, args.repeats, args.warmup, args.hyperfine_bin, ranks=args.ranks
    )
    hf = hyperfine_result["results"][0]

    thermal_after = bench_lib.capture_thermal_pressure()
    environment_after = bench_lib.capture_environment()

    repeats = collect_repeat_metadata(run_dir)
    failed = any_failed_repeat(repeats)

    case_dir = run_dir / tier["case_subdir"]
    dia_path = case_dir / tier["dia_path_template"]
    if not dia_path.is_file() and tier["mode"] in ("mpi", "mpi_direct") and "_0000" in tier["dia_path_template"]:
        # At --ranks 1 dflowfm runs the *unpartitioned* model (dimr launches a
        # single process against the plain .mdu, or for mpi_direct there is no
        # partition step at all), so the diagnostics keep the unpartitioned
        # name (westerscheldt.dia, not westerscheldt_0000.dia; l_tier.dia, not
        # l_tier_0000.dia). Observed empirically in the rank sweep,
        # 2026-07-11. L-mpi's scan never uses --ranks 1 in practice (the L
        # tier's existing sequential numbers are reused as the rank=1
        # reference instead), but the fallback is kept for robustness.
        dia_path = case_dir / tier["dia_path_template"].replace("_0000", "")
    dia_timers = bench_lib.parse_dia_timers(dia_path)

    mean_s = hf["mean"]
    stddev_s = hf.get("stddev", 0.0) or 0.0
    relative_stddev = (stddev_s / mean_s) if mean_s else None
    noise_threshold = 0.02

    result = {
        "schema_version": bench_lib.SCHEMA_VERSION,
        "tier": args.tier,
        "description": tier.get("description"),
        "mode": tier["mode"],
        "ranks": tier.get("ranks", 1),
        "conditions": {
            "label": args.conditions,
            # "baseline" = normal measurement run; "exclusive-baseline" =
            # the convention for real baselines taken with the machine
            # guaranteed otherwise idle (no other concurrent workloads).
            "publishable": args.conditions in ("baseline", "exclusive-baseline"),
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_dir": str(run_dir),
        "any_repeat_failed": failed,
        "repeats": {
            "requested": args.repeats,
            "warmup": args.warmup,
            "recorded": len(repeats),
        },
        "timing_s": {
            "mean": mean_s,
            "stddev": stddev_s,
            "min": hf.get("min"),
            "max": hf.get("max"),
            "median": hf.get("median"),
            "user": hf.get("user"),
            "system": hf.get("system"),
            "times": hf.get("times"),
            "relative_stddev": relative_stddev,
            "noise_policy": {
                "threshold": noise_threshold,
                "applies_to_tier": "M-seq/M-mpi3",
                "pass": (relative_stddev is not None and relative_stddev < noise_threshold),
            },
        },
        "rss": aggregate_rss(repeats),
        "dia_timers": dia_timers,
        "dia_path": str(dia_path),
        "thermal_pressure": {"before": thermal_before, "after": thermal_after},
        "environment": {"before": environment_before, "after": environment_after},
        "hyperfine_raw": hf,
    }

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered)

    if args.cleanup:
        shutil.rmtree(run_dir, ignore_errors=True)

    if failed:
        print("[run_benchmark] WARNING: at least one repeat exited non-zero", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
