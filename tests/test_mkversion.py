"""Tests for mkversion module."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from _pytest.capture import CaptureFixture

from photos_manager.mkversion import find_json_files, main, validate_and_process_json


class TestFindJsonFiles:
    """Tests for find_json_files function."""

    def test_finds_json_files(self, tmp_path: Path) -> None:
        """Test that JSON files are found in directory."""
        # Create test JSON files
        (tmp_path / "file1.json").write_text("[]")
        (tmp_path / "file2.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 2
        paths = [path for _, path in result]
        assert any("file1.json" in p for p in paths)
        assert any("file2.json" in p for p in paths)

    def test_excludes_version_json_files(self, tmp_path: Path) -> None:
        """Test that *version.json files are excluded."""
        # Create test files
        (tmp_path / "archive.json").write_text("[]")
        (tmp_path / ".version.json").write_text("{}")
        (tmp_path / "backup.version.json").write_text("{}")

        result = find_json_files(str(tmp_path))

        # Should only find archive.json, not version files
        assert len(result) == 1
        _, path = result[0]
        assert "archive.json" in path
        assert "version.json" not in path

    def test_recursive_search(self, tmp_path: Path) -> None:
        """Test that search is recursive."""
        # Create nested directory structure
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "root.json").write_text("[]")
        (subdir / "nested.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 2
        paths = [path for _, path in result]
        assert any("root.json" in p for p in paths)
        assert any("nested.json" in p for p in paths)

    def test_returns_modification_times(self, tmp_path: Path) -> None:
        """Test that modification times are returned."""
        (tmp_path / "file.json").write_text("[]")

        result = find_json_files(str(tmp_path))

        assert len(result) == 1
        mtime, _ = result[0]
        assert isinstance(mtime, float)
        assert mtime > 0

    def test_raises_on_empty_directory(self, tmp_path: Path) -> None:
        """Test that SystemExit is raised when no JSON files found."""
        with pytest.raises(SystemExit, match="No JSON files found"):
            find_json_files(str(tmp_path))


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
        assert len(hashes["archive.json"]) == 40  # SHA1 hex length

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


class TestMain:
    """Tests for main function."""

    def test_writes_to_stdout_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main writes to stdout when no output file specified."""
        # Create test JSON file
        data = [
            {"md5": "abc", "path": "/test.jpg", "sha1": "def", "size": 1000, "date": "2025-01-01"}
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["mkversion.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "version" in output
        assert output["total_bytes"] == 1000
        assert output["file_count"] == 1
        assert "archive.json" in output["files"]

    def test_writes_to_output_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that main writes to file when --output specified."""
        # Create test JSON file
        data = [
            {"md5": "abc", "path": "/test.jpg", "sha1": "def", "size": 2000, "date": "2025-01-01"}
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        output_file = tmp_path / ".version.json"
        monkeypatch.setattr("sys.argv", ["mkversion.py", str(tmp_path), "-o", str(output_file)])

        exit_code = main()

        assert exit_code == os.EX_OK
        assert output_file.exists()

        version_data = json.loads(output_file.read_text())
        assert "version" in version_data
        assert version_data["total_bytes"] == 2000
        assert version_data["file_count"] == 1

    def test_calculates_version_string_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that version string is calculated correctly."""
        # Create test with specific total size
        # 1234 files with 1000000000 bytes each = 1234000000000 bytes = 1.234 TB
        # 1234 files -> last 3 digits = 234
        data = []
        for i in range(1234):
            data.append(
                {
                    "md5": "abc",
                    "path": f"/test{i}.jpg",
                    "sha1": "def",
                    "size": 1000000000,  # 1GB each
                    "date": "2025-01-01",
                }
            )

        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        monkeypatch.setattr("sys.argv", ["mkversion.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Version format: photos-{TB:.3f}-{count%1000}
        assert output["total_bytes"] == 1234000000000
        assert output["file_count"] == 1234
        # Check that version string is correctly formatted
        assert output["version"].endswith("-234")  # Last 3 digits of count
        assert "photos-" in output["version"]

    def test_exits_with_error_for_nonexistent_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error for nonexistent directory."""
        monkeypatch.setattr("sys.argv", ["mkversion.py", "/nonexistent/directory"])

        with pytest.raises(SystemExit, match="does not exist or is not readable"):
            main()

    def test_exits_with_error_for_empty_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error when no JSON files found."""
        monkeypatch.setattr("sys.argv", ["mkversion.py", str(tmp_path)])

        with pytest.raises(SystemExit, match="No JSON files found"):
            main()

    def test_exits_with_error_for_invalid_output_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that main exits with error when output file cannot be written."""
        # Create test JSON file
        data = [
            {"md5": "abc", "path": "/test.jpg", "sha1": "def", "size": 100, "date": "2025-01-01"}
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        # Try to write to a directory that doesn't exist
        invalid_output = tmp_path / "nonexistent" / "output.json"
        monkeypatch.setattr(
            "sys.argv", ["mkversion.py", str(tmp_path), "--output", str(invalid_output)]
        )

        with pytest.raises(SystemExit, match="Could not write to output file"):
            main()

    def test_processes_multiple_json_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[Any]
    ) -> None:
        """Test that main processes multiple JSON files correctly."""
        data1 = [{"md5": "a", "path": "/1.jpg", "sha1": "b", "size": 500, "date": "2025-01-01"}]
        data2 = [{"md5": "c", "path": "/2.jpg", "sha1": "d", "size": 1500, "date": "2025-01-02"}]

        (tmp_path / "archive1.json").write_text(json.dumps(data1))
        (tmp_path / "archive2.json").write_text(json.dumps(data2))

        monkeypatch.setattr("sys.argv", ["mkversion.py", str(tmp_path)])

        exit_code = main()

        assert exit_code == os.EX_OK
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["total_bytes"] == 2000
        assert output["file_count"] == 2
        assert len(output["files"]) == 2
