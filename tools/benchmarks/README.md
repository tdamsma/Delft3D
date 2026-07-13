# D-Flow FM macOS benchmark harness

This is the measurement infrastructure for the Delft3D macOS port. It is
deliberately *not* an optimization pass -- the port's numerical correctness
was already verified separately ("Numerical verification report"). This
harness exists so that when optimization work does start, it is driven by
numbers instead of guesses.

Scope: one Mac Studio, all cores and/or GPU, up to 256 GiB RAM. No
multi-node/distributed work (explicitly out of scope for this harness).

## Contents

| File | Purpose |
|---|---|
| `tiers.json` | Model tier definitions: S, M-seq, M-mpi3, M-mpi (rank-parameterized), L |
| `bench_lib.py` | Shared helpers: `.dia` timer parsing, `/usr/bin/time -l` parsing, environment capture, process-tree RSS polling, MPI rank-count override |
| `run_once.py` | The single invocation hyperfine repeats (warm-up + N timed runs) |
| `run_benchmark.py` | Orchestrator: stages a disposable run dir, drives hyperfine, aggregates RSS/timers/environment into one JSON |
| `compare_benchmarks.py` | Diffs two `run_benchmark.py` JSON result sets and flags regressions beyond measured noise |
| `samply_top.py` | Ranked self/inclusive-time function list from a `samply record --save-only --unstable-presymbolicate` profile (joins the `.syms.json` sidecar; demangles `__module_MOD_proc`) |
| `samply_attr.py` | Same, but re-attributes samples landing in gfortran's IEEE FPU-state runtime to the nearest caller -- that runtime otherwise dominates raw sample counts in gfortran profiles, obscuring the actual hot functions |

### Rank-count scaling sweep additions (2026-07-11)

- **`run_benchmark.py --ranks N`** (mode=mpi tiers, i.e. `M-mpi`): rewrites the
  partition step's `ndomains=N`, mpirun's `-np N`, and the staged
  `dimr_config.xml`'s `<process>` rank-id list (`0 1 2` -> `0..N-1`), so one
  tier definition covers the whole rank sweep. Verified against N in
  {1,2,4,8,16,24,32}. Two empirical notes baked into the code: the partition
  step accepts the degenerate `ndomains=1`, and at 1 rank dflowfm runs the
  *unpartitioned* model so its `.dia` keeps the unpartitioned name
  (`westerscheldt.dia`, not `_0000`) -- `run_benchmark.py` falls back
  accordingly.
- **`--conditions exclusive-baseline`** is the label for real baselines taken
  with the machine guaranteed otherwise idle (no other concurrent workloads);
  it is publishable like `baseline`.
- This measurement round's model-config choices (M tier `TStop`
  120 -> 560 min; L tier `TStop` 900 -> 300 s, which must stay a multiple of the
  300 s his/map interval or dflowfm aborts at startup) are recorded here for
  reference; the edited `.mdu`s live in gitignored
  `baseline_artifacts/`/`baseline_runs/`, so re-apply those two TStop edits
  after regenerating either model before comparing against recorded
  baselines.

No third-party Python packages are required -- everything is standard
library, so any Python 3.9+ works (the validation venv at
`baseline_tools/dfm-validation` is unrelated and not needed here).

## Quick start

```bash
cd /path/to/Delft3D

# S tier (example 01, 222 cells) -- seconds, sanity/regression check
python3 tools/benchmarks/run_benchmark.py --tier S \
  --json-out baseline_logs/benchmarks/S.json

# M tier, sequential (example 02 mesh, Western Scheldt, 8,355 cells)
python3 tools/benchmarks/run_benchmark.py --tier M-seq \
  --json-out baseline_logs/benchmarks/M-seq.json

# M tier, 3-rank MPI via dimr
python3 tools/benchmarks/run_benchmark.py --tier M-mpi3 \
  --json-out baseline_logs/benchmarks/M-mpi3.json

# Compare two result sets (e.g. before/after a change, or two separate runs)
python3 tools/benchmarks/compare_benchmarks.py \
  baseline_logs/benchmarks/M-seq-before.json \
  baseline_logs/benchmarks/M-seq-after.json
```

Useful flags on `run_benchmark.py`:

- `--repeats N` (default 5) -- timed repeats hyperfine performs.
- `--warmup N` (default 1) -- untimed warm-up runs before timing starts
  (populates dflowfm's `.cache` flow-node-numbering cache so the first timed
  repeat isn't penalized by one-time setup cost).
- `--conditions LABEL` -- free-text label stored in the result JSON's
  `conditions` field. Use `--conditions validation-plumbing-check` (the
  default is `baseline`) whenever you're proving the harness works rather
  than taking a real measurement -- e.g. because another process is
  generating models or otherwise loading the machine concurrently. The JSON's
  `conditions.publishable` field is only `true` for `baseline`.
- `--output-dir` -- where disposable run dirs are staged (default
  `baseline_runs/benchmarks/<tier>/run-<timestamp>/`; gitignored, same as the
  rest of `baseline_runs/`).
- `--cleanup` -- remove the disposable run dir after writing the result JSON
  (off by default -- run dirs are kept for post-hoc inspection/profiling
  since they're cheap: the S/M tiers are a few MB each).

Each run is staged fresh from the pristine example sources under
`baseline_artifacts/deltares-examples/extracted/examples/`, never from a
previous run's output, so repeated invocations never accumulate state beyond
the harness's own `.bench_meta/` bookkeeping directory inside the run dir.

## Tiers (`tiers.json`)

- **S** -- example 01 (222 cells). Direct `dflowfm --autostartstop f34.mdu`,
  sequential, no MPI, no dimr. Seconds-scale.
- **M-seq** -- example 02's Western Scheldt mesh (8,355 cells), run
  sequentially: `dflowfm --autostartstop westerscheldt.mdu`, the unpartitioned
  `.mdu` with zero tweaks (this runs fine sequentially, verified separately
  on Linux). This is the scaling workhorse's single-rank baseline.
- **M-mpi3** -- same mesh, 3-rank MPI via dimr. `run_benchmark.py` runs an
  untimed partition step once per staged run dir
  (`dflowfm --partition:ndomains=3:icgsolver=6 westerscheldt.mdu`, matching
  the real invocation logged in `baseline_logs/example-02-partition-macos.log`),
  then times `mpirun --bind-to none -np 3 -x DYLD_LIBRARY_PATH dimr dimr_config.xml`
  repeatedly.
- **L** -- placeholder in early tier definitions. The generator for this
  tier, `tools/benchmarks/l_tier/generate_l_model.py`, was developed
  independently of this harness (see `l_tier/README.md`) -- it
  Casulli-refines example 02's Western Scheldt mesh via meshkernel into a
  flat directory (`<stem>.mdu`/`_net.nc`/`.ext` + boundary aux files + a
  `generation_metadata.json`, no `dflowfm/` subfolder or `dimr_config.xml`;
  sequential/OpenMP-only, no MPI for this tier). `tiers.json`'s `_comment` on
  the `"L"` entry spells out exactly which fields to fill in once a model has
  been generated with it (`source_dir`, `mdu`, `status: "ready"`); no
  `run_benchmark.py`/`run_once.py` code changes are needed since the flat
  layout already fits the same `source_dir`/`case_subdir` staging model as
  S/M (`case_subdir` is just `"."`).
- **L-mpi** -- the L tier's 576,000-cell
  synthetic channel, N-rank MPI via **direct dflowfm, not dimr** (the L model
  ships no `dimr_config.xml`). New tier mode `mpi_direct`: an untimed
  partition step (`dflowfm --partition:ndomains=N:icgsolver=6 l_tier.mdu`,
  ~2-14 s wall depending on N -- measured informally, not part of the
  hyperfine timing), then `mpirun --bind-to none -np N dflowfm
  --autostartstop l_tier.mdu` -- dflowfm invoked under MPI auto-loads the
  partitioned `l_tier_NNNN.mdu` files itself. No `-x DYLD_LIBRARY_PATH`
  needed (unlike the dimr tiers): the standalone binary's `@rpath` entries
  are absolute. `--ranks N` works the same as on M-mpi. Seq-vs-MPI output
  equivalence is checked at the map-field level with
  `l_tier/compare_seq_vs_mpi_map.py` (the L model has no observation
  stations, so the M-tier his-file convention doesn't apply); see that
  script's docstring for the cell-renumbering gotcha it works around.

## Noise policy

By convention: **a benchmark is usable when relative standard deviation is
below ~2% on the M tier.** `run_benchmark.py` computes this automatically
(`timing_s.relative_stddev` = `stddev / mean` across hyperfine's timed
repeats) and records `timing_s.noise_policy.pass` (threshold hardcoded at
0.02, tier-agnostic in the code but the policy's target is specifically
M-seq/M-mpi3). Practical guidance:

- Increase `--repeats` if a run is noisy (5 is a reasonable default; the
  validation runs below used 3 to keep the plumbing check short and still
  landed well under 1% relative sigma on both M tiers).
- Always use at least one `--warmup` run -- the first invocation after
  staging includes flow-node-numbering cache generation, which is a
  significant one-time cost relative to the S tier's ~1.7s runtime.
- **P-core vs E-core scheduling is a variance source on Apple Silicon.**
  This M3 Ultra is 24 P-cores + 8 E-cores (`sysctl hw.perflevel0.physicalcpu`
  / `hw.perflevel1.physicalcpu`). macOS has **no processor-affinity API**
  (no `sched_setaffinity`/`taskset` equivalent) -- the scheduler places
  threads based on QoS class, and a benchmark process can occasionally get
  scheduled partly onto E-cores, which shows up as a wall-time outlier rather
  than a re-runnable difference. Two practical implications:
  - For MPI, always pass `--bind-to none` (already baked into `tiers.json`'s
    `M-mpi3.mpirun_args`) -- Open MPI's normal `--bind-to core`/`--bind-to
    socket` binding relies on `hwloc` affinity calls that don't work the same
    way on macOS; `--bind-to none` avoids Open MPI fighting the (nonexistent)
    affinity API and just lets the OS scheduler place ranks.
  - The closest thing macOS offers to a scheduling hint is a **QoS clamp**,
    via `taskpolicy -c <utility|background|maintenance>`, which biases (does
    not force) a process toward E-cores. This is useful for *deliberately*
    sampling E-core-only-ish performance as a reference point, e.g.:
    ```bash
    taskpolicy -c utility python3 tools/benchmarks/run_benchmark.py --tier M-seq --conditions e-core-biased
    ```
    but it is a bias, not a guarantee, and should not be treated as
    equivalent to Linux `taskset`/`sched_setaffinity` pinning. Record when
    it's used (the `conditions` field is a good place) rather than silently
    mixing biased and unbiased runs into one comparison.
- Keep the machine otherwise idle during a real (non-validation) benchmark
  session; `run_benchmark.py` records `pmset -g therm` output before and
  after specifically so a thermal-pressure event coinciding with an outlier
  run is visible after the fact rather than silently blamed on "noise".

## Result JSON schema (informal)

Top-level fields written by `run_benchmark.py` (schema_version 1):

- `tier`, `description`, `mode`, `ranks`
- `conditions.{label,publishable}`
- `run_dir`, `generated_at`, `any_repeat_failed`
- `repeats.{requested,warmup,recorded}`
- `timing_s.{mean,stddev,min,max,median,times,relative_stddev,noise_policy}`
  -- straight from hyperfine's `--export-json`.
- `rss.time_dash_l.{max_bytes,mean_bytes,per_repeat_bytes}` -- from
  `/usr/bin/time -l`'s "maximum resident set size" (bytes on macOS's BSD
  `time`, confirmed empirically -- **not** kilobytes like GNU `time -v` on
  Linux). Absent for the M-mpi3 tier; see "Open issues" below.
- `rss.process_tree.{max_bytes,mean_bytes,per_repeat_bytes}` -- supplementary
  cross-check: every 100ms, sums RSS across the benchmarked process and all
  of its live descendants (via `ps -axo pid=,ppid=,rss=`), tracks the peak.
  This is the only RSS source for M-mpi3.
- `dia_timers.fields.*` -- the parsed `.dia` step-loop timing block from the
  **final** repeat (see "`.dia` timer format" below); `dia_timers.mpi_enabled`,
  `dia_timers.openmp_threads`.
- `thermal_pressure.{before,after}` -- raw `pmset -g therm` text.
- `environment.{before,after}` -- `sw_vers`, `sysctl hw.*`, compiler
  versions, git commit/branch/dirty state, captured both before staging and
  after the timed repeats finish (a long M/L-tier session is exactly when
  environment drift -- a `git commit` in another terminal, a compiler
  upgrade -- would matter).
- `hyperfine_raw` -- the unmodified hyperfine result object, kept for
  anything not surfaced above.

## `.dia` timer format (what `bench_lib.parse_dia_timers` reads)

**Important, non-obvious finding:** a completed dflowfm run's diagnostics do
**not** live in a top-level `unstruc.dia` in the working directory. Every
example's `.mdu` sets `OutputDir = dflowfmoutput`, so the real file is
`<workingDir>/dflowfmoutput/<mduBaseName>.dia` (e.g.
`dflowfm/dflowfmoutput/f34.dia` for example 01, or
`dflowfm/dflowfmoutput/westerscheldt_0000.dia` for rank 0 of the MPI tier).
Several existing debug run directories under `baseline_runs/`
(`bin-snapshot`, `crash-debug`, `release-verify`, `verification-macos`) each
have a 4-line stub `unstruc.dia` sitting next to the real file -- it's
written before the `.mdu` is parsed and never flushed with real content.
Anything that consumes dflowfm diagnostics should look under
`dflowfmoutput/`, not at the stub.

The timing block at the end of a completed `.dia` looks like (real excerpt,
`baseline_runs/release-verify/lake_at_rest/dflowfmoutput/lake_at_rest.dia`):

```
** INFO   : extra timer:Sethuau                                              0.0284280777
** INFO   : extra timer:Compute advection term                               0.0511376858
** INFO   : nr of timesteps        ( )  :           398.0000000000
** INFO   : total computation time (s)  :             0.1634209156
** INFO   : time modelinit         (s)  :             0.0181639194
** INFO   : time steps (+ plots)   (s)  :             0.1452569962
** INFO   : time solve             (s)  :             0.0146598816
** INFO   : time totalsolve        (s)  :             0.0100000000
** INFO   : time transport         (s)  :             0.0210000000
** INFO   : Computation started  at: 07:56:00, 11-07-2026
** INFO   : Computation finished at: 07:56:01, 11-07-2026
** INFO   : MPI    : no.
** INFO   : OpenMP : yes.         #threads max : 1
```

`parse_dia_timers` slugifies every "label (unit) : value" and "extra
timer:label   value" line generically (e.g. `time solve (s)` ->
`time_solve`, `extra timer:Compute advection term` ->
`extra_timer_compute_advection_term`), so new timer lines added upstream show
up automatically without a parser change. One filter is applied: the
periodic progress-table row (`Sim. time done / Sim. time left / ...`, which
looks like `0d  0:02:00   0d  0:58:00   ...   0.00000`) is skipped by
detecting >=2 colons in the candidate label (real timer lines have exactly
one, the `label (unit)  :  value` separator; clock-style `H:MM:SS` tokens
contribute two each).

Because the harness's `--prepare` hook wipes `dflowfmoutput/` before every
timed repeat (so each repeat writes clean output rather than appending),
`dia_timers` in the final JSON reflects the **last** repeat only -- this is
representative (repeats are deterministic runs of the same input) but is
worth knowing if you go looking for per-repeat timer variance; it isn't
recorded (only wall time and RSS are, per-repeat, in `.bench_meta/repeat-*.json`
inside the run dir).

## Open issues for the real baseline measurement

1. **`/usr/bin/time -l` cannot wrap the MPI invocation.** `/usr/bin/time` is
   an Apple SIP-restricted system binary; dyld strips all `DYLD_*`
   environment variables before executing anything through it. Confirmed
   empirically:
   ```bash
   export DYLD_LIBRARY_PATH=/tmp/probe
   /usr/bin/time -l python3 -c "import os; print(os.environ.get('DYLD_LIBRARY_PATH'))"
   # -> None
   python3 -c "import os; print(os.environ.get('DYLD_LIBRARY_PATH'))"
   # -> /tmp/probe
   ```
   Since M-mpi3 needs `DYLD_LIBRARY_PATH` to reach dimr (see finding 2 below),
   `run_once.py` does **not** wrap the MPI command in `time -l` at all -- RSS
   for that tier comes only from the process-tree `ps` poll. Consequence:
   M-mpi3's `rss.time_dash_l` is absent from the JSON, and its
   `rss.process_tree` peak (sum across `mpirun` + 3 `dimr` processes) is not
   directly comparable to S/M-seq's `rss.time_dash_l` (single-process,
   different measurement method) even though both are "peak RSS". A cross-
   check during validation: M-seq's single-process RSS was ~115 MB
   (`time_dash_l`) vs. ~334 MB for M-mpi3's 3-rank process-tree total --
   roughly 3x, which is the expected relationship and a reasonable sanity
   check to repeat once real (non-validation) numbers are collected.
2. **dimr needs `DYLD_LIBRARY_PATH` and Open MPI needs `-x` to forward it.**
   `dimr` `dlopen()`s `libdflowfm.dylib` as a runtime plugin -- confirmed
   absent from `otool -L build_fm-suite_release/dimr/dimr`, i.e. it is not a
   linked dependency and gets no automatic `@rpath` treatment. Without
   `DYLD_LIBRARY_PATH` including `build_fm-suite_release/dflowfm_lib`, dimr
   aborts with `Cannot load component library "libdflowfm.dylib"`. Less
   obviously: setting `DYLD_LIBRARY_PATH` in `mpirun`'s own environment is
   **not** sufficient -- Open MPI does not forward arbitrary environment
   variables to the ranks it launches unless told to with `-x VARNAME`;
   without it, all 3 ranks fail with the identical dlopen error even though
   `mpirun` itself has the variable set. Both are baked into
   `tiers.json`'s `M-mpi3.mpirun_args` (`--bind-to none -np 3 -x
   DYLD_LIBRARY_PATH`) with an on-record comment; worth knowing if the L
   tier or a future rank-count sweep needs to reconstruct the
   `mpirun` command line by hand. The standalone `dflowfm` binary needs no
   `DYLD_LIBRARY_PATH` at all -- its `@rpath` entries are baked in absolute
   at link time (verified with `otool -l`), so this only affects the dimr
   path.
3. **`xcrun xctrace` is not currently available on this machine.** It
   requires full `Xcode.app`; only the Command Line Tools are installed
   (`xcode-select -p` -> `/Library/Developer/CommandLineTools`). The Time
   Profiler recipe below is recorded as a ready-to-run command for whenever
   Xcode.app is installed, not verified end-to-end here. `sample` (part of
   CLT) is confirmed present and usable today.
4. **`samply` is installed** (0.13.1 via `brew install samply`, verified
   2026-07-11). For scriptable text extraction record with
   `samply record -r 500 --save-only --unstable-presymbolicate -o p.json.gz -- <cmd>`
   and parse with `samply_top.py` / `samply_attr.py` (this directory) -- the
   plain saved profile contains raw addresses only (samply symbolicates
   lazily when serving to the browser); the `--unstable-presymbolicate`
   sidecar `.syms.json` is what makes offline symbolication possible.
5. **Wall-time repeatability was excellent in validation** (see below,
   ~0.1-0.6% relative sigma on all three tiers) **on a lightly loaded
   machine** with another process doing Python-side model generation
   concurrently. A real baseline measurement should confirm this holds with
   the machine otherwise idle, and should re-check the noise policy at
   `--repeats 5` (validation used 3 to keep the check short).
6. **RSS accounting for MPI is a sum-of-processes approximation.** The
   `process_tree` poll samples `ps` every 100ms and is therefore a discrete
   approximation of the true peak (it can miss a brief spike between
   samples); it is expected to be a reasonable-not-exact number, adequate for
   regression tracking via `compare_benchmarks.py` but not for
   memory-bandwidth-level precision (that's what Instruments' Counters/
   Allocations profiling is for).
7. **The L tier is a placeholder.** `tiers.json`'s `"L"` entry has
   `"status": "pending"` and no `source_dir`; `run_benchmark.py --tier L`
   will raise a clear `SystemExit` until it is filled in.

## Validation runs (plumbing check, not baselines)

To prove the harness end-to-end without claiming publishable numbers (the
machine had another process generating models concurrently), each tier was
run once with `--repeats 3 --warmup 1 --conditions validation-plumbing-check`:

| tier | mean wall time | relative sigma | RSS (peak) | timesteps |
|---|---|---|---|---|
| S | 1.738 s | 0.56% | 77.5 MB (`time -l`) | 3018 |
| M-seq | 19.561 s | 0.22% | 117.3 MB (`time -l`) | 559 |
| M-mpi3 | 8.373 s | 0.11% | 334.4 MB (process-tree, 3 ranks + mpirun) | 559 |

All three comfortably clear the 2% noise-policy threshold even at only 3
repeats on a non-idle machine; JSON written, `.dia` timers parsed (41 fields
for S, matching structure for M), RSS captured via both methods where
applicable. Full JSON: `baseline_logs/benchmarks/validation-{S,M-seq,M-mpi3}.json`.
These are explicitly **not** baseline numbers (`conditions.publishable:
false` in each JSON) -- re-run with `--conditions baseline` on an idle
machine, at `--repeats 5` or more, for the real baseline measurement.

## Profiling recipes

Build a profiling-flavored binary first -- `Release` optimizes away frame
pointers and inlines aggressively enough to make stacks hard to read:

```bash
cd /path/to/Delft3D
CONAN_HOME="$PWD/.conan2-macos" python3 build.py --config fm-suite --build --build-type RelWithDebInfo
```

`RelWithDebInfo` gives `-O2 -g`. Add `-fno-omit-frame-pointer` for clean
stacks -- gfortran, like GCC generally, will omit frame pointers at `-O2`
otherwise, which makes sampling profilers misattribute time.
`build.py` has no pass-through for arbitrary CMake flags, but the per-config
flag variables are ordinary CMake *cache* variables (gnu.cmake only hard-sets
the base `CMAKE_Fortran_FLAGS`), so the route used for these baseline
profiles (verified 2026-07-11, build dir `build_dflowfm_relwithdebinfo`) is
configure-then-override:

```bash
# 1. conan install + configure only (no --build):
CONAN_HOME="$PWD/.conan2-macos" python3 build.py --config dflowfm \
  --build-type RelWithDebInfo --build-dir build_dflowfm_relwithdebinfo
# 2. append -fno-omit-frame-pointer to the per-config cache vars:
cmake -DCMAKE_Fortran_FLAGS_RELWITHDEBINFO="-O2 -g -fno-omit-frame-pointer" \
      -DCMAKE_C_FLAGS_RELWITHDEBINFO="-O2 -g -DNDEBUG -fno-omit-frame-pointer" \
      -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-O2 -g -DNDEBUG -fno-omit-frame-pointer" \
      build_dflowfm_relwithdebinfo
# 3. build just the CLI target:
cmake --build build_dflowfm_relwithdebinfo --target dflowfm-cli --parallel
```

### CPU: Instruments Time Profiler (xctrace CLI)

Requires full Xcode.app (see "Open issues" #3 -- not yet installed here):

```bash
xcrun xctrace record --template 'Time Profiler' --output /tmp/dflowfm-M-seq.trace \
  --launch -- build_fm-suite_release/dflowfm_cli_exe/dflowfm --autostartstop westerscheldt.mdu
open /tmp/dflowfm-M-seq.trace   # opens in Instruments.app for flame graph / heaviest-stack analysis
```

For the MPI tier, launch under `mpirun` the same way and use `--attach`
against a known rank's PID instead of `--launch`, since `xctrace` traces one
process tree at a time:

```bash
mpirun --bind-to none -np 3 -x DYLD_LIBRARY_PATH \
  build_fm-suite_release/dimr/dimr dimr_config.xml &
sleep 1   # let ranks start
xcrun xctrace record --template 'Time Profiler' --output /tmp/dflowfm-rank0.trace --attach "$(pgrep -n dimr)"
```

### CPU: `samply` (shareable flamegraphs, no Xcode needed)

```bash
brew install samply   # installed (0.13.1), verified 2026-07-11
# interactive: opens a flamegraph in the browser (firefox-profiler UI)
samply record build_dflowfm_relwithdebinfo/dflowfm_cli_exe/dflowfm --autostartstop westerscheldt.mdu
# scriptable (what these baseline profiles used): save + presymbolicate, then
# extract a ranked hotspot table offline -- the plain saved profile has raw
# addresses only, the .syms.json sidecar carries the symbol tables:
samply record -r 500 --save-only --unstable-presymbolicate \
  -o profile.json.gz -- build_dflowfm_relwithdebinfo/dflowfm_cli_exe/dflowfm --autostartstop westerscheldt.mdu
python3 tools/benchmarks/samply_top.py profile.json.gz 20    # raw self-time ranking
python3 tools/benchmarks/samply_attr.py profile.json.gz 20   # gfortran IEEE-FPU runtime re-attributed to callers
```

### CPU: `sample` (quick look, already installed via CLT)

```bash
build_fm-suite_release/dflowfm_cli_exe/dflowfm --autostartstop westerscheldt.mdu &
sample $! 10 -f /tmp/dflowfm-sample.txt   # 10 seconds, symbolicated text report
```

For MPI, `sample` each rank's PID separately (they're separate processes,
unlike threads within one process):

```bash
mpirun --bind-to none -np 3 -x DYLD_LIBRARY_PATH \
  build_fm-suite_release/dimr/dimr dimr_config.xml &
sleep 1
for pid in $(pgrep dimr); do sample "$pid" 10 -f "/tmp/dflowfm-rank-$pid.txt" & done
wait
```

### Memory/bandwidth: Instruments Allocations + CPU Counters

GUI-only (no useful CLI equivalent for live counters): `Instruments.app` ->
new document -> "Allocations" template for heap growth/leak-shaped
regressions, or "CPU Counters" template for the memory-bound-vs-compute-bound
classification that matters for this workload -- Delft3D's solvers are
typically bandwidth-bound, and the M3 Ultra's ~800 GB/s memory bandwidth is
the headline optimization opportunity. Attach to a running `dflowfm`/`dimr`
PID the same way as the
`xctrace --attach` example above, or launch directly from Instruments.app.

### MPI: per-rank timing

The harness's own `dia_timers` already gives per-rank internal timing
(pointed at rank 0's `.dia` by default via `tiers.json`'s
`M-mpi3.dia_path_template`; the sibling `westerscheldt_0001.dia` /
`_0002.dia` files in the same run dir have the same block per rank if you
need to compare ranks against each other for load imbalance). Open MPI's own
timing (`mpirun --report-bindings`, or `OMPI_MCA_orte_timing=1`) is a
lower-effort alternative to instrumenting the code by hand. No cross-node
tooling is relevant here -- multi-node is explicitly out of scope for this
port.
