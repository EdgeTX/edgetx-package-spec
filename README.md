# EdgeTX Package Spec

[![Spec](https://img.shields.io/badge/spec-package%20format-blue)](./docs/Manifest.md)
[![State Files](https://img.shields.io/badge/state-files%20reference-blue)](./docs/State.md)
[![License: GPL-2.0](https://img.shields.io/badge/license-GPL--2.0-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)

Specification for the EdgeTX Lua package format.

This repository defines the manifest format, package layout, variant selection model, and runtime state files used by EdgeTX package tooling. It is the canonical reference for package authors and tooling implementers.

## What this repository contains

- `docs/Manifest.md` — the `edgetx.yml` manifest reference
- `docs/State.md` — runtime state file reference
- examples and rules for:
  - package metadata
  - tools, widgets, telemetry, functions, mixes, sounds, and themes
  - libraries and dependencies
  - hardware capability matching
  - package variants
  - subpackages
  - install/update/remove state

## Quick links

- [Manifest reference](./docs/Manifest.md)
- [State files reference](./docs/State.md)

## Overview

An EdgeTX package is described by an `edgetx.yml` manifest stored in the package repository. The manifest tells tooling:

- what the package is
- where its files live in the source tree
- where those files should be installed on the SD card
- what radio hardware the package supports
- whether alternate variants are available
- which libraries or other content items it depends on

The spec also defines the SD-card state files written by package operations so installs can be tracked, updated, and removed safely.

## Core concepts

### Package identity

Each package has a canonical `id` that identifies its repository location:

```yaml
package:
  id: github.com/ExpressLRS/Lua-Scripts
```

For subpackages, the `id` includes the subdirectory path:

```yaml
package:
  id: github.com/offer-shmuely/lua-scripts/log-viewer
```

### Package content types

The manifest can define these content sections:

- `libraries`
- `tools`
- `widgets`
- `telemetry`
- `functions`
- `mixes`
- `sounds`
- `themes`

Each item typically declares:

- `name`
- `path`

and may also define:

- `dest`
- `depends`
- `exclude`
- `dev`

### Source vs destination

- `path` tells tooling where to **read** the files from in the repository
- `dest` optionally tells tooling where to **write** them on the SD card

If `dest` is omitted, the destination defaults to `path`.

### Hardware capabilities

Packages can declare required hardware features such as:

- display type: `bw` or `colorlcd`
- resolution
- touch support

This allows EdgeTX tooling to reject incompatible packages before install.

### Variants

Variants are alternate manifests for the same logical package, typically used for different radio hardware profiles.

The base manifest lists available variants, and tooling chooses the best match automatically from the connected radio’s capabilities. Manual selection is also supported.

### Subpackages

A single repository can contain multiple independent packages, each with its own manifest and package `id`.

This is useful when one repo hosts multiple tools or scripts that should be installed and updated independently.

### Runtime state files

EdgeTX package operations maintain SD-card state under:

- `EDGETX/PKG/state/installed.yml`
- `EDGETX/PKG/state/files.yml`

These files track installed packages, file ownership, compatibility status, and dependency relationships.

## Example manifest

```yaml
package:
  id: github.com/ExpressLRS/Lua-Scripts
  name: ExpressLRS
  description: ExpressLRS Lua scripts and widgets for EdgeTX
  license: GPL-2.0
  min_edgetx_version: "2.12.0"
  max_edgetx_version: "2.13.x"

libraries:
  - name: ELRS
    path: SCRIPTS/ELRS

tools:
  - name: ExpressLRS
    path: SCRIPTS/TOOLS/ExpressLRS
    depends:
      - ELRS

widgets:
  - name: ELRSTelemetry
    path: WIDGETS/ELRSTelemetry
    depends:
      - ELRS
```

## Manifest reference highlights

The manifest specification covers:

- package metadata
- authors, URLs, screenshots, keywords, and license
- source directories and install destinations
- EdgeTX version constraints
- bytecode support via `binary: true`
- device capability requirements
- variant selection behavior
- subpackage layouts
- flat-file fallback layouts for subpackages

See the full reference in [docs/Manifest.md](./docs/Manifest.md).

## State file reference highlights

The state specification covers:

- installed package tracking
- selected variant persistence
- file ownership and integrity tracking
- compatibility status codes
- shared library request tracking
- cleanup rules for update and uninstall

See the full reference in [docs/State.md](./docs/State.md).

## Intended audience

This repository is useful for:

- package authors
- EdgeTX package tooling maintainers
- validator and registry implementers
- anyone building installers, updaters, or package catalogs for EdgeTX

## Contributing

When updating the spec:

- keep examples concrete and reproducible
- prefer machine-readable rules
- document edge cases explicitly
- update related sections when behavior changes
- preserve backward compatibility where possible

## License

This project is licensed under the terms of the GNU General Public License v2.0 (GPL-2.0). See the `LICENSE` file for details.
