"""Tests for photos_manager.common module."""

import json
import os
from pathlib import Path

import pytest

from photos_manager.common import (
    CHUNK_SIZE,
    calculate_checksums,
    calculate_checksums_strict,
    find_json_files,
    find_json_files_with_mtime,
    load_json,
)


class TestLoadJson:
    """Tests for load_json function."""

    def test_valid_json_file(self, tmp_path: Path) -> None:
        """Test loading valid JSON file."""
        json_file = tmp_path / "test.json"
        data = [
            {"path": "/test/file1.jpg", "size": 100},
            {"path": "/test/file2.jpg", "size": 200},
        ]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        result = load_json(str(json_file))
        assert result == data

    def test_nonexistent_file_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that nonexistent file raises SystemExit."""
        nonexistent = tmp_path / "nonexistent.json"

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(nonexistent))

        assert "does not exist" in str(exc_info.value)

    def test_invalid_json_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that invalid JSON raises SystemExit."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("{invalid json}", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(json_file))

        assert "Invalid JSON" in str(exc_info.value)

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test that empty file raises SystemExit."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(json_file))

        assert "Invalid JSON" in str(exc_info.value)

    def test_non_array_json_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that JSON object (not array) raises SystemExit."""
        json_file = tmp_path / "object.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_json(str(json_file))

        assert "does not contain a JSON array" in str(exc_info.value)

    def test_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that passing a directory raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            load_json(str(tmp_path))

        assert "is not a file" in str(exc_info.value)


class TestCalculateChecksums:
    """Tests for calculate_checksums (lenient version)."""

    def test_valid_file_returns_checksums(self, tmp_path: Path) -> None:
        """Test calculating checksums for valid file."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"Hello, World!")

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 == "0a0a9f2a6772942557ab5355d76af442f8f65e01"
        assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test calculating checksums for empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        assert md5 == "d41d8cd98f00b204e9800998ecf8427e"

    def test_binary_file(self, tmp_path: Path) -> None:
        """Test calculating checksums for binary file."""
        test_file = tmp_path / "binary.bin"
        test_file.write_bytes(bytes(range(256)))

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 is not None
        assert md5 is not None
        assert len(sha1) == 40  # SHA1 hex length
        assert len(md5) == 32  # MD5 hex length

    def test_nonexistent_file_returns_none(self, tmp_path: Path) -> None:
        """Test that nonexistent file returns (None, None)."""
        nonexistent = tmp_path / "nonexistent.txt"

        sha1, md5 = calculate_checksums(str(nonexistent))

        assert sha1 is None
        assert md5 is None

    def test_large_file_uses_chunks(self, tmp_path: Path) -> None:
        """Test that large file (>64KB) is processed in chunks."""
        test_file = tmp_path / "large.bin"
        # Create file larger than CHUNK_SIZE
        data = b"x" * (CHUNK_SIZE * 2 + 1000)
        test_file.write_bytes(data)

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 is not None
        assert md5 is not None
        assert len(sha1) == 40
        assert len(md5) == 32

    def test_permission_error_returns_none(self, tmp_path: Path) -> None:
        """Test that permission error returns (None, None)."""
        if os.name == "nt":  # Skip on Windows
            pytest.skip("Permission test not reliable on Windows")

        test_file = tmp_path / "no_read.txt"
        test_file.write_bytes(b"test")
        test_file.chmod(0o000)

        try:
            sha1, md5 = calculate_checksums(str(test_file))
            assert sha1 is None
            assert md5 is None
        finally:
            test_file.chmod(0o644)


class TestCalculateChecksumsStrict:
    """Tests for calculate_checksums_strict (strict version)."""

    def test_valid_file(self, tmp_path: Path) -> None:
        """Test calculating checksums for valid file."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"Hello, World!")

        sha1, md5 = calculate_checksums_strict(str(test_file))

        assert sha1 == "0a0a9f2a6772942557ab5355d76af442f8f65e01"
        assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"

    def test_nonexistent_file_raises_oserror(self, tmp_path: Path) -> None:
        """Test that nonexistent file raises OSError."""
        nonexistent = tmp_path / "nonexistent.txt"

        with pytest.raises(OSError, match="No such file"):
            calculate_checksums_strict(str(nonexistent))

    def test_permission_error_raises_oserror(self, tmp_path: Path) -> None:
        """Test that permission error raises OSError."""
        if os.name == "nt":  # Skip on Windows
            pytest.skip("Permission test not reliable on Windows")

        test_file = tmp_path / "no_read.txt"
        test_file.write_bytes(b"test")
        test_file.chmod(0o000)

        try:
            with pytest.raises(OSError, match="Permission denied"):
                calculate_checksums_strict(str(test_file))
        finally:
            test_file.chmod(0o644)

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test calculating checksums for empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        sha1, md5 = calculate_checksums_strict(str(test_file))

        assert sha1 == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        assert md5 == "d41d8cd98f00b204e9800998ecf8427e"


class TestFindJsonFiles:
    """Tests for find_json_files function."""

    def test_finds_json_files(self, tmp_path: Path) -> None:
        """Test finding JSON files in directory."""
        (tmp_path / "file1.json").write_text("[]")
        (tmp_path / "file2.json").write_text("[]")
        (tmp_path / "file.txt").write_text("not json")

        result = find_json_files(str(tmp_path))

        assert len(result) == 2
        assert all(f.endswith(".json") for f in result)

    def test_excludes_version_json(self, tmp_path: Path) -> None:
        """Test that *version.json files are excluded."""
        (tmp_path / "data.json").write_text("[]")
        (tmp_path / "archive.version.json").write_text("{}")
        (tmp_path / ".version.json").write_text("{}")

        result = find_json_files(str(tmp_path))

        assert len(result) == 1
        assert result[0].endswith("data.json")

    def test_empty_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that directory with no JSON files raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            find_json_files(str(tmp_path))

        assert "No JSON files found" in str(exc_info.value)

    def test_nested_directories(self, tmp_path: Path) -> None:
        """Test finding JSON files in nested directories."""
        (tmp_path / "file1.json").write_text("[]")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.json").write_text("[]")
        subsubdir = subdir / "nested"
        subsubdir.mkdir()
        (subsubdir / "file3.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 3

    def test_sorted_by_name(self, tmp_path: Path) -> None:
        """Test that results are sorted by filename."""
        (tmp_path / "c.json").write_text("[]")
        (tmp_path / "a.json").write_text("[]")
        (tmp_path / "b.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        filenames = [Path(f).name for f in result]
        assert filenames == ["a.json", "b.json", "c.json"]

    def test_nonexistent_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that nonexistent directory raises SystemExit."""
        nonexistent = tmp_path / "nonexistent"

        with pytest.raises(SystemExit) as exc_info:
            find_json_files(str(nonexistent))

        assert "does not exist" in str(exc_info.value)

    def test_file_not_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that passing a file instead of directory raises SystemExit."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("test")

        with pytest.raises(SystemExit) as exc_info:
            find_json_files(str(test_file))

        assert "is not a directory" in str(exc_info.value)


class TestFindJsonFilesWithMtime:
    """Tests for find_json_files_with_mtime function."""

    def test_returns_tuples_with_mtime(self, tmp_path: Path) -> None:
        """Test that function returns (mtime, path) tuples."""
        (tmp_path / "file1.json").write_text("[]")
        (tmp_path / "file2.json").write_text("[]")

        result = find_json_files_with_mtime(str(tmp_path))

        assert len(result) == 2
        assert all(isinstance(item, tuple) for item in result)
        assert all(len(item) == 2 for item in result)
        assert all(isinstance(item[0], float) for item in result)
        assert all(isinstance(item[1], str) for item in result)

    def test_sorted_by_mtime_descending(self, tmp_path: Path) -> None:
        """Test that results are sorted by mtime, newest first."""
        import os
        import time

        base_time = time.time()

        file1 = tmp_path / "file1.json"
        file1.write_text("[]")
        os.utime(file1, (base_time - 2, base_time - 2))

        file2 = tmp_path / "file2.json"
        file2.write_text("[]")
        os.utime(file2, (base_time - 1, base_time - 1))

        file3 = tmp_path / "file3.json"
        file3.write_text("[]")
        os.utime(file3, (base_time, base_time))

        result = find_json_files_with_mtime(str(tmp_path))

        # Should be sorted newest first
        mtimes = [item[0] for item in result]
        assert mtimes == sorted(mtimes, reverse=True)

        # file3 should be first (newest)
        assert result[0][1].endswith("file3.json")

    def test_excludes_version_json(self, tmp_path: Path) -> None:
        """Test that *version.json files are excluded."""
        (tmp_path / "data.json").write_text("[]")
        (tmp_path / "archive.version.json").write_text("{}")

        result = find_json_files_with_mtime(str(tmp_path))

        assert len(result) == 1
        assert result[0][1].endswith("data.json")

    def test_empty_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that directory with no JSON files raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            find_json_files_with_mtime(str(tmp_path))

        assert "No JSON files found" in str(exc_info.value)

    def test_nested_directories(self, tmp_path: Path) -> None:
        """Test finding JSON files with mtime in nested directories."""
        (tmp_path / "file1.json").write_text("[]")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file2.json").write_text("[]")

        result = find_json_files_with_mtime(str(tmp_path))

        assert len(result) == 2
