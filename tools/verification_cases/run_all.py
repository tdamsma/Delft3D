#!/usr/bin/env python3
"""Generate, (optionally) run, and verify the analytic verification suite.

Mirrors the reporting discipline of tools/output_validation/validate_examples.py:
a single JSON report with package versions and a per-case status/result dict.

Usage:
    # Generate + validate all case inputs (no simulation, no dflowfm needed):
    python run_all.py --runs-root baseline_runs/verification

    # Generate, run, and verify (once a working native dflowfm exists):
    python run_all.py --runs-root baseline_runs/verification \\
        --dflowfm-binary build_dflowfm_release/dflowfm_cli_exe/dflowfm \\
        --json-out baseline_logs/verification-suite.json
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SUITE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE_DIR))

CASES = [
    "lake_at_rest",
    "normal_depth_channel",
    "linear_seiche",
    "stoker_dambreak",
    "thacker_basin",
]

EXPECTED_PACKAGES = ("dfm-tools", "hydrolib-core", "meshkernel", "xugrid", "numpy", "xarray")


def _load(case: str, module: str):
    """(Re-)import a case's generate.py/verify.py as plain "generate"/"verify".

    See selftest.py's ``_import`` for why the sys.modules eviction is
    necessary (every case names its scripts identically).
    """
    sys.modules.pop("generate", None)
    sys.modules.pop("verify", None)
    case_dir = SUITE_DIR / case
    sys.path.insert(0, str(case_dir))
    try:
        return importlib.import_module(module)
    finally:
        sys.path.remove(str(case_dir))


def _output_dir_and_stem(mdu_path: Path) -> tuple[str, str]:
    """D-Flow FM's default output layout: <run_dir>/dflowfmoutput/<stem>_map.nc.

    All cases use common.mdu_base.make_base_model's default
    ``output_dir="dflowfmoutput"`` and never override ``Output.mapfile``, so
    D-Flow FM derives the map/his file names from the .mdu base name itself.
    """
    return "dflowfmoutput", mdu_path.stem


def run_case(
    case: str, runs_root: Path, dflowfm_binary: Path | None, timeout_s: float
) -> dict[str, Any]:
    out_dir = runs_root / case
    generate = _load(case, "generate")

    result: dict[str, Any] = {"case": case, "out_dir": str(out_dir)}
    try:
        mdu_path = generate.generate(out_dir)
        result["mdu_path"] = str(mdu_path)
        result["generated"] = True
    except Exception as exc:  # noqa: BLE001
        result["generated"] = False
        result["error"] = f"generate() failed: {exc!r}"
        return result

    output_dir_name, stem = _output_dir_and_stem(mdu_path)
    map_path = out_dir / output_dir_name / f"{stem}_map.nc"

    if dflowfm_binary is None:
        result["status"] = "generated_only"
        return result

    log_path = out_dir / "dflowfm_run.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                [str(dflowfm_binary), "--autostartstop", mdu_path.name],
                cwd=out_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
            )
        result["dflowfm_returncode"] = proc.returncode
        result["dflowfm_log"] = str(log_path)
    except subprocess.TimeoutExpired:
        result["status"] = "run_timeout"
        result["dflowfm_log"] = str(log_path)
        return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "run_failed"
        result["error"] = f"subprocess failed to start: {exc!r}"
        return result

    if proc.returncode != 0:
        result["status"] = "run_failed"
        return result

    if not map_path.is_file():
        result["status"] = "missing_output"
        result["expected_map_path"] = str(map_path)
        return result

    verify = _load(case, "verify")
    try:
        verify_result = verify.verify(map_path)
        result["verify"] = verify_result
        result["status"] = "passed" if verify_result.get("passed") else "failed"
    except Exception as exc:  # noqa: BLE001
        result["status"] = "verify_error"
        result["error"] = f"verify() failed: {exc!r}"
    return result


def run_suite(
    runs_root: Path,
    dflowfm_binary: Path | None,
    cases: list[str],
    timeout_s: float,
) -> dict[str, Any]:
    packages = {}
    for name in EXPECTED_PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None

    case_results = {
        case: run_case(case, runs_root, dflowfm_binary, timeout_s) for case in cases
    }

    all_generated = all(r.get("generated", False) for r in case_results.values())
    all_passed = dflowfm_binary is not None and all(
        r.get("status") == "passed" for r in case_results.values()
    )

    return {
        "schema_version": 1,
        "dflowfm_binary": str(dflowfm_binary) if dflowfm_binary else None,
        "packages": packages,
        "cases": case_results,
        "summary": {
            "all_generated": all_generated,
            "all_passed": all_passed if dflowfm_binary else None,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("baseline_runs/verification"),
        help="Directory to write each case's generated run into (one subdir per case).",
    )
    parser.add_argument(
        "--dflowfm-binary",
        type=Path,
        default=None,
        help="Path to the native dflowfm executable. If omitted, only "
        "generate + validate the inputs (no simulation, no verification).",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        default=CASES,
        choices=CASES,
        help="Subset of cases to run (default: all).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Per-case wall-clock timeout in seconds for the dflowfm subprocess.",
    )
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_suite(args.runs_root, args.dflowfm_binary, args.cases, args.timeout)
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    if args.dflowfm_binary is None:
        return 0 if result["summary"]["all_generated"] else 1
    return 0 if result["summary"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
