"""Tests for fixdates module."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from _pytest.capture import CaptureFixture

from photos_manager.fixdates import (
    get_newest_files,
    run,
    set_dirs_timestamps,
    set_files_timestamps,
    set_json_timestamps,
)


class TestGetNewestFiles:
    """Tests for get_newest_files function."""

    def test_finds_newest_file_per_directory(self, tmp_path: Path) -> None:
        """Test that newest file is found for each directory."""
        json_file = tmp_path / "test.json"
        data = [
            {
                "path": "/photos/2024/img1.jpg",
                "date": "2024-01-01T12:00:00+0000",
                "size": 100,
            },
            {
                "path": "/photos/2024/img2.jpg",
                "date": "2024-12-31T23:59:59+0000",
                "size": 200,
            },
            {
                "path": "/photos/2025/img3.jpg",
                "date": "2025-01-01T00:00:00+0000",
                "size": 300,
            },
        ]
        json_file.write_text(json.dumps(data))

        newest_files, newest_entry = get_newest_files(str(json_file))

        # Should have entries for both directories
        assert len(newest_files) == 2
        assert "/photos/2024" in newest_files
        assert "/photos/2025" in newest_files

        # Newest in 2024 should be img2
        assert newest_files["/photos/2024"]["path"] == "/photos/2024/img2.jpg"

        # Overall newest should be img3
        assert newest_entry["path"] == "/photos/2025/img3.jpg"

    def test_raises_on_empty_json(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for empty JSON."""
        json_file = tmp_path / "empty.json"
        json_file.write_text("[]")

        with pytest.raises(SystemExit, match="empty"):
            get_newest_files(str(json_file))

    def test_raises_on_missing_path_field(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when path field is missing."""
        json_file = tmp_path / "test.json"
        data = [{"date": "2024-01-01T12:00:00+0000", "size": 100}]
        json_file.write_text(json.dumps(data))

        with pytest.raises(SystemExit, match="Missing 'path'"):
            get_newest_files(str(json_file))

    def test_raises_on_missing_date_field(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when date field is missing."""
        json_file = tmp_path / "test.json"
        data = [{"path": "/test.jpg", "size": 100}]
        json_file.write_text(json.dumps(data))

        with pytest.raises(SystemExit, match="Missing 'date'"):
            get_newest_files(str(json_file))

    def test_raises_on_invalid_date_format(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for invalid date format."""
        json_file = tmp_path / "test.json"
        data = [{"path": "/test.jpg", "date": "invalid-date", "size": 100}]
        json_file.write_text(json.dumps(data))

        with pytest.raises(SystemExit, match="Invalid date format"):
            get_newest_files(str(json_file))


class TestSetFilesTimestamps:
    """Tests for set_files_timestamps function."""

    def test_updates_file_timestamp_in_dry_run(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that dry run mode prints changes without applying them."""
        # Create test file
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test content")

        # Create JSON with different timestamp
        json_file = tmp_path / "test.json"
        target_date = "2024-01-01T12:00:00+0000"
        data = [{"path": str(test_file), "date": target_date, "size": 12}]
        json_file.write_text(json.dumps(data))

        # Get original mtime
        original_mtime = int(test_file.stat().st_mtime)

        # Run in dry-run mode
        set_files_timestamps(str(json_file), dry_run=True)

        # Timestamp should not be changed
        assert int(test_file.stat().st_mtime) == original_mtime

        # Should print what would be done
        captured = capsys.readouterr()
        assert "Set timestamp for file" in captured.out

    def test_updates_file_timestamp(self, tmp_path: Path) -> None:
        """Test that file timestamp is actually updated."""
        # Create test file
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test content")

        # Create JSON with specific timestamp
        json_file = tmp_path / "test.json"
        target_date = "2024-01-01T12:00:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        data = [{"path": str(test_file), "date": target_date, "size": 12}]
        json_file.write_text(json.dumps(data))

        # Update timestamp
        set_files_timestamps(str(json_file), dry_run=False)

        # Verify timestamp was updated
        assert int(test_file.stat().st_mtime) == target_timestamp

    def test_skips_nonexistent_files(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test that nonexistent files are skipped with warning."""
        json_file = tmp_path / "test.json"
        data = [
            {
                "path": str(tmp_path / "missing.jpg"),
                "date": "2024-01-01T12:00:00+0000",
                "size": 100,
            }
        ]
        json_file.write_text(json.dumps(data))

        set_files_timestamps(str(json_file), dry_run=False)

        # Should print error to stderr
        captured = capsys.readouterr()
        assert "not found" in captured.err or "not writable" in captured.err

    def test_skips_entries_with_missing_fields(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that entries with missing fields are skipped."""
        json_file = tmp_path / "test.json"
        data = [{"path": "/test.jpg"}]  # Missing date field
        json_file.write_text(json.dumps(data))

        set_files_timestamps(str(json_file), dry_run=False)

        # Should print error
        captured = capsys.readouterr()
        assert "missing path or date" in captured.err


class TestSetDirsTimestamps:
    """Tests for set_dirs_timestamps function."""

    def test_updates_directory_timestamp(self, tmp_path: Path) -> None:
        """Test that directory timestamp is updated to match newest file."""
        # Create directory with file
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        # Set specific timestamp on file
        target_date = "2024-01-01T12:00:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))

        # Create newest_files dict
        newest_files = cast(
            "dict[str, dict[str, str | int]]", {str(subdir): {"path": str(test_file)}}
        )

        # Update directory timestamp
        set_dirs_timestamps(newest_files, dry_run=False)

        # Directory should now have same timestamp as file
        assert int(subdir.stat().st_mtime) == target_timestamp

    def test_dry_run_does_not_update(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test that dry run prints but doesn't update."""
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        original_dir_mtime = int(subdir.stat().st_mtime)

        newest_files = cast(
            "dict[str, dict[str, str | int]]", {str(subdir): {"path": str(test_file)}}
        )
        set_dirs_timestamps(newest_files, dry_run=True)

        # Directory timestamp should not change
        assert int(subdir.stat().st_mtime) == original_dir_mtime

        # Should print what would be done
        captured = capsys.readouterr()
        assert "Set timestamp for directory" in captured.out

    def test_skips_nonexistent_directory(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test that nonexistent directories are skipped."""
        newest_files = cast(
            "dict[str, dict[str, str | int]]",
            {str(tmp_path / "missing"): {"path": str(tmp_path / "missing" / "file.jpg")}},
        )

        set_dirs_timestamps(newest_files, dry_run=False)

        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestSetJsonTimestamps:
    """Tests for set_json_timestamps function."""

    def test_updates_json_and_directory_timestamps(self, tmp_path: Path) -> None:
        """Test that both JSON file and directory timestamps are updated."""
        # Create directory and file
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        # Create JSON file
        json_file = tmp_path / "photos.json"
        json_file.write_text("{}")

        # Set specific timestamp on test file
        target_date = "2024-01-01T12:00:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))

        # Create newest entry
        newest_entry = cast("dict[str, str | int]", {"path": str(test_file)})

        # Update timestamps
        set_json_timestamps(str(json_file), str(subdir), newest_entry, dry_run=False)

        # Both should have matching timestamps
        assert int(json_file.stat().st_mtime) == target_timestamp
        assert int(subdir.stat().st_mtime) == target_timestamp

    def test_dry_run_does_not_update(self, tmp_path: Path, capsys: CaptureFixture[Any]) -> None:
        """Test that dry run doesn't update timestamps."""
        subdir = tmp_path / "photos"
        subdir.mkdir()
        test_file = subdir / "test.jpg"
        test_file.write_text("content")

        json_file = tmp_path / "photos.json"
        json_file.write_text("{}")

        original_json_mtime = int(json_file.stat().st_mtime)
        original_dir_mtime = int(subdir.stat().st_mtime)

        newest_entry = cast("dict[str, str | int]", {"path": str(test_file)})
        set_json_timestamps(str(json_file), str(subdir), newest_entry, dry_run=True)

        # Timestamps should not change
        assert int(json_file.stat().st_mtime) == original_json_mtime
        assert int(subdir.stat().st_mtime) == original_dir_mtime

        # Should print what would be done
        captured = capsys.readouterr()
        assert "Set timestamp" in captured.out

    def test_handles_missing_path_in_entry(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test handling of missing path in newest entry."""
        json_file = tmp_path / "test.json"
        json_file.write_text("{}")

        newest_entry: dict[str, str | int] = {}  # Missing path

        set_json_timestamps(str(json_file), str(tmp_path), newest_entry, dry_run=False)

        captured = capsys.readouterr()
        assert "Missing 'path'" in captured.err

    def test_handles_nonexistent_reference_file(
        self, tmp_path: Path, capsys: CaptureFixture[Any]
    ) -> None:
        """Test handling of nonexistent reference file."""
        json_file = tmp_path / "test.json"
        json_file.write_text("{}")

        newest_entry = cast("dict[str, str | int]", {"path": str(tmp_path / "missing.jpg")})

        set_json_timestamps(str(json_file), str(tmp_path), newest_entry, dry_run=False)

        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestRun:
    """Integration tests for run() function."""

    def test_run_updates_timestamps(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Test that run() updates directory timestamps based on JSON."""
        # Create test directory and files
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "photo.jpg"
        test_file.write_text("photo content")

        # Set old mtime on directory
        old_time = 1000000000.0
        os.utime(test_dir, (old_time, old_time))

        # Create JSON with newer timestamp
        data = [
            {
                "path": str(test_file),
                "date": "2025-01-15T12:30:00+00:00",
                "sha1": "abc",
                "md5": "def",
                "size": len("photo content"),
            }
        ]
        json_file = tmp_path / "photos.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(json_files=[str(json_file)], dry_run=False, all=False)

        exit_code = run(args)

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "timestamps set" in captured.out.lower() or "timestamp" in captured.out.lower()

    def test_run_with_dry_run(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Test that run() in dry-run mode doesn't modify anything."""
        # Create test directory
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "photo.jpg"
        test_file.write_text("photo")

        # Create JSON
        data = [
            {
                "path": str(test_file),
                "date": "2025-01-15T12:30:00+00:00",
                "sha1": "abc",
                "md5": "def",
                "size": 5,
            }
        ]
        json_file = tmp_path / "photos.json"
        json_file.write_text(json.dumps(data))

        # Store original mtime
        original_dir_mtime = test_dir.stat().st_mtime

        args = argparse.Namespace(json_files=[str(json_file)], dry_run=True, all=False)

        exit_code = run(args)

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "Set timestamp" in captured.out  # Dry run still prints messages

        # Verify mtime wasn't actually changed in dry-run mode
        assert test_dir.stat().st_mtime == original_dir_mtime

    def test_run_with_all_flag(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """Test that run() with --all flag updates individual file timestamps."""
        # Create test files
        test_dir = tmp_path / "photos"
        test_dir.mkdir()
        test_file = test_dir / "photo.jpg"
        test_file.write_text("photo")

        # Set old mtime
        old_time = 1000000000.0
        os.utime(test_file, (old_time, old_time))

        # Create JSON with newer timestamp
        data = [
            {
                "path": str(test_file),
                "date": "2025-01-15T12:30:00+00:00",
                "sha1": "abc",
                "md5": "def",
                "size": 5,
            }
        ]
        json_file = tmp_path / "photos.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(json_files=[str(json_file)], dry_run=False, all=True)

        exit_code = run(args)

        assert exit_code == os.EX_OK
        # File mtime should be updated
        assert test_file.stat().st_mtime != old_time

    def test_run_with_multiple_json_files(
        self, tmp_path: Path, capsys: CaptureFixture[str]
    ) -> None:
        """Test that run() processes multiple JSON files."""
        # Create two sets of files
        dir1 = tmp_path / "photos1"
        dir2 = tmp_path / "photos2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "file1.txt").write_text("content1")
        (dir2 / "file2.txt").write_text("content2")

        # Create two JSON files
        data1 = [
            {
                "path": str(dir1 / "file1.txt"),
                "date": "2025-01-15T12:30:00+00:00",
                "sha1": "a",
                "md5": "b",
                "size": 8,
            }
        ]
        data2 = [
            {
                "path": str(dir2 / "file2.txt"),
                "date": "2025-01-16T12:30:00+00:00",
                "sha1": "c",
                "md5": "d",
                "size": 8,
            }
        ]

        json1 = tmp_path / "photos1.json"
        json2 = tmp_path / "photos2.json"
        json1.write_text(json.dumps(data1))
        json2.write_text(json.dumps(data2))

        args = argparse.Namespace(json_files=[str(json1), str(json2)], dry_run=False, all=False)

        exit_code = run(args)

        assert exit_code == os.EX_OK

    def test_run_with_nonexistent_json_file(self, capsys: CaptureFixture[str]) -> None:
        """Test that run() handles nonexistent JSON file gracefully."""
        args = argparse.Namespace(json_files=["/nonexistent/file.json"], dry_run=False, all=False)

        exit_code = run(args)

        # Should complete but print error
        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "non-existent" in captured.err.lower() or "unreadable" in captured.err.lower()
