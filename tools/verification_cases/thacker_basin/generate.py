#!/usr/bin/env python3
"""Generate the Thacker planar-surface verification case (with wetting/drying).

See ../README.md, section "Thacker oscillating basin (planar)", for the full
exact periodic solution (from Delestre et al. 2013, SWASHES, Sec.4.2.1,
itself citing Thacker 1981) reproduced in :func:`thacker_solution` below.
This is the hardest and most valuable case in the suite: it is the only one
exercising the flooding/drying logic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.fields import collocated_sample_field  # noqa: E402
from common.grid import build_rectilinear_grid  # noqa: E402
from common.mdu_base import make_base_model, round_up_to_multiple  # noqa: E402
from hydrolib.core.dflowfm.inifield.models import IniFieldModel  # noqa: E402

# Parameters follow SWASHES's own reference values for this case exactly
# (a=1 m, h0=0.5 m, L=4 m), so results are directly comparable to that
# widely-used benchmark compilation.
LENGTH = 4.0  # m, domain [0, L]; the parabola is centered at L/2
BASIN_RADIUS = 1.0  # m, "a": half-width of the paraboloid at the rim
CENTRAL_DEPTH = 0.5  # m, "h0": depth at the basin center for a flat (z=0) surface
WIDTH = 0.5  # m, cross-channel width (planar case: bed/solution are y-invariant)
DX = 0.02  # m: 200 cells over the 4 m length, to resolve the moving shoreline
DY = WIDTH
GRAVITY = 9.81

N_PERIODS = 3
MAP_INTERVAL = 0.02
HIS_INTERVAL = 0.02

# D-Flow FM's default wetting/drying threshold depth (epsHu, [numerics]
# section). Kept at the hydrolib-core/D-Flow FM default rather than tuned,
# since this case is precisely meant to probe the default drying behavior;
# see README "Tolerance policy" for the implication on shoreline accuracy.
EPSHU = 1.0e-4


def angular_frequency(
    basin_radius: float = BASIN_RADIUS, central_depth: float = CENTRAL_DEPTH, g: float = GRAVITY
) -> float:
    """omega = sqrt(2*g*h0) / a (SWASHES Sec.4.2.1)."""
    return np.sqrt(2.0 * g * central_depth) / basin_radius


def period(
    basin_radius: float = BASIN_RADIUS, central_depth: float = CENTRAL_DEPTH, g: float = GRAVITY
) -> float:
    return 2.0 * np.pi / angular_frequency(basin_radius, central_depth, g)


def bed_level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """z(x) = h0 * ( ((x - L/2)/a)^2 - 1 ): a parabolic bowl, y-invariant."""
    return CENTRAL_DEPTH * (((x - 0.5 * LENGTH) / BASIN_RADIUS) ** 2 - 1.0)


def shoreline(t: float) -> tuple[float, float]:
    """x1(t), x2(t): the wet/dry interface positions (SWASHES Sec.4.2.1)."""
    omega = angular_frequency()
    common = -0.5 * np.cos(omega * t) + 0.5 * LENGTH
    return common - BASIN_RADIUS, common + BASIN_RADIUS


def thacker_solution(x: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    """Exact Thacker 1D planar solution: depth h(x, t) and velocity u(x, t).

    h(x, t) = -h0 * ( ((x-L/2)/a + B/sqrt(2 g h0) * cos(omega t))^2 - 1 )
              for x1(t) <= x <= x2(t), else 0 (dry)
    u(x, t)  = B * sin(omega t)          for x1(t) <= x <= x2(t), else 0
    with B = sqrt(2*g*h0) / (2*a), omega = sqrt(2*g*h0)/a.
    """
    omega = angular_frequency()
    b_coeff = np.sqrt(2.0 * GRAVITY * CENTRAL_DEPTH) / (2.0 * BASIN_RADIUS)
    x1, x2 = shoreline(t)

    xi = (x - 0.5 * LENGTH) / BASIN_RADIUS + (b_coeff / np.sqrt(2.0 * GRAVITY * CENTRAL_DEPTH)) * np.cos(
        omega * t
    )
    depth = -CENTRAL_DEPTH * (xi**2 - 1.0)
    velocity = np.full_like(x, b_coeff * np.sin(omega * t))

    wet = (x >= x1) & (x <= x2)
    depth = np.where(wet, depth, 0.0)
    velocity = np.where(wet, velocity, 0.0)
    return depth, velocity


def generate(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    net_path = out_dir / "thacker_net.nc"
    grid = build_rectilinear_grid(
        net_path, length=LENGTH, width=WIDTH, dx=DX, dy=DY, bed_level=bed_level
    )

    x1_0, x2_0 = shoreline(0.0)
    assert x1_0 > 0.2 and x2_0 < LENGTH - 0.2, "shoreline swing must stay clear of domain walls"

    # TSTOP is snapped up to a whole multiple of DtUser (=min(his,map)
    # interval = 0.02 s here): D-Flow FM requires (TStop - TStart) to be an
    # exact DtUser multiple (see round_up_to_multiple's docstring), which
    # N_PERIODS * period() is not in general, since the period involves
    # 2*pi/omega.
    tstop = round_up_to_multiple(N_PERIODS * period(), min(HIS_INTERVAL, MAP_INTERVAL))

    def initial_waterdepth(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Prescribe *depth* directly rather than absolute water level.

        A real run showed that ``BedLevType=3`` ("at face, using mean
        network levels") derives each flow cell's actual bed level from
        neighboring *node* z-values, which for this strongly-curved
        (quadratic) parabolic bed differs from :func:`bed_level` evaluated
        exactly at the cell-center x by up to ~0.02 m near the domain
        edges (confirmed by comparing this run's own
        ``mesh2d_flowelem_bl`` map output against ``bed_level(face_x)``).
        Setting the initial condition as an absolute water level
        (``bed_level(x) + depth0``, this suite's original approach) bakes
        that mismatch directly into the realized depth (``actual depth =
        prescribed s1 - actual bed level = depth0 + (bed_level(x) -
        actual bed level)``), corrupting exactly the dry/wet transition
        this case exists to test (observed as spurious few-cm-deep
        "pre-wetting" beyond the true analytic shoreline at t=0, and a
        persistent shoreline/velocity bias throughout the run). Using the
        ``waterdepth``/``initialWaterDepth`` quantity instead (confirmed
        supported by dflowfm, see
        ``fm_external_forcings_init.f90``'s ``'waterdepth'``/
        ``'initialwaterdepth'`` cases) sidesteps the mismatch entirely: D-Flow
        FM adds this depth on top of whatever bed level it actually computed
        for that cell, so the realized depth matches the analytic solution
        regardless of the bed-level discretization detail.
        """
        depth0, _ = thacker_solution(x, 0.0)
        return depth0

    model = make_base_model(
        network=grid.network,
        net_filename=net_path.name,
        tstop=tstop,
        dtmax=0.01,
        dtinit=0.001,
        his_interval=HIS_INTERVAL,
        map_interval=MAP_INTERVAL,
        uniffrictcoef=0.0,  # frictionless: matches Thacker's undamped solution
        epshu=EPSHU,
    )

    ini_field = collocated_sample_field(
        "waterdepth",
        out_dir / "initial_waterdepth.xyz",
        grid.face_x,
        grid.face_y,
        initial_waterdepth,
        # Single-row flume: every face_y is identical, which makes
        # Delaunay triangulation degenerate (see collocated_sample_field's
        # y_jitter docstring) -- confirmed by a real run silently keeping
        # the flat default IC (zero velocity throughout, and the shoreline
        # frozen and centered rather than oscillating). WIDTH/2 places the
        # extra sample rows exactly on the domain's y=0/y=WIDTH edges.
        y_jitter=WIDTH / 2.0,
        # Every flow node already has its own exact sample (dry-zone nodes
        # included, with the exact zero-depth value); extrapolation is not
        # just unneeded here but actively harmful -- a real run showed it
        # bleeding small spurious positive depths beyond the true shoreline
        # at t=0 (see collocated_sample_field's extrapolate docstring),
        # corrupting the one case in this suite that specifically tests
        # wetting/drying.
        extrapolate=False,
    )
    model.geometry.inifieldfile = IniFieldModel(initial=[ini_field])
    # Initial velocity is exactly zero everywhere at t=0 in this
    # parametrization (u(x,0) = B*sin(0) = 0), so no InitialVelocityX/Y
    # field is needed -- D-Flow FM starts from rest by default.

    mdu_path = out_dir / "thacker_basin.mdu"
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
