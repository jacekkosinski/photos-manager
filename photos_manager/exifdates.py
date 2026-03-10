"""exifdates - Detect and fix JSON date fields from EXIF/GPS data.

Compares EXIF and GPS timestamps against JSON metadata dates and reports
discrepancies. With --fix, updates JSON date fields in place. The tool
uses a hierarchy of date sources: GPS timestamp (most accurate), EXIF
with GPS-derived clock drift correction, EXIF alone, and neighbour
interpolation for files without EXIF (e.g. MOV).

After running with --fix, use ``photos fixdates`` to propagate the
corrected JSON dates to file and directory timestamps.

Usage:
    photos exifdates archive.json
    photos exifdates archive.json --fix
    photos exifdates archive.json --radius 5 --gps-radius 20
    photos exifdates archive.json --time-zone Europe/London
"""

import argparse
import json
import os
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from photos_manager.common import load_json

# Optional EXIF support
try:
    import piexif

    _EXIF_AVAILABLE = True
except ImportError:  # pragma: no cover
    _EXIF_AVAILABLE = False

# Std-dev threshold (seconds) above which an offset is considered unstable (~)
_GPS_STD_THRESHOLD = 30.0

# Column width for tag alignment (len("[EXIF+GPS~]") + 1)
_TAG_WIDTH = 12

# Correction result: (tag, new_date_iso, info_dict) or None for no change
CorrectionResult = tuple[str, str, dict[str, Any]] | None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def parse_gps_datetime(gps_date: bytes, gps_time: tuple[tuple[int, int], ...]) -> datetime | None:
    """Parse GPS date and time fields into a UTC datetime.

    Args:
        gps_date: GPSDateStamp bytes, e.g. ``b"2023:05:14"``.
        gps_time: GPSTimeStamp as rational tuples,
            e.g. ``((9, 1), (23, 1), (45, 1))`` for 09:23:45 UTC.

    Returns:
        UTC datetime or None if the fields cannot be parsed.

    Examples:
        >>> parse_gps_datetime(b"2023:05:14", ((9, 1), (23, 1), (45, 1)))
        datetime.datetime(2023, 5, 14, 9, 23, 45, tzinfo=datetime.timezone.utc)
    """
    try:
        date_str = gps_date.decode("ascii").strip()
        if not date_str:
            return None
        year_s, month_s, day_s = date_str.split(":")
        (h_num, h_den), (m_num, m_den), (s_num, s_den) = gps_time
        hour = h_num // h_den
        minute = m_num // m_den
        second = s_num // s_den
        return datetime(int(year_s), int(month_s), int(day_s), hour, minute, second, tzinfo=UTC)
    except (ValueError, ZeroDivisionError, AttributeError, TypeError):
        return None


def compute_rolling_stats(
    offsets: list[tuple[int, int]],
    center: int,
    radius: int,
) -> tuple[float, float] | None:
    """Compute mean and population std-dev of offsets within a window.

    Args:
        offsets: List of (index, offset_seconds) pairs.
        center: Centre index of the window.
        radius: Half-width of the window (inclusive).

    Returns:
        ``(mean, std_dev)`` or None if no entries fall within the window.

    Examples:
        >>> compute_rolling_stats([(0, 3600), (1, 3600)], center=0, radius=2)
        (3600.0, 0.0)
    """
    window = [off for idx, off in offsets if abs(idx - center) <= radius]
    if not window:
        return None
    mean = statistics.mean(window)
    std = statistics.pstdev(window)
    return float(mean), float(std)


def format_report_line(
    filename: str,
    tag: str,
    old_dt: datetime,
    new_dt: datetime,
    info: dict[str, Any],
) -> str:
    """Format a single report line for a corrected file.

    Args:
        filename: Basename of the file (no directory).
        tag: Confidence tag, e.g. ``"[GPS]"``, ``"[EXIF+GPS]"``.
        old_dt: Original (JSON) datetime (naive, local).
        new_dt: Corrected datetime (naive, local).
        info: Tag-specific data dict (see module docstring for keys).

    Returns:
        Formatted report line string.

    Examples:
        >>> old = datetime(2023, 5, 14, 10, 23, 45)
        >>> new = datetime(2023, 5, 14, 11, 23, 45)
        >>> line = format_report_line("f.JPG", "[EXIF]", old, new, {})
        >>> "(delta: +3600s)" in line
        True
    """
    delta_s = int((new_dt - old_dt).total_seconds())
    delta_str = f"+{delta_s}s" if delta_s >= 0 else f"{delta_s}s"
    if old_dt.date() != new_dt.date():
        old_str = f"{old_dt:%Y-%m-%d %H:%M:%S}"
        new_str = f"{new_dt:%Y-%m-%d %H:%M:%S}"
    else:
        old_str = f"{old_dt:%H:%M:%S}"
        new_str = f"{new_dt:%H:%M:%S}"
    core = f"{filename}  {tag:<{_TAG_WIDTH}}  {old_str} → {new_str} (delta: {delta_str})"

    if tag == "[GPS]":
        exif_str = info["exif_dt"].strftime("%H:%M:%S")
        d = info["delta"]
        d_str = f"+{d}s" if d >= 0 else f"{d}s"
        return f"{core} [EXIF {exif_str}, delta: {d_str}]"

    if tag in ("[EXIF+GPS]", "[EXIF+GPS~]"):
        exif_str = info["exif_dt"].strftime("%H:%M:%S")
        off = info["offset"]
        off_str = f"+{off}s" if off >= 0 else f"{off}s"
        std = round(info["std"])
        return f"{core} [EXIF {exif_str}, offset: {off_str} std: {std}s]"

    if tag in ("[INT]", "[INT~]"):
        off = info["offset"]
        off_str = f"+{off}s" if off >= 0 else f"{off}s"
        std = round(info["std"])
        return f"{core} [offset: {off_str} std: {std}s]"

    return core  # [EXIF] — no extra info


# ---------------------------------------------------------------------------
# EXIF reading
# ---------------------------------------------------------------------------


def parse_exif_date(date_str: str) -> datetime | None:
    """Parse an EXIF date string to a naive datetime.

    EXIF dates are in format ``YYYY:MM:DD HH:MM:SS``, optionally with
    sub-seconds separated by a dot.

    Args:
        date_str: EXIF date string to parse.

    Returns:
        Naive datetime object, or None if parsing fails.

    Examples:
        >>> parse_exif_date("2025:01:24 15:30:45")
        datetime.datetime(2025, 1, 24, 15, 30, 45)
        >>> parse_exif_date("invalid")
    """
    if not date_str:
        return None
    date_str = date_str.replace("\x00", "").strip()
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        pass
    try:
        if "." in date_str:
            return datetime.strptime(date_str.split(".")[0], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        pass
    return None


def read_file_exif(file_path: str) -> tuple[datetime | None, datetime | None]:
    """Read EXIF DateTimeOriginal and GPS timestamp from a file.

    Args:
        file_path: Absolute path to the image file.

    Returns:
        Tuple of ``(exif_datetime, gps_datetime_utc)``.
        Either element may be None if not available or on read error.
        ``exif_datetime`` is naive (local camera time).
        ``gps_datetime_utc`` is timezone-aware UTC.

    Examples:
        >>> exif_dt, gps_dt = read_file_exif("/path/to/photo.jpg")
    """
    if not _EXIF_AVAILABLE:  # pragma: no cover
        return None, None

    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        return None, None

    exif_dt: datetime | None = None
    gps_dt: datetime | None = None

    # DateTimeOriginal
    exif_ifd = exif_dict.get("Exif", {})
    dt_bytes = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
    if dt_bytes:
        exif_dt = parse_exif_date(dt_bytes.decode("ascii", errors="replace"))

    # GPS timestamp
    gps_ifd = exif_dict.get("GPS", {})
    gps_date_bytes = gps_ifd.get(piexif.GPSIFD.GPSDateStamp)
    gps_time_rationals = gps_ifd.get(piexif.GPSIFD.GPSTimeStamp)
    if gps_date_bytes and gps_time_rationals:
        gps_dt = parse_gps_datetime(gps_date_bytes, gps_time_rationals)

    return exif_dt, gps_dt


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def compute_corrections(
    entries: list[dict[str, str | int]],
    exif_data: list[tuple[datetime | None, datetime | None]],
    time_zone: str,
    radius: int,
    gps_radius: int,
) -> list[CorrectionResult]:
    """Determine date corrections for each entry.

    Args:
        entries: JSON metadata entries (with ``date`` and ``path`` fields).
        exif_data: Parallel list of ``(exif_datetime, gps_datetime_utc)``
            per entry; either element may be None.
        time_zone: IANA timezone name for GPS UTC→local conversion.
        radius: Neighbour window half-width for INT interpolation.
        gps_radius: Rolling-average window half-width for GPS drift.

    Returns:
        List of CorrectionResult (one per entry).  None means no change.
        Non-None entries are ``(tag, new_date_iso, info_dict)``.

    Examples:
        >>> compute_corrections([], [], "Europe/Warsaw", 5, 20)
        []
    """
    tz = ZoneInfo(time_zone)

    # Build GPS drift series: (index, offset_seconds) for entries with both EXIF+GPS
    gps_drift_series: list[tuple[int, int]] = []
    for i, ((exif_dt, gps_dt), _entry) in enumerate(zip(exif_data, entries, strict=False)):
        if exif_dt is not None and gps_dt is not None:
            gps_local_naive = gps_dt.astimezone(tz).replace(tzinfo=None)
            drift = int((gps_local_naive - exif_dt).total_seconds())
            gps_drift_series.append((i, drift))

    # Pass 1: corrections for entries with EXIF
    corrections: list[CorrectionResult] = []
    effective_offsets: list[tuple[int, int]] = []  # (index, delta_from_json) for INT

    for i, ((exif_dt, gps_dt), entry) in enumerate(zip(exif_data, entries, strict=False)):
        json_dt = datetime.fromisoformat(str(entry["date"])).astimezone(tz)

        if gps_dt is not None:
            gps_local = gps_dt.astimezone(tz)
            offset_from_json = int((gps_local - json_dt).total_seconds())
            if abs(offset_from_json) < 1:
                corrections.append(None)
                effective_offsets.append((i, 0))
                continue
            gps_naive = gps_local.replace(tzinfo=None)
            gps_exif_delta = int((gps_naive - exif_dt).total_seconds()) if exif_dt else 0
            corrections.append(
                ("[GPS]", gps_local.isoformat(), {"exif_dt": exif_dt, "delta": gps_exif_delta})
            )
            effective_offsets.append((i, offset_from_json))
            continue

        if exif_dt is not None:
            rolling = compute_rolling_stats(gps_drift_series, center=i, radius=gps_radius)
            if rolling is not None:
                mean_drift, std = rolling
                corrected_naive = exif_dt + timedelta(seconds=round(mean_drift))
                new_dt = corrected_naive.replace(tzinfo=tz)
            else:
                new_dt = exif_dt.replace(tzinfo=tz)
                std = 0.0
                mean_drift = 0.0

            offset_from_json = int((new_dt - json_dt).total_seconds())
            if abs(offset_from_json) < 1:
                corrections.append(None)
                effective_offsets.append((i, 0))
                continue

            if rolling is not None:
                tag = "[EXIF+GPS]" if std <= _GPS_STD_THRESHOLD else "[EXIF+GPS~]"
                info: dict[str, Any] = {"exif_dt": exif_dt, "offset": round(mean_drift), "std": std}
            else:
                tag = "[EXIF]"
                info = {}

            corrections.append((tag, new_dt.isoformat(), info))
            effective_offsets.append((i, offset_from_json))
            continue

        # No EXIF — placeholder; INT pass will fill in
        corrections.append(None)
        effective_offsets.append((i, 0))

    # Pass 2: INT corrections for entries without EXIF
    non_zero_offsets = [(idx, off) for idx, off in effective_offsets if off != 0]
    for i, ((exif_dt, gps_dt), entry) in enumerate(zip(exif_data, entries, strict=False)):
        if exif_dt is not None or gps_dt is not None:
            continue  # already handled
        rolling = compute_rolling_stats(non_zero_offsets, center=i, radius=radius)
        if rolling is None:
            continue
        mean_off, std = rolling
        json_dt = datetime.fromisoformat(str(entry["date"])).astimezone(tz)
        new_dt = json_dt + timedelta(seconds=round(mean_off))
        count = sum(1 for idx, _ in non_zero_offsets if abs(idx - i) <= radius)
        tag = "[INT]" if std <= _GPS_STD_THRESHOLD else "[INT~]"
        corrections[i] = (
            tag,
            new_dt.isoformat(),
            {"offset": round(mean_off), "count": count, "std": std},
        )

    return corrections


# ---------------------------------------------------------------------------
# JSON update
# ---------------------------------------------------------------------------


def apply_corrections(json_file: str, corrections: list[CorrectionResult]) -> None:
    """Write corrected dates back to a JSON file, preserving all other data.

    Field order within each entry and entry order in the file are preserved.

    Args:
        json_file: Path to the JSON metadata file to update.
        corrections: List of CorrectionResult (one per entry).
            None entries are skipped; non-None entries provide the new date.

    Examples:
        >>> apply_corrections("archive.json", [None])  # no changes
    """
    path = Path(json_file)
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry, correction in zip(data, corrections, strict=False):
        if correction is not None:
            _, new_date, _ = correction
            entry["date"] = new_date
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Configure argument parser for exifdates command.

    Args:
        parser: ArgumentParser instance to configure with exifdates arguments.
    """
    parser.add_argument(
        "json_file",
        type=str,
        help="Path to JSON metadata file to check",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Update JSON date fields in place (dry-run by default)",
    )
    parser.add_argument(
        "-r",
        "--radius",
        type=int,
        default=5,
        metavar="N",
        help="Neighbour window half-width for non-EXIF file interpolation (default: 5)",
    )
    parser.add_argument(
        "-g",
        "--gps-radius",
        type=int,
        default=20,
        dest="gps_radius",
        metavar="N",
        help="Rolling-average window half-width for GPS drift calculation (default: 20)",
    )
    parser.add_argument(
        "-z",
        "--time-zone",
        default="Europe/Warsaw",
        dest="time_zone",
        metavar="TZ",
        help="Timezone for GPS UTC→local conversion (default: Europe/Warsaw)",
    )


def run(args: argparse.Namespace) -> int:
    """Execute exifdates command with parsed arguments.

    Reads EXIF and GPS timestamps from archive files, compares them with
    JSON metadata dates, and reports discrepancies.  With --fix, updates
    the JSON dates in place (then run ``photos fixdates`` to propagate to
    the filesystem).

    Args:
        args: Parsed arguments with fields: json_file, fix, radius,
            gps_radius, time_zone.

    Returns:
        os.EX_OK (0) on success, 1 on error.

    Examples:
        >>> args = argparse.Namespace(json_file="archive.json", fix=False,
        ...     radius=5, gps_radius=20, time_zone="Europe/Warsaw")
        >>> run(args)  # doctest: +SKIP
        0
    """
    json_path = Path(args.json_file)
    if not json_path.exists():
        raise SystemExit(f"Error: '{args.json_file}' does not exist")

    try:
        entries = load_json(args.json_file)
    except SystemExit as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    json_dir = json_path.parent

    exif_data: list[tuple[datetime | None, datetime | None]] = []
    for entry in entries:
        file_path = json_dir / str(entry.get("path", ""))
        exif_dt, gps_dt = read_file_exif(str(file_path))
        exif_data.append((exif_dt, gps_dt))

    corrections = compute_corrections(
        entries, exif_data, args.time_zone, args.radius, args.gps_radius
    )

    changed = 0
    for entry, correction in zip(entries, corrections, strict=False):
        if correction is None:
            continue
        tag, new_date, info = correction
        filename = Path(str(entry.get("path", ""))).name
        old_dt_aware = datetime.fromisoformat(str(entry["date"]))
        new_dt_aware = datetime.fromisoformat(new_date)
        old_dt_naive = old_dt_aware.replace(tzinfo=None)
        new_dt_naive = new_dt_aware.replace(tzinfo=None)
        print(format_report_line(filename, tag, old_dt_naive, new_dt_naive, info))
        changed += 1

    print(f"\n{changed} change(s) detected in {len(entries)} entries.")

    if args.fix and changed:
        apply_corrections(args.json_file, corrections)
        print("JSON updated. Run 'photos fixdates' to propagate to filesystem.")
    elif not args.fix and changed:
        print("Dry-run: use --fix to apply changes.")

    return os.EX_OK
