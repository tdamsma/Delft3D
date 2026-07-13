# GNU Fortran (gfortran) toolchain support

This series adds GNU Fortran as a supported compiler for building the
`fm-suite` (D-Flow FM / DIMR) configuration, alongside the previously
sole-supported Intel Fortran (`ifx`) toolchain on Linux. It is
OS-agnostic groundwork: everything here applies equally on any Unix
platform gfortran targets. A later, separate layer (not part of this
branch) adds the Darwin-specific pieces needed to build on macOS, where
gfortran is the only available Fortran compiler.

## What's supported

- `fm-suite` (dflowfm, dimr, SWAN/wave, delwaq, RR, fbc, PART, tools_gpl)
  builds and links cleanly with GNU Fortran, both Debug and Release.
- The full CTest suite passes: 361 of 362 registered tests pass, 1
  disabled (`FF2NFWriterTest.WriteToFile`, disabled independent of
  compiler) -- the same pass/disabled counts as the ifx baseline.
- The analytic verification suite (`tools/verification_cases/`, 5
  closed-form shallow-water cases) passes 5/5, matching the closed-form
  solutions to 12-13 significant digits.
- `example 01` (sequential) and `example 02` (MPI) run to completion and
  match an ifx-built reference to floating-point-epsilon level
  (`~1e-15`-`~1e-16` relative) on every checked variable -- the two
  toolchains are numerically interchangeable for these cases.
- `example 03` (D-WAQ transport coupled to a 120 h run with an adaptive
  internal timestep) fails the strict field-comparison gate wholesale:
  divergence includes per-node wet/dry mask disagreement at a handful
  (<=6) of roughly 9,100 node-timesteps checked. This is attributed to
  legitimate adaptive-dt trajectory divergence -- different compiler
  arithmetic reassociation nudges which internal timestep the adaptive
  scheme takes, which compounds over a long run -- rather than a
  toolchain bug, based on two controls that come back exact-zero on the
  same model: a same-toolchain sequential-vs-MPI run, and a
  before/after-this-series' -shared-code-changes comparison on the ifx
  toolchain. It is not, and should not be described as, a passing
  result; see `tools/output_validation/README.md` for the gate's exact
  tolerance policy.

## How to build with gfortran on Linux

1. A Conan profile with GNU Fortran (gfortran) selected as the Fortran
   compiler, matching PETSc and preCICE built (or available as
   prebuilt binaries) against that same compiler. This series does not
   yet ship a canonical, checked-in Linux GNU Conan profile the way it
   does for macOS -- it was validated against a container image with
   gfortran, PETSc, and preCICE preinstalled and Conan's local cache
   pointed at that image's package set. Shipping a portable Linux
   equivalent of the macOS profile (see the macOS-port layer for that
   pattern) is a known follow-up, not yet done here.
2. With such a profile active:

   ```bash
   python run_conan.py initialize external   # or: deltares, if Nexus access is available
   python build.py --config fm-suite --build --build-type Release
   ```

3. Run the test suite and the validation tools:

   ```bash
   cd build_fm-suite_release
   ctest -C Release        # serial: some tests interfere under parallel ctest, pre-existing and unrelated to compiler
   ```

   ```bash
   uv venv baseline_tools/dfm-validation
   uv pip install --python baseline_tools/dfm-validation/bin/python -r tools/output_validation/requirements.txt
   baseline_tools/dfm-validation/bin/python tools/output_validation/selftest.py
   ```

## Known limitations

- **`io_netcdf_dll` is not built under GNU Fortran.** Its BIND(C)
  interfaces pass derived types with non-interoperable
  `CHARACTER(len>1)` components, which ifx accepts as a lenient
  extension and gfortran correctly rejects. Nothing in this repository
  links against it (dflowfm/dimr use the ordinary `io_netcdf` Fortran
  target), so in-tree builds are unaffected, but no C-callable
  `libio_netcdf` shared library is produced for external C/C#/Python
  bindings on this toolchain. The real fix -- reworking
  `ug_meta.f90`/`ug_charinfo.f90` to use interoperable
  `character(kind=c_char)` arrays -- is tracked but not done here. A
  configure-time `message(STATUS ...)` reports this whenever it applies.
- **No portable, checked-in Linux GNU Conan profile.** See "How to
  build" above; a from-scratch build currently depends on a
  compatible externally-provided toolchain/dependency image.
- **`-fallow-argument-mismatch` is enabled tree-wide** in `gnu.cmake` to
  let legacy call sites that predate explicit interfaces continue to
  compile. This is a broad compatibility flag, not a narrow one; it
  papers over a class of interface mismatches gfortran would otherwise
  reject, some of which may be worth tightening on a case-by-case basis
  in the future rather than blanket-permitting.
- **`D3D_NATIVE_CPU_TUNING` is a manual opt-in**, off by default. Builds
  with it ON are tuned for, and only supported on, the exact machine
  that built them.

## Evidence

Full CTest run: **361/361 passing, 1 disabled**, matching the ifx
baseline's pass/disabled counts exactly. Analytic verification suite:
**5/5**, 12-13 significant digits of agreement with closed-form
solutions. Cross-toolchain field comparison (`field_diff.py`) on
examples 01/02: floating-point-epsilon-level agreement on every checked
variable. Example 03: see "What's supported" above for the honest,
gate-hardened disposition of that comparison.
