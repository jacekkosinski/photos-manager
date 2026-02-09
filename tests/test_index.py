"""Tests for index module."""

import argparse
import json
import os
from pathlib import Path

import pytest

from photos_manager.common import calculate_checksums, load_json
from photos_manager.index import extract_numbers, get_file_info, run


class TestCalculateChecksums:
    """Tests for calculate_checksums function."""

    def test_calculates_checksums_for_valid_file(self, tmp_path: Path) -> None:
        """Test that checksums are correctly calculated for a valid file."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 is not None
        assert md5 is not None
        assert len(sha1) == 40  # SHA1 hex length
        assert len(md5) == 32  # MD5 hex length
        # Expected values for "Hello, World!"
        assert sha1 == "0a0a9f2a6772942557ab5355d76af442f8f65e01"
        assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"

    def test_calculates_checksums_for_empty_file(self, tmp_path: Path) -> None:
        """Test that checksums are calculated for an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 is not None
        assert md5 is not None
        # Expected values for empty file
        assert sha1 == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        assert md5 == "d41d8cd98f00b204e9800998ecf8427e"

    def test_calculates_checksums_for_binary_file(self, tmp_path: Path) -> None:
        """Test that checksums work for binary files."""
        test_file = tmp_path / "binary.bin"
        test_content = bytes(range(256))
        test_file.write_bytes(test_content)

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 is not None
        assert md5 is not None
        assert len(sha1) == 40
        assert len(md5) == 32

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that None is returned for nonexistent file."""
        nonexistent = tmp_path / "does_not_exist.txt"

        sha1, md5 = calculate_checksums(str(nonexistent))

        assert sha1 is None
        assert md5 is None

    def test_handles_permission_error(self, tmp_path: Path) -> None:
        """Test handling of permission errors."""
        test_file = tmp_path / "protected.txt"
        test_file.write_text("test")
        # Make file unreadable
        test_file.chmod(0o000)

        try:
            sha1, md5 = calculate_checksums(str(test_file))
            # Should return None for permission errors
            assert sha1 is None
            assert md5 is None
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)


class TestGetFileInfo:
    """Tests for get_file_info function."""

    def test_collects_info_for_single_file(self, tmp_path: Path) -> None:
        """Test that file info is collected for a single file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = get_file_info(str(tmp_path), "UTC")

        assert len(result) == 1
        assert result[0]["path"] == str(test_file)
        assert "sha1" in result[0]
        assert "md5" in result[0]
        assert "date" in result[0]
        assert "size" in result[0]
        assert result[0]["size"] == 7  # "content" is 7 bytes

    def test_collects_info_for_multiple_files(self, tmp_path: Path) -> None:
        """Test that file info is collected for multiple files."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.txt").write_text("content3")

        result = get_file_info(str(tmp_path), "UTC")

        assert len(result) == 3
        paths = [item["path"] for item in result]
        assert str(tmp_path / "file1.txt") in paths
        assert str(tmp_path / "file2.txt") in paths
        assert str(tmp_path / "file3.txt") in paths

    def test_recursive_directory_scan(self, tmp_path: Path) -> None:
        """Test that directory scanning is recursive."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "root.txt").write_text("root")
        (subdir / "nested.txt").write_text("nested")

        result = get_file_info(str(tmp_path), "UTC")

        assert len(result) == 2
        paths = [item["path"] for item in result]
        assert str(tmp_path / "root.txt") in paths
        assert str(subdir / "nested.txt") in paths

    def test_handles_empty_directory(self, tmp_path: Path) -> None:
        """Test that empty directory returns empty list."""
        result = get_file_info(str(tmp_path), "UTC")

        assert result == []

    def test_skips_files_with_read_errors(self, tmp_path: Path) -> None:
        """Test that files with read errors are skipped."""
        good_file = tmp_path / "good.txt"
        good_file.write_text("content")

        # Create a file that will cause read errors
        bad_file = tmp_path / "bad.txt"
        bad_file.write_text("content")
        bad_file.chmod(0o000)

        try:
            result = get_file_info(str(tmp_path), "UTC")

            # Should only include the good file
            assert len(result) == 1
            assert result[0]["path"] == str(good_file)
        finally:
            bad_file.chmod(0o644)

    def test_formats_timestamp_with_timezone(self, tmp_path: Path) -> None:
        """Test that timestamps include timezone information."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = get_file_info(str(tmp_path), "Europe/Warsaw")

        assert len(result) == 1
        date_str = str(result[0]["date"])
        # Check ISO 8601 format with timezone
        assert "T" in date_str
        assert "+" in date_str or "-" in date_str  # Timezone offset

    def test_handles_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test handling of nonexistent directory."""
        nonexistent = tmp_path / "does_not_exist"

        result = get_file_info(str(nonexistent), "UTC")

        assert result == []


class TestExtractNumbers:
    """Tests for extract_numbers function."""

    def test_extracts_numbers_from_path(self) -> None:
        """Test extraction of numbers from directory and filename."""
        result = extract_numbers("/archive/batch_42/photo_123.jpg")

        assert result == (42, 123, "photo_123.jpg")

    def test_returns_zero_when_no_numbers_in_directory(self) -> None:
        """Test that 0 is returned when directory has no numbers."""
        result = extract_numbers("/archive/photos/image_123.jpg")

        assert result == (0, 123, "image_123.jpg")

    def test_returns_zero_when_no_numbers_in_filename(self) -> None:
        """Test that 0 is returned when filename has no numbers."""
        result = extract_numbers("/archive/batch_42/image.jpg")

        assert result == (42, 0, "image.jpg")

    def test_returns_zero_when_no_numbers_at_all(self) -> None:
        """Test that (0, 0, filename) is returned when no numbers found."""
        result = extract_numbers("/archive/photos/image.jpg")

        assert result == (0, 0, "image.jpg")

    def test_extracts_first_number_only(self) -> None:
        """Test that only first number is extracted from each component."""
        result = extract_numbers("/archive/batch_42_99/photo_123_456.jpg")

        assert result == (42, 123, "photo_123_456.jpg")

    def test_handles_relative_path(self) -> None:
        """Test extraction from relative paths."""
        result = extract_numbers("batch_42/photo_123.jpg")

        assert result == (42, 123, "photo_123.jpg")

    def test_handles_filename_only(self) -> None:
        """Test extraction from filename without directory."""
        # Parent directory would be empty or ".", no numbers
        _dir_num, file_num, filename = extract_numbers("photo_123.jpg")
        assert file_num == 123
        assert filename == "photo_123.jpg"


class TestLoadJson:
    """Tests for load_json function."""

    def test_loads_valid_json_file(self, tmp_path: Path) -> None:
        """Test loading a valid JSON file."""
        data = [
            {"path": "/test1", "sha1": "abc", "md5": "def", "date": "2025-01-01", "size": 100},
            {"path": "/test2", "sha1": "ghi", "md5": "jkl", "date": "2025-01-02", "size": 200},
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        result = load_json(str(json_file))

        assert result == data
        assert len(result) == 2

    def test_loads_empty_json_array(self, tmp_path: Path) -> None:
        """Test loading an empty JSON array."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("[]")

        result = load_json(str(json_file))

        assert result == []

    def test_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for nonexistent file."""
        nonexistent = tmp_path / "does_not_exist.json"

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(nonexistent))

        assert "does not exist" in str(exc_info.value)

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for invalid JSON syntax."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text('{"invalid": json}')

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(json_file))

        assert "Invalid JSON" in str(exc_info.value)

    def test_loads_json_with_unicode(self, tmp_path: Path) -> None:
        """Test loading JSON with Unicode characters."""
        data = [
            {
                "path": "/photos/zdjęcie.jpg",
                "sha1": "abc",
                "md5": "def",
                "date": "2025-01-01",
                "size": 100,
            }
        ]
        json_file = tmp_path / "unicode.json"
        json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = load_json(str(json_file))

        assert result is not None
        assert result[0]["path"] == "/photos/zdjęcie.jpg"


class TestRun:
    """Integration tests for run() function."""

    def test_run_creates_json_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that run() creates a JSON file with correct structure."""
        # Create test directory with a file
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "test.txt"
        test_file.write_text("Hello")

        # Change to tmp_path so output file is created there
        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        assert output_file.exists()

        # Verify JSON structure
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert "path" in data[0]
        assert "sha1" in data[0]
        assert "md5" in data[0]
        assert "date" in data[0]
        assert "size" in data[0]

    def test_run_with_invalid_directory(self) -> None:
        """Test that run() raises SystemExit for invalid directory."""
        args = argparse.Namespace(
            directory="/nonexistent/directory",
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "not a valid directory" in str(exc_info.value)

    def test_run_with_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that run() merges data from existing JSON."""
        # Create test directory
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "new.txt"
        test_file.write_text("New")

        # Create merge file
        merge_data = [
            {
                "path": "/old/file.txt",
                "sha1": "old_sha1",
                "md5": "old_md5",
                "date": "2024-01-01T00:00:00+00:00",
                "size": 100,
            }
        ]
        merge_file = tmp_path / "merge.json"
        merge_file.write_text(json.dumps(merge_data))

        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge=str(merge_file),
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        data = json.loads(output_file.read_text())
        assert len(data) == 2  # One new + one merged

    def test_run_with_duplicate_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that run() detects duplicate paths."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "test.txt"
        test_file.write_text("Content")

        # Create merge file with duplicate path
        merge_data = [
            {
                "path": str(test_file),
                "sha1": "different_sha1",
                "md5": "different_md5",
                "date": "2024-01-01T00:00:00+00:00",
                "size": 100,
            }
        ]
        merge_file = tmp_path / "merge.json"
        merge_file.write_text(json.dumps(merge_data))

        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge=str(merge_file),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "Duplicate path found" in str(exc_info.value)

    def test_run_with_sort_by_number(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that run() sorts by number when requested."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        (test_dir / "file_10.txt").write_text("10")
        (test_dir / "file_2.txt").write_text("2")
        (test_dir / "file_1.txt").write_text("1")

        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=True,
            sort_by_dir=False,
            merge=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        data = json.loads(output_file.read_text())
        filenames = [Path(item["path"]).name for item in data]
        assert filenames == ["file_1.txt", "file_2.txt", "file_10.txt"]

    def test_run_with_sort_by_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that run() sorts by directory when requested."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        (test_dir / "a_dir").mkdir()
        (test_dir / "b_dir").mkdir()
        (test_dir / "a_dir" / "file.txt").write_text("a")
        (test_dir / "b_dir" / "file.txt").write_text("b")
        (test_dir / "file.txt").write_text("root")

        monkeypatch.chdir(tmp_path)

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=True,
            merge=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        data = json.loads(output_file.read_text())
        # Files should be grouped by directory
        dirs = [str(Path(item["path"]).parent) for item in data]
        assert dirs == sorted(dirs)

    def test_run_with_nonexistent_merge_file(self, tmp_path: Path) -> None:
        """Test that run() raises SystemExit for nonexistent merge file."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge="/nonexistent/merge.json",
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "merge file" in str(exc_info.value).lower()
        assert "does not exist" in str(exc_info.value).lower()

    def test_run_with_invalid_merge_json(self, tmp_path: Path) -> None:
        """Test that run() raises SystemExit for invalid merge JSON."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()

        merge_file = tmp_path / "invalid.json"
        merge_file.write_text("{invalid json}")

        args = argparse.Namespace(
            directory=str(test_dir),
            time_zone="UTC",
            sort_by_number=False,
            sort_by_dir=False,
            merge=str(merge_file),
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "invalid format" in str(exc_info.value).lower()
