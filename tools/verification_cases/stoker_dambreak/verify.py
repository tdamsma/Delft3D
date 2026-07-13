#!/usr/bin/env python3
"""Verify the Stoker dam-break map output against the exact Riemann solution.

Two independent checks against :func:`generate.stoker_solution` at several
snapshot times:

1. **Shock front position**: located in the simulated field as the
   steepest-gradient point in depth between the intermediate state h_m and
   the downstream depth h_right, compared against the analytic
   ``x0 + shock_speed * t``. Tolerated in units of dx (finite-volume shock
   capturing smears a discontinuity over a few cells; the *position* of the
   smeared front, not its shape, is the physically meaningful quantity).
2. **Pointwise depth/velocity RMS error** in the reservoir, rarefaction fan
   and constant intermediate-state zones (i.e. everywhere except a
   near-shock exclusion band, where a first-order-accurate finite-volume
   scheme's smeared shock cannot match the exact step pointwise).
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
from generate import DX, H_LEFT, H_RIGHT, X0, intermediate_state, stoker_solution  # noqa: E402

# Provisional tolerances (see README "Tolerance policy").
SHOCK_POSITION_TOLERANCE_DX = 4.0  # front location within 4 cells
FIELD_RMS_TOLERANCE_M = 0.02 * H_LEFT  # 2% of the reservoir depth
VELOCITY_RMS_TOLERANCE_M_S = 0.1  # m/s
SHOCK_EXCLUSION_DX = 3.0  # cells straddling the analytic shock excluded from RMS
ANALYSIS_FRACTIONS = (0.4, 0.7, 1.0)  # fractions of TSTOP to evaluate at
WALL_MARGIN_M = 1.0  # exclude cells within this distance of x=0/L (wall effects)


def verify(map_path: Path) -> dict[str, Any]:
    from generate import LENGTH, TSTOP

    ugrid_ds = xu.open_dataset(map_path, decode_timedelta=False)
    grid = ugrid_ds.ugrid.grids[0]
    face_x = grid.face_coordinates[:, 0]
    ds = ugrid_ds.obj
    time_s = (ds["time"].values - ds["time"].values[0]) / np.timedelta64(1, "s")

    _, _, shock_speed = intermediate_state()

    checks = []
    for fraction in ANALYSIS_FRACTIONS:
        t_target = fraction * TSTOP
        time_index = int(np.argmin(np.abs(time_s - t_target)))
        t_actual = float(time_s[time_index])

        depth = np.asarray(ds["mesh2d_waterdepth"].isel(time=time_index).values)
        ucx = np.asarray(ds["mesh2d_ucx"].isel(time=time_index).values)

        h_exact, u_exact = stoker_solution(face_x, t_actual)

        x_shock_exact = X0 + shock_speed * t_actual
        # Locate the simulated front: steepest negative d(depth)/dx crossing
        # the mid-value between h_m and h_right, restricted to the region
        # downstream of the rarefaction (near where the exact shock is).
        window = np.abs(face_x - x_shock_exact) < 5.0
        if window.sum() >= 2:
            idx_window = np.where(window)[0]
            grad = np.gradient(depth[idx_window], face_x[idx_window])
            x_shock_sim = float(face_x[idx_window[np.argmin(grad)]])
        else:
            x_shock_sim = float("nan")
        shock_error_dx = abs(x_shock_sim - x_shock_exact) / DX

        wall_ok = (face_x > WALL_MARGIN_M) & (face_x < LENGTH - WALL_MARGIN_M)
        away_from_shock = np.abs(face_x - x_shock_exact) > SHOCK_EXCLUSION_DX * DX
        mask = wall_ok & away_from_shock

        depth_rms = float(np.sqrt(np.mean((depth[mask] - h_exact[mask]) ** 2)))
        velocity_rms = float(np.sqrt(np.mean((ucx[mask] - u_exact[mask]) ** 2)))

        checks.append(
            {
                "t_target_s": t_target,
                "t_actual_s": t_actual,
                "x_shock_exact_m": float(x_shock_exact),
                "x_shock_simulated_m": x_shock_sim,
                "shock_position_error_dx": shock_error_dx,
                "depth_rms_error_m": depth_rms,
                "velocity_rms_error_m_s": velocity_rms,
                "n_cells_compared": int(mask.sum()),
            }
        )

    passed = all(
        c["shock_position_error_dx"] < SHOCK_POSITION_TOLERANCE_DX
        and c["depth_rms_error_m"] < FIELD_RMS_TOLERANCE_M
        and c["velocity_rms_error_m_s"] < VELOCITY_RMS_TOLERANCE_M_S
        for c in checks
    )

    return {
        "case": "stoker_dambreak",
        "map_path": str(map_path),
        "h_left_m": H_LEFT,
        "h_right_m": H_RIGHT,
        "shock_speed_exact_m_s": float(shock_speed),
        "checks": checks,
        "shock_position_tolerance_dx": SHOCK_POSITION_TOLERANCE_DX,
        "field_rms_tolerance_m": FIELD_RMS_TOLERANCE_M,
        "velocity_rms_tolerance_m_s": VELOCITY_RMS_TOLERANCE_M_S,
        "passed": bool(passed),
    }


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
