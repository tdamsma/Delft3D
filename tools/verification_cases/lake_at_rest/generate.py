#!/usr/bin/env python3
"""Generate the lake-at-rest verification case.

See ../README.md, section "Lake at rest", for the exact solution and the
well-balancedness argument this case exercises.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.grid import build_rectilinear_grid  # noqa: E402
from common.mdu_base import make_base_model  # noqa: E402

LENGTH = 100.0  # m, x-extent
WIDTH = 60.0  # m, y-extent
DX = 5.0
DY = 5.0
WATER_LEVEL = 0.5  # m, uniform initial (and, analytically, for all time) water level
TSTOP = 3600.0  # s, 1 hour: long enough to reveal any well-balancedness drift
MAP_INTERVAL = 300.0
HIS_INTERVAL = 60.0


def bed_level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Uneven bed elevation z_b(x, y) [m], see README for the equation.

    Bounded in [-6.5, -1.5] m; combined with WATER_LEVEL = 0.5 m this keeps
    the whole basin wet with at least ~2 m of margin everywhere (including
    at BedLevType=3's mean-of-surrounding-nodes cell-center bed level, which
    cannot exceed the local node maximum).
    """
    bowl = 1.5 * np.sin(2.0 * np.pi * x / LENGTH) * np.cos(2.0 * np.pi * y / WIDTH)
    bump = 1.0 * np.exp(
        -(((x - 0.6 * LENGTH) ** 2) + ((y - 0.4 * WIDTH) ** 2)) / (0.15 * LENGTH) ** 2
    )
    return -4.0 + bowl + bump


def generate(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    net_path = out_dir / "lake_net.nc"
    grid = build_rectilinear_grid(
        net_path, length=LENGTH, width=WIDTH, dx=DX, dy=DY, bed_level=bed_level
    )
    assert (grid.node_z < WATER_LEVEL - 1.0).all(), "bed too close to water level"

    model = make_base_model(
        network=grid.network,
        net_filename=net_path.name,
        tstop=TSTOP,
        dtmax=10.0,
        dtinit=0.1,
        his_interval=HIS_INTERVAL,
        map_interval=MAP_INTERVAL,
        uniffrictcoef=0.0,  # frictionless: this case is about the pressure/bed-slope
        # source-term balance, not friction.
        waterlevini=WATER_LEVEL,
    )
    mdu_path = out_dir / "lake_at_rest.mdu"
    model.filepath = mdu_path
    model.save(recurse=True)
    return mdu_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "run",
        help="Directory to write the run's .mdu/net/inifield files into.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mdu_path = generate(args.out_dir)
    print(f"wrote {mdu_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
