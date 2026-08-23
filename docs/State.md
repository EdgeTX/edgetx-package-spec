# State Files Reference

This document describes runtime state files written to the SD card by package operations (`pkg install`, `pkg update`, `pkg remove`).

## Overview

State files are maintained under:

- `EDGETX/PKG/state/installed.yml`
- `EDGETX/PKG/state/files.yml`

No transaction journal is used in this model.

## `installed.yml`

Tracks installed packages, selected variant, source/ref, stored constraints, and compatibility status.

```yaml
schema_version: 1
packages:
  - id: github.com/offer-shmuely/lua-scripts/log-viewer
    version: "1.2.0"
    variant: "edgetx.color.yml"         # null when no variants
    installed_at: "2026-08-23T12:40:00Z"
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

### Compatibility status

`status.code` should use stable machine-readable values:

- `OK`
- `EDGETX_VERSION_TOO_LOW`
- `EDGETX_VERSION_TOO_HIGH`
- `CAPABILITY_MISMATCH`
- `DEPENDENCY_MISSING`
- `FILE_CONFLICT`

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
