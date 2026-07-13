# D-Flow FM example output validation

This read-only validator provides platform-neutral checks for the public Deltares
examples used by the Linux baseline. Run the same script against Linux and macOS
outputs before comparing numerical tolerances.

Create an isolated environment and run it from the repository root:

```bash
uv venv baseline_tools/dfm-validation
uv pip install \
  --python baseline_tools/dfm-validation/bin/python \
  -r tools/output_validation/requirements.txt

baseline_tools/dfm-validation/bin/python \
  tools/output_validation/validate_examples.py \
  --runs-root baseline_runs \
  --json-out baseline_logs/example-output-validation.json
```

The validator checks:

- expected files and time ranges;
- readable NetCDF datasets;
- UGRID topology and mesh sizes;
- finite water levels and water depths;
- finite, nonnegative D-WAQ concentrations in wet layers;
- direct validation-tool versions for reproducibility.

`baseline_tools`, `baseline_runs`, and `baseline_logs` are runtime artifacts and
must remain outside Git.

## `field_diff.py` -- node-by-node cross-platform parity

`field_diff.py` is a heavier, separate comparison from `validate_examples.py`
(it does not replace it): for each example it opens two platforms' map/his
output side by side (e.g. one build's output against a reference build's
output) and diffs every shared variable *node by node, over every shared
output timestep* -- not just topology and extrema. It reports, per variable,
RMS and max-abs differences both absolute and relative to the reference
field's dynamic range, per timestep and overall.

The reference outputs are not in this repository -- copy them once from the
reference build/machine (read-only `scp`) into the ignored
`baseline_artifacts/` directory, keeping the three-case layout:

```bash
mkdir -p baseline_artifacts/linux-reference-outputs/{01_dflowfm_sequential,02_dflowfm_parallel,03_dflowfm_dwaq_sequential}/dflowfm/dflowfmoutput
scp popos:~/projects/Delft3D/baseline_runs/01_dflowfm_sequential/dflowfm/dflowfmoutput/{f34.dia,f34_his.nc,f34_map.nc} \
  baseline_artifacts/linux-reference-outputs/01_dflowfm_sequential/dflowfm/dflowfmoutput/
scp popos:~/projects/Delft3D/baseline_runs/02_dflowfm_parallel/dflowfm/dflowfmoutput/{westerscheldt_0000.dia,westerscheldt_0001.dia,westerscheldt_0002.dia,westerscheldt.dia,westerscheldt_0000_his.nc} \
  baseline_artifacts/linux-reference-outputs/02_dflowfm_parallel/dflowfm/dflowfmoutput/
scp popos:~/projects/Delft3D/baseline_runs/03_dflowfm_dwaq_sequential/dflowfm/dflowfmoutput/{f34_dynamo.dia,f34_dynamo_his.nc,f34_dynamo_map.nc,f34_dynamo_mass_balances.csv,f34_dynamo_mass_balances.txt} \
  baseline_artifacts/linux-reference-outputs/03_dflowfm_dwaq_sequential/dflowfm/dflowfmoutput/
```

Then run:

```bash
baseline_tools/dfm-validation/bin/python \
  tools/output_validation/field_diff.py \
  --mac-runs-root baseline_runs \
  --linux-runs-root baseline_artifacts/linux-reference-outputs \
  --json-out baseline_logs/field-diff-macos-vs-linux.json
```

`field_diff.py` exits non-zero if **any** variable's status is `fail*` --
it is safe to use directly as a completion/CI gate, not just a report
generator.

Tolerance tiers:

| tier | relative threshold | meaning |
| --- | --- | --- |
| `deterministic` | ~1e-9 | bit-reproducible arithmetic |
| `iterative` | ~1e-4 | compiler math reassociation / iterative PETSc solve |
| `adaptive_transport` | ~1e-2 | example 03's adaptive internal dt couples into D-WAQ transport; applied to the D-WAQ tracer variables (`OXY`, `NH4`, `NO3`, `PO4`, `Diat`, `Green`) |

Two additional rules apply before a tier verdict is reached:

- **Finite-value masks must agree** between platforms at every timestep.
  A node that is finite on one platform and NaN/fill on the other is
  reported as a hard `fail` (with the mismatched-node count), never
  silently dropped from the comparison -- even if other nodes at that
  timestep still agree. (Both platforms being entirely non-finite at the
  same timestep is fine -- some D-WAQ tracers legitimately stop being
  written on both platforms after a point in the run.)
- **Near-zero Linux references get an absolute tolerance.** When a
  variable's Linux reference magnitude is negligible (max abs below
  `--reference-negligible-threshold`, default 1e-9), a relative-tolerance
  verdict is meaningless, so the variable is graded against `--abs-tol`
  (default `1e-12`, sized for waterlevel/velocity-scale fields -- pass a
  larger value for variables with a coarser natural scale) instead of
  being unconditionally marked as a pass.

The time axes are verified to match exactly before any comparison (fixed
output times survive an adaptive internal dt); a mismatch degrades to
comparing only the intersecting times, and a *completely* disjoint time
axis (no shared timestep at all) raises rather than silently comparing
nothing.

See `selftest.py` for synthetic regression tests of this gate logic
(mask-mismatch, near-zero-reference, tolerance-boundary, time-axis, and
exit-code cases) -- run with the same interpreter:

```bash
baseline_tools/dfm-validation/bin/python tools/output_validation/selftest.py
```

Both examples 01 (sequential) and 02 (MPI) are expected to match at
floating-point-epsilon level (`~1e-15` to `~1e-16` relative) for every
variable, since they exercise no adaptive time-stepping. An example built
around an adaptive internal dt (D-WAQ transport coupled to a long tidal run,
for instance) is expected to show materially larger node-by-node differences
than a simple "extrema" comparison would suggest, because independent
compiler/platform arithmetic reassociation nudges the adaptive-dt trajectory
itself, not just per-step rounding -- this shows up as legitimate tidal-phase
drift that grows with run length and localizes near flow-reversal/
wetting-drying instants, including occasional per-node wet/dry mask
disagreement at a small fraction of node-timesteps. A same-model
sequential-vs-MPI run on the reference platform is a useful control for
separating "expected adaptive-dt trajectory divergence" from "genuine
platform bug": if the reference platform's own seq-vs-MPI divergence is
exact-zero on the same model, then cross-platform divergence of the same
shape indicts the trajectory, not the port. See a specific project's
verification report for how this gate has been applied to a real model.

## `conservation_check.py` -- volume/mass conservation invariants

`conservation_check.py` runs independently per platform (point it at
`baseline_runs` for macOS, `baseline_artifacts/linux-reference-outputs` for
Linux) and computes, for each example, three conservation checks from what
the outputs actually provide:

1. **`his_balance`** -- dflowfm's own water-balance ledger
   (`water_balance_*` variables in the his-file; the `.mdu` sets
   `Wrihis_balance = 1`, which is why the `.dia` files only print a single
   "model volume" line instead of a balance block -- the ledger is written to
   the his-file instead). `water_balance_volume_error` is dflowfm's own
   residual of storage vs boundary flux.
2. **`map_independent`** -- an independent recomputation from the map file
   (examples 01 and 03; example 02 does not write a map.nc in this baseline
   set): storage change (`sum(cell_area * waterdepth)`, differenced from t0)
   vs the trapezoidal time-integral of the open-boundary flux (`q1` summed
   over the boundary flow links/edges, identified from `FlowLink`/
   `mesh2d_edge_type`).
3. **`dwaq_mba`** -- example 03 only: parses the D-WAQ
   `*_mass_balances.csv` "Whole model" / "Water" rows and checks that each
   interval's storage-nett and boundary-nett sum to zero.

```bash
baseline_tools/dfm-validation/bin/python \
  tools/output_validation/conservation_check.py \
  --runs-root baseline_runs --platform macos \
  --json-out baseline_logs/conservation-macos.json

baseline_tools/dfm-validation/bin/python \
  tools/output_validation/conservation_check.py \
  --runs-root baseline_artifacts/linux-reference-outputs --platform linux \
  --json-out baseline_logs/conservation-linux.json
```

`his_balance` and `dwaq_mba` are expected to sit at genuine
numerical-precision level (`~1e-14` to `~1e-9` relative, depending on the
check) and to match closely between platforms/builds. `map_independent`, by
contrast, is expected to carry an O(10-30%) residual on any platform: it
compares an instantaneous discharge sample (`q1`, on the semi-implicit
scheme's discharge time level) against storage change (on the water-level
time level) using only the coarse map-output interval for time-integration,
which is a deterministic artifact of the sampling scheme, not a conservation
violation. Its value is as a cross-platform/cross-build consistency probe --
it should reproduce to several significant digits between two builds even
though its absolute residual is large -- while `his_balance` and `dwaq_mba`
are the precision-level conservation evidence.
