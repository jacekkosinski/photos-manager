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
class TestBuildDirectoryRanges:
    """Tests for build_directory_ranges function."""

    def test_single_directory(self) -> None:
        """Test range for entries in a single directory."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES[:3])
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.build_directory_ranges(dir_entries)
        assert "camera/100" in result
        lo, hi = result["camera/100"]
        assert lo == datetime.fromisoformat("2025-07-07T10:00:00+02:00")
        assert hi == datetime.fromisoformat("2025-07-07T10:10:00+02:00")

    def test_multiple_directories(self) -> None:
        """Test ranges for entries in multiple directories."""
        sorted_entries = _build_sorted_entries(SAMPLE_ENTRIES)
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.build_directory_ranges(dir_entries)
        assert len(result) == 3
        assert "camera/100" in result
        assert "camera/101" in result
        assert "phone/202507" in result

    def test_empty_entries(self) -> None:
        """Test with empty entries list."""
        dir_entries = locate.build_directory_entries([])
        result = locate.build_directory_ranges(dir_entries)
        assert result == {}


@pytest.mark.unit
class TestProposeDirectories:
    """Tests for propose_directories hybrid function."""

    def test_unambiguous_single_match(self) -> None:
        """Test that a directory matching both range and neighbor passes."""
        entries = [
            _make_entry("dir_a/f1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/f2.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_ranges = locate.build_directory_ranges(locate.build_directory_entries(sorted_entries))
        target = datetime.fromisoformat("2025-07-07T11:00:00+02:00")
        assert locate.propose_directories(sorted_entries, dir_ranges, target, 5) == ["dir_a"]

    def test_ambiguous_overlapping_ranges_and_neighbors(self) -> None:
        """Test that two dirs passing both checks are both returned."""
        entries = [
            _make_entry("dir_a/f1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/f2.jpg", "2025-07-07T14:00:00+02:00"),
            _make_entry("dir_b/f1.jpg", "2025-07-07T11:00:00+02:00"),
            _make_entry("dir_b/f2.jpg", "2025-07-07T15:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_ranges = locate.build_directory_ranges(locate.build_directory_entries(sorted_entries))
        target = datetime.fromisoformat("2025-07-07T12:00:00+02:00")
        result = locate.propose_directories(sorted_entries, dir_ranges, target, 5)
        assert result == ["dir_a", "dir_b"]

    def test_filtered_by_neighbor(self) -> None:
        """Test that a dir in range but not in neighbors is excluded."""
        entries = [
            _make_entry("dir_a/f1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/f2.jpg", "2025-07-07T10:05:00+02:00"),
            _make_entry("dir_b/f1.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_b/f2.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_ranges = locate.build_directory_ranges(locate.build_directory_entries(sorted_entries))
        # target inside both ranges, but N=1 only catches dir_a neighbors
        target = datetime.fromisoformat("2025-07-07T10:03:00+02:00")
        result = locate.propose_directories(sorted_entries, dir_ranges, target, 1)
        assert result == ["dir_a"]

    def test_filtered_by_range(self) -> None:
        """Test that a dir in neighbors but not in range is excluded."""
        entries = [
            _make_entry("dir_a/f1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/f2.jpg", "2025-07-07T10:10:00+02:00"),
            _make_entry("dir_b/f1.jpg", "2025-07-07T10:03:00+02:00"),
            _make_entry("dir_b/f2.jpg", "2025-07-07T10:04:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_ranges = locate.build_directory_ranges(locate.build_directory_entries(sorted_entries))
        # target inside dir_a range (10:00-10:10) but outside dir_b (10:03-10:04)
        target = datetime.fromisoformat("2025-07-07T10:06:00+02:00")
        result = locate.propose_directories(sorted_entries, dir_ranges, target, 5)
        assert "dir_b" not in result
        assert result == ["dir_a"]

    def test_empty_no_matches(self) -> None:
        """Test no matches when timestamp is outside all ranges."""
        entries = [
            _make_entry("dir_a/f1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/f2.jpg", "2025-07-07T10:05:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_ranges = locate.build_directory_ranges(locate.build_directory_entries(sorted_entries))
        target = datetime.fromisoformat("2025-07-07T09:00:00+02:00")
        result = locate.propose_directories(sorted_entries, dir_ranges, target, 5)
        assert result == []


@pytest.mark.unit
class TestExtractSequenceNumber:
    """Tests for extract_sequence_number function."""

    def test_standard_photo_name(self) -> None:
        """Test extraction from standard photo filename."""
        assert locate.extract_sequence_number("img_6767.jpg") == 6767

    def test_multiple_digit_groups(self) -> None:
        """Test that last digit group is used."""
        assert locate.extract_sequence_number("DSC_20250707_001.jpg") == 1

    def test_no_digits(self) -> None:
        """Test that None is returned for filename without digits."""
        assert locate.extract_sequence_number("readme.txt") is None

    def test_digits_only(self) -> None:
        """Test filename that is just digits."""
        assert locate.extract_sequence_number("12345.jpg") == 12345


@pytest.mark.unit
class TestFindSeqMatches:
    """Tests for find_seq_matches function."""

    def test_matches_between_entries(self) -> None:
        """Test seq match when file number is between adjacent entries."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.find_seq_matches(["dir_a"], dir_entries, "img_105.jpg")
        assert result == ["dir_a"]

    def test_matches_before_first_entry(self) -> None:
        """Test weak match when file number is before the first archive entry."""
        entries = [
            _make_entry("dir_a/img_200.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_210.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.find_seq_matches(["dir_a"], dir_entries, "img_190.jpg")
        assert result == ["dir_a"]

    def test_no_match_returns_empty(self) -> None:
        """Test no match when target seq is outside all directory ranges."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.find_seq_matches(["dir_b"], dir_entries, "img_105.jpg")
        assert result == []

    def test_prefix_filters_different_naming(self) -> None:
        """Test that match_prefix=True excludes entries with different prefix."""
        entries = [
            _make_entry("dir_a/dsc_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/dsc_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        # Without prefix matching: seq 105 fits between 100 and 110
        assert locate.find_seq_matches(["dir_a"], dir_entries, "img_105.jpg") == ["dir_a"]
        # With prefix matching: img_ != dsc_, no match
        assert (
            locate.find_seq_matches(["dir_a"], dir_entries, "img_105.jpg", match_prefix=True) == []
        )

    def test_tightest_gap_wins(self) -> None:
        """Test that directory with tightest seq gap is preferred."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_b/img_050.jpg", "2025-07-07T09:00:00+02:00"),
            _make_entry("dir_b/img_500.jpg", "2025-07-07T15:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        # img_105 fits in both dirs, but dir_a has tighter gap (10 vs 450)
        result = locate.find_seq_matches(["dir_a", "dir_b"], dir_entries, "img_105.jpg")
        assert result == ["dir_a"]

    def test_no_digits_returns_empty(self) -> None:
        """Test that file without digits returns empty list."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        result = locate.find_seq_matches(["dir_a"], dir_entries, "readme.txt")
        assert result == []


@pytest.mark.unit
class TestResolveCandiates:
    """Tests for _resolve_candidates function."""

    def test_seq_finds_dir_not_in_neighbors(self) -> None:
        """Test that --seq finds a directory via range+seq even without neighbor match."""
        # dir_a has a wide gap between entries — neighbors won't include it
        # dir_b is close in time — neighbors will include it
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T08:00:00+02:00"),
            _make_entry("dir_a/img_120.jpg", "2025-07-07T16:00:00+02:00"),
            _make_entry("dir_b/img_500.jpg", "2025-07-07T11:58:00+02:00"),
            _make_entry("dir_b/img_510.jpg", "2025-07-07T12:02:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        dir_ranges = locate.build_directory_ranges(dir_entries)
        # target at 12:00 — neighbors (N=1) are dir_b, but seq 105 fits dir_a
        target = datetime.fromisoformat("2025-07-07T12:00:00+02:00")
        result = locate._resolve_candidates(
            sorted_entries,
            dir_ranges,
            dir_entries,
            target,
            1,
            use_seq=True,
            filename="img_105.jpg",
        )
        assert result == ["dir_a"]

    def test_seq_fallback_outside_range(self) -> None:
        """Test that --seq matches files before archive date range."""
        entries = [
            _make_entry("dir_a/img_200.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_210.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        dir_ranges = locate.build_directory_ranges(dir_entries)
        # File before range, seq 190 < 200
        target = datetime.fromisoformat("2025-07-07T08:00:00+02:00")
        result = locate._resolve_candidates(
            sorted_entries,
            dir_ranges,
            dir_entries,
            target,
            5,
            use_seq=True,
            filename="img_190.jpg",
        )
        assert result == ["dir_a"]

    def test_without_seq_uses_hybrid(self) -> None:
        """Test that without --seq, standard hybrid matching is used."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        dir_ranges = locate.build_directory_ranges(dir_entries)
        target = datetime.fromisoformat("2025-07-07T11:00:00+02:00")
        result = locate._resolve_candidates(
            sorted_entries,
            dir_ranges,
            dir_entries,
            target,
            5,
            use_seq=False,
            filename="img_105.jpg",
        )
        assert result == ["dir_a"]

    def test_seq_no_match_falls_back_to_hybrid(self) -> None:
        """Test that when seq doesn't match, hybrid candidates are kept."""
        entries = [
            _make_entry("dir_a/dsc_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/dsc_110.jpg", "2025-07-07T12:00:00+02:00"),
        ]
        sorted_entries = _build_sorted_entries(entries)
        dir_entries = locate.build_directory_entries(sorted_entries)
        dir_ranges = locate.build_directory_ranges(dir_entries)
        target = datetime.fromisoformat("2025-07-07T11:00:00+02:00")
        # With match_prefix: img_ != dsc_, seq fails, falls back to hybrid
        result = locate._resolve_candidates(
            sorted_entries,
            dir_ranges,
            dir_entries,
            target,
            5,
            use_seq=True,
            match_prefix=True,
            filename="img_105.jpg",
        )
        assert result == ["dir_a"]


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
            seq=False,
            prefix=False,
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
            seq=False,
            prefix=False,
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
            seq=False,
            prefix=False,
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
        # Two directories with overlapping date ranges
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/file2.jpg", "2025-07-07T14:00:00+02:00"),
            _make_entry("dir_b/file1.jpg", "2025-07-07T11:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T15:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "photo.jpg"
        f.write_text("data")
        # 12:00+02:00 falls within both dir_a (10:00-14:00) and dir_b (11:00-15:00)
        target_ts = datetime(2025, 7, 7, 10, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        script_path = str(tmp_path / "move.sh")
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=script_path,
            seq=False,
            prefix=False,
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
        """Test default mode shows all candidates when date ranges overlap."""
        entries = [
            _make_entry("dir_a/file1.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/file2.jpg", "2025-07-07T14:00:00+02:00"),
            _make_entry("dir_b/file1.jpg", "2025-07-07T11:00:00+02:00"),
            _make_entry("dir_b/file2.jpg", "2025-07-07T15:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "photo.jpg"
        f.write_text("data")
        # 12:00+02:00 falls within both dir_a and dir_b ranges
        target_ts = datetime(2025, 7, 7, 10, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=False,
            prefix=False,
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
            seq=False,
            prefix=False,
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
            seq=False,
            prefix=False,
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
            seq=False,
            prefix=False,
        )
        with pytest.raises(SystemExit, match="No files found"):
            locate.run(args)

    def test_seq_filter_narrows_ambiguous(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --seq narrows ambiguous placement to matching directory."""
        entries = [
            _make_entry("dir_a/img_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/img_110.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_b/img_200.jpg", "2025-07-07T10:30:00+02:00"),
            _make_entry("dir_b/img_210.jpg", "2025-07-07T11:30:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "img_105.jpg"
        f.write_text("data")
        # 11:00+02:00 = within both dir_a (10:00-12:00) and dir_b (10:30-11:30)
        target_ts = datetime(2025, 7, 7, 9, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=True,
            prefix=False,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out
        assert "dir_b" not in captured.out

    def test_seq_fallback_matches_outside_range(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --seq matches files before archive date range by sequence number."""
        # Archive starts at img_200, new file img_190 is before the range
        entries = [
            _make_entry("dir_a/img_200.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_210.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "img_190.jpg"
        f.write_text("data")
        # Timestamp before archive range
        target_ts = datetime(2025, 7, 7, 8, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=True,
            prefix=False,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "dir_a" in captured.out

    def test_list_mode_aggregates_across_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test -l mode finds match even when first file is outside range."""
        entries = [
            _make_entry("dir_a/img_200.jpg", "2025-07-07T12:00:00+02:00"),
            _make_entry("dir_a/img_210.jpg", "2025-07-07T14:00:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        # First file: before archive range (no hybrid match)
        f1 = new_dir / "img_190.jpg"
        f1.write_text("data")
        ts1 = datetime(2025, 7, 7, 8, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f1, (ts1, ts1))
        # Second file: within archive range (hybrid match)
        f2 = new_dir / "img_205.jpg"
        f2.write_text("data")
        ts2 = datetime(2025, 7, 7, 11, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f2, (ts2, ts2))
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=True,
            context=5,
            filter=None,
            output=None,
            seq=False,
            prefix=False,
        )
        result = locate.run(args)
        assert result == os.EX_OK
        captured = capsys.readouterr()
        assert "Proposed directory:" in captured.out
        assert "dir_a" in captured.out

    def test_prefix_requires_seq(self, tmp_path: Path) -> None:
        """Test that --prefix without --seq raises SystemExit."""
        json_file = self._setup_archive(tmp_path)
        new_dir = self._setup_new_files(tmp_path)
        args = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=False,
            prefix=True,
        )
        with pytest.raises(SystemExit, match="--prefix requires --seq"):
            locate.run(args)

    def test_prefix_narrows_seq_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test --prefix with --seq only matches entries with same naming pattern."""
        entries = [
            # dir_a has dsc_ entries: seq 100-110
            _make_entry("dir_a/dsc_100.jpg", "2025-07-07T10:00:00+02:00"),
            _make_entry("dir_a/dsc_110.jpg", "2025-07-07T12:00:00+02:00"),
            # dir_b has img_ entries: seq 100-110
            _make_entry("dir_b/img_100.jpg", "2025-07-07T10:30:00+02:00"),
            _make_entry("dir_b/img_110.jpg", "2025-07-07T11:30:00+02:00"),
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(entries), encoding="utf-8")
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        f = new_dir / "img_105.jpg"
        f.write_text("data")
        target_ts = datetime(2025, 7, 7, 9, 0, 0, tzinfo=UTC).timestamp()
        os.utime(f, (target_ts, target_ts))
        # With --seq only: both dirs match (same seq range)
        args_seq = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=True,
            prefix=False,
        )
        locate.run(args_seq)
        captured = capsys.readouterr()
        assert "dir_a" in captured.out
        assert "dir_b" in captured.out
        # With --seq --prefix: only dir_b matches (img_ prefix)
        args_prefix = argparse.Namespace(
            directory=str(new_dir),
            json_files=[str(json_file)],
            list=False,
            context=5,
            filter=None,
            output=None,
            seq=True,
            prefix=True,
        )
        locate.run(args_prefix)
        captured = capsys.readouterr()
        assert "dir_b" in captured.out
        assert "dir_a" not in captured.out
