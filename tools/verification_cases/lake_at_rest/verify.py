#!/usr/bin/env python3
"""Verify the lake-at-rest map output against the exact (trivial) solution.

Exact solution: for a closed, frictionless basin with any bed topography
z_b(x, y) and a uniform initial water level eta0 > max(z_b), the shallow
water equations are satisfied identically by

    eta(x, y, t) = eta0,   u(x, y, t) = v(x, y, t) = 0   for all t >= 0.

(Set u=v=0 in the momentum equations: the pressure-gradient term
-g*h*grad(eta) collapses to -g*h*grad(z_b) canceled by the bed-slope source
term g*h*grad(z_b) with the opposite sign convention used in the
non-conservative form, i.e. the two terms are identical in magnitude and
sign definition, so the residual is exactly zero; see e.g. Bermudez &
Vazquez-Cendon (1994) on the "C-property"/well-balancedness of numerical
schemes for this exact statement.) Any nonzero velocity or drifting water
level produced by the numerical scheme over the run is therefore a
numerical artifact, not physics -- this is the classic "well-balancedness"
regression test.
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
from generate import TSTOP, WATER_LEVEL  # noqa: E402

# Provisional tolerances (see README "Tolerance policy"): D-Flow FM's
# iterative solver (Icgsolver=4, sobekGS+Saad) and single/double-precision
# arithmetic do not reach literal machine epsilon; residual velocities of
# O(1e-9) - O(1e-7) m/s are typical "well-balanced" scheme results in the
# literature. We flag anything above 1e-6 m/s as a likely real bug.
VELOCITY_TOLERANCE_M_S = 1.0e-6
WATERLEVEL_TOLERANCE_M = 1.0e-8


def verify(map_path: Path) -> dict[str, Any]:
    ds = xu.open_dataset(map_path, decode_timedelta=False).obj

    waterlevel = np.asarray(ds["mesh2d_s1"].values)
    u = np.asarray(ds["mesh2d_ucx"].values)
    v = np.asarray(ds["mesh2d_ucy"].values)
    speed = np.hypot(u, v)

    max_speed = float(np.nanmax(np.abs(speed)))
    max_waterlevel_drift = float(np.nanmax(np.abs(waterlevel - WATER_LEVEL)))

    result = {
        "case": "lake_at_rest",
        "map_path": str(map_path),
        "n_times": int(ds["time"].size),
        "max_speed_m_s": max_speed,
        "max_waterlevel_drift_m": max_waterlevel_drift,
        "velocity_tolerance_m_s": VELOCITY_TOLERANCE_M_S,
        "waterlevel_tolerance_m": WATERLEVEL_TOLERANCE_M,
        "expected_waterlevel_m": WATER_LEVEL,
        "expected_tstop_s": TSTOP,
    }
    result["passed"] = bool(
        max_speed < VELOCITY_TOLERANCE_M_S
        and max_waterlevel_drift < WATERLEVEL_TOLERANCE_M
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
