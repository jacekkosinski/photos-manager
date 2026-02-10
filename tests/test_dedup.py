"""Tests for dedup module."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from photos_manager import dedup


@pytest.mark.unit
class TestScanDirectory:
    """Tests for scan_directory function."""

    def test_scan_single_file(self, tmp_path: Path) -> None:
        """Test scanning directory with single file."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        result = dedup.scan_directory(str(tmp_path))

        assert len(result) == 1
        assert result[0]["path"] == str(test_file.resolve())
        assert result[0]["size"] == 7
        assert result[0]["sha1"] is not None
        assert result[0]["md5"] is not None
        assert "date" in result[0]

    def test_scan_multiple_files(self, tmp_path: Path) -> None:
        """Test scanning directory with multiple files."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")

        result = dedup.scan_directory(str(tmp_path))

        assert len(result) == 2
        paths = {entry["path"] for entry in result}
        assert str((tmp_path / "file1.txt").resolve()) in paths
        assert str((tmp_path / "file2.txt").resolve()) in paths

    def test_scan_recursive(self, tmp_path: Path) -> None:
        """Test scanning directory recursively."""
        (tmp_path / "file1.txt").write_text("content1")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("content2")

        result = dedup.scan_directory(str(tmp_path))

        assert len(result) == 2
        paths = {entry["path"] for entry in result}
        assert str((tmp_path / "file1.txt").resolve()) in paths
        assert str((subdir / "file2.txt").resolve()) in paths

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning empty directory."""
        result = dedup.scan_directory(str(tmp_path))
        assert result == []

    def test_scan_nonexistent_directory(self) -> None:
        """Test scanning nonexistent directory raises SystemExit."""
        with pytest.raises(SystemExit, match="not found"):
            dedup.scan_directory("/nonexistent/dir")

    def test_scan_not_directory(self, tmp_path: Path) -> None:
        """Test scanning a file (not directory) raises SystemExit."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        with pytest.raises(SystemExit, match="Not a directory"):
            dedup.scan_directory(str(test_file))


@pytest.mark.unit
class TestBuildArchiveIndex:
    """Tests for build_archive_index function."""

    def test_build_index_basic(self) -> None:
        """Test building indexes from archive data."""
        archive_data = [
            {"path": "/file1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            {"path": "/file2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
        ]

        size_index, checksum_index = dedup.build_archive_index(archive_data)

        assert 100 in size_index
        assert 200 in size_index
        assert len(size_index[100]) == 1
        assert ("abc", "def") in checksum_index
        assert ("ghi", "jkl") in checksum_index

    def test_build_index_multiple_same_size(self) -> None:
        """Test building index with multiple files of same size."""
        archive_data = [
            {"path": "/file1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            {"path": "/file2.txt", "size": 100, "sha1": "ghi", "md5": "jkl"},
        ]

        size_index, _ = dedup.build_archive_index(archive_data)

        assert len(size_index[100]) == 2

    def test_build_index_empty(self) -> None:
        """Test building index from empty archive."""
        size_index, checksum_index = dedup.build_archive_index([])

        assert size_index == {}
        assert checksum_index == {}

    def test_build_index_missing_fields(self) -> None:
        """Test building index handles entries with missing fields."""
        archive_data = [
            {"path": "/file1.txt", "size": "not_int", "sha1": "abc", "md5": "def"},
            {"path": "/file2.txt", "size": 200},
        ]

        size_index, _ = dedup.build_archive_index(archive_data)

        # Only the valid entry (size=200) should be indexed; "not_int" entry is skipped
        assert len(size_index) == 1
        assert 200 in size_index


@pytest.mark.unit
class TestFindDuplicates:
    """Tests for find_duplicates function."""

    def test_find_exact_match(self) -> None:
        """Test finding exact duplicate."""
        scanned = [{"path": "/scan/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]
        archive_data = [{"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = dedup.build_archive_index(archive_data)
        duplicates, missing = dedup.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 1
        assert len(missing) == 0
        assert duplicates[0][0]["path"] == "/scan/file.txt"
        assert duplicates[0][1]["path"] == "/archive/file.txt"

    def test_find_missing(self) -> None:
        """Test finding missing file."""
        scanned = [{"path": "/scan/new.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]
        archive_data = [{"path": "/archive/old.txt", "size": 200, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = dedup.build_archive_index(archive_data)
        duplicates, missing = dedup.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 0
        assert len(missing) == 1
        assert missing[0]["path"] == "/scan/new.txt"

    def test_find_size_match_checksum_mismatch(self) -> None:
        """Test size matches but checksums don't."""
        scanned = [{"path": "/scan/file.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]
        archive_data = [{"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = dedup.build_archive_index(archive_data)
        duplicates, missing = dedup.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 0
        assert len(missing) == 1

    def test_find_empty_scanned(self) -> None:
        """Test with no scanned files."""
        archive_data = [{"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = dedup.build_archive_index(archive_data)
        duplicates, missing = dedup.find_duplicates([], size_index, checksum_index)

        assert len(duplicates) == 0
        assert len(missing) == 0

    def test_find_multiple_duplicates_and_missing(self) -> None:
        """Test finding mix of duplicates and missing files."""
        scanned = [
            {"path": "/scan/dup1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            {"path": "/scan/dup2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
            {"path": "/scan/miss1.txt", "size": 300, "sha1": "xyz", "md5": "uvw"},
        ]
        archive_data = [
            {"path": "/archive/dup1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            {"path": "/archive/dup2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
        ]

        size_index, checksum_index = dedup.build_archive_index(archive_data)
        duplicates, missing = dedup.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 2
        assert len(missing) == 1


@pytest.mark.unit
class TestCompareFilenames:
    """Tests for compare_filenames function."""

    def test_compare_identical_filenames(self) -> None:
        """Test comparing identical filenames."""
        is_same, warning = dedup.compare_filenames("/scan/file.txt", "/archive/file.txt")
        assert is_same is True
        assert warning is None

    def test_compare_different_filenames(self) -> None:
        """Test comparing different filenames."""
        is_same, warning = dedup.compare_filenames("/scan/file1.txt", "/archive/file2.txt")
        assert is_same is False
        assert warning is not None
        assert "file1.txt" in warning
        assert "file2.txt" in warning

    def test_compare_same_basename_different_paths(self) -> None:
        """Test comparing files with same basename but different paths."""
        is_same, warning = dedup.compare_filenames("/scan/dir1/file.txt", "/archive/dir2/file.txt")
        assert is_same is True
        assert warning is None


@pytest.mark.unit
class TestCompareTimestamps:
    """Tests for compare_timestamps function."""

    def test_compare_identical_timestamps(self) -> None:
        """Test comparing identical timestamps."""
        dt = datetime.now(UTC).isoformat()
        is_within, diff = dedup.compare_timestamps(dt, dt, 1)
        assert is_within is True
        assert diff is None

    def test_compare_within_tolerance(self) -> None:
        """Test comparing timestamps within tolerance."""
        dt1 = datetime.now(UTC)
        dt2 = dt1 + timedelta(seconds=0.5)
        is_within, diff = dedup.compare_timestamps(dt1.isoformat(), dt2.isoformat(), 1)
        assert is_within is True
        assert diff is None

    def test_compare_outside_tolerance(self) -> None:
        """Test comparing timestamps outside tolerance."""
        dt1 = datetime.now(UTC)
        dt2 = dt1 + timedelta(seconds=10)
        is_within, diff = dedup.compare_timestamps(dt1.isoformat(), dt2.isoformat(), 1)
        assert is_within is False
        assert diff is not None
        assert "10 seconds" in diff

    def test_compare_invalid_timestamps(self) -> None:
        """Test comparing invalid timestamps."""
        is_within, diff = dedup.compare_timestamps("invalid", "also_invalid", 1)
        assert is_within is False
        assert diff is not None
        assert "Could not parse" in diff


@pytest.mark.unit
class TestFormatSize:
    """Tests for format_size function."""

    def test_format_small_size(self) -> None:
        """Test formatting small size."""
        assert dedup.format_size(123) == "123"

    def test_format_large_size(self) -> None:
        """Test formatting large size with thousands separators."""
        assert dedup.format_size(1234567) == "1,234,567"

    def test_format_zero(self) -> None:
        """Test formatting zero."""
        assert dedup.format_size(0) == "0"


@pytest.mark.unit
class TestGroupFiles:
    """Tests for group_files_by_directory function."""

    def test_group_files_single_directory(self) -> None:
        """Test grouping files from single directory."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
            {"path": "/scan/dir1/file2.txt", "size": 200},
        ]

        groups = dedup.group_files_by_directory(files)

        assert len(groups) == 1
        assert "/scan/dir1" in groups
        assert len(groups["/scan/dir1"]) == 2

    def test_group_files_multiple_directories(self) -> None:
        """Test grouping files from multiple directories."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
            {"path": "/scan/dir2/file2.txt", "size": 200},
            {"path": "/scan/dir3/file3.txt", "size": 300},
        ]

        groups = dedup.group_files_by_directory(files)

        assert len(groups) == 3
        assert "/scan/dir1" in groups
        assert "/scan/dir2" in groups
        assert "/scan/dir3" in groups

    def test_group_files_empty(self) -> None:
        """Test grouping empty list of files."""
        groups = dedup.group_files_by_directory([])
        assert groups == {}

    def test_group_files_nested_paths(self) -> None:
        """Test grouping files from nested directory structures."""
        files = [
            {"path": "/scan/parent/child1/file1.txt", "size": 100},
            {"path": "/scan/parent/child2/file2.txt", "size": 200},
        ]

        groups = dedup.group_files_by_directory(files)

        assert len(groups) == 2
        assert "/scan/parent/child1" in groups
        assert "/scan/parent/child2" in groups


@pytest.mark.unit
class TestAssignDirectoryNumbers:
    """Tests for assign_directory_numbers function."""

    def test_assign_numbers_single(self) -> None:
        """Test assigning number to single directory."""
        file_groups = {"/scan/dir1": []}

        mapping = dedup.assign_directory_numbers(file_groups)

        assert mapping["/scan/dir1"] == "dir00001"

    def test_assign_numbers_multiple(self) -> None:
        """Test assigning numbers to multiple directories."""
        file_groups = {
            "/scan/dir1": [],
            "/scan/dir2": [],
            "/scan/dir3": [],
        }

        mapping = dedup.assign_directory_numbers(file_groups)

        assert len(mapping) == 3
        # Should be sorted alphabetically
        assert mapping["/scan/dir1"] == "dir00001"
        assert mapping["/scan/dir2"] == "dir00002"
        assert mapping["/scan/dir3"] == "dir00003"

    def test_assign_numbers_sorted(self) -> None:
        """Test directories are sorted alphabetically before numbering."""
        file_groups = {
            "/scan/zebra": [],
            "/scan/alpha": [],
            "/scan/beta": [],
        }

        mapping = dedup.assign_directory_numbers(file_groups)

        assert mapping["/scan/alpha"] == "dir00001"
        assert mapping["/scan/beta"] == "dir00002"
        assert mapping["/scan/zebra"] == "dir00003"

    def test_assign_numbers_custom_start(self) -> None:
        """Test starting from custom number."""
        file_groups = {
            "/scan/dir1": [],
            "/scan/dir2": [],
        }

        mapping = dedup.assign_directory_numbers(file_groups, start=10)

        assert mapping["/scan/dir1"] == "dir00010"
        assert mapping["/scan/dir2"] == "dir00011"


@pytest.mark.unit
class TestGenerateCommands:
    """Tests for command generation functions."""

    def test_generate_move_commands(self, tmp_path: Path) -> None:
        """Test generating mv -iv commands."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
            {"path": "/scan/dir1/file2.txt", "size": 200},
        ]
        target_dir = str(tmp_path / "target")
        dir_mapping = {"/scan/dir1": "dir00001"}

        commands = dedup.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

        assert len(commands) == 3  # 1 mkdir + 2 mv
        assert commands[0].startswith("mkdir -p")
        assert "dir00001" in commands[0]
        assert commands[1].startswith("mv -iv")
        assert "file1.txt" in commands[1]
        assert commands[2].startswith("mv -iv")
        assert "file2.txt" in commands[2]

    def test_generate_file_operation_commands(self, tmp_path: Path) -> None:
        """Test generating cp -pv commands."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
        ]
        target_dir = str(tmp_path / "target")
        dir_mapping = {"/scan/dir1": "dir00001"}

        commands = dedup.generate_file_operation_commands(files, target_dir, dir_mapping, "cp")

        assert len(commands) == 2  # 1 mkdir + 1 cp
        assert commands[0].startswith("mkdir -p")
        assert commands[1].startswith("cp -pv")
        assert "file1.txt" in commands[1]

    def test_generate_commands_with_spaces(self, tmp_path: Path) -> None:
        """Test path quoting works with spaces."""
        files = [
            {"path": "/scan/my photos/photo 1.jpg", "size": 100},
        ]
        target_dir = str(tmp_path / "my target")
        dir_mapping = {"/scan/my photos": "dir00001"}

        commands = dedup.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

        # Verify paths are quoted
        assert "'" in commands[0] or '"' in commands[0]
        assert "'" in commands[1] or '"' in commands[1]
        assert "photo 1.jpg" in commands[1]

    def test_generate_commands_mkdir(self, tmp_path: Path) -> None:
        """Test mkdir -p commands included for each directory."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
            {"path": "/scan/dir2/file2.txt", "size": 200},
        ]
        target_dir = str(tmp_path / "target")
        dir_mapping = {"/scan/dir1": "dir00001", "/scan/dir2": "dir00002"}

        commands = dedup.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

        mkdir_commands = [cmd for cmd in commands if cmd.startswith("mkdir")]
        assert len(mkdir_commands) == 2
        assert "dir00001" in mkdir_commands[0]
        assert "dir00002" in mkdir_commands[1]

    def test_generate_commands_special_chars(self, tmp_path: Path) -> None:
        """Test special characters are properly escaped."""
        files = [
            {"path": "/scan/dir$/file'1.txt", "size": 100},
        ]
        target_dir = str(tmp_path / "target")
        dir_mapping = {"/scan/dir$": "dir00001"}

        commands = dedup.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

        # Should have proper quoting
        assert len(commands) == 2
        # Commands should be safe to execute (quotes handled)
        assert "mv -iv" in commands[1]


@pytest.mark.unit
class TestDisplayCommands:
    """Tests for display_commands function."""

    def test_display_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying commands."""
        commands = [
            "mkdir -p /target/dir00001",
            "mv -iv /scan/file.txt /target/dir00001/file.txt",
        ]

        dedup.display_commands(commands)

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "mkdir -p /target/dir00001"
        assert lines[1] == "mv -iv /scan/file.txt /target/dir00001/file.txt"

    def test_display_commands_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty command list."""
        dedup.display_commands([])
        captured = capsys.readouterr()
        assert captured.out == ""


@pytest.mark.unit
class TestListDisplay:
    """Tests for list display functions."""

    def test_display_list_duplicates(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying duplicates in list format."""
        duplicates = [
            (
                {"path": "/scan/file1.txt", "size": 100, "sha1": "abc", "md5": "def"},
                {"path": "/archive/file1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            ),
            (
                {"path": "/scan/file2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
                {"path": "/archive/file2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
            ),
        ]

        dedup.display_file_paths(duplicates, extract_path=lambda item: item[0]["path"])

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "/scan/file1.txt"
        assert lines[1] == "/scan/file2.txt"

    def test_display_list_duplicates_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty duplicates list in list format."""
        dedup.display_file_paths([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_display_list_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying missing files in list format."""
        missing = [
            {"path": "/scan/new1.txt", "size": 100, "sha1": "xyz", "md5": "uvw"},
            {"path": "/scan/new2.txt", "size": 200, "sha1": "mno", "md5": "pqr"},
        ]

        dedup.display_file_paths(missing)

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "/scan/new1.txt"
        assert lines[1] == "/scan/new2.txt"

    def test_display_list_missing_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty missing list in list format."""
        dedup.display_file_paths([])
        captured = capsys.readouterr()
        assert captured.out == ""


@pytest.mark.unit
class TestDisplayFunctions:
    """Tests for display functions."""

    def test_display_duplicates_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying duplicates without warnings."""
        duplicates = [
            (
                {
                    "path": "/scan/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00",
                },
                {
                    "path": "/archive/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00",
                },
            )
        ]

        fw, tw = dedup.display_duplicates(duplicates, False, False, 1)

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out
        assert "/scan/file.txt" in captured.out
        assert "/archive/file.txt" in captured.out
        assert fw == 0
        assert tw == 0

    def test_display_duplicates_with_filename_warnings(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test displaying duplicates with filename warnings."""
        duplicates = [
            (
                {
                    "path": "/scan/file1.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00",
                },
                {
                    "path": "/archive/file2.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00",
                },
            )
        ]

        fw, tw = dedup.display_duplicates(duplicates, True, False, 1)

        captured = capsys.readouterr()
        assert "Filename differs" in captured.out
        assert fw == 1
        assert tw == 0

    def test_display_duplicates_with_timestamp_warnings(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test displaying duplicates with timestamp warnings."""
        dt1 = datetime.now(UTC)
        dt2 = dt1 + timedelta(seconds=100)
        duplicates = [
            (
                {
                    "path": "/scan/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": dt1.isoformat(),
                },
                {
                    "path": "/archive/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": dt2.isoformat(),
                },
            )
        ]

        fw, tw = dedup.display_duplicates(duplicates, False, True, 1)

        captured = capsys.readouterr()
        assert "Timestamp differs" in captured.out
        assert fw == 0
        assert tw == 1

    def test_display_duplicates_empty(self) -> None:
        """Test displaying empty duplicates list."""
        fw, tw = dedup.display_duplicates([], False, False, 1)
        assert fw == 0
        assert tw == 0

    def test_display_missing_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying missing files."""
        missing = [{"path": "/scan/new.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]

        dedup.display_missing(missing)

        captured = capsys.readouterr()
        assert "Missing from archive" in captured.out
        assert "/scan/new.txt" in captured.out

    def test_display_missing_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty missing list."""
        dedup.display_missing([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_display_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying summary."""
        duplicates = [
            (
                {"path": "/scan/file.txt", "size": 100, "sha1": "abc", "md5": "def"},
                {"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"},
            )
        ]
        missing = [{"path": "/scan/new.txt", "size": 200, "sha1": "xyz", "md5": "uvw"}]

        dedup.display_summary(10, duplicates, missing, 1, 2)

        captured = capsys.readouterr()
        assert "Summary:" in captured.out
        assert "Files scanned: 10" in captured.out
        assert "Duplicates found: 1" in captured.out
        assert "100 bytes" in captured.out
        assert "Missing from archive: 1" in captured.out
        assert "200 bytes" in captured.out
        assert "Filename warnings: 1" in captured.out
        assert "Timestamp warnings: 2" in captured.out


@pytest.mark.unit
class TestSetupParser:
    """Tests for setup_parser function."""

    def test_setup_parser(self) -> None:
        """Test parser setup."""
        parser = argparse.ArgumentParser()
        dedup.setup_parser(parser)

        # Test that parser accepts expected arguments
        args = parser.parse_args(
            ["archive.json", "/scan/dir", "-d", "-m", "-f", "-t", "--tolerance", "5"]
        )

        assert args.json_file == "archive.json"
        assert args.directory == "/scan/dir"
        assert args.show_duplicates is True
        assert args.show_missing is True
        assert args.check_filenames is True
        assert args.check_timestamps is True
        assert args.tolerance == 5


@pytest.mark.integration
class TestMain:
    """Integration tests for main/run functions."""

    def test_run_no_flags(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run without -d or -m flags shows error."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=False,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "At least one of" in captured.err

    def test_run_show_duplicates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with -d flag showing duplicates."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file.txt"
        archive_file.write_text("content")

        # Generate archive JSON
        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory with duplicate
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        scan_file = scan_dir / "file.txt"
        scan_file.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out
        assert "Summary:" in captured.out

    def test_run_show_missing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with -m flag showing missing files."""
        # Create empty archive
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        # Create scan directory with file
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "new.txt").write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=False,
            show_missing=True,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Missing from archive" in captured.out

    def test_run_with_filename_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run with -f flag checking filenames."""
        # Create archive with different filename
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "original.txt"
        archive_file.write_text("content")

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory with different filename but same content
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        scan_file = scan_dir / "renamed.txt"
        scan_file.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=True,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Filename differs" in captured.out
        assert "Filename warnings: 1" in captured.out

    def test_run_with_timestamp_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run with -t flag checking timestamps."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file.txt"
        archive_file.write_text("content")

        # Use old timestamp in JSON
        old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": old_date,
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory with same content but current timestamp
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        scan_file = scan_dir / "file.txt"
        scan_file.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=True,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Timestamp differs" in captured.out

    def test_run_nonexistent_json(self, tmp_path: Path) -> None:
        """Test run with nonexistent JSON file."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file="/nonexistent.json",
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="not found"):
            dedup.run(args)

    def test_run_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test run with nonexistent directory."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory="/nonexistent/dir",
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="not found"):
            dedup.run(args)

    def test_run_not_directory(self, tmp_path: Path) -> None:
        """Test run with file instead of directory."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        not_dir = tmp_path / "file.txt"
        not_dir.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(not_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="Not a directory"):
            dedup.run(args)

    def test_run_all_flags(self, tmp_path: Path) -> None:
        """Test run with all flags enabled."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file.txt"
        archive_file.write_text("content")

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "file.txt").write_text("content")
        (scan_dir / "new.txt").write_text("new content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=True,
            check_filenames=True,
            check_timestamps=True,
            tolerance=5,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

    def test_run_list_mode_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run with --list flag showing duplicates."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file.txt"
        archive_file.write_text("content")

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        scan_file = scan_dir / "file.txt"
        scan_file.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # Should only have one line with the file path
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert str(scan_file.resolve()) in lines[0]
        # Should not have progress messages or summary
        assert "Loading" not in captured.out
        assert "Summary" not in captured.out

    def test_run_list_mode_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test run with --list flag showing missing files."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        scan_file = scan_dir / "new.txt"
        scan_file.write_text("content")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=False,
            show_missing=True,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert str(scan_file.resolve()) in lines[0]
        assert "Loading" not in captured.out
        assert "Summary" not in captured.out

    def test_run_list_mode_both(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with --list flag showing both duplicates and missing."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file1.txt"
        archive_file.write_text("content1")

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 8,
                "sha1": "105e7a844ac896f68e6f7dc0a9389d3e9be95abc",
                "md5": "7e55db001d319a94b0b713529a756623",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory with duplicate and new file
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        dup_file = scan_dir / "file1.txt"
        dup_file.write_text("content1")
        new_file = scan_dir / "file2.txt"
        new_file.write_text("content2")

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=True,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        # Both files should be in output
        output = captured.out
        assert str(dup_file.resolve()) in output
        assert str(new_file.resolve()) in output

    def test_main_entry_point(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test main() entry point."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        monkeypatch.setattr("sys.argv", ["dedup", str(json_file), str(scan_dir), "-d"])

        result = dedup.main()
        assert result == os.EX_OK

    def test_run_move_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with --move flag."""
        # Create empty archive
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        # Create scan directory with files
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        subdir = scan_dir / "photos2023"
        subdir.mkdir()
        (subdir / "file1.txt").write_text("content1")
        (subdir / "file2.txt").write_text("content2")

        # Create target directory
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=False,
            show_missing=True,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "umask 022" in captured.out
        assert "mkdir -p" in captured.out
        assert "mv -iv" in captured.out
        assert "dir00001" in captured.out

    def test_run_copy_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with --copy flag."""
        # Create archive
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "file.txt"
        archive_file.write_text("content")

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_file.resolve()),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            }
        ]
        json_file.write_text(json.dumps(json_data))

        # Create scan directory with duplicate
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "file.txt").write_text("content")

        # Create target directory
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=None,
            copy=str(target_dir),
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "umask 022" in captured.out
        assert "mkdir -p" in captured.out
        assert "cp -pv" in captured.out
        assert "dir00001" in captured.out

    def test_run_move_copy_exclusive(self, tmp_path: Path) -> None:
        """Test error when both --move and --copy specified."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=str(target_dir),
            start=1,
        )

        with pytest.raises(SystemExit, match="mutually exclusive"):
            dedup.run(args)

    def test_run_move_list_exclusive(self, tmp_path: Path) -> None:
        """Test error when --move and --list specified."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=True,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="cannot be used with --list"):
            dedup.run(args)

    def test_run_move_no_files(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test no output when no files match."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # No files to process, so no output
        assert captured.out == ""

    def test_run_move_target_not_exists(self, tmp_path: Path) -> None:
        """Test error when target directory doesn't exist."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=True,
            show_missing=False,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move="/nonexistent/target",
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="does not exist"):
            dedup.run(args)

    def test_run_move_custom_start(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --start option with custom number."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "file.txt").write_text("content")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            directory=str(scan_dir),
            show_duplicates=False,
            show_missing=True,
            check_filenames=False,
            check_timestamps=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=100,
        )

        result = dedup.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "dir00100" in captured.out
        assert "dir00001" not in captured.out
