#!/usr/bin/env python3
"""Generate the normal-depth uniform-channel-flow verification case.

See ../README.md, section "Normal-depth uniform channel flow", for the exact
Manning equilibrium depth/velocity and their derivation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.boundary import constant_boundary  # noqa: E402
from common.grid import build_rectilinear_grid  # noqa: E402
from common.mdu_base import make_base_model  # noqa: E402
from hydrolib.core.dflowfm.ext.models import ExtModel  # noqa: E402

LENGTH = 200.0  # m
WIDTH = 10.0  # m (channel width b)
DX = 5.0
DY = WIDTH  # single row of cells: an effectively 1D flume
MANNING_N = 0.03  # s / m^(1/3)
BED_SLOPE = 0.001  # -, dz/dx = -BED_SLOPE (bed drops in +x)
DISCHARGE = 5.0  # m^3/s, total (not per unit width)
TSTOP = 3000.0  # s, several channel residence times (see generate() docstring)
# MAP_INTERVAL must be an exact multiple of DtUser (=min(his,map)=HIS_INTERVAL
# here): D-Flow FM's runtime input validation (check_time_interval in
# dflowfm_data/unstruc_model.f90) rejects a Map/His interval, or a
# (TStop-TStart) span, that is not an exact multiple of DtUser. 100.0 is not
# a multiple of 30.0; 90.0 (=3*HIS_INTERVAL) is the closest round choice that
# satisfies it while keeping map output nearly as fine as originally chosen.
MAP_INTERVAL = 90.0
HIS_INTERVAL = 30.0
GRAVITY = 9.81


def bed_level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Uniform, linearly sloping bed: z_b(x) = -BED_SLOPE * x (flat in y)."""
    return -BED_SLOPE * x


def solve_normal_depth(
    discharge: float,
    width: float,
    manning_n: float,
    slope: float,
    g: float = GRAVITY,
    tol: float = 1.0e-12,
    max_iter: int = 100,
) -> float:
    """Solve Manning's equation for the normal (equilibrium) depth h0.

    Q = (1/n) * A * R^(2/3) * sqrt(S0),  A = b*h,  R = A / (b + 2h)  (rectangular
    cross-section, exact hydraulic radius -- no wide-channel approximation).
    Solved by Newton's method on f(h) = Q_manning(h) - Q = 0.
    """
    h = (discharge / width) ** 0.6  # wide-channel estimate as the Newton seed
    for _ in range(max_iter):
        area = width * h
        wetted_perimeter = width + 2.0 * h
        hydraulic_radius = area / wetted_perimeter
        q_manning = (1.0 / manning_n) * area * hydraulic_radius ** (2.0 / 3.0) * np.sqrt(
            slope
        )
        residual = q_manning - discharge

        eps = 1.0e-8 * max(h, 1.0)
        area2 = width * (h + eps)
        wetted_perimeter2 = width + 2.0 * (h + eps)
        hydraulic_radius2 = area2 / wetted_perimeter2
        q_manning2 = (1.0 / manning_n) * area2 * hydraulic_radius2 ** (
            2.0 / 3.0
        ) * np.sqrt(slope)
        derivative = (q_manning2 - q_manning) / eps

        step = residual / derivative
        h -= step
        if abs(step) < tol:
            break
    return h


def generate(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    net_path = out_dir / "channel_net.nc"
    grid = build_rectilinear_grid(
        net_path, length=LENGTH, width=WIDTH, dx=DX, dy=DY, bed_level=bed_level
    )
    assert grid.ny == 1, "expected a single-row flume"

    h0 = solve_normal_depth(DISCHARGE, WIDTH, MANNING_N, BED_SLOPE)
    downstream_level = bed_level(np.array([LENGTH]), np.array([0.0]))[0] + h0

    # Initial condition: uniform absolute water level h0/2, i.e. a *different*
    # depth profile than the analytic equilibrium (deeper downstream, since
    # the bed drops while the surface starts flat) -- see SWASHES (Delestre
    # et al. 2013) remark that initial conditions equal to the expected
    # steady state would only test preservation, not convergence.
    initial_level = 0.5 * h0

    model = make_base_model(
        network=grid.network,
        net_filename=net_path.name,
        tstop=TSTOP,
        dtmax=5.0,
        dtinit=0.1,
        his_interval=HIS_INTERVAL,
        map_interval=MAP_INTERVAL,
        uniffrictcoef=MANNING_N,
        uniffricttype=1,  # 1 = Manning (UM Sec.A.3, [physics] UnifFrictType)
        waterlevini=initial_level,
    )

    upstream = constant_boundary(
        name="upstream",
        quantity="dischargebnd",
        unit="m3/s",
        value=DISCHARGE,
        y_points=(-1.0, WIDTH + 1.0),
        x=0.0,
        pli_path=out_dir / "upstream.pli",
        bc_path=out_dir / "upstream.bc",
    )
    downstream = constant_boundary(
        name="downstream",
        quantity="waterlevelbnd",
        unit="m",
        value=downstream_level,
        y_points=(-1.0, WIDTH + 1.0),
        x=LENGTH,
        pli_path=out_dir / "downstream.pli",
        bc_path=out_dir / "downstream.bc",
    )
    model.external_forcing.extforcefilenew = ExtModel(boundary=[upstream, downstream])

    mdu_path = out_dir / "normal_depth_channel.mdu"
    model.filepath = mdu_path
    model.save(recurse=True)
    return mdu_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mdu_path = generate(args.out_dir)
    print(f"wrote {mdu_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
