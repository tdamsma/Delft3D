# weekend-ai-experiments: what these branches are

This stack of four branches is a personal, out-of-hours exploration of
porting Delft3D FM to build and run natively on Apple Silicon with GNU
Fortran, plus the performance and portability work that came out of
doing so. It lives on a personal fork, not the upstream Deltares
repository.

## Honest attribution

This work was very heavily AI-agent-assisted: mostly Claude Code
sessions (Claude Fable 5, Anthropic), with some GPT-5.6 Sol (OpenAI /
Codex) assistance during the Linux-baseline phase that this work builds
on. It was human-directed and human-reviewed throughout -- goals, scope,
and acceptance were set by a human, agent output was read and checked
against build/test/benchmark evidence at every step, and this branch
stack itself is the product of a further human-directed review and
reconstruction pass that reorganized, re-verified, and rewrote the
original development history into the commit series here. It should be
read as a credible, evidence-backed engineering exploration produced
with heavy AI assistance, not as unreviewed AI output, and not as a
claim of unassisted human authorship either.

The full, unedited development history -- every intermediate commit,
including the session-by-session record of how this was actually built
-- is preserved on the fork's `mac-port` branch, which is the
full-provenance branch for everything in this stack. The four branches
here are a curated, reviewable reconstruction of that history: the same
end-state code, organized into logical commits with fresh commit
messages, excluding agent-operating instructions and session metadata
that don't belong in ordinary project history.

## The four branches

1. **`weekend-ai-experiments/gfortran-support`** -- OS-agnostic GNU
   Fortran (gfortran) toolchain support: cross-platform output
   validation tooling, an analytic verification suite, GNU
   compiler-option support, and a substantial family of genuine
   pre-existing bugs (unallocated-allocatable access, uninitialized
   state, an ABI mismatch) that ifx tolerated silently but gfortran's
   stricter runtime caught. See `doc/gnu-toolchain-support.md`.
2. **`weekend-ai-experiments/ieee-performance-fix`** -- one commit on
   top of the above: a two-line fix for a gfortran-specific performance
   bug (`ieee_arithmetic` imported at module scope, wrapping most of the
   simulation kernel in FPU-state save/restore calls) worth roughly
   7-8x at the canonical benchmark config. See
   `doc/ieee-wrapper-finding.md`.
3. **`weekend-ai-experiments/macos-port`** -- the Darwin-specific layer
   on top: Conan/toolchain detection, Darwin build-system support, and
   `__APPLE__` source branches, expressing macOS as its own platform
   rather than spoofing Linux. See `doc/building-macos.md`.
4. **`weekend-ai-experiments/benchmarks-and-tuning`** (this branch) --
   the benchmark harness and the results it produced: scaling curves,
   a whole-machine comparison against a Ryzen workstation, and power/
   thermal measurement. See `doc/benchmark-results.md`.

Each branch's tip was verified independently: the first two on Linux
(proving the GNU-toolchain work carries no Apple-specific dependency),
the third on Apple Silicon (a full native build, test suite, and example
run), and the fourth's harness with a smoke run. See each branch's own
documentation for its specific evidence.

## Where to look for more

- `doc/gnu-toolchain-support.md`, `doc/ieee-wrapper-finding.md`,
  `doc/building-macos.md`, `doc/benchmark-results.md` -- the four
  neutral, technical documents this stack adds, one per branch.
- The `mac-port` branch on this fork -- full development provenance,
  including the detailed, dated status reports this stack's docs were
  distilled from.
