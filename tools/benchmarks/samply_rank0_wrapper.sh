#!/bin/bash
# Wrapper invoked once per MPI rank by mpirun: the target rank (0 by default,
# override via SAMPLY_TARGET_RANK) runs under `samply record` (self-time
# sampling profiler); every other rank runs the binary directly so it
# doesn't fall behind and skew the collective timing/synchronization the
# profiled rank is part of. Used for production-config profiling of the
# L-mpi tier (N ranks).
#
# Usage (inside an `mpirun --bind-to none -np N ...` invocation, cwd set to
# the staged run directory):
#   SAMPLY_OUT=/path/to/out.profile.json.gz [SAMPLY_TARGET_RANK=0] \
#     mpirun ... samply_rank0_wrapper.sh <dflowfm-binary> <dflowfm-args...>
set -e
DFLOWFM_BIN="$1"
shift
TARGET_RANK="${SAMPLY_TARGET_RANK:-0}"
if [ "${OMPI_COMM_WORLD_RANK:-0}" -eq "$TARGET_RANK" ]; then
  exec samply record -r 1000 --save-only --unstable-presymbolicate \
    -o "${SAMPLY_OUT:?SAMPLY_OUT not set}" \
    -- "$DFLOWFM_BIN" "$@"
else
  exec "$DFLOWFM_BIN" "$@"
fi
