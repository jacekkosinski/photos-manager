# Photos Manager CLI

Modern command-line tool for managing photo archives built with Python 3.12.

This toolkit provides utilities for generating and managing metadata about photo
collections, including checksum calculation, file tracking, and version
management.

## Features

- 🚀 Modern Python 3.12
- 📝 Type-safe with mypy strict mode
- ✅ Comprehensive testing with pytest (535 tests, 87% coverage)
- 📚 Google-style docstrings with interrogate validation
- 🔧 Pre-commit hooks for code quality
- 🎯 Linting and formatting with Ruff
- 🔐 SHA1 and MD5 checksum generation
- 📦 JSON-based metadata tracking
- 🌍 Timezone-aware timestamps

## Prerequisites

- Python 3.12+
- Poetry (recommended) or pip

## Installation

### Using Poetry (recommended)

```bash
# Install Poetry if you haven't already
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Using pip

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
pip install -e ".[dev]"
```

## Available Commands

The photos-manager CLI provides a unified `photos` command with subcommands for
each tool:

```bash
photos <command> [options]
```

**Available commands:**

- `prepare` - Fix permissions and normalize filenames
- `locate` - Find archive directories for new photos based on timestamps
- `index` - Generate JSON file with file metadata
- `fixdates` - Update file timestamps based on metadata
- `manifest` - Generate archive version information
- `verify` - Verify archive integrity
- `info` - Show archive statistics
- `sync` - Synchronize archives
- `dedup` - Deduplicate files

### Quick Start

```bash
# Show all available commands
photos --help

# Get help for specific command
photos prepare --help
photos index --help
photos fixdates --help
photos manifest --help
photos verify --help
```

### prepare - Prepare Directory for Archiving

Check and fix file permissions, ownership, and filenames before archiving.

```bash
# Preview changes without applying them
photos prepare /path/to/directory --dry-run

# Apply fixes (permissions, ownership, filenames)
photos prepare /path/to/directory

# Process multiple directories
photos prepare /photos/incoming /photos/new --dry-run

# Custom owner/group
photos prepare /path/to/directory --owner storage --group storage

# Restore file timestamps from EXIF metadata (requires: pip install photos-manager-cli[exif])
photos prepare /path/to/directory --use-exif
```

**What it fixes:**

- **File permissions**: Sets files to 644
- **Directory permissions**: Sets directories to 755
- **Ownership**: Sets owner and group (default: `storage:storage`)
- **Filenames**: Converts to lowercase, replaces spaces with underscores

**Notes:**

- Hidden files (starting with `.`) are skipped
- Symbolic links are checked but not followed
- Use `--dry-run` to preview all changes before applying

### locate - Find Archive Directories for New Photos

Find where new photos belong in the archive by matching modification timestamps
against existing archive metadata. Useful for organizing incoming photos into
the correct archive subdirectories.

```bash
# Find target directories for new photos
photos locate /path/to/new/photos archive.json

# Show interleaved timeline with archive context
photos locate /path/to/new/photos archive.json --list

# Show more/less context lines around new files
photos locate /path/to/new/photos archive.json -l -N 3

# Filter archive entries by path substring
photos locate /path/to/new/photos archive.json --filter canon-eos

# Generate shell script with mkdir/mv commands
photos locate /path/to/new/photos archive.json --output move.sh

# Search across multiple archive JSON files
photos locate /path/to/new/photos camera1.json camera2.json
```

**Modes:**

- **Default**: Prints proposed target directory for each new file
- **List** (`-l`): Shows a merged timeline of archive and new files, with N
  archive entries before and after for context
- **Output** (`-o`): Generates an executable shell script with `mkdir -p` and
  `mv -iv` commands

### index - Generate File Metadata

Generate a JSON file containing metadata (checksums, sizes, timestamps) for all
files in a directory.

```bash
# Basic usage - scan directory and create JSON
photos index /path/to/photos

# Merge with existing JSON file
photos index /path/to/new-photos --merge existing.json

# Sort by numeric patterns in filenames
photos index /path/to/photos --sort-by-number

# Specify timezone for timestamps
photos index /path/to/photos --time-zone Europe/Warsaw
```

**Output format:**

```json
[
    {
        "path": "/path/to/photos/image.jpg",
        "sha1": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "md5": "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
        "date": "2025-01-04T12:34:56+01:00",
        "size": 1234567
    }
]
```

### fixdates - Update File Timestamps

Update file and directory modification timestamps based on JSON metadata
(created by index).

```bash
# Preview changes without applying them
photos fixdates photos.json --dry-run

# Update directory timestamps only (default)
photos fixdates photos.json

# Update all file timestamps plus directories
photos fixdates photos.json --all

# Process multiple JSON files
photos fixdates archive1.json archive2.json --all
```

**What it updates:**

- **Individual files** (with `--all`): Sets each file's modification time to
  match the 'date' field in JSON
- **Directories**: Sets each directory's modification time to match its newest
  file
- **JSON file**: Sets the JSON metadata file's modification time to match the
  newest entry

**Use cases:**

- Restore original timestamps after copying files from archives
- Ensure directory timestamps reflect their actual content
- Keep filesystem timestamps synchronized with photo metadata

### manifest - Generate Archive Version Info

Generate version metadata from a collection of JSON files (created by index).

```bash
# Basic usage - output to stdout
photos manifest /path/to/archive

# Save to file
photos manifest /path/to/archive --output version.json
photos manifest /path/to/archive -o .version.json

# Custom archive name prefix (default: "photos")
photos manifest /path/to/uploads --prefix upload
photos manifest /path/to/dups --prefix duplicates
```

**Output format:**

```json
{
    "version": "photos-2.456-234",
    "total_bytes": 2701131776000,
    "file_count": 12234,
    "last_modified": "2025-01-04T12:34:56+01:00",
    "last_verified": "2025-01-04T13:45:23+01:00",
    "files": {
        "archive1.json": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "archive2.json": "f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e7"
    }
}
```

**Version string format:** `{prefix}-{TB:.3f}-{count%1000:03d}`

- prefix: Archive name (default: `photos`, configurable with `-P`/`--prefix`)
- TB: Total size in terabytes (3 decimal places)
- count%1000: Last three digits of total file count (zero-padded to 3 digits)

### verify - Verify Archive Integrity

Verify archive integrity by checking files against JSON metadata.

```bash
# Full verification (timestamps, extra files, permissions checked by default)
photos verify /path/to/archive

# Full verification with checksums (time-consuming)
photos verify /path/to/archive --all

# Skip timestamp verification
photos verify /path/to/archive -t

# Full verification with custom timestamp tolerance
photos verify /path/to/archive --all --tolerance 2
```

**What it verifies:**

- **File existence**: All files listed in JSON metadata exist
- **File sizes**: Actual file sizes match metadata
- **Checksums** (with `--all`): SHA1 and MD5 hashes match metadata
  (time-consuming)
- **Timestamps**: File mtimes match metadata (disable with `-t`)
- **Directory timestamps**: Directory mtimes match newest file (disable with
  `-t`)
- **JSON timestamps**: JSON file mtimes match newest entry (disable with `-t`)
- **Extra files**: Files on disk not in metadata (disable with `-e`)
- **Permissions**: File/directory permissions and ownership (disable with `-p`)
- **Version file**: If .version.json exists, verifies totals and file hashes

**Use cases:**

- Detect data corruption in archives
- Verify backup integrity after restore
- Check for missing or modified files
- Validate archive consistency before/after migration

### info - Show Archive Statistics

Display a human-readable summary of archive contents from JSON index files,
without touching or re-hashing files.

```bash
# Basic summary (file count, total size, date range)
photos info /path/to/archive

# Detailed stats with breakdown by year and file extension
photos info /path/to/archive --stats

# Show more rows in year/extension tables
photos info /path/to/archive --stats --top-n 20
```

### sync - Synchronize Archives

Compare source and destination archives and generate minimal operations to
synchronize them. Matches files by content (SHA1, MD5, size) to detect
moves/renames and prioritize moves over copy+delete.

```bash
# Preview sync operations (default: dry-run)
photos sync /source/archive /dest/archive

# Execute sync operations
photos sync /source/archive /dest/archive --execute

# Save sync commands to a shell script
photos sync /source/archive /dest/archive --output sync.sh

# Skip deletion operations
photos sync /source/archive /dest/archive --no-delete --execute

# Rewrite destination path for remote execution
photos sync /source /dest --rewrite-dest /remote/dest --output sync.sh
```

**Notes:**

- Dry-run by default — use `--execute` to perform real operations
- Requires `.version.json` and JSON metadata in both archives

### dedup - Find Duplicates and Missing Files

Compare files in a directory against archive metadata to identify duplicates
(files already in archive) and missing files (files in archive but not in the
scanned directory). Matches by file size, then SHA1 and MD5 checksums.

```bash
# Find duplicates (files that exist in archive)
photos dedup archive.json /path/to/scan -d

# Find missing files (files in archive but not in scan directory)
photos dedup archive.json /path/to/scan -m

# Both duplicates and missing
photos dedup archive.json /path/to/scan -d -m

# Output one path per line (for piping)
photos dedup archive.json /path/to/scan -d -l

# Generate move commands for duplicates
photos dedup archive.json /path/to/scan -d -M /path/to/duplicates

# Compare from pre-computed PSV file (path|sha1|md5|date|size)
photos dedup archive.json scan_results.psv -d -m

# Also check filenames and timestamps
photos dedup archive.json /path/to/scan -d -f -t
```

### Common Workflows

#### 1. Create archive metadata from scratch

```bash
# Step 1: Prepare directory (fix permissions, ownership, filenames)
photos prepare /photos/2024 --dry-run
photos prepare /photos/2024

# Step 2: Scan photos directory and generate metadata
photos index /photos/2024 --time-zone Europe/Warsaw

# Step 3: Generate version info from all JSON files
photos manifest /photos --output /photos/.version.json
```

#### 2. Add new photos to existing archive

```bash
# Prepare new photos
photos prepare /photos/incoming

# Find where new photos belong in the archive
photos locate /photos/incoming /photos/archive.json --list

# Generate and review move commands
photos locate /photos/incoming /photos/archive.json --output move.sh
cat move.sh
bash move.sh

# Scan and merge with existing metadata
photos index /photos/2025 --merge /photos/2024.json

# Update version info
photos manifest /photos --output /photos/.version.json
```

#### 3. Verify archive integrity

```bash
# Quick verification (file existence and sizes)
photos verify /photos/archive

# Full verification with checksums
photos verify /photos/archive --all

# Show archive statistics
photos info /photos/archive --stats
```

#### 4. Restore timestamps after copying from archive

```bash
# After copying files from backup/archive, their timestamps may be wrong
# Use fixdates to restore original timestamps from metadata

# Preview what will be changed
photos fixdates /photos/restored/2024.json --dry-run

# Update directory timestamps only
photos fixdates /photos/restored/2024.json

# Update all file and directory timestamps
photos fixdates /photos/restored/2024.json --all
```

## Setup Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

## Development

For AI-assisted development with Claude Code, see [CLAUDE.md](CLAUDE.md) for
architecture details and development patterns.

### Project Structure

```
photos-manager-cli/
├── photos_manager/
│   ├── __init__.py        # Package initialization
│   ├── cli.py             # Main CLI entry point
│   ├── common.py          # Shared utilities
│   ├── prepare.py         # Fix permissions and filenames
│   ├── locate.py          # Find archive directories for new photos
│   ├── index.py           # Generate file metadata JSON
│   ├── fixdates.py        # Update file timestamps from metadata
│   ├── manifest.py        # Generate archive version info
│   ├── verify.py          # Verify archive integrity
│   ├── info.py            # Show archive statistics
│   ├── sync.py            # Synchronization tool
│   └── dedup.py           # Deduplication tool
├── tests/                 # 535 tests, 87% coverage
│   ├── conftest.py        # Shared fixtures
│   ├── test_cli.py
│   ├── test_common.py
│   ├── test_prepare.py
│   ├── test_locate.py
│   ├── test_index.py
│   ├── test_fixdates.py
│   ├── test_manifest.py
│   ├── test_verify.py
│   ├── test_info.py
│   ├── test_sync.py
│   └── test_dedup.py
├── pyproject.toml         # Project configuration
├── .pre-commit-config.yaml # Pre-commit hooks config
├── Makefile               # Development commands
├── LICENSE                # MIT License
├── README.md              # This file
└── CLAUDE.md              # Development guide
```

### Running the Tools

#### Using the Unified CLI

The recommended way to use photos-manager is through the unified `photos`
command:

```bash
# Using Poetry
poetry run photos prepare /path/to/incoming
poetry run photos locate /path/to/new /path/to/archive.json
poetry run photos index /path/to/photos
poetry run photos fixdates /path/to/photos.json
poetry run photos manifest /path/to/archive
poetry run photos verify /path/to/archive

# Or after activating the virtual environment
poetry shell
photos prepare /path/to/incoming
photos locate /path/to/new archive.json --list
photos index /path/to/photos
photos fixdates /path/to/photos.json
photos manifest /path/to/archive
photos verify /path/to/archive --all
```

#### Standalone Binary

For production deployment, you can build a standalone binary that doesn't
require Python:

```bash
# Build the binary using Nuitka
./build.sh

# The binary will be created in dist/photos
./dist/photos --help
./dist/photos index /path/to/photos
```

See [BUILD.md](BUILD.md) for detailed build instructions and deployment guide.

### Code Quality Tools

#### Ruff (Linting and Formatting)

```bash
# Check for issues
poetry run ruff check .

# Fix issues automatically
poetry run ruff check --fix .

# Format code
poetry run ruff format .
```

#### Type Checking with mypy

```bash
poetry run mypy photos_manager/
```

#### Docstring Coverage with interrogate

```bash
# Check docstring coverage (must be >= 80%)
poetry run interrogate -v photos_manager/

# Generate badge
poetry run interrogate -v --generate-badge . photos_manager/
```

### Testing

The project has comprehensive test coverage with 535 tests covering all modules.

```bash
# Run all tests
poetry run pytest

# Run with coverage report
poetry run pytest --cov

# Run specific test file
poetry run pytest tests/test_prepare.py

# Run with verbose output
poetry run pytest -v
```

**Test Coverage:** 87% overall with 535 tests across all modules.

### Documentation

```bash
# Serve documentation locally
poetry run mkdocs serve

# Build documentation
poetry run mkdocs build
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Example configuration
DEBUG=false
LOG_LEVEL=INFO
```

### Ruff Configuration

Configured in `pyproject.toml` under `[tool.ruff]`. Current settings:

- Line length: 100
- Target: Python 3.12
- Google-style docstrings required

### mypy Configuration

Configured in `pyproject.toml` under `[tool.mypy]`. Using strict mode.

### pytest Configuration

Configured in `pyproject.toml` under `[tool.pytest.ini_options]`:

- Minimum coverage: configured via pytest-cov
- Test markers: unit, integration, slow

## CI/CD

Pre-commit hooks will run automatically before each commit. They check:

- ✅ Ruff linting and formatting
- ✅ mypy type checking
- ✅ interrogate docstring coverage (>= 80%)
- ✅ Standard file checks (trailing whitespace, file size, etc.)
- ✅ Poetry lock file validity
- ✅ Security checks with bandit

## Code Style

- Follow Google-style docstrings
- Use type hints for all functions
- Keep functions focused and small
- Write tests for all new features
- Maintain >= 80% docstring coverage
- Maintain high test coverage

## Contributing

1. Create a new branch for your feature
1. Make your changes
1. Ensure all tests pass: `poetry run pytest`
1. Ensure code quality: `pre-commit run --all-files`
1. Submit a pull request

## License

MIT License - see LICENSE file for details

## Author

Jacek Kosiński <jacek.kosinski@softflow.tech>
