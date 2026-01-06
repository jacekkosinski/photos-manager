"""Tests for verify module."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from photos_manager.verify import (
    calculate_checksums,
    calculate_file_hash,
    find_json_files,
    find_version_file,
    load_json,
    load_version_json,
    verify_directory_timestamps,
    verify_file_entry,
    verify_json_file_timestamp,
    verify_timestamps,
    verify_version_file,
)


class TestLoadJson:
    """Tests for load_json function."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        """Test that valid JSON is loaded correctly."""
        json_file = tmp_path / "test.json"
        data = cast(
            list[dict[str, str | int]],
            [{"path": "/test.jpg", "sha1": "abc", "md5": "def", "size": 100}],
        )
        json_file.write_text(json.dumps(data))

        result = load_json(str(json_file))

        assert len(result) == 1
        assert result[0]["path"] == "/test.jpg"

    def test_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for nonexistent file."""
        with pytest.raises(SystemExit, match="does not exist"):
            load_json(str(tmp_path / "missing.json"))

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for invalid JSON."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("not valid json")

        with pytest.raises(SystemExit, match="invalid format"):
            load_json(str(json_file))


class TestLoadVersionJson:
    """Tests for load_version_json function."""

    def test_loads_valid_version_json(self, tmp_path: Path) -> None:
        """Test that valid version JSON is loaded correctly."""
        version_file = tmp_path / ".version.json"
        data = {
            "version": "photos-1.234-567",
            "total_bytes": 1234567890,
            "file_count": 567,
            "files": {"test.json": "abc123"},
        }
        version_file.write_text(json.dumps(data))

        result = load_version_json(str(version_file))

        assert result["version"] == "photos-1.234-567"
        assert result["total_bytes"] == 1234567890

    def test_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for nonexistent file."""
        with pytest.raises(SystemExit, match="does not exist"):
            load_version_json(str(tmp_path / ".version.json"))


class TestFindJsonFiles:
    """Tests for find_json_files function."""

    def test_finds_json_files(self, tmp_path: Path) -> None:
        """Test that JSON files are found in directory."""
        (tmp_path / "file1.json").write_text("[]")
        (tmp_path / "file2.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 2
        assert any("file1.json" in p for p in result)
        assert any("file2.json" in p for p in result)

    def test_excludes_version_json_files(self, tmp_path: Path) -> None:
        """Test that *version.json files are excluded."""
        (tmp_path / "archive.json").write_text("[]")
        (tmp_path / ".version.json").write_text("{}")
        (tmp_path / "data.version.json").write_text("{}")

        result = find_json_files(str(tmp_path))

        assert len(result) == 1
        assert "archive.json" in result[0]

    def test_recursive_search(self, tmp_path: Path) -> None:
        """Test that search is recursive."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "root.json").write_text("[]")
        (subdir / "nested.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 2
        assert any("root.json" in p for p in result)
        assert any("nested.json" in p for p in result)

    def test_raises_on_empty_directory(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when no JSON files found."""
        with pytest.raises(SystemExit, match="No JSON metadata files found"):
            find_json_files(str(tmp_path))


class TestFindVersionFile:
    """Tests for find_version_file function."""

    def test_finds_version_file(self, tmp_path: Path) -> None:
        """Test that .version.json is found."""
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        result = find_version_file(str(tmp_path))

        assert result == str(version_file)

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Test that None is returned when .version.json doesn't exist."""
        result = find_version_file(str(tmp_path))

        assert result is None


class TestCalculateChecksums:
    """Tests for calculate_checksums function."""

    def test_calculates_checksums_for_valid_file(self, tmp_path: Path) -> None:
        """Test that checksums are correctly calculated."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        sha1, md5 = calculate_checksums(str(test_file))

        assert len(sha1) == 40
        assert len(md5) == 32
        assert sha1 == "0a0a9f2a6772942557ab5355d76af442f8f65e01"
        assert md5 == "65a8e27d8879283831b664bd8b7f0ad4"

    def test_calculates_checksums_for_empty_file(self, tmp_path: Path) -> None:
        """Test checksums for empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_bytes(b"")

        sha1, md5 = calculate_checksums(str(test_file))

        assert sha1 == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        assert md5 == "d41d8cd98f00b204e9800998ecf8427e"


class TestCalculateFileHash:
    """Tests for calculate_file_hash function."""

    def test_calculates_file_hash(self, tmp_path: Path) -> None:
        """Test that file hash is calculated correctly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        result = calculate_file_hash(str(test_file))

        assert len(result) == 40
        assert isinstance(result, str)


class TestVerifyFileEntry:
    """Tests for verify_file_entry function."""

    def test_verifies_valid_file(self, tmp_path: Path) -> None:
        """Test that valid file passes verification."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        entry = cast(
            dict[str, str | int],
            {
                "path": str(test_file),
                "size": len(test_content),
                "sha1": "0a0a9f2a6772942557ab5355d76af442f8f65e01",
                "md5": "65a8e27d8879283831b664bd8b7f0ad4",
            },
        )

        success, errors = verify_file_entry(entry, verify_checksums=True)

        assert success is True
        assert len(errors) == 0

    def test_detects_missing_file(self, tmp_path: Path) -> None:
        """Test that missing file is detected."""
        entry = cast(
            dict[str, str | int],
            {
                "path": str(tmp_path / "missing.txt"),
                "size": 100,
                "sha1": "abc",
                "md5": "def",
            },
        )

        success, errors = verify_file_entry(entry, verify_checksums=False)

        assert success is False
        assert len(errors) > 0
        assert any("not found" in err for err in errors)

    def test_detects_size_mismatch(self, tmp_path: Path) -> None:
        """Test that size mismatch is detected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        entry = cast(
            dict[str, str | int],
            {
                "path": str(test_file),
                "size": 999,  # Wrong size
                "sha1": "abc",
                "md5": "def",
            },
        )

        success, errors = verify_file_entry(entry, verify_checksums=False)

        assert success is False
        assert any("Size mismatch" in err for err in errors)

    def test_detects_sha1_mismatch(self, tmp_path: Path) -> None:
        """Test that SHA-1 mismatch is detected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        entry = cast(
            dict[str, str | int],
            {
                "path": str(test_file),
                "size": 7,
                "sha1": "wrong_sha1_hash_1234567890123456789012",
                "md5": "wrong_md5_hash_12345678901234",
            },
        )

        success, errors = verify_file_entry(entry, verify_checksums=True)

        assert success is False
        assert any("SHA-1 mismatch" in err for err in errors)
        assert any("MD5 mismatch" in err for err in errors)

    def test_skips_checksum_verification_by_default(self, tmp_path: Path) -> None:
        """Test that checksums are not verified by default."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        entry = cast(
            dict[str, str | int],
            {
                "path": str(test_file),
                "size": 7,
                "sha1": "wrong_hash",
                "md5": "wrong_hash",
            },
        )

        # Without verify_checksums=True, should pass despite wrong hashes
        success, errors = verify_file_entry(entry, verify_checksums=False)

        assert success is True
        assert len(errors) == 0

    def test_handles_missing_path_field(self) -> None:
        """Test handling of missing path field."""
        entry = cast(dict[str, str | int], {"size": 100, "sha1": "abc", "md5": "def"})

        success, errors = verify_file_entry(entry, verify_checksums=False)

        assert success is False
        assert any("Missing 'path'" in err for err in errors)


class TestVerifyTimestamps:
    """Tests for verify_timestamps function."""

    def test_verifies_matching_timestamp(self, tmp_path: Path) -> None:
        """Test that matching timestamp passes verification."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Get current mtime
        mtime = int(test_file.stat().st_mtime)
        date_str = datetime.fromtimestamp(mtime).astimezone().isoformat()

        entry = cast(dict[str, str | int], {"path": str(test_file), "date": date_str})

        success, errors = verify_timestamps(entry, tolerance_seconds=1)

        assert success is True
        assert len(errors) == 0

    def test_detects_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that timestamp mismatch is detected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Use very old timestamp
        entry = cast(
            dict[str, str | int],
            {"path": str(test_file), "date": "2020-01-01T00:00:00+0000"},
        )

        success, errors = verify_timestamps(entry, tolerance_seconds=1)

        assert success is False
        assert any("Timestamp mismatch" in err for err in errors)

    def test_respects_tolerance(self, tmp_path: Path) -> None:
        """Test that tolerance parameter is respected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Get current mtime and add 5 seconds
        mtime = int(test_file.stat().st_mtime) + 5
        date_str = datetime.fromtimestamp(mtime).astimezone().isoformat()

        entry = cast(dict[str, str | int], {"path": str(test_file), "date": date_str})

        # Should fail with 1 second tolerance
        success1, _ = verify_timestamps(entry, tolerance_seconds=1)
        assert success1 is False

        # Should pass with 10 second tolerance
        success2, errors2 = verify_timestamps(entry, tolerance_seconds=10)
        assert success2 is True
        assert len(errors2) == 0

    def test_handles_invalid_date_format(self, tmp_path: Path) -> None:
        """Test handling of invalid date format."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        entry = cast(dict[str, str | int], {"path": str(test_file), "date": "invalid-date"})

        success, errors = verify_timestamps(entry, tolerance_seconds=1)

        assert success is False
        assert any("Invalid date format" in err for err in errors)


class TestVerifyDirectoryTimestamps:
    """Tests for verify_directory_timestamps function."""

    def test_verifies_directory_timestamps(self, tmp_path: Path) -> None:
        """Test that directory timestamps are verified correctly."""
        # Create directory with file
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        # Set matching timestamps
        target_date = "2024-01-01T12:00:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))
        os.utime(str(subdir), (target_timestamp, target_timestamp))

        data = cast(list[dict[str, str | int]], [{"path": str(test_file), "date": target_date}])

        dir_count, errors = verify_directory_timestamps(data)

        assert dir_count == 1
        assert len(errors) == 0

    def test_detects_directory_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that directory timestamp mismatch is detected."""
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        # Set different timestamps
        file_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+0000").timestamp())
        dir_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+0000").timestamp())

        os.utime(str(test_file), (file_timestamp, file_timestamp))
        os.utime(str(subdir), (dir_timestamp, dir_timestamp))

        data = cast(
            list[dict[str, str | int]],
            [{"path": str(test_file), "date": "2024-01-01T12:00:00+0000"}],
        )

        dir_count, errors = verify_directory_timestamps(data)

        assert dir_count == 1
        assert len(errors) > 0
        assert any("timestamp mismatch" in err for err in errors)


class TestVerifyJsonFileTimestamp:
    """Tests for verify_json_file_timestamp function."""

    def test_verifies_json_timestamp(self, tmp_path: Path) -> None:
        """Test that JSON file timestamp is verified correctly."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("content")

        json_file = tmp_path / "test.json"
        json_file.write_text("[]")

        # Set matching timestamps
        target_timestamp = int(test_file.stat().st_mtime)
        os.utime(str(json_file), (target_timestamp, target_timestamp))

        date_str = datetime.fromtimestamp(target_timestamp).astimezone().isoformat()
        data = cast(list[dict[str, str | int]], [{"path": str(test_file), "date": date_str}])

        success, errors = verify_json_file_timestamp(str(json_file), data)

        assert success is True
        assert len(errors) == 0

    def test_detects_json_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that JSON file timestamp mismatch is detected."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("content")

        json_file = tmp_path / "test.json"
        json_file.write_text("[]")

        # Set very different timestamp on JSON file
        old_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+0000").timestamp())
        os.utime(str(json_file), (old_timestamp, old_timestamp))

        mtime = int(test_file.stat().st_mtime)
        date_str = datetime.fromtimestamp(mtime).astimezone().isoformat()
        data = cast(list[dict[str, str | int]], [{"path": str(test_file), "date": date_str}])

        success, errors = verify_json_file_timestamp(str(json_file), data)

        assert success is False
        assert any("timestamp mismatch" in err for err in errors)


class TestVerifyVersionFile:
    """Tests for verify_version_file function."""

    def test_verifies_valid_version_file(self, tmp_path: Path) -> None:
        """Test that valid version file passes verification."""
        # Create JSON metadata file
        json_file = tmp_path / "archive.json"
        data = cast(
            list[dict[str, str | int]],
            [
                {
                    "path": "/test1.jpg",
                    "size": 100,
                    "sha1": "abc",
                    "md5": "def",
                    "date": "2024-01-01",
                },
                {
                    "path": "/test2.jpg",
                    "size": 200,
                    "sha1": "ghi",
                    "md5": "jkl",
                    "date": "2024-01-02",
                },
            ],
        )
        json_file.write_text(json.dumps(data))

        # Calculate actual hash
        actual_hash = calculate_file_hash(str(json_file))

        # Create version file
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-300",
            "total_bytes": 300,
            "file_count": 2,
            "files": {"archive.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))

        success, errors = verify_version_file(str(version_file), [str(json_file)], data)

        assert success is True
        assert len(errors) == 0

    def test_detects_hash_mismatch(self, tmp_path: Path) -> None:
        """Test that file hash mismatch is detected."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-0",
            "total_bytes": 0,
            "file_count": 0,
            "files": {"archive.json": "wrong_hash_1234567890123456789012345678"},
        }
        version_file.write_text(json.dumps(version_data))

        success, errors = verify_version_file(str(version_file), [str(json_file)], [])

        assert success is False
        assert any("Hash mismatch" in err for err in errors)

    def test_detects_total_bytes_mismatch(self, tmp_path: Path) -> None:
        """Test that total bytes mismatch is detected."""
        json_file = tmp_path / "archive.json"
        data = cast(
            list[dict[str, str | int]],
            [{"path": "/test.jpg", "size": 100, "sha1": "abc", "md5": "def"}],
        )
        json_file.write_text(json.dumps(data))

        actual_hash = calculate_file_hash(str(json_file))

        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 999,  # Wrong total
            "file_count": 1,
            "files": {"archive.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))

        success, errors = verify_version_file(str(version_file), [str(json_file)], data)

        assert success is False
        assert any("Total bytes mismatch" in err for err in errors)

    def test_detects_file_count_mismatch(self, tmp_path: Path) -> None:
        """Test that file count mismatch is detected."""
        json_file = tmp_path / "archive.json"
        data = cast(
            list[dict[str, str | int]],
            [{"path": "/test.jpg", "size": 100, "sha1": "abc", "md5": "def"}],
        )
        json_file.write_text(json.dumps(data))

        actual_hash = calculate_file_hash(str(json_file))

        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-99",
            "total_bytes": 100,
            "file_count": 99,  # Wrong count
            "files": {"archive.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))

        success, errors = verify_version_file(str(version_file), [str(json_file)], data)

        assert success is False
        assert any("File count mismatch" in err for err in errors)

    def test_detects_missing_required_field(self, tmp_path: Path) -> None:
        """Test that missing required fields are detected."""
        version_file = tmp_path / ".version.json"
        version_data = {"version": "photos-0.000-0"}  # Missing required fields
        version_file.write_text(json.dumps(version_data))

        success, errors = verify_version_file(str(version_file), [], [])

        assert success is False
        assert any("missing required field" in err for err in errors)
