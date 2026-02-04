"""Path helper.

Copyright (C)  Stichting Deltares, 2026
"""

import os
import re
from pathlib import Path
from typing import List


# Path helpers
class Paths:
    """Path helper class."""

    def split_network_path(self, path: Path) -> tuple[str, str, str]:
        """Split network path in server, folder and rest with os.sep.

        input: path
        output: server part, folder part, left over part
        """
        lfrom = str(path)

        # Split on both Windows and Unix separators, tolerate leading/trailing slashes.
        parts = [p for p in re.split(r"[\\/]+", lfrom.strip("\\/")) if p]

        server = parts[0] if len(parts) > 0 else ""
        folder = parts[1] if len(parts) > 1 else ""

        rest_parts = parts[2:] if len(parts) > 2 else []
        rest = os.sep.join(rest_parts) + (os.sep if rest_parts else "")

        return server, folder, rest

    def is_path(self, path: Path | str) -> bool:
        """Check if a given path string is an actual path.

        input: path
        output: boolean
        """
        path_str = str(path)

        if "/" in path_str:
            if path_str.startswith("/") and path_str.count("/") == 1:
                return False
            if not re.match(r"^[A-Za-z][A-Za-z]+://", path_str):
                return True
        if "\\" in path_str:
            return True
        return False

    def is_absolute(self, path: Path | str) -> bool:
        """Check if the given path is an absolute path.

        input: path
        output: boolean
        """
        path_str = str(path)
        if path_str[0] == "/" or re.match(r"^[A-Za-z]:", path_str):
            return True
        return False

    def rebuild_to_local_path(self, path: Path | str) -> str:
        """Ensure valid local system path.

        input: some local path string
        output: valid system path
        """
        # if path starts with a /, put that in result; it will be removed during splitting
        path_str = str(path)
        if path_str == "":
            return path_str
        if path_str[0] == "/":
            result = "/"
        else:
            result = ""
        # split in windows paths
        wpes = self.__convert_absolute_to_literal(path_str).split("\\")
        for wpe in wpes:
            # split in linux path elements
            lpes = wpe.split("/")
            for lpe in lpes:
                if re.match(r"^[A-Za-z]:", lpe):
                    lpe = lpe + "\\"
                result = os.path.join(result, lpe)
        return result

    def merge_path_elements(self, left: Path | None, right: Path | None) -> Path:
        """Assumes left is correct notation.

        input: left part and right part of path string
        output: merged path assuming left part of string is correct notation
        """
        fws = "/"
        bws = "\\"

        if left is not None and not isinstance(left, Path):
            raise TypeError("merge_path_elements expects Path values for 'left'")
        if right is not None and not isinstance(right, Path):
            raise TypeError("merge_path_elements expects Path values for 'right'")

        if left is None or str(left) in ("", "."):
            return Path() if right is None or str(right) in ("", ".") else Path(right)
        if right is None or str(right) in ("", "."):
            return Path(left)

        left_str = str(left)
        right_str = str(right)

        # Make sure that the handlers can accept URIs that contain spaces.
        if "://" in left_str:
            left_str = left_str.replace(" ", "%20")
            right_str = right_str.replace(" ", "%20")


        # remove ending slashes from left part
        tl = left_str
        tr = right_str
        while tl.endswith(fws):
            tl = tl[0 : tl.rfind(fws)]
        while tl.endswith(bws):
            tl = tl[0 : tl.rfind(bws)]
        # remove leading slashes from right part
        while tr.find(fws) == 0:
            tr = tr[1:]
        while tr.find(bws) == 0:
            tr = tr[1:]
        # if left is forward slashed
        if left_str.find(fws) >= 0:
            # invert backslashed if they exist in right
            return Path(tl + fws + tr.replace(bws, fws))
        # if left is backward slashed
        if left_str.find(bws) >= 0:
            # invert forward slashed if they exist in right
            return Path(tl + bws + tr.replace(fws, bws))
        # if left has no slashes and right is forward slashed
        if right_str.find(fws) >= 0:
            # put a forwards slash between left and right
            return Path(tl + fws + tr)
        # if left is backward slashed
        if right_str.find(bws) >= 0:
            # put a backwards slash between left and right
            return Path(tl + bws + tr)
        # No slashes in left or right, choose something

        return Path(tl + fws + tr)

    def merge_full_path(self, left: Path | None, *args: Path | None) -> Path:
        """Merge path parts.

        input: left and rest (variable args)
        output: string formatted on left as origin
        """
        if left is not None and not isinstance(left, Path):
            raise TypeError("merge_full_path expects Path values")
        for arg in args:
            if arg is not None and not isinstance(arg, Path):
                raise TypeError("merge_full_path expects Path values")
        parts = [p for p in (left, *args) if p is not None and str(p) not in ("", ".")]
        if not parts:
            return Path()

        result = Path(parts[0])
        for a in parts[1:]:
            result = self.merge_path_elements(result, a)
        return result

    def find_all_sub_folders(self, root: Path, exclude_paths_containing: str) -> List[Path]:
        """Find all sub directory paths from a given path.

        input: root path to search from string identifying paths that should be excluded
        output: list of absolute paths
        """
        root_path = Path(root)
        if exclude_paths_containing == "":
            return [Path(x[0]).resolve() for x in os.walk(root_path)]
        else:
            return [Path(x[0]).resolve() for x in os.walk(root_path) if exclude_paths_containing not in str(x[0])]

    def find_all_sub_files(self, root: Path) -> List[Path]:
        """Find all files in all sub directories from a given path.

        input: root path to search from
        output: list of file names
        """
        root_path = Path(root).resolve()
        retval: List[Path] = []
        for subdir in self.find_all_sub_folders(root_path, ""):
            subdir_path = Path(subdir)
            rel_dir = Path(os.path.relpath(subdir_path, root_path))
            if rel_dir == Path("."):
                rel_dir = Path()
            for f in subdir_path.iterdir():
                if f.is_file():
                    retval.append(rel_dir / f.name)
        return retval

    @staticmethod
    def is_url(path: Path | str) -> bool:
        return re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", str(path)) is not None

    def __convert_absolute_to_literal(self, path: str) -> str:
        r"""Convert a path string containing \ -> \\"""
        # convert double backslash to single
        conv = re.sub(r"(\\\\)", r"\\", path)
        return re.sub(r"(?<!\\)+\\(?!\\)+", r"\\", conv)
