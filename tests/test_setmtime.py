"""Tests for setmtime module."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from _pytest.capture import CaptureFixture

from photos_manager.setmtime import (
    get_newest_files,
    load_json,
    main,
    set_dirs_timestamps,
    set_files_timestamps,
    set_json_timestamps,
)


class TestLoadJson:
    """Tests for load_json function."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        """Test that valid JSON is loaded correctly."""
        json_file = tmp_path / "test.json"
        data = [{"path": "/test.jpg", "date": "2025-01-01T12:00:00+0000", "size": 100}]
        json_file.write_text(json.dumps(data))

        result = load_json(str(json_file))

        assert len(result) == 1
        assert result[0]["path"] == "/test.jpg"

    def test_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for nonexistent file."""
        nonexistent = tmp_path / "missing.json"

        with pytest.raises(SystemExit, match="does not exist"):
            load_json(str(nonexistent))

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised for invalid JSON."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("not valid json{")

        with pytest.raises(SystemExit, match="invalid format"):
            load_json(str(json_file))


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
            dict[str, dict[str, str | int]], {str(subdir): {"path": str(test_file)}}
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
            dict[str, dict[str, str | int]], {str(subdir): {"path": str(test_file)}}
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
            dict[str, dict[str, str | int]],
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
        newest_entry = cast(dict[str, str | int], {"path": str(test_file)})

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

        newest_entry = cast(dict[str, str | int], {"path": str(test_file)})
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

        newest_entry = cast(dict[str, str | int], {"path": str(tmp_path / "missing.jpg")})

        set_json_timestamps(str(json_file), str(tmp_path), newest_entry, dry_run=False)

        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestMain:
    """Tests for main function."""

    def test_updates_directory_timestamps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main updates directory timestamps by default."""
        # Create directory with file
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        test_file = photos_dir / "test.jpg"
        test_file.write_text("content")

        # Set specific timestamp on file
        target_date = "2024-01-01T12:00:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        os.utime(str(test_file), (target_timestamp, target_timestamp))

        # Create JSON file
        json_file = tmp_path / "photos.json"
        data = [{"path": str(test_file), "date": target_date, "size": 7}]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["setmtime.py", str(json_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        # Directory should have same timestamp as its newest file
        assert int(photos_dir.stat().st_mtime) == target_timestamp
        # JSON file should also have the timestamp
        assert int(json_file.stat().st_mtime) == target_timestamp

    def test_updates_all_files_with_all_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main updates all file timestamps with --all flag."""
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        test_file = photos_dir / "test.jpg"
        test_file.write_text("content")

        # Create JSON with different timestamp
        target_date = "2024-06-15T10:30:00+0000"
        target_timestamp = int(datetime.fromisoformat(target_date).timestamp())
        json_file = tmp_path / "photos.json"
        data = [{"path": str(test_file), "date": target_date, "size": 7}]
        json_file.write_text(json.dumps(data))

        # Get original timestamp (should be different)
        original_mtime = int(test_file.stat().st_mtime)
        assert original_mtime != target_timestamp

        monkeypatch.setattr("sys.argv", ["setmtime.py", "--all", str(json_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        # File timestamp should be updated
        assert int(test_file.stat().st_mtime) == target_timestamp

    def test_dry_run_does_not_modify_timestamps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --dry-run flag prevents modifications."""
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        test_file = photos_dir / "test.jpg"
        test_file.write_text("content")

        json_file = tmp_path / "photos.json"
        data = [{"path": str(test_file), "date": "2024-01-01T12:00:00+0000", "size": 7}]
        json_file.write_text(json.dumps(data))

        original_dir_mtime = int(photos_dir.stat().st_mtime)
        original_json_mtime = int(json_file.stat().st_mtime)

        monkeypatch.setattr("sys.argv", ["setmtime.py", "--dry-run", str(json_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        # Timestamps should not change
        assert int(photos_dir.stat().st_mtime) == original_dir_mtime
        assert int(json_file.stat().st_mtime) == original_json_mtime

        # Should print what would be done
        captured = capsys.readouterr()
        assert "Set timestamp" in captured.out

    def test_processes_multiple_json_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main processes multiple JSON files."""
        # Create first directory and file
        photos1_dir = tmp_path / "photos1"
        photos1_dir.mkdir()
        file1 = photos1_dir / "test1.jpg"
        file1.write_text("content1")

        # Create second directory and file
        photos2_dir = tmp_path / "photos2"
        photos2_dir.mkdir()
        file2 = photos2_dir / "test2.jpg"
        file2.write_text("content2")

        # Set timestamps on files
        date1 = "2024-01-01T10:00:00+0000"
        timestamp1 = int(datetime.fromisoformat(date1).timestamp())
        os.utime(str(file1), (timestamp1, timestamp1))

        date2 = "2024-06-15T15:00:00+0000"
        timestamp2 = int(datetime.fromisoformat(date2).timestamp())
        os.utime(str(file2), (timestamp2, timestamp2))

        # Create JSON files
        json1 = tmp_path / "photos1.json"
        json1.write_text(json.dumps([{"path": str(file1), "date": date1, "size": 8}]))

        json2 = tmp_path / "photos2.json"
        json2.write_text(json.dumps([{"path": str(file2), "date": date2, "size": 8}]))

        monkeypatch.setattr("sys.argv", ["setmtime.py", str(json1), str(json2)])

        exit_code = main()

        assert exit_code == os.EX_OK
        # Both directories should be updated
        assert int(photos1_dir.stat().st_mtime) == timestamp1
        assert int(photos2_dir.stat().st_mtime) == timestamp2

    def test_skips_nonexistent_json_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main skips nonexistent JSON files with warning."""
        nonexistent = tmp_path / "missing.json"

        monkeypatch.setattr("sys.argv", ["setmtime.py", str(nonexistent)])

        exit_code = main()

        # Should still return OK (just skip the file)
        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "Skipping" in captured.err
        assert "missing.json" in captured.err

    def test_skips_when_directory_does_not_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main skips when corresponding directory doesn't exist."""
        # Create JSON file but not the corresponding directory
        json_file = tmp_path / "photos.json"
        data = [{"path": "/some/file.jpg", "date": "2024-01-01T12:00:00+0000", "size": 100}]
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["setmtime.py", str(json_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "Skipping" in captured.err
        assert "photos" in captured.err

    def test_combines_all_and_dry_run_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that --all and --dry-run can be combined."""
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        test_file = photos_dir / "test.jpg"
        test_file.write_text("content")

        json_file = tmp_path / "photos.json"
        data = [{"path": str(test_file), "date": "2024-01-01T12:00:00+0000", "size": 7}]
        json_file.write_text(json.dumps(data))

        original_file_mtime = int(test_file.stat().st_mtime)

        monkeypatch.setattr("sys.argv", ["setmtime.py", "--all", "--dry-run", str(json_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        # File timestamp should not change
        assert int(test_file.stat().st_mtime) == original_file_mtime

        # Should show what would be done for both files and directories
        captured = capsys.readouterr()
        assert "Set timestamp for file" in captured.out
        assert "Set timestamp for directory" in captured.out
