"""Tests for photos_manager.common module."""

import json
import os
import time
from pathlib import Path

import pytest

from photos_manager.common import (
    CHUNK_SIZE,
    calculate_checksums,
    calculate_checksums_strict,
    find_json_files,
    find_json_files_with_mtime,
    find_version_file,
    format_count,
    load_metadata_json,
    resolve_group_name,
    resolve_owner_name,
    validate_directory,
    write_manifest_json,
    write_metadata_json,
)

_ENTRY: dict[str, str | int] = {
    "path": "/test/file.jpg",
    "sha1": "aabbcc",
    "md5": "ddeeff",
    "date": "2024-01-01T00:00:00+00:00",
    "size": 100,
}


@pytest.mark.unit
class TestLoadMetadataJson:
    """Tests for load_metadata_json function."""

    def test_valid_json_file(self, tmp_path: Path) -> None:
        """Test loading valid JSON file."""
        json_file = tmp_path / "test.json"
        data = [
            {**_ENTRY, "path": "/test/file1.jpg", "size": 100},
            {**_ENTRY, "path": "/test/file2.jpg", "size": 200},
        ]
        json_file.write_text(json.dumps(data), encoding="utf-8")

        result = load_metadata_json(str(json_file))
        assert result == data

    def test_nonexistent_file_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that nonexistent file raises SystemExit."""
        nonexistent = tmp_path / "nonexistent.json"

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(nonexistent))

        assert "does not exist" in str(exc_info.value)

    def test_invalid_json_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that invalid JSON raises SystemExit."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("{invalid json}", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(json_file))

        assert "Invalid JSON" in str(exc_info.value)

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test that empty file raises SystemExit."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(json_file))

        assert "Invalid JSON" in str(exc_info.value)

    def test_non_array_json_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that JSON object (not array) raises SystemExit."""
        json_file = tmp_path / "object.json"
        json_file.write_text('{"key": "value"}', encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(json_file))

        assert "does not contain a JSON array" in str(exc_info.value)

    def test_directory_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that passing a directory raises SystemExit."""
        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(tmp_path))

        assert "is not a file" in str(exc_info.value)

    def test_entry_not_dict_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that non-dict entry raises SystemExit."""
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(["not", "dicts"]), encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(json_file))

        assert "array of objects" in str(exc_info.value)

    def test_entry_missing_keys_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that entry missing required keys raises SystemExit."""
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps([{"path": "/x.jpg", "size": 1}]), encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_metadata_json(str(json_file))

        assert "missing required keys" in str(exc_info.value)


@pytest.mark.unit
class TestWriteMetadataJson:
    """Tests for write_metadata_json function."""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        """Test that JSON file is written with correct content."""
        output = tmp_path / "out.json"
        data = [_ENTRY]

        write_metadata_json(str(output), data)

        result = json.loads(output.read_text())
        assert result == [_ENTRY]

    def test_normalises_key_order(self, tmp_path: Path) -> None:
        """Test that keys are written in canonical order."""
        output = tmp_path / "out.json"
        shuffled: dict[str, str | int] = {
            "size": 100,
            "md5": "dd",
            "path": "/f",
            "sha1": "aa",
            "date": "2024-01-01T00:00:00+00:00",
        }

        write_metadata_json(str(output), [shuffled])

        text = output.read_text()
        keys = [line.strip().split(":")[0].strip('"') for line in text.splitlines() if ":" in line]
        assert keys == ["path", "sha1", "md5", "date", "size"]

    def test_sets_644_permissions(self, tmp_path: Path) -> None:
        """Test that output file has 644 permissions."""
        output = tmp_path / "out.json"

        write_metadata_json(str(output), [_ENTRY])

        mode = output.stat().st_mode & 0o777
        assert mode == 0o644

    def test_trailing_newline(self, tmp_path: Path) -> None:
        """Test that file ends with a newline."""
        output = tmp_path / "out.json"

        write_metadata_json(str(output), [_ENTRY])

        assert output.read_text().endswith("\n")

    def test_raises_systemexit_on_write_error(self) -> None:
        """Test that SystemExit is raised when file cannot be written."""
        with pytest.raises(SystemExit) as exc_info:
            write_metadata_json("/nonexistent/dir/out.json", [_ENTRY])

        assert "Could not write to" in str(exc_info.value)


_MANIFEST: dict[str, object] = {
    "version": "photos-0.001-001",
    "total_bytes": 1000,
    "file_count": 1,
    "last_modified": "2024-01-01T00:00:00+00:00",
    "last_verified": "2024-01-01T01:00:00+00:00",
    "files": {"archive.json": "aabbcc"},
}


@pytest.mark.unit
class TestWriteManifestJson:
    """Tests for write_manifest_json function."""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        """Test that JSON file is written with correct content."""
        output = tmp_path / ".version.json"

        write_manifest_json(str(output), dict(_MANIFEST))

        result = json.loads(output.read_text())
        assert result == _MANIFEST

    def test_sets_644_permissions(self, tmp_path: Path) -> None:
        """Test that output file has 644 permissions."""
        output = tmp_path / ".version.json"

        write_manifest_json(str(output), dict(_MANIFEST))

        mode = output.stat().st_mode & 0o777
        assert mode == 0o644

    def test_trailing_newline(self, tmp_path: Path) -> None:
        """Test that file ends with a newline."""
        output = tmp_path / ".version.json"

        write_manifest_json(str(output), dict(_MANIFEST))

        assert output.read_text().endswith("\n")

    def test_raises_systemexit_when_not_dict(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when data is not a dict."""
        with pytest.raises(SystemExit, match="must be a JSON object"):
            write_manifest_json(str(tmp_path / "out.json"), [])

    def test_raises_systemexit_on_missing_keys(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when required keys are missing."""
        incomplete = {"version": "x", "total_bytes": 0}

        with pytest.raises(SystemExit, match="missing required keys"):
            write_manifest_json(str(tmp_path / "out.json"), incomplete)

    def test_raises_systemexit_on_write_error(self) -> None:
        """Test that SystemExit is raised when file cannot be written."""
        with pytest.raises(SystemExit, match="Could not write to"):
            write_manifest_json("/nonexistent/dir/out.json", dict(_MANIFEST))


@pytest.mark.unit
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

        assert sha1 == "4916d6bdb7f78e6803698cab32d1586ea457dfc8"
        assert md5 == "e2c865db4162bed963bfaa9ef6ac18f0"

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

        assert sha1 == "999aa3be859f5b133f5168e57d8a12221df6cec1"
        assert md5 == "752ef0e8f3ee573790c989f401cab9c4"

    @pytest.mark.skipif(os.name == "nt", reason="Permission test not reliable on Windows")
    @pytest.mark.skipif(os.getuid() == 0, reason="chmod 0o000 has no effect as root")
    def test_permission_error_returns_none(self, tmp_path: Path) -> None:
        """Test that permission error returns (None, None)."""
        test_file = tmp_path / "no_read.txt"
        test_file.write_bytes(b"test")
        test_file.chmod(0o000)

        try:
            sha1, md5 = calculate_checksums(str(test_file))
            assert sha1 is None
            assert md5 is None
        finally:
            test_file.chmod(0o644)


@pytest.mark.unit
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

    @pytest.mark.skipif(os.name == "nt", reason="Permission test not reliable on Windows")
    @pytest.mark.skipif(os.getuid() == 0, reason="chmod 0o000 has no effect as root")
    def test_permission_error_raises_oserror(self, tmp_path: Path) -> None:
        """Test that permission error raises OSError."""
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestFormatCount:
    """Tests for format_count function."""

    def test_zero(self) -> None:
        """Test formatting zero."""
        assert format_count(0) == "0"

    def test_small_number(self) -> None:
        """Test number below 1000 has no separator."""
        assert format_count(999) == "999"

    def test_thousands(self) -> None:
        """Test thousands use space separator."""
        assert format_count(1000) == "1 000"
        assert format_count(12345) == "12 345"

    def test_millions(self) -> None:
        """Test millions use space separators."""
        assert format_count(1234567) == "1 234 567"

    def test_no_commas(self) -> None:
        """Result must not contain commas."""
        assert "," not in format_count(1_000_000)


@pytest.mark.unit
class TestValidateDirectory:
    """Tests for validate_directory function."""

    def test_valid_directory_returns_path(self, tmp_path: Path) -> None:
        """Test that valid directory returns a Path object."""
        result = validate_directory(str(tmp_path))
        assert result == tmp_path

    def test_nonexistent_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that nonexistent directory raises SystemExit."""
        nonexistent = str(tmp_path / "missing")
        with pytest.raises(SystemExit, match="does not exist"):
            validate_directory(nonexistent)

    def test_file_raises_systemexit(self, tmp_path: Path) -> None:
        """Test that a file path raises SystemExit."""
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(SystemExit, match="is not a directory"):
            validate_directory(str(f))

    def test_check_readable_passes_for_readable_dir(self, tmp_path: Path) -> None:
        """Test check_readable=True passes for a readable directory."""
        result = validate_directory(str(tmp_path), check_readable=True)
        assert result == tmp_path

    @pytest.mark.skipif(os.getuid() == 0, reason="chmod 0o000 has no effect as root")
    def test_check_readable_raises_for_unreadable_dir(self, tmp_path: Path) -> None:
        """Test check_readable=True raises SystemExit for unreadable directory."""
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            with pytest.raises(SystemExit, match="is not readable"):
                validate_directory(str(locked), check_readable=True)
        finally:
            locked.chmod(0o755)


@pytest.mark.unit
class TestFindVersionFile:
    """Tests for find_version_file function."""

    def test_finds_existing_version_file(self, tmp_path: Path) -> None:
        """Test that .version.json is found when present."""
        version_file = tmp_path / ".version.json"
        version_file.write_text("{}")

        result = find_version_file(str(tmp_path))

        assert result is not None
        assert result.endswith(".version.json")

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        """Test that None is returned when .version.json is absent."""
        result = find_version_file(str(tmp_path))
        assert result is None


@pytest.mark.unit
class TestResolveOwnerName:
    """Tests for resolve_owner_name function."""

    def test_valid_uid_returns_name(self) -> None:
        """Test that a valid UID returns a username string."""
        uid = os.getuid()
        result = resolve_owner_name(uid)
        assert result is not None
        assert isinstance(result, str)

    def test_invalid_uid_returns_none(self) -> None:
        """Test that an invalid UID returns None."""
        result = resolve_owner_name(999999999)
        assert result is None


@pytest.mark.unit
class TestResolveGroupName:
    """Tests for resolve_group_name function."""

    def test_valid_gid_returns_name(self) -> None:
        """Test that a valid GID returns a group name string."""
        gid = os.getgid()
        result = resolve_group_name(gid)
        assert result is not None
        assert isinstance(result, str)

    def test_invalid_gid_returns_none(self) -> None:
        """Test that an invalid GID returns None."""
        result = resolve_group_name(999999999)
        assert result is None
