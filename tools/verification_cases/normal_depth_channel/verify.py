#!/usr/bin/env python3
"""Verify the normal-depth channel map output against the Manning equilibrium.

Exact solution: for steady, uniform flow in a prismatic rectangular channel
of width b, bed slope S0 and Manning roughness n, momentum balance reduces
to a balance between the bed-slope source term and the friction slope, i.e.
Manning's equation

    Q = (1/n) * A * R^(2/3) * sqrt(S0),   A = b*h0,   R = A / (b + 2*h0)

which has a unique positive root h0 (the normal depth); see e.g. Chow (1959),
"Open-Channel Hydraulics", Ch. 7. The equilibrium velocity is U0 = Q / (b*h0).

The simulation starts from a different depth profile (uniform absolute water
level h0/2, so shallower than equilibrium everywhere but especially near the
outlet) and is forced with the equilibrium discharge/level at both ends,
so reaching h0/U0 in the channel interior demonstrates convergence to the
equilibrium, not just its preservation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xugrid as xu

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import (  # noqa: E402
    BED_SLOPE,
    DISCHARGE,
    LENGTH,
    MANNING_N,
    WIDTH,
    solve_normal_depth,
)

# Provisional tolerances (see README "Tolerance policy"). Away from the
# boundaries, a well-resolved 1D-equivalent friction-dominated steady state
# is expected to match the algebraic Manning solution to within a fraction
# of a percent; discretization error from Conveyance2D/limiter choices and
# the coarse (dx=5 m) mesh motivate a relative tolerance rather than an
# absolute one.
RELATIVE_TOLERANCE = 0.02
# Window (fraction of channel length, centered) used to average out
# cell-to-cell noise while staying clear of both open boundaries.
INTERIOR_FRACTION = 0.4


def verify(map_path: Path) -> dict[str, Any]:
    h0 = solve_normal_depth(DISCHARGE, WIDTH, MANNING_N, BED_SLOPE)
    u0 = DISCHARGE / (WIDTH * h0)

    ugrid_ds = xu.open_dataset(map_path, decode_timedelta=False)
    grid = ugrid_ds.ugrid.grids[0]
    face_x = grid.face_coordinates[:, 0]
    ds = ugrid_ds.obj

    lo, hi = 0.5 * LENGTH - INTERIOR_FRACTION * LENGTH / 2, 0.5 * LENGTH + INTERIOR_FRACTION * LENGTH / 2
    interior = (face_x >= lo) & (face_x <= hi)

    depth_final = np.asarray(ds["mesh2d_waterdepth"].isel(time=-1).values)[interior]
    ucx_final = np.asarray(ds["mesh2d_ucx"].isel(time=-1).values)[interior]

    mean_depth = float(np.nanmean(depth_final))
    mean_velocity = float(np.nanmean(ucx_final))

    depth_error = abs(mean_depth - h0) / h0
    velocity_error = abs(mean_velocity - u0) / u0

    result = {
        "case": "normal_depth_channel",
        "map_path": str(map_path),
        "h0_exact_m": float(h0),
        "u0_exact_m_s": float(u0),
        "mean_depth_interior_m": mean_depth,
        "mean_velocity_interior_m_s": mean_velocity,
        "depth_relative_error": depth_error,
        "velocity_relative_error": velocity_error,
        "relative_tolerance": RELATIVE_TOLERANCE,
        "interior_window_m": [lo, hi],
    }
    result["passed"] = bool(
        depth_error < RELATIVE_TOLERANCE and velocity_error < RELATIVE_TOLERANCE
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify(args.map_file)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
