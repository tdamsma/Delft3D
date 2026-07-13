#!/usr/bin/env python3
"""Generate the "L" (large, memory-resident) D-Flow FM benchmark model.

Default mode ("synthetic"): a long, meandering rectilinear tidal channel
(pure-quad mesh) with a realistic 2D bathymetric gradient (sloped
sea-to-head bed, a meandering deeper thalweg, shallower banks) and the exact
same open-boundary forcing as the public Western Scheldt example (example
02): a Fourier/tidal water level at the sea end, a constant discharge at the
river end. Cell count is controlled directly and exactly via --cells (a
rectilinear nx*ny grid), so --cells 140000 and --cells 576000 give *exactly*
those cell counts, unlike mesh-refinement-based sizing.

Why not refine the real Western Scheldt mesh (the first approach tried)?
See "Western Scheldt refinement: what was tried and why it's blocked" below
-- short version: meshkernel refines it fine, but the refined mesh crashes
dflowfm via a pre-existing (gfortran-only) allocation-guard bug in
gridoperations.F90, unrelated to and out of scope for this generator (no
source changes permitted for this task). The synthetic channel is the
explicitly sanctioned fallback ("a synthetic-but-honest bandwidth
workload is acceptable if Western Scheldt refinement proves impractical").

Usage:
    python generate_l_model.py --cells 140000 --out-dir baseline_runs/l-tier/mid
    python generate_l_model.py --cells 576000 --out-dir baseline_runs/l-tier/large
    python generate_l_model.py --mode western-scheldt --refine-passes 4 --dry-run
        # mesh-only size probe for the blocked approach, see below.

Run with the baseline_tools/dfm-validation Python environment (meshkernel
8.3.0, hydrolib-core, xarray, scipy -- see tools/verification_cases/common
for the shared hydrolib-core conventions this script reuses).

--------------------------------------------------------------------------
Western Scheldt refinement: what was tried and why it's blocked
--------------------------------------------------------------------------
The first approach tried was to refine the public Western Scheldt mesh
(example 02, 8,355 cells) with meshkernel. That part works cleanly:

- The mesh ships in D-Flow FM's *old* net-file convention (NetNode_x/y/z,
  NetLink, NetElemNode), not UGRID -- hydrolib-core's Network.from_file
  silently returns an *empty* mesh on it (confirmed by a real read). But
  meshkernel doesn't care about UGRID either; it only needs node
  coordinates + an edge-node array, and NetLink already *is* that (1-based;
  `edge_nodes = NetLink - 1`).
- meshkernel's Casulli refinement (mesh2d_casulli_refinement) refines this
  mesh deterministically, no auxiliary sample grid needed: measured growth
  8,355 -> 34,993 -> 142,652 -> 576,457 -> 2,317,529 cells for passes 1-4 on
  this exact mesh -- almost exactly the expected ~4x-per-pass curve.
  generate_refined_network()/build_western_scheldt_network() below implement
  this and it runs in seconds even at 2.3M cells.

The blocker is downstream: running dflowfm on *any* Casulli-refined output
(even a single pass, 34,993 cells) crashes during initialization:

    Fortran runtime error: Attempting to allocate already allocated
    variable 'kck'
    (src/utils_lgpl/gridgeom/packages/gridgeom/src/gridoperations.F90:783)

This is the same *class* of bug already fixed elsewhere in this exact file
on this branch (commit 109999b35a, "fix: utils_lgpl disassociated-pointer/
unallocated-allocatable guards"): an allocate() with no `if (allocated(...))`
guard, harmless on ifx/Linux but fatal under gfortran's stricter runtime
checks. `kck` is allocated unconditionally a few lines below a sibling `kc`
array that *does* have such a guard.

Diagnosis performed (summarized here since it's not reproducible without a
debugger, which this sandboxed environment does not permit attaching):
- Ruled out sheer mesh size: a from-scratch 144,400-cell all-quad
  rectilinear mesh (tools/verification_cases/common/grid.py) runs cleanly.
- The original (unrefined) Western Scheldt mesh, round-tripped through this
  exact meshkernel-to-hydrolib-UGRID pipeline with *zero* refinement passes,
  also runs cleanly -- so the pipeline itself is not the problem.
- The crash appears starting at the *first* Casulli pass. That mesh has a
  small number (out of ~35k) of quality artifacts introduced by refining a
  mesh that already mixes triangles and quads: ~90 faces with 5 or 6 nodes
  (vs. only tri/quad in the original), a handful of near-duplicate node
  pairs (~0.2-0.03 m apart) and one exactly-zero-area sliver quad.
- Mitigated with meshkernel post-processing (mesh2d_merge_nodes_with_
  merging_distance to fuse near-duplicate nodes up to 5 m apart, plus
  fan-triangulating every face with >4 nodes via mesh2d_insert_edge): this
  measurably improved mesh quality (eliminated the zero-area cell and all
  sub-10 m^2 faces, reduced 5/6-sided faces) but did *not* eliminate the
  crash -- strongly suggesting either additional undiagnosed degeneracies or
  (more likely, given the fix required for the sibling `kc` bug) a node
  administration/valence issue that isn't visible from face geometry alone.
- Fixing the actual bug means patching gridoperations.F90's `kck` allocation
  the same way its `kc` neighbor already was -- a one-line, well-precedented
  fix, but a *source* change, which this benchmark-generation task is
  explicitly scoped not to make. Left for future work with that permission.

The mesh-generation code for this path is kept below (build_western_scheldt_
network(), --mode western-scheldt) since it works and may be useful once the
source fix lands -- but it is *not* the default and its output is *not*
verified to run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr

L_TIER_DIR = Path(__file__).resolve().parent
VERIFICATION_COMMON_DIR = L_TIER_DIR.parent.parent / "verification_cases"
sys.path.insert(0, str(VERIFICATION_COMMON_DIR))

from common.fields import write_polyline  # noqa: E402
from common.grid import build_rectilinear_grid  # noqa: E402
from common.mdu_base import make_base_model, round_up_to_multiple  # noqa: E402

import meshkernel as mk  # noqa: E402
from hydrolib.core.base.models import DiskOnlyFileModel  # noqa: E402
from hydrolib.core.dflowfm.net.models import Network  # noqa: E402

REPO_ROOT = L_TIER_DIR.parent.parent.parent
EXAMPLE_02_DIR = (
    REPO_ROOT
    / "baseline_artifacts/deltares-examples/extracted/examples/02_dflowfm_parallel/dflowfm"
)
DEFAULT_SOURCE_NET = EXAMPLE_02_DIR / "westerscheldt_net.nc"

# The exact Fourier/constant boundary signal from example 02's
# boundarysea_0001.cmp / boundaryriver_0001.cmp, reused verbatim (same
# tidal forcing) for the synthetic channel's sea/river cross-sections.
SEA_CMP_LINES = [
    "* COLUMNN=3",
    "* COLUMN1=Period (min) or Astronomical Componentname",
    "* COLUMN2=Amplitude (ISO)",
    "* COLUMN3=Phase (deg)",
    "  0.0  0.5  0.0",
    "745.0  2.0  0.0",
]
RIVER_CMP_LINES = [
    "* COLUMNN=3",
    "* COLUMN1=Period (min) or Astronomical Componentname",
    "* COLUMN2=Amplitude (ISO)",
    "* COLUMN3=Phase (deg)",
    "  0.0  2500.0  0.0",
]
EXT_TEMPLATE = """\
* Old-format external forcing, boundary conditions reused verbatim from
* baseline_artifacts/deltares-examples/extracted/examples/02_dflowfm_parallel
* (same tidal sea-level Fourier signal, same constant river discharge).
QUANTITY=waterlevelbnd
FILENAME=sea.pli
FILETYPE=9
METHOD=3
OPERAND=O

QUANTITY=dischargebnd
FILENAME=river.pli
FILETYPE=9
METHOD=3
OPERAND=O
"""

M2_LIKE_PERIOD_S = 745.0 * 60.0  # matches *_0001.cmp's 745 min component

# Default simulation length: 900 s (0.25 h). Calibrated on the M3 Ultra
# (2026-07-11; another process was benchmarking concurrently, so indicative):
# the 576,000-cell tier runs 900 sim-s in ~13 min single-threaded and
# ~7.5 min with OMP_NUM_THREADS=8 -- comfortably past the
# ">= several minutes so profiles are stable" floor on ~8 cores, without
# making N>=5 harness repeats impractical. For long profiling runs, pass
# --tstop-hours 12.416667 (one full tidal period of the boundary forcing,
# M2_LIKE_PERIOD_S) or anything in between.
DEFAULT_TSTOP_HOURS = 0.25

# Measured on the real Western Scheldt mesh (see module docstring): Casulli
# refinement passes 1-4 give 34,993 / 142,652 / 576,457 / 2,317,529 faces.
MAX_PASSES_DEFAULT = 4


@dataclass
class NetworkSpec:
    """A generated D-Flow FM mesh + bookkeeping, uniform across both modes."""

    network: Network
    n_nodes: int
    n_faces: int
    extra_meta: dict


# ---------------------------------------------------------------------------
# Default (verified) mode: synthetic meandering tidal channel
# ---------------------------------------------------------------------------


def _channel_bed_level(length: float, width: float):
    """Bed level [m] with a genuine 2D gradient: sloped sea (deep, x=0) to
    river (shallow, x=length), a meandering deeper thalweg, and shallower
    banks -- deliberately not separable in x/y, so it exercises the same
    kind of spatially-varying coefficient fields (bed slope terms, wetted
    cross-sections) a real estuary model would, rather than a trivial flat
    or purely-1D bed.
    """
    depth_sea = 20.0
    depth_river = 3.0
    bank_relief = 4.0  # thalweg-to-bank depth difference
    meander_wavelength = length / 3.0
    meander_amplitude = 0.15 * width

    def bed_level(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        slope = depth_sea - (depth_sea - depth_river) * (x / length)
        centerline = width / 2.0 + meander_amplitude * np.sin(2.0 * np.pi * x / meander_wavelength)
        cross = bank_relief * np.cos(np.pi * np.clip((y - centerline) / width, -0.5, 0.5))
        return -(slope - cross)

    return bed_level


def build_synthetic_channel_network(
    net_path: Path, target_cells: int, width: float = 2000.0, dx: float = 10.0
) -> NetworkSpec:
    """Build a rectilinear meandering-channel mesh at (approximately) the
    requested cell count.

    ny is fixed by width/dx; nx is chosen so nx*ny is as close to
    target_cells as possible (exact whenever target_cells is a multiple of
    ny, which is how both committed tiers -- 140,000 and 576,000 -- were
    chosen: ny=200 divides both exactly).
    """
    ny = round(width / dx)
    nx = max(1, round(target_cells / ny))
    length = nx * dx
    width_exact = ny * dx

    grid = build_rectilinear_grid(
        net_path=net_path,
        length=length,
        width=width_exact,
        dx=dx,
        dy=dx,
        bed_level=_channel_bed_level(length, width_exact),
    )
    return NetworkSpec(
        network=grid.network,
        n_nodes=len(grid.node_x),
        n_faces=grid.nx * grid.ny,
        extra_meta={"length_m": length, "width_m": width_exact, "dx_m": dx, "nx": grid.nx, "ny": grid.ny},
    )


def write_synthetic_boundary_files(out_dir: Path, width: float) -> list[str]:
    """Write sea.pli/river.pli (straight cross-channel lines, slightly
    beyond the mesh width per OpenBoundaryTolerance convention) and their
    *_0001.cmp Fourier/constant signal files (example 02's exact values)."""
    margin = 0.1 * width
    write_polyline(out_dir / "sea.pli", [(0.0, -margin), (0.0, width + margin)], name="sea")
    write_polyline(
        out_dir / "river.pli",
        [(_synthetic_length_holder["length"], -margin), (_synthetic_length_holder["length"], width + margin)],
        name="river",
    )
    (out_dir / "sea_0001.cmp").write_text("\n".join(SEA_CMP_LINES) + "\n")
    (out_dir / "river_0001.cmp").write_text("\n".join(RIVER_CMP_LINES) + "\n")
    return ["sea.pli", "sea_0001.cmp", "river.pli", "river_0001.cmp"]


# module-level scratch used only to pass length into write_synthetic_boundary_files
# without complicating its call sites in main(); set right before the call.
_synthetic_length_holder: dict = {"length": None}


# ---------------------------------------------------------------------------
# Experimental / blocked mode: real Western Scheldt mesh + Casulli refinement
# (mesh generation works; running the result in dflowfm does not -- see the
# module docstring "Western Scheldt refinement" section)
# ---------------------------------------------------------------------------


def _load_old_format_net_arrays(net_path: Path):
    """Read node coordinates/levels and edge connectivity from an *old-format*
    D-Flow FM net file (NetNode_x/y/z, NetLink), bypassing hydrolib-core's
    UGRID reader (which silently returns an empty mesh on this convention)."""
    ds = xr.open_dataset(net_path)
    node_x = ds["NetNode_x"].values.astype(np.float64)
    node_y = ds["NetNode_y"].values.astype(np.float64)
    node_z = ds["NetNode_z"].values.astype(np.float64)
    edge_nodes = (ds["NetLink"].values.astype(np.int32) - 1).ravel()
    ds.close()
    return node_x, node_y, node_z, edge_nodes


def _interpolate_bathymetry(src_x, src_y, src_z, dst_x, dst_y):
    from scipy.interpolate import griddata

    src_pts = np.column_stack([src_x, src_y])
    dst_pts = np.column_stack([dst_x, dst_y])
    z_linear = griddata(src_pts, src_z, np.column_stack([dst_x, dst_y]), method="linear")
    n_nan = int(np.isnan(z_linear).sum())
    if n_nan:
        z_nearest = griddata(src_pts, src_z, dst_pts, method="nearest")
        z_linear = np.where(np.isnan(z_linear), z_nearest, z_linear)
    return z_linear, n_nan


def build_western_scheldt_network(
    source_net: Path,
    target_cells: int | None,
    max_passes: int = MAX_PASSES_DEFAULT,
    explicit_passes: int | None = None,
) -> NetworkSpec:
    """EXPERIMENTAL -- mesh generation only, see module docstring: dflowfm
    crashes on this mesh's output (pre-existing gfortran-only gridgeom bug,
    not fixable within this task's no-source-changes constraint)."""
    node_x, node_y, node_z, edge_nodes = _load_old_format_net_arrays(source_net)

    network = Network()
    network._mesh2d._set_mesh2d(node_x, node_y, edge_nodes)
    kernel = network._mesh2d.meshkernel

    passes = 0
    n_faces = len(kernel.mesh2d_get().face_x)
    while True:
        if explicit_passes is not None:
            if passes >= explicit_passes:
                break
        else:
            if target_cells is not None and n_faces >= target_cells:
                break
            if passes >= max_passes:
                break
        kernel.mesh2d_casulli_refinement()
        passes += 1
        n_faces = len(kernel.mesh2d_get().face_x)

    mesh2d = kernel.mesh2d_get()
    z_final, n_nan = _interpolate_bathymetry(node_x, node_y, node_z, mesh2d.node_x, mesh2d.node_y)
    if n_nan:
        print(
            f"  bathymetry: {n_nan}/{len(z_final)} refined nodes fell outside the "
            "source convex hull, filled by nearest-neighbour",
            file=sys.stderr,
        )
    network._mesh2d.mesh2d_node_z = z_final.astype(np.float64)

    return NetworkSpec(
        network=network,
        n_nodes=len(mesh2d.node_x),
        n_faces=len(mesh2d.face_x),
        extra_meta={"refine_passes": passes},
    )


# ---------------------------------------------------------------------------
# Shared MDU construction
# ---------------------------------------------------------------------------


def build_mdu(
    spec: NetworkSpec,
    out_dir: Path,
    stem: str,
    tstop_s: float,
    his_interval_s: float,
    map_interval_s: float,
    ext_text: str,
):
    net_filename = f"{stem}_net.nc"

    model = make_base_model(
        network=spec.network,
        net_filename=net_filename,
        tstop=tstop_s,
        dtmax=60.0,  # matches example 02's DtMax
        dtinit=1.0,  # matches example 02's DtInit
        his_interval=his_interval_s,
        map_interval=map_interval_s,
        uniffrictcoef=2.3e-2,
        uniffricttype=1,  # Manning, matches example 02
        waterlevini=0.5,  # matches example 02's WaterLevIni
        cflmax=0.7,
        epshu=1.0e-4,
        output_dir="dflowfmoutput",
    )

    # Solver: SobekGS_OMPthreadsafe, matches example 02's sequential Icgsolver
    # (the M-tier's MPI variant instead uses icgsolver=6 at partition time;
    # the L-tier is sequential/OpenMP-threaded only, by design for this
    # tier).
    model.numerics.icgsolver = 2
    # turbulencemodel/turbulenceadvection (k-eps) and bedlevuni (-5.0) already
    # default to example 02's values in this hydrolib-core version -- no
    # override needed (verified against the FMModel field defaults).

    # Minimize output: benchmarks want compute, not I/O (Sec. 6a). Keep only
    # water level + velocity (enough to eyeball a NaN/blow-up), drop the
    # heavier per-cell diagnostic fields example 02 enables (turbulence,
    # viscosity/diffusivity, chezy, spiral flow, numlimdt, tau, density,
    # wind, tidal potential terms).
    out = model.output
    for flag in (
        "wrimap_velocity_component_u0",
        "wrimap_density_rho",
        "wrimap_horizontal_viscosity_viu",
        "wrimap_horizontal_diffusivity_diu",
        "wrimap_flow_flux_q1",
        "wrimap_spiral_flow",
        "wrimap_numlimdt",
        "wrimap_taucurrent",
        "wrimap_chezy",
        "wrimap_turbulence",
        "wrimap_wind",
        "wrimap_tidal_potential",
        "wrimap_sal_potential",
        "wrimap_internal_tides_dissipation",
        "wrimap_calibration",
    ):
        setattr(out, flag, False)
    out.wrihis_balance = True  # cheap (one scalar time series), useful for mass-conservation sanity

    out_dir.mkdir(parents=True, exist_ok=True)
    model.filepath = out_dir / f"{stem}.mdu"

    # Old-format external forcing (.ext): DiskOnlyFileModel is hydrolib-core's
    # disk-passthrough for file formats it has no structured model for (the
    # old .ext format qualifies) -- see tools/verification_cases/common/
    # boundary.py's forcing_model.save() precedent for why the explicit
    # save-then-reset-to-bare-name dance is needed: whatever path sits in
    # .filepath when the *parent* FMModel is serialized is what ends up
    # (verbatim) in ExtForceFile=, so a temporary absolute path must not
    # still be there at save time.
    ext_target = out_dir / f"{stem}.ext"
    ext_target.write_text(ext_text)
    dof = DiskOnlyFileModel(filepath=ext_target)
    dof.save(filepath=ext_target)  # source == target here; a safe no-op copy
    dof.filepath = Path(ext_target.name)
    model.external_forcing.extforcefile = dof

    model.save(recurse=True)

    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--mode",
        choices=["synthetic", "western-scheldt"],
        default="synthetic",
        help="synthetic (default, verified): meandering rectilinear channel. "
        "western-scheldt (experimental, NOT verified to run in dflowfm): "
        "Casulli-refine the real Western Scheldt mesh -- see module docstring.",
    )
    parser.add_argument("--cells", type=int, default=None, help="Target cell count. synthetic: exact (nx*ny). western-scheldt: approximate, snapped up to the nearest Casulli refinement level.")
    parser.add_argument("--refine-passes", type=int, default=None, help="[western-scheldt only] explicit number of Casulli refinement passes (overrides --cells).")
    parser.add_argument("--max-passes", type=int, default=MAX_PASSES_DEFAULT, help="[western-scheldt only] upper bound on refinement passes when using --cells (default: %(default)s).")
    parser.add_argument("--width-m", type=float, default=2000.0, help="[synthetic only] channel width [m] (default: %(default)s).")
    parser.add_argument("--dx-m", type=float, default=10.0, help="[synthetic only] cell size [m] (default: %(default)s).")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory for the generated model (required unless --dry-run).")
    parser.add_argument("--stem", type=str, default="l_tier", help="Base filename stem for the .mdu/_net.nc (default: %(default)s).")
    parser.add_argument("--tstop-hours", type=float, default=DEFAULT_TSTOP_HOURS, help="Simulation length in hours (default: %(default)s h = 900 s, calibrated so the 576k tier runs >=5 min on ~8 cores; pass 12.416667 for one full boundary-forcing tidal period).")
    parser.add_argument("--his-interval-s", type=float, default=300.0, help="History output interval [s] (default: %(default)s).")
    parser.add_argument("--map-interval-s", type=float, default=None, help="Map output interval [s] (default: ~1/4 of TStop, snapped to a His-interval multiple).")
    parser.add_argument("--source-net", type=Path, default=DEFAULT_SOURCE_NET, help="[western-scheldt only] source (old-format) net.nc to refine.")
    parser.add_argument("--dry-run", action="store_true", help="Only report the resulting mesh size, write nothing to disk.")
    args = parser.parse_args()

    if not args.dry_run and args.out_dir is None:
        parser.error("--out-dir is required unless --dry-run")

    t0 = time.time()
    if args.mode == "western-scheldt":
        print(f"[EXPERIMENTAL/blocked, see docstring] Refining {args.source_net.name} ...", file=sys.stderr)
        spec = build_western_scheldt_network(
            source_net=args.source_net,
            target_cells=args.cells,
            max_passes=args.max_passes,
            explicit_passes=args.refine_passes,
        )
        gen_time = time.time() - t0
        print(
            f"  -> {spec.extra_meta['refine_passes']} Casulli pass(es): {spec.n_nodes} nodes, "
            f"{spec.n_faces} faces (mesh refinement took {gen_time:.1f}s)",
            file=sys.stderr,
        )
    else:
        if args.cells is None:
            parser.error("--cells is required in synthetic mode")
        print(f"Building synthetic channel for ~{args.cells} cells ...", file=sys.stderr)
        if args.out_dir is not None:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            net_path = args.out_dir / f"{args.stem}_net.nc"
        else:
            dry_run_tmp = tempfile.TemporaryDirectory()
            net_path = Path(dry_run_tmp.name) / f"{args.stem}_net.nc"
        spec = build_synthetic_channel_network(
            net_path=net_path,
            target_cells=args.cells,
            width=args.width_m,
            dx=args.dx_m,
        )
        gen_time = time.time() - t0
        print(
            f"  -> {spec.extra_meta['nx']}x{spec.extra_meta['ny']} cells = {spec.n_faces} faces, "
            f"{spec.extra_meta['length_m']:.0f}m x {spec.extra_meta['width_m']:.0f}m "
            f"(mesh generation took {gen_time:.1f}s)",
            file=sys.stderr,
        )

    if args.dry_run:
        print(json.dumps({"mode": args.mode, "n_nodes": spec.n_nodes, "n_faces": spec.n_faces, **spec.extra_meta}))
        return 0

    tstop_s_raw = args.tstop_hours * 3600.0
    his_interval_s = args.his_interval_s
    map_interval_s = args.map_interval_s
    if map_interval_s is None:
        map_interval_s = round_up_to_multiple(tstop_s_raw / 4.0, his_interval_s)
    map_interval_s = max(map_interval_s, his_interval_s)
    # DtUser (= min(his_interval, map_interval), set by make_base_model) must
    # evenly divide TStop -- see common/mdu_base.py's round_up_to_multiple
    # docstring for why this is a real dflowfm runtime check, not just a
    # hydrolib-core one.
    dtuser = min(his_interval_s, map_interval_s)
    tstop_s = round_up_to_multiple(tstop_s_raw, dtuser)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "synthetic":
        _synthetic_length_holder["length"] = spec.extra_meta["length_m"]
        aux = write_synthetic_boundary_files(args.out_dir, width=spec.extra_meta["width_m"])
        ext_text = EXT_TEMPLATE
    else:
        # western-scheldt mode still needs its boundary files; reused
        # verbatim from example 02 (geometry unaffected by refinement).
        aux_source_dir = args.source_net.parent
        aux = []
        for name in ("boundarysea.pli", "boundarysea_0001.cmp", "boundaryriver.pli", "boundaryriver_0001.cmp"):
            shutil.copy(aux_source_dir / name, args.out_dir / name)
            aux.append(name)
        # Filenames already match (boundarysea.pli/boundaryriver.pli), so the
        # original .ext content is valid verbatim -- no rewriting needed.
        ext_text = (aux_source_dir / "westerscheldt.ext").read_text()

    model = build_mdu(
        spec=spec,
        out_dir=args.out_dir,
        stem=args.stem,
        tstop_s=tstop_s,
        his_interval_s=his_interval_s,
        map_interval_s=map_interval_s,
        ext_text=ext_text,
    )

    meta = {
        "generated_by": "tools/benchmarks/l_tier/generate_l_model.py",
        "mode": args.mode,
        "n_nodes": spec.n_nodes,
        "n_faces": spec.n_faces,
        "tstop_s": tstop_s,
        "tstop_hours": tstop_s / 3600.0,
        "his_interval_s": his_interval_s,
        "map_interval_s": map_interval_s,
        "mesh_generation_wall_s": gen_time,
        "mdu": str(model.filepath),
        "aux_files": aux,
        **spec.extra_meta,
    }
    (args.out_dir / "generation_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
