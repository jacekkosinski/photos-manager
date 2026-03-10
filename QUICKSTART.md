# Quick Start Guide

Get started with Photos Manager CLI in 5 minutes!

## 1. Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/photos-manager-cli.git
cd photos-manager-cli

# Install with Poetry (recommended)
poetry install

# OR with pip
pip install -e .
```

## 2. Setup Pre-commit Hooks

```bash
poetry run pre-commit install
```

## 3. Verify Installation

```bash
# Using Poetry - unified CLI (recommended)
poetry run photos --help
poetry run photos prepare --help
poetry run photos index --help
poetry run photos fixdates --help
poetry run photos manifest --help
poetry run photos verify --help
poetry run photos info --help
poetry run photos sync --help
poetry run photos find --help

# Or activate shell first
poetry shell
photos --help
photos index --help
```

## 4. Run Your First Commands

### Generate metadata for a photo directory

```bash
# Create a test directory with some files
mkdir -p test_photos
echo "test image 1" > test_photos/photo1.jpg
echo "test image 2" > test_photos/photo2.jpg

# Generate JSON metadata using unified CLI
photos index test_photos

# This creates test_photos.json with checksums, sizes, and timestamps
cat test_photos.json
```

### Generate version info from JSON files

```bash
# Create a directory with JSON files (from index)
mkdir -p archive
cp test_photos.json archive/

# Generate version information
photos manifest archive

# Or save to file
photos manifest archive --output archive/.version.json
cat archive/.version.json
```

## 5. Development Commands

```bash
# Run tests
make test

# Check code quality
make check-all

# Format code
make format

# View all available commands
make help
```

## 6. Project Structure

```
photos-manager-cli/
├── photos_manager/       # Main source code
│   ├── __init__.py      # Package initialization
│   ├── cli.py          # Main CLI entry point
│   ├── common.py        # Shared utilities
│   ├── prepare.py       # Fix permissions and filenames
│   ├── index.py         # Generate file metadata JSON
│   ├── fixdates.py      # Update file timestamps
│   ├── manifest.py      # Generate archive manifest
│   ├── verify.py        # Verify archive integrity
│   ├── info.py          # Show archive statistics
│   ├── sync.py          # Synchronization tool
│   └── find.py         # Find duplicates tool
├── tests/               # Test files (535 tests)
│   ├── conftest.py      # Shared fixtures
│   ├── test_cli.py
│   ├── test_common.py
│   ├── test_prepare.py
│   ├── test_index.py
│   ├── test_fixdates.py
│   ├── test_manifest.py
│   ├── test_verify.py
│   ├── test_info.py
│   ├── test_sync.py
│   └── test_find.py
├── Makefile             # Development commands
└── pyproject.toml       # Project configuration
```

## 7. Common Use Cases

### Prepare directory for archiving

```bash
# Fix permissions, normalize filenames (lowercase, no spaces)
# Preview changes first
photos prepare /photos/incoming --dry-run

# Apply fixes
photos prepare /photos/incoming

# With EXIF timestamp restoration (requires: pip install photos-manager-cli[exif])
photos prepare /photos/incoming --use-exif

# Custom owner/group
photos prepare /photos/incoming --owner storage --group storage
```

### Archive a photo collection

```bash
# 1. Scan your entire photo collection
photos index /photos/2024 --time-zone Europe/Warsaw

# 2. Generate version info
photos manifest /photos --output /photos/.version.json

# 3. Verify integrity
photos verify /photos

# 4. Full verification with checksums (time-consuming)
photos verify /photos --all
```

### Merge multiple photo directories

```bash
# Scan first directory
photos index /photos/january

# Scan second directory and merge
photos index /photos/february --merge january.json

# Result: february.json contains both january and february photos
```

### Sort photos numerically

```bash
# If your photos are named: IMG_001.jpg, IMG_002.jpg, etc.
photos index /photos --sort-by-number

# Results will be sorted: 1, 2, 3... instead of 1, 10, 11, 2, 20...
```

### Restore timestamps after copying from archive

```bash
# After copying files from backup, timestamps may be wrong
# Use fixdates to restore original timestamps

# Preview changes first
photos fixdates /photos/2024.json --dry-run

# Update directory timestamps only (fast)
photos fixdates /photos/2024.json

# Update all file and directory timestamps
photos fixdates /photos/2024.json --all
```

### Synchronize archives

```bash
# Preview sync commands without executing (default: dry-run)
photos sync /source/archive /dest/archive

# Execute sync operations for real
photos sync /source/archive /dest/archive --execute
```

### Find duplicates and missing files

```bash
# Find duplicates in scan directory (files that exist in archive)
photos find archive.json /path/to/scan -d

# Find missing files (files in archive but not in scan directory)
photos find archive.json /path/to/scan -m

# Both duplicates and missing
photos find archive.json /path/to/scan -d -m
```

## 8. Before Committing

```bash
# Run all quality checks
make check-all

# Or let pre-commit do it automatically
git add .
git commit -m "feat: add new awesome feature"
```

## 9. Common Issues

### Poetry not found

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### Python version mismatch

Make sure you have Python 3.12+ installed:

```bash
python --version
```

### Pre-commit hooks fail

Run manually to see errors:

```bash
make pre-commit
```

## 10. Building Standalone Binary

For production deployment, build a standalone binary that doesn't require
Python:

```bash
# Install Nuitka
pip install nuitka

# Install build dependencies (Debian/Ubuntu)
sudo apt-get install gcc g++ ccache patchelf

# Build the binary
./build.sh

# Test the binary
./dist/photos --help
./dist/photos index /path/to/photos

# Deploy to target system
scp dist/photos user@server:/usr/local/bin/
```

See [BUILD.md](BUILD.md) for detailed build instructions, deployment guide, and
troubleshooting.

## 11. Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Explore the source code in `photos_manager/`
- Check test examples in `tests/`
- Try the commands with your own photo collections!
- Build and deploy the standalone binary (see [BUILD.md](BUILD.md))

## Useful Commands Reference

| Command           | Description           |
| ----------------- | --------------------- |
| `make install`    | Install dependencies  |
| `make test`       | Run tests             |
| `make coverage`   | Test coverage report  |
| `make lint`       | Check code quality    |
| `make format`     | Format code           |
| `make type-check` | Run type checker      |
| `make check-all`  | Run all checks        |
| `make clean`      | Clean generated files |
| `make docs-serve` | Preview documentation |

Happy coding! 🚀
