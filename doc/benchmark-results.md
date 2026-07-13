# Benchmark results: scaling, power, and machine comparison

Distilled results from the benchmark harness in `tools/benchmarks/` (see
`tools/benchmarks/README.md` for the harness itself, tiers, and noise
policy). All numbers below were measured on a verified-idle machine (a
co-tenant background process on the shared Mac Studio was found to
inflate several early sequential references by 9-24%; every number here
is from the corrected, clean re-baseline, with a logged power/conditions
state alongside each run) at matched, verified step counts between any
two configs being compared.

Machines: an Apple Silicon Mac Studio (M3 Ultra, 24 P-cores + 8 E-cores)
running GNU Fortran, and an AMD Ryzen 7 3800X (8 cores/16 threads,
dual-channel DDR4) running GNU Fortran under the same compiler/MPI
toolchain, both against the same input models.

## Scaling curves

**M tier (8,355 cells, canonical config: `westerscheldt.mdu`, 6,532
steps):**

| Config | Mac (M3 Ultra) | Ryzen 3800X |
|---|---|---|
| Sequential, optimized | 24.27 s loop (3.72 ms/step) | 42.98 s loop (6.58 ms/step) |
| Best MPI config | 4.23 s @ 24 ranks | 8.19 s @ 8 ranks |

The M tier's small mesh saturates parallel benefit early on both
machines: MPI scaling on the Mac plateaus across 8-24 ranks (within
~10% of each other), with a real cliff at 32 ranks (E-core scheduling
effect, not a thread-count artifact). Whole-machine best-vs-best ratio:
**1.94x**.

**L tier (576k cells, long config: TStop=3000 s, 2,054 steps, verified
identical step counts on both machines):**

| Config | Mac (M3 Ultra) | Ryzen 3800X |
|---|---|---|
| Sequential, optimized | 670.04 s (326.2 ms/step) | 1341.36 s (653.1 ms/step) |
| Best MPI config | 47.1 s @ 24 ranks (the exact P-core count; rel sigma 0.25%) | 434.3 s @ 8 ranks (the physical core count) |

The Ryzen's MPI scaling flatlines at ~3.1-3.7x from 4 ranks on -- a
dual-channel-DDR4 memory-bandwidth wall -- and SMT (16 ranks on 8 cores)
is a net loss. Whole-machine best-vs-best ratio: **9.22x loop time** in
the Mac's favor.

Decomposition of the L-tier 9.22x (identity: per-core x core-count x
relative-parallel-efficiency):

- **2.00x per-core** throughput (bandwidth-heavy tier; the M tier's
  per-core ratio is lower, 1.77x, since it is more cache-resident).
- **3x real cores** (24 P-cores vs 8 physical cores; neither machine's
  extra hardware threads -- the Mac's E-cores, the Ryzen's SMT -- help
  at either machine's own best configuration).
- **1.53x relative parallel efficiency** (59% vs 39% at each machine's
  best config).

2.00 x 3 x 1.53 = 9.18, matching the measured 9.22x within rounding.

## Combined optimization ratio (IEEE fix + compiler flags)

At the canonical M-seq config, clean/matched: **191.17 s -> 24.27 s =
7.88x**, combining the `ieee_arithmetic` module-scope fix (the large
majority of this ratio) and Release compiler flag tuning (a further
small single-digit-percent win; see `doc/ieee-wrapper-finding.md` for the
IEEE fix in isolation).

## Power and thermal

- Idle: 5.8 W system-level draw (Mac Studio).
- Production config (L tier, 24 ranks, thermal steady state): **~158 W
  whole-system**, **3.66 J per timestep**.
- 40-minute soak test at the production config: temperature plateaus at
  73.5 degC, zero throttle events, loop-time drift +0.3% over 40 minutes
  (no thermal decay). One mid-soak excursion was traced to external
  CPU co-tenancy (a background process raising E-core usage from 10% to
  37%, temperatures flat throughout), not a thermal effect of the
  benchmark itself.

## Contention finding

While instrumenting power capture, a co-tenant GPU inference job was
caught at 114 W / 100% utilization while the benchmark machine was
believed idle. On a unified-memory machine, a saturated GPU competes
directly for the same memory bandwidth the L tier is designed to stress,
and this inflated several earlier "idle machine" sequential references
by 9-24%. Practical consequence adopted going forward: every benchmark
run in this harness should be taken on a verified-idle machine with a
logged power/conditions state alongside it -- "the machine felt idle" is
not evidence on a system with background resident services.

## Production context (honestly scoped)

This is indicative framing, not a benchmark: no comparable server-class
machine was available to measure directly.

- **Performance-per-watt** is plausibly this machine's strongest single
  metric: ~9.2x a Ryzen 3800X whole-machine at the L tier while drawing
  ~158 W measured at the SoC-reported level. For comparison, a
  dual-socket AMD Epyc "Turin" server node's CPU TDPs alone are 2x500 W
  before RAM, fans, and PSU losses -- TDP is a thermal design ceiling,
  not a measured draw, so this comparison is indicative only.
- **Acquisition cost per unit of memory bandwidth** (the resource this
  workload binds on at scale): the Mac Studio's ~819 GB/s in a
  ~$10-13k machine compares favorably with a ~576 GB/s theoretical
  (12-channel DDR5-6000) single-socket Epyc node at an estimated
  $15-25k -- the Mac delivers more bandwidth per dollar before even
  counting its per-core efficiency advantage.

## Reproduction

```bash
python tools/benchmarks/run_benchmark.py --tier M-seq
python tools/benchmarks/run_benchmark.py --tier L-mpi-long --ranks 24
```

See `tools/benchmarks/README.md` for the full tier catalog (S, M-seq,
M-mpi, L, L-mpi, L-long, L-mpi-long), the noise-reduction policy, and
profiling recipes (samply-based). Every measurement in this document
verified its own step count from the run's own log rather than assuming
a canonical duration -- ms/step does not normalize reliably across
mismatched run lengths on this workload, since per-step cost rises as
the simulated tidal signal develops.
