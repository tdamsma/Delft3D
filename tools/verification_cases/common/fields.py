"""Helpers to build D-Flow FM initial-field and polyline/polygon inputs.

Two patterns are used throughout this suite to inject an exact analytic
field into D-Flow FM's initial conditions:

1. **Collocated samples + triangulation** (:func:`collocated_sample_field`):
   for smoothly varying initial conditions (a cosine tilt, a paraboloid
   free surface, ...), we write one ``.xyz`` sample *at every flow-node
   (cell-center) location*, holding the exact analytic value there. Because
   the sample points are collocated with the query points, hydrolib/D-Flow FM's
   Delaunay-triangulation interpolation returns (up to floating point/
   degenerate-triangulation error) exactly the sample value at every interior
   cell, which is the closest a mesh-based interpolation scheme can get to an
   "exact" analytic initial condition. Boundary cells rely on
   ``extrapolationMethod=True`` to avoid falling back to a default value.
2. **Polygon fields** (:func:`polygon_value_field`): for piecewise-constant
   initial conditions (the dam-break step), D-Flow FM's native "value inside
   polygon" mechanism (``dataFileType=polygon``) assigns a single constant
   exactly, with no interpolation error at all, as long as the polygon
   boundary is aligned with a mesh line (so no cell straddles it).

Both are wired into a case's ``[geometry] IniFieldFile`` through
:class:`hydrolib.core.dflowfm.inifield.models.IniFieldModel`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from hydrolib.core.dflowfm.inifield.models import (
    DataFileType,
    InitialField,
    InterpolationMethod,
)
from hydrolib.core.dflowfm.polyfile.models import Metadata, Point, PolyFile, PolyObject
from hydrolib.core.dflowfm.xyz.models import XYZModel, XYZPoint


def write_xyz(path: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> XYZModel:
    """Write a sample (.xyz) file and return the parsed model (for validation)."""
    model = XYZModel(
        points=[
            XYZPoint(x=float(xi), y=float(yi), z=float(zi))
            for xi, yi, zi in zip(x, y, z)
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    model.filepath = path
    model.save(filepath=path)
    return XYZModel(filepath=path)


def collocated_sample_field(
    quantity: str,
    path: Path,
    face_x: np.ndarray,
    face_y: np.ndarray,
    value_func: Callable[[np.ndarray, np.ndarray], np.ndarray],
    margin: float = 0.0,
    y_jitter: float = 0.0,
    extrapolate: bool = True,
) -> InitialField:
    """Build an ``[Initial]`` field sampled exactly at the given cell centers.

    Args:
        quantity: D-Flow FM initial-field quantity name (e.g. ``"waterlevel"``,
            ``"initialvelocityx"``); see UM Table D.2.
        path: Output path of the ``.xyz`` sample file.
        face_x, face_y: Cell-center coordinates (typically ``FlumeGrid.face_x/y``)
            at which the analytic value is evaluated and stored.
        value_func: ``value = value_func(x, y)`` analytic field.
        margin: If > 0, additionally place samples at ``face_x`` shifted by
            ``+-margin`` in x (only) to stabilize triangulation/extrapolation
            right at the domain edges. Not needed for interior cells.
        y_jitter: If > 0, additionally place samples at ``face_y`` shifted by
            ``+-y_jitter``. **Required** for single-row "flume" grids (every
            cell sharing one ``face_y``, e.g. ``linear_seiche``,
            ``thacker_basin``): a real dflowfm run confirmed that a perfectly
            collinear sample set (constant y) makes the requested
            ``interpolationMethod=triangulation`` degenerate -- Delaunay
            triangulation cannot form any triangle from colinear points, so
            every query point falls outside all (zero) triangles and D-Flow FM
            silently keeps the global default initial water level (flat
            ``waterLevIni=0.0``) instead of applying this field at all (no
            error/warning beyond the generic, always-printed "merged N
            samples" duplicate-removal message, which is unrelated -- see
            ``rmdouble.f90`` -- and is not itself diagnostic of this). Adding
            a second (and third) row of samples at ``+-y_jitter``, evaluating
            ``value_func`` at those exact (x, y) coordinates rather than
            duplicating the on-row value, keeps the field exact even if a
            future case's ``value_func`` does depend on ``y``, while giving
            triangulation the non-degenerate 2D point set it needs. Verified
            against a real run: without this, ``linear_seiche`` and
            ``thacker_basin`` both silently simulated a flat lake at rest
            (zero velocity for the entire run); with it, both show genuine
            oscillation.
        extrapolate: Whether to set ``extrapolationMethod=1``. Defaults to
            ``True`` (matching this suite's original choice, "to avoid
            falling back to a default value" at domain-edge cells). Set to
            ``False`` when every single flow node already has its own exact
            collocated sample (true of every case using this helper, since
            samples are written at ``face_x``/``face_y`` themselves) *and*
            the field has a genuine dry region (``thacker_basin``): a real
            run showed extrapolation bleeding small (0.005-0.02 m) spurious
            positive depths into cells beyond the true analytic shoreline
            (bed_level-exact, zero-depth samples there), i.e. artificially
            "pre-wetting" part of the dry zone at t=0 and contaminating the
            wetting/drying test this case exists to exercise. With a
            complete, exact, per-cell sample set there is no cell left for
            extrapolation to legitimately fill in, so disabling it removes
            this artifact without losing any coverage.

    Returns:
        InitialField pointing at the written sample file with
        ``interpolationMethod=triangulation`` and extrapolation as given.
    """
    x = np.asarray(face_x, dtype=np.float64)
    y = np.asarray(face_y, dtype=np.float64)
    if margin:
        x = np.concatenate([x - margin, x, x + margin])
        y = np.concatenate([y, y, y])
    if y_jitter:
        x = np.concatenate([x, x, x])
        y = np.concatenate([y - y_jitter, y, y + y_jitter])
    z = value_func(x, y)
    write_xyz(path, x, y, z)
    return InitialField(
        quantity=quantity,
        datafile=str(path.name),
        datafiletype=DataFileType.sample,
        interpolationmethod=InterpolationMethod.triangulation,
        extrapolationmethod=extrapolate,
    )


def write_polygon(
    path: Path, points: Sequence[tuple[float, float]], name: str = "region"
) -> PolyFile:
    """Write a closed polygon (.pol) file from a list of (x, y) vertices.

    The polygon is closed automatically (first point repeated at the end) if
    the caller did not already close it.
    """
    pts = list(points)
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    obj = PolyObject(
        metadata=Metadata(name=name, n_rows=len(pts), n_columns=2),
        points=[Point(x=float(px), y=float(py), data=[]) for px, py in pts],
    )
    model = PolyFile(has_z_values=False, objects=[obj])
    path.parent.mkdir(parents=True, exist_ok=True)
    model.filepath = path
    model.save(filepath=path)
    return PolyFile(filepath=path)


def write_polyline(
    path: Path, points: Sequence[tuple[float, float]], name: str = "boundary"
) -> PolyFile:
    """Write an open polyline (.pli) file, e.g. for a boundary condition."""
    obj = PolyObject(
        metadata=Metadata(name=name, n_rows=len(points), n_columns=2),
        points=[Point(x=float(px), y=float(py), data=[]) for px, py in points],
    )
    model = PolyFile(has_z_values=False, objects=[obj])
    path.parent.mkdir(parents=True, exist_ok=True)
    model.filepath = path
    model.save(filepath=path)
    return PolyFile(filepath=path)


def polygon_value_field(
    quantity: str, polygon_path: Path, value: float
) -> InitialField:
    """Build an ``[Initial]`` field that sets ``value`` everywhere inside a polygon."""
    return InitialField(
        quantity=quantity,
        datafile=str(polygon_path.name),
        datafiletype=DataFileType.polygon,
        interpolationmethod=InterpolationMethod.constant,
        value=value,
    )
