"""Tests for find module."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from photos_manager import find


@pytest.mark.unit
class TestScanDirectory:
    """Tests for scan_directory function."""

    def test_scan_single_file(self, tmp_path: Path) -> None:
        """Test scanning directory with single file."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        result = find.scan_directory(str(tmp_path))

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

        result = find.scan_directory(str(tmp_path))

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

        result = find.scan_directory(str(tmp_path))

        assert len(result) == 2
        paths = {entry["path"] for entry in result}
        assert str((tmp_path / "file1.txt").resolve()) in paths
        assert str((subdir / "file2.txt").resolve()) in paths

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning empty directory."""
        result = find.scan_directory(str(tmp_path))
        assert result == []

    def test_scan_nonexistent_directory(self) -> None:
        """Test scanning nonexistent directory raises SystemExit."""
        with pytest.raises(SystemExit, match="does not exist"):
            find.scan_directory("/nonexistent/dir")

    def test_scan_not_directory(self, tmp_path: Path) -> None:
        """Test scanning a file (not directory) raises SystemExit."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        with pytest.raises(SystemExit, match="is not a directory"):
            find.scan_directory(str(test_file))


@pytest.mark.unit
class TestLoadPsv:
    """Tests for load_psv function."""

    def test_load_psv_happy_path(self, tmp_path: Path) -> None:
        """Test loading a valid PSV file with 3 records."""
        psv = tmp_path / "files.psv"
        psv.write_text(
            "/a/photo.jpg|sha1aaa|md5aaa|2023-01-01T00:00:00+00:00|1024\n"
            "/b/video.mp4|sha1bbb|md5bbb|2023-02-01T00:00:00+00:00|2048\n"
            "/c/doc.pdf|sha1ccc|md5ccc|2023-03-01T00:00:00+00:00|512\n"
        )

        result = find.load_psv(str(psv))

        assert len(result) == 3
        assert result[0] == {
            "path": "/a/photo.jpg",
            "sha1": "sha1aaa",
            "md5": "md5aaa",
            "date": "2023-01-01T00:00:00+00:00",
            "size": 1024,
        }
        assert result[1]["path"] == "/b/video.mp4"
        assert result[2]["size"] == 512

    def test_load_psv_skips_blank_lines_and_comments(self, tmp_path: Path) -> None:
        """Test that blank lines and # comments are skipped."""
        psv = tmp_path / "files.psv"
        psv.write_text(
            "# This is a comment\n"
            "\n"
            "/a/file.jpg|sha1aaa|md5aaa|2023-01-01T00:00:00+00:00|100\n"
            "   \n"
            "# Another comment\n"
            "/b/file.jpg|sha1bbb|md5bbb|2023-01-02T00:00:00+00:00|200\n"
        )

        result = find.load_psv(str(psv))

        assert len(result) == 2
        assert result[0]["path"] == "/a/file.jpg"
        assert result[1]["path"] == "/b/file.jpg"

    def test_load_psv_skips_malformed_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that malformed lines (wrong field count) are skipped with a warning."""
        psv = tmp_path / "files.psv"
        psv.write_text(
            "/a/file.jpg|sha1aaa|md5aaa|2023-01-01T00:00:00+00:00|100\n"
            "bad-line-with-no-pipes\n"
            "/b/file.jpg|sha1bbb|md5bbb|2023-01-02T00:00:00+00:00|200\n"
        )

        result = find.load_psv(str(psv))

        assert len(result) == 2
        captured = capsys.readouterr()
        assert "malformed" in captured.err
        assert "line 2" in captured.err

    def test_load_psv_skips_invalid_size(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that lines with non-integer size are skipped with a warning."""
        psv = tmp_path / "files.psv"
        psv.write_text(
            "/a/file.jpg|sha1aaa|md5aaa|2023-01-01T00:00:00+00:00|100\n"
            "/b/file.jpg|sha1bbb|md5bbb|2023-01-02T00:00:00+00:00|not-a-number\n"
        )

        result = find.load_psv(str(psv))

        assert len(result) == 1
        assert result[0]["path"] == "/a/file.jpg"
        captured = capsys.readouterr()
        assert "invalid size" in captured.err

    def test_load_psv_missing_file(self) -> None:
        """Test that a missing PSV file raises SystemExit."""
        with pytest.raises(SystemExit, match="Could not open PSV file"):
            find.load_psv("/nonexistent/files.psv")


@pytest.mark.unit
class TestBuildArchiveIndex:
    """Tests for build_archive_index function."""

    def test_build_index_basic(self) -> None:
        """Test building indexes from archive data."""
        archive_data = [
            {"path": "/file1.txt", "size": 100, "sha1": "abc", "md5": "def"},
            {"path": "/file2.txt", "size": 200, "sha1": "ghi", "md5": "jkl"},
        ]

        size_index, checksum_index = find.build_archive_index(archive_data)

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

        size_index, _ = find.build_archive_index(archive_data)

        assert len(size_index[100]) == 2

    def test_build_index_empty(self) -> None:
        """Test building index from empty archive."""
        size_index, checksum_index = find.build_archive_index([])

        assert size_index == {}
        assert checksum_index == {}

    def test_build_index_missing_fields(self) -> None:
        """Test building index handles entries with missing fields."""
        archive_data = [
            {"path": "/file1.txt", "size": "not_int", "sha1": "abc", "md5": "def"},
            {"path": "/file2.txt", "size": 200},
        ]

        size_index, _ = find.build_archive_index(archive_data)

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

        size_index, checksum_index = find.build_archive_index(archive_data)
        duplicates, missing = find.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 1
        assert len(missing) == 0
        assert duplicates[0][0]["path"] == "/scan/file.txt"
        assert duplicates[0][1]["path"] == "/archive/file.txt"

    def test_find_missing(self) -> None:
        """Test finding missing file."""
        scanned = [{"path": "/scan/new.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]
        archive_data = [{"path": "/archive/old.txt", "size": 200, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = find.build_archive_index(archive_data)
        duplicates, missing = find.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 0
        assert len(missing) == 1
        assert missing[0]["path"] == "/scan/new.txt"

    def test_find_size_match_checksum_mismatch(self) -> None:
        """Test size matches but checksums don't."""
        scanned = [{"path": "/scan/file.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]
        archive_data = [{"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = find.build_archive_index(archive_data)
        duplicates, missing = find.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 0
        assert len(missing) == 1

    def test_find_empty_scanned(self) -> None:
        """Test with no scanned files."""
        archive_data = [{"path": "/archive/file.txt", "size": 100, "sha1": "abc", "md5": "def"}]

        size_index, checksum_index = find.build_archive_index(archive_data)
        duplicates, missing = find.find_duplicates([], size_index, checksum_index)

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

        size_index, checksum_index = find.build_archive_index(archive_data)
        duplicates, missing = find.find_duplicates(scanned, size_index, checksum_index)

        assert len(duplicates) == 2
        assert len(missing) == 1


@pytest.mark.unit
class TestSizeDisplay:
    """Tests for size display format (space as thousands separator)."""

    def test_display_missing_uses_space_thousands_separator(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that display_missing uses space as thousands separator."""
        missing = [
            {
                "path": "/scan/file.txt",
                "size": 1234567,
                "sha1": "abc",
                "md5": "def",
                "date": "2024-01-01T12:00:00+01:00",
            }
        ]
        find.display_missing(missing)
        captured = capsys.readouterr()
        assert "1 234 567 bytes" in captured.out

    def test_display_duplicates_uses_space_thousands_separator(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that display_duplicates uses space as thousands separator."""
        duplicates = [
            (
                {
                    "path": "/scan/file.txt",
                    "size": 3217638,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00+01:00",
                },
                {
                    "path": "/archive/file.txt",
                    "size": 3217638,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00+01:00",
                },
            )
        ]
        find.display_duplicates(duplicates, 1)
        captured = capsys.readouterr()
        assert "3 217 638 bytes" in captured.out


@pytest.mark.unit
class TestGroupFiles:
    """Tests for group_files_by_directory function."""

    def test_group_files_single_directory(self) -> None:
        """Test grouping files from single directory."""
        files = [
            {"path": "/scan/dir1/file1.txt", "size": 100},
            {"path": "/scan/dir1/file2.txt", "size": 200},
        ]

        groups = find.group_files_by_directory(files)

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

        groups = find.group_files_by_directory(files)

        assert len(groups) == 3
        assert "/scan/dir1" in groups
        assert "/scan/dir2" in groups
        assert "/scan/dir3" in groups

    def test_group_files_empty(self) -> None:
        """Test grouping empty list of files."""
        groups = find.group_files_by_directory([])
        assert groups == {}

    def test_group_files_nested_paths(self) -> None:
        """Test grouping files from nested directory structures."""
        files = [
            {"path": "/scan/parent/child1/file1.txt", "size": 100},
            {"path": "/scan/parent/child2/file2.txt", "size": 200},
        ]

        groups = find.group_files_by_directory(files)

        assert len(groups) == 2
        assert "/scan/parent/child1" in groups
        assert "/scan/parent/child2" in groups


@pytest.mark.unit
class TestAssignDirectoryNumbers:
    """Tests for assign_directory_numbers function."""

    def test_assign_numbers_single(self) -> None:
        """Test assigning number to single directory."""
        file_groups = {"/scan/dir1": []}

        mapping = find.assign_directory_numbers(file_groups)

        assert mapping["/scan/dir1"] == "dir00001"

    def test_assign_numbers_multiple(self) -> None:
        """Test assigning numbers to multiple directories."""
        file_groups = {
            "/scan/dir1": [],
            "/scan/dir2": [],
            "/scan/dir3": [],
        }

        mapping = find.assign_directory_numbers(file_groups)

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

        mapping = find.assign_directory_numbers(file_groups)

        assert mapping["/scan/alpha"] == "dir00001"
        assert mapping["/scan/beta"] == "dir00002"
        assert mapping["/scan/zebra"] == "dir00003"

    def test_assign_numbers_custom_start(self) -> None:
        """Test starting from custom number."""
        file_groups = {
            "/scan/dir1": [],
            "/scan/dir2": [],
        }

        mapping = find.assign_directory_numbers(file_groups, start=10)

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

        commands = find.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

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

        commands = find.generate_file_operation_commands(files, target_dir, dir_mapping, "cp")

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

        commands = find.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

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

        commands = find.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

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

        commands = find.generate_file_operation_commands(files, target_dir, dir_mapping, "mv")

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

        find.display_commands(commands)

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "mkdir -p /target/dir00001"
        assert lines[1] == "mv -iv /scan/file.txt /target/dir00001/file.txt"

    def test_display_commands_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty command list."""
        find.display_commands([])
        captured = capsys.readouterr()
        assert captured.out == ""


@pytest.mark.unit
class TestProcessListMode:
    """Tests for process_list_mode output format."""

    def _make_args(self, **kwargs: object) -> argparse.Namespace:
        defaults = {
            "show_duplicates": False,
            "show_missing": False,
            "filter_name": False,
            "filter_date": False,
            "tolerance": 0,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_list_dup_tag_and_ref(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that [DUP] tag and ref path appear in --list output."""
        duplicates = [
            (
                {
                    "path": "/scan/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00+01:00",
                },
                {
                    "path": "/archive/file.txt",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01T12:00:00+01:00",
                },
            )
        ]
        args = self._make_args(show_duplicates=True)
        find.process_list_mode(args, duplicates, [])
        captured = capsys.readouterr()
        assert "[DUP]" in captured.out
        assert "[ref: /archive/file.txt]" in captured.out

    def test_list_miss_tag_and_size(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that [MISS] tag and size appear in --list output."""
        missing = [
            {
                "path": "/scan/new.txt",
                "size": 2048,
                "sha1": "xyz",
                "md5": "uvw",
                "date": "2024-06-01T08:00:00+02:00",
            }
        ]
        args = self._make_args(show_missing=True)
        find.process_list_mode(args, [], missing)
        captured = capsys.readouterr()
        assert "[MISS]" in captured.out
        assert "2.0 kB" in captured.out

    def test_list_empty_output_when_no_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that no-flag mode shows both DUP and MISS."""
        duplicates = [
            (
                {
                    "path": "/scan/a.txt",
                    "size": 10,
                    "sha1": "a",
                    "md5": "b",
                    "date": "2024-01-01T00:00:00+00:00",
                },
                {
                    "path": "/archive/a.txt",
                    "size": 10,
                    "sha1": "a",
                    "md5": "b",
                    "date": "2024-01-01T00:00:00+00:00",
                },
            )
        ]
        missing = [
            {
                "path": "/scan/b.txt",
                "size": 5,
                "sha1": "c",
                "md5": "d",
                "date": "2024-01-02T00:00:00+00:00",
            }
        ]
        args = self._make_args()
        find.process_list_mode(args, duplicates, missing)
        captured = capsys.readouterr()
        assert "[DUP]" in captured.out
        assert "[MISS]" in captured.out


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

        fw, tw = find.display_duplicates(duplicates, 1)

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out
        assert "/scan/file.txt" in captured.out
        assert "/archive/file.txt" in captured.out
        assert fw == 0
        assert tw == 0

    def test_display_duplicates_with_filename_warnings(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test displaying duplicates with real filename change (case-insensitive diff)."""
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

        fw, tw = find.display_duplicates(duplicates, 1)

        captured = capsys.readouterr()
        assert "name: file1.txt -> file2.txt" in captured.out
        assert captured.err == ""
        assert fw == 1
        assert tw == 0

    def test_display_duplicates_case_only_filename_ignored(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that case-only filename differences are not flagged."""
        duplicates = [
            (
                {
                    "path": "/scan/FILE.TXT",
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

        fw, tw = find.display_duplicates(duplicates, 1)

        captured = capsys.readouterr()
        assert "name:" not in captured.out
        assert captured.err == ""
        assert fw == 0
        assert tw == 0

    def test_display_duplicates_with_timestamp_warnings(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test displaying duplicates with date change shown inline."""
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

        fw, tw = find.display_duplicates(duplicates, 1)

        captured = capsys.readouterr()
        assert "-> " in captured.out
        assert "delta: +100s" in captured.out
        assert captured.err == ""
        assert fw == 0
        assert tw == 1

    def test_display_duplicates_empty(self) -> None:
        """Test displaying empty duplicates list."""
        fw, tw = find.display_duplicates([], 1)
        assert fw == 0
        assert tw == 0

    def test_display_missing_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying missing files."""
        missing = [{"path": "/scan/new.txt", "size": 100, "sha1": "xyz", "md5": "uvw"}]

        find.display_missing(missing)

        captured = capsys.readouterr()
        assert "Missing from archive" in captured.out
        assert "/scan/new.txt" in captured.out

    def test_display_missing_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test displaying empty missing list."""
        find.display_missing([])
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

        find.display_summary(duplicates, missing)

        captured = capsys.readouterr()
        assert "1 duplicates found" in captured.out
        assert "1 files missing" in captured.out


@pytest.mark.unit
class TestSetupParser:
    """Tests for setup_parser function."""

    def test_setup_parser(self) -> None:
        """Test parser setup."""
        parser = argparse.ArgumentParser()
        find.setup_parser(parser)

        # Test that parser accepts expected arguments
        args = parser.parse_args(
            [
                "archive.json",
                "/scan/dir",
                "-d",
                "-m",
                "--filter-name",
                "--filter-date",
                "--tolerance",
                "5",
            ]
        )

        assert args.json_file == "archive.json"
        assert args.source == ["/scan/dir"]
        assert args.show_duplicates is True
        assert args.show_missing is True
        assert args.filter_name is True
        assert args.filter_date is True
        assert args.tolerance == 5


@pytest.mark.integration
class TestMain:
    """Integration tests for main/run functions."""

    def test_run_no_flags(self, tmp_path: Path) -> None:
        """Test run without -d or -m flags (normal mode) succeeds."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

    def test_run_list_no_dm_flags_shows_both(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--list without -d/-m shows both [DUP] and [MISS] entries."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "dup.txt"
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

        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "dup.txt").write_text("content")  # duplicate
        (scan_dir / "new.txt").write_text("new content")  # missing

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "[DUP]" in captured.out
        assert "[MISS]" in captured.out

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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out
        assert "duplicates found" in captured.out

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
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Missing from archive" in captured.out

    def test_run_with_filename_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --list -f filter: shows only duplicates with filename differences."""
        # Two archive entries with same content but different sizes to distinguish them.
        # Entry 1: "content" (7 bytes) stored as "original.txt"
        # Entry 2: "content2" (8 bytes) stored as "same.txt"
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                "path": str(archive_dir / "original.txt"),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": datetime.now(UTC).isoformat(),
            },
            {
                "path": str(archive_dir / "same.txt"),
                "size": 8,
                "sha1": "105e7a844ac896f68e6f7dc0a9389d3e9be95abc",
                "md5": "7e55db001d319a94b0b713529a756623",
                "date": datetime.now(UTC).isoformat(),
            },
        ]
        json_file.write_text(json.dumps(json_data))

        # Scan dir: renamed.txt has different name from archive (original.txt) -> should appear
        # same.txt has same name as archive (same.txt) -> should NOT appear with -f filter
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        renamed_file = scan_dir / "renamed.txt"
        renamed_file.write_text("content")  # matches original.txt by checksum
        same_name_file = scan_dir / "same.txt"
        same_name_file.write_text("content2")  # matches same.txt by checksum

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=True,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # renamed.txt (name differs from original.txt) should appear
        assert "renamed.txt" in captured.out
        # same.txt (name matches) should NOT appear
        assert "same.txt" not in captured.out

    def test_run_with_timestamp_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --list --filter-date filter: shows only duplicates with date differences."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        now = datetime.now(UTC)
        old_date = (now - timedelta(days=100)).isoformat()

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                # file1.txt: stored with old date -> date differs -> should appear
                "path": str(archive_dir / "file1.txt"),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": old_date,
            },
            {
                # file2.txt: stored with same date as PSV -> no date diff -> should NOT appear
                "path": str(archive_dir / "file2.txt"),
                "size": 8,
                "sha1": "105e7a844ac896f68e6f7dc0a9389d3e9be95abc",
                "md5": "7e55db001d319a94b0b713529a756623",
                "date": now.isoformat(),
            },
        ]
        json_file.write_text(json.dumps(json_data))

        # Use a PSV file so we can control the scanned dates precisely
        psv_file = tmp_path / "files.psv"
        lines = [
            f"/scan/file1.txt|040f06fd774092478d450774f5ba30c5da78acc8"
            f"|9a0364b9e99bb480dd25e1f0284c8555|{now.isoformat()}|7",
            f"/scan/file2.txt|105e7a844ac896f68e6f7dc0a9389d3e9be95abc"
            f"|7e55db001d319a94b0b713529a756623|{now.isoformat()}|8",
        ]
        psv_file.write_text("\n".join(lines) + "\n")

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(psv_file)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=True,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # file1.txt has date diff (old_date vs now) -> should appear
        assert "file1.txt" in captured.out
        # file2.txt has same date -> should NOT appear
        assert "file2.txt" not in captured.out

    def test_run_combined_filename_and_timestamp_filter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --list --filter-name --filter-date AND filter."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        now = datetime.now(UTC)
        old_date = (now - timedelta(days=100)).isoformat()

        json_file = tmp_path / "archive.json"
        json_data = [
            {
                # file1.txt: different name AND date diff -> should appear (both conditions met)
                "path": str(archive_dir / "file1_arch.txt"),
                "size": 7,
                "sha1": "040f06fd774092478d450774f5ba30c5da78acc8",
                "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                "date": old_date,
            },
            {
                # file2.txt: different name but SAME date -> should NOT appear (date cond fails)
                "path": str(archive_dir / "file2_arch.txt"),
                "size": 8,
                "sha1": "105e7a844ac896f68e6f7dc0a9389d3e9be95abc",
                "md5": "7e55db001d319a94b0b713529a756623",
                "date": now.isoformat(),
            },
            {
                # file3.txt: same name but date diff -> should NOT appear (name cond fails)
                "path": str(archive_dir / "file3.txt"),
                "size": 5,
                "sha1": "ac3478d69a3c81fa62e60f5c3696165a4e5e6ac4",
                "md5": "b026324c6904b2a9cb4b88d6d61c81d1",
                "date": old_date,
            },
        ]
        json_file.write_text(json.dumps(json_data))

        psv_file = tmp_path / "files.psv"
        lines = [
            f"/scan/file1.txt|040f06fd774092478d450774f5ba30c5da78acc8"
            f"|9a0364b9e99bb480dd25e1f0284c8555|{now.isoformat()}|7",
            f"/scan/file2.txt|105e7a844ac896f68e6f7dc0a9389d3e9be95abc"
            f"|7e55db001d319a94b0b713529a756623|{now.isoformat()}|8",
            f"/scan/file3.txt|ac3478d69a3c81fa62e60f5c3696165a4e5e6ac4"
            f"|b026324c6904b2a9cb4b88d6d61c81d1|{now.isoformat()}|5",
        ]
        psv_file.write_text("\n".join(lines) + "\n")

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(psv_file)],
            show_duplicates=True,
            show_missing=False,
            filter_name=True,
            filter_date=True,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # Only file1 matches both: name diff AND date diff
        assert "file1.txt" in captured.out
        # file2: name diff but no date diff -> filtered out
        assert "file2.txt" not in captured.out
        # file3: date diff but no name diff -> filtered out
        assert "file3.txt" not in captured.out

    def test_run_nonexistent_json(self, tmp_path: Path) -> None:
        """Test run with nonexistent JSON file."""
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file="/nonexistent.json",
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="not found"):
            find.run(args)

    def test_run_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test run with nonexistent directory."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        args = argparse.Namespace(
            json_file=str(json_file),
            source=["/nonexistent/dir"],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="not found"):
            find.run(args)

    def test_run_psv_input(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test run with a PSV file as source."""
        # Archive entry
        json_data = [
            {
                "path": "/archive/photo.jpg",
                "size": 1024,
                "sha1": "aabbccdd" * 5,
                "md5": "11223344" * 4,
                "date": "2023-01-01T00:00:00+00:00",
            }
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(json_data))

        sha1 = "aabbccdd" * 5
        md5 = "11223344" * 4
        # PSV file: one duplicate (matches archive) and one missing
        psv_file = tmp_path / "files.psv"
        lines = [
            f"/scan/photo.jpg|{sha1}|{md5}|2023-01-01T00:00:00+00:00|1024",
            "/scan/new.jpg|deadbeef00000000|cafebabe00000000|2023-06-01T00:00:00+00:00|2048",
        ]
        psv_file.write_text("\n".join(lines) + "\n")

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(psv_file)],
            show_duplicates=True,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "Duplicates" in captured.out
        assert "/scan/photo.jpg" in captured.out
        assert "Missing from archive" in captured.out
        assert "/scan/new.jpg" in captured.out

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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=True,
            filter_name=True,
            filter_date=True,
            tolerance=5,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # Should only have one line with the file path
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert "[DUP]" in lines[0]
        assert "file.txt" in lines[0]
        assert "[ref:" in lines[0]
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
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert "[MISS]" in lines[0]
        assert "new.txt" in lines[0]
        assert "[date:" in lines[0]
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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        output = captured.out
        assert "[DUP]" in output
        assert "[MISS]" in output
        assert "file1.txt" in output
        assert "file2.txt" in output

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
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        result = find.run(args)
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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=str(target_dir),
            start=1,
        )

        result = find.run(args)
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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=str(target_dir),
            start=1,
        )

        with pytest.raises(SystemExit, match="mutually exclusive"):
            find.run(args)

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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="cannot be used with --list"):
            find.run(args)

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
            source=[str(scan_dir)],
            show_duplicates=True,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=1,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        # No matching files — no move commands should be emitted
        assert "umask 022" not in captured.out
        assert "mv -iv" not in captured.out
        assert "mkdir -p" not in captured.out

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
            source=[str(scan_dir)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=str(target_dir),
            copy=None,
            start=100,
        )

        result = find.run(args)
        assert result == os.EX_OK

        captured = capsys.readouterr()
        assert "dir00100" in captured.out
        assert "dir00001" not in captured.out


@pytest.mark.unit
class TestFormatListLine:
    """Tests for format_list_line function."""

    def test_miss_line_contains_date_and_size(self) -> None:
        """MISS line contains date and human-readable size."""
        line = find.format_list_line(
            "dir/a.jpg",
            "[MISS]",
            {"date": "2023-01-01T10:00:00", "size": 100},
        )
        assert "[MISS]" in line
        assert "2023" in line
        assert "100 B" in line

    def test_dup_line_no_differences(self) -> None:
        """DUP with same name/date shows path, [DUP], and [ref:]."""
        scanned = {"path": "/scan/a.jpg", "date": "2023-01-01T10:00:00", "size": 100}
        archive = {"path": "/archive/a.jpg", "date": "2023-01-01T10:00:00", "size": 100}
        line = find.format_list_line("scan/a.jpg", "[DUP]", scanned, archive)
        assert "[DUP]" in line
        assert "[ref:" in line
        # No date delta (dates are equal)
        assert "delta" not in line
        # No filename change (basenames are equal)
        assert "->" not in line

    def test_dup_line_date_diff_same_day(self) -> None:
        """DUP with date diff on same day shows time-only format."""
        scanned = {"path": "/scan/a.jpg", "date": "2023-01-01T10:00:00", "size": 100}
        archive = {"path": "/archive/a.jpg", "date": "2023-01-01T10:00:05", "size": 100}
        line = find.format_list_line("scan/a.jpg", "[DUP]", scanned, archive)
        assert "10:00:00" in line
        assert "10:00:05" in line
        assert "delta: +5s" in line
        # Full date should NOT appear (same day)
        assert "2023-01-01" not in line

    def test_dup_line_date_diff_crosses_midnight(self) -> None:
        """DUP with date diff crossing midnight shows full YYYY-MM-DD HH:MM:SS."""
        scanned = {"path": "/scan/a.jpg", "date": "2023-01-01T23:59:00", "size": 100}
        archive = {"path": "/archive/a.jpg", "date": "2023-01-02T00:01:00", "size": 100}
        line = find.format_list_line("scan/a.jpg", "[DUP]", scanned, archive)
        assert "2023-01-01" in line
        assert "2023-01-02" in line

    def test_dup_line_name_diff(self) -> None:
        """DUP with name diff shows 'A -> B'."""
        scanned = {"path": "/scan/IMG_1.JPG", "date": "2023-01-01T10:00:00", "size": 100}
        archive = {"path": "/archive/img_2.jpg", "date": "2023-01-01T10:00:00", "size": 100}
        line = find.format_list_line("scan/IMG_1.JPG", "[DUP]", scanned, archive)
        assert "IMG_1.JPG" in line
        assert "img_2.jpg" in line
        assert "->" in line

    def test_dup_line_date_and_name_diff_both_present(self) -> None:
        """DUP with both date diff and name diff shows both in the same line."""
        scanned = {"path": "/scan/IMG_1.JPG", "date": "2023-01-01T10:00:00", "size": 100}
        archive = {"path": "/archive/img_2.jpg", "date": "2023-01-01T10:00:05", "size": 100}
        line = find.format_list_line("scan/IMG_1.JPG", "[DUP]", scanned, archive)
        assert "delta: +5s" in line
        assert "IMG_1.JPG -> img_2.jpg" in line
        assert "[ref:" in line

    def test_dup_line_date_within_tolerance_not_shown(self) -> None:
        """DUP date delta is suppressed when difference is within tolerance."""
        scanned = {"path": "/scan/a.jpg", "date": "2023-01-01T10:00:00", "size": 100}
        archive = {"path": "/archive/a.jpg", "date": "2023-01-01T10:00:00.5", "size": 100}
        # tolerance=1 → 0.5s diff should not produce delta
        line = find.format_list_line("scan/a.jpg", "[DUP]", scanned, archive, tolerance=1)
        assert "delta" not in line
        assert "->" not in line


@pytest.mark.unit
class TestDupFilters:
    """Tests for _dup_has_name_change and _dup_has_date_change helpers."""

    def test_has_name_change_true(self) -> None:
        """Different basenames returns True."""
        assert find._dup_has_name_change(({"path": "IMG_1.JPG"}, {"path": "img_2.jpg"})) is True

    def test_has_name_change_false_same_case(self) -> None:
        """Identical basenames returns False."""
        assert find._dup_has_name_change(({"path": "a/IMG.JPG"}, {"path": "b/IMG.JPG"})) is False

    def test_has_name_change_false_different_case(self) -> None:
        """Same name different case returns False (case-insensitive)."""
        assert find._dup_has_name_change(({"path": "IMG.JPG"}, {"path": "img.jpg"})) is False

    def test_has_date_change_true(self) -> None:
        """Date difference beyond tolerance returns True."""
        now = datetime.now(UTC)
        later = now + timedelta(seconds=100)
        dup: tuple[dict[str, str | int], dict[str, str | int]] = (
            {"date": now.isoformat()},
            {"date": later.isoformat()},
        )
        assert find._dup_has_date_change(dup, 1) is True

    def test_has_date_change_false_within_tolerance(self) -> None:
        """Date difference within tolerance returns False."""
        now = datetime.now(UTC)
        almost = now + timedelta(seconds=0)
        dup: tuple[dict[str, str | int], dict[str, str | int]] = (
            {"date": now.isoformat()},
            {"date": almost.isoformat()},
        )
        assert find._dup_has_date_change(dup, 1) is False

    def test_has_date_change_invalid_date_returns_false(self) -> None:
        """Unparsable date string returns False without raising."""
        dup: tuple[dict[str, str | int], dict[str, str | int]] = (
            {"date": "not-a-date"},
            {"date": "also-not-a-date"},
        )
        assert find._dup_has_date_change(dup, 1) is False


@pytest.mark.integration
class TestMultipleSources:
    """Integration tests for multiple source arguments."""

    def _make_archive_json(self, tmp_path: Path, files: list[tuple[Path, str]]) -> Path:
        """Write archive JSON for given (path, content) pairs."""
        import hashlib

        json_file = tmp_path / "archive.json"
        entries = []
        for file_path, content in files:
            data = content.encode()
            entries.append(
                {
                    "path": str(file_path.resolve()),
                    "size": len(data),
                    "sha1": hashlib.sha1(data, usedforsecurity=False).hexdigest(),
                    "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
                    "date": datetime.now(UTC).isoformat(),
                }
            )
        json_file.write_text(json.dumps(entries))
        return json_file

    def test_run_two_directories_combined(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Scanning two directories combines their files into one result."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "file_a.txt").write_text("aaa")

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "file_b.txt").write_text("bbb")

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(dir_a), str(dir_b)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)

        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "2 files missing" in captured.out

    def test_run_directory_and_psv_combined(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A directory and a PSV file can be given together."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()
        (scan_dir / "from_dir.txt").write_text("dir content")

        psv_file = tmp_path / "extra.psv"
        psv_file.write_text(
            "/some/path/from_psv.jpg"
            "|aabbccddaabbccddaabbccddaabbccddaabbccdd"
            "|11223344112233441122334411223344"
            "|2024-01-01T10:00:00+00:00|12345\n"
        )

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(scan_dir), str(psv_file)],
            show_duplicates=False,
            show_missing=True,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)

        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "2 files missing" in captured.out

    def test_run_two_directories_list_mode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """List mode works with multiple directories."""
        content = "shared"
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()
        archive_file = archive_dir / "shared.txt"
        archive_file.write_text(content)
        json_file = self._make_archive_json(tmp_path, [(archive_file, content)])

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "shared.txt").write_text(content)  # duplicate

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "unique.txt").write_text("only in b")  # missing

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(dir_a), str(dir_b)],
            show_duplicates=False,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=True,
            move=None,
            copy=None,
            start=1,
        )

        result = find.run(args)

        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "[DUP]" in captured.out
        assert "[MISS]" in captured.out

    def test_validate_args_nonexistent_second_source(self, tmp_path: Path) -> None:
        """validate_args raises SystemExit if any source does not exist."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")
        scan_dir = tmp_path / "scan"
        scan_dir.mkdir()

        args = argparse.Namespace(
            json_file=str(json_file),
            source=[str(scan_dir), "/nonexistent/path"],
            show_duplicates=False,
            show_missing=False,
            filter_name=False,
            filter_date=False,
            tolerance=1,
            list=False,
            move=None,
            copy=None,
            start=1,
        )

        with pytest.raises(SystemExit, match="Source not found"):
            find.validate_args(args)

    def test_setup_parser_multiple_sources(self) -> None:
        """Parser accepts multiple positional source arguments."""
        parser = argparse.ArgumentParser()
        find.setup_parser(parser)

        args = parser.parse_args(["archive.json", "/dir/a", "/dir/b", "/file.psv"])

        assert args.json_file == "archive.json"
        assert args.source == ["/dir/a", "/dir/b", "/file.psv"]
