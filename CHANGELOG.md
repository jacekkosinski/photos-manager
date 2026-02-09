## v0.4.0 (2026-02-09)

### Feat

- **dedup**: add --move and --copy options for generating file operation
  commands
- **dedup**: add --list option for simple output format
- **dedup**: add tool for finding duplicate and missing files
- **prepare**: add optional EXIF metadata support for setting file timestamps
- **sync**: add explicit permissions and verbose output to commands
- **sync**: add --rewrite-dest option for remote execution
- **sync**: optimize sync by comparing .version.json before loading archives
- **sync**: add archive synchronization tool
- **verify**: add archive directory timestamp verification
- **verify**: enforce ISO 8601 'T' separator in date validation
- **verify**: add file/directory permissions and ownership verification
- **verify**: add ISO 8601 date format validation with timezone colon check
- **verify**: add zero-byte and duplicate checksum detection
- **verify**: add extra files detection with --check-extra-files
- **verify**: add version file timestamp verification with --check-timestamps
- **prepare**: add space-to-underscore conversion in filenames

### Fix

- **mkjson**: use ISO 8601 compliant timezone format in timestamps
- **sync**: preserve directory timestamp ordering in script output
- **sync**: exclude base directory from mkdir and add mtime update
- **sync**: remove path normalization that caused false move operations
- **sync**: improve sync logic based on file metadata comparison
- **sync**: generate commands with absolute paths by passing archive directories
- **sync**: eliminate redundant mkdir operations by checking existing
  directories
- **sync**: remove redundant --dry-run option and optimize write permission
  check
- **verify**: ensure consistent path resolution across JSON file discovery
- **verify**: resolve directory path to absolute in collect_filesystem_files
- **verify**: normalize relative paths to absolute paths based on archive
  directory
- **setmtime**: allow dry-run mode on read-only filesystems

### Refactor

- reduce complexity in sync.py run() function
- rename setmtime tool to fixdates for better clarity
- rename mkversion to manifest for better clarity
- improve code quality and add integration tests
- change default timezone to Europe/Warsaw in index command
- update remaining 'mkjson' references to 'index'
- rename mkjson to index for clarity
- optimize code by consolidating duplicate functions
- standardize SHA-1 to SHA1 notation
- extract common utilities to shared module
- **sync**: use umask instead of explicit mkdir permissions
- **sync**: replace rsync with cp for file copying
- **sync**: improve script output format and remove redundant mtime setting
- **sync**: improve script output format and remove redundant mtime setting
- remove direct execution capability from utility modules

## v0.3.0 (2026-01-15)

### Feat

- **tooling**: add code complexity check to Makefile
- **prepare**: add prepare command for archive preparation
- **config**: enhance pyproject.toml with metadata and stricter linting
- **ci**: enhance pre-commit configuration with better comments and new hooks

### Refactor

- standardize error messages and docstrings across modules

## v0.2.0 (2026-01-07)

### Feat

- **tooling**: add complete commitizen configuration

### Fix

- **tooling**: correct commitizen configuration for dynamic versioning

## v0.1.0 (2026-01-07)

### Fix

- adjust code quality checks for existing codebase

### Refactor

- **build**: centralize version management in __init__.py
