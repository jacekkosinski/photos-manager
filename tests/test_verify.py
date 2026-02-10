"""Tests for verify module."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from photos_manager.common import (
    calculate_checksums_strict as calculate_checksums,
)
from photos_manager.common import (
    find_json_files,
)
from photos_manager.verify import (
    calculate_file_hash,
    collect_expected_files,
    collect_filesystem_files,
    find_duplicate_checksums,
    find_extra_files,
    find_invalid_dates,
    find_version_file,
    find_zero_byte_files,
    load_version_json,
    normalize_paths,
    run,
    validate_date_format,
    validate_version_file_dates,
    verify_archive_directory_timestamp,
    verify_directory_timestamps,
    verify_file_entry,
    verify_json_file_timestamp,
    verify_permissions,
    verify_timestamps,
    verify_version_file,
    verify_version_file_timestamp,
)


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
        with pytest.raises(SystemExit, match="No JSON files found"):
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
        """Test that SHA1 mismatch is detected."""
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
        assert any("SHA1 mismatch" in err for err in errors)
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
            {"path": str(test_file), "date": "2020-01-01T00:00:00+00:00"},
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
        target_date = "2024-01-01T12:00:00+00:00"
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
        file_timestamp = int(datetime.fromisoformat("2024-01-01T12:00:00+00:00").timestamp())
        dir_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+00:00").timestamp())

        os.utime(str(test_file), (file_timestamp, file_timestamp))
        os.utime(str(subdir), (dir_timestamp, dir_timestamp))

        data = cast(
            "list[dict[str, str | int]]",
            [{"path": str(test_file), "date": "2024-01-01T12:00:00+00:00"}],
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
        old_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+00:00").timestamp())
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
        old_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+00:00").timestamp())
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


class TestVerifyArchiveDirectoryTimestamp:
    """Tests for verify_archive_directory_timestamp function."""

    def test_verifies_archive_directory_timestamp(self, tmp_path: Path) -> None:
        """Test that archive directory timestamp is verified correctly."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        json_file1 = archive_dir / "archive1.json"
        json_file1.write_text("[]")

        json_file2 = archive_dir / "archive2.json"
        json_file2.write_text("[]")

        # Set directory timestamp to match newest JSON file
        target_timestamp = int(json_file2.stat().st_mtime)
        os.utime(str(archive_dir), (target_timestamp, target_timestamp))

        json_files = [str(json_file1), str(json_file2)]

        success, errors = verify_archive_directory_timestamp(str(archive_dir), json_files)

        assert success is True
        assert len(errors) == 0

    def test_detects_archive_directory_timestamp_mismatch(self, tmp_path: Path) -> None:
        """Test that archive directory timestamp mismatch is detected."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        json_file = archive_dir / "archive.json"
        json_file.write_text("[]")

        # Set very different timestamp on directory
        old_timestamp = int(datetime.fromisoformat("2020-01-01T00:00:00+00:00").timestamp())
        os.utime(str(archive_dir), (old_timestamp, old_timestamp))

        json_files = [str(json_file)]

        success, errors = verify_archive_directory_timestamp(str(archive_dir), json_files)

        assert success is False
        assert any("timestamp mismatch" in err for err in errors)

    def test_handles_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test that error is returned for nonexistent directory."""
        archive_dir = tmp_path / "archive"

        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        json_files = [str(json_file)]

        success, errors = verify_archive_directory_timestamp(str(archive_dir), json_files)

        assert success is False
        assert any("not found" in err for err in errors)

    def test_handles_path_is_not_directory(self, tmp_path: Path) -> None:
        """Test that error is returned when path is not a directory."""
        # Create a file instead of a directory
        archive_file = tmp_path / "archive.txt"
        archive_file.write_text("not a directory")

        json_file = tmp_path / "archive.json"
        json_file.write_text("[]")

        json_files = [str(json_file)]

        success, errors = verify_archive_directory_timestamp(str(archive_file), json_files)

        assert success is False
        assert any("not a directory" in err for err in errors)

    def test_handles_empty_json_files_list(self, tmp_path: Path) -> None:
        """Test that error is returned for empty JSON files list."""
        archive_dir = tmp_path / "archive"
        archive_dir.mkdir()

        json_files: list[str] = []

        success, errors = verify_archive_directory_timestamp(str(archive_dir), json_files)

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


class TestValidateDateFormat:
    """Tests for validate_date_format function."""

    def test_valid_date_with_colon_timezone(self) -> None:
        """Test that function accepts valid ISO 8601 date with colon in timezone."""
        is_valid, error = validate_date_format("2024-01-01T12:00:00+02:00")
        assert is_valid is True
        assert error is None

    def test_valid_date_with_negative_timezone(self) -> None:
        """Test that function accepts valid date with negative timezone."""
        is_valid, error = validate_date_format("2024-01-01T12:00:00-05:00")
        assert is_valid is True
        assert error is None

    def test_valid_date_with_utc_z(self) -> None:
        """Test that function accepts valid date with Z (UTC) timezone."""
        is_valid, error = validate_date_format("2024-01-01T12:00:00Z")
        assert is_valid is True
        assert error is None

    def test_invalid_date_without_colon_in_timezone(self) -> None:
        """Test that function rejects date without colon in timezone."""
        is_valid, error = validate_date_format("2024-01-01T12:00:00+0200")
        assert is_valid is False
        assert error is not None
        assert "colon" in error

    def test_invalid_date_without_timezone(self) -> None:
        """Test that function rejects date without timezone."""
        is_valid, error = validate_date_format("2024-01-01T12:00:00")
        assert is_valid is False
        assert error is not None

    def test_invalid_date_format(self) -> None:
        """Test that function rejects invalid date format."""
        is_valid, error = validate_date_format("not-a-date")
        assert is_valid is False
        assert error is not None
        assert "ISO 8601" in error

    def test_invalid_date_without_t_separator(self) -> None:
        """Test that function rejects date without T separator between date and time."""
        is_valid, error = validate_date_format("2024-01-01 12:00:00+02:00")
        assert is_valid is False
        assert error is not None
        assert "T" in error


class TestFindInvalidDates:
    """Tests for find_invalid_dates function."""

    def test_finds_invalid_dates(self) -> None:
        """Test that function finds files with invalid date formats."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "date": "2024-01-01T12:00:00+02:00"},
            {"path": "/archive/photo2.jpg", "date": "2024-01-01T12:00:00+0200"},
            {"path": "/archive/photo3.jpg", "date": "2024-01-01T12:00:00-05:00"},
        ]

        invalid = find_invalid_dates(data)

        assert len(invalid) == 1
        assert "/archive/photo2.jpg" in invalid
        assert len(invalid["/archive/photo2.jpg"]) == 1
        assert "colon" in invalid["/archive/photo2.jpg"][0][1]

    def test_handles_all_valid_dates(self) -> None:
        """Test that function returns empty dict when all dates are valid."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "date": "2024-01-01T12:00:00+02:00"},
            {"path": "/archive/photo2.jpg", "date": "2024-01-01T12:00:00Z"},
            {"path": "/archive/photo3.jpg", "date": "2024-01-01T12:00:00-05:00"},
        ]

        invalid = find_invalid_dates(data)

        assert len(invalid) == 0

    def test_handles_empty_metadata(self) -> None:
        """Test that function handles empty metadata list."""
        invalid = find_invalid_dates([])
        assert len(invalid) == 0

    def test_skips_entries_without_date(self) -> None:
        """Test that function skips entries without date field."""
        data: list[dict[str, str | int]] = [
            {"path": "/archive/photo1.jpg", "date": "2024-01-01T12:00:00+02:00"},
            {"path": "/archive/photo2.jpg"},  # Missing date
        ]

        invalid = find_invalid_dates(data)

        assert len(invalid) == 0


class TestValidateVersionFileDates:
    """Tests for validate_version_file_dates function."""

    def test_validates_valid_version_file(self, tmp_path: Path) -> None:
        """Test that function accepts valid dates in version file."""
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 1024,
            "file_count": 1,
            "last_modified": "2024-01-01T12:00:00+02:00",
            "last_verified": "2024-01-02T12:00:00+02:00",
            "files": {},
        }
        version_file.write_text(json.dumps(version_data))

        errors = validate_version_file_dates(str(version_file))

        assert len(errors) == 0

    def test_finds_invalid_last_modified(self, tmp_path: Path) -> None:
        """Test that function finds invalid last_modified date."""
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 1024,
            "file_count": 1,
            "last_modified": "2024-01-01T12:00:00+0200",
            "files": {},
        }
        version_file.write_text(json.dumps(version_data))

        errors = validate_version_file_dates(str(version_file))

        assert len(errors) == 1
        assert errors[0][0] == "last_modified"
        assert "colon" in errors[0][2]

    def test_finds_invalid_last_verified(self, tmp_path: Path) -> None:
        """Test that function finds invalid last_verified date."""
        version_file = tmp_path / ".version.json"
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 1024,
            "file_count": 1,
            "last_verified": "2024-01-02T12:00:00+0200",
            "files": {},
        }
        version_file.write_text(json.dumps(version_data))

        errors = validate_version_file_dates(str(version_file))

        assert len(errors) == 1
        assert errors[0][0] == "last_verified"

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that function handles nonexistent version file."""
        version_file = tmp_path / ".version.json"

        errors = validate_version_file_dates(str(version_file))

        assert len(errors) == 0


class TestVerifyPermissions:
    """Tests for verify_permissions function."""

    def test_correct_permissions_and_ownership(self, tmp_path: Path) -> None:
        """Test that correct permissions and ownership return no errors."""
        # Create test structure
        test_file = tmp_path / "photos" / "test.jpg"
        test_file.parent.mkdir()
        test_file.write_bytes(b"Test")

        json_file = tmp_path / "archive.json"
        sha1, md5 = calculate_checksums(str(test_file))
        data: list[dict[str, str | int]] = [
            {
                "path": str(test_file),
                "size": 4,
                "sha1": sha1,
                "md5": md5,
                "date": "2024-01-01T12:00:00+00:00",
            }
        ]
        json_file.write_text(json.dumps(data))

        # Set correct permissions
        test_file.chmod(0o644)
        test_file.parent.chmod(0o755)
        json_file.chmod(0o644)
        tmp_path.chmod(0o755)

        # Get current user and group
        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        errors = verify_permissions(
            str(tmp_path), [str(json_file)], None, data, current_user, current_group
        )

        assert errors == {}

    def test_detects_incorrect_file_permissions(self, tmp_path: Path) -> None:
        """Test that incorrect file permissions are detected."""
        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"Test")

        # Set incorrect permissions (755 instead of 644)
        test_file.chmod(0o755)

        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        data: list[dict[str, str | int]] = [
            {"path": str(test_file), "size": 4, "sha1": "abc", "md5": "def"}
        ]

        errors = verify_permissions(str(tmp_path), [], None, data, current_user, current_group)

        assert str(test_file) in errors
        assert any(issue_type == "permissions" for issue_type, _ in errors[str(test_file)])

    def test_detects_incorrect_directory_permissions(self, tmp_path: Path) -> None:
        """Test that incorrect directory permissions are detected."""
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "test.jpg"
        test_file.write_bytes(b"Test")

        # Set permissions - file first, then directory
        test_file.chmod(0o644)
        # Set incorrect directory permissions (644 instead of 755)
        test_dir.chmod(0o644)

        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        data: list[dict[str, str | int]] = [
            {"path": str(test_file), "size": 4, "sha1": "abc", "md5": "def"}
        ]

        errors = verify_permissions(str(tmp_path), [], None, data, current_user, current_group)

        # Restore permissions for cleanup
        test_dir.chmod(0o755)

        assert str(test_dir) in errors
        assert any(issue_type == "permissions" for issue_type, _ in errors[str(test_dir)])

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that nonexistent files are handled gracefully."""
        # Create subdirectory with correct permissions
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        photos_dir.chmod(0o755)
        tmp_path.chmod(0o755)

        nonexistent = photos_dir / "nonexistent.jpg"

        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        data: list[dict[str, str | int]] = [
            {"path": str(nonexistent), "size": 4, "sha1": "abc", "md5": "def"}
        ]

        errors = verify_permissions(str(tmp_path), [], None, data, current_user, current_group)

        # Nonexistent files should not generate errors (just skipped)
        assert errors == {}

    def test_checks_version_file_permissions(self, tmp_path: Path) -> None:
        """Test that version file permissions are checked."""
        version_file = tmp_path / ".version.json"
        version_file.write_text(json.dumps({"version": "test"}))

        # Set incorrect permissions
        version_file.chmod(0o755)

        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        errors = verify_permissions(
            str(tmp_path), [], str(version_file), [], current_user, current_group
        )

        assert str(version_file) in errors
        assert any(issue_type == "permissions" for issue_type, _ in errors[str(version_file)])

    def test_checks_json_file_permissions(self, tmp_path: Path) -> None:
        """Test that JSON file permissions are checked."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps([]))

        # Set incorrect permissions
        json_file.chmod(0o600)

        import grp
        import pwd

        current_uid = os.getuid()
        current_gid = os.getgid()
        current_user = pwd.getpwuid(current_uid).pw_name
        current_group = grp.getgrgid(current_gid).gr_name

        errors = verify_permissions(
            str(tmp_path), [str(json_file)], None, [], current_user, current_group
        )

        assert str(json_file) in errors
        assert any(issue_type == "permissions" for issue_type, _ in errors[str(json_file)])


class TestNormalizePaths:
    """Tests for normalize_paths function."""

    def test_converts_relative_paths_to_absolute(self, tmp_path: Path) -> None:
        """Test that relative paths are converted to absolute paths."""
        data: list[dict[str, str | int]] = [
            {"path": "photos/img1.jpg", "size": 100},
            {"path": "photos/img2.jpg", "size": 200},
        ]

        result = normalize_paths(data, str(tmp_path))

        assert Path(str(result[0]["path"])).is_absolute()
        assert Path(str(result[1]["path"])).is_absolute()
        assert str(result[0]["path"]) == str(tmp_path / "photos/img1.jpg")
        assert str(result[1]["path"]) == str(tmp_path / "photos/img2.jpg")

    def test_preserves_absolute_paths(self, tmp_path: Path) -> None:
        """Test that absolute paths are not modified."""
        abs_path1 = str(tmp_path / "photos/img1.jpg")
        abs_path2 = str(tmp_path / "photos/img2.jpg")

        data: list[dict[str, str | int]] = [
            {"path": abs_path1, "size": 100},
            {"path": abs_path2, "size": 200},
        ]

        result = normalize_paths(data, str(tmp_path))

        assert str(result[0]["path"]) == abs_path1
        assert str(result[1]["path"]) == abs_path2

    def test_handles_empty_data(self, tmp_path: Path) -> None:
        """Test that empty data is handled correctly."""
        data: list[dict[str, str | int]] = []

        result = normalize_paths(data, str(tmp_path))

        assert result == []

    def test_handles_entries_without_path(self, tmp_path: Path) -> None:
        """Test that entries without path field are handled gracefully."""
        data: list[dict[str, str | int]] = [
            {"size": 100},
            {"path": "photos/img.jpg", "size": 200},
        ]

        result = normalize_paths(data, str(tmp_path))

        assert "path" not in result[0]
        assert Path(str(result[1]["path"])).is_absolute()

    def test_resolves_paths_correctly(self, tmp_path: Path) -> None:
        """Test that paths are resolved relative to base directory."""
        base_dir = tmp_path / "archive"
        base_dir.mkdir()

        data: list[dict[str, str | int]] = [
            {"path": "subdir/file.jpg", "size": 100},
        ]

        result = normalize_paths(data, str(base_dir))

        expected_path = base_dir / "subdir/file.jpg"
        assert str(result[0]["path"]) == str(expected_path)


class TestRun:
    """Integration tests for run() function."""

    def test_run_verifies_basic_archive(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() verifies a basic archive successfully."""
        import argparse

        # Create test files
        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Create JSON with metadata
        sha1, md5 = calculate_checksums(str(test_file))
        mtime = test_file.stat().st_mtime
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": datetime.fromtimestamp(mtime).astimezone().isoformat(),
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "verified successfully" in captured.out.lower() or "ok" in captured.out.lower()

    def test_run_detects_missing_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects missing files."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        # Create JSON with non-existent file
        data = [
            {
                "path": str(test_dir / "missing.txt"),
                "sha1": "abc",
                "md5": "def",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 10,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "missing" in captured.out.lower() or "not found" in captured.out.lower()

    def test_run_with_all_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run() with --all verifies checksums."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Create JSON with correct checksums
        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=True,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_detects_size_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects file size mismatches."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Create JSON with wrong size
        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 999,  # Wrong size
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "size" in captured.out.lower()

    def test_run_with_version_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() verifies version file if present."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Create JSON
        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "last_modified": "2025-01-01T00:00:00+00:00",
            "last_verified": "2025-01-01T00:00:00+00:00",
            "files": {"archive.json": calculate_file_hash(str(json_file))},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_check_timestamps(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() with --check-timestamps verifies mtimes."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Get actual file timestamp
        mtime = test_file.stat().st_mtime
        timestamp = datetime.fromtimestamp(mtime).astimezone().isoformat()

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": timestamp,
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file (required for timestamp verification)
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "last_modified": timestamp,
            "last_verified": timestamp,
            "files": {"archive.json": calculate_file_hash(str(json_file))},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=True,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_nonexistent_directory(self) -> None:
        """Test that run() handles nonexistent directory."""
        import argparse

        args = argparse.Namespace(
            directory="/nonexistent/directory",
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "does not exist" in str(exc_info.value).lower()

    def test_run_with_verbose_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() with --verbose shows detailed output."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("test")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 4,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=True,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_quiet_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run() with --quiet suppresses normal output."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("test")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 4,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=True,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_empty_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run() handles empty JSON files."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        # Create empty JSON
        json_file = test_dir / "archive.json"
        json_file.write_text("[]")

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_check_extra_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() with --check-extra-files detects extra files."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        # Create a documented file
        test_file = test_dir / "documented.txt"
        test_file.write_text("documented")

        # Create an extra file not in JSON
        extra_file = test_dir / "extra.txt"
        extra_file.write_text("extra")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 11,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=True,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should detect extra file
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "extra" in captured.out.lower()

    def test_run_multiple_json_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() processes multiple JSON metadata files."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        # Create files for first JSON
        file1 = test_dir / "file1.txt"
        file1.write_text("content1")

        # Create files for second JSON
        file2 = test_dir / "file2.txt"
        file2.write_text("content2")

        # Create first JSON
        sha1_1, md5_1 = calculate_checksums(str(file1))
        data1 = [
            {
                "path": str(file1),
                "sha1": sha1_1,
                "md5": md5_1,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 8,
            }
        ]
        (test_dir / "metadata1.json").write_text(json.dumps(data1))

        # Create second JSON
        sha1_2, md5_2 = calculate_checksums(str(file2))
        data2 = [
            {
                "path": str(file2),
                "sha1": sha1_2,
                "md5": md5_2,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 8,
            }
        ]
        (test_dir / "metadata2.json").write_text(json.dumps(data2))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "metadata1.json" in captured.out or "2" in captured.out

    def test_run_detects_checksum_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() with --all detects checksum mismatches."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("wrong content")

        # Create JSON with different checksums
        data = [
            {
                "path": str(test_file),
                "sha1": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "md5": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 13,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=True,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "sha1" in captured.out.lower() or "checksum" in captured.out.lower()

    def test_run_detects_timestamp_errors_with_version_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects timestamp mismatches when checking timestamps."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Set file timestamp to long time ago
        old_time = datetime.now().timestamp() - 86400  # 1 day ago
        os.utime(test_file, (old_time, old_time))

        # Create JSON with recent timestamp (mismatch)
        recent_time = datetime.now().astimezone().isoformat()
        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": recent_time,
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file (required for timestamp checks)
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "last_modified": recent_time,
            "last_verified": recent_time,
            "files": {"archive.json": calculate_file_hash(str(json_file))},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=True,
            tolerance=1,  # 1 second tolerance won't be enough
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should detect timestamp mismatch
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "timestamp" in captured.err.lower() or "mtime" in captured.err.lower()

    def test_run_with_check_timestamps_but_no_version_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() reports error when checking timestamps without version file."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # No version file created

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=True,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should report error about missing version file
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "version file" in captured.err.lower() and "not found" in captured.err.lower()

    def test_run_detects_multiple_extra_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects extra JSON files, regular files, and missing files."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        # Create documented file
        documented = test_dir / "documented.txt"
        documented.write_text("doc")

        # Create extra regular file
        extra_regular = test_dir / "extra.txt"
        extra_regular.write_text("extra")

        # Document only one file
        sha1, md5 = calculate_checksums(str(documented))
        data = [
            {
                "path": str(documented),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 3,
            },
            # Add a missing file that's in metadata but not on disk
            {
                "path": str(test_dir / "missing.txt"),
                "sha1": "missing_sha1",
                "md5": "missing_md5",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 10,
            },
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file
        version_data = {
            "version": "photos-0.000-2",
            "total_bytes": 13,
            "file_count": 2,
            "last_modified": "2025-01-01T00:00:00+00:00",
            "last_verified": "2025-01-01T00:00:00+00:00",
            "files": {"archive.json": calculate_file_hash(str(json_file))},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        # Create extra JSON file not in version
        extra_json = test_dir / "extra_metadata.json"
        extra_json.write_text("[]")

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=True,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should detect all three types of issues
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "extra" in output.lower()
        assert "missing" in output.lower()

    def test_run_with_check_extra_files_but_no_version_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() reports error when checking extra files without version file."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # No version file

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=True,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should report error about missing version file
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "version file" in captured.err.lower() and "not found" in captured.err.lower()

    def test_run_detects_version_file_hash_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects when JSON file hash doesn't match version file."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file with WRONG hash
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 7,
            "file_count": 1,
            "last_modified": "2025-01-01T00:00:00+00:00",
            "last_verified": "2025-01-01T00:00:00+00:00",
            "files": {"archive.json": "wrong_hash_value_here"},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should detect hash mismatch
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        assert "hash" in captured.err.lower() or "mismatch" in captured.err.lower()

    def test_run_detects_version_file_totals_mismatch(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() detects when totals in version file don't match actual data."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        # Create version file with WRONG totals
        version_data = {
            "version": "photos-0.000-1",
            "total_bytes": 999,  # Wrong!
            "file_count": 99,  # Wrong!
            "last_modified": "2025-01-01T00:00:00+00:00",
            "last_verified": "2025-01-01T00:00:00+00:00",
            "files": {"archive.json": calculate_file_hash(str(json_file))},
        }
        version_file = test_dir / ".version.json"
        version_file.write_text(json.dumps(version_data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=False,
            owner=None,
            group=None,
        )

        exit_code = run(args)

        # Should detect totals mismatch
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "bytes mismatch" in output.lower() or "count mismatch" in output.lower()

    def test_run_with_check_permissions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() with --check-permissions verifies file permissions."""
        import argparse

        test_dir = tmp_path / "archive"
        test_dir.mkdir()

        test_file = test_dir / "file.txt"
        test_file.write_text("content")

        # Set wrong permissions (not 644)
        test_file.chmod(0o600)

        sha1, md5 = calculate_checksums(str(test_file))
        data = [
            {
                "path": str(test_file),
                "sha1": sha1,
                "md5": md5,
                "date": "2025-01-01T00:00:00+00:00",
                "size": 7,
            }
        ]
        json_file = test_dir / "archive.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(
            directory=str(test_dir),
            all=False,
            check_timestamps=False,
            tolerance=2,
            verbose=False,
            quiet=False,
            check_extra_files=False,
            check_permissions=True,
            owner="nonexistent_user",
            group="nonexistent_group",
        )

        exit_code = run(args)

        # Should detect permission/ownership issues
        # (will fail both on permissions and ownership)
        assert exit_code != os.EX_OK
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert (
            "permission" in output.lower()
            or "ownership" in output.lower()
            or "owner" in output.lower()
        )
