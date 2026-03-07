# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Photos Manager CLI — Python 3.12+ toolkit for photo archive management.

Tools: **prepare** (permissions/filenames), **locate** (find target
directories), **index** (JSON metadata), **fixdates** (restore timestamps),
**manifest** (version summaries), **verify** (integrity check), **info**
(archive statistics), **sync** (synchronize), **dedup** (deduplicate),
**sequences** (detect interleaved camera sequences).

JSON format per file: `path`, `sha1`, `md5`, `date` (ISO 8601 with `+HH:MM`),
`size`.

## Setup

```bash
poetry install                        # install deps
poetry install --extras exif          # with EXIF support
pre-commit install                    # install hooks
```

## Key Commands

```bash
poetry run pytest                     # all tests (~636, ~88% coverage)
poetry run pytest tests/test_X.py    # single file
poetry run pytest -m unit            # unit tests only
poetry run pytest -m integration     # integration tests only
poetry run ruff check --fix .        # lint + autofix
poetry run ruff format .             # format
poetry run mypy photos_manager/      # type check
make check-all                       # all quality checks
pre-commit run --all-files           # all hooks
```

## Architecture

All modules: strict mypy, Google-style docstrings (≥80%), line length 100,
`pathlib.Path` over `os.path`.

Each module has `run(args)` as CLI entry point: returns `os.EX_OK` on success,
raises `SystemExit` on error. Some `run()` functions catch `SystemExit`
internally to continue processing remaining items (e.g. fixdates, verify) —
intentional.

```
photos_manager/
├── cli.py        # CLI entry point
├── common.py     # shared utilities
├── prepare.py / locate.py / index.py / fixdates.py / manifest.py
├── verify.py / info.py / sync.py / dedup.py / sequences.py
└── __init__.py

tests/
├── conftest.py   # shared fixtures: current_user_and_group, verify_args
├── test_cli.py / test_common.py / test_prepare.py / test_index.py
├── test_locate.py / test_fixdates.py / test_manifest.py / test_verify.py
├── test_info.py / test_sync.py / test_dedup.py / test_sequences.py
```

## Testing Conventions

- Unit tests: `@pytest.mark.unit` — test individual functions
- Integration tests: `@pytest.mark.integration` — test `run()` entry points
- 4 EXIF tests skip when piexif/Pillow not installed (expected)
- `chmod(0o000)` tests skip when running as root (`os.getuid() == 0`)
- Coverage tracked in `htmlcov/`; mypy relaxed in tests (see pyproject.toml)

## Git Commits

- English, conventional format: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`,
  `chore:`
- Multi-line messages (5–15 lines): what, why, impact
- No AI attribution, no Co-Authored-By tags

## Version Management

```bash
poetry run cz bump --changelog --increment MINOR  # bump + CHANGELOG + tag
poetry run cz version --project                   # check current version
```

Version must be in sync: `photos_manager/__init__.py` and `pyproject.toml`.

If `cz bump` fails due to pre-commit: stage `CHANGELOG.md`, commit manually, tag
with `git tag -a vX.Y.Z -m "bump: version X → Y"`.

## Adding a New Tool

1. Create `photos_manager/new_tool.py` with `run()`, `setup_parser()`,
   docstrings, type hints
1. Register as subcommand in `photos_manager/cli.py`
1. Create `tests/test_new_tool.py`
1. Run `make check-all`

## Gotchas

- `prepare --use-exif` requires `pip install photos-manager-cli[exif]`
- `.version.json` files are excluded from manifest processing
- `sync` is dry-run by default; use `--execute` to perform real operations
- prepare handles case-insensitive filesystems (macOS) correctly
- ruff/isort enforces aliased imports (`as foo`) in a separate block — do not
  merge them with non-aliased imports from the same module
- Stream routing: errors/warnings → stderr; progress and result summaries →
  stdout
- `validate_args()` helpers must use `raise SystemExit` uniformly, not
  `return False`
- `validate_args()` with `action="append"` flags: use `is not None` / `is None`,
  not truthiness — argparse never produces `[]` here but `default=[]` would
  silently break truthiness guards
- `prepare.iter_directory()` — iterator over visible paths (renamed from
  `scan_directory`)
