#!/usr/bin/env python3
"""Diff two run_benchmark.py JSON result sets and flag regressions beyond noise.

A "regression" on a metric is flagged when the relative change between the
two runs exceeds both:

  - a fixed noise floor (--min-threshold, default 2%, matching the harness's
    own noise policy: "a benchmark is usable when relative sigma < ~2% on
    the M tier"), and
  - `--z` (default 2.0) times the two runs' *measured* combined relative
    standard deviation, when available (wall time and RSS have per-repeat
    samples to compute sigma from; .dia timer fields do not -- they come
    from a single final-repeat sample, so they fall back to the fixed
    floor alone and are marked accordingly).

Usage:

    python3 tools/benchmarks/compare_benchmarks.py baseline.json candidate.json
    python3 tools/benchmarks/compare_benchmarks.py baseline.json candidate.json --json-out diff.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def relative_stddev(values: list[float] | None) -> float | None:
    if not values or len(values) < 2:
        return None
    mean = statistics.mean(values)
    if not mean:
        return None
    return statistics.stdev(values) / mean


def compare_metric(
    name: str,
    a_mean: float | None,
    b_mean: float | None,
    a_sigma_rel: float | None,
    b_sigma_rel: float | None,
    min_threshold: float,
    z: float,
    higher_is_worse: bool = True,
) -> dict[str, Any] | None:
    if a_mean is None or b_mean is None or a_mean == 0:
        return None
    pct_change = (b_mean - a_mean) / a_mean

    combined_sigma = None
    if a_sigma_rel is not None and b_sigma_rel is not None:
        combined_sigma = math.sqrt(a_sigma_rel**2 + b_sigma_rel**2)

    noise_aware = combined_sigma is not None
    threshold = max(min_threshold, z * combined_sigma) if noise_aware else min_threshold

    worse_direction = pct_change > 0 if higher_is_worse else pct_change < 0
    flagged = worse_direction and abs(pct_change) > threshold

    return {
        "metric": name,
        "baseline": a_mean,
        "candidate": b_mean,
        "pct_change": pct_change,
        "threshold_used": threshold,
        "noise_aware": noise_aware,
        "baseline_relative_sigma": a_sigma_rel,
        "candidate_relative_sigma": b_sigma_rel,
        "flagged_regression": flagged,
    }


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def compare(baseline: dict, candidate: dict, min_threshold: float, z: float) -> dict:
    if baseline.get("tier") != candidate.get("tier"):
        print(
            f"warning: comparing different tiers ({baseline.get('tier')!r} vs "
            f"{candidate.get('tier')!r}) -- results are not meaningful",
            file=sys.stderr,
        )

    checks: list[dict[str, Any]] = []

    a_t = baseline.get("timing_s", {})
    b_t = candidate.get("timing_s", {})
    checks.append(
        compare_metric(
            "wall_time_mean_s",
            a_t.get("mean"),
            b_t.get("mean"),
            a_t.get("relative_stddev"),
            b_t.get("relative_stddev"),
            min_threshold,
            z,
        )
    )

    a_rss = baseline.get("rss", {})
    b_rss = candidate.get("rss", {})
    for rss_kind in ("time_dash_l", "process_tree"):
        a_kind = a_rss.get(rss_kind, {})
        b_kind = b_rss.get(rss_kind, {})
        checks.append(
            compare_metric(
                f"peak_rss_{rss_kind}_bytes",
                a_kind.get("mean_bytes"),
                b_kind.get("mean_bytes"),
                relative_stddev(a_kind.get("per_repeat_bytes")),
                relative_stddev(b_kind.get("per_repeat_bytes")),
                min_threshold,
                z,
            )
        )

    a_dia = baseline.get("dia_timers", {}).get("fields", {})
    b_dia = candidate.get("dia_timers", {}).get("fields", {})
    for key in sorted(set(a_dia) & set(b_dia)):
        checks.append(
            compare_metric(
                f"dia.{key}",
                a_dia[key],
                b_dia[key],
                None,
                None,
                min_threshold,
                z,
            )
        )

    checks = [c for c in checks if c is not None]
    regressions = [c for c in checks if c["flagged_regression"]]

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_run_dir": baseline.get("run_dir"),
        "candidate_run_dir": candidate.get("run_dir"),
        "tier": candidate.get("tier"),
        "min_threshold": min_threshold,
        "z": z,
        "checks": checks,
        "regressions": regressions,
        "any_regression": bool(regressions),
    }


def print_table(report: dict) -> None:
    print(f"tier: {report['tier']}")
    print(f"baseline: {report['baseline_run_dir']}")
    print(f"candidate: {report['candidate_run_dir']}")
    print()
    header = f"{'metric':<32} {'baseline':>16} {'candidate':>16} {'% change':>10} {'threshold':>10}  flag"
    print(header)
    print("-" * len(header))
    for c in report["checks"]:
        flag = "REGRESSION" if c["flagged_regression"] else ""
        print(
            f"{c['metric']:<32} {c['baseline']:>16.6g} {c['candidate']:>16.6g} "
            f"{c['pct_change'] * 100:>9.2f}% {c['threshold_used'] * 100:>9.2f}%  {flag}"
        )
    print()
    if report["any_regression"]:
        print(f"RESULT: {len(report['regressions'])} regression(s) flagged")
    else:
        print("RESULT: no regressions flagged")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--min-threshold",
        type=float,
        default=0.02,
        help="fixed noise floor, fraction (default: 0.02 == 2%%, matches the harness noise policy)",
    )
    parser.add_argument(
        "--z",
        type=float,
        default=2.0,
        help="multiplier on the combined measured relative sigma (default: 2.0)",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    baseline = load(args.baseline)
    candidate = load(args.candidate)
    report = compare(baseline, candidate, args.min_threshold, args.z)

    print_table(report)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    return 1 if report["any_regression"] else 0


if __name__ == "__main__":
    sys.exit(main())
