"""Tests for mkjson module."""

import json
import os
from pathlib import Path

import pytest

from photos_manager.mkjson import (
    calculate_checksums,
    extract_numbers,
    get_file_info,
    load_json,
    main,
)


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

        assert "invalid format" in str(exc_info.value)

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


class TestMain:
    """Tests for main function."""

    def test_creates_json_file_for_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main creates a JSON file for a directory."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        (test_dir / "image.jpg").write_bytes(b"fake image data")

        # Change to tmp_path so output file is created there
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir)])

        exit_code = main()

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        assert output_file.exists()

        # Verify JSON content
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["path"] == str(test_dir / "image.jpg")

    def test_exits_with_error_for_nonexistent_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error for nonexistent directory."""
        monkeypatch.setattr("sys.argv", ["mkjson.py", "/nonexistent/directory"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert "not a valid directory" in str(exc_info.value)

    def test_exits_with_error_for_nonexistent_merge_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error for nonexistent merge file."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()

        monkeypatch.setattr(
            "sys.argv", ["mkjson.py", str(test_dir), "--merge", "/nonexistent.json"]
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert "does not exist" in str(exc_info.value)

    def test_exits_with_error_for_invalid_merge_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error for invalid JSON in merge file."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()

        invalid_json = tmp_path / "invalid.json"
        invalid_json.write_text('{"invalid": json}')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir), "--merge", str(invalid_json)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert "invalid format" in str(exc_info.value)

    def test_exits_with_error_for_duplicate_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error when duplicates are detected."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        (test_dir / "image.jpg").write_bytes(b"data")

        # Create merge file with same path
        merge_data = [
            {
                "path": str(test_dir / "image.jpg"),
                "sha1": "different",
                "md5": "different",
                "date": "2025-01-01T00:00:00+0000",
                "size": 100,
            }
        ]
        merge_file = tmp_path / "merge.json"
        merge_file.write_text(json.dumps(merge_data))

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir), "--merge", str(merge_file)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert "Duplicate path found" in str(exc_info.value)

    def test_merges_with_existing_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main properly merges with existing JSON file."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        (test_dir / "new_image.jpg").write_bytes(b"new data")

        # Create merge file with different file
        merge_data = [
            {
                "path": "/old/image.jpg",
                "sha1": "abc123",
                "md5": "def456",
                "date": "2025-01-01T00:00:00+0000",
                "size": 100,
            }
        ]
        merge_file = tmp_path / "merge.json"
        merge_file.write_text(json.dumps(merge_data))

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir), "--merge", str(merge_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        output_file = tmp_path / "photos.json"
        assert output_file.exists()

        # Verify merged content
        data = json.loads(output_file.read_text())
        assert len(data) == 2
        paths = [item["path"] for item in data]
        assert "/old/image.jpg" in paths
        assert str(test_dir / "new_image.jpg") in paths

    def test_sorts_by_number_when_flag_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --sort-by-number flag works correctly."""
        test_dir = tmp_path / "batch_1"
        test_dir.mkdir()
        (test_dir / "photo_3.jpg").write_bytes(b"data3")
        (test_dir / "photo_1.jpg").write_bytes(b"data1")
        (test_dir / "photo_2.jpg").write_bytes(b"data2")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir), "--sort-by-number"])

        exit_code = main()

        assert exit_code == os.EX_OK
        output_file = tmp_path / "batch_1.json"
        data = json.loads(output_file.read_text())

        # Verify numeric sorting
        paths = [Path(item["path"]).name for item in data]
        assert paths == ["photo_1.jpg", "photo_2.jpg", "photo_3.jpg"]

    def test_handles_unicode_in_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that Unicode characters are properly handled in output."""
        test_dir = tmp_path / "zdjęcia"
        test_dir.mkdir()
        (test_dir / "obraz.jpg").write_bytes(b"data")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["mkjson.py", str(test_dir)])

        exit_code = main()

        assert exit_code == os.EX_OK
        output_file = tmp_path / "zdjęcia.json"
        assert output_file.exists()

        # Verify Unicode is preserved
        content = output_file.read_text(encoding="utf-8")
        assert "zdjęcia" in content
        assert "obraz.jpg" in content
