"""Local Paths Data Class.

Copyright (C)  Stichting Deltares, 2026
"""

from pathlib import Path


class LocalPaths:
    """Class containing locations to given root directories."""

    def __init__(
        self,
        cases_path: Path = Path("cases"),
        engines_path: Path = Path("engines"),
        references_path: Path = Path("references"),
    ) -> None:
        self.__cases_path: Path = Path(cases_path)
        self.__engines_path: Path = Path(engines_path)
        self.__reference_path: Path = Path(references_path)

    @property
    def cases_path(self) -> Path:
        """Path to the data of the test cases."""
        return self.__cases_path

    @cases_path.setter
    def cases_path(self, value: Path) -> None:
        self.__cases_path = value

    @property
    def engines_path(self) -> Path:
        """Path to the engines (executables to run)."""
        return self.__engines_path

    @engines_path.setter
    def engines_path(self, value: Path) -> None:
        self.__engines_path = value

    @property
    def reference_path(self) -> Path:
        """Path to the reference data."""
        return self.__reference_path

    @reference_path.setter
    def reference_path(self, value: Path) -> None:
        self.__reference_path = value
