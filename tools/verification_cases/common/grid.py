"""Rectilinear D-Flow FM grid generation for the analytic verification suite.

All cases in this suite use a single-block rectilinear ("flume" or "basin")
mesh built with meshkernel through hydrolib-core's ``Network`` wrapper. Bed
levels are assigned per *mesh node* (``mesh2d_node_z``) and written into the
UGRID net file; the .mdu selects ``BedLevType = 3`` ("bottom levels at
velocity points, using mean network levels"), matching the convention already
used by the bundled ``01_dflowfm_sequential`` example
(baseline_artifacts/deltares-examples/extracted/examples/01_dflowfm_sequential/dflowfm/f34.mdu).
D-Flow FM then derives cell-center (flow node) bed levels from the node
values automatically, so callers of this module never need to compute
face-based bed levels by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from hydrolib.core.dflowfm.net.models import Network, NetworkModel


@dataclass
class FlumeGrid:
    """A rectilinear mesh plus the geometric bookkeeping the cases need.

    Attributes:
        network: The hydrolib-core ``Network`` (mesh2d + bed levels).
        node_x, node_y, node_z: Node coordinates and bed level [m], in the
            mesh's native (meshkernel) node ordering.
        face_x, face_y: Cell-center (flow node) coordinates, in the mesh's
            native face ordering. These are the coordinates D-Flow FM map
            output reports variables at (``mesh2d_face_x/y``), so comparator
            scripts should key off these arrays, not a regenerated grid.
        nx, ny: Number of cells in x and y.
        dx, dy: Cell size in x and y [m].
    """

    network: Network
    node_x: np.ndarray
    node_y: np.ndarray
    node_z: np.ndarray
    face_x: np.ndarray
    face_y: np.ndarray
    nx: int
    ny: int
    dx: float
    dy: float


def build_rectilinear_grid(
    net_path: Path,
    length: float,
    width: float,
    dx: float,
    dy: float,
    bed_level: Callable[[np.ndarray, np.ndarray], np.ndarray],
) -> FlumeGrid:
    """Build a rectilinear mesh over ``[0, length] x [0, width]`` and save it.

    Args:
        net_path: Output path for the ``*_net.nc`` UGRID file.
        length: Domain extent in x [m].
        width: Domain extent in y [m].
        dx: Cell size in x [m]. ``length / dx`` must be (close to) an integer.
        dy: Cell size in y [m]. ``width / dy`` must be (close to) an integer.
        bed_level: Function ``z = bed_level(x, y)`` evaluated at mesh *nodes*
            (not cell centers), returning the bed level [m, positive up] as
            used by D-Flow FM's ``mesh2d_node_z``.

    Returns:
        FlumeGrid with the network already written to ``net_path``.
    """
    nx = round(length / dx)
    ny = round(width / dy)
    if not np.isclose(nx * dx, length, rtol=0, atol=1e-9):
        raise ValueError(f"length {length} is not an integer multiple of dx {dx}")
    if not np.isclose(ny * dy, width, rtol=0, atol=1e-9):
        raise ValueError(f"width {width} is not an integer multiple of dy {dy}")

    network = Network()
    network.mesh2d_create_rectilinear_within_extent(
        extent=(0.0, 0.0, length, width), dx=dx, dy=dy
    )

    node_x = network._mesh2d.mesh2d_node_x
    node_y = network._mesh2d.mesh2d_node_y
    node_z = bed_level(node_x, node_y).astype(np.float64)
    network._mesh2d.mesh2d_node_z = node_z

    face_x = network._mesh2d.mesh2d_face_x
    face_y = network._mesh2d.mesh2d_face_y

    net_path.parent.mkdir(parents=True, exist_ok=True)
    network.to_file(net_path)

    return FlumeGrid(
        network=network,
        node_x=node_x,
        node_y=node_y,
        node_z=node_z,
        face_x=face_x,
        face_y=face_y,
        nx=nx,
        ny=ny,
        dx=dx,
        dy=dy,
    )
