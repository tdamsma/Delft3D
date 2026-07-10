# AGENTS.md

## Mission

Port Delft3D to macOS, using this Mac Studio as the eventual native development and build machine.

All development belongs in `tdamsma`'s private Delft3D fork. Nothing may be pushed to a public remote, submitted upstream, published as a PR, or otherwise made public without the user's explicit approval. Before any push, verify the destination remote URL and that the repository is private.

Work in two deliberately separate phases:

1. Establish a reproducible, tested Linux baseline on the Pop!_OS desktop.
2. Only after that baseline is credible, begin the macOS port in this checkout.

Do not blur Linux baseline failures together with macOS porting failures. Record enough detail that every macOS difference can be compared with a known-good Linux result.

## Current phase: Linux baseline

The Linux host is reachable over Tailscale:

```text
ssh thijs@100.89.33.91
```

Treat the remote host as a user-owned machine:

- Start with read-only discovery of its OS, compilers, Python, CMake, Conan, container tooling, disk space, repository state, and existing build artifacts.
- Preserve unrelated files, processes, repositories, and local changes.
- Explain and request approval before installing packages, changing system configuration, deleting artifacts, or making other broad/destructive changes.
- Prefer a containerized Linux build as recommended by `CLAUDE.md`, unless discovery shows a concrete reason not to.
- Use the repository wrappers `run_conan.py` and `build.py`, rather than invoking Conan and CMake directly.
- Begin with `fm-suite` unless the user changes the target. Keep build type, Conan profile/source, commands, commit, and environment recorded.

## Linux completion gate

Before starting macOS changes, produce a concise baseline report containing:

- Linux distribution/architecture and relevant hardware details.
- Repository URL, branch, commit, and working-tree state.
- Confirmation that any development remote is `tdamsma`'s private fork.
- Compiler and dependency-tool versions.
- Exact configure/build/install commands and whether they are reproducible from a clean build directory.
- Build products and basic executable smoke-test results.
- CTest totals, failures, skips, labels/configuration used, and logs for failures.
- Relevant integration or regression tests that were run, plus tests not run and why.
- Known warnings, environment assumptions, external data requirements, and remaining uncertainties.

The gate is satisfied only when the selected Linux suite builds successfully and its relevant tests are understood. A test failure may be accepted only when it is investigated and clearly documented as an existing/environmental limitation rather than silently ignored.

## Preparing for the macOS port

While establishing the Linux baseline, capture likely portability constraints without changing macOS code yet:

- Fortran compiler and preprocessor assumptions.
- Intel-specific flags, directives, runtime libraries, and Windows/Linux conditionals.
- GNU/Linux-only APIs, linker flags, RPATH behavior, shell utilities, and filesystem assumptions.
- Conan recipes and dependency binaries available for Apple Silicon.
- CMake platform checks and hard-coded architecture/compiler logic.
- Test data paths, case sensitivity, line endings, and runtime environment variables.

When the Linux gate is met, propose a staged macOS plan before implementing it. Prefer small, reviewable changes that preserve Linux behavior and add macOS CI/build/test coverage where practical.

## Repository conventions

Follow `CLAUDE.md` for project layout, build commands, tests, formatting, and branch naming. In particular:

- The CMake source root is `src/cmake`.
- Linux builds are normally containerized.
- Tests run through CTest and use `DATA_PATH` for runtime test data.
- Do not reformat `flow2d3d` or `third_party*`; use the repository fprettify configuration elsewhere.
- Never discard user changes or use destructive Git commands without explicit approval.

## Working style

- Lead with evidence: inspect first, then change.
- Keep a running command/result record for long build and test work.
- Report blockers with the exact failing command and the useful portion of its output.
- Continue through safe diagnostic and verification steps without waiting for confirmation; pause for credentials, system changes, destructive actions, or choices that materially alter scope.
- Keep Linux baseline artifacts and macOS port artifacts clearly named and separate.
