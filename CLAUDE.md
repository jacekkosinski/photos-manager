# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Photos Manager CLI is a Python 3.12+ toolkit for managing photo archives with
utilities for indexing, verification, synchronization, and preparation:

- **index** - Generate JSON metadata with checksums, sizes, and timestamps
- **manifest** - Aggregate metadata into version summaries
- **setmtime** - Restore timestamps from metadata
- **verify** - Verify archive integrity against metadata
- **prepare** - Fix permissions and normalize filenames
- **sync** - Synchronize archives
- **dedup** - Deduplicate files

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

The project has comprehensive test coverage with 508 tests.

```bash
# Run all tests with coverage
poetry run pytest

# Run specific test file
poetry run pytest tests/test_prepare.py

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
poetry run index /path/to/photos
poetry run manifest /path/to/archive
poetry run setmtime /path/to/photos.json
poetry run verify /path/to/archive
poetry run prepare /path/to/directory --dry-run
poetry run sync /source/archive /dest/archive
poetry run dedup archive.json /path/to/scan

# Or after activating virtual environment
poetry shell
index /path/to/photos
manifest /path/to/archive
setmtime /path/to/photos.json --dry-run
verify /path/to/archive --all
prepare /path/to/directory --dry-run
sync /source/archive /dest/archive
dedup archive.json /path/to/scan -d -m
```

## Architecture

All utilities are standalone scripts following unified implementation style:

- Fully type-annotated with strict mypy compliance
- Comprehensive Google-style docstrings
- Complete argument validation with clear error messages
- Designed to be called as CLI tools or imported as modules

### Project Structure

```
photos_manager/
├── __init__.py
├── cli.py             # Main CLI entry point
├── common.py          # Shared utilities
├── dedup.py           # Deduplication tool
├── index.py           # Directory scanner and metadata generator
├── manifest.py       # Version aggregator for JSON files
├── prepare.py         # Directory preparation (permissions, naming)
├── setmtime.py        # Timestamp updater based on metadata
├── sync.py            # Synchronization tool
└── verify.py          # Archive integrity verifier

tests/                 # 508 tests total
├── test_cli.py
├── test_common.py
├── test_dedup.py
├── test_index.py
├── test_manifest.py
├── test_prepare.py
├── test_setmtime.py
├── test_sync.py
└── test_verify.py
```

## Code Style Requirements

- **Python version**: 3.12+
- **Type hints**: Required on all functions (strict mypy mode)
- **Docstrings**: Google-style docstrings required (>= 80% coverage enforced by
  interrogate)
- **Line length**: 100 characters (Ruff)
- **Import sorting**: Enforced by Ruff (isort rules)
- **Path handling**: Use `pathlib.Path` instead of `os.path` (PTH rules)

## Pre-commit Hooks

Pre-commit hooks run automatically on every commit and check:

- Ruff linting and formatting
- mypy strict type checking
- interrogate docstring coverage (>= 80%)
- Xenon code complexity checks (Radon CI)
- File checks (trailing whitespace, large files, etc.)
- Poetry lock file validity
- Security checks with bandit

To run manually: `pre-commit run --all-files`

## Testing Conventions

- Tests use pytest with comprehensive coverage (508 tests)
- Each module has dedicated test file matching the module name
- Test structure includes:
  - Unit tests for individual functions
  - Integration tests for `run()` CLI entry points
  - Edge case and error handling tests
- Coverage is tracked with pytest-cov (reports in htmlcov/)
- Type checking is relaxed in tests (see mypy overrides in pyproject.toml)

## Git Commit Conventions

All commits in this repository should follow these guidelines:

- **Language**: Write commit messages in English
- **Message length**: Provide detailed descriptions spanning multiple lines
  (typically 5-15 lines) that explain:
  - What changes were made
  - Why the changes were necessary
  - Impact on coverage, performance, or functionality (when applicable)
- **Format**: Use conventional commit format (e.g., `feat:`, `fix:`, `test:`,
  `refactor:`, `docs:`)
- **NO AI attribution**: Do not include references to AI assistants, Claude, or
  similar attribution in commit messages
- **Co-Authored-By**: Do not add Co-Authored-By tags for AI assistants

## Common Patterns

### Adding a new CLI utility

1. Create `photos_manager/new_tool.py` with `run()` function
1. Add CLI entry point in `pyproject.toml` under `[project.scripts]`
1. Follow existing patterns from index.py or manifest.py:
   - Use argparse for argument parsing
   - Return `os.EX_OK` on success
   - Raise `SystemExit` with error messages on failure
   - Include comprehensive docstrings
   - Use strict type hints
1. Create `tests/test_new_tool.py` with unit tests
1. Run `make check-all` before committing

### Working with file metadata

The JSON format produced by index contains:

- `path`: Absolute file path (string)
- `sha1`: SHA1 checksum (hex string)
- `md5`: MD5 checksum (hex string)
- `date`: ISO 8601 timestamp with timezone (string)
- `size`: File size in bytes (integer)

This structure is validated by manifest (expects all five fields) and used by
setmtime (requires `path` and `date` fields).
