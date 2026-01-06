# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Photos Manager CLI is a Python 3.12+ toolkit for managing photo archives. It provides two main utilities:

1. **mkjson** - Scans directories and generates JSON metadata files containing checksums (SHA-1, MD5), file sizes, and timestamps for all files
2. **mkversion** - Aggregates multiple JSON metadata files to generate version information with total size, file count, and integrity hashes

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

# Or after activating virtual environment
poetry shell
mkjson /path/to/photos
mkversion /path/to/archive
```

## Architecture

### Core Utilities

Both `mkjson.py` and `mkversion.py` are standalone scripts that follow a unified implementation style:

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

### Project Structure

```
photos_manager/
├── __init__.py
├── mkjson.py           # Directory scanner and metadata generator
└── mkversion.py        # Version aggregator for JSON files

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

This structure is validated by mkversion, which expects all five fields.
