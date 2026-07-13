#!/usr/bin/env python3
"""Unit-test every case's comparator against synthetic (not simulated) data.

None of the ``verify.py`` scripts can be exercised against a real dflowfm
run yet (see ../README.md "Status"), so this script instead builds, for each
case, a synthetic UGRID map.nc file on the case's own grid, filled directly
from the case's own closed-form exact solution (see common/synthetic_map.py)
-- and checks two things per case:

1. "positive" control: exact-solution-as-data must PASS the comparator.
2. "negative" control: the same data, perturbed well beyond the comparator's
   stated tolerance, must FAIL the comparator.

This tests the comparators' logic (thresholds, indexing, masking) in
isolation from both the physics and the native dflowfm binary. It does not
replace running the real suite once dflowfm is available.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

CASES_DIR = Path(__file__).resolve().parent


def _import(case: str, module: str):
    """(Re-)import a case's generate.py or verify.py as plain "generate"/"verify".

    Every case names its scripts identically (``generate.py``, ``verify.py``),
    and ``verify.py`` itself does a bare ``from generate import ...`` relying
    on its own directory being on ``sys.path``. To keep that working while
    still getting the *current* case's file (not a different case's,
    cached under the same plain module name from an earlier call in this
    process), we forcibly evict any stale ``generate``/``verify`` entries
    from ``sys.modules`` before each (re-)import.
    """
    import importlib

    sys.modules.pop("generate", None)
    sys.modules.pop("verify", None)

    case_dir = CASES_DIR / case
    sys.path.insert(0, str(case_dir))
    try:
        return importlib.import_module(module)
    finally:
        sys.path.remove(str(case_dir))


def test_lake_at_rest(tmp_dir: Path) -> None:
    from common.grid import build_rectilinear_grid
    from common.synthetic_map import write_synthetic_map

    gen = _import("lake_at_rest", "generate")
    grid = build_rectilinear_grid(
        tmp_dir / "net.nc", gen.LENGTH, gen.WIDTH, gen.DX, gen.DY, gen.bed_level
    )
    n = len(grid.face_x)
    times = np.linspace(0.0, gen.TSTOP, 5)

    verify = _import("lake_at_rest", "verify")

    good_path = write_synthetic_map(
        tmp_dir / "good_map.nc",
        grid,
        times,
        {
            "mesh2d_s1": np.full((len(times), n), gen.WATER_LEVEL),
            "mesh2d_ucx": np.zeros((len(times), n)),
            "mesh2d_ucy": np.zeros((len(times), n)),
        },
    )
    good = verify.verify(good_path)
    assert good["passed"], f"lake_at_rest: exact data should pass: {good}"

    bad_ucx = np.zeros((len(times), n))
    bad_ucx[-1, 0] = 1.0e-3  # 1000x the 1e-6 m/s tolerance
    bad_path = write_synthetic_map(
        tmp_dir / "bad_map.nc",
        grid,
        times,
        {
            "mesh2d_s1": np.full((len(times), n), gen.WATER_LEVEL),
            "mesh2d_ucx": bad_ucx,
            "mesh2d_ucy": np.zeros((len(times), n)),
        },
    )
    bad = verify.verify(bad_path)
    assert not bad["passed"], f"lake_at_rest: perturbed data should fail: {bad}"


def test_normal_depth_channel(tmp_dir: Path) -> None:
    from common.grid import build_rectilinear_grid
    from common.synthetic_map import write_synthetic_map

    gen = _import("normal_depth_channel", "generate")
    grid = build_rectilinear_grid(
        tmp_dir / "net.nc", gen.LENGTH, gen.WIDTH, gen.DX, gen.DY, gen.bed_level
    )
    n = len(grid.face_x)
    h0 = gen.solve_normal_depth(gen.DISCHARGE, gen.WIDTH, gen.MANNING_N, gen.BED_SLOPE)
    u0 = gen.DISCHARGE / (gen.WIDTH * h0)
    times = np.linspace(0.0, gen.TSTOP, 3)

    verify = _import("normal_depth_channel", "verify")

    good_path = write_synthetic_map(
        tmp_dir / "good_map.nc",
        grid,
        times,
        {
            "mesh2d_waterdepth": np.full((len(times), n), h0),
            "mesh2d_ucx": np.full((len(times), n), u0),
        },
    )
    good = verify.verify(good_path)
    assert good["passed"], f"normal_depth_channel: exact data should pass: {good}"

    bad_depth = np.full((len(times), n), h0 * 1.5)  # 50% off, tolerance is 2%
    bad_path = write_synthetic_map(
        tmp_dir / "bad_map.nc",
        grid,
        times,
        {
            "mesh2d_waterdepth": bad_depth,
            "mesh2d_ucx": np.full((len(times), n), u0),
        },
    )
    bad = verify.verify(bad_path)
    assert not bad["passed"], f"normal_depth_channel: perturbed data should fail: {bad}"


def test_linear_seiche(tmp_dir: Path) -> None:
    from common.grid import build_rectilinear_grid
    from common.synthetic_map import write_synthetic_map

    gen = _import("linear_seiche", "generate")
    grid = build_rectilinear_grid(
        tmp_dir / "net.nc", gen.LENGTH, gen.WIDTH, gen.DX, gen.DY, gen.bed_level
    )
    n = len(grid.face_x)
    t1 = gen.seiche_period()
    times = np.arange(0.0, gen.N_PERIODS * t1, gen.MAP_INTERVAL)
    omega = 2.0 * np.pi / t1

    verify = _import("linear_seiche", "verify")

    def eta(t: np.ndarray) -> np.ndarray:
        return gen.AMPLITUDE * np.cos(np.pi * grid.face_x / gen.LENGTH)[None, :] * np.cos(
            omega * t
        )[:, None]

    good_path = write_synthetic_map(
        tmp_dir / "good_map.nc", grid, times, {"mesh2d_s1": eta(times)}
    )
    good = verify.verify(good_path)
    assert good["passed"], f"linear_seiche: exact data should pass: {good}"

    omega_bad = omega * 1.10  # 10% off, tolerance is 2%
    bad_signal = gen.AMPLITUDE * np.cos(np.pi * grid.face_x / gen.LENGTH)[None, :] * np.cos(
        omega_bad * times
    )[:, None]
    bad_path = write_synthetic_map(
        tmp_dir / "bad_map.nc", grid, times, {"mesh2d_s1": bad_signal}
    )
    bad = verify.verify(bad_path)
    assert not bad["passed"], f"linear_seiche: perturbed data should fail: {bad}"


def test_stoker_dambreak(tmp_dir: Path) -> None:
    from common.grid import build_rectilinear_grid
    from common.synthetic_map import write_synthetic_map

    gen = _import("stoker_dambreak", "generate")
    grid = build_rectilinear_grid(
        tmp_dir / "net.nc", gen.LENGTH, gen.WIDTH, gen.DX, gen.DY, lambda x, y: 0.0 * x
    )
    n = len(grid.face_x)
    times = np.arange(0.0, gen.TSTOP + gen.MAP_INTERVAL, gen.MAP_INTERVAL)

    verify = _import("stoker_dambreak", "verify")

    depth = np.empty((len(times), n))
    ucx = np.empty((len(times), n))
    for i, t in enumerate(times):
        h, u = gen.stoker_solution(grid.face_x, float(t))
        depth[i], ucx[i] = h, u

    good_path = write_synthetic_map(
        tmp_dir / "good_map.nc",
        grid,
        times,
        {"mesh2d_waterdepth": depth, "mesh2d_ucx": ucx},
    )
    good = verify.verify(good_path)
    assert good["passed"], f"stoker_dambreak: exact data should pass: {good}"

    bad_depth = depth + 0.5  # way beyond the 2%*H_LEFT RMS tolerance
    bad_path = write_synthetic_map(
        tmp_dir / "bad_map.nc",
        grid,
        times,
        {"mesh2d_waterdepth": bad_depth, "mesh2d_ucx": ucx},
    )
    bad = verify.verify(bad_path)
    assert not bad["passed"], f"stoker_dambreak: perturbed data should fail: {bad}"


def test_thacker_basin(tmp_dir: Path) -> None:
    from common.grid import build_rectilinear_grid
    from common.synthetic_map import write_synthetic_map

    gen = _import("thacker_basin", "generate")
    grid = build_rectilinear_grid(
        tmp_dir / "net.nc", gen.LENGTH, gen.WIDTH, gen.DX, gen.DY, gen.bed_level
    )
    n = len(grid.face_x)
    t_period = gen.period()
    times = np.arange(0.0, gen.N_PERIODS * t_period + gen.MAP_INTERVAL, gen.MAP_INTERVAL)

    verify = _import("thacker_basin", "verify")

    depth = np.empty((len(times), n))
    ucx = np.empty((len(times), n))
    for i, t in enumerate(times):
        h, u = gen.thacker_solution(grid.face_x, float(t))
        depth[i], ucx[i] = h, u

    good_path = write_synthetic_map(
        tmp_dir / "good_map.nc",
        grid,
        times,
        {"mesh2d_waterdepth": depth, "mesh2d_ucx": ucx},
    )
    good = verify.verify(good_path)
    assert good["passed"], f"thacker_basin: exact data should pass: {good}"

    # Shrink the wet region by ~20*dx on both sides: an obviously-wrong
    # shoreline, well beyond the tolerance of 5 dx.
    bad_depth = depth.copy()
    shrink = 20
    for i in range(len(times)):
        wet_idx = np.where(bad_depth[i] > 0)[0]
        if wet_idx.size > 2 * shrink:
            bad_depth[i, wet_idx[:shrink]] = 0.0
            bad_depth[i, wet_idx[-shrink:]] = 0.0
    bad_path = write_synthetic_map(
        tmp_dir / "bad_map.nc",
        grid,
        times,
        {"mesh2d_waterdepth": bad_depth, "mesh2d_ucx": ucx},
    )
    bad = verify.verify(bad_path)
    assert not bad["passed"], f"thacker_basin: perturbed data should fail: {bad}"


TESTS = [
    test_lake_at_rest,
    test_normal_depth_channel,
    test_linear_seiche,
    test_stoker_dambreak,
    test_thacker_basin,
]


def main() -> int:
    import tempfile

    failures = 0
    for test in TESTS:
        name = test.__name__
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(Path(tmp))
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} comparator self-tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
