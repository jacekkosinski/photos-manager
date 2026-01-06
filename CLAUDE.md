# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Photos Manager CLI is a Python 3.12+ toolkit for managing photo archives. It provides four main utilities:

1. **mkjson** - Scans directories and generates JSON metadata files containing checksums (SHA-1, MD5), file sizes, and timestamps for all files
2. **mkversion** - Aggregates multiple JSON metadata files to generate version information with total size, file count, and integrity hashes
3. **setmtime** - Updates file and directory modification timestamps based on JSON metadata, useful for restoring original timestamps after copying from archives
4. **verify** - Verifies archive integrity by checking files against JSON metadata, including existence, sizes, checksums, and timestamps

## Development Commands

### Setup

```bash
# Install dependencies (Poetry recommended)
poetry install

# Or using pip with virtual environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Testing

```bash
# Run all tests with coverage
poetry run pytest

# Run specific test file
poetry run pytest tests/test_mkjson.py

# Run with verbose output
poetry run pytest -v

# Coverage report (HTML output in htmlcov/)
poetry run pytest --cov --cov-report=html
```

### Code Quality

```bash
# Lint with Ruff
poetry run ruff check .
poetry run ruff check --fix .  # Auto-fix issues

# Format code
poetry run ruff format .

# Type checking (strict mode)
poetry run mypy photos_manager/

# Check docstring coverage (must be >= 80%)
poetry run interrogate -v photos_manager/

# Run all quality checks at once
make check-all
```

### Running Tools

```bash
# Using Poetry
poetry run mkjson /path/to/photos
poetry run mkversion /path/to/archive
poetry run setmtime /path/to/photos.json
poetry run verify /path/to/archive

# Or after activating virtual environment
poetry shell
mkjson /path/to/photos
mkversion /path/to/archive
setmtime /path/to/photos.json --dry-run
verify /path/to/archive --all
```

## Architecture

### Core Utilities

All four utilities (`mkjson.py`, `mkversion.py`, `setmtime.py`, and `verify.py`) are standalone scripts that follow a unified implementation style:

- Fully type-annotated with strict mypy compliance
- Comprehensive Google-style docstrings
- Complete argument validation with clear error messages
- No external libraries for core functionality (only stdlib)
- Designed to be called as CLI tools or imported as modules

### mkjson.py

**Purpose**: Generate metadata JSON files by scanning directory trees

**Key functions**:
- `calculate_checksums(file_path)` - Computes SHA-1 and MD5 checksums using 64KB chunks
- `get_file_info(directory, time_zone)` - Recursively scans directory and collects file metadata
- `extract_numbers(path)` - Extracts numeric patterns for custom sorting
- `main()` - CLI entry point with argument parsing and duplicate detection

**Output format**: JSON array of objects with fields: `path`, `sha1`, `md5`, `date`, `size`

**Key features**:
- Timezone-aware timestamps using `zoneinfo`
- Three sorting modes: by date (default), numeric patterns, or directory structure
- Merge capability to combine with existing JSON files
- Duplicate detection for paths, SHA-1, and MD5 hashes
- Custom field ordering in output (path, sha1, md5, date, size)

### mkversion.py

**Purpose**: Aggregate metadata from multiple JSON files into a version summary

**Key functions**:
- `find_json_files(directory)` - Recursively finds JSON files, excluding `*version.json` files
- `validate_and_process_json(file_paths)` - Validates structure, calculates file hashes, aggregates totals
- `main()` - CLI entry point that generates version string and output

**Output format**: JSON object with version string, totals, timestamps, and file hashes

**Version string format**: `photos-{TB:.3f}-{count%1000}`
- TB: Total size in terabytes (3 decimal places)
- count%1000: Last three digits of total file count

**Key features**:
- Automatically excludes files ending with `version.json` from processing
- Validates that all JSON files contain arrays of objects with required fields
- Calculates SHA-1 hash of each JSON file for integrity verification
- Tracks last modification time across all JSON files
- Can output to file or stdout

### setmtime.py

**Purpose**: Update file and directory timestamps based on JSON metadata

**Key functions**:
- `load_json(file_path)` - Loads and parses JSON metadata file
- `get_newest_files(json_file)` - Groups files by directory and finds newest in each
- `set_files_timestamps(json_file, dry_run)` - Updates individual file timestamps
- `set_dirs_timestamps(newest_files, dry_run)` - Updates directory timestamps
- `set_json_timestamps(json_file, dir_name, newest_entry, dry_run)` - Updates JSON and directory timestamps
- `main()` - CLI entry point with dry-run support

**Expected input**: JSON files created by mkjson with 'path' and 'date' fields

**Key features**:
- Three-level timestamp management: files, directories, and JSON metadata
- Dry-run mode to preview changes without applying them
- Graceful handling of missing or inaccessible files
- Expects JSON filename to match directory name (e.g., `photos.json` → `photos/`)
- Only updates timestamps when they differ from metadata
- Optional `--all` flag to update all individual files (default: directories only)

**Use cases**:
- Restoring original timestamps after copying from archives
- Synchronizing filesystem timestamps with photo metadata
- Ensuring directory timestamps reflect newest content

### verify.py

**Purpose**: Verify archive integrity by checking files against JSON metadata

**Key functions**:
- `find_json_files(directory)` - Finds all JSON metadata files in directory (excluding *version.json)
- `find_version_file(directory)` - Locates .version.json file if present
- `verify_file_entry(entry, verify_checksums)` - Verifies single file: existence, size, optionally checksums
- `verify_timestamps(entry, tolerance_seconds)` - Verifies file mtime matches metadata
- `verify_directory_timestamps(data)` - Verifies directory mtimes match newest file
- `verify_json_file_timestamp(json_file, data)` - Verifies JSON file mtime matches newest entry
- `verify_version_file(version_file, json_files, all_data)` - Verifies version file integrity
- `calculate_checksums(file_path)` - Computes SHA-1 and MD5 for verification
- `main()` - CLI entry point that orchestrates all verification checks

**Expected input**: Directory containing JSON metadata files and optionally .version.json

**Verification levels**:
- **Basic** (default): File existence and size verification
- **With --check-timestamps**: Adds mtime verification for files, directories, and JSON files
- **With --all**: Adds SHA-1 and MD5 checksum verification (time-consuming)
- **With --tolerance N**: Allows N seconds tolerance for timestamp comparisons

**Key features**:
- Comprehensive integrity checking at multiple levels
- Automatic discovery of JSON files and version file in directory
- Progress indicators for large archives during checksum verification
- Detailed error reporting with file-level granularity
- Returns exit code 0 on success, 1 on any verification failure
- Validates version file totals (file_count, total_bytes) and JSON file hashes

**Use cases**:
- Detecting data corruption in long-term archives
- Verifying backup integrity after restore operations
- Checking for missing or modified files
- Validating archive consistency before/after migrations

### Project Structure

```
photos_manager/
├── __init__.py
├── mkjson.py           # Directory scanner and metadata generator
├── mkversion.py        # Version aggregator for JSON files
├── setmtime.py         # Timestamp updater based on metadata
└── verify.py           # Archive integrity verifier

tests/
├── __init__.py
├── test_mkjson.py      # Comprehensive tests for mkjson
└── test_mkversion.py   # Tests for mkversion
```

## Code Style Requirements

- **Python version**: 3.12+
- **Type hints**: Required on all functions (strict mypy mode)
- **Docstrings**: Google-style docstrings required (>= 80% coverage enforced by interrogate)
- **Line length**: 100 characters (Ruff)
- **Import sorting**: Enforced by Ruff (isort rules)
- **Path handling**: Use `pathlib.Path` instead of `os.path` (PTH rules)

## Pre-commit Hooks

Pre-commit hooks run automatically on every commit and check:
- Ruff linting and formatting
- mypy strict type checking
- interrogate docstring coverage (>= 80%)
- File checks (trailing whitespace, large files, etc.)
- Poetry lock file validity
- Security checks with bandit

To run manually: `pre-commit run --all-files`

## Testing Conventions

- Tests use pytest with markers: `unit`, `integration`, `slow`
- Coverage is tracked with pytest-cov (reports in htmlcov/)
- Tests for utilities are in `tests/test_*.py` matching the module name
- Type checking is relaxed in tests (see mypy overrides in pyproject.toml)

## Common Patterns

### Adding a new CLI utility

1. Create `photos_manager/new_tool.py` with `main()` function
2. Add CLI entry point in `pyproject.toml` under `[project.scripts]`
3. Follow existing patterns from mkjson.py or mkversion.py:
   - Use argparse for argument parsing
   - Return `os.EX_OK` on success
   - Raise `SystemExit` with error messages on failure
   - Include comprehensive docstrings
   - Use strict type hints
4. Create `tests/test_new_tool.py` with unit tests
5. Run `make check-all` before committing

### Working with file metadata

The JSON format produced by mkjson contains:
- `path`: Absolute file path (string)
- `sha1`: SHA-1 checksum (hex string)
- `md5`: MD5 checksum (hex string)
- `date`: ISO 8601 timestamp with timezone (string)
- `size`: File size in bytes (integer)

This structure is validated by mkversion (expects all five fields) and used by setmtime (requires `path` and `date` fields).
