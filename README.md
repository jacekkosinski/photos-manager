# Photos Manager CLI

Modern command-line tool for managing photos built with Python 3.12.

## Features

- 🚀 Modern Python 3.12
- 📝 Type-safe with mypy strict mode
- ✅ Comprehensive testing with pytest
- 📚 Google-style docstrings with interrogate validation
- 🔧 Pre-commit hooks for code quality
- 🎯 Linting and formatting with Ruff

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

## Setup Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

## Development

### Project Structure

```
photos-manager-cli/
├── photos_manager/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   └── commands/
├── tests/
│   ├── __init__.py
│   └── test_cli.py
├── docs/
├── pyproject.toml
├── .pre-commit-config.yaml
└── README.md
```

### Running the CLI

```bash
# Using Poetry
poetry run photos --help

# Or after activating the virtual environment
photos --help
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
