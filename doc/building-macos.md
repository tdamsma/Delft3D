# Building on macOS (Apple Silicon)

This series adds a native macOS build of the `fm-suite` configuration
(dflowfm, dimr, SWAN/wave, delwaq, RR, fbc, PART, tools_gpl) on Apple
Silicon, using Homebrew's GNU Fortran (gfortran) as the Fortran compiler
and Apple Clang for C/C++. It builds on top of this fork's OS-agnostic
GNU-toolchain-support layer -- read `doc/gnu-toolchain-support.md` first
for what applies to any gfortran build, GNU compiler-option flags, and
known limitations shared with the Linux GNU build.

## Prerequisites

Xcode Command Line Tools (for Apple Clang) and Homebrew, then:

```bash
brew install gfortran cmake ninja open-mpi petsc boost libxml2 precice hyperfine
```

- **gfortran**: the only Fortran compiler available for Apple Silicon
  (there is no Intel Fortran for arm64 macOS).
- **open-mpi**: `find_package(MPI)` finds it on the standard UNIX path.
- **petsc**: must expose a `lib/pkgconfig/PETSc.pc` (Homebrew's package
  does).
- **precice**: if the formula fails to build, build preCICE from source;
  as a last resort an `APPLE`-guarded option to exclude the preCICE
  coupling targets could be added, but was not needed on Apple Silicon.
- **libuuid** is not a separate Homebrew dependency: `uuid_generate`
  lives in libSystem on macOS and is linked automatically.

## Build

```bash
python run_conan.py initialize deltares   # or: external, if Nexus access is unavailable
python build.py --config fm-suite --build --build-type Release
```

`run_conan.py` detects the Homebrew prefix, the latest installed
`gfortran-NN`, and the installed Apple Clang major version on the machine
running the build, and writes a fresh Conan profile to
`conan/.generated/delft3d_macos_detected` (gitignored) rather than
requiring a hand-edited, machine-specific profile to be committed. See
`conan/config/profiles/delft3d_macos_apple_clang_21` for a worked example
of the generated profile's shape.

Build directories follow the same convention as Linux:
`build_<config>_<build_type>/`, with the install tree under
`.../install`.

## Test

```bash
cd build_fm-suite_release
ctest -C Release --parallel 1   # some tests interfere under parallel ctest; run serial
```

Expect the same test inventory as the Linux ifx baseline: 362 tests
registered, 361 pass, 1 disabled (`FF2NFWriterTest.WriteToFile`).

## Run

Public D-Flow FM examples run the same way as on Linux. MPI runs need
`DYLD_LIBRARY_PATH` forwarded explicitly through `mpirun -x
DYLD_LIBRARY_PATH` -- macOS's System Integrity Protection strips `DYLD_*`
environment variables across several process-launching paths (including
`/usr/bin/time` and `nohup`), and Open MPI does not forward arbitrary
parent-process environment variables to launched ranks without an
explicit `-x`.

`cmake --install` succeeds and the installed `dflowfm` runs standalone.
`dimr`, which loads its engine plugins via `dlopen()` rather than being
linked against them directly, additionally needs
`DYLD_LIBRARY_PATH=<install-prefix>/lib` set by hand.

## Known limitations

- **The install tree is not relocatable.** `cmake --install` completes
  and the installed binaries run from their install location, but their
  `@rpath` entries are absolute paths into the build tree and Conan
  cache at build time, not install-prefix-relative. Moving the install
  directory, or deleting the build tree/Conan cache it was built from,
  breaks it. Linux's install step performs a dependency-copy and RPATH
  rewrite (`install_linux_libs`, ELF-specific: shells out to `ldd` and
  `patchelf`) that has no macOS equivalent yet; a real fix needs a
  Mach-O equivalent (`otool -L`/dylib copy + `install_name_tool
  -change`/`@loader_path` rewrite). Treat "install command succeeds" and
  "installed suite is relocatable to another machine" as separate
  claims -- only the first is true today.
- **WAVE's ESMF regridding is unavailable.** No ESMF build exists for
  arm64 macOS; `wave_exe.cmake` skips installing the
  `ESMF_RegridWeightGen` wrapper under APPLE instead of failing
  configure on a required `find_program`.
- **`io_netcdf_dll` is not built** (gfortran-general limitation, not
  macOS-specific -- see `doc/gnu-toolchain-support.md`).
- **Release codegen is portable by default, not machine-tuned.** The
  `D3D_NATIVE_CPU_TUNING` CMake option (off by default) appends
  `-mcpu=native -funroll-loops` for a build tuned to, and only meant to
  run on, the exact machine that built it. Do not turn this on for a
  binary you intend to copy to a different Mac, even one with the same
  Apple Silicon generation.
- **`-flto` is unavailable**: gfortran 16.1.0 hits an internal compiler
  error in the LTO streamer on one dflowfm_kernel source file.
- **Example 03** (D-WAQ transport, adaptive internal timestep) fails the
  strict cross-toolchain field-comparison gate against a Linux
  reference -- see `doc/gnu-toolchain-support.md`'s "What's supported"
  section for the exact, honest disposition; this is attributed to
  legitimate adaptive-dt trajectory divergence under independent
  compiler arithmetic, not a macOS-specific defect (examples 01/02, with
  no adaptive timestep, match to floating-point-epsilon level).

## Verified

Full `fm-suite` configure + build + serial CTest (361/361 passing, 1
disabled) on Apple Silicon (Apple Clang, Homebrew gfortran). The analytic
verification suite (`tools/verification_cases/`) passes 5/5. Public
examples 01 and 02 run to completion and match a Linux reference build to
floating-point-epsilon level.
