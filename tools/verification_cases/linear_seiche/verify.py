#!/usr/bin/env python3
"""Verify the linear-seiche map output against Merian's dispersion relation.

The period is extracted from the simulated free-surface time series purely
by counting zero-up-crossings (linear interpolation between samples) -- no
assumption about the analytic frequency is used in the extraction, so this
is an independent check of the wave-propagation core against
:func:`generate.seiche_period` (T1 = 2L / sqrt(g H0)).
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
from generate import DEPTH, LENGTH, seiche_period  # noqa: E402

# Provisional tolerance (see README "Tolerance policy"): with a/H0 = 0.02,
# amplitude dispersion (a nonlinear shallow-water effect, absent from the
# linear dispersion relation used here) and numerical dispersion from the
# finite dx/dt are both expected to be well under 1%; 2% leaves headroom.
PERIOD_RELATIVE_TOLERANCE = 0.02


def zero_up_crossing_period(time_s: np.ndarray, signal: np.ndarray) -> float:
    """Estimate the dominant period from zero-up-crossings, linearly interpolated.

    Returns the mean spacing between consecutive positive-going zero
    crossings of ``signal - mean(signal)``, i.e. one estimate of the period
    per detected crossing pair.
    """
    centered = signal - np.mean(signal)
    sign = np.signbit(centered)  # True where negative
    up_crossings = np.where(sign[:-1] & ~sign[1:])[0]
    if up_crossings.size < 2:
        raise ValueError("fewer than two zero-up-crossings found; run too short?")

    crossing_times = []
    for i in up_crossings:
        t0, t1 = time_s[i], time_s[i + 1]
        y0, y1 = centered[i], centered[i + 1]
        frac = -y0 / (y1 - y0)
        crossing_times.append(t0 + frac * (t1 - t0))
    crossing_times = np.asarray(crossing_times)
    periods = np.diff(crossing_times)
    return float(np.mean(periods)), periods


def verify(map_path: Path) -> dict[str, Any]:
    t1_exact = seiche_period()

    ugrid_ds = xu.open_dataset(map_path, decode_timedelta=False)
    grid = ugrid_ds.ugrid.grids[0]
    face_x = grid.face_coordinates[:, 0]
    corner_face = int(np.argmin(face_x))  # cell nearest x=0, the antinode

    ds = ugrid_ds.obj
    s1 = ds["mesh2d_s1"]
    face_dim = [d for d in s1.dims if d != "time"][0]
    waterlevel = np.asarray(s1.isel({face_dim: corner_face}).values)
    time_s = (ds["time"].values - ds["time"].values[0]) / np.timedelta64(1, "s")

    t1_measured, periods = zero_up_crossing_period(time_s, waterlevel)
    relative_error = abs(t1_measured - t1_exact) / t1_exact

    result = {
        "case": "linear_seiche",
        "map_path": str(map_path),
        "length_m": LENGTH,
        "depth_m": DEPTH,
        "period_exact_s": t1_exact,
        "period_measured_s": t1_measured,
        "n_periods_detected": int(len(periods)),
        "period_relative_error": relative_error,
        "relative_tolerance": PERIOD_RELATIVE_TOLERANCE,
    }
    result["passed"] = bool(relative_error < PERIOD_RELATIVE_TOLERANCE)
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
