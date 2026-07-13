"""Common D-Flow FM .mdu settings shared by all verification cases.

The numerics/physics defaults mirror the bundled public example
(baseline_artifacts/deltares-examples/extracted/examples/01_dflowfm_sequential/dflowfm/f34.mdu)
wherever this suite has no case-specific reason to deviate, so that any
discrepancy against the analytic solution can be attributed to the physics
under test rather than to an unusual numerical configuration. Deviations
(documented inline) are: no Coriolis/tides/wind/salinity (irrelevant, and
would break the closed-form solutions), and friction is set explicitly per
case (0 for the frictionless cases, Manning for normal_depth_channel).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from hydrolib.core.dflowfm.mdu.models import FMModel
from hydrolib.core.dflowfm.net.models import Network, NetworkModel


def round_up_to_multiple(value: float, step: float, rel_tol: float = 1.0e-9) -> float:
    """Round ``value`` up to the nearest exact multiple of ``step``.

    D-Flow FM's runtime input validation (``check_time_interval`` in
    ``dflowfm_data/unstruc_model.f90``) requires every His/Map output
    interval's step *and* its ``(End - TStart)``/``(Start - TStart)`` span to
    be an exact multiple of ``DtUser`` (``model.time.dtuser``, itself set to
    ``min(his_interval, map_interval)`` in :func:`make_base_model`) -- not a
    hydrolib-core-level constraint, so it was never caught by this suite's
    generate-time round-trip checks, only by a real ``dflowfm`` run (see
    README "Smoke-test result" / verification-case Linux run notes). Cases
    whose ``TSTOP`` is derived from an irrational physical period (e.g.
    ``linear_seiche``'s ``2*L/sqrt(g*H0)``, ``thacker_basin``'s
    ``2*pi/omega``) must snap it to a ``DtUser`` multiple with this helper
    before handing it to :func:`make_base_model`. Rounding *up* (never down)
    preserves each case's "simulate at least N_PERIODS periods" intent;
    comparators in this suite locate analysis times by nearest-sample lookup
    or count actual zero-crossings, so a few extra milliseconds/seconds of
    runtime past the nominal target does not affect correctness.

    The ``rel_tol`` nudge avoids `math.ceil` landing one multiple too high
    purely from floating-point representation error when ``value`` is
    already (numerically very close to) an exact multiple.
    """
    n = math.ceil(value / step - rel_tol)
    return n * step


def make_base_model(
    network: Network,
    net_filename: str,
    tstop: float,
    dtmax: float = 1.0,
    dtinit: float = 0.01,
    his_interval: float = 10.0,
    map_interval: float = 10.0,
    uniffrictcoef: float = 0.0,
    uniffricttype: int = 0,
    waterlevini: Optional[float] = None,
    cflmax: float = 0.7,
    epshu: float = 1.0e-4,
    output_dir: str = "dflowfmoutput",
) -> FMModel:
    """Build an FMModel with the settings shared by every verification case.

    Args:
        network: The already-built ``hydrolib.core...Network`` (e.g.
            ``FlumeGrid.network`` from :func:`common.grid.build_rectilinear_grid`).
            Passed in directly (not just a file path) and wrapped in a fresh
            ``NetworkModel`` here, because ``FMModel()`` otherwise defaults
            ``geometry.netfile`` to an *empty* ``NetworkModel`` -- assigning
            only its ``.filepath`` would make ``model.save()`` silently
            overwrite an already-written, populated net file with an empty
            one.
        net_filename: Filename (not path) the net file is saved as, next to
            the .mdu.
        tstop: Simulation end time [s].
        dtmax: Maximum (and, since AutoTimestep=1, initial-guess-ceiling)
            timestep [s].
        dtinit: Initial timestep [s].
        his_interval: History (time-series) output interval [s].
        map_interval: Map (spatial) output interval [s].
        uniffrictcoef: Uniform friction coefficient (0 = frictionless).
        uniffricttype: 0=Chezy, 1=Manning (see UM Sec.A.3, [physics] UnifFrictType).
        waterlevini: Uniform initial water level [m]; leave None when a case
            supplies its own spatially varying initial field instead.
        cflmax: Maximum Courant number (AutoTimestep=1 uses this to pick dt).
        epshu: Threshold water depth for wetting/drying [m] (epsHu). Kept at
            the hydrolib/D-Flow FM default (1e-4 m) unless a case overrides
            it explicitly (see thacker_basin, where drying is the point).
        output_dir: Name of the output subdirectory, created by D-Flow FM.

    Returns:
        A fully-formed FMModel; the caller still needs to set
        ``model.filepath`` and call ``model.save()``, and typically still
        needs to attach ``geometry.inifieldfile`` and/or
        ``external_forcing.extforcefilenew`` for the case-specific initial
        and boundary conditions.
    """
    model = FMModel()

    # NB: NetworkModel(network=network, filepath=...) would NOT work here --
    # passing filepath directly to the constructor makes hydrolib try to
    # *load* (parse) an existing file at that path immediately, which fails
    # (it doesn't exist yet). Constructing empty and assigning both
    # attributes afterwards avoids that eager-load path.
    netfile = NetworkModel()
    netfile.network = network
    netfile.filepath = Path(net_filename)
    model.geometry.netfile = netfile
    model.geometry.bedlevtype = 3  # mean network-node levels -> link -> flow node
    if waterlevini is not None:
        model.geometry.waterlevini = waterlevini

    # No Coriolis/tides/wind/salinity: keep the physics restricted to the
    # shallow-water core so the analytic solutions apply unmodified.
    # (tidalforcing/salinity already default to False in hydrolib-core.)
    model.geometry.anglat = 0.0
    model.physics.uniffrictcoef = uniffrictcoef
    model.physics.uniffricttype = uniffricttype
    model.physics.ag = 9.81  # matches the g=9.81 used throughout the README derivations

    model.numerics.cflmax = cflmax
    model.numerics.epshu = epshu
    model.numerics.icgsolver = 4

    model.time.refdate = 20000101
    model.time.tunit = "S"
    model.time.dtuser = min(his_interval, map_interval)
    model.time.dtmax = dtmax
    model.time.dtinit = dtinit
    model.time.autotimestep = 1
    model.time.tstart = 0.0
    model.time.tstop = tstop

    model.output.outputdir = output_dir
    model.output.hisinterval = [his_interval]
    model.output.mapinterval = [map_interval]
    model.output.fullgridoutput = False

    # Callers attach geometry.inifieldfile / external_forcing.extforcefilenew
    # themselves, only when the case actually needs a spatial initial field
    # or an open boundary (lake_at_rest needs neither).
    return model
