"""Tests for verify module."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from _pytest.capture import CaptureFixture

from photos_manager.verify import (
    calculate_checksums,
    calculate_file_hash,
    collect_expected_files,
    collect_filesystem_files,
    find_duplicate_checksums,
    find_extra_files,
    find_json_files,
    find_version_file,
    find_zero_byte_files,
    load_json,
    load_version_json,
    main,
    verify_directory_timestamps,
    verify_file_entry,
    verify_json_file_timestamp,
    verify_timestamps,
    verify_version_file,
    verify_version_file_timestamp,
)


class TestLoadJson:
    """Tests for load_json function."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        """Test that valid JSON is loaded correctly."""
        json_file = tmp_path / "test.json"
        data = cast(
            "list[dict[str, str | int]]",
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
            "dict[str, str | int]",
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
            "dict[str, str | int]",
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
            "dict[str, str | int]",
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
            "dict[str, str | int]",
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
            "dict[str, str | int]",
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
        entry = cast("dict[str, str | int]", {"size": 100, "sha1": "abc", "md5": "def"})

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

        entry = cast("dict[str, str | int]", {"path": str(test_file), "date": date_str})

        success, errors = verify_timestamps(entry, tolerance_seconds=1)

        assert success is True
        assert len(errors) == 0

    def test_detects_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that timestamp mismatch is detected."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Use very old timestamp
        entry = cast(
            "dict[str, str | int]",
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

        entry = cast("dict[str, str | int]", {"path": str(test_file), "date": date_str})

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

        entry = cast("dict[str, str | int]", {"path": str(test_file), "date": "invalid-date"})

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

        data = cast("list[dict[str, str | int]]", [{"path": str(test_file), "date": target_date}])

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
            "list[dict[str, str | int]]",
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
        data = cast("list[dict[str, str | int]]", [{"path": str(test_file), "date": date_str}])

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
        data = cast("list[dict[str, str | int]]", [{"path": str(test_file), "date": date_str}])

        success, errors = verify_json_file_timestamp(str(json_file), data)

        assert success is False
        assert any("timestamp mismatch" in err for err in errors)


class TestVerifyVersionFileTimestamp:
    """Tests for verify_version_file_timestamp function."""

    def test_verifies_version_file_timestamp(self, tmp_path: Path) -> None:
        """Test that version file timestamp is verified correctly."""
        json_file1 = tmp_path / "archive1.json"
        json_file1.write_text("[]")

        json_file2 = tmp_path / "archive2.json"
        json_file2.write_text("[]")

        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        # Set version file timestamp to match newest JSON file
        target_timestamp = int(json_file2.stat().st_mtime)
        os.utime(str(version_file), (target_timestamp, target_timestamp))

        json_files = [str(json_file1), str(json_file2)]

        success, errors = verify_version_file_timestamp(str(version_file), json_files)

        assert success is True
        assert len(errors) == 0

    def test_detects_version_file_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that version file timestamp mismatch is detected."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        # Set very different timestamp on version file
        old_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+0000").timestamp())
        os.utime(str(version_file), (old_timestamp, old_timestamp))

        json_files = [str(json_file)]

        success, errors = verify_version_file_timestamp(str(version_file), json_files)

        assert success is False
        assert any("timestamp mismatch" in err for err in errors)

    def test_handles_nonexistent_version_file(self, tmp_path: Path) -> None:
        """Test that error is returned for nonexistent version file."""
        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        version_file = tmp_path / ".version.json"

        json_files = [str(json_file)]

        success, errors = verify_version_file_timestamp(str(version_file), json_files)

        assert success is False
        assert any("not found" in err for err in errors)

    def test_handles_empty_json_files_list(self, tmp_path: Path) -> None:
        """Test that error is returned for empty JSON files list."""
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        json_files: list[str] = []

        success, errors = verify_version_file_timestamp(str(version_file), json_files)

        assert success is False
        assert any("No JSON files" in err for err in errors)


class TestVerifyVersionFile:
    """Tests for verify_version_file function."""

    def test_verifies_valid_version_file(self, tmp_path: Path) -> None:
        """Test that valid version file passes verification."""
        # Create JSON metadata file
        json_file = tmp_path / "archive.json"
        data = cast(
            "list[dict[str, str | int]]",
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
            "list[dict[str, str | int]]",
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
            "list[dict[str, str | int]]",
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


class TestCollectFilesystemFiles:
    """Tests for collect_filesystem_files function."""

    def test_collects_regular_and_json_files(self, tmp_path: Path) -> None:
        """Test that function separates regular and JSON files."""
        # Create regular files
        file1 = tmp_path / "photo1.jpg"
        file1.write_text("content")
        file2 = tmp_path / "subdir" / "photo2.jpg"
        file2.parent.mkdir()
        file2.write_text("content")

        # Create JSON files
        json1 = tmp_path / "archive.json"
        json1.write_text("{}")
        json2 = tmp_path / "subdir" / "data.json"
        json2.write_text("{}")

        regular_files, json_files = collect_filesystem_files(str(tmp_path))

        assert str(file1) in regular_files
        assert str(file2) in regular_files
        assert str(json1) in json_files
        assert str(json2) in json_files
        assert len(regular_files) == 2
        assert len(json_files) == 2

    def test_handles_empty_directory(self, tmp_path: Path) -> None:
        """Test that function handles empty directory."""
        regular_files, json_files = collect_filesystem_files(str(tmp_path))

        assert len(regular_files) == 0
        assert len(json_files) == 0

    def test_excludes_directories(self, tmp_path: Path) -> None:
        """Test that function only collects files, not directories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        file1 = tmp_path / "file.txt"
        file1.write_text("content")

        regular_files, _ = collect_filesystem_files(str(tmp_path))

        assert str(file1) in regular_files
        assert str(subdir) not in regular_files
        assert len(regular_files) == 1


class TestCollectExpectedFiles:
    """Tests for collect_expected_files function."""

    def test_collects_paths_from_metadata(self) -> None:
        """Test that function extracts file paths from metadata."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "size": 100},
            {"path": "/archive/photo2.jpg", "size": 200},
            {"path": "/archive/subdir/photo3.jpg", "size": 300},
        ]

        expected_files = collect_expected_files(data)

        assert "/archive/photo1.jpg" in expected_files
        assert "/archive/photo2.jpg" in expected_files
        assert "/archive/subdir/photo3.jpg" in expected_files
        assert len(expected_files) == 3

    def test_handles_empty_metadata(self) -> None:
        """Test that function handles empty metadata list."""
        expected_files = collect_expected_files([])

        assert len(expected_files) == 0

    def test_skips_entries_without_path(self) -> None:
        """Test that function skips entries without path field."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "size": 100},
            {"size": 200},  # Missing path
            {"path": "/archive/photo2.jpg", "size": 300},
        ]

        expected_files = collect_expected_files(data)

        assert len(expected_files) == 2
        assert "/archive/photo1.jpg" in expected_files
        assert "/archive/photo2.jpg" in expected_files


class TestFindExtraFiles:
    """Tests for find_extra_files function."""

    def test_finds_no_extra_files_in_clean_archive(self, tmp_path: Path) -> None:
        """Test that function finds no extra files in clean archive."""
        # Create files
        file1 = tmp_path / "photo1.jpg"
        file1.write_text("content1")
        file2 = tmp_path / "photo2.jpg"
        file2.write_text("content2")

        # Create JSON metadata
        json_file = tmp_path / "archive.json"
        json_file.write_text("{}")

        # Create version file
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        metadata: list[dict[str, str | int]] = [
            {"path": str(file1), "size": 8},
            {"path": str(file2), "size": 8},
        ]

        extra_json, extra_regular, missing = find_extra_files(
            str(tmp_path), str(version_file), [str(json_file)], metadata
        )

        assert len(extra_json) == 0
        assert len(extra_regular) == 0
        assert len(missing) == 0

    def test_finds_extra_json_files(self, tmp_path: Path) -> None:
        """Test that function finds extra JSON files not in version file."""
        # Create files
        file1 = tmp_path / "photo.jpg"
        file1.write_text("content")

        # Create JSON files
        json_file = tmp_path / "archive.json"
        json_file.write_text("{}")
        extra_json_file = tmp_path / "extra.json"
        extra_json_file.write_text("{}")

        # Create version file
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        metadata: list[dict[str, str | int]] = [{"path": str(file1), "size": 7}]

        extra_json, extra_regular, missing = find_extra_files(
            str(tmp_path), str(version_file), [str(json_file)], metadata
        )

        assert str(extra_json_file) in extra_json
        assert len(extra_json) == 1
        assert len(extra_regular) == 0
        assert len(missing) == 0

    def test_finds_extra_regular_files(self, tmp_path: Path) -> None:
        """Test that function finds extra regular files not in metadata."""
        # Create files
        file1 = tmp_path / "photo.jpg"
        file1.write_text("content")
        extra_file = tmp_path / "extra.txt"
        extra_file.write_text("extra")

        # Create JSON metadata
        json_file = tmp_path / "archive.json"
        json_file.write_text("{}")

        # Create version file
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        metadata: list[dict[str, str | int]] = [{"path": str(file1), "size": 7}]

        extra_json, extra_regular, missing = find_extra_files(
            str(tmp_path), str(version_file), [str(json_file)], metadata
        )

        assert str(extra_file) in extra_regular
        assert len(extra_json) == 0
        assert len(extra_regular) == 1
        assert len(missing) == 0

    def test_finds_missing_files(self, tmp_path: Path) -> None:
        """Test that function finds files in metadata but missing from filesystem."""
        # Create only one file
        file1 = tmp_path / "photo1.jpg"
        file1.write_text("content")

        # Create JSON metadata
        json_file = tmp_path / "archive.json"
        json_file.write_text("{}")

        # Create version file
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        # Metadata includes missing file
        missing_file = tmp_path / "photo2.jpg"
        metadata: list[dict[str, str | int]] = [
            {"path": str(file1), "size": 7},
            {"path": str(missing_file), "size": 100},
        ]

        extra_json, extra_regular, missing = find_extra_files(
            str(tmp_path), str(version_file), [str(json_file)], metadata
        )

        assert str(missing_file) in missing
        assert len(extra_json) == 0
        assert len(extra_regular) == 0
        assert len(missing) == 1

    def test_handles_no_version_file(self, tmp_path: Path) -> None:
        """Test that function works without version file."""
        # Create files
        file1 = tmp_path / "photo.jpg"
        file1.write_text("content")

        # Create JSON metadata
        json_file = tmp_path / "archive.json"
        json_file.write_text("{}")

        metadata: list[dict[str, str | int]] = [{"path": str(file1), "size": 7}]

        extra_json, extra_regular, missing = find_extra_files(
            str(tmp_path), None, [str(json_file)], metadata
        )

        # JSON file should not be in extra since it's in the list
        assert len(extra_json) == 0
        assert len(extra_regular) == 0
        assert len(missing) == 0


class TestFindZeroByteFiles:
    """Tests for find_zero_byte_files function."""

    def test_finds_zero_byte_files(self) -> None:
        """Test that function finds files with zero bytes."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo.jpg", "size": 1024},
            {"path": "/archive/empty.txt", "size": 0},
            {"path": "/archive/another.jpg", "size": 2048},
            {"path": "/archive/empty2.dat", "size": 0},
        ]

        zero_files = find_zero_byte_files(data)

        assert len(zero_files) == 2
        assert "/archive/empty.txt" in zero_files
        assert "/archive/empty2.dat" in zero_files
        assert "/archive/photo.jpg" not in zero_files

    def test_handles_no_zero_byte_files(self) -> None:
        """Test that function returns empty list when no zero-byte files."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "size": 1024},
            {"path": "/archive/photo2.jpg", "size": 2048},
        ]

        zero_files = find_zero_byte_files(data)

        assert len(zero_files) == 0

    def test_handles_empty_metadata(self) -> None:
        """Test that function handles empty metadata list."""
        zero_files = find_zero_byte_files([])

        assert len(zero_files) == 0

    def test_skips_entries_without_path(self) -> None:
        """Test that function skips entries without path field."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo.jpg", "size": 1024},
            {"size": 0},  # Missing path
            {"path": "/archive/empty.txt", "size": 0},
        ]

        zero_files = find_zero_byte_files(data)

        assert len(zero_files) == 1
        assert "/archive/empty.txt" in zero_files


class TestFindDuplicateChecksums:
    """Tests for find_duplicate_checksums function."""

    def test_finds_sha1_duplicates(self) -> None:
        """Test that function finds duplicate SHA1 checksums."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "sha1": "abc123", "md5": "def456"},
            {"path": "/archive/photo2.jpg", "sha1": "abc123", "md5": "ghi789"},
            {"path": "/archive/photo3.jpg", "sha1": "xyz999", "md5": "uvw888"},
        ]

        sha1_dups, md5_dups = find_duplicate_checksums(data)

        assert len(sha1_dups) == 1
        assert "abc123" in sha1_dups
        assert len(sha1_dups["abc123"]) == 2
        assert "/archive/photo1.jpg" in sha1_dups["abc123"]
        assert "/archive/photo2.jpg" in sha1_dups["abc123"]
        assert len(md5_dups) == 0

    def test_finds_md5_duplicates(self) -> None:
        """Test that function finds duplicate MD5 checksums."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "sha1": "abc123", "md5": "same999"},
            {"path": "/archive/photo2.jpg", "sha1": "def456", "md5": "same999"},
            {"path": "/archive/photo3.jpg", "sha1": "xyz789", "md5": "diff888"},
        ]

        sha1_dups, md5_dups = find_duplicate_checksums(data)

        assert len(sha1_dups) == 0
        assert len(md5_dups) == 1
        assert "same999" in md5_dups
        assert len(md5_dups["same999"]) == 2
        assert "/archive/photo1.jpg" in md5_dups["same999"]
        assert "/archive/photo2.jpg" in md5_dups["same999"]

    def test_finds_both_sha1_and_md5_duplicates(self) -> None:
        """Test that function finds both SHA1 and MD5 duplicates."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "sha1": "dup1", "md5": "md5_1"},
            {"path": "/archive/photo2.jpg", "sha1": "dup1", "md5": "md5_1"},
            {"path": "/archive/photo3.jpg", "sha1": "dup2", "md5": "md5_2"},
            {"path": "/archive/photo4.jpg", "sha1": "dup2", "md5": "md5_2"},
        ]

        sha1_dups, md5_dups = find_duplicate_checksums(data)

        assert len(sha1_dups) == 2
        assert len(md5_dups) == 2

    def test_handles_no_duplicates(self) -> None:
        """Test that function returns empty dicts when no duplicates."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "sha1": "unique1", "md5": "md5_1"},
            {"path": "/archive/photo2.jpg", "sha1": "unique2", "md5": "md5_2"},
            {"path": "/archive/photo3.jpg", "sha1": "unique3", "md5": "md5_3"},
        ]

        sha1_dups, md5_dups = find_duplicate_checksums(data)

        assert len(sha1_dups) == 0
        assert len(md5_dups) == 0

    def test_handles_empty_metadata(self) -> None:
        """Test that function handles empty metadata list."""
        sha1_dups, md5_dups = find_duplicate_checksums([])

        assert len(sha1_dups) == 0
        assert len(md5_dups) == 0

    def test_handles_multiple_files_with_same_checksums(self) -> None:
        """Test that function handles more than 2 files with same checksum."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "sha1": "same", "md5": "md5_1"},
            {"path": "/archive/photo2.jpg", "sha1": "same", "md5": "md5_1"},
            {"path": "/archive/photo3.jpg", "sha1": "same", "md5": "md5_1"},
            {"path": "/archive/photo4.jpg", "sha1": "same", "md5": "md5_1"},
        ]

        sha1_dups, md5_dups = find_duplicate_checksums(data)

        assert len(sha1_dups) == 1
        assert len(sha1_dups["same"]) == 4
        assert len(md5_dups) == 1
        assert len(md5_dups["md5_1"]) == 4


class TestMain:
    """Tests for main function."""

    def test_verifies_valid_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main verifies valid archive without errors."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_content = b"Test image data"
        test_file.write_bytes(test_content)

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Create JSON file
        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": len(test_content),
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Scanning directory" in captured.out
        assert "Found 1 JSON metadata file(s)" in captured.out

    def test_verifies_with_all_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main verifies checksums with --all flag."""
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test data")

        sha1, md5 = calculate_checksums(str(test_file))

        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 9,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["verify.py", "--all", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "WARNING: Full checksum verification enabled" in captured.out

    def test_detects_missing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main detects missing files."""
        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(tmp_path / "missing.jpg"),
                "size": 100,
                "sha1": "abc",
                "md5": "def",
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == 1  # Should return error code
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_detects_checksum_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main detects checksum mismatches with --all."""
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Actual content")

        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 14,
                "sha1": "wrong_sha1_hash_1234567890123456789012",
                "md5": "wrong_md5_hash_12345678901234",
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["verify.py", "--all", str(tmp_path)])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "SHA-1 mismatch" in captured.err or "MD5 mismatch" in captured.err

    def test_verifies_timestamps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main verifies timestamps with --check-timestamps."""
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Content")

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Set specific timestamp
        target_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+0000").timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))
        # Also set directory timestamp
        os.utime(str(test_file.parent), (target_timestamp, target_timestamp))

        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 7,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))
        # Set JSON file timestamp too
        os.utime(str(json_file), (target_timestamp, target_timestamp))

        # Create version file with matching timestamp
        actual_hash = calculate_file_hash(str(json_file))
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "files": {"photos.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))
        os.utime(str(version_file), (target_timestamp, target_timestamp))

        monkeypatch.setattr("sys.argv", ["verify.py", "--check-timestamps", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Timestamp verification enabled" in captured.out

    def test_respects_tolerance_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that main respects --tolerance flag."""
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Content")

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Set timestamp that's off by 5 seconds from metadata
        target_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+0000").timestamp())
        actual_timestamp = target_timestamp + 5
        os.utime(str(test_file), (actual_timestamp, actual_timestamp))
        # Directory and JSON should match the actual file timestamp (newest file)
        os.utime(str(test_file.parent), (actual_timestamp, actual_timestamp))

        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 7,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))
        # JSON file should match actual file timestamp too
        os.utime(str(json_file), (actual_timestamp, actual_timestamp))

        # Create version file with matching timestamp
        actual_hash = calculate_file_hash(str(json_file))
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "files": {"photos.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))
        os.utime(str(version_file), (actual_timestamp, actual_timestamp))

        # With tolerance of 10, should pass (file is 5 seconds off but within tolerance)
        monkeypatch.setattr(
            "sys.argv", ["verify.py", "--check-timestamps", "--tolerance", "10", str(tmp_path)]
        )

        exit_code = main()

        assert exit_code == 0

    def test_verifies_version_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main verifies .version.json file."""
        # Create real test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test content")

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Create JSON metadata file with real file data
        json_file = tmp_path / "archive.json"
        data = [
            {
                "path": str(test_file),
                "size": 12,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))

        # Calculate actual hash of JSON file
        actual_hash = calculate_file_hash(str(json_file))

        # Create version file
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 12,
            "file_count": 1,
            "files": {"archive.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Found version file" in captured.out
        assert "Version file verified successfully" in captured.out

    def test_requires_version_file_with_check_timestamps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main reports error when .version.json missing with --check-timestamps."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test content")

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Set specific timestamp
        target_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+0000").timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))
        os.utime(str(test_file.parent), (target_timestamp, target_timestamp))

        # Create JSON file (but no .version.json)
        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 12,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))
        os.utime(str(json_file), (target_timestamp, target_timestamp))

        monkeypatch.setattr("sys.argv", ["verify.py", "--check-timestamps", str(tmp_path)])

        exit_code = main()

        # Should fail because .version.json is missing
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Version file (.version.json) not found" in captured.err

    def test_verifies_version_file_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main verifies .version.json timestamp with --check-timestamps."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test content")

        # Calculate actual checksums
        sha1, md5 = calculate_checksums(str(test_file))

        # Set specific timestamp
        target_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+0000").timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))
        os.utime(str(test_file.parent), (target_timestamp, target_timestamp))

        # Create JSON file
        json_file = tmp_path / "photos.json"
        data = [
            {
                "path": str(test_file),
                "size": 12,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+0000",
            }
        ]
        json_file.write_text(json.dumps(data))
        os.utime(str(json_file), (target_timestamp, target_timestamp))

        # Calculate actual hash of JSON file
        actual_hash = calculate_file_hash(str(json_file))

        # Create version file with matching timestamp
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 12,
            "file_count": 1,
            "files": {"photos.json": actual_hash},
        }
        version_file.write_text(json.dumps(version_data))
        # Set version file timestamp to match JSON file
        os.utime(str(version_file), (target_timestamp, target_timestamp))

        monkeypatch.setattr("sys.argv", ["verify.py", "--check-timestamps", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Verifying version file timestamp" in captured.out
        assert "Version file timestamp OK" in captured.out

    def test_exits_with_error_for_nonexistent_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error for nonexistent directory."""
        monkeypatch.setattr("sys.argv", ["verify.py", "/nonexistent/directory"])

        with pytest.raises(SystemExit, match="does not exist or is not readable"):
            main()

    def test_exits_with_error_for_empty_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main exits with error when no JSON files found."""
        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_processes_multiple_json_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main processes multiple JSON files."""
        # Create first file
        file1 = tmp_path / "photos1" / "test1.jpg"
        file1.parent.mkdir()
        file1.write_bytes(b"Content1")

        # Create second file
        file2 = tmp_path / "photos2" / "test2.jpg"
        file2.parent.mkdir()
        file2.write_bytes(b"Content2")

        # Create JSON files
        sha1_1, md5_1 = calculate_checksums(str(file1))
        json1 = tmp_path / "archive1.json"
        json1.write_text(
            json.dumps(
                [
                    {
                        "path": str(file1),
                        "size": 8,
                        "sha1": sha1_1,
                        "md5": md5_1,
                        "date": "2024-01-01T12:00:00+0000",
                    }
                ]
            )
        )

        sha1_2, md5_2 = calculate_checksums(str(file2))
        json2 = tmp_path / "archive2.json"
        json2.write_text(
            json.dumps(
                [
                    {
                        "path": str(file2),
                        "size": 8,
                        "sha1": sha1_2,
                        "md5": md5_2,
                        "date": "2024-01-02T12:00:00+0000",
                    }
                ]
            )
        )

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Found 2 JSON metadata file(s)" in captured.out
        assert "archive1.json" in captured.out
        assert "archive2.json" in captured.out

    def test_check_extra_files_requires_version_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --check-extra-files requires .version.json file."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        # Create JSON metadata
        sha1, md5 = calculate_checksums(str(test_file))
        json_file = tmp_path / "archive.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "path": str(test_file),
                        "size": 4,
                        "sha1": sha1,
                        "md5": md5,
                        "date": "2024-01-01T12:00:00+0000",
                    }
                ]
            )
        )

        # No version file

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path), "--check-extra-files"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Version file (.version.json) not found" in captured.err
        assert "Extra files check requires .version.json file" in captured.err

    def test_check_extra_files_finds_clean_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --check-extra-files reports clean archive."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        # Create JSON metadata
        sha1, md5 = calculate_checksums(str(test_file))
        json_file = tmp_path / "archive.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "path": str(test_file),
                        "size": 4,
                        "sha1": sha1,
                        "md5": md5,
                        "date": "2024-01-01T12:00:00+0000",
                    }
                ]
            )
        )

        # Create version file
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 4,
            "file_count": 1,
            "last_modified": "2024-01-01T12:00:00+0000",
            "files": {json_file.name: calculate_file_hash(str(json_file))},
        }
        version_file.write_text(json.dumps(version_data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path), "--check-extra-files"])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No extra or missing files found - archive is clean" in captured.out

    def test_check_extra_files_finds_extra_json_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --check-extra-files detects extra JSON files."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        # Create JSON metadata
        sha1, md5 = calculate_checksums(str(test_file))
        json_file = tmp_path / "archive.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "path": str(test_file),
                        "size": 4,
                        "sha1": sha1,
                        "md5": md5,
                        "date": "2024-01-01T12:00:00+0000",
                    }
                ]
            )
        )

        # Create extra JSON file
        extra_json = tmp_path / "extra.json"
        extra_json.write_text("{}")

        # Create version file (without extra.json)
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 4,
            "file_count": 1,
            "last_modified": "2024-01-01T12:00:00+0000",
            "files": {json_file.name: calculate_file_hash(str(json_file))},
        }
        version_file.write_text(json.dumps(version_data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path), "--check-extra-files"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "extra JSON file(s) not in .version.json" in captured.out
        assert "extra.json" in captured.err

    def test_check_extra_files_finds_extra_regular_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --check-extra-files detects extra regular files."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        # Create extra file
        extra_file = tmp_path / "photos" / "extra.txt"
        extra_file.write_text("extra")

        # Create JSON metadata (without extra file)
        sha1, md5 = calculate_checksums(str(test_file))
        json_file = tmp_path / "archive.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "path": str(test_file),
                        "size": 4,
                        "sha1": sha1,
                        "md5": md5,
                        "date": "2024-01-01T12:00:00+0000",
                    }
                ]
            )
        )

        # Create version file
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 4,
            "file_count": 1,
            "last_modified": "2024-01-01T12:00:00+0000",
            "files": {json_file.name: calculate_file_hash(str(json_file))},
        }
        version_file.write_text(json.dumps(version_data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path), "--check-extra-files"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "extra file(s) not in metadata" in captured.out
        assert "extra.txt" in captured.err

    def test_check_extra_files_finds_missing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --check-extra-files detects missing files."""
        # Create test file
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        # Create JSON metadata with extra file that doesn't exist
        sha1, md5 = calculate_checksums(str(test_file))
        missing_file = tmp_path / "photos" / "missing.jpg"
        json_file = tmp_path / "archive.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "path": str(test_file),
                        "size": 4,
                        "sha1": sha1,
                        "md5": md5,
                        "date": "2024-01-01T12:00:00+0000",
                    },
                    {
                        "path": str(missing_file),
                        "size": 100,
                        "sha1": "a" * 40,
                        "md5": "b" * 32,
                        "date": "2024-01-02T12:00:00+0000",
                    },
                ]
            )
        )

        # Create version file
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-2",
            "total_bytes": 104,
            "file_count": 2,
            "last_modified": "2024-01-02T12:00:00+0000",
            "files": {json_file.name: calculate_file_hash(str(json_file))},
        }
        version_file.write_text(json.dumps(version_data))

        monkeypatch.setattr("sys.argv", ["verify.py", str(tmp_path), "--check-extra-files"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "missing file(s) from filesystem" in captured.out
        assert "missing.jpg" in captured.err
