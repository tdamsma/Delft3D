# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Delft3D is the collection of simulation engines (mostly Fortran, with C/C++ and Python tooling) behind the **Delft3D 4** suite (structured grids) and its successor **Delft3D FM** (Flexible Mesh: unstructured grids + 1D networks). The engines cover hydrodynamics, morphodynamics, waves, water quality, hydrology, real-time control and particle tracking.

The two suites share this one repository and are selected at build time via CMake's `CONFIGURATION_TYPE`:
- Delft3D 4 (`d3d4-suite`): `d_hydro`/`flow2d3d` (FLOW), `wave`, `rtc`, `waq`, `part`.
- Delft3D FM (`fm-suite`): `dimr`, `dflowfm`, `wave`, `fbc`, `waq`, `rr`. The full FM binary set is called `dimrset`, with **DIMR** (Deltares Integrated Model Runner) as the central coupler that orchestrates multiple engines in one simulation.

## Build system

Builds are a two-stage process: **Conan 2** resolves third-party dependencies, then **CMake** configures and builds. Two Python wrappers in the repo root drive everything — prefer them over invoking conan/cmake directly:

- `run_conan.py` — one-time Conan setup (compiler profile, settings, remotes).
- `build.py` — runs Conan install, CMake configure, and optionally build + install.

The CMake source root is `src/cmake` (not the repo root). Available `--config` values: `all`, `fm-suite`, `d3d4-suite`, plus per-engine configs (`dflowfm`, `dimr`, `dwaq`, `dwaves`, `flow2d3d`, `swan`, `drr`, `fbc`, `tools`, `tools_gpl`, `dflowfm_interacter`).

### Linux (containerized — recommended)

Linux builds run inside a container (the `.devcontainer/delft3d` devcontainer in VSCode, or the `third-party-libs` image interactively). Linux uses a single-config generator, so build type is chosen at configure time.

```bash
# One-time Conan setup (choose based on Nexus access):
python run_conan.py initialize deltares    # Deltares developers (pre-built binaries from Nexus)
python run_conan.py initialize external     # external devs (build deps from local recipes)

# Configure + build + install:
python build.py --config fm-suite --build --build-type Release
# External developers add --build-dependencies on the first build (or after a conan/recipes change):
python build.py --config fm-suite --build --build-type Release --build-dependencies
```

Default build type is `Debug`; choices are `Debug`, `Release`, `RelWithDebInfo`. Build dirs are `build_<config>_<buildtype>/` with install under `.../install`. `python build.py --help` lists all flags.

### Windows

Windows uses Visual Studio (2019/2022/2026) with the Intel `ifx` Fortran compiler; must run from a Developer Command Prompt. Multi-config, so build type is chosen at build time. `build.py` auto-detects the VS version and generates `build_<config>/<config>.sln`.

## Tests

Unit tests use the **ftnunit** Fortran framework and run through **CTest**. They live in two places: `test/unit_test/` (run from the build folder, mirrors the `src/` tree) and `src/test/` (run from the install folder). Integration tests are in `test/integration_test/`; larger model-simulation regression testbenches live in `test/deltares_testbench/` (Python, uses DVC for test data — see its own README).

```bash
cd <build-or-install-dir>
ctest -C Debug                 # all tests (-C selects config on multi-config/Windows)
ctest -R "^MyTest$"            # single test by regex
ctest -R MyTest -VV           # verbose output
ctest -C Debug -L fast        # by label; -LE excludes a label
```

Tests are registered via the custom `create_test()` CMake function (see `test/unit_test/.../CMakeLists.txt` and `doc/unit-testing.md`). Test data is reached at runtime via the `DATA_PATH` environment variable, not hardcoded paths. To unit-test a subroutine that touches a module global, the global must be exported in the source with `!DEC$ ATTRIBUTES DLLEXPORT`.

## Code layout

- `src/engines_gpl/` — the simulation engines (`dflowfm`, `flow2d3d`, `waq`, `wave`, `part`, `rr`, `rtc`, `fbc`, `dimr`, `d_hydro`, ...).
- `src/utils_gpl/` — larger shared domain libraries (`morphology`, `flow1d`, `trachytopes`, `dhydrology`, ...).
- `src/utils_lgpl/` — foundational LGPL libraries reused across engines (`deltares_common`, `io_netcdf`, `ec_module` for external coupling, `gridgeom`, `nefis`/`delftio` I/O, `kdtree_wrapper`, `ftnunit`, ...).
- `src/third_party*/` — vendored dependencies (excluded from formatting/most changes).
- `src/cmake/` — the build entry point: `configurations/`, `compiler_options/`, `modules/`, and `functions.cmake`.

Engine packages are typically structured as `<engine>/packages/<lib>/src/...` with a sibling `CMakeLists.txt`.

## Conventions

- **Fortran formatting** is enforced with **fprettify** using `.fprettify.rc` (indent = 3 spaces, standardized whitespace). `flow2d3d` and the `third_party*` trees are excluded — do not reformat them.
- **Branch naming** (required for CI to run): `<kernel>/<type>/<ISSUENR>_short_description`, e.g. `fm/feature/UNST-1234_improve_partition_file`. Kernel ∈ {`all`, `d3d4`, `fm`, `none`, `part`, `rr`, `swan`, `waq`, `wave`, `tc`} and determines which integration test cases run — use `all` if unsure. Type ∈ {`bugfix`, `doc`, `feature`, `poc`, `release`, `task`}. `ISSUENR` is the JIRA issue (e.g. `UNST-####`).
- PR descriptions use a closing keyword (e.g. `Fixes #160`) to link the JIRA issue. Only PRs opened by Deltares employees trigger the CI pipelines.

## Further reading

`doc/development.md` is the hub; see `doc/compiling_Linux.md`, `doc/compiling_Windows.md`, `doc/unit-testing.md`, `doc/debugging.md`, and `doc/contributing.md` for details.
