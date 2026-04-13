"""Executes DVC commands.

Copyright (C)  Stichting Deltares, 2025
"""

import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from dvc.repo import Repo
from dvc.scm import NoSCM

from src.config.credentials import Credentials
from src.utils.handlers.i_handler import IHandler
from src.utils.logging.i_logger import ILogger

_AWS_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
_DVC_FETCH_JOBS_ENV = "DVC_FETCH_JOBS"


@contextmanager
def _aws_credentials(credentials: Credentials) -> Iterator[None]:
    """Temporarily inject S3/MinIO credentials as env vars, restoring afterwards."""
    prev_env = {k: os.environ.get(k) for k in _AWS_KEYS}
    if credentials and credentials.username:
        os.environ[_AWS_KEYS[0]] = credentials.username
        os.environ[_AWS_KEYS[1]] = credentials.password
    try:
        yield
    finally:
        for key, val in prev_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


class DvcHandler(IHandler):
    """DVC wrapper, has handler interface."""

    def __init__(self, repo: Repo | None = None) -> None:
        if repo is not None:
            self.__repo = repo
        else:
            current_file_path = os.getcwd()
            repo_root = self.__find_dvc_root(current_file_path)
            self.__repo = Repo(repo_root, scm=NoSCM())

    def download(
        self, from_path: str, to_path: str, credentials: Credentials, version: Optional[str], logger: ILogger
    ) -> None:
        """Set up a DVC client connection.

        You can specify the download source and destination.

        Parameters
        ----------
        from_path : str
            dvc file path.
        to_path : str
            Deprecated: use from_path as the location of the .dvc file.
        credentials : Credentials
            DVC credentials (used for remote storage access).
        version : str
            Not used for DVC, version is already in md5 hash of the .dvc file.
        logger : ILogger
            The logger that logs to a file.
        """
        self.__download_with_dvc_pull(from_path, credentials, logger)

    def download_batch(
        self, dvc_files: list[str], credentials: Credentials, logger: ILogger, jobs: Optional[int] = None
    ) -> None:
        """Download multiple .dvc files in a single fetch + checkout operation.

        Parameters
        ----------
        dvc_files : list[str]
            Paths to .dvc files to download.
        credentials : Credentials
            DVC credentials (used for remote storage access).
        logger : ILogger
            Logger instance.
        jobs : Optional[int]
            Number of parallel jobs for DVC fetch. Similar to ``dvc pull -j``.
            When *None*, DVC uses its own default.
        """
        if not dvc_files:
            return

        jobs = self.__resolve_fetch_jobs(jobs, logger)
        batch_start = time.perf_counter()
        with _aws_credentials(credentials):
            resolve_start = time.perf_counter()
            all_targets = self.__resolve_dvc_targets(dvc_files, logger)
            logger.info(
                f"DVC resolve: {len(dvc_files)} .dvc files -> {len(all_targets)} targets in "
                f"{time.perf_counter() - resolve_start:.2f}s"
            )

            fetch_checkout_start = time.perf_counter()
            self.__fetch_and_checkout(all_targets, logger, jobs)
            logger.info(
                f"DVC fetch+checkout total: {len(all_targets)} targets in "
                f"{time.perf_counter() - fetch_checkout_start:.2f}s"
            )

            verify_start = time.perf_counter()
            self.__verify_output_dirs(dvc_files, logger)
            logger.info(
                f"DVC verify: {len(dvc_files)} output directories checked in {time.perf_counter() - verify_start:.2f}s"
            )
            logger.info(
                f"Batch DVC download complete for {len(dvc_files)} .dvc files in "
                f"{time.perf_counter() - batch_start:.2f}s"
            )

    @staticmethod
    def __resolve_fetch_jobs(jobs: Optional[int], logger: ILogger) -> Optional[int]:
        """Resolve fetch parallelism from explicit argument or environment."""
        if jobs is not None:
            return jobs

        configured_jobs = os.getenv(_DVC_FETCH_JOBS_ENV)
        if not configured_jobs:
            return None

        try:
            parsed_jobs = int(configured_jobs)
        except ValueError:
            logger.warning(
                f"Ignoring invalid {_DVC_FETCH_JOBS_ENV} value '{configured_jobs}'; expected integer"
            )
            return None

        if parsed_jobs <= 0:
            logger.warning(f"Ignoring invalid {_DVC_FETCH_JOBS_ENV} value '{configured_jobs}'; expected > 0")
            return None

        logger.info(f"Using DVC fetch jobs from environment: {parsed_jobs}")
        return parsed_jobs

    def __download_with_dvc_pull(self, dvc_file: str, credentials: Credentials, logger: ILogger) -> None:
        """Download using DVC by reading the .dvc file and fetching from remote.

        Parameters
        ----------
        dvc_file : str
            Path to the .dvc file (e.g., "data/cases/e02_f002_c100.dvc").
        credentials : Credentials
            Credentials whose username maps to the S3 access key ID and
            password maps to the S3 secret access key.
        logger : ILogger
            Logger instance.
        """
        with _aws_credentials(credentials):
            targets = self.__resolve_dvc_targets([dvc_file], logger)
            self.__fetch_and_checkout(targets, logger)
            logger.info(f"Downloading DVC directory complete: {dvc_file}")

    def __resolve_dvc_targets(self, dvc_files: list[str], logger: ILogger) -> list[str]:
        """Resolve .dvc file paths to absolute paths, validating each exists."""
        targets: list[str] = []
        for dvc_file in dvc_files:
            resolved = os.path.realpath(dvc_file)
            logger.debug(f"Loading DVC file: {resolved}")
            if not os.path.isfile(resolved):
                raise FileNotFoundError(f"DVC file not found: {resolved}")
            targets.append(resolved)
        return targets

    def __fetch_and_checkout(self, targets: list[str], logger: ILogger, jobs: Optional[int] = None) -> None:
        """Run DVC fetch + checkout for the given targets."""
        logger.debug(f"DVC repo root: {self.__repo.root_dir}")
        logger.debug(f"DVC targets: {targets}")

        logger.info(f"Fetching {len(targets)} DVC targets (jobs={jobs})")
        fetch_start = time.perf_counter()
        fetch_result = self.__repo.fetch(targets=targets, jobs=jobs)
        logger.debug(f"Fetch result: {fetch_result}")
        logger.info(f"DVC fetch finished in {time.perf_counter() - fetch_start:.2f}s")

        logger.info(f"Checking out {len(targets)} DVC targets")
        checkout_start = time.perf_counter()
        checkout_result = self.__repo.checkout(targets=targets, force=True)
        logger.debug(f"Checkout result: {checkout_result}")
        logger.info(f"DVC checkout finished in {time.perf_counter() - checkout_start:.2f}s")

    @staticmethod
    def __verify_output_dirs(dvc_files: list[str], logger: ILogger) -> None:
        """Verify that DVC checkout produced the expected output directories."""
        missing = []
        for dvc_file in dvc_files:
            expected_dir = os.path.splitext(os.path.realpath(dvc_file))[0]
            if not os.path.isdir(expected_dir):
                missing.append(expected_dir)
        if missing:
            logger.error(f"DVC checkout completed but {len(missing)} expected directories are missing:")
            for m in missing:
                logger.error(f"  - {m}")
            raise FileNotFoundError(
                f"DVC checkout did not produce {len(missing)} expected directories. First missing: {missing[0]}"
            )

    def __find_dvc_root(self, path: str) -> str:
        """Find the DVC repository root by looking for .dvc directory.

        Parameters
        ----------
        path : str
            Starting path to search from.

        Returns
        -------
        str
            Path to the DVC repository root.
        """
        current = os.path.dirname(os.path.abspath(path))
        while True:
            if os.path.isdir(os.path.join(current, ".dvc")):
                return os.path.realpath(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        raise ValueError("Could not find DVC repository root (.dvc directory)")
