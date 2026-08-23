# State Files Reference

This document describes runtime state files written to the SD card by package operations (`pkg install`, `pkg update`, `pkg remove`).

## Overview

State files are maintained under:

- `EDGETX/PKG/state/installed.yml`
- `EDGETX/PKG/state/files.yml`

### Transaction safety and crash recovery

**CRITICAL implementation requirement**: All operations (install, update, remove) must be crash-safe and support recovery from power loss or interruption.

**Transaction model:**

Each operation must follow an atomic transaction pattern:

1. **Prepare**: Create a transaction record in `EDGETX/PKG/state/.txn-<operation-id>.yml` with:
   - `operation`: "install", "update", or "remove"
   - `package_id`: Target package identifier
   - `timestamp`: Operation start time
   - `old_state`: Snapshot of current `installed.yml` and `files.yml` entries for this package
   - `backup_files`: **CRITICAL**: Full backup of all files to be deleted or overwritten, stored in `.backup-<operation-id>/` with relative paths and hashes preserved
   - `staged_files`: List of files to be copied/removed with source paths and hashes
   - `new_state`: Target state after operation completes

2. **Execute**: Perform file operations (copy, delete, backup)
   - **For all operations**: Before any destructive change (deletion, overwrite), back up the existing file bytes and hash to `.backup-<operation-id>/`
   - For update: backup existing package files to backup directory
   - For remove: backup all files before deletion
   - For install: backup any untracked files that the user confirmed can be overwritten
   - For install/update: copy staged files to destinations

3. **Commit**: Write a commit marker to the transaction record (`committed: true`) using an atomic/durable file write

4. **Finalize**: Update `installed.yml` and `files.yml`, then delete transaction record and backups

**Recovery on startup:**

On package manager startup, scan for `.txn-*.yml` files:
- If `committed: false` or absent: rollback (restore all backed-up files, remove staged files, restore old_state)
- If `committed: true`: complete the operation (apply new_state, clean up backups)
- If transaction record is unreadable or corrupted: abort startup and log error - manual recovery required

**Backup location:**

All operations must backup existing files to:
- `EDGETX/PKG/state/.backup-<operation-id>/` 
- Preserve relative paths within backup directory
- Include backup manifest with file hashes for integrity verification
- **CRITICAL**: Never perform destructive operations without complete backup first

## `installed.yml`

Tracks installed packages, selected variant, source/ref, stored constraints, and compatibility status.

```yaml
schema_version: 1
packages:
  - id: github.com/offer-shmuely/lua-scripts/log-viewer
    version: "1.2.0"
    variant: "edgetx.color.yml"         # null when no variants
    installed_at: "2026-08-23T12:40:00Z"
    dev_mode: false                     # true if installed with --dev flag
    source:
      repo: github.com/offer-shmuely/lua-scripts
      ref: "v1.2.0"
      manifest_path: "log-viewer/edgetx.yml"
    constraints:
      min_edgetx_version: "2.12.0"
      max_edgetx_version: "2.13.x"
      capabilities:
        display:
          type: colorlcd
          resolution: "480x272"
    status:
      compatible: true
      code: "OK"
      reason: ""
    last_checked_at: "2026-08-23T12:40:10Z"
```

**Field semantics:**

- `dev_mode`: Boolean indicating whether the package was installed with `--dev` flag (includes `dev: true` content items). Update operations preserve this mode unless explicitly changed with `--dev` (to enable) or `--no-dev` (to disable). Defaults to `false` for packages installed before this field was introduced.

### Compatibility status

`status.code` should use stable machine-readable values:

- `OK`
- `EDGETX_VERSION_TOO_LOW`
- `EDGETX_VERSION_TOO_HIGH`
- `CAPABILITY_MISMATCH`
- `DEPENDENCY_MISSING`
- `DEPENDENCY_INVALID`
- `FILE_CONFLICT`
- `FILE_MODIFIED`

Firmware/CLI should re-check compatibility when firmware version or package set changes.

Compatibility is evaluated against EdgeTX firmware version (`min_edgetx_version`, optional `max_edgetx_version`) and capabilities only.

## `files.yml`

Tracks file ownership and integrity to support safe uninstall/update and conflict checks.

```yaml
schema_version: 1
files:
  - path: "SCRIPTS/TOOLS/LogViewer/main.lua"
    owner_id: "github.com/offer-shmuely/lua-scripts/log-viewer"
    owner_version: "1.2.0"
    owner_variant: "edgetx.color.yml"
    sha256: "..."
  - path: "WIDGETS/yaapu/main.lua"
    owner_id: "github.com/yaapu/FrskyTelemetryScript"
    owner_version: "3.0.1"
    owner_variant: "edgetx.color-touch.yml"
    sha256: "..."
```

## Dependency handling

Dependencies declared in the manifest via the `depends` field reference **local libraries within the same package**. All libraries and content items in a package are installed together, and file ownership is tracked at the package level in `files.yml`. When a package is removed, all its files (including its libraries) are removed together.

## Variant behavior

- Persist selected `variant` path per installed package.
- `pkg update` keeps the current variant unless user explicitly switches via `pkg install`.
- If package becomes incompatible after firmware change, mark status accordingly so firmware/tooling can warn the user and allow explicit override behavior.
