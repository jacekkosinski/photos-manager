"""Tests for manifest module."""

import argparse
import json
import os
from pathlib import Path

import pytest

from photos_manager.manifest import run, validate_and_process_json


@pytest.mark.unit
class TestValidateAndProcessJson:
    """Tests for validate_and_process_json function."""

    def test_processes_valid_json(self, tmp_path: Path) -> None:
        """Test processing of valid JSON files."""
        data = [
            {"md5": "abc", "path": "/test1", "sha1": "def", "size": 100, "date": "2025-01-01"},
            {"md5": "ghi", "path": "/test2", "sha1": "jkl", "size": 200, "date": "2025-01-02"},
        ]
        file_path = tmp_path / "archive.json"
        file_path.write_text(json.dumps(data))

        total_bytes, file_count, hashes = validate_and_process_json([str(file_path)])

        assert total_bytes == 300
        assert file_count == 2
        assert "archive.json" in hashes
        assert hashes["archive.json"] == "f92a472aabf75795a5f296f40d5614a19a58213e"

    def test_rejects_non_array_json(self, tmp_path: Path) -> None:
        """Test that non-array JSON is rejected."""
        file_path = tmp_path / "invalid.json"
        file_path.write_text('{"key": "value"}')

        with pytest.raises(SystemExit, match="must contain an array of objects"):
            validate_and_process_json([str(file_path)])

    def test_rejects_array_of_non_objects(self, tmp_path: Path) -> None:
        """Test that array of non-objects is rejected."""
        file_path = tmp_path / "invalid.json"
        file_path.write_text('["string1", "string2"]')

        with pytest.raises(SystemExit, match="must contain an array of objects"):
            validate_and_process_json([str(file_path)])

    def test_rejects_missing_required_fields(self, tmp_path: Path) -> None:
        """Test that missing required fields are detected."""
        data = [{"md5": "abc", "path": "/test"}]  # Missing sha1, size, date
        file_path = tmp_path / "incomplete.json"
        file_path.write_text(json.dumps(data))

        with pytest.raises(SystemExit, match="missing required fields"):
            validate_and_process_json([str(file_path)])

    def test_rejects_invalid_json_syntax(self, tmp_path: Path) -> None:
        """Test that invalid JSON syntax is handled."""
        file_path = tmp_path / "bad.json"
        file_path.write_text('{"invalid": json}')

        with pytest.raises(SystemExit, match="Invalid JSON"):
            validate_and_process_json([str(file_path)])

    def test_processes_multiple_files(self, tmp_path: Path) -> None:
        """Test processing multiple JSON files."""
        data1 = [{"md5": "a", "path": "/1", "sha1": "b", "size": 100, "date": "2025-01-01"}]
        data2 = [{"md5": "c", "path": "/2", "sha1": "d", "size": 200, "date": "2025-01-02"}]

        file1 = tmp_path / "file1.json"
        file2 = tmp_path / "file2.json"
        file1.write_text(json.dumps(data1))
        file2.write_text(json.dumps(data2))

        total_bytes, file_count, hashes = validate_and_process_json([str(file1), str(file2)])

        assert total_bytes == 300
        assert file_count == 2
        assert len(hashes) == 2
        assert "file1.json" in hashes
        assert "file2.json" in hashes

    def test_handles_empty_array(self, tmp_path: Path) -> None:
        """Test handling of empty JSON array."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]")

        total_bytes, file_count, hashes = validate_and_process_json([str(file_path)])

        assert total_bytes == 0
        assert file_count == 0
        assert "empty.json" in hashes


@pytest.mark.integration
class TestRun:
    """Integration tests for run() function."""

    def test_run_prints_to_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run() prints version JSON to stdout when no output file specified."""
        # Create test JSON file
        data = [
            {
                "path": "/test/file.txt",
                "sha1": "abc123",
                "md5": "def456",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 1000,
            }
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        args = argparse.Namespace(directory=str(tmp_path), output_file=None)

        exit_code = run(args)

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        assert "photos-" in captured.out

        # Verify stdout contains valid JSON with correct structure
        version_data = json.loads(captured.out)
        assert "version" in version_data
        assert "total_bytes" in version_data
        assert "file_count" in version_data
        assert "last_modified" in version_data
        assert "files" in version_data
        assert version_data["total_bytes"] == 1000
        assert version_data["file_count"] == 1

    def test_run_with_output_file(self, tmp_path: Path) -> None:
        """Test that run() writes to specified output file."""
        # Create test JSON file
        data = [
            {
                "path": "/test/file.txt",
                "sha1": "abc123",
                "md5": "def456",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 500,
            }
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        output_file = tmp_path / "custom.version.json"
        args = argparse.Namespace(directory=str(tmp_path), output_file=str(output_file))

        exit_code = run(args)

        assert exit_code == os.EX_OK
        assert output_file.exists()

        version_data = json.loads(output_file.read_text())
        assert version_data["file_count"] == 1
        assert version_data["total_bytes"] == 500

    def test_run_with_nonexistent_directory(self) -> None:
        """Test that run() raises SystemExit for nonexistent directory."""
        args = argparse.Namespace(directory="/nonexistent/directory", output_file=None)

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "does not exist" in str(exc_info.value)

    def test_run_with_no_json_files(self, tmp_path: Path) -> None:
        """Test that run() raises SystemExit when no JSON files found."""
        # Create empty directory
        test_dir = tmp_path / "empty"
        test_dir.mkdir()

        args = argparse.Namespace(directory=str(test_dir), output_file=None)

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "No JSON files found" in str(exc_info.value)

    def test_run_excludes_version_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() excludes *version.json files."""
        # Create regular JSON file
        data = [
            {
                "path": "/test/file.txt",
                "sha1": "abc",
                "md5": "def",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 100,
            }
        ]
        (tmp_path / "test.json").write_text(json.dumps(data))

        # Create version file (should be excluded)
        version_data = {"version": "old"}
        (tmp_path / "old.version.json").write_text(json.dumps(version_data))

        output_file = tmp_path / ".version.json"
        args = argparse.Namespace(directory=str(tmp_path), output_file=str(output_file))

        exit_code = run(args)

        assert exit_code == os.EX_OK

        # Verify only test.json was processed
        version_result = json.loads(output_file.read_text())
        assert version_result["file_count"] == 1
        assert "test.json" in version_result["files"]
        assert "old.version.json" not in version_result["files"]

    def test_run_with_multiple_json_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run() processes multiple JSON files."""
        # Create multiple JSON files
        data1 = [
            {
                "path": "/test/file1.txt",
                "sha1": "a",
                "md5": "b",
                "date": "2025-01-01T00:00:00+00:00",
                "size": 100,
            }
        ]
        data2 = [
            {
                "path": "/test/file2.txt",
                "sha1": "c",
                "md5": "d",
                "date": "2025-01-02T00:00:00+00:00",
                "size": 200,
            }
        ]
        (tmp_path / "file1.json").write_text(json.dumps(data1))
        (tmp_path / "file2.json").write_text(json.dumps(data2))

        output_file = tmp_path / ".version.json"
        args = argparse.Namespace(directory=str(tmp_path), output_file=str(output_file))

        exit_code = run(args)

        assert exit_code == os.EX_OK

        version_data = json.loads(output_file.read_text())
        assert version_data["file_count"] == 2
        assert version_data["total_bytes"] == 300
        assert len(version_data["files"]) == 2

    def test_run_with_invalid_json_file(self, tmp_path: Path) -> None:
        """Test that run() handles invalid JSON files."""
        # Create invalid JSON file
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{invalid json}")

        args = argparse.Namespace(directory=str(tmp_path), output_file=None)

        with pytest.raises(SystemExit) as exc_info:
            run(args)

        assert "Invalid JSON" in str(exc_info.value)
