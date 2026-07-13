#!/usr/bin/env python3
"""Generate the Stoker wet-bed dam-break verification case.

See ../README.md, section "Stoker dam break (wet bed)", for the full Riemann
solution (from Delestre et al. 2013, SWASHES, Sec.4.1.1, itself citing
Stoker 1957) reproduced in :func:`stoker_solution` below.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.fields import polygon_value_field, write_polygon  # noqa: E402
from common.grid import build_rectilinear_grid  # noqa: E402
from common.mdu_base import make_base_model  # noqa: E402
from hydrolib.core.dflowfm.inifield.models import IniFieldModel  # noqa: E402

LENGTH = 50.0  # m
X0 = 20.0  # m, dam location
WIDTH = 5.0  # m
DX = 0.25
DY = WIDTH  # single row of cells: an effectively 1D flume
H_LEFT = 1.0  # m, reservoir depth h_l
H_RIGHT = 0.3  # m, downstream (wet) depth h_r
GRAVITY = 9.81

TSTOP = 5.0  # s: see generate.py module docstring / README for the margin check
MAP_INTERVAL = 0.25
HIS_INTERVAL = 0.25


def intermediate_state(
    h_left: float = H_LEFT,
    h_right: float = H_RIGHT,
    g: float = GRAVITY,
    tol: float = 1.0e-14,
    max_iter: int = 200,
) -> tuple[float, float, float]:
    """Solve for Stoker's intermediate state (h_m, u_m) and shock speed S.

    c_m = sqrt(g*h_m) is the unique root, in (sqrt(g*h_right), sqrt(g*h_left)),
    of
        -8*g*h_right*c_m^2*(sqrt(g*h_left) - c_m)^2
        + (c_m^2 - g*h_right)^2 * (c_m^2 + g*h_right) = 0
    (SWASHES Sec.4.1.1). Solved here by bisection, which is robust because
    the root is bracketed and the function changes sign exactly once in
    that interval for h_left > h_right > 0.
    """

    def residual(c_m: float) -> float:
        return -8.0 * g * h_right * c_m**2 * (np.sqrt(g * h_left) - c_m) ** 2 + (
            c_m**2 - g * h_right
        ) ** 2 * (c_m**2 + g * h_right)

    lo = np.sqrt(g * h_right) * (1.0 + 1.0e-12)
    hi = np.sqrt(g * h_left) * (1.0 - 1.0e-12)
    f_lo = residual(lo)
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = residual(mid)
        if np.sign(f_mid) == np.sign(f_lo):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    c_m = 0.5 * (lo + hi)
    h_m = c_m**2 / g
    u_m = 2.0 * (np.sqrt(g * h_left) - c_m)
    shock_speed = 2.0 * c_m**2 * (np.sqrt(g * h_left) - c_m) / (c_m**2 - g * h_right)
    return h_m, u_m, shock_speed


def stoker_solution(
    x: np.ndarray,
    t: float,
    x0: float = X0,
    h_left: float = H_LEFT,
    h_right: float = H_RIGHT,
    g: float = GRAVITY,
) -> tuple[np.ndarray, np.ndarray]:
    """Exact Stoker wet-bed dam-break solution h(x, t), u(x, t) at time t > 0.

    SWASHES (Delestre et al. 2013) Sec.4.1.1, citing Stoker (1957),
    "Water Waves", pp.333-341. Four zones, from left to right:
      1. undisturbed reservoir: h=h_left, u=0, for x <= xA(t)
      2. rarefaction fan, for xA(t) <= x <= xB(t)
      3. constant intermediate state: h=h_m, u=u_m, for xB(t) <= x <= xC(t)
      4. undisturbed downstream: h=h_right, u=0, for x > xC(t)
    """
    if t <= 0:
        h = np.where(x <= x0, h_left, h_right)
        u = np.zeros_like(x)
        return h, u

    h_m, u_m, shock_speed = intermediate_state(h_left, h_right, g)
    c_m = np.sqrt(g * h_m)

    x_a = x0 - t * np.sqrt(g * h_left)
    x_b = x0 + t * (2.0 * np.sqrt(g * h_left) - 3.0 * c_m)
    x_c = x0 + t * shock_speed

    h = np.empty_like(x, dtype=np.float64)
    u = np.empty_like(x, dtype=np.float64)

    in_reservoir = x <= x_a
    in_fan = (x > x_a) & (x <= x_b)
    in_middle = (x > x_b) & (x <= x_c)
    in_downstream = x > x_c

    h[in_reservoir] = h_left
    u[in_reservoir] = 0.0

    xi = (x[in_fan] - x0) / t
    h[in_fan] = (4.0 / (9.0 * g)) * (np.sqrt(g * h_left) - xi / 2.0) ** 2
    u[in_fan] = (2.0 / 3.0) * (xi + np.sqrt(g * h_left))

    h[in_middle] = h_m
    u[in_middle] = u_m

    h[in_downstream] = h_right
    u[in_downstream] = 0.0

    return h, u


def generate(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Margin check: neither the left-going rarefaction head nor the
    # right-going shock may reach a domain wall within [0, TSTOP], or the
    # (physically fictitious, closed) channel ends would contaminate the
    # solution.
    _, _, shock_speed = intermediate_state()
    left_reach = TSTOP * np.sqrt(GRAVITY * H_LEFT)
    right_reach = TSTOP * shock_speed
    assert X0 - left_reach > 1.0, "rarefaction head would reach the left wall"
    assert (LENGTH - X0) - right_reach > 1.0, "shock would reach the right wall"

    net_path = out_dir / "dambreak_net.nc"
    grid = build_rectilinear_grid(
        net_path,
        length=LENGTH,
        width=WIDTH,
        dx=DX,
        dy=DY,
        bed_level=lambda x, y: 0.0 * x,  # flat bed
    )

    left_pol = out_dir / "reservoir.pol"
    right_pol = out_dir / "downstream.pol"
    write_polygon(
        left_pol, [(0.0, -1.0), (X0, -1.0), (X0, WIDTH + 1.0), (0.0, WIDTH + 1.0)], "reservoir"
    )
    write_polygon(
        right_pol,
        [(X0, -1.0), (LENGTH, -1.0), (LENGTH, WIDTH + 1.0), (X0, WIDTH + 1.0)],
        "downstream",
    )
    initial = [
        polygon_value_field("waterlevel", right_pol, H_RIGHT),
        polygon_value_field("waterlevel", left_pol, H_LEFT),
    ]

    model = make_base_model(
        network=grid.network,
        net_filename=net_path.name,
        tstop=TSTOP,
        dtmax=0.05,
        dtinit=0.001,
        his_interval=HIS_INTERVAL,
        map_interval=MAP_INTERVAL,
        uniffrictcoef=0.0,  # frictionless: matches the Stoker/Riemann solution
    )
    model.geometry.inifieldfile = IniFieldModel(initial=initial)

    mdu_path = out_dir / "stoker_dambreak.mdu"
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
