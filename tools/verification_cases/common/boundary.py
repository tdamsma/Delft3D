"""Constant open-boundary conditions (D-Flow FM new-style .ext + .bc + .pli).

Only ``normal_depth_channel`` needs open boundaries (every other case is a
closed basin), so this is kept deliberately minimal: one polyline, one
constant-in-time value, one boundary quantity.
"""

from __future__ import annotations

from pathlib import Path

from hydrolib.core.dflowfm.bc.models import Constant, ForcingModel, QuantityUnitPair
from hydrolib.core.dflowfm.ext.models import Boundary

from .fields import write_polyline


def constant_boundary(
    name: str,
    quantity: str,
    unit: str,
    value: float,
    y_points: tuple[float, float],
    x: float,
    pli_path: Path,
    bc_path: Path,
) -> Boundary:
    """Build a `[Boundary]` block with a constant value along a cross-section.

    Args:
        name: Unique name; must match between the .pli polyline label and the
            .bc [Forcing] block (D-Flow FM matches boundary polylines to
            forcing time series/constants by this name).
        quantity: D-Flow FM boundary quantity, e.g. ``"dischargebnd"`` or
            ``"waterlevelbnd"`` (see UM Sec. C.5.2.1, and
            src/engines_gpl/dflowfm/res/example_new.ext in this repo).
        unit: Physical unit string for the .bc quantityunitpair (``"m3/s"``,
            ``"m"``, ...).
        value: The constant value.
        y_points: (y_min, y_max) of the cross-section polyline; should extend
            slightly beyond the mesh width so the boundary line unambiguously
            crosses every net-boundary edge at this x.
        x: x-coordinate of the cross-section (0 or the channel length).
        pli_path: Output path for the polyline (.pli).
        bc_path: Output path for the forcing (.bc) file. If it already
            exists on disk it is extended (multiple boundaries commonly
            share one .bc file); the caller is responsible for writing it
            only once all boundaries have been added, via
            :func:`save_forcing_model`.

    Returns:
        The Boundary object (not yet attached to an ExtModel).
    """
    write_polyline(pli_path, [(x, y_points[0]), (x, y_points[1])], name=name)
    # D-Flow FM's runtime (not hydrolib-core -- this went undetected until a
    # real run) matches a .bc [Forcing] block to a polyline support point by
    # "<polyline_label>_0001" (0001 = first/only support point), *not* by
    # the bare polyline label alone (confirmed against
    # src/utils_lgpl/ec_module/.../ec_bcreader.f90's matchblock, and by
    # trial against a real run: bare "name" alone failed with "No signals
    # for polyline file ... found in ....bc" even though the .bc file
    # existed with the right quantity/value). One "_0001" block correctly
    # applies uniformly to every point on this 2-point (straight,
    # cross-channel) polyline.
    forcing = Constant(
        name=f"{name}_0001",
        quantityunitpair=[QuantityUnitPair(quantity=quantity, unit=unit)],
        datablock=[[value]],
    )
    forcing_model = ForcingModel(forcing=[forcing])
    forcing_model.filepath = bc_path
    # NB: must save explicitly here, unlike write_xyz/write_polyline/
    # write_polygon which all call .save() themselves -- a real run showed
    # that the top-level FMModel.save(recurse=True) in each case's
    # generate() does *not* cascade this deep (a ForcingModel nested inside
    # a Boundary inside an ExtModel.boundary list), silently leaving no .bc
    # file on disk at all and making dflowfm fail at "Start initializing
    # external forcings" with "No signals for polyline file ... found in
    # ....bc". Saving here (like the other write_* helpers do) makes this
    # helper self-contained and independent of that recursion behavior.
    forcing_model.save(filepath=bc_path)
    # Reset to a bare filename (matching locationfile=pli_path.name below)
    # *after* saving to the real bc_path: a real run showed that whatever
    # path sits in forcing_model.filepath at the time the enclosing
    # ExtModel/Boundary is serialized is written verbatim into the .ext
    # file's forcingFile= value. Since generate() is called with an
    # out_dir like "baseline_runs/verification/normal_depth_channel" (not
    # "."), leaving filepath=bc_path there baked that whole relative path
    # into the .ext file. D-Flow FM resolves forcingFile relative to the
    # run directory (its cwd when invoked "from inside" the case dir, per
    # run_all.py/README), so it then looked for
    # "<rundir>/baseline_runs/verification/normal_depth_channel/upstream.bc"
    # -- doubling the path and never finding the (correctly-placed) file,
    # failing with "No signals for polyline file ... found in ....bc".
    forcing_model.filepath = Path(bc_path.name)
    boundary = Boundary(
        quantity=quantity,
        locationfile=pli_path.name,
        forcingfile=forcing_model,
    )
    return boundary
