#!/usr/bin/env python3
"""Generate the linear-seiche verification case.

See ../README.md, section "Linear seiche in a closed basin", for the
dispersion relation (Merian's formula) this case checks.
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

LENGTH = 200.0  # m
WIDTH = 10.0  # m
DX = 2.5
DY = WIDTH  # single row of cells: an effectively 1D closed flume
DEPTH = 5.0  # m, uniform still-water depth H0
AMPLITUDE = 0.1  # m, initial tilt amplitude a (a/H0 = 0.02: small-amplitude/linear regime)
GRAVITY = 9.81

N_PERIODS = 6
MAP_INTERVAL = 1.0  # s: fine sampling for period extraction (zero-crossing method)
HIS_INTERVAL = 1.0


def seiche_period(length: float = LENGTH, depth: float = DEPTH, g: float = GRAVITY) -> float:
    """Merian's formula for the fundamental (1-node) seiche period.

    T1 = 2*L / sqrt(g*H0); see e.g. Wilson (1972), "Seiches",
    Advances in Hydroscience, Vol. 8, or any standard physical-oceanography
    text (derived from the linear shallow-water wave equation
    eta_tt = g*H0*eta_xx on [0, L] with no-flux (Neumann) walls at x=0, L:
    eigenmodes eta_n(x,t) = cos(n*pi*x/L)*cos(omega_n t),
    omega_n = n*pi*sqrt(g*H0)/L, T_n = 2*pi/omega_n = 2*L / (n*sqrt(g*H0))).
    """
    return 2.0 * length / np.sqrt(g * depth)


def bed_level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -DEPTH + 0.0 * x


def initial_waterlevel(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """eta(x, 0) = a * cos(pi*x/L): the exact n=1 eigenmode shape, u=v=0.

    Because this initial free-surface shape is precisely the n=1 basis
    function of the closed-basin eigenproblem (with zero initial velocity),
    linear theory predicts it excites *only* the fundamental mode -- no
    higher harmonics are seeded, so any measured deviation from mode-1
    behavior in the simulated signal is attributable to nonlinearity/
    discretization, not to the initial condition itself.
    """
    return AMPLITUDE * np.cos(np.pi * x / LENGTH)


def generate(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    net_path = out_dir / "seiche_net.nc"
    grid = build_rectilinear_grid(
        net_path, length=LENGTH, width=WIDTH, dx=DX, dy=DY, bed_level=bed_level
    )

    # TSTOP is snapped up to a whole multiple of DtUser (=min(his,map)
    # interval = 1.0 s here): D-Flow FM requires (TStop - TStart) to be an
    # exact DtUser multiple (see round_up_to_multiple's docstring), which
    # N_PERIODS * seiche_period() is not in general, since the period
    # involves sqrt(g*H0).
    tstop = round_up_to_multiple(N_PERIODS * seiche_period(), min(HIS_INTERVAL, MAP_INTERVAL))

    model = make_base_model(
        network=grid.network,
        net_filename=net_path.name,
        tstop=tstop,
        dtmax=2.0,
        dtinit=0.05,
        his_interval=HIS_INTERVAL,
        map_interval=MAP_INTERVAL,
        uniffrictcoef=0.0,  # frictionless: matches the inviscid linear wave theory
    )

    ini_field = collocated_sample_field(
        "waterlevel",
        out_dir / "initial_waterlevel.xyz",
        grid.face_x,
        grid.face_y,
        initial_waterlevel,
        # Single-row flume: every face_y is identical, which makes
        # Delaunay triangulation degenerate (see collocated_sample_field's
        # y_jitter docstring) -- confirmed by a real run silently keeping
        # the flat default IC (zero velocity throughout). WIDTH/2 places
        # the extra sample rows exactly on the domain's y=0/y=WIDTH edges.
        y_jitter=WIDTH / 2.0,
    )
    model.geometry.inifieldfile = IniFieldModel(initial=[ini_field])

    mdu_path = out_dir / "linear_seiche.mdu"
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
