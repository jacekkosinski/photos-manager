"""Tests for photos_manager.locate module."""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from photos_manager import locate


def _make_entry(path: str, date: str, size: int = 1000) -> dict[str, str | int]:
    """Create a minimal JSON metadata entry."""
    return {
        "path": path,
        "sha1": "a" * 40,
        "md5": "b" * 32,
        "date": date,
        "size": size,
    }


SAMPLE_ENTRIES = [
    _make_entry("camera/100/img_001.jpg", "2025-07-07T10:00:00+02:00"),
    _make_entry("camera/100/img_002.jpg", "2025-07-07T10:05:00+02:00"),
    _make_entry("camera/100/img_003.jpg", "2025-07-07T10:10:00+02:00"),
    _make_entry("camera/101/img_004.jpg", "2025-07-07T12:00:00+02:00"),
    _make_entry("camera/101/img_005.jpg", "2025-07-07T12:05:00+02:00"),
    _make_entry("camera/101/img_006.jpg", "2025-07-07T12:10:00+02:00"),
    _make_entry("phone/202507/img_100.jpg", "2025-07-07T14:00:00+02:00"),
    _make_entry("phone/202507/img_101.jpg", "2025-07-07T14:05:00+02:00"),
]


def _build_sorted_entries(
    entries: list[dict[str, str | int]],
) -> list[tuple[datetime, dict[str, str | int]]]:
    """Convert raw entries to sorted (datetime, entry) tuples."""
    result = []
    for entry in entries:
        dt = datetime.fromisoformat(str(entry["date"]))
        result.append((dt, entry))
    result.sort(key=lambda x: x[0])
    return result


# --- Unit tests ---


@pytest.mark.unit
class TestFindNeighbors:
    """Tests for find_neighbors function."""

    def test_finds_neighbors_in_middle(self) -> None:
        """Test finding neighbors around a timestamp in the middle of entries."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES)
        target = datetime(2025, 7, 7, 10, 7, 0, tzinfo=timezone(timedelta(hours=2)))
        result = locate.find_neighbors(sorted_entries, target, 2)
        assert len(result) >= 2
        paths = [str(e["path"]) for _, e in result]
        assert "camera/100/img_002.jpg" in paths
        assert "camera/100/img_003.jpg" in paths

    def test_finds_neighbors_at_start(self) -> None:
        """Test finding neighbors near the beginning of entries."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES)
        target = datetime(2025, 7, 7, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        result = locate.find_neighbors(sorted_entries, target, 3)
        assert len(result) >= 1
        paths = [str(e["path"]) for _, e in result]
        assert "camera/100/img_001.jpg" in paths

    def test_finds_neighbors_at_end(self) -> None:
        """Test finding neighbors near the end of entries."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES)
        target = datetime(2025, 7, 7, 15, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        result = locate.find_neighbors(sorted_entries, target, 2)
        paths = [str(e["path"]) for _, e in result]
        assert "phone/202507/img_101.jpg" in paths

    def test_empty_entries(self) -> None:
        """Test with empty entries list."""
        result = locate.find_neighbors([], datetime.now(tz=UTC), 5)
        assert result == []


@pytest.mark.unit
class TestProposeDirectories:
    """Tests for propose_directories function."""

    def test_proposes_most_common_directory(self) -> None:
        """Test that the most common parent directory is proposed."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES[:3])
        result = locate.propose_directories(sorted_entries)
        assert result == ["camera/100"]

    def test_returns_empty_for_empty(self) -> None:
        """Test that empty list is returned for empty input."""
        result = locate.propose_directories([])
        assert result == []

    def test_mixed_directories(self) -> None:
        """Test with entries from different directories, clear winner."""
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/file2.jpg", "2025-07-07T10:01:00+02:00"),
            _make_entry("dir_b/file3.jpg", "2025-07-07T10:02:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        result = locate.propose_directories(sorted_entries)
        assert result == ["dir_a"]

    def test_ambiguous_two_tied(self) -> None:
        """Test that tied directories are all returned."""
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T10:01:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        result = locate.propose_directories(sorted_entries)
        assert result == ["dir_a", "dir_b"]

    def test_ambiguous_three_tied(self) -> None:
        """Test that three tied directories are all returned."""
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T10:01:00+02:00"),
            _make_entry("dir_c/file3.jpg", "2025-07-07T10:02:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        result = locate.propose_directories(sorted_entries)
        assert result == ["dir_a", "dir_b", "dir_c"]

    def test_single_entry(self) -> None:
        """Test with a single entry returns one directory."""
        entries = [
            _make_entry("only_dir/file1.jpg", "2025-07-07T10:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        result = locate.propose_directories(sorted_entries)
        assert result == ["only_dir"]


@pytest.mark.unit
class TestLoadArchiveEntries:
    """Tests for load_archive_entries function."""

    def test_loads_and_sorts(self, tmp_path: Path) -> None:
        """Test loading entries from JSON file."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        result = locate.load_archive_entries([str(json_file)], None)
        assert len(result) == len(SAMPLE_ENTRIES)
        dates = [dt for dt, _ in result]
        assert dates == sorted(dates)

    def test_filter(self, tmp_path: Path) -> None:
        """Test filtering entries by path substring."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        result = locate.load_archive_entries([str(json_file)], "phone")
        assert len(result) == 2
        for _, entry in result:
            assert "phone" in str(entry["path"])

    def test_multiple_json_files(self, tmp_path: Path) -> None:
        """Test loading from multiple JSON files."""
        json1 = tmp_path / "a.json"
        json2 = tmp_path / "b.json"
        json1.write_text(json.dumps(SAMPLE_ENTRIES[:3]), encoding="utf-8")
        json2.write_text(json.dumps(SAMPLE_ENTRIES[3:]), encoding="utf-8")
        result = locate.load_archive_entries([str(json1), str(json2)], None)
        assert len(result) == len(SAMPLE_ENTRIES)


@pytest.mark.unit
class TestScanNewFiles:
    """Tests for scan_new_files function."""

    def test_scans_directory(self, tmp_path: Path) -> None:
        """Test scanning directory for files."""
        (tmp_path / "a.jpg").write_text("data")
        (tmp_path / "b.jpg").write_text("data")
        result = locate.scan_new_files(str(tmp_path))
        assert len(result) == 2
        names = [Path(p).name for p, _ in result]
        assert "a.jpg" in names
        assert "b.jpg" in names

    def test_scans_subdirectories(self, tmp_path: Path) -> None:
        """Test that files in subdirectories are found recursively."""
        (tmp_path / "file.jpg").write_text("data")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.jpg").write_text("data")
        result = locate.scan_new_files(str(tmp_path))
        assert len(result) == 2
        names = [Path(p).name for p, _ in result]
        assert "file.jpg" in names
        assert "nested.jpg" in names

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test scanning empty directory."""
        result = locate.scan_new_files(str(tmp_path))
        assert result == []


@pytest.mark.unit
class TestWriteScript:
    """Tests for _write_script function."""

    def test_generates_script(self, tmp_path: Path) -> None:
        """Test shell script generation."""
        script_path = str(tmp_path / "move.sh")
        placements = [
            ("/new/a.jpg", "camera/100"),
            ("/new/b.jpg", "camera/101"),
        ]
        locate._write_script(placements, script_path)
        content = Path(script_path).read_text(encoding="utf-8")
        assert "#!/bin/bash" in content
        assert 'mkdir -p "camera/100"' in content
        assert 'mkdir -p "camera/101"' in content
        assert 'mv -iv "/new/a.jpg" "camera/100/a.jpg"' in content
        assert 'mv -iv "/new/b.jpg" "camera/101/b.jpg"' in content

    def test_script_is_executable(self, tmp_path: Path) -> None:
        """Test that generated script has execute permission."""
        script_path = str(tmp_path / "move.sh")
        locate._write_script([("/new/a.jpg", "dir")], script_path)
        mode = Path(script_path).stat().st_mode
        assert mode & 0o111


# --- Integration tests ---


@pytest.mark.integration
class TestRun:
    """Integration tests for run() function."""

    def _setup_archive(self, tmp_path: Path) -> Path:
        """Create a JSON archive file with sample entries."""
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(SAMPLE_ENTRIES), encoding="utf-8")
        return json_file

    def _setup_new_files(self, tmp_path: Path) -> Path:
        """Create a directory with new files having specific mtimes."""
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "new_photo.jpg"
        f.write_text("photo data")
        # Set mtime to 2025-07-07 10:07:00 UTC (between img_002 and img_003)
        target_ts = datetime(2025, 7, 7, 8, 7, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        return new_dir

    def test_default_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test default mode prints proposed directories."""
        json_file = self._setup_archive(tmp_path)
        new_dir = self._setup_new_files(tmp_path)
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=10,
            filter=None,
            output=None,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "camera/100" in captured.out

    def test_list_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test list mode shows interleaved listing."""
        json_file = self._setup_archive(tmp_path)
        new_dir = self._setup_new_files(tmp_path)
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=True,
            context=3,
            filter=None,
            output=None,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert ">" in captured.out
        assert "Proposed directory:" in captured.out

    def test_output_mode(self, tmp_path: Path) -> None:
        """Test output mode generates shell script."""
        json_file = self._setup_archive(tmp_path)
        new_dir = self._setup_new_files(tmp_path)
        script_path = str(tmp_path / "move.sh")
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=3,
            filter=None,
            output=script_path,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        content = Path(script_path).read_text(encoding="utf-8")
        assert "mkdir -p" in content
        assert "mv -iv" in content

    def test_output_mode_refuses_ambiguous(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test -o mode refuses to write script when placement is ambiguous."""
        # Build archive where neighbors are evenly split between two dirs
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T10:01:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "photo.jpg"
        f.write_text("data")
        target_ts = datetime(2025, 7, 7, 8, 0, 30, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        script_path = str(tmp_path / "move.sh")
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=script_path,
        )
        with pytest.raises(SystemExit, match="Use -f to narrow results"):
            locate.run(args)
        captured = capsys.readouterr()
        assert "Ambiguous placement" in captured.err
        assert "photo.jpg" in captured.err
        assert not Path(script_path).exists()

    def test_default_mode_ambiguous(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test default mode shows all candidates when ambiguous."""
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T10:01:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "photo.jpg"
        f.write_text("data")
        target_ts = datetime(2025, 7, 7, 8, 0, 30, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out
        assert "dir_b" in captured.out

    def test_filter_option(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test filter restricts archive entries by path."""
        json_file = self._setup_archive(tmp_path)
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "photo.jpg"
        f.write_text("data")
        # Set mtime near phone entries
        target_ts = datetime(2025, 7, 7, 12, 2, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=10,
            filter="phone",
            output=None,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "phone" in captured.out

    def test_invalid_directory(self) -> None:
        """Test that invalid directory raises SystemExit."""
        args = argparse.Namespace(
            directory="/nonexistent",
            json_files=["a.json"],
            list=False,
            context=10,
            filter=None,
            output=None,
        )
        with pytest.raises(SystemExit, match="Not a directory"):
            locate.run(args)

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Test that empty directory raises SystemExit."""
        json_file = self._setup_archive(tmp_path)
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        args = argparse.Namespace(
            directory=str(empty_dir),
            json_files=[str(json_file)],
            list=False,
            context=10,
            filter=None,
            output=None,
        )
        with pytest.raises(SystemExit, match="No files found"):
            locate.run(args)
