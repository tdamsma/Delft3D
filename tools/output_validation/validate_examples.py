#!/usr/bin/env python3
"""Validate the public Deltares example outputs used by the port baseline."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
import xugrid as xu


EXPECTED_PACKAGES = ("dfm-tools", "hydrolib-core", "meshkernel", "xugrid")
EXPECTED_TOPOLOGY = {"nodes": 258, "edges": 479, "faces": 222}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def time_summary(dataset: xr.Dataset, expected_count: int, expected_hours: float) -> dict[str, Any]:
    require("time" in dataset.coords, "missing time coordinate")
    time = dataset["time"]
    require(time.size == expected_count, f"expected {expected_count} times, found {time.size}")
    require(time.size > 1, "time coordinate must have at least two values")
    deltas = np.diff(time.values).astype("timedelta64[ns]").astype(np.int64)
    require(bool(np.all(deltas > 0)), "time coordinate is not strictly increasing")
    duration_hours = float((time.values[-1] - time.values[0]) / np.timedelta64(1, "h"))
    require(abs(duration_hours - expected_hours) < 1.0e-9, f"expected {expected_hours} h, found {duration_hours} h")
    return {
        "count": int(time.size),
        "start": str(time.values[0]),
        "end": str(time.values[-1]),
        "duration_hours": duration_hours,
    }


def finite_summary(dataset: xr.Dataset, variable: str, nonnegative: bool = False) -> dict[str, Any]:
    require(variable in dataset, f"missing variable {variable}")
    values = np.asarray(dataset[variable].values)
    finite = np.isfinite(values)
    count = int(finite.sum())
    require(count > 0, f"{variable} has no finite values")
    selected = values[finite]
    minimum = float(selected.min())
    maximum = float(selected.max())
    if nonnegative:
        require(minimum >= 0.0, f"{variable} has negative concentration {minimum}")
    return {
        "finite": count,
        "total": int(values.size),
        "minimum": minimum,
        "maximum": maximum,
    }


def validate_history(path: Path, expected_count: int, expected_hours: float) -> dict[str, Any]:
    require(path.is_file(), f"missing history output: {path}")
    with xr.open_dataset(path, decode_timedelta=False) as dataset:
        result = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "time": time_summary(dataset, expected_count, expected_hours),
            "waterlevel": finite_summary(dataset, "waterlevel"),
        }
        require(
            result["waterlevel"]["finite"] == result["waterlevel"]["total"],
            "waterlevel contains non-finite values",
        )
        return result


def validate_map(
    path: Path,
    expected_count: int,
    expected_hours: float,
    waterdepth_variable: str,
) -> tuple[dict[str, Any], xr.Dataset]:
    require(path.is_file(), f"missing map output: {path}")
    ugrid_dataset = xu.open_dataset(path, decode_timedelta=False)
    require(len(ugrid_dataset.ugrid.grids) == 1, "expected exactly one UGRID topology")
    grid = ugrid_dataset.ugrid.grids[0]
    topology = {"nodes": grid.n_node, "edges": grid.n_edge, "faces": grid.n_face}
    require(topology == EXPECTED_TOPOLOGY, f"unexpected topology: {topology}")
    dataset = ugrid_dataset.obj
    result = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "grid_name": grid.name,
        "topology": topology,
        "time": time_summary(dataset, expected_count, expected_hours),
        "waterdepth": finite_summary(dataset, waterdepth_variable, nonnegative=True),
    }
    require(
        result["waterdepth"]["finite"] == result["waterdepth"]["total"],
        "water depth contains non-finite values",
    )
    return result, dataset


def validate(runs_root: Path) -> dict[str, Any]:
    case1 = runs_root / "01_dflowfm_sequential/dflowfm/dflowfmoutput"
    case2 = runs_root / "02_dflowfm_parallel/dflowfm/dflowfmoutput"
    case3 = runs_root / "03_dflowfm_dwaq_sequential/dflowfm/dflowfmoutput"

    case1_map, case1_dataset = validate_map(case1 / "f34_map.nc", 31, 25.0, "waterdepth")
    case1_dataset.close()
    case3_map, case3_dataset = validate_map(
        case3 / "f34_dynamo_map.nc", 41, 120.0, "mesh2d_waterdepth"
    )
    concentrations = {}
    for name in ("OXY", "NH4", "NO3", "PO4", "Diat", "Green"):
        concentrations[name] = finite_summary(case3_dataset, f"mesh2d_{name}", nonnegative=True)
        require(
            concentrations[name]["finite"] >= concentrations[name]["total"] // 5,
            f"mesh2d_{name} has unexpectedly sparse wet-layer data",
        )
    case3_dataset.close()
    case3_map["water_quality"] = concentrations

    return {
        "schema_version": 1,
        "packages": {
            name: importlib.metadata.version(name) for name in EXPECTED_PACKAGES
        },
        "cases": {
            "01_dflowfm_sequential": {
                "history": validate_history(case1 / "f34_his.nc", 301, 25.0),
                "map": case1_map,
            },
            "02_dflowfm_parallel": {
                "history": validate_history(
                    case2 / "westerscheldt_0000_his.nc", 7, 110.0 / 60.0
                ),
            },
            "03_dflowfm_dwaq_sequential": {
                "history": validate_history(case3 / "f34_dynamo_his.nc", 241, 120.0),
                "map": case3_map,
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("baseline_runs"))
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate(args.runs_root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
