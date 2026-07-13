#!/usr/bin/env python3
"""Synthetic regression tests for field_diff.py's gate logic.

These are not simulation regression tests (field_diff.py is already
exercised against real macOS/Linux output elsewhere -- see the port
status doc); they are unit tests, with hand-built arrays, of the
comparator's own pass/fail decisions. They exist because a local review
(2026-07-12) reproduced two false passes from field_diff.py using exactly
this kind of synthetic input:

1. macOS ``[1.0, NaN]`` vs Linux ``[1.0, 2.0]`` at a single timestep used
   to return ``pass_deterministic`` -- the mismatching node was silently
   dropped by ``finite_mac & finite_lin`` instead of being treated as a
   parity defect.
2. macOS ``1.0`` vs Linux ``0.0`` (reference magnitude below the
   negligible-reference threshold) used to return ``reference_negligible``
   unconditionally, with no tolerance check at all.

Every test below builds inputs directly with numpy/xarray and calls
field_diff's functions -- no dflowfm run, no real NetCDF files, no
network/uv install required beyond what field_diff.py itself needs
(numpy, xarray). Run with the same interpreter used for the real
comparisons:

    baseline_tools/dfm-validation/bin/python tools/output_validation/selftest.py

Exits 0 if every test passes, non-zero (number of failures) otherwise.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))

import field_diff  # noqa: E402  (path insert above must run first)


def _da(values: list[list[float]], name: str = "var") -> xr.DataArray:
    """Build a (time, node) DataArray from nested lists, float64."""
    arr = np.asarray(values, dtype=np.float64)
    return xr.DataArray(arr, dims=("time", "node"), name=name)


def _time_match(ntime_mac: int, ntime_lin: int | None = None) -> dict[str, Any]:
    ntime_lin = ntime_mac if ntime_lin is None else ntime_lin
    mac_time = np.arange(ntime_mac, dtype=np.float64)
    lin_time = np.arange(ntime_lin, dtype=np.float64)
    return field_diff.match_times(mac_time, lin_time)


def test_finite_mask_mismatch_fails() -> None:
    """Reproduces the review's exact false-pass case: must now fail."""
    mac = _da([[1.0, float("nan")]])
    lin = _da([[1.0, 2.0]])
    tm = _time_match(1)
    result = field_diff.diff_variable(mac, lin, tm, tier="iterative")
    assert result["status"] == "fail", f"expected fail, got {result['status']!r}: {result}"
    assert "mask_mismatch" in result, "expected mask_mismatch details in result"
    assert result["mask_mismatch"]["total_mismatched_nodes"] == 1
    assert "fail_reason" in result and "mask" in result["fail_reason"].lower()


def test_finite_mask_mismatch_reports_all_offending_timesteps() -> None:
    mac = _da([[1.0, float("nan")], [2.0, 3.0], [float("nan"), 5.0]])
    lin = _da([[1.0, 2.0], [2.0, 3.0], [4.0, 5.0]])
    tm = _time_match(3)
    result = field_diff.diff_variable(mac, lin, tm, tier="iterative")
    assert result["status"] == "fail"
    # timesteps 0 and 2 disagree; timestep 1 is a clean, agreeing match.
    assert result["mask_mismatch"]["timesteps"] == 2
    assert result["mask_mismatch"]["total_mismatched_nodes"] == 2
    assert result["per_timestep"][1]["status"] == "ok"


def test_both_platforms_nan_is_not_a_mismatch() -> None:
    """Both platforms legitimately stop writing a variable at the same time."""
    mac = _da([[1.0, 2.0], [float("nan"), float("nan")]])
    lin = _da([[1.0, 2.0], [float("nan"), float("nan")]])
    tm = _time_match(2)
    result = field_diff.diff_variable(mac, lin, tm, tier="iterative")
    assert result["status"] == "pass_deterministic", result["status"]
    assert "mask_mismatch" not in result
    assert result["per_timestep"][1]["status"] == "no_data_both_platforms"
    assert result["overall"]["skipped_timesteps_no_data"] == 1


def test_near_zero_reference_mismatch_fails() -> None:
    """Reproduces the review's second false-pass case: must now fail."""
    mac = _da([[1.0]])
    lin = _da([[0.0]])
    tm = _time_match(1)
    result = field_diff.diff_variable(mac, lin, tm, tier="iterative")
    assert result["status"] == "fail", f"expected fail, got {result['status']!r}: {result}"
    assert "negligible" in result["fail_reason"].lower()


def test_near_zero_reference_within_abs_tol_passes() -> None:
    mac = _da([[5.0e-13]])
    lin = _da([[0.0]])
    tm = _time_match(1)
    result = field_diff.diff_variable(mac, lin, tm, tier="iterative", abs_tol=1.0e-12)
    assert result["status"] == "pass_negligible_reference", result["status"]


def test_near_zero_reference_respects_custom_abs_tol() -> None:
    """A looser --abs-tol should let a slightly larger absolute diff through."""
    mac = _da([[5.0e-6]])
    lin = _da([[0.0]])
    tm = _time_match(1)
    tight = field_diff.diff_variable(mac, lin, tm, tier="iterative", abs_tol=1.0e-12)
    loose = field_diff.diff_variable(mac, lin, tm, tier="iterative", abs_tol=1.0e-5)
    assert tight["status"] == "fail", tight["status"]
    assert loose["status"] == "pass_negligible_reference", loose["status"]


def test_relative_tolerance_boundary() -> None:
    """max_rel just under the iterative tier boundary passes; just over fails.

    (Deliberately not testing bit-exact equality at the boundary: the
    tier check is a floating-point "<=" comparison, so a diff constructed
    to land *exactly* on the boundary is at the mercy of the last-ULP
    rounding of the test's own arithmetic, not of field_diff's logic. A
    comfortable margin on each side of the threshold still exercises the
    same branch and is what "boundary case" is protecting: that pass and
    fail land on the correct side of TOLERANCE_TIERS['iterative'].)
    """
    ref_scale = 100.0
    tier_tol = field_diff.TOLERANCE_TIERS["iterative"]
    # diff chosen well above the deterministic-tier shortcut (1e-9 absolute)
    # so the relative-tier branch is actually exercised.
    lin = _da([[ref_scale, ref_scale]])
    tm = _time_match(1)

    just_under = ref_scale * tier_tol * 0.99
    mac_pass = _da([[ref_scale + just_under, ref_scale]])
    result_pass = field_diff.diff_variable(mac_pass, lin, tm, tier="iterative")
    assert result_pass["status"] == "pass_iterative", result_pass

    just_over = ref_scale * tier_tol * 1.01
    mac_fail = _da([[ref_scale + just_over, ref_scale]])
    result_fail = field_diff.diff_variable(mac_fail, lin, tm, tier="iterative")
    assert result_fail["status"] == "fail", result_fail
    assert "tolerance" in result_fail["fail_reason"].lower()


def test_time_axis_mismatch_fails() -> None:
    """Completely disjoint time axes must not silently produce a comparison."""
    mac_time = np.array([0.0, 1.0, 2.0])
    lin_time = np.array([10.0, 11.0, 12.0])
    try:
        field_diff.match_times(mac_time, lin_time)
    except AssertionError:
        return
    raise AssertionError("expected match_times to raise on disjoint time axes")


def test_time_axis_partial_overlap_is_flagged_not_exact() -> None:
    mac_time = np.array([0.0, 1.0, 2.0, 3.0])
    lin_time = np.array([1.0, 2.0, 3.0, 4.0])
    tm = field_diff.match_times(mac_time, lin_time)
    assert tm["exact_match"] is False
    assert tm["compared_count"] == 3


def test_main_exit_code_zero_on_all_pass(monkeypatch) -> None:
    fake_report = {
        "schema_version": 2,
        "tolerance_tiers": field_diff.TOLERANCE_TIERS,
        "abs_tol": field_diff.ABS_TOL_DEFAULT,
        "reference_negligible_threshold": field_diff.REFERENCE_NEGLIGIBLE_THRESHOLD,
        "known_limitations": [],
        "cases": {
            "01_dflowfm_sequential": {
                "his": {
                    "variables": {
                        "waterlevel": {
                            "overall": {
                                "rms_abs": 0.0,
                                "max_abs": 0.0,
                                "rms_rel": 0.0,
                                "max_rel": 0.0,
                            },
                            "tolerance_tier": "iterative",
                            "status": "pass_deterministic",
                        }
                    }
                }
            }
        },
    }
    monkeypatch.setattr(field_diff, "run", lambda *a, **k: fake_report)
    monkeypatch.setattr(
        sys, "argv", ["field_diff.py", "--mac-runs-root", ".", "--linux-runs-root", "."]
    )
    assert field_diff.main() == 0


def test_main_exit_code_nonzero_on_any_fail(monkeypatch) -> None:
    fake_report = {
        "schema_version": 2,
        "tolerance_tiers": field_diff.TOLERANCE_TIERS,
        "abs_tol": field_diff.ABS_TOL_DEFAULT,
        "reference_negligible_threshold": field_diff.REFERENCE_NEGLIGIBLE_THRESHOLD,
        "known_limitations": [],
        "cases": {
            "01_dflowfm_sequential": {
                "his": {
                    "variables": {
                        "waterlevel": {
                            "overall": {
                                "rms_abs": 0.0,
                                "max_abs": 0.0,
                                "rms_rel": 0.0,
                                "max_rel": 0.0,
                            },
                            "tolerance_tier": "iterative",
                            "status": "pass_deterministic",
                        },
                        "x_velocity": {
                            "overall": {
                                "rms_abs": 1.0,
                                "max_abs": 1.0,
                                "rms_rel": 1.0,
                                "max_rel": 1.0,
                            },
                            "tolerance_tier": "iterative",
                            "status": "fail",
                            "fail_reason": "synthetic failure for exit-code test",
                        },
                    }
                }
            }
        },
    }
    monkeypatch.setattr(field_diff, "run", lambda *a, **k: fake_report)
    monkeypatch.setattr(
        sys, "argv", ["field_diff.py", "--mac-runs-root", ".", "--linux-runs-root", "."]
    )
    assert field_diff.main() == 1


class _FakeMonkeypatch:
    """Minimal drop-in for pytest's monkeypatch fixture (attr set + restore)."""

    def __init__(self) -> None:
        self._restore: list[tuple[Any, str, Any, bool]] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        had = hasattr(obj, name)
        old = getattr(obj, name, None)
        self._restore.append((obj, name, old, had))
        setattr(obj, name, value)

    def undo(self) -> None:
        for obj, name, old, had in reversed(self._restore):
            if had:
                setattr(obj, name, old)
            else:
                delattr(obj, name)
        self._restore.clear()


TESTS = [
    test_finite_mask_mismatch_fails,
    test_finite_mask_mismatch_reports_all_offending_timesteps,
    test_both_platforms_nan_is_not_a_mismatch,
    test_near_zero_reference_mismatch_fails,
    test_near_zero_reference_within_abs_tol_passes,
    test_near_zero_reference_respects_custom_abs_tol,
    test_relative_tolerance_boundary,
    test_time_axis_mismatch_fails,
    test_time_axis_partial_overlap_is_flagged_not_exact,
    test_main_exit_code_zero_on_all_pass,
    test_main_exit_code_nonzero_on_any_fail,
]


def main() -> int:
    failures = 0
    for test in TESTS:
        name = test.__name__
        mp = _FakeMonkeypatch()
        try:
            if "monkeypatch" in test.__code__.co_varnames[: test.__code__.co_argcount]:
                test(mp)
            else:
                test()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
        finally:
            mp.undo()
    total = len(TESTS)
    print(f"\n{total - failures}/{total} passed")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
