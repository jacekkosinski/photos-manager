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
poetry run photos --help

# Or activate shell first
poetry shell
photos --help
```

## 4. Run Your First Command

```bash
photos hello --name "Your Name"
photos version
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
│   ├── cli.py           # CLI entry point
│   └── commands/        # CLI commands (add yours here)
├── tests/               # Test files
├── docs/                # Documentation
└── pyproject.toml       # Project configuration
```

## 7. Adding a New Command

1. **Create command file** in `photos_manager/commands/`:

```python
"""My new command."""


def my_command(option: str) -> None:
    """Do something useful.

    Args:
        option: Some option for the command.
    """
    print(f"Processing: {option}")
```

2. **Register in `cli.py`**:

```python
from photos_manager.commands.my_command import my_command

# Register your command in the CLI
```

3. **Add tests** in `tests/test_my_command.py`:

```python
def test_my_command():
    """Test my new command."""
    # Add your test logic here
    pass
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

- Read the full [README.md](README.md)
- Check [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines
- Browse [documentation](docs/)
- Start building your features!

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
