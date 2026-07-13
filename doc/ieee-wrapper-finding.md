# A two-line change that makes gfortran builds of Delft3D FM ~7-8x faster

Status: verified on two architectures (Apple Silicon, x86_64); candidate for upstream contribution (not yet submitted -- see "Upstream path").

## Executive summary

D-Flow FM's `precision_basics` module imported `ieee_arithmetic` at **module scope**. Because nearly every procedure in the codebase transitively uses this module (via `use precision`), and because **gfortran wraps every procedure that can see `ieee_arithmetic` in FPU-state save/restore calls**, virtually the entire simulation kernel was paying a per-call floating-point-environment tax -- invisible under Intel Fortran, which does not generate these wrappers.

Moving the import from module scope into the only two procedures that actually use it (measured on the Western Scheldt benchmark, step-loop time, step counts verified per run, all figures below from a clean, verified-idle re-baseline):

| Platform / compiler | Config | Before | After | Speedup |
|---|---|---|---|---|
| macOS arm64, gfortran (Apple Silicon) | M tier, 6,532 steps | 191.2 s | 24.3 s | **7.9x** |
| Linux x86_64, gfortran (Ryzen 3800X) | M tier, 1,663-step window | 222.0 s | 7.6 s | **28.75x** (window-specific, see "Magnitude") |
| Linux x86_64, ifx (control) | M tier, 6,532 steps | 44.7 s | 44.9 s | none (expected) |

The ratio depends on the workload window (the wrapper tax is per-procedure-call, so call-dense phases of the simulation pay more -- see "Magnitude"); at the canonical full-length config on a clean, verified-idle machine the effect is **7.88x**, and the 28.75x figure on Linux is a genuinely measured but shorter-window ratio. Outputs are unchanged in every A/B: field-level diffs at machine-precision level, identical timestep counts everywhere, the full unit-test suite and a 5-case analytic verification suite pass identically before and after.

**Whole-machine context:** with this fix plus the rest of this fork's build/parallelism work, an Apple Silicon workstation's best MPI configuration runs a mid-size tidal model **9.22x faster (loop time)** than an 8-core Ryzen 3800X's best MPI configuration on the same input, verified at matched step counts on both machines; decomposed as roughly 2.0x per-core throughput times 3x more real cores times ~1.5x better relative parallel efficiency at that config. This is whole-machine, best-vs-best context for the two-line change above -- not a claim that the IEEE fix alone accounts for it.

## The change

`src/utils_lgpl/deltares_common/packages/deltares_common/src/precision_basics.f90`:

```fortran
! BEFORE (module scope -- contaminates every transitive user of `precision`)
module precision_basics
   use, intrinsic :: ieee_arithmetic, only: ieee_is_nan, ieee_is_finite
   ...

! AFTER (procedure-local, in the only two consumers)
module precision_basics
   ...
contains
   function comparerealdouble_finite_check(...)
      use, intrinsic :: ieee_arithmetic, only: ieee_is_nan, ieee_is_finite
      ...
   function comparerealsingle_finite_check(...)
      use, intrinsic :: ieee_arithmetic, only: ieee_is_nan, ieee_is_finite
      ...
```

Semantics are identical -- the same intrinsics are available in exactly the procedures that call them.

## Mechanism

The Fortran standard requires that when IEEE modules are accessible in a scoping unit, the floating-point environment (rounding mode, halting mode, exception flags) behaves predictably across procedure boundaries. gfortran implements this conservatively: **any procedure whose scope can see `ieee_arithmetic` gets prologue/epilogue calls** (`_gfortrani_get_fpu_state`, `_gfortrani_set_fpu_state`, exception-flag bookkeeping) to save and restore the FPU environment.

With the import at module scope in a module as foundational as `precision_basics` -- re-exported through `precision`, which nearly every routine in dflowfm, gridgeom, and the shared libraries uses -- this wrapping applied to essentially the whole call graph, including tiny per-cell/per-link functions called millions of times per timestep.

Intel ifx does not generate equivalent per-procedure wrappers here, which is why the cost was invisible on the officially supported toolchain and went unnoticed.

## Evidence chain (how it was found and proven)

1. **Profile** (sampling profiler, macOS, RelWithDebInfo + frame pointers): the large majority of sequential samples land inside gfortran's FPU-state runtime.
2. **Disassembly**: hot leaf functions (e.g. `get_chezy`, slope limiters) each carried IEEE prologue/epilogue call sites before the fix, zero after. On Linux the whole-binary wrapper-call-site count dropped by roughly two orders of magnitude, down to the legitimate procedure-local users.
3. **Minimal reproducer**: a small module + caller reproduces the wrapping at every optimization level whenever `ieee_arithmetic` is visible at module scope.
4. **Counterfactual A/B**: identical source trees differing only in this hunk, same flags, same inputs, identical timestep counts within each A/B pair, on a verified-idle machine with a logged power/conditions state.
5. **Correctness gates on the fixed build**: full unit-test suite passing at parity with the pre-fix build; five analytic shallow-water cases with closed-form solutions pass at 12-13 significant digits of cross-platform parity; field-level diff of standard examples vs the pre-fix binary at machine precision.

## Magnitude: what the ratio depends on

The wrapper tax is paid **per procedure call**, so the speedup ratio tracks the call density of the simulated window, not the platform:

- At the canonical full-length M config (6,532 steps), on a clean verified-idle machine, the fix is worth **7.88x** end-to-end.
- A shorter 1,663-step window of the same model on Linux shows a larger ratio (28.75x) because per-step cost for the fixed binary is lower early in the run than at full length (the tidal signal, and with it per-step cost, develops over the run) -- i.e. that window is *more* call-overhead-dominated relative to its own per-step cost, which is why its ratio is larger. Both numbers are real measurements; they answer slightly different questions, and mixing windows when comparing across platforms is a documented pitfall (see "Correction history").
- Cross-platform, per-timestep, at the matched full-length config, the fixed gfortran build on Apple Silicon runs somewhat faster per step than the fixed gfortran build on the Ryzen -- consistent with hardware expectations for single-core throughput on these two parts.

## Who benefits

- **Every gfortran build of Delft3D FM, on any platform.** On identical hardware, gfortran+fix now matches ifx per-step; before the fix it was many times slower -- effectively unusable for production. This matters for external developers building without Intel licenses, HPC sites, and packaging ecosystems.
- **Intel builds are unaffected** -- measured neutral on ifx, as predicted by the mechanism. A separate flag-tuning sweep on ifx (`-O3`, `-xHost`, `-ipo`) found at most a small, sub-2% effect, confirming the shipped `-O2` is near-optimal for ifx on this workload.
- The same audit pattern likely applies to other large Fortran codebases: `grep -rn "use.*ieee_arithmetic" --include="*.f90"` for module-scope imports in widely-used foundation modules is a cheap check with potentially large payoff under gfortran.

## Upstream path

This repository is a personal fork; nothing has been submitted upstream yet. The change is self-contained, standard-conforming, semantics-preserving, and measured-neutral on the officially supported Intel toolchain, which makes it a low-risk upstream candidate. A companion set of correctness fixes found during the same body of work (unallocated-allocatable access, uninitialized components, a NEFIS C-interop ABI mismatch -- genuine undefined behavior that ifx currently tolerates) is upstream-worthy independently of performance; see the GNU-toolchain-support documentation in this series. Submission requires the fork owner's explicit decision.

## Reproduction

- macOS benchmark harness: `tools/benchmarks/` (`run_benchmark.py --tier M-seq`). The canonical M config is 6,532 timesteps; every measurement should verify the actual step count from the run's own log, not assume it.
- Linux gfortran environment: this series' three gfortran-on-Linux portability fixes (see the GNU-toolchain-support documentation) make a from-scratch gfortran build on Linux possible; the Linux A/B above was run with gfortran and Open MPI in a containerized toolchain with PETSc and preCICE prebuilt.

## Correction history

An earlier comparison mixed runs with mismatched simulated durations (1,663 vs 6,532 timesteps), producing spurious cross-platform conclusions. A step-count audit corrected these to the per-step, matched-config numbers above. A later re-baseline on a verified-idle machine (a co-tenant background process had inflated several earlier sequential references by roughly 9-24%) produced the clean 7.88x headline used here; the within-A/B speedup ratios and the underlying mechanism were never affected by either correction.
