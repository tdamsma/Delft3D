import os
from pathlib import Path

import pytest

from src.utils.paths import Paths


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("//server/folder/rest/sub", ("server", "folder", f"rest{os.sep}sub{os.sep}"), id="fwd"),
        pytest.param(
            "//server/folder/rest/sub/",
            ("server", "folder", f"rest{os.sep}sub{os.sep}"),
            id="fwd-trailing",
        ),
        pytest.param(
            r"\\server\folder\rest\sub",
            ("server", "folder", f"rest{os.sep}sub{os.sep}"),
            id="back",
        ),
        pytest.param(
            r"\\server\folder\rest\sub\\",
            ("server", "folder", f"rest{os.sep}sub{os.sep}"),
            id="back-trailing",
        ),
    ],
)
def test_split_network_path(path: str, expected: tuple[str, str, str]) -> None:
    # Arrange
    paths = Paths()

    # Act
    server, folder, rest = paths.splitNetworkPath(path)

    # Assert
    assert (server, folder, rest) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/etc/path", True, id="linux-absolute"),
        pytest.param("/etc/path/file.txt", True, id="linux-file"),
        pytest.param("relative/path", True, id="linux-relative"),
        pytest.param("justone/", True, id="single-slash-end"),
        pytest.param("/justone", False, id="single-slash-begin"),
        pytest.param("http://example.com/a/b", False, id="url-http"),
        pytest.param("https://example.com/a/b", False, id="url-https"),
        pytest.param(r"C:\\temp\\file.txt", True, id="windows-path"),
    ],
)
def test_is_path(path: str, expected: bool) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.isPath(path)

    # Assert
    assert result is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/etc/path", True, id="linux-absolute"),
        pytest.param("relative/path", False, id="linux-relative"),
        pytest.param(r"C:\\temp\\file.txt", True, id="windows-absolute"),
    ],
)
def test_is_absolute(path: str, expected: bool) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.isAbsolute(path)

    # Assert
    assert result is expected


def test_rebuild_to_local_path_normalizes_mixed_separators() -> None:
    # Arrange
    paths = Paths()
    mixed = "/a/b\\c/d"

    # Act
    result = paths.rebuildToLocalPath(mixed)

    # Assert
    assert result == os.path.join("/", "a", "b", "c", "d")


def test_rebuild_to_local_path_preserves_drive_letter() -> None:
    # Arrange
    paths = Paths()
    mixed = "C:/folder/sub"

    # Act
    result = paths.rebuildToLocalPath(mixed)

    # Assert
    assert result == os.path.join("C:\\", "folder", "sub")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        pytest.param(None, "fruit", "fruit", id="none-left"),
        pytest.param("", "fruit", "fruit", id="empty-left"),
        pytest.param("/etc/path", None, "/etc/path", id="none-right"),
        pytest.param("/etc/path", "", "/etc/path", id="empty-right"),
        pytest.param("/etc/path", "child", "/etc/path/child", id="linux-path"),
        pytest.param(r"C:\user\documents", "child", r"C:\user\documents\child", id="windows-path"),
        pytest.param("/etc/path", "/child", "/etc/path/child", id="trim-right-fwd"),
        pytest.param(r"C:\root", r"\child", r"C:\root\child", id="trim-right-back"),
        pytest.param(r"C:\root\\", "child", r"C:\root\child", id="trim-left-back"),
        pytest.param("root", "sub/child", "root/sub/child", id="right-fwd-no-left-slash"),
        pytest.param("root", r"sub\child", r"root\sub\child", id="right-back-no-left-slash"),
    ],
)
def test_merge_path_elements(left: str | None, right: str, expected: str) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.mergePathElements(left, right)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    ("left", "segments", "expected"),
    [
        pytest.param(None, ("fruit", "apple"), "fruit/apple", id="no-base"),
        pytest.param("", ("fruit", "apple"), "fruit/apple", id="empty-base"),
        pytest.param("/etc", ("sub1", "sub2"), "/etc/sub1/sub2", id="linux-base"),
        pytest.param(r"C:\user", ("documents",), r"C:\user\documents", id="windows-base"),
        pytest.param(None, ("", None), "", id="all-empty"),
        pytest.param(
            r"https://s3.deltares.nl/dsc-testbench/references",
            ("win64", "\n      e02_dflowfm/f012_inout/c0325_alloutrealistic_f12_e02_3dom_classmap"),
            r"https://s3.deltares.nl/dsc-testbench/references/win64/e02_dflowfm/f012_inout/c0325_alloutrealistic_f12_e02_3dom_classmap",
            id="s3",
        ),
    ],
)
def test_merge_full_path(left: str | None, segments: tuple[str, ...], expected: str) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.mergeFullPath(left, *segments)

    # Assert
    assert result == expected


def test_find_all_sub_files_returns_relative_files(tmp_path: Path) -> None:
    # Arrange
    paths = Paths()
    root = tmp_path / "root"
    root.mkdir()
    (root / "b.txt").write_text("root")
    (root / "a").mkdir()
    (root / "a" / "file1.txt").write_text("nested")

    # Act
    result = paths.findAllSubFiles(str(root))

    # Assert
    assert sorted(result) == sorted(["b.txt", os.path.join("a", "file1.txt")])


def test_find_all_sub_folders_respects_exclude(tmp_path: Path) -> None:
    # Arrange
    paths = Paths()
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep").mkdir()
    (root / "skip").mkdir()
    (root / "skip" / "child").mkdir()

    # Act
    result = paths.findAllSubFolders(str(root), "skip")

    # Assert
    expected = {
        os.path.abspath(str(root)),
        os.path.abspath(str(root / "keep")),
    }
    assert set(result) == expected
