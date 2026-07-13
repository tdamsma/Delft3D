#!/usr/bin/env python3
"""Seq-vs-MPI decomposition-drift check for a partitioned dflowfm map file.

Added alongside the L-mpi tier: the L tier has no observation stations
wired into its `.mdu` (unlike example 02's Western Scheldt model), so the
M-tier convention of diffing
the merged `_his.nc` file (see field_diff.py's Control 2 methodology) isn't
available here -- there is nothing non-trivial to compare in `l_tier_his.nc`.
This script does the equivalent check at the map-field level instead:
merges N per-rank `<stem>_NNNN_map.nc` files (owned cells only, filtered by
`mesh2d_flowelem_domain == <that rank's id>`) and diffs the merged field
against a sequential run's `<stem>_map.nc`.

Correspondence is established by (x, y) cell-center coordinates
(`mesh2d_face_x`/`mesh2d_face_y`), NOT by array position or
`mesh2d_flowelem_globalnr` -- verified empirically (2026-07-11) that
dflowfm applies its own internal flow-node renumbering independently in a
sequential run vs. a partitioned run (bandwidth optimization), so those
two orderings do not correspond 1:1 even though both ultimately describe
the same physical mesh. A first attempt at a globalnr-keyed diff produced
spurious near-full-range "differences" that were actually a shuffled
correspondence, not real divergence -- coordinate matching resolved it
(same run pair then diffed to ~1e-12 absolute, matching the M-tier
decomposition-drift control's ~1e-11 scale).

Usage:

    python3 tools/benchmarks/l_tier/compare_seq_vs_mpi_map.py \\
        <sequential_map.nc> <rank0_map.nc> [<rank1_map.nc> ...] \\
        [--variables mesh2d_s1 mesh2d_waterdepth mesh2d_ucx mesh2d_ucy] \\
        [--abs-tol 1e-6] [--json-out out.json]

Exits 0 if every compared variable's max-abs diff (over cells present in
both, excluding NaNs) is within --abs-tol; exits 1 otherwise (with the
failing variable(s) printed) so this can gate a CI-style check if wanted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

DEFAULT_VARIABLES = ["mesh2d_s1", "mesh2d_waterdepth", "mesh2d_ucx", "mesh2d_ucy"]


def _coord_key(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    # Combine rounded (x, y) into one sortable/searchable key. 1e9-ish
    # multiplier keeps x and y from colliding for any realistic model
    # extent (works fine at L-tier's 28.8 km x 2 km domain); round to 1e-6 m
    # to absorb any float32/float64 NetCDF round-trip noise in coordinates
    # themselves (the physical fields are compared at full precision).
    return np.round(x, 6) * 1_000_000_003.0 + np.round(y, 6)


def merge_partitions(rank_paths: list[str], variables: list[str], n_global: int, seq_key_sorted: np.ndarray, order: np.ndarray):
    merged = {v: np.full(n_global, np.nan) for v in variables}
    covered = np.zeros(n_global, dtype=bool)

    for rp in rank_paths:
        ds = xr.open_dataset(rp)
        domain = ds["mesh2d_flowelem_domain"].values.astype(np.int64)
        rank_id = np.bincount(domain).argmax()
        owned = domain == rank_id
        rkey = _coord_key(ds["mesh2d_face_x"].values[owned], ds["mesh2d_face_y"].values[owned])
        pos = np.clip(np.searchsorted(seq_key_sorted, rkey), 0, len(order) - 1)
        gidx = order[pos]
        matched = seq_key_sorted[pos] == rkey
        if not matched.all():
            print(
                f"WARNING: {(~matched).sum()} owned cells in {rp} had no exact coordinate match",
                file=sys.stderr,
            )
        for v in variables:
            arr_last = ds[v].isel(time=-1).values[owned]
            merged[v][gidx[matched]] = arr_last[matched]
        covered[gidx[matched]] = True
        ds.close()

    return merged, covered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sequential_map", help="path to the sequential run's <stem>_map.nc")
    parser.add_argument("rank_maps", nargs="+", help="paths to each rank's <stem>_NNNN_map.nc")
    parser.add_argument("--variables", nargs="+", default=DEFAULT_VARIABLES)
    parser.add_argument("--abs-tol", type=float, default=1e-6, help="pass threshold on max-abs diff (default 1e-6)")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    seq = xr.open_dataset(args.sequential_map)
    n_global = seq.sizes["mesh2d_nFaces"]
    seq_key = _coord_key(seq["mesh2d_face_x"].values, seq["mesh2d_face_y"].values)
    order = np.argsort(seq_key)
    seq_key_sorted = seq_key[order]

    merged, covered = merge_partitions(args.rank_maps, args.variables, n_global, seq_key_sorted, order)

    print(f"global cells: {n_global}, covered by merge: {covered.sum()} ({covered.sum() / n_global:.4%})")
    if not covered.all():
        print(f"WARNING: {n_global - covered.sum()} global cells not covered by any rank's owned set")

    results: dict[str, dict] = {}
    overall_pass = True
    for v in args.variables:
        seq_last = seq[v].isel(time=-1).values
        mpi_last = merged[v]
        mask = covered & ~np.isnan(seq_last) & ~np.isnan(mpi_last)
        diff = np.abs(seq_last[mask] - mpi_last[mask])
        denom = np.maximum(np.abs(seq_last[mask]), 1e-12)
        rel = diff / denom
        max_abs = float(diff.max())
        entry = {
            "n_compared": int(mask.sum()),
            "max_abs": max_abs,
            "rms_abs": float(np.sqrt((diff**2).mean())),
            "max_rel": float(rel.max()),
            "seq_range": [float(seq_last[mask].min()), float(seq_last[mask].max())],
            "mpi_range": [float(mpi_last[mask].min()), float(mpi_last[mask].max())],
            "pass": max_abs <= args.abs_tol,
        }
        results[v] = entry
        print(
            f"{v}: n={entry['n_compared']} max_abs={max_abs:.6e} rms_abs={entry['rms_abs']:.6e} "
            f"max_rel={entry['max_rel']:.6e} seq_range={entry['seq_range']} mpi_range={entry['mpi_range']}"
        )
        overall_pass = overall_pass and entry["pass"]

    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'} (abs_tol={args.abs_tol:.1e})")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "sequential_map": str(args.sequential_map),
                    "rank_maps": [str(p) for p in args.rank_maps],
                    "n_global": int(n_global),
                    "covered": int(covered.sum()),
                    "abs_tol": args.abs_tol,
                    "overall_pass": overall_pass,
                    "variables": results,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
