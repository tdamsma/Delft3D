"""Build synthetic D-Flow FM-shaped UGRID map datasets for comparator self-tests.

None of the comparator scripts (``verify.py``) can be exercised against a
real dflowfm run until the native binary is available, so each one is
instead unit-tested here against a *synthetic* map file: the grid comes from
the same :func:`common.grid.build_rectilinear_grid` the case's own
``generate.py`` uses, and the data variables (``mesh2d_s1``,
``mesh2d_waterdepth``, ``mesh2d_ucx``, ``mesh2d_ucy``) are filled directly
from each case's own closed-form exact solution (optionally perturbed), so
we are testing the *comparator's logic*, not the physics.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
import xugrid as xu

from .grid import FlumeGrid


def write_synthetic_map(
    path: Path,
    grid: FlumeGrid,
    times_s: np.ndarray,
    variables: dict[str, np.ndarray],
    bed_level_at_face: np.ndarray | None = None,
) -> Path:
    """Write a minimal D-Flow FM-shaped UGRID map.nc file.

    Args:
        path: Output netCDF path.
        grid: The FlumeGrid the data lives on (for topology + face coords).
        times_s: 1D array of times [s] since an arbitrary epoch.
        variables: Mapping of D-Flow FM map variable name (e.g.
            ``"mesh2d_s1"``, ``"mesh2d_waterdepth"``, ``"mesh2d_ucx"``,
            ``"mesh2d_ucy"``) to a ``(len(times_s), n_faces)`` array.
        bed_level_at_face: Unused placeholder for symmetry with real output
            (bed level is a static, not time-varying, map quantity); kept
            for callers that want to record it alongside for clarity.

    Returns:
        The path written to (for convenience chaining).
    """
    mesh2d = grid.network._mesh2d.meshkernel.mesh2d_get()
    ugrid2d = xu.Ugrid2d.from_meshkernel(mesh2d, name="mesh2d")

    # NB: build the timedelta64 directly in nanoseconds from a (rounded)
    # integer count, not via `(times_s * timedelta64(1, "s")).astype(
    # "timedelta64[s]")` -- the latter's final cast *truncates to whole
    # seconds*, silently discarding all sub-second time resolution. That
    # went undetected for a long time because every case whose
    # MAP_INTERVAL happens to be a whole number of seconds (e.g.
    # linear_seiche's 1.0 s) is unaffected by construction, but it
    # corrupted thacker_basin's sub-second (0.02 s) time axis down to
    # ~1 s spacing -- fine for the original pointwise-only checks (which
    # compared the exact solution at that same, self-consistently coarse
    # time), but fatal for a from-data period measurement (added to
    # thacker_basin/verify.py after a real run), which needs the actual
    # sub-second sample spacing to resolve zero-up-crossings accurately.
    time = np.datetime64("2000-01-01T00:00:00", "ns") + np.round(
        np.asarray(times_s, dtype=np.float64) * 1.0e9
    ).astype("int64").astype("timedelta64[ns]")

    data_vars = {}
    n_faces = len(grid.face_x)
    for name, values in variables.items():
        values = np.asarray(values, dtype=np.float64)
        assert values.shape == (len(times_s), n_faces), (
            f"{name}: expected shape {(len(times_s), n_faces)}, got {values.shape}"
        )
        data_vars[name] = xr.DataArray(values, dims=("time", "mesh2d_nFaces"))

    ds = xr.Dataset(data_vars).assign_coords(time=time)
    uds = xu.UgridDataset(ds, grids=[ugrid2d])
    path.parent.mkdir(parents=True, exist_ok=True)
    uds.ugrid.to_netcdf(path)
    return path
