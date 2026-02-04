"""TestCasePath Data Class.

Copyright (C)  Stichting Deltares, 2026
"""

import os
from pathlib import Path


class TestCasePath:
    """Class for registering path to test case data."""

    __test__ = False  # Pytest gets confused by classes with names starting with 'Test'.

    def __init__(self, prefix: Path | str, version: str | None = None) -> None:
        self.__prefix: str = os.fspath(Path(prefix))
        self.__version = version

    @property
    def prefix(self) -> str:
        """Get path prefix to the test case data."""
        return self.__prefix

    @prefix.setter
    def prefix(self, value: Path | str) -> None:
        """Set path prefix to the test case data."""
        self.__prefix = os.fspath(Path(value))

    @property
    def version(self) -> str | None:
        """Get version of test case data."""
        return self.__version

    @version.setter
    def version(self, value: str | None) -> None:
        """Set version of test case data."""
        self.__version = value
