## v0.6.0 (2026-04-03)

### Feat

- add deb target to Makefile
- add GitHub Actions workflow for .deb builds
- add debian packaging with dh-virtualenv
- add QuickTime metadata parser for MOV/MP4 camera and date support
- extend --camera filter to --list mode in find
- add --stat flag with aligned camera statistics table to find
- sort --list output by file modification date ascending
- add --camera flag and camera info to find output
- add -G/--no-gps flag to exifdates to disable GPS timestamps
- redesign display_duplicates output for -d flag
- improve display_missing and display_duplicates output format
- accept multiple source arguments in dedup
- rich --list output with [DUP]/[MISS] tags; -f/-t become filters
- show full date in exifdates output when date changes across midnight
- add summary line to prepare output
- show paths from argument directory in prepare output, use Unicode arrow
- add summary line at end of fixdates output
- add exifdates tool to detect and fix JSON date fields from EXIF/GPS
- always show sequence number decreases in sequences output
- show missing sequence count in sequences summary
- add --gaps flag to sequences to show missing sequence numbers
- add informational output to index, manifest, and fixdates
- manifest -o now resets archive directory mtime
- add sequences tool to detect interleaved photo sequences
- allow multiple -f/--filter patterns with OR logic in locate
- show per-file context in locate -l mode
- add git-clean target to Makefile
- show relative paths with directory name in locate -l mode
- improve --seq matching with prefix filter and tightest-gap scoring
- hybrid matching algorithm with --seq filter in locate
- scan new files recursively in locate
- detect and report ambiguous directory matches in locate
- add locate tool to find archive directories for new photos
- parallelize checksum computation in index
- parallelize checksum verification in verify -a
- default directory argument to current directory for info, manifest, verify
- set 644 permissions on output files from index and manifest
- set manifest output file mtime to last_modified timestamp
- add --prefix option to manifest for custom archive names
- enable verify checks by default with opt-out flags
- standardize CLI options across all tools
- detect empty directories in verify --check-extra-files
- add PSV file input support to dedup command
- add -s shorthand for --stats in info command
- show archive date span in info output
- add info tool for archive statistics

### Fix

- correct dotfile extension extraction and disambiguate entry vars
- use singular 'file' when count is 1 in confirmation messages
- print basename and JSON file count in manifest confirmation message
- use correct path in utime error message for directory
- use .timestamp() for datetime comparison in verify to handle mixed tzinfo
- validate merge data keys before processing in index run()
- correct youngest_mtime name and count MD5 duplicates as errors
- eliminate double load_json per file in fixdates run()
- eliminate TOCTOU in apply_corrections by using already-loaded data
- partition detect_sequences by prefix to prevent cross-camera mixing
- catch TypeError for aware/naive datetime subtraction in find
- update find help text, docs, and apply filters uniformly in --move/--copy
- validate --stat incompatibility and test [DUP] camera filtering in --list
- detect camera from HEIC/HEIF files via embedded EXIF byte scan
- remove target directory existence check from --move and --copy
- change default --tolerance from 1s to 0s in find and verify
- standardize output/communication patterns across tools
- correct three bugs in exifdates
- align date delta condition between display_duplicates and format_list_line
- update --list help text to match actual output format
- handle BrokenPipeError when stdout is closed (pipe to head/less)
- move parse_exif_date into exifdates, remove broken import from prepare
- use JSON date as target timestamp for dirs and json, not stale on-disk mtime
- root directory set twice by fixdates when it contains direct files
- hide decreases section and colon when output is unambiguous
- wrap long directory lists in sequences summary rows
- wrap long gap lists in sequences --gaps output
- preserve directory order by first appearance in sequences summary
- prepare crashes when the target directory itself is renamed
- sequences -l now shows listing for a single sequence
- display absolute path in info archive header
- unify CLI help text for shared options across modules
- remove misleading DRY-RUN message from prepare
- resolve project-wide inconsistencies after recent changes
- zero-pad count component in manifest version string
- use full valid hex values in README checksum examples
- resolve critical and important code quality issues
- improve info output formatting and unit correctness
- pin mdformat to 0.7.21; apply pre-commit autoupdate for other hooks
- correct stdout/stderr routing for duplicate checksum headers in verify

### Refactor

- migrate fixdates output formatting to tabulate
- optimize \_gather_stats in info.py
- simplify info.py and use 4-space table column separator
- simplify \_gather_stats in info.py
- move setup_parser after private helpers in info.py
- split \_print_stats into \_print_summary and \_print_detail
- move date_span to common.py and extend to full range string
- extract format_date_verbose() to common.py
- use tabulate for all table formatting in info.py
- replace module-level common import with named imports in info.py
- inline args.prefix and add Examples output line in manifest.py
- extract DUPLICATE_CHECK_KEYS constant and fix run() Returns doc
- extract write_manifest_json() and default output to .version.json
- remove aliased imports in manifest.py
- extract write_metadata_json() to common.py
- remove get_file_info wrapper, call scan_files directly in index
- rename load_json to load_metadata_json and add entry validation
- cache read_camera_slug results with lru_cache
- avoid redundant stat() in fix_file/dir_permissions dry-run
- pre-compute entry_dates list for bisect_left in locate
- avoid double group_files_by_directory call in find command mode
- resolve uid/gid once per batch in prepare.\_process_ownership
- combine three data passes into one in manifest.validate_and_process_json
- replace string path prefix check with Path.is_relative_to()
- hoist dry_run check out of timestamp-apply loop in fixdates
- replace getattr() with direct args access in locate.run()
- introduce tag constants in exifdates.py
- replace manual json.load in index --merge with common.load_json
- extract format_datetime_change() to deduplicate date delta formatting
- extract scan_files() to common.py, deduplicate scan logic
- centralise version JSON loading in common.py
- replace inline directory validation with common.validate_directory
- deduplicate SHA1 file hashing via common.calculate_checksums_strict
- extract \_exif_correction() to deduplicate EXIF drift logic
- extract format_timestamp_change() to common.py
- rewrite locate algorithm to series-based gap-fitting
- extract \_apply_filters() to deduplicate filtering logic in find
- rename find CLI flags for consistency
- simplify find CLI — remove display_duplicates/display_missing, --stat flag
- remove --fix execution mode from sync; output-only design
- rename --check-filenames/--check-timestamps to --filter-name/--filter-date
- centralise shared utilities to eliminate code duplication
- fix CLI interface inconsistencies across tools
- remove dead code from find.py
- rename dedup tool to find
- use GPS-derived drift to correct EXIF, not raw GPS timestamp
- move TS_FMT and TIME_FMT constants to common
- simplify dedup output, move size/count helpers to common
- simplify prepare.py — extract \_owner_group_names, drop redundant exists()
  checks
- change prepare default to preview-only, add --fix to apply changes
- remove EXIF date functionality from prepare
- rewrite fixdates output — global alignment, uppercase tags, src field
- change fixdates default to preview-only, add --fix to apply changes
- simplify sync.py — remove 39 lines of redundant code
- rename sequences tool to series
- clean up sequences.py based on code review
- use [] for gap lists and {} for directories in sequences output
- standardize output formatting across tools
- eliminate duplication in locate output functions
- unify directory scanning to use Path.rglob
- remove unused tuple element from merged timeline in locate -l

### Perf

- parallelize checksum computation in dedup scan_directory
- pre-compute sequence numbers for faster --seq matching

## v0.5.0 (2026-02-13)

### Fix

- correct return value inconsistencies in fixdates, sync, and index
- correct docstring example, stream routing, and misleading test names

### Refactor

- fix PASS/FAIL stream routing in verify.py and sync.py
- fix remaining code and test inconsistencies (A, B, C, D, F-M)

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
