# Photos Manager CLI

Modern command-line tool for managing photo archives built with Python 3.12.

This toolkit provides utilities for generating and managing metadata about photo collections, including checksum calculation, file tracking, and version management.

## Features

- 🚀 Modern Python 3.12
- 📝 Type-safe with mypy strict mode
- ✅ Comprehensive testing with pytest
- 📚 Google-style docstrings with interrogate validation
- 🔧 Pre-commit hooks for code quality
- 🎯 Linting and formatting with Ruff
- 🔐 SHA-1 and MD5 checksum generation
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

### mkjson - Generate File Metadata

Generate a JSON file containing metadata (checksums, sizes, timestamps) for all files in a directory.

```bash
# Basic usage - scan directory and create JSON
mkjson /path/to/photos

# Merge with existing JSON file
mkjson /path/to/new-photos --merge existing.json

# Sort by numeric patterns in filenames
mkjson /path/to/photos --sort-by-number

# Specify timezone for timestamps
mkjson /path/to/photos --time-zone Europe/Warsaw
```

**Output format:**
```json
[
    {
        "path": "/path/to/photos/image.jpg",
        "sha1": "a1b2c3d4e5f6...",
        "md5": "d4e5f6g7h8i9...",
        "date": "2025-01-04T12:34:56+0100",
        "size": 1234567
    }
]
```

### mkversion - Generate Archive Version Info

Generate version metadata from a collection of JSON files (created by mkjson).

```bash
# Basic usage - output to stdout
mkversion /path/to/archive

# Save to file
mkversion /path/to/archive --output version.json
mkversion /path/to/archive -o .version.json
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
        "archive1.json": "a1b2c3d4e5f6...",
        "archive2.json": "f6e5d4c3b2a1..."
    }
}
```

**Version string format:** `photos-{TB:.3f}-{count%1000}`
- TB: Total size in terabytes (3 decimal places)
- count%1000: Last three digits of total file count

### Common Workflows

#### 1. Create archive metadata from scratch

```bash
# Step 1: Scan photos directory and generate metadata
mkjson /photos/2024 --time-zone Europe/Warsaw

# Step 2: Generate version info from all JSON files
mkversion /photos --output /photos/.version.json
```

#### 2. Add new photos to existing archive

```bash
# Scan new photos and merge with existing metadata
mkjson /photos/2025 --merge /photos/2024.json

# Update version info
mkversion /photos --output /photos/.version.json
```

#### 3. Verify archive integrity

```bash
# Generate current metadata
mkjson /photos/backup --output current.json

# Compare with original (manual diff or use external tools)
diff original.json current.json
```

## Setup Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

## Development

For AI-assisted development with Claude Code, see [CLAUDE.md](CLAUDE.md) for architecture details and development patterns.

### Project Structure

```
photos-manager-cli/
├── photos_manager/
│   ├── __init__.py          # Package initialization
│   ├── mkjson.py           # Generate file metadata JSON
│   └── mkversion.py        # Generate archive version info
├── tests/
│   ├── __init__.py
│   ├── test_mkjson.py      # Tests for mkjson
│   └── test_mkversion.py   # Tests for mkversion
├── pyproject.toml          # Project configuration
├── .pre-commit-config.yaml # Pre-commit hooks config
├── .editorconfig           # Editor settings
├── Makefile                # Development commands
├── LICENSE                 # MIT License
├── README.md               # This file
├── QUICKSTART.md           # Quick start guide
└── CLAUDE.md               # AI assistant development guide
```

### Running the Tools

```bash
# Using Poetry
poetry run mkjson /path/to/photos
poetry run mkversion /path/to/archive

# Or after activating the virtual environment
poetry shell
mkjson /path/to/photos
mkversion /path/to/archive
```

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

```bash
# Run all tests
poetry run pytest

# Run with coverage report
poetry run pytest --cov

# Run only unit tests
poetry run pytest -m unit

# Run specific test file
poetry run pytest tests/test_cli.py

# Run with verbose output
poetry run pytest -v
```

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
2. Make your changes
3. Ensure all tests pass: `poetry run pytest`
4. Ensure code quality: `pre-commit run --all-files`
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Author

Jacek Kosiński <jacek.kosinski@softflow.tech>
