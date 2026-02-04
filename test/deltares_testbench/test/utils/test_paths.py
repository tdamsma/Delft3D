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
def test_split_network_path(path: Path, expected: tuple[str, str, str]) -> None:
    # Arrange
    paths = Paths()

    # Act
    server, folder, rest = paths.split_network_path(path)

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
def test_is_path(path: Path, expected: bool) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.is_path(path)

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
def test_is_absolute(path: Path, expected: bool) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.is_absolute(path)

    # Assert
    assert result is expected


def test_rebuild_to_local_path_normalizes_mixed_separators() -> None:
    # Arrange
    paths = Paths()
    mixed = Path("/a/b\\c/d")

    # Act
    result = paths.rebuild_to_local_path(mixed)

    # Assert
    assert result == os.path.join("/", "a", "b", "c", "d")


def test_rebuild_to_local_path_preserves_drive_letter() -> None:
    # Arrange
    paths = Paths()
    mixed = Path("C:/folder/sub")

    # Act
    result = paths.rebuild_to_local_path(mixed)

    # Assert
    assert result == os.path.join("C:\\", "folder", "sub")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        pytest.param(None, Path("fruit"), Path("fruit"), id="none-left"),
        pytest.param(Path(), Path("fruit"), Path("fruit"), id="empty-left"),
        pytest.param(Path("/etc/path"), None, Path("/etc/path"), id="none-right"),
        pytest.param(Path("/etc/path"), Path(), Path("/etc/path"), id="empty-right"),
        pytest.param(Path("/etc/path"), Path("child"), Path("/etc/path/child"), id="linux-path"),
        pytest.param(Path(r"C:\user\documents"), Path("child"), Path(r"C:\user\documents\child"), id="windows-path"),
        pytest.param(Path("/etc/path"), Path("/child"), Path("/etc/path/child"), id="trim-right-fwd"),
        pytest.param(Path(r"C:\root"), Path(r"\child"), Path(r"C:\root\child"), id="trim-right-back"),
        pytest.param(Path(r"C:\root\\"), Path("child"), Path(r"C:\root\child"), id="trim-left-back"),
        pytest.param(Path("root"), Path("sub/child"), Path("root/sub/child"), id="right-fwd-no-left-slash"),
        pytest.param(Path("root"), Path(r"sub\child"), Path(r"root\sub\child"), id="right-back-no-left-slash"),
    ],
)
def test_merge_path_elements(left: Path | None, right: Path | None, expected: Path) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.merge_path_elements(left, right)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    ("left", "segments", "expected"),
    [
        pytest.param(None, (Path("fruit"), Path("apple")), Path("fruit/apple"), id="no-base"),
        pytest.param(Path(), (Path("fruit"), Path("apple")), Path("fruit/apple"), id="empty-base"),
        pytest.param(Path("/etc"), (Path("sub1"), Path("sub2")), Path("/etc/sub1/sub2"), id="linux-base"),
        pytest.param(Path(r"C:\user"), (Path("documents"),), Path(r"C:\user\documents"), id="windows-base"),
        pytest.param(None, (Path(), None), Path(), id="all-empty"),
        pytest.param(
            r"https://s3.deltares.nl/dsc-testbench/references",
            ("win64", "\n      e02_dflowfm/f012_inout/c0325_alloutrealistic_f12_e02_3dom_classmap"),
            r"https://s3.deltares.nl/dsc-testbench/references/win64/e02_dflowfm/f012_inout/c0325_alloutrealistic_f12_e02_3dom_classmap",
            id="s3",
        ),
    ],
)
def test_merge_full_path(left: Path | None, segments: tuple[Path | None, ...], expected: Path) -> None:
    # Arrange
    paths = Paths()

    # Act
    result = paths.merge_full_path(left, *segments)

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
    result = paths.find_all_sub_files(root)

    # Assert
    assert sorted(result) == sorted([Path("b.txt"), Path("a") / "file1.txt"])


def test_find_all_sub_folders_respects_exclude(tmp_path: Path) -> None:
    # Arrange
    paths = Paths()
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep").mkdir()
    (root / "skip").mkdir()
    (root / "skip" / "child").mkdir()

    # Act
    result = paths.find_all_sub_folders(root, "skip")

    # Assert
    expected = {
        root.resolve(),
        (root / "keep").resolve(),
    }
    assert set(result) == expected
