import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

# ── Paths (resolved relative to this script) ────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
TESTBENCH_DIR = SCRIPT_DIR
REPO_ROOT = TESTBENCH_DIR.parent.parent  # test/deltares_testbench -> Delft3D

DVC_CACHE_DIR = REPO_ROOT / ".dvc" / "cache"
DATA_CASES = TESTBENCH_DIR / "data" / "cases"
DATA_REFS = TESTBENCH_DIR / "data" / "reference_results"
LOGS_DIR = TESTBENCH_DIR / "logs"
RESULTS_DIR = LOGS_DIR / "benchmark_results"

IS_WINDOWS = platform.system() == "Windows"
PLATFORM_DIR = "win64" if IS_WINDOWS else "lnx64"

if IS_WINDOWS:
    PYTHON = str(TESTBENCH_DIR / ".venv" / "Scripts" / "python.exe")
else:
    PYTHON = str(TESTBENCH_DIR / ".venv" / "bin" / "python")


# ── Helpers ──────────────────────────────────────────────────────────────────


def clean_data() -> None:
    """Remove all downloaded data except git-tracked .dvc files."""
    print(f"  Cleaning downloaded data in {DATA_CASES} ...")
    if DATA_CASES.exists():
        for item in DATA_CASES.rglob("*"):
            if item.is_file() and item.suffix != ".dvc":
                item.unlink()
        # Remove empty directories bottom-up
        for dirpath in sorted(DATA_CASES.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                dirpath.rmdir()

    print(f"  Cleaning reference results in {DATA_REFS} ...")
    if DATA_REFS.exists():
        shutil.rmtree(DATA_REFS)
    DATA_REFS.mkdir(parents=True, exist_ok=True)


def _remove_readonly(func, path, _excinfo):
    """Error handler for shutil.rmtree to clear read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clean_dvc_cache() -> None:
    """Wipe the DVC cache."""
    print(f"  Cleaning DVC cache at {DVC_CACHE_DIR} ...")
    if DVC_CACHE_DIR.exists():
        shutil.rmtree(DVC_CACHE_DIR, onerror=_remove_readonly)
    DVC_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def restore_dvc_files() -> None:
    """Restore .dvc files from git."""
    print("  Restoring .dvc files from git ...")
    subprocess.run(
        ["git", "checkout", "--", "test/deltares_testbench/data/cases/"],
        cwd=str(REPO_ROOT),
        check=True,
    )


def save_logs(label: str) -> None:
    """Copy logs to the benchmark results directory."""
    dest = RESULTS_DIR / label
    dest.mkdir(parents=True, exist_ok=True)

    for log_file in LOGS_DIR.glob("*.log"):
        shutil.copy2(log_file, dest / log_file.name)

    for log_dir in LOGS_DIR.iterdir():
        if log_dir.is_dir() and log_dir.name.startswith("e03_"):
            shutil.copytree(log_dir, dest / log_dir.name, dirs_exist_ok=True)

    print(f"  Logs saved to {dest}")


def run_benchmark(label: str, config: str, username: str, password: str) -> float:
    """Run a single benchmark: clean, execute, save logs. Returns wall time in seconds."""
    print()
    print("=" * 66)
    print(f" Running: {label}")
    print(f" Config:  {config}")
    print("=" * 66)

    print("-- Step 1: Clean state --")
    clean_data()
    clean_dvc_cache()
    restore_dvc_files()

    print("-- Step 2: Run testbench --")
    cmd = [
        PYTHON,
        "TestBench.py",
        "--username",
        username,
        "--password",
        password,
        "--compare",
        "--log-level",
        "DEBUG",
        "--parallel",
        "--config",
        config,
    ]

    full_log = LOGS_DIR / f"{label}.full.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    with open(full_log, "w") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(TESTBENCH_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            log_fh.write(line)
        proc.wait()
    duration = time.monotonic() - start

    print(f"\n  Wall time for {label}: {duration:.3f}s")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{label}.walltime").write_text(f"{duration:.3f}")

    print("-- Step 3: Save logs --")
    save_logs(label)

    return duration


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MinIO vs DVC testbench speed.")
    parser.add_argument("--username", required=True, help="MinIO/S3 username")
    parser.add_argument("--password", required=True, help="MinIO/S3 password")
    parser.add_argument("--only", choices=["minio", "dvc"], help="Run only one of the benchmarks.")
    args = parser.parse_args()

    minio_config = f"configs/dwaq_dpart/{PLATFORM_DIR}/dwaq_minio.xml"
    dvc_config = f"configs/dwaq_dpart/{PLATFORM_DIR}/dwaq_dvc.xml"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Benchmark results will be saved to: {RESULTS_DIR}")
    print(f"Platform: {platform.system()} ({PLATFORM_DIR})")

    minio_time = None
    dvc_time = None

    if args.only != "dvc":
        minio_time = run_benchmark("minio", minio_config, args.username, args.password)

    if args.only != "minio":
        dvc_time = run_benchmark("dvc", dvc_config, args.username, args.password)

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    print("=" * 66)
    print(" BENCHMARK SUMMARY")
    print("=" * 66)

    if minio_time is not None:
        print(f"  MinIO wall time: {minio_time:.3f}s")
    else:
        stored = RESULTS_DIR / "minio.walltime"
        if stored.exists():
            minio_time = float(stored.read_text().strip())
            print(f"  MinIO wall time: {minio_time:.3f}s (from previous run)")

    if dvc_time is not None:
        print(f"  DVC   wall time: {dvc_time:.3f}s")
    else:
        stored = RESULTS_DIR / "dvc.walltime"
        if stored.exists():
            dvc_time = float(stored.read_text().strip())
            print(f"  DVC   wall time: {dvc_time:.3f}s (from previous run)")

    if minio_time and dvc_time:
        ratio = minio_time / dvc_time
        print(f"  Ratio (MinIO/DVC): {ratio:.2f}x")
    print()
    print("  Log files:")
    print(f"    MinIO: {RESULTS_DIR / 'minio'}")
    print(f"    DVC:   {RESULTS_DIR / 'dvc'}")
    print("=" * 66)


if __name__ == "__main__":
    main()
