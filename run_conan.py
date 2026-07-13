from __future__ import annotations

import argparse
from dataclasses import dataclass
import enum
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_CONAN_PROFILE_LINUX = "delft3d_alma8_intel_2024_v3"
DEFAULT_CONAN_PROFILE_WINDOWS = "delft3d_windows_msvc_194_v3"
CONAN_PROFILE_ENV_VAR = "CONAN_DEFAULT_PROFILE"

# macOS has no single fixed profile name: the Homebrew prefix, the
# installed gfortran-NN version, and the Apple Clang major version all
# vary per machine (and per Homebrew upgrade). `delft3d_macos_apple_clang_21`
# below is kept as a documented, human-readable *example* of what a
# generated profile looks like -- the actual profile used at
# install/lock time is generated fresh for the current host by
# `_generate_macos_profile()` (see MACOS_GENERATED_PROFILE).
MACOS_EXAMPLE_PROFILE = "delft3d_macos_apple_clang_21"

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "conan/config"
RECIPES_DIR = ROOT / "conan/recipes"
LOCKFILE = ROOT / "conan.lock"

# Host-specific, not checked in (see .gitignore): regenerated on every run
# from whatever Homebrew/gfortran/Apple Clang happen to be installed.
MACOS_GENERATED_PROFILE = ROOT / "conan/.generated/delft3d_macos_detected"


@dataclass(frozen=True)
class PackageInfo:
    name_version: str
    revision_id: str
    package_id: str

    @property
    def identifier(self) -> str:
        return f"{self.name_version}#{self.revision_id}:{self.package_id}"


def _conan_config_install(*, ci: bool) -> None:
    cmd = ["conan", "config", "install", "--type", "dir", str(CONFIG_DIR)]
    if ci:
        cmd += ["--core-conf", "core:non_interactive=True"]
    subprocess.run(cmd, check=True)


def _register_local_recipes() -> None:
    """Register the local recipes folder with highest priority."""
    subprocess.run(
        [
            "conan",
            "remote",
            "add",
            "local-recipes",
            str(RECIPES_DIR.parent.resolve()),
            "--type=local-recipes-index",
            "--index=0",
            "--force",
        ],
        check=True,
    )


def setup_conan_config_deltares(*, ci: bool = False) -> None:
    """Install full Conan configuration including Deltares Nexus remotes and register local recipes."""
    _conan_config_install(ci=ci)
    _register_local_recipes()


def setup_conan_config_external(*, ci: bool = False) -> None:
    """Install Conan configuration (profiles, settings) without Nexus remotes.

    Removes all remotes installed by the config (i.e. the Deltares Nexus instances)
    and registers only the local recipes folder.  Use this when Nexus is not accessible.
    """
    _conan_config_install(ci=ci)

    # Remove all remotes that were just installed from remotes.json so that no
    # network access to Nexus is attempted later.
    subprocess.run(["conan", "remote", "remove", "*"], check=True)

    _register_local_recipes()


class BuildPolicy(enum.Enum):
    NONE = "none"  # Build no packages from source, only use pre-built binaries from remotes.
    MISSING = "missing"  # Build packages from source if a pre-built binary is not available from remotes.
    ALL = "all"  # Build all packages from source using local recipes only, do not use any pre-built binaries from remotes.


def clean_conan_cache() -> None:
    subprocess.run(["conan", "remove", "*", "--confirm"], check=True)
    subprocess.run(["conan", "cache", "clean"], check=True)


@contextmanager
def _isolated_conan_home() -> Generator[Path, None, None]:
    """Run a block with CONAN_HOME pointed at a fresh, temporary directory.

    Ensures that the lockfile can be deterministically generated and
    that the user's real Conan cache is left untouched.
    """
    tmp = Path(tempfile.mkdtemp(prefix="conan-lockgen-"))
    prev = os.environ.get("CONAN_HOME")
    os.environ["CONAN_HOME"] = str(tmp)
    try:
        yield tmp
    finally:
        if prev is None:
            os.environ.pop("CONAN_HOME", None)
        else:
            os.environ["CONAN_HOME"] = prev
        shutil.rmtree(tmp, ignore_errors=True)


def update_lockfile(profile: str) -> None:
    """Regenerate conan.lock from the current conanfile and local recipes.

    Runs `conan lock create` against an isolated, throw-away `CONAN_HOME` so
    that only the `local-recipes` remote can influence dependency resolution
    (the user's existing cache cannot leak versions or revisions into the
    lockfile via newer timestamps / higher version-range matches).
    """
    if LOCKFILE.exists():
        print(f"Removing existing lockfile {LOCKFILE}...")
        LOCKFILE.unlink()

    with _isolated_conan_home() as home:
        print(f"Using isolated CONAN_HOME={home}")
        setup_conan_config_external()

        cmd = [
            "conan",
            "lock",
            "create",
            ".",
            f"--profile:all={profile}",
            "--settings:all",
            "build_type=Release",
            f"--lockfile-out={LOCKFILE}",
            "--remote=local-recipes",
            "--update",
        ]

        print(f"Generating lockfile {LOCKFILE}...")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            # Do not leave a partial/inconsistent lockfile behind.
            if LOCKFILE.exists():
                LOCKFILE.unlink()
            raise


def conan_install(
    profile: str,
    output_folder: Path,
    build_type: str,
    *,
    consumer_build_type: str | None = None,
    ci: bool = False,
    build_policy: BuildPolicy = BuildPolicy.NONE,
) -> None:
    cmd = [
        "conan",
        "install",
        f"--profile:all={profile}",
        "--settings:all",
        f"build_type={build_type}",
        f"--output-folder={output_folder}",
        f"--lockfile={LOCKFILE}",
        # Large source archives can exceed Conan's default 60-second read timeout.
        "--core-conf",
        "core.net.http:timeout=300",
    ]

    if build_policy == BuildPolicy.ALL:
        cmd += ["--build=*", "--remote=local-recipes"]
    elif build_policy == BuildPolicy.MISSING:
        cmd += ["--build=missing"]

    if ci:
        cmd += ["--core-conf", "core:non_interactive=True"]

    if consumer_build_type:
        # Odd syntax explained here: https://github.com/conan-io/conan/issues/13478#issuecomment-1475389368
        cmd += ["--settings:all", f"&:build_type={consumer_build_type}"]

    subprocess.run(cmd, check=True)


def _list_conan_packages(pattern: str, remote: str | None = None) -> dict[str, Any]:
    """Invoke `conan list` with the given pattern and remote."""
    args = ["conan", "list", pattern, "--format=json"]
    if remote is not None:
        args.append(f"--remote={remote}")

    process = subprocess.run(args, capture_output=True, text=True, check=True)
    obj = json.loads(process.stdout)
    repo_key = remote or "Local Cache"
    if not isinstance(obj, dict):
        raise ValueError(f"Failed to list {repo_key}. Response: {obj}")

    repo_object = obj.get(repo_key)
    if not isinstance(repo_object, dict):
        raise ValueError(f"Failed to list {repo_key}. Response: {obj})")

    error = repo_object.get("error")
    if error is not None:
        # If `pattern` matches no packages/revisions, the "error" property is set with this content:
        # - package name/version can't be found: "404: Not Found. [Remote: remote]"
        # - package revision can't be found: "Recipe revision 'name/version#revision_id' not found"
        # - package id can't be found: "Package ID 'name/version#revision_id:package_id' not found"
        if "not found" in str(error).lower():
            # Not an error: We use this to test if a package is present on the remote.
            return {}
        raise ValueError(f"Failed to list {repo_key}. Error message in reponse: {error}")

    return repo_object


def _iter_revisions(name_version: str, revisions_map: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Walks through `conan list` revision object and yields `(revision_id, package_id)` pairs."""
    for revision_id, revision_obj in revisions_map.items():
        package_map = revision_obj.get("packages")
        if not isinstance(package_map, dict):
            raise ValueError(f".{name_version}.revisions.{revision_id}.packages must be an object. Got: {package_map}")

        for package_id in package_map.keys():
            yield revision_id, package_id


def _iter_packages(repo_object: dict[str, Any]) -> Iterator[PackageInfo]:
    """Walks through `conan list` repo object and yields `PackageInfo`s."""
    for name_version, revisions_data in repo_object.items():
        if not isinstance(revisions_data, dict):
            raise ValueError(f".{name_version} be an object. Got: {revisions_data}")

        revisions_map = revisions_data.get("revisions")
        if not isinstance(revisions_map, dict):
            raise ValueError(f".{name_version}.revisions must be an object. Got: {revisions_map}")

        for revision_id, package_id in _iter_revisions(name_version, revisions_map):
            yield PackageInfo(name_version=name_version, revision_id=revision_id, package_id=package_id)


def _remote_contains_package(remote: str, package_info: PackageInfo) -> bool:
    """Test membership of package in remote Conan repository."""
    repo_object = _list_conan_packages(package_info.identifier, remote)
    return next(_iter_packages(repo_object), None) is not None


def upload_new_packages(remote: str, *, ci: bool = False) -> None:
    """Upload only packages whose recipe_revision + package_id don't exist on the remote yet."""
    local_cache_packages = _list_conan_packages("*:*")

    uploaded = 0
    skipped = 0
    for package_info in _iter_packages(local_cache_packages):
        if _remote_contains_package(remote, package_info):
            print(f"SKIP (already on remote): {package_info.identifier}")
            skipped += 1
        else:
            print(f"UPLOAD: {package_info.identifier}")
            cmd = ["conan", "upload", package_info.identifier, f"--remote={remote}", "--confirm", "--check"]
            if ci:
                cmd += ["--core-conf", "core:non_interactive=True"]
            subprocess.run(cmd, check=True)
            uploaded += 1

    print(f"\nDone. Uploaded: {uploaded}, skipped: {skipped}")


def _brew_prefix() -> Path:
    """Locate the Homebrew prefix, without assuming any particular user account.

    Tries `brew --prefix` first (correct on both Apple Silicon and Intel,
    and for non-default install locations); falls back to the two
    well-known default prefixes if `brew` itself is not on PATH.
    """
    brew = shutil.which("brew")
    if brew is not None:
        result = subprocess.run([brew, "--prefix"], capture_output=True, text=True)
        if result.returncode == 0:
            prefix = Path(result.stdout.strip())
            if prefix.is_dir():
                return prefix

    for candidate in (Path("/opt/homebrew"), Path("/usr/local")):
        if (candidate / "bin").is_dir():
            return candidate

    raise RuntimeError(
        "Could not locate a Homebrew installation (tried `brew --prefix`, "
        "then /opt/homebrew and /usr/local). Install Homebrew "
        "(https://brew.sh) and a Fortran compiler (`brew install gcc`) first."
    )


def _gfortran_version_key(path: Path) -> int:
    """Extract the trailing version number from e.g. 'gfortran-16' -> 16."""
    suffix = path.name.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else -1


def _latest_gfortran(brew_prefix: Path) -> Path:
    """Pick the newest Homebrew gfortran-NN under `brew_prefix/bin`.

    Delft3D FM needs a real Fortran compiler; Apple Clang has no Fortran
    front end, so this is always a Homebrew (or similarly installed) GNU
    toolchain, never the system Clang. Picking the *latest* installed
    version (rather than pinning one) keeps this working across gfortran
    upgrades without editing this file.
    """
    candidates = sorted(
        (p for p in brew_prefix.glob("bin/gfortran-*") if p.is_file() or p.is_symlink()),
        key=_gfortran_version_key,
    )
    if candidates:
        return candidates[-1]

    bare = brew_prefix / "bin" / "gfortran"
    if bare.exists():
        return bare

    raise RuntimeError(
        f"No gfortran found under {brew_prefix}/bin (looked for 'gfortran-NN' "
        "and a bare 'gfortran'). Install one with `brew install gcc`."
    )


def _apple_clang_major_version() -> int:
    """Parse the major version out of `clang --version` (Apple Clang only).

    Apple Clang's version numbering is independent of upstream LLVM's, and
    Conan's `compiler.version` setting for `apple-clang` expects Apple's
    own major version (e.g. the "17" in "Apple clang version 17.0.0
    (clang-1700.0.13.3)"), so this must read the installed Clang directly
    rather than assume a fixed value.
    """
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError(
            "`clang` not found on PATH. Install the Xcode Command Line Tools "
            "(`xcode-select --install`) first."
        )
    result = subprocess.run([clang, "--version"], capture_output=True, text=True, check=True)
    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.search(r"version (\d+)", first_line)
    if not match:
        raise RuntimeError(
            f"Could not parse an Apple Clang version from `clang --version` output: "
            f"{first_line!r}"
        )
    return int(match.group(1))


def _conan_arch() -> str:
    machine = platform.machine()
    if machine in ("arm64", "aarch64"):
        return "armv8"
    if machine in ("x86_64", "AMD64"):
        return "x86_64"
    raise RuntimeError(f"Unrecognized macOS architecture from platform.machine(): {machine!r}")


def _generate_macos_profile() -> Path:
    """Detect this Mac's toolchain and (re)write a Conan profile for it.

    Replaces a single checked-in profile that pinned one developer's home
    directory and exact Apple Clang major version: those are properties of
    the machine running the build, not of the Delft3D source tree, so they
    are detected here every time instead of being committed.
    `MACOS_EXAMPLE_PROFILE` in conan/config/profiles/ remains as a worked
    example of the resulting file for anyone reading the repo without
    running this script.
    """
    brew_prefix = _brew_prefix()
    gfortran = _latest_gfortran(brew_prefix)
    clang_major = _apple_clang_major_version()
    clang_path = shutil.which("clang") or "/usr/bin/clang"
    clangxx_path = shutil.which("clang++") or "/usr/bin/clang++"
    arch = _conan_arch()

    profile_text = (
        "# Generated by run_conan.py's _generate_macos_profile() -- do not edit by\n"
        "# hand, it is overwritten on every run. See conan/config/profiles/"
        f"{MACOS_EXAMPLE_PROFILE} for a documented, checked-in example.\n"
        "[settings]\n"
        f"arch={arch}\n"
        "compiler=apple-clang\n"
        "compiler.cppstd=20\n"
        "compiler.libcxx=libc++\n"
        f"compiler.version={clang_major}\n"
        "os=Macos\n"
        "\n"
        "[conf]\n"
        "tools.build:compiler_executables="
        f'{{"c": "{clang_path}", "cpp": "{clangxx_path}", "fortran": "{gfortran}"}}\n'
    )

    MACOS_GENERATED_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    MACOS_GENERATED_PROFILE.write_text(profile_text)
    return MACOS_GENERATED_PROFILE


def _get_default_profile() -> str:
    os_name = platform.system()
    if os_name == "Windows":
        return DEFAULT_CONAN_PROFILE_WINDOWS
    if os_name == "Darwin":
        # No single fixed macOS profile: generate one for this host's
        # Homebrew/gfortran/Apple Clang and return its absolute path.
        try:
            return str(_generate_macos_profile())
        except RuntimeError as exc:
            sys.exit(f"ERROR: {exc}")
    return DEFAULT_CONAN_PROFILE_LINUX


def _get_profile_or_default(profile_override: str | None) -> str:
    return profile_override or os.environ.get(CONAN_PROFILE_ENV_VAR) or _get_default_profile()


def _require_profile(profile: str) -> None:
    default_profile = _get_default_profile()
    for candidate in dict.fromkeys((default_profile, profile)):
        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            # macOS: a freshly generated profile file (see
            # _generate_macos_profile), not a name registered with conan --
            # just confirm it is there.
            if not candidate_path.is_file():
                sys.exit(f"ERROR: expected generated Conan profile at '{candidate}', but it is missing.")
            continue
        result = subprocess.run(
            ["conan", "profile", "path", candidate],
            capture_output=True,
        )
        if result.returncode != 0:
            sys.exit(
                f"ERROR: Conan profile '{candidate}' not found.\n"
                "       Run 'python run_conan.py initialize external' (or 'initialize deltares' on the network) "
                "first to install the latest profiles, configure settings and set up remotes.\n"
                f"       If {CONAN_PROFILE_ENV_VAR} is set, update it to the latest profile name or unset it."
            )


def _do_install(
    profile: str,
    output_folder: Path,
    build_type: str,
    *,
    ci: bool = False,
    build_policy: BuildPolicy = BuildPolicy.NONE,
) -> None:
    os_name = platform.system()
    if os_name == "Windows":
        # Multi-config generator: generate CMakeDeps for all three configurations.
        # Only the first install builds packages; the other two reuse the cache.
        conan_install(
            profile,
            output_folder,
            "Release",
            ci=ci,
            build_policy=build_policy,
        )
        conan_install(
            profile,
            output_folder,
            "Release",
            consumer_build_type="Debug",
            ci=ci,
        )
        conan_install(
            profile,
            output_folder,
            "Release",
            consumer_build_type="RelWithDebInfo",
            ci=ci,
        )
    else:
        # Single-config generator: one install for the requested build type.
        # Packages are always built as Release; consumer_build_type controls the CMakeDeps output.
        conan_install(
            profile,
            output_folder,
            "Release",
            consumer_build_type=build_type,
            ci=ci,
            build_policy=build_policy,
        )


def cmd_init(args: argparse.Namespace) -> None:
    if args.mode == "deltares":
        setup_conan_config_deltares(ci=args.ci)
    else:
        setup_conan_config_external(ci=args.ci)


def cmd_clean_cache(args: argparse.Namespace) -> None:
    clean_conan_cache()


def cmd_update_lockfile(args: argparse.Namespace) -> None:
    profile = _get_profile_or_default(args.profile)
    _require_profile(profile)
    update_lockfile(profile)


def cmd_install(args: argparse.Namespace) -> None:
    profile = _get_profile_or_default(args.profile)
    _require_profile(profile)

    if args.rebuild_packages:
        build_policy = BuildPolicy.ALL
    elif args.build_missing:
        build_policy = BuildPolicy.MISSING
    else:
        build_policy = BuildPolicy.NONE

    _do_install(
        profile,
        args.output_folder,
        args.build_type,
        ci=args.ci,
        build_policy=build_policy,
    )


def cmd_upload(args: argparse.Namespace) -> None:
    upload_new_packages(args.remote, ci=args.ci)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Conan dependencies for the Delft3D repository.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- initialize ---
    parser_init = subparsers.add_parser(
        "initialize",
        help="One-time Conan setup (profiles, settings, remotes).",
    )
    parser_init.add_argument(
        "mode",
        choices=["deltares", "external"],
        help=(
            "'deltares': installs profiles, settings and Deltares Nexus remotes. "
            "'external': installs profiles and settings only, without Nexus remotes."
        ),
    )
    parser_init.add_argument("--ci", action="store_true", help="Non-interactive mode.")
    parser_init.set_defaults(func=cmd_init)

    # --- clean-cache ---
    parser_clean_cache = subparsers.add_parser(
        "clean-cache",
        help="Clean the local Conan cache.",
    )
    parser_clean_cache.set_defaults(func=cmd_clean_cache)

    # --- update-lockfile ---
    parser_update_lockfile = subparsers.add_parser(
        "update-lockfile",
        help="Regenerate conan.lock from the current conanfile and recipes.",
    )
    parser_update_lockfile.add_argument(
        "--profile",
        help=(
            f"Conan profile (default: ${CONAN_PROFILE_ENV_VAR}, or {_get_default_profile()} "
            "when the environment variable is unset)."
        ),
    )
    parser_update_lockfile.set_defaults(func=cmd_update_lockfile)

    # --- install ---
    parser_install = subparsers.add_parser(
        "install",
        help="Install Conan-managed dependencies.",
    )
    parser_install.add_argument(
        "--profile",
        help=(
            f"Conan profile (default: ${CONAN_PROFILE_ENV_VAR}, or {_get_default_profile()} "
            "when the environment variable is unset)."
        ),
    )
    parser_install.add_argument("--ci", action="store_true", help="Non-interactive mode.")
    build_group = parser_install.add_mutually_exclusive_group()
    build_group.add_argument(
        "--build-missing",
        action="store_true",
        help="Build packages from source if a pre-built binary is not available.",
    )
    build_group.add_argument(
        "--rebuild-packages",
        action="store_true",
        help="Rebuild all packages from local recipes only.",
    )
    parser_install.add_argument(
        "--build-type",
        default="Release",
        choices=["Release", "Debug", "RelWithDebInfo"],
        help=(
            "CMake build type for the consumer. "
            "On Linux, determines which CMakeDeps files are generated. "
            "Ignored on Windows (all configurations are always generated)."
        ),
    )
    parser_install.add_argument(
        "--output-folder",
        type=Path,
        required=True,
        help="Output folder for Conan install files.",
    )
    parser_install.set_defaults(func=cmd_install)

    # --- upload ---
    parser_upload = subparsers.add_parser(
        "upload",
        help="Upload packages to a remote, skipping those already present (same recipe revision + package id).",
    )
    parser_upload.add_argument(
        "--remote",
        required=True,
        help="Name of the Conan remote to upload to.",
    )
    parser_upload.add_argument("--ci", action="store_true", help="Non-interactive mode.")
    parser_upload.set_defaults(func=cmd_upload)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
