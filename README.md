# EdgeTX Package Spec

This repository is the canonical EdgeTX package specification repository, used by package authors and tooling maintainers.

Tooling implementation lives in [`EdgeTX/edgetx-package-tools`](https://github.com/EdgeTX/edgetx-package-tools). This repository defines the specification that tooling must implement.

## Repository contents

- [`docs/GettingStarted.md`](./docs/GettingStarted.md) — quick start guide for package authors
- [`docs/Manifest.md`](./docs/Manifest.md) — normative reference for the `edgetx.yml` manifest format
- [`docs/State.md`](./docs/State.md) — normative reference for runtime state files written by package operations
- [`docs/Implementation.md`](./docs/Implementation.md) — implementation guide with pseudocode for package manager developers
- [`schema/edgetx-manifest.v1.json`](./schema/edgetx-manifest.v1.json) — JSON Schema for manifest validation
- [`conformance/`](./conformance/) — test fixtures and validator for spec compliance

## Scope

This specification defines:

- package identity and metadata
- supported package content sections:
  - `libraries`
  - `tools`
  - `widgets`
  - `telemetry`
  - `functions`
  - `mixes`
  - `sounds`
  - `themes`
- source and destination path rules
- hardware capability constraints
- package variants
- subpackage layouts, including flat-file fallback layouts
- state tracking for install, update, and remove operations

## Overview

An EdgeTX package shall be described by an `edgetx.yml` manifest stored in the package repository. Tooling uses the manifest to determine:

- package identity
- source locations for package content
- SD card installation destinations
- content dependencies
- compatibility with radio hardware
- available package variants

This repository also defines the SD card state files used to track installed packages, selected variants, file ownership, compatibility status, and dependency relationships.

## Core concepts

### Package identity

Each package shall declare a canonical `id` that identifies the repository location:

```yaml
package:
  id: github.com/ExpressLRS/Lua-Scripts
```

For subpackages, the `id` shall include the subdirectory path:

```yaml
package:
  id: github.com/offer-shmuely/lua-scripts/log-viewer
```

### Package content model

The manifest may define the following content sections:

- `libraries`
- `tools`
- `widgets`
- `telemetry`
- `functions`
- `mixes`
- `sounds`
- `themes`

Content entries generally define:

- `name`
- `path`

Content entries may also define:

- `dest`
- `depends`
- `exclude`
- `dev`

### Source and destination paths

- `path` identifies the source location in the package repository.
- `dest` optionally overrides the SD card destination path.

If `dest` is omitted, the installation destination defaults to `path`.

### Hardware capabilities

Packages may declare hardware capability requirements, including:

- display type: `bw` or `colorlcd`
- display resolution
- touchscreen support

Tooling shall use these constraints to detect incompatible packages before installation.

### Variants

Variants define alternate manifests for the same logical package, typically for different radio hardware profiles.

The base manifest declares available variants and their capability filters. Tooling selects the best matching variant from the target radio capabilities unless the user explicitly selects another compatible variant.

### Subpackages

A repository may contain multiple independent packages. Each package has its own manifest and canonical `id`.

### Runtime state files

Package operations maintain state under:

- `EDGETX/PKG/state/installed.yml`
- `EDGETX/PKG/state/files.yml`

These files record installed packages, selected variants, file ownership, compatibility status, and dependency relationships required for safe update and removal behavior.

## Example manifest

```yaml
spec_version: "1.0"
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

## Reference highlights

### Manifest reference

[`docs/Manifest.md`](./docs/Manifest.md) defines:

- package metadata
- authors, URLs, screenshots, keywords, and license fields
- source directories and install destinations
- EdgeTX version constraints
- bytecode support
- radio capability requirements
- variant selection behavior
- subpackage layouts
- flat-file fallback layouts for subpackages

### State reference

[`docs/State.md`](./docs/State.md) defines:

- installed package tracking
- selected variant persistence
- file ownership and integrity tracking
- compatibility status codes
- shared library request tracking
- cleanup behavior for update and remove operations

## Intended consumers

This specification is intended for:

- package authors
- EdgeTX package tooling maintainers
- validators and catalog implementations
- installers, updaters, and related SD card management tools

## Contributing

Specification changes should be proposed with documentation updates in the same change set. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

This repository is licensed under the GNU General Public License v2.0 (GPL-2.0). See [LICENSE](./LICENSE).
