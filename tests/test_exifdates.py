"""Tests for photos_manager.exifdates module."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from photos_manager import exifdates

try:
    import piexif

    EXIF_LIBS_INSTALLED = True
except ImportError:
    EXIF_LIBS_INSTALLED = False


# ---------------------------------------------------------------------------
# parse_gps_datetime
# ---------------------------------------------------------------------------


class TestParseGpsDatetime:
    @pytest.mark.unit
    def test_parses_standard_gps_fields(self) -> None:
        """GPS date + time rationals produce UTC datetime."""
        result = exifdates.parse_gps_datetime(b"2023:05:14", ((9, 1), (23, 1), (45, 1)))
        assert result == datetime(2023, 5, 14, 9, 23, 45, tzinfo=UTC)

    @pytest.mark.unit
    def test_parses_fractional_seconds_as_integer(self) -> None:
        """Rational seconds are truncated to whole seconds."""
        result = exifdates.parse_gps_datetime(b"2023:05:14", ((9, 1), (23, 1), (30, 2)))
        assert result == datetime(2023, 5, 14, 9, 23, 15, tzinfo=UTC)

    @pytest.mark.unit
    def test_returns_none_for_invalid_date(self) -> None:
        result = exifdates.parse_gps_datetime(b"invalid", ((9, 1), (0, 1), (0, 1)))
        assert result is None

    @pytest.mark.unit
    def test_returns_none_for_empty_date(self) -> None:
        result = exifdates.parse_gps_datetime(b"", ((0, 1), (0, 1), (0, 1)))
        assert result is None


# ---------------------------------------------------------------------------
# compute_rolling_stats
# ---------------------------------------------------------------------------


class TestComputeRollingStats:
    @pytest.mark.unit
    def test_returns_mean_and_zero_std_for_uniform_offsets(self) -> None:
        offsets = [(0, 3600), (2, 3600), (4, 3600), (6, 3600)]
        result = exifdates.compute_rolling_stats(offsets, center=3, radius=2)
        assert result is not None
        mean, std = result
        assert mean == pytest.approx(3600.0)
        assert std == pytest.approx(0.0)

    @pytest.mark.unit
    def test_includes_only_entries_within_radius(self) -> None:
        """Entries at index 0 and 20 are outside radius=2 from center=6."""
        offsets = [(0, 1000), (5, 3600), (6, 3600), (7, 3600), (20, 9999)]
        result = exifdates.compute_rolling_stats(offsets, center=6, radius=2)
        assert result is not None
        mean, _ = result
        assert mean == pytest.approx(3600.0)

    @pytest.mark.unit
    def test_returns_none_when_no_entries_in_window(self) -> None:
        offsets = [(10, 3600), (20, 3600)]
        result = exifdates.compute_rolling_stats(offsets, center=0, radius=2)
        assert result is None

    @pytest.mark.unit
    def test_single_entry_returns_zero_std(self) -> None:
        result = exifdates.compute_rolling_stats([(5, 3600)], center=5, radius=3)
        assert result is not None
        mean, std = result
        assert mean == pytest.approx(3600.0)
        assert std == pytest.approx(0.0)

    @pytest.mark.unit
    def test_computes_nonzero_std_for_mixed_offsets(self) -> None:
        offsets = [(0, 0), (1, 3600), (2, 7200)]
        result = exifdates.compute_rolling_stats(offsets, center=1, radius=2)
        assert result is not None
        mean, std = result
        assert mean == pytest.approx(3600.0)
        assert std > 0


# ---------------------------------------------------------------------------
# format_report_line
# ---------------------------------------------------------------------------


class TestFormatReportLine:
    @pytest.mark.unit
    def test_formats_gps_line(self) -> None:
        """[GPS] tag is GPS-only fallback (no EXIF); line ends after delta, no bracket info."""
        old_dt = datetime(2023, 5, 14, 10, 23, 45)
        new_dt = datetime(2023, 5, 14, 11, 23, 45)
        line = exifdates.format_report_line("DSC01234.JPG", "[GPS]", old_dt, new_dt, {})
        assert "DSC01234.JPG" in line
        assert "[GPS]" in line
        assert "10:23:45 → 11:23:45" in line
        assert "(delta: +3600s)" in line
        assert line.endswith("(delta: +3600s)")

    @pytest.mark.unit
    def test_formats_exif_plus_gps_line(self) -> None:
        old_dt = datetime(2023, 5, 14, 10, 27, 0)
        new_dt = datetime(2023, 5, 14, 11, 27, 0)
        line = exifdates.format_report_line(
            "DSC01238.JPG",
            "[EXIF+GPS]",
            old_dt,
            new_dt,
            {"exif_dt": datetime(2023, 5, 14, 10, 27, 0), "offset": 3600, "std": 6.0},
        )
        assert "[EXIF+GPS]" in line
        assert "10:27:00 → 11:27:00" in line
        assert "offset: +3600s" in line
        assert "std: 6s" in line

    @pytest.mark.unit
    def test_formats_exif_only_line_no_extra_brackets(self) -> None:
        old_dt = datetime(2023, 5, 14, 10, 29, 0)
        new_dt = datetime(2023, 5, 14, 10, 31, 0)
        line = exifdates.format_report_line("DSC01240.JPG", "[EXIF]", old_dt, new_dt, {})
        assert "[EXIF]" in line
        assert "(delta: +120s)" in line
        assert line.endswith("(delta: +120s)")

    @pytest.mark.unit
    def test_formats_int_line(self) -> None:
        old_dt = datetime(2023, 5, 14, 10, 24, 12)
        new_dt = datetime(2023, 5, 14, 11, 24, 12)
        line = exifdates.format_report_line(
            "MVI_1235.MOV",
            "[INT]",
            old_dt,
            new_dt,
            {"offset": 3600, "count": 8, "std": 6.0},
        )
        assert "[INT]" in line
        assert "offset: +3600s" in line
        assert "std: 6s" in line

    @pytest.mark.unit
    def test_formats_negative_delta(self) -> None:
        old_dt = datetime(2023, 5, 14, 11, 0, 0)
        new_dt = datetime(2023, 5, 14, 10, 0, 0)
        line = exifdates.format_report_line("DSC01234.JPG", "[EXIF]", old_dt, new_dt, {})
        assert "delta: -3600s" in line

    @pytest.mark.unit
    def test_shows_full_date_when_date_changes(self) -> None:
        old_dt = datetime(2013, 1, 1, 23, 59, 59)
        new_dt = datetime(2013, 1, 2, 0, 0, 0)
        line = exifdates.format_report_line("DSC01234.JPG", "[EXIF]", old_dt, new_dt, {})
        assert "2013-01-01 23:59:59 → 2013-01-02 00:00:00" in line

    @pytest.mark.unit
    def test_shows_time_only_when_same_date(self) -> None:
        old_dt = datetime(2023, 5, 14, 10, 0, 0)
        new_dt = datetime(2023, 5, 14, 11, 0, 0)
        line = exifdates.format_report_line("DSC01234.JPG", "[EXIF]", old_dt, new_dt, {})
        assert "10:00:00 → 11:00:00" in line
        assert "2023" not in line


# ---------------------------------------------------------------------------
# compute_corrections
# ---------------------------------------------------------------------------

_TZ = "Europe/Warsaw"
_RADIUS = 5
_GPS_RADIUS = 20


def _make_entry(filename: str, date_iso: str) -> dict[str, Any]:
    return {
        "path": f"2023/05/{filename}",
        "sha1": "abc",
        "md5": "def",
        "date": date_iso,
        "size": 1000,
    }


class TestComputeCorrections:
    @pytest.mark.unit
    def test_no_correction_when_exif_matches_json(self) -> None:
        """File with EXIF matching JSON date produces no correction."""
        entries = [_make_entry("DSC01234.JPG", "2023-05-14T10:23:45+02:00")]
        exif_dt = datetime(2023, 5, 14, 10, 23, 45)
        exif_data = [(exif_dt, None)]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[0] is None

    @pytest.mark.unit
    def test_exif_tag_when_exif_differs_from_json(self) -> None:
        """File where EXIF differs from JSON gets [EXIF] tag."""
        entries = [_make_entry("DSC01234.JPG", "2023-05-14T10:23:45+02:00")]
        exif_dt = datetime(2023, 5, 14, 11, 23, 45)  # 1 hour later than JSON
        exif_data = [(exif_dt, None)]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[0] is not None
        tag, new_date, _ = result[0]
        assert tag == "[EXIF]"
        assert "11:23:45" in new_date

    @pytest.mark.unit
    def test_exif_plus_gps_tag_when_gps_and_exif_available(self) -> None:
        """File with both GPS and EXIF gets [EXIF+GPS] tag; GPS is used for drift, not directly."""
        entries = [_make_entry("DSC01234.JPG", "2023-05-14T10:23:45+02:00")]
        exif_dt = datetime(2023, 5, 14, 10, 23, 45)
        gps_dt = datetime(2023, 5, 14, 9, 23, 45, tzinfo=UTC)  # +02:00 → 11:23:45 local
        exif_data = [(exif_dt, gps_dt)]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[0] is not None
        tag, new_date, _ = result[0]
        assert tag in ("[EXIF+GPS]", "[EXIF+GPS~]")
        assert "11:23:45" in new_date

    @pytest.mark.unit
    def test_exif_plus_gps_tag_when_no_direct_gps_but_neighbors_have_gps(self) -> None:
        """File without GPS but in cluster of GPS files gets [EXIF+GPS] tag."""
        # 5 files: 4 with consistent GPS showing +3600s drift, 1 without GPS
        date = "2023-05-14T10:{:02d}:00+02:00"
        entries = [_make_entry(f"DSC0123{i}.JPG", date.format(i)) for i in range(5)]
        exif_data = [
            (datetime(2023, 5, 14, 10, 0, 0), datetime(2023, 5, 14, 9, 0, 0, tzinfo=UTC)),
            (datetime(2023, 5, 14, 10, 1, 0), datetime(2023, 5, 14, 9, 1, 0, tzinfo=UTC)),
            (datetime(2023, 5, 14, 10, 2, 0), None),  # no GPS — this one
            (datetime(2023, 5, 14, 10, 3, 0), datetime(2023, 5, 14, 9, 3, 0, tzinfo=UTC)),
            (datetime(2023, 5, 14, 10, 4, 0), datetime(2023, 5, 14, 9, 4, 0, tzinfo=UTC)),
        ]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[2] is not None
        tag, new_date, _ = result[2]
        assert tag in ("[EXIF+GPS]", "[EXIF+GPS~]")
        assert "11:02:00" in new_date

    @pytest.mark.unit
    def test_int_tag_for_file_without_exif_with_consistent_neighbors(self) -> None:
        """MOV file without EXIF surrounded by consistent corrections gets [INT] tag."""
        entries = [
            _make_entry("DSC01230.JPG", "2023-05-14T10:00:00+02:00"),
            _make_entry("MVI_1231.MOV", "2023-05-14T10:01:00+02:00"),
            _make_entry("DSC01232.JPG", "2023-05-14T10:02:00+02:00"),
        ]
        exif_data = [
            (datetime(2023, 5, 14, 11, 0, 0), None),  # EXIF differs by +3600s
            (None, None),  # MOV, no EXIF
            (datetime(2023, 5, 14, 11, 2, 0), None),  # EXIF differs by +3600s
        ]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[1] is not None
        tag, new_date, _ = result[1]
        assert tag in ("[INT]", "[INT~]")
        assert "11:01:00" in new_date

    @pytest.mark.unit
    def test_none_for_file_without_exif_and_no_neighbors(self) -> None:
        """MOV file without EXIF and no neighbor corrections is skipped."""
        entries = [_make_entry("MVI_1231.MOV", "2023-05-14T10:01:00+02:00")]
        exif_data = [(None, None)]
        result = exifdates.compute_corrections(entries, exif_data, _TZ, _RADIUS, _GPS_RADIUS)
        assert result[0] is None


# ---------------------------------------------------------------------------
# apply_corrections (JSON update preserves order)
# ---------------------------------------------------------------------------


class TestApplyCorrections:
    @pytest.mark.unit
    def test_updates_only_date_field_preserves_other_fields(self, tmp_path: Path) -> None:
        """apply_corrections updates date in JSON, preserving field and entry order."""
        data = [
            {
                "path": "a.jpg",
                "sha1": "111",
                "md5": "aaa",
                "date": "2023-05-14T10:00:00+02:00",
                "size": 100,
            },
            {
                "path": "b.jpg",
                "sha1": "222",
                "md5": "bbb",
                "date": "2023-05-14T11:00:00+02:00",
                "size": 200,
            },
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data, indent=2))

        corrections = [
            ("[EXIF]", "2023-05-14T11:00:00+02:00", {}),
            None,
        ]
        exifdates.apply_corrections(str(json_file), data, corrections)

        result = json.loads(json_file.read_text())
        assert result[0]["date"] == "2023-05-14T11:00:00+02:00"
        assert result[0]["sha1"] == "111"  # unchanged
        assert list(result[0].keys()) == ["path", "sha1", "md5", "date", "size"]  # order preserved
        assert result[1]["date"] == "2023-05-14T11:00:00+02:00"  # unchanged

    @pytest.mark.unit
    def test_preserves_file_order(self, tmp_path: Path) -> None:
        """Entry order in JSON file is unchanged after apply_corrections."""
        data = [
            {
                "path": f"{i}.jpg",
                "date": "2023-05-14T10:00:00+02:00",
                "sha1": "",
                "md5": "",
                "size": 0,
            }
            for i in range(5)
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data, indent=2))

        corrections = [None] * 5
        exifdates.apply_corrections(str(json_file), data, corrections)

        result = json.loads(json_file.read_text())
        assert [e["path"] for e in result] == [f"{i}.jpg" for i in range(5)]


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.integration
    def test_run_dry_run_prints_report_no_changes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Dry-run mode prints report but does not modify JSON."""
        data = [
            {
                "path": "a.jpg",
                "sha1": "x",
                "md5": "y",
                "date": "2023-05-14T10:00:00+02:00",
                "size": 1,
            }
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data, indent=2))
        original_content = json_file.read_text()

        with patch.object(exifdates, "read_file_exif", return_value=(None, None)):
            args = argparse.Namespace(
                json_file=str(json_file),
                fix=False,
                radius=5,
                gps_radius=20,
                time_zone="Europe/Warsaw",
                no_gps=False,
            )
            result = exifdates.run(args)

        assert result == 0
        assert json_file.read_text() == original_content  # no change

    @pytest.mark.integration
    def test_run_fix_updates_json_when_exif_differs(self, tmp_path: Path) -> None:
        """--fix mode updates JSON date when EXIF differs."""
        data = [
            {
                "path": "a.jpg",
                "sha1": "x",
                "md5": "y",
                "date": "2023-05-14T10:00:00+02:00",
                "size": 1,
            }
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data, indent=2))

        exif_dt = datetime(2023, 5, 14, 11, 0, 0)
        with patch.object(exifdates, "read_file_exif", return_value=(exif_dt, None)):
            args = argparse.Namespace(
                json_file=str(json_file),
                fix=True,
                radius=5,
                gps_radius=20,
                time_zone="Europe/Warsaw",
                no_gps=False,
            )
            exifdates.run(args)

        result = json.loads(json_file.read_text())
        assert "11:00:00" in result[0]["date"]

    @pytest.mark.integration
    def test_run_exits_on_missing_json_file(self, tmp_path: Path) -> None:
        args = argparse.Namespace(
            json_file=str(tmp_path / "nonexistent.json"),
            fix=False,
            radius=5,
            gps_radius=20,
            time_zone="Europe/Warsaw",
            no_gps=False,
        )
        with pytest.raises(SystemExit):
            exifdates.run(args)

    @pytest.mark.integration
    def test_run_no_gps_uses_exif_tag_when_gps_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --no-gps, GPS data is ignored; [EXIF] tag used instead of [EXIF+GPS]."""
        data = [
            {
                "path": "a.jpg",
                "sha1": "x",
                "md5": "y",
                "date": "2023-05-14T10:00:00+02:00",
                "size": 1,
            }
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        exif_dt = datetime(2023, 5, 14, 11, 0, 0)
        gps_dt = datetime(
            2023, 5, 14, 9, 0, 0, tzinfo=UTC
        )  # would give [EXIF+GPS] without --no-gps

        with patch.object(exifdates, "read_file_exif", return_value=(exif_dt, gps_dt)):
            args = argparse.Namespace(
                json_file=str(json_file),
                fix=False,
                radius=5,
                gps_radius=20,
                time_zone="Europe/Warsaw",
                no_gps=True,
            )
            exifdates.run(args)

        out = capsys.readouterr().out
        assert "[EXIF]" in out
        assert "[EXIF+GPS]" not in out

    @pytest.mark.integration
    def test_run_no_gps_skips_gps_only_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With --no-gps, files that only have GPS data (no EXIF) are not corrected."""
        data = [
            {
                "path": "a.jpg",
                "sha1": "x",
                "md5": "y",
                "date": "2023-05-14T10:00:00+02:00",
                "size": 1,
            }
        ]
        json_file = tmp_path / "archive.json"
        json_file.write_text(json.dumps(data))

        gps_dt = datetime(2023, 5, 14, 9, 0, 0, tzinfo=UTC)  # GPS only, no EXIF

        with patch.object(exifdates, "read_file_exif", return_value=(None, gps_dt)):
            args = argparse.Namespace(
                json_file=str(json_file),
                fix=False,
                radius=5,
                gps_radius=20,
                time_zone="Europe/Warsaw",
                no_gps=True,
            )
            exifdates.run(args)

        out = capsys.readouterr().out
        assert "0 change(s)" in out


# ---------------------------------------------------------------------------
# setup_parser
# ---------------------------------------------------------------------------


class TestSetupParser:
    @pytest.mark.unit
    def test_no_gps_flag_long_form(self) -> None:
        """--no-gps flag is registered and defaults to False."""
        parser = argparse.ArgumentParser()
        exifdates.setup_parser(parser)
        args = parser.parse_args(["archive.json", "--no-gps"])
        assert args.no_gps is True

    @pytest.mark.unit
    def test_no_gps_flag_short_form(self) -> None:
        """-G short form is registered and sets no_gps=True."""
        parser = argparse.ArgumentParser()
        exifdates.setup_parser(parser)
        args = parser.parse_args(["archive.json", "-G"])
        assert args.no_gps is True

    @pytest.mark.unit
    def test_no_gps_defaults_to_false(self) -> None:
        """no_gps defaults to False when flag not provided."""
        parser = argparse.ArgumentParser()
        exifdates.setup_parser(parser)
        args = parser.parse_args(["archive.json"])
        assert args.no_gps is False


# ---------------------------------------------------------------------------
# EXIF reading (requires piexif)
# ---------------------------------------------------------------------------


class TestReadFileExif:
    @pytest.mark.unit
    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_reads_datetime_original(self, tmp_path: Path) -> None:
        """Returns EXIF DateTimeOriginal as naive datetime."""
        from PIL import Image

        img_path = tmp_path / "test.jpg"
        img = Image.new("RGB", (10, 10))
        exif_dict = {
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2023:05:14 10:23:45"},
            "GPS": {},
            "1st": {},
        }
        img.save(str(img_path), exif=piexif.dump(exif_dict))

        exif_dt, gps_dt = exifdates.read_file_exif(str(img_path))
        assert exif_dt == datetime(2023, 5, 14, 10, 23, 45)
        assert gps_dt is None

    @pytest.mark.unit
    @pytest.mark.skipif(not EXIF_LIBS_INSTALLED, reason="EXIF libraries not installed")
    def test_reads_gps_timestamp(self, tmp_path: Path) -> None:
        """Returns GPS UTC datetime when GPS fields present."""
        from PIL import Image

        img_path = tmp_path / "test.jpg"
        img = Image.new("RGB", (10, 10))
        exif_dict = {
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2023:05:14 10:23:45"},
            "GPS": {
                piexif.GPSIFD.GPSDateStamp: b"2023:05:14",
                piexif.GPSIFD.GPSTimeStamp: ((8, 1), (23, 1), (45, 1)),
            },
            "1st": {},
        }
        img.save(str(img_path), exif=piexif.dump(exif_dict))

        exif_dt, gps_dt = exifdates.read_file_exif(str(img_path))
        assert exif_dt == datetime(2023, 5, 14, 10, 23, 45)
        assert gps_dt == datetime(2023, 5, 14, 8, 23, 45, tzinfo=UTC)

    @pytest.mark.unit
    def test_returns_none_tuple_for_non_image(self, tmp_path: Path) -> None:
        """Non-image file returns (None, None) without raising."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        exif_dt, gps_dt = exifdates.read_file_exif(str(txt_file))
        assert exif_dt is None
        assert gps_dt is None
