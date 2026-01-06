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
# Using Poetry
poetry run mkjson --help
poetry run mkversion --help
poetry run setmtime --help
poetry run verify --help

# Or activate shell first
poetry shell
mkjson --help
mkversion --help
setmtime --help
verify --help
```

## 4. Run Your First Commands

### Generate metadata for a photo directory

```bash
# Create a test directory with some files
mkdir -p test_photos
echo "test image 1" > test_photos/photo1.jpg
echo "test image 2" > test_photos/photo2.jpg

# Generate JSON metadata
mkjson test_photos

# This creates test_photos.json with checksums, sizes, and timestamps
cat test_photos.json
```

### Generate version info from JSON files

```bash
# Create a directory with JSON files (from mkjson)
mkdir -p archive
cp test_photos.json archive/

# Generate version information
mkversion archive

# Or save to file
mkversion archive --output archive/.version.json
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
│   ├── mkjson.py        # Generate file metadata JSON
│   ├── mkversion.py     # Generate archive version info
│   ├── setmtime.py      # Update file timestamps from metadata
│   └── verify.py        # Verify archive integrity
├── tests/               # Test files (120 tests, 85.46% coverage)
│   ├── test_mkjson.py   # Tests for mkjson (32 tests)
│   ├── test_mkversion.py # Tests for mkversion (19 tests)
│   ├── test_setmtime.py  # Tests for setmtime (26 tests)
│   └── test_verify.py    # Tests for verify (43 tests)
├── Makefile             # Development commands
└── pyproject.toml       # Project configuration
```

## 7. Common Use Cases

### Archive a photo collection

```bash
# 1. Scan your entire photo collection
mkjson /photos/2024 --time-zone Europe/Warsaw

# 2. Generate version info
mkversion /photos --output /photos/.version.json

# 3. Verify integrity
verify /photos

# 4. Full verification with checksums (time-consuming)
verify /photos --all --check-timestamps
```

### Restore timestamps after copying from archive

```bash
# After copying files from backup, timestamps may be wrong
# Use setmtime to restore original timestamps

# Preview changes first
setmtime /photos/2024.json --dry-run

# Update directory timestamps only (fast)
setmtime /photos/2024.json

# Update all file and directory timestamps
setmtime /photos/2024.json --all
```

### Merge multiple photo directories

```bash
# Scan first directory
mkjson /photos/january

# Scan second directory and merge
mkjson /photos/february --merge january.json

# Result: february.json contains both january and february photos
```

### Sort photos numerically

```bash
# If your photos are named: IMG_001.jpg, IMG_002.jpg, etc.
mkjson /photos --sort-by-number

# Results will be sorted: 1, 2, 3... instead of 1, 10, 11, 2, 20...
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

## 10. Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Explore the source code in `photos_manager/`
- Check test examples in `tests/`
- Try the commands with your own photo collections!

## Useful Commands Reference

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies |
| `make test` | Run tests |
| `make coverage` | Test coverage report |
| `make lint` | Check code quality |
| `make format` | Format code |
| `make type-check` | Run type checker |
| `make check-all` | Run all checks |
| `make clean` | Clean generated files |
| `make docs-serve` | Preview documentation |

Happy coding! 🚀
