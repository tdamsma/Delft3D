#!/usr/bin/env python3
"""Node-by-node cross-platform field comparison for the public example outputs.

For each baseline example, compare the map/his NetCDF output produced on one
platform/build against a reference produced on another (e.g. a new toolchain
against the officially supported one), variable by variable, over every
shared output timestep. Reports RMS and max-abs absolute and relative
differences, per timestep and overall, and evaluates each variable against
the following tolerance tiers:

- ``deterministic``  (~1e-10 relative): bit-reproducible arithmetic.
- ``iterative``      (~1e-6 .. 1e-4 relative): compiler math reassociation
  and the iterative PETSc solve legitimately diverge at this scale.
- ``adaptive_transport`` (~1e-2 relative): example 03 couples an adaptive
  internal timestep to D-WAQ transport; the fixed *output* times still line
  up exactly, but the internal trajectories differ enough to move tracer
  extrema by O(1e-3), which is expected and documented in the plan.

This does not replace validate_examples.py (topology/finite-value smoke
checks); it is a separate, heavier numerical comparison.

Gate semantics
--------------
This script is meant to be usable as a pass/fail gate (CI or a manual
completion check), not just a report generator:

- **Finite-value masks must agree** between the two platforms at every
  timestep. If one platform has a finite value at a node/time where the
  other has NaN/fill (and it is *not* the case that both platforms are
  entirely non-finite there -- which does legitimately happen, e.g. a
  D-WAQ tracer that stops being written past a certain time on both
  platforms), that is a parity defect and is reported as a hard ``fail``,
  never silently dropped from the comparison.
- **Near-zero reference fields get an absolute tolerance, not a free
  pass.** When the Linux reference magnitude for a variable is negligible
  (below ``--reference-negligible-threshold``), a purely relative
  tolerance is meaningless (dividing by ~0 either explodes or, worse,
  masks a real difference once clamped). Such variables are graded
  against ``--abs-tol`` instead of being unconditionally marked
  ``reference_negligible``/pass.
- ``main()`` aggregates every variable's status across every example/file
  and returns a non-zero exit code if any variable's status is a
  ``fail*`` status, so this script is safe to use directly as a gate.

See ``selftest.py`` alongside this file for synthetic regression tests
covering exactly these gate behaviours.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

TOLERANCE_TIERS: dict[str, float] = {
    "deterministic": 1.0e-9,
    "iterative": 1.0e-4,
    "adaptive_transport": 1.0e-2,
}

# Below this Linux-reference magnitude (max-abs over the whole run), a
# relative-tolerance verdict is not meaningful -- fall back to an absolute
# tolerance instead (see ABS_TOL_DEFAULT below and the --abs-tol flag).
REFERENCE_NEGLIGIBLE_THRESHOLD = 1.0e-9

# Default absolute-tolerance floor applied when the Linux reference is
# negligible. The fields this tool compares (waterlevel/waterdepth in
# metres, velocity in m/s, D-WAQ concentrations in mass/volume) are all
# double-precision quantities accumulated over a few hundred to a few
# thousand explicit/iterative-solver timesteps; 1e-12 sits comfortably
# above double-precision rounding noise (~1e-15..1e-16 relative to O(1)
# quantities) while still being far tighter than any legitimate physical
# signal at these scales, so it catches a real O(1e-2..1)-sized mismatch
# (like a dropped/zeroed node) without flagging last-ULP noise. Fields with
# a much larger natural scale (e.g. concentrations reported in mg/L with
# values in the thousands) should pass a larger --abs-tol explicitly.
ABS_TOL_DEFAULT = 1.0e-12

# Variables that are expected to fall in the "adaptive_transport" tier rather
# than "iterative", because they are D-WAQ tracers transported with example
# 03's adaptive internal dt.
ADAPTIVE_TRANSPORT_VARIABLES = {"OXY", "NH4", "NO3", "PO4", "Diat", "Green"}


def _base_name(variable: str) -> str:
    return variable[len("mesh2d_") :] if variable.startswith("mesh2d_") else variable


# For each example: which NetCDF file(s) to open (relative to
# <runs-root>/<example>/dflowfm/dflowfmoutput) and which variables to diff.
EXAMPLE_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "01_dflowfm_sequential": {
        "map": {
            "filename": "f34_map.nc",
            "variables": ["s1", "waterdepth", "ucx", "ucy"],
            "open": "xarray",
        },
        "his": {
            "filename": "f34_his.nc",
            "variables": ["waterlevel", "x_velocity", "y_velocity"],
            "open": "xarray",
        },
    },
    "02_dflowfm_parallel": {
        "his": {
            "filename": "westerscheldt_0000_his.nc",
            "variables": ["waterlevel", "x_velocity", "y_velocity"],
            "open": "xarray",
        },
    },
    "03_dflowfm_dwaq_sequential": {
        "map": {
            "filename": "f34_dynamo_map.nc",
            "variables": [
                "mesh2d_s1",
                "mesh2d_waterdepth",
                "mesh2d_ucx",
                "mesh2d_ucy",
                "mesh2d_OXY",
                "mesh2d_NH4",
                "mesh2d_NO3",
                "mesh2d_PO4",
                "mesh2d_Diat",
                "mesh2d_Green",
            ],
            "open": "xarray",
        },
        "his": {
            "filename": "f34_dynamo_his.nc",
            "variables": [
                "waterlevel",
                "x_velocity",
                "y_velocity",
                "OXY",
                "NH4",
                "NO3",
                "PO4",
                "Diat",
                "Green",
            ],
            "open": "xarray",
        },
    },
}

# examples 01/02 use different meshes for the sequential and MPI runs
# respectively, so a Linux-sequential-vs-Linux-MPI "inherent divergence"
# control (mentioned in the plan text for 5a) cannot be built from the
# existing baseline runs -- it would require running one model both ways.
# Recorded here rather than silently skipped.
KNOWN_LIMITATIONS = [
    "Linux-sequential vs Linux-MPI control not computed: example 01 "
    "(sequential) and example 02 (MPI) run different meshes/models in this "
    "baseline set, so they cannot serve as a same-model seq-vs-MPI control. "
    "Building that control would require an additional run (e.g. example 02's "
    "mesh run sequentially, or example 01 run under MPI) and is out of scope "
    "for this task.",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def tier_for(variable: str, example: str) -> str:
    base = _base_name(variable)
    if example == "03_dflowfm_dwaq_sequential" and base in ADAPTIVE_TRANSPORT_VARIABLES:
        return "adaptive_transport"
    return "iterative"


def match_times(mac_time: np.ndarray, lin_time: np.ndarray) -> dict[str, Any]:
    """Verify the fixed output time axes line up and return matching indices."""
    exact = mac_time.size == lin_time.size and bool(np.array_equal(mac_time, lin_time))
    if exact:
        mac_idx = np.arange(mac_time.size)
        lin_idx = np.arange(lin_time.size)
    else:
        common = np.intersect1d(mac_time, lin_time)
        mac_idx = np.nonzero(np.isin(mac_time, common))[0]
        lin_idx = np.nonzero(np.isin(lin_time, common))[0]
    require(mac_idx.size > 0, "no shared output timesteps between macOS and Linux datasets")
    return {
        "exact_match": exact,
        "mac_count": int(mac_time.size),
        "linux_count": int(lin_time.size),
        "compared_count": int(mac_idx.size),
        "mac_index": mac_idx,
        "linux_index": lin_idx,
        "first_compared": str(mac_time[mac_idx[0]]),
        "last_compared": str(mac_time[mac_idx[-1]]),
    }


def diff_variable(
    mac_da: xr.DataArray,
    lin_da: xr.DataArray,
    time_match: dict[str, Any],
    tier: str,
    abs_tol: float = ABS_TOL_DEFAULT,
    reference_negligible_threshold: float = REFERENCE_NEGLIGIBLE_THRESHOLD,
) -> dict[str, Any]:
    require(mac_da.dims[0] == "time", f"expected time as first dim, got {mac_da.dims}")
    require(mac_da.shape[1:] == lin_da.shape[1:], "non-time shape mismatch between platforms")

    mac_values = np.asarray(mac_da.values)[time_match["mac_index"]]
    lin_values = np.asarray(lin_da.values)[time_match["linux_index"]]
    ntime = mac_values.shape[0]
    mac_flat = mac_values.reshape(ntime, -1)
    lin_flat = lin_values.reshape(ntime, -1)

    eps = 1.0e-12
    # Normalise relative differences against the Linux reference's dynamic
    # range over the *whole* run (not the instantaneous per-timestep value).
    # Using a per-timestep scale would make the relative metric blow up
    # whenever a field passes near zero at some node/time (e.g. tracer
    # concentrations ramping up from a near-zero initial condition), which
    # would misrepresent a tiny absolute difference as a huge relative one.
    lin_finite_all = np.isfinite(lin_flat)
    require(bool(lin_finite_all.any()), "Linux reference has no finite values at all")
    ref_rms_scale = float(np.sqrt(np.mean(lin_flat[lin_finite_all] ** 2)))
    ref_max_scale = float(np.max(np.abs(lin_flat[lin_finite_all])))

    per_timestep = []
    all_diff = []
    all_ref = []
    skipped_no_data = 0
    mask_mismatch_timesteps = 0
    mask_mismatch_nodes_total = 0
    for t in range(ntime):
        m = mac_flat[t]
        l = lin_flat[t]
        finite_mac = np.isfinite(m)
        finite_lin = np.isfinite(l)

        # Finite-value masks must agree between platforms. A node that is
        # finite on one platform and NaN/fill on the other is a real parity
        # defect (missing/garbage data), not something to quietly drop from
        # the comparison by intersecting the masks.
        mask_disagreement = finite_mac != finite_lin
        n_mismatch = int(mask_disagreement.sum())
        if n_mismatch > 0:
            mask_mismatch_timesteps += 1
            mask_mismatch_nodes_total += n_mismatch
            per_timestep.append(
                {
                    "status": "mask_mismatch",
                    "mismatched_nodes": n_mismatch,
                    "mac_finite_count": int(finite_mac.sum()),
                    "linux_finite_count": int(finite_lin.sum()),
                }
            )
            continue

        # Masks agree here (finite_mac == finite_lin elementwise).
        finite = finite_mac
        if not finite.any():
            # Some D-WAQ tracers (e.g. mesh2d_PO4 in example 03) legitimately
            # stop being written (become entirely fill-value) from a certain
            # timestep onward on *both* platforms -- not a parity issue,
            # because both masks agree (checked above).
            skipped_no_data += 1
            per_timestep.append({"status": "no_data_both_platforms"})
            continue

        d = m[finite] - l[finite]
        ref = l[finite]
        all_diff.append(d)
        all_ref.append(ref)
        rms_abs = float(np.sqrt(np.mean(d**2)))
        max_abs = float(np.max(np.abs(d)))
        per_timestep.append(
            {
                "status": "ok",
                "rms_abs": rms_abs,
                "max_abs": max_abs,
                "rms_rel": rms_abs / max(ref_rms_scale, eps),
                "max_rel": max_abs / max(ref_max_scale, eps),
            }
        )

    mask_mismatch = mask_mismatch_timesteps > 0

    if all_diff:
        diff_concat = np.concatenate(all_diff)
        overall_rms_abs = float(np.sqrt(np.mean(diff_concat**2)))
        overall_max_abs = float(np.max(np.abs(diff_concat)))
        overall_rms_rel = overall_rms_abs / max(ref_rms_scale, eps)
        overall_max_rel = overall_max_abs / max(ref_max_scale, eps)
    else:
        # The only legitimate way to have zero comparable timesteps is if
        # every timestep was a mask mismatch (already a hard failure below).
        require(
            mask_mismatch,
            "no timestep had finite data on both platforms, and no finite-mask "
            "mismatch was detected either -- this should not be reachable",
        )
        overall_rms_abs = float("nan")
        overall_max_abs = float("nan")
        overall_rms_rel = float("nan")
        overall_max_rel = float("nan")

    reference_negligible = ref_max_scale < reference_negligible_threshold
    tolerance_value = TOLERANCE_TIERS[tier]
    fail_reason: str | None = None

    if mask_mismatch:
        status = "fail"
        fail_reason = (
            f"finite-value mask mismatch: {mask_mismatch_nodes_total} node-timestep "
            f"disagreement(s) across {mask_mismatch_timesteps} timestep(s) (one "
            "platform finite, the other NaN/fill)"
        )
    elif reference_negligible:
        if overall_max_abs <= abs_tol:
            status = "pass_negligible_reference"
        else:
            status = "fail"
            fail_reason = (
                f"Linux reference magnitude negligible (max |ref|={ref_max_scale:.3e} < "
                f"{reference_negligible_threshold:.3e}), but max abs diff "
                f"{overall_max_abs:.3e} exceeds absolute tolerance {abs_tol:.3e}"
            )
    elif overall_max_abs <= TOLERANCE_TIERS["deterministic"]:
        status = "pass_deterministic"
    elif overall_max_rel <= tolerance_value:
        status = f"pass_{tier}"
    else:
        status = "fail"
        fail_reason = (
            f"max relative diff {overall_max_rel:.3e} exceeds '{tier}' tolerance "
            f"{tolerance_value:.3e}"
        )

    result: dict[str, Any] = {
        "shape": list(mac_da.shape),
        "time": {
            "exact_match": time_match["exact_match"],
            "mac_count": time_match["mac_count"],
            "linux_count": time_match["linux_count"],
            "compared_count": time_match["compared_count"],
            "first_compared": time_match["first_compared"],
            "last_compared": time_match["last_compared"],
        },
        "per_timestep": per_timestep,
        "overall": {
            "rms_abs": overall_rms_abs,
            "max_abs": overall_max_abs,
            "rms_rel": overall_rms_rel,
            "max_rel": overall_max_rel,
            "reference_rms_scale": ref_rms_scale,
            "reference_max_scale": ref_max_scale,
            "skipped_timesteps_no_data": skipped_no_data,
        },
        "tolerance_tier": tier,
        "tolerance_value": tolerance_value,
        "abs_tol": abs_tol,
        "status": status,
    }
    if mask_mismatch:
        result["mask_mismatch"] = {
            "timesteps": mask_mismatch_timesteps,
            "total_mismatched_nodes": mask_mismatch_nodes_total,
        }
    if fail_reason is not None:
        result["fail_reason"] = fail_reason
    return result


def diff_file_kind(
    mac_path: Path,
    lin_path: Path,
    variables: list[str],
    example: str,
    abs_tol: float = ABS_TOL_DEFAULT,
) -> dict[str, Any]:
    require(mac_path.is_file(), f"missing macOS output: {mac_path}")
    require(lin_path.is_file(), f"missing Linux output: {lin_path}")
    with xr.open_dataset(mac_path, decode_timedelta=False) as mac_ds, xr.open_dataset(
        lin_path, decode_timedelta=False
    ) as lin_ds:
        time_match = match_times(mac_ds["time"].values, lin_ds["time"].values)
        results = {}
        for variable in variables:
            require(variable in mac_ds, f"missing variable {variable} in {mac_path}")
            require(variable in lin_ds, f"missing variable {variable} in {lin_path}")
            tier = tier_for(variable, example)
            results[variable] = diff_variable(
                mac_ds[variable], lin_ds[variable], time_match, tier, abs_tol=abs_tol
            )
        return {
            "mac_path": str(mac_path),
            "linux_path": str(lin_path),
            "time_axis": {
                "exact_match": time_match["exact_match"],
                "mac_count": time_match["mac_count"],
                "linux_count": time_match["linux_count"],
                "compared_count": time_match["compared_count"],
            },
            "variables": results,
        }


def diff_example(
    mac_root: Path, lin_root: Path, example: str, abs_tol: float = ABS_TOL_DEFAULT
) -> dict[str, Any]:
    spec = EXAMPLE_SPECS[example]
    mac_dir = mac_root / example / "dflowfm" / "dflowfmoutput"
    lin_dir = lin_root / example / "dflowfm" / "dflowfmoutput"
    result: dict[str, Any] = {}
    for kind, kind_spec in spec.items():
        mac_path = mac_dir / kind_spec["filename"]
        lin_path = lin_dir / kind_spec["filename"]
        result[kind] = diff_file_kind(
            mac_path, lin_path, kind_spec["variables"], example, abs_tol=abs_tol
        )
    return result


def run(mac_root: Path, lin_root: Path, abs_tol: float = ABS_TOL_DEFAULT) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "tolerance_tiers": TOLERANCE_TIERS,
        "abs_tol": abs_tol,
        "reference_negligible_threshold": REFERENCE_NEGLIGIBLE_THRESHOLD,
        "known_limitations": KNOWN_LIMITATIONS,
        "cases": {
            example: diff_example(mac_root, lin_root, example, abs_tol=abs_tol)
            for example in EXAMPLE_SPECS
        },
    }


def iter_variable_statuses(report: dict[str, Any]):
    """Yield (example, kind, variable, status) for every variable in a report."""
    for example, kinds in report["cases"].items():
        for kind, kind_result in kinds.items():
            for variable, stats in kind_result["variables"].items():
                yield example, kind, variable, stats["status"]


def failing_variables(report: dict[str, Any]) -> list[str]:
    return [
        f"{example}/{kind}/{variable} ({status})"
        for example, kind, variable, status in iter_variable_statuses(report)
        if status.startswith("fail")
    ]


def render_console_table(report: dict[str, Any]) -> str:
    lines = []
    lines.append("Field-diff (macOS vs Linux) -- tolerance tiers: " + ", ".join(
        f"{name}<={value:.0e}" for name, value in report["tolerance_tiers"].items()
    ))
    header = (
        f"{'example':<30}{'kind':<6}{'variable':<14}{'rms_abs':>12}{'max_abs':>12}"
        f"{'rms_rel':>12}{'max_rel':>12}  {'tier':<20}{'status':<20}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for example, kinds in report["cases"].items():
        for kind, kind_result in kinds.items():
            for variable, stats in kind_result["variables"].items():
                overall = stats["overall"]
                lines.append(
                    f"{example:<30}{kind:<6}{variable:<14}"
                    f"{overall['rms_abs']:>12.3e}{overall['max_abs']:>12.3e}"
                    f"{overall['rms_rel']:>12.3e}{overall['max_rel']:>12.3e}  "
                    f"{stats['tolerance_tier']:<20}{stats['status']:<20}"
                )
                if stats["status"].startswith("fail") and stats.get("fail_reason"):
                    lines.append(f"    -> {stats['fail_reason']}")
    if report["known_limitations"]:
        lines.append("")
        lines.append("Known limitations:")
        for note in report["known_limitations"]:
            lines.append(f"  - {note}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac-runs-root", type=Path, default=Path("baseline_runs"))
    parser.add_argument(
        "--linux-runs-root",
        type=Path,
        default=Path("baseline_artifacts/linux-reference-outputs"),
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=ABS_TOL_DEFAULT,
        help=(
            "Absolute tolerance floor applied instead of an unconditional pass "
            "when a variable's Linux reference magnitude is negligible (below "
            f"--reference-negligible-threshold, default {REFERENCE_NEGLIGIBLE_THRESHOLD:.0e}). "
            f"Default {ABS_TOL_DEFAULT:.0e} is sized for waterlevel/velocity-scale "
            "fields (metres, m/s) where double-precision rounding noise is many "
            "orders of magnitude smaller; pass a larger value for variables with "
            "a coarser natural scale."
        ),
    )
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(args.mac_runs_root, args.linux_runs_root, abs_tol=args.abs_tol)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(render_console_table(report))

    failures = failing_variables(report)
    if failures:
        print(f"FAIL: {len(failures)} variable(s) failed parity/tolerance checks:")
        for entry in failures:
            print(f"  - {entry}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
