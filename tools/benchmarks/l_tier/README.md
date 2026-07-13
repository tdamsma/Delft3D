# L-tier benchmark model

A large, memory-resident D-Flow FM model meant to meaningfully exercise the
M3 Ultra Mac Studio's memory bandwidth (256 GiB, ~800 GB/s). Committed as a
**generator script**
(`generate_l_model.py`), not as data -- the generated `.mdu`/net files/run
outputs live under `baseline_runs/l-tier/` (gitignored, regenerate on
demand).

## TL;DR

```bash
baseline_tools/dfm-validation/bin/python tools/benchmarks/l_tier/generate_l_model.py \
    --cells 140000 --out-dir baseline_runs/l-tier/mid
baseline_tools/dfm-validation/bin/python tools/benchmarks/l_tier/generate_l_model.py \
    --cells 576000 --out-dir baseline_runs/l-tier/large

baseline_runs/bin-snapshot/dflowfm --autostartstop l_tier.mdu   # from within the out-dir
```

Both tiers use the exact same tidal + river-discharge boundary forcing as
the public Western Scheldt example
(`baseline_artifacts/deltares-examples/extracted/examples/02_dflowfm_parallel`),
Manning friction (0.023) and k-eps turbulence matching that example, and a
default `TStop` of 900 s (0.25 h) -- calibrated so the 576k tier runs
~7.5 min wall on 8 OpenMP threads / ~11 min single-threaded (see "Verified
sizes"). Pass `--tstop-hours 12.416667` for one full boundary-forcing
tidal period (~12.42 h sim) when a long profiling run is wanted.

## Design

### Mesh: synthetic meandering channel (default, verified)

`--mode synthetic` (default) builds a rectilinear (pure-quad) mesh over a
long, narrow domain (`width` fixed at 2000 m, `dx=dy=10 m` by default) with
a deliberately non-trivial bed level:

- sloped along-channel: -20 m at the sea end (x=0) to -3 m at the river end
  (x=length),
- a meandering deeper thalweg (sinusoidal centerline, wavelength =
  length/3, amplitude = 15% of width),
- shallower banks (+/-4 m relief across the channel, `cos` profile).

This is not separable in x/y, so it exercises genuinely 2D bed-slope /
wetted-cross-section coefficient fields the way a real estuary model would,
rather than a flat or purely-1D bed. It reuses
`tools/verification_cases/common/grid.py`'s `build_rectilinear_grid` (the
same meshkernel-backed rectilinear builder the verification-cases analytic
suite uses) and `common/mdu_base.py`'s `make_base_model` for the shared,
already-battle-tested hydrolib-core MDU scaffolding (round-trip pitfalls
documented there, e.g. the `NetworkModel` empty-overwrite trap).

Cell count is controlled *exactly*: `ny = width/dx` is fixed, `nx =
round(cells/ny)`, so `nx*ny` is exact whenever `cells` is a multiple of
`ny`. With the defaults (`width=2000`, `dx=10` => `ny=200`), `--cells
140000` gives exactly 140,000 cells (700x200) and `--cells 576000` gives
exactly 576,000 (2880x200).

Boundary forcing is the *exact* Fourier/constant signal from example 02's
`boundarysea_0001.cmp` (mean level 0.5 m + an M2-like 745-min, 2 m
amplitude component) and `boundaryriver_0001.cmp` (constant 2500 m3/s),
applied via straight cross-channel polylines at x=0 (`sea.pli`,
`waterlevelbnd`) and x=length (`river.pli`, `dischargebnd`) -- same old-style
`.ext`/`.pli`/`.cmp` mechanism example 02 itself uses.

### Mesh: real Western Scheldt refinement (`--mode western-scheldt`, blocked)

The first approach tried was to refine the actual public Western
Scheldt mesh (8,355 cells) with meshkernel. **This was attempted, mesh
generation works, but running the result in dflowfm crashes** -- see the
long "Western Scheldt refinement" section in `generate_l_model.py`'s module
docstring for the full write-up. Summary:

- The old-format net file (`NetNode_x/y/z`, `NetLink`) loads fine into
  meshkernel by reading `NetLink` directly as the edge-node array (hydrolib-
  core's own UGRID reader can't read this file at all -- it silently
  returns an empty mesh).
- meshkernel's Casulli refinement (`mesh2d_casulli_refinement`) refines it
  deterministically and fast: **8,355 -> 34,993 -> 142,652 -> 576,457 ->
  2,317,529** faces for passes 1-4 (measured; `--dry-run` reproduces this in
  seconds, even at the 2.3M-cell pass-4 size). This is almost exactly the
  expected "~4x cells per pass" curve, and 142,652/576,457 line up almost
  exactly with this generator's requested mid/large targets -- which is why
  that approach was tried first.
- Running `dflowfm --autostartstop` on *any* refined output (even pass 1,
  34,993 cells) crashes during initialization with a Fortran runtime error:
  `Attempting to allocate already allocated variable 'kck'`
  (`src/utils_lgpl/gridgeom/packages/gridgeom/src/gridoperations.F90:783`).
- This is the same *class* of bug already fixed elsewhere in this exact
  file on this branch (commit `109999b35a`, "fix: utils_lgpl
  disassociated-pointer/unallocated-allocatable guards"): an `allocate()`
  with no `if (allocated(...))` guard, harmless on ifx/Linux, fatal under
  gfortran's runtime checks. The `kck` array is allocated unconditionally a
  few lines below its sibling `kc`, which *does* have the guard.
- Ruled out: sheer mesh size (a from-scratch 144,400-cell all-quad
  rectilinear mesh runs cleanly) and the meshkernel-to-UGRID pipeline
  itself (the *unrefined* Western Scheldt mesh, round-tripped through the
  identical pipeline with zero refinement passes, also runs cleanly).
- Tried and did not fully resolve it: `mesh2d_merge_nodes_with_merging_
  distance` (fusing near-duplicate nodes Casulli refinement introduces, up
  to 5 m apart -- this did eliminate one exactly-zero-area sliver quad and
  all sub-10 m^2 faces) and fan-triangulating every face with >4 nodes via
  `mesh2d_insert_edge` (Casulli refinement of this mesh, which already
  mixes triangles and quads, introduces ~90 5-/6-sided faces near the
  triangle/quad junctions per refinement pass). Both measurably improved
  mesh quality; neither stopped the crash, suggesting either further
  undiagnosed degeneracies or a node-valence/administration issue not
  visible from face geometry alone.
- The actual fix is almost certainly a one-line source change (guard `kck`
  like `kc` is guarded, mirroring commit `109999b35a`) -- but that is a
  *source* change, explicitly out of scope for this benchmark-generation
  task (no source/build changes permitted). Left for future work with that
  permission.

The mesh-generation code path (`build_western_scheldt_network`) is kept in
`generate_l_model.py` since it works standalone and may be useful once the
source fix lands (`--mode western-scheldt --dry-run` reproduces the sizes
above in seconds) -- it is just not the default, and its `.mdu` output is
**not verified to run**.

### MDU / output minimization

Both modes share `build_mdu()`: Manning friction 2.3e-2, k-eps turbulence
(`turbulencemodel`/`turbulenceadvection` = 3, hydrolib-core's own defaults,
matching example 02), `Icgsolver=2` (SobekGS_OMPthreadsafe, matching
example 02's sequential setting -- this tier is sequential/OpenMP-threaded
only, by design; the M-tier covers the MPI axis),
`WaterLevIni=0.5`. Output is deliberately minimized (benchmarks want
compute, not I/O): only `wrimap_waterlevel_s1`/`waterdepth`/
`velocity_component_u1`/`velocity_vector`/`velocity_magnitude` stay on
(hydrolib-core defaults), everything else (turbulence, viscosity/
diffusivity, chezy, spiral flow, numlimdt, tau, density, wind, tidal
potential terms) is explicitly turned off. `wrihis_balance` stays on (one
cheap scalar time series, useful for a mass-conservation sanity check).
`TStop` defaults to 900 s (see the calibration note in the generator's
`DEFAULT_TSTOP_HOURS`); `MapInterval` defaults to ~1/4 of `TStop` (a
handful of snapshots, not full time resolution), `HisInterval` to 300 s.
Both intervals (and `TStop`) are
snapped to exact multiples of `DtUser` via
`tools/verification_cases/common/mdu_base.round_up_to_multiple` -- a real
dflowfm runtime check (not just a hydrolib-core one), documented in that
module.

## Verified sizes

**Caveat: another process was concurrently running short benchmark
validation runs on this same machine while these numbers were measured
(harness development work) -- wall-clock/throughput numbers below are
indicative only, not clean single-tenant measurements.** Peak RSS is much
less sensitive to co-tenancy and should be reliable. Machine: Mac Studio
M3 Ultra, 32 cores, 256 GiB RAM (confirmed via `sysctl`, this is real
target hardware, not emulated).

Both tiers were verified with a 900-sim-s `--autostartstop` run (equal to
the generator's now-default `TStop`, which was calibrated *from* these
runs) wrapped in `/usr/bin/time -l` for peak RSS, plus an OpenMP
thread-count check on the mid tier. 900 sim-s is enough to see steady
per-step cost: 528-651 timesteps, so the first step's one-time setup is
noise.

### Mid tier: 140,000 cells (700 x 200, 7 km x 2 km)

| Check | Result |
|---|---|
| Generation | `--cells 140000` -> exactly 700x200 = 140,000 faces, 140,901 nodes. Mesh build: ~6.3 s. |
| Init | Clean: "Model initialization was successful", cache written, no warnings beyond routine deprecated-keyword notices. |
| Timesteps advance | Yes, autotimestep-controlled (CFLmax=0.7), 900 s sim time completed. |
| NaN check | `mesh2d_s1` (water level) shows NaN at 844/249/121/0 cells across the 4 map snapshots -- confirmed to be the shallow bank cells starting **dry** under `WaterLevIni=0.5` (bed level there reaches +1 m), progressively wetting as the tide comes in (NaN count strictly decreasing to 0). This is D-Flow FM's normal dry-cell convention, not an instability. `mesh2d_ucx`/`ucy` (velocity) have **zero** NaN, range -1.9..+4.8 m/s, physically reasonable. `waterdepth` range 0..22.5 m, matching the -20 m sea depth. |
| `.dia` clean | Yes -- no ERROR/WARNING beyond routine deprecated-keyword and disabled-keyword notices (both present verbatim in example 02's own `.dia` too). |
| Init time | ~2 s (log timestamps: process start 11:16:17 -> "Modelinit finished" 11:16:19). |
| Time per timestep (indicative, co-tenant machine) | 651 timesteps for 900 sim-s (autotimestep, avg dt ~1.38 s). 1 thread: 195.6 s timeloop -> **0.30 s/step** (198.5 s wall total, ~4.5 sim-s per wall-s). 8 threads (`OMP_NUM_THREADS=8`, "OpenMP enabled, number of threads = 8" confirmed in log): 109.0 s timeloop -> **0.167 s/step** (111.9 s wall; ~1.8x speedup -- modest, consistent with partial OpenMP coverage of the step loop; take with the co-tenancy caveat). |
| Peak RSS | **751 MiB** 1-thread / **748 MiB** 8-thread (`maximum resident set size` from `/usr/bin/time -l`) -- ~5.5 KiB/cell. |

### Large tier: 576,000 cells (2880 x 200, 28.8 km x 2 km)

| Check | Result |
|---|---|
| Generation | `--cells 576000` -> exactly 2880x200 = 576,000 faces, 579,081 nodes. Mesh build: ~27 s. |
| Init | Clean, same pattern as mid tier. |
| Timesteps advance | Yes: 528 timesteps for 900 sim-s (autotimestep, avg dt ~1.70 s -- slightly larger than mid tier's, the deeper/along-channel-longer domain relaxes the local CFL limit on average). |
| NaN check | Same dry-bank-cell pattern as mid tier: `mesh2d_s1` NaN at 3534/1814/363/177 of 576,000 cells over the 4 snapshots (strictly decreasing as the tide wets the banks); `mesh2d_ucx`/`ucy` **zero** NaN, ranges -1.3..+4.2 / -1.0..+0.9 m/s; waterdepth 0..22.5 m. No instability. |
| `.dia` clean | Yes -- zero ERROR lines. |
| Init time | ~10 s (log timestamps: process start 11:21:11 -> "Modelinit finished" 11:21:21). |
| Time per timestep (indicative, co-tenant machine) | 1 thread: 659.8 s timeloop / 528 steps -> **1.25 s/step** (671.5 s wall total for 900 sim-s, ~1.34 sim-s per wall-s). Solve fraction 14% (`fraction solve/steps` from the .dia) -- the bulk is in `inistep` (advection/coefficient assembly), the classic bandwidth-bound region, which is exactly what this tier exists to profile. No 8-thread repeat was run at this size (the mid-tier 8-thread point plus these single-thread numbers bracket the harness's expectations; the 6b harness will sweep threads properly). |
| Peak RSS | **2.74 GiB** (2,945,138,688 B from `/usr/bin/time -l`) -- ~5.0 KiB/cell, consistent with the mid tier's ~5.5 KiB/cell. |

Raw evidence: `baseline_runs/l-tier/{mid,large}/smoketest_run*.log`
(dflowfm output + `/usr/bin/time -l` block), `dflowfmoutput/*.dia`, and
`generation_metadata.json` in each directory.

## Scaling further

- `--cells` scales the synthetic channel exactly (`nx*ny`); `--dx-m` and
  `--width-m` change resolution/cross-section independently. Mesh
  generation itself is fast even at large sizes (linear in cell count,
  dominated by `build_rectilinear_grid`'s meshkernel call + bathymetry
  evaluation) -- the practical limit is dflowfm's own run time/memory, not
  generation.
- Memory: measured ~5.5 KiB/cell (mid) and ~5.0 KiB/cell (large) -- a
  2M-cell model needs roughly ~10 GiB, and RAM would only become the
  binding constraint somewhere in the tens-of-millions-of-cells range,
  far beyond what wall time allows. Time is the real limit: per-step cost
  measured essentially linear in cell count between the two tiers (0.30 ->
  1.25 s/step for 4.11x cells, a 4.2x ratio; the small excess over linear
  is within co-tenancy noise), and the number of steps per sim-second is
  roughly constant at fixed dx. Scaling the default 900-sim-s run:
  ~2.3M cells => ~45 min single-threaded -- feasible unattended, but slow
  for N>=5 harness repeats. Estimated practical ceiling for a repeatable
  benchmark tier on this machine: ~2M cells (one Casulli-pass-4-equivalent),
  with anything larger better run as a one-off profiling target.
- `--tstop-hours` scales run length independently of size. Default 0.25 h
  (900 s) is the calibrated benchmark length (576k tier: ~11 min
  single-thread, ~7.5 min at 8 threads). For long profiling runs pass
  `--tstop-hours 12.416667` (one full tidal period): extrapolated
  ~2.7 h single-threaded for the mid tier and ~9.3 h for the large tier.
- `--mode western-scheldt` remains available for real-geometry sizing
  estimates (`--dry-run`) and may become runnable once the `kck` allocation
  guard is fixed upstream (see "Mesh: real Western Scheldt refinement"
  above) -- at that point it would be a drop-in replacement offering the
  same 8,355 -> 34,993 -> 142,652 -> 576,457 -> 2,317,529 growth curve on
  real bathymetry.

## Files

- `generate_l_model.py` -- the generator. Run with
  `baseline_tools/dfm-validation/bin/python` (meshkernel 8.3.0,
  hydrolib-core, xarray, scipy).
- Generated models/runs live under `baseline_runs/l-tier/{mid,large}/`
  (gitignored; regenerate with the commands at the top of this file).
  Each `out-dir` contains `l_tier.mdu`, `l_tier_net.nc`, `sea.pli`/
  `sea_0001.cmp`, `river.pli`/`river_0001.cmp`, `l_tier.ext`, and
  `generation_metadata.json` (mesh size, timing, tstop/interval values --
  the same numbers reported on stdout at generation time).

## For the benchmark harness (`tools/benchmarks/tiers.json`)

`tiers.json`'s `"L"` entry is a placeholder pointing at
`baseline_runs/benchmarks/L/` -- once wired up, it should instead point
`source_dir` at a pristine copy of one of these generated model
directories (e.g. `baseline_runs/l-tier/mid` or `.../large`) with `mdu:
"l_tier.mdu"`, `mode: "sequential"`, matching the `"M-seq"` entry's shape
(this tier has no MPI variant, by design). This file is outside this
generator's write scope (`tools/benchmarks/l_tier/` +
`baseline_runs/l-tier/` only), so that wiring is left for whoever owns
`tiers.json`.
