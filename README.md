# EdgeTX Package Spec

This repository is the canonical specification for EdgeTX packages: the
`edgetx.yml` manifest that package authors write, and the on-card state that
package management tooling maintains.

This README is an overview. It is **not normative** — see
[Scope and conformance](#scope-and-conformance) below.

**Start here:**

| You are | Read |
|---|---|
| Making your Lua scripts installable | [docs/GettingStarted.md](./docs/GettingStarted.md) |
| Building tooling — a CLI, browser tool, or firmware | [docs/Manifest.md](./docs/Manifest.md) and [docs/State.md](./docs/State.md), then [docs/Implementation.md](./docs/Implementation.md) |
| Proposing a change to the specification | [CONTRIBUTING.md](./CONTRIBUTING.md) |

## Repository layout

| Path | What it is |
|---|---|
| [`docs/Manifest.md`](./docs/Manifest.md) | **Normative.** The `edgetx.yml` manifest format. |
| [`docs/State.md`](./docs/State.md) | **Normative.** The state files written to the SD card. |
| [`schema/edgetx-manifest.v1.json`](./schema/edgetx-manifest.v1.json) | **Normative.** Machine-checkable subset of the manifest format. |
| [`schema/edgetx-state.v1.json`](./schema/edgetx-state.v1.json) | **Normative.** Machine-checkable subset of the state format. |
| [`docs/Implementation.md`](./docs/Implementation.md) | Guidance for tooling authors — algorithms and worked examples. |
| [`docs/GettingStarted.md`](./docs/GettingStarted.md) | Guide for package authors writing their first manifest. |
| [`conformance/`](./conformance/) | Manifest fixtures, state fixtures, [`file-lists/`](./conformance/file-lists/), and the validator that checks them and every example in these docs. |
| [`CHANGELOG.md`](./CHANGELOG.md) | Changes to this specification. |

Tooling lives separately, in
[`EdgeTX/edgetx-package-tools`](https://github.com/EdgeTX/edgetx-package-tools).
Command examples in these documents use that tool's CLI, `edgetx-cli`.

## Scope and conformance

Normative: `docs/Manifest.md`, `docs/State.md`, and the two JSON Schemas.
Together they define what an implementation must do.

Non-normative: this README, `docs/Implementation.md` and
`docs/GettingStarted.md`. Where they appear to disagree with a normative
document, the normative document wins.

The specification covers:

- package identity, metadata and versioning
- content sections: `libraries`, `tools`, `widgets`, `telemetry`, `functions`,
  `mixes`, `sounds`, `images`, `themes`, `files`
- source and destination path rules
- dependencies on other packages (`requires`)
- hardware capability requirements and firmware version constraints
- hardware variants of one package
- multiple packages in one repository, each with its own manifest
- the state tooling keeps on the SD card to make update and remove correct

## A manifest at a glance

```yaml
edgetx_format_version: "1.0"

package:
  id: github.com/ExpressLRS/Lua-Scripts
  name: ExpressLRS
  version: "3.1.2"
  description: ExpressLRS Lua scripts and widgets for EdgeTX
  license: GPL-3.0-only
  min_edgetx_version: "2.12.0"

libraries:
  - name: ELRS
    path: SCRIPTS/ELRS

tools:
  - name: ExpressLRS
    path: SCRIPTS/TOOLS/ExpressLRS

widgets:
  - name: ELRSTelemetry
    path: WIDGETS/ELRSTelemetry
```

`id` is where the package lives — the git clone URL without the scheme. `path`
is where files are read from, and where they are installed unless `dest` says
otherwise. The top-level `requires` names other packages this one needs.

## Key ideas

**Identity is location.** A package's `id` is its repository URL minus the
scheme, plus any subpackage path. There is no separate registry of names.

**Variants are one package, many builds.** A package with black-and-white and
color LCD builds declares each as a variant with a hardware filter. Tooling
picks the best match for the connected radio at install time. Every variant
manifest is a complete, self-contained manifest sharing the base's `id`.

**Subpackages are separate packages.** Several independent packages can live
in one repository, each with its own manifest and its own `id`, installed and
removed independently.

**State makes removal safe.** Tooling records what it installed, per file,
under `PKG/` on the SD card. That is what lets it update or remove a package
without guessing, and without touching files another package owns.

## Validating

**Validating your own `edgetx.yml`** is covered in
[GettingStarted § Validation](./docs/GettingStarted.md#validation). Use that —
the command below checks *this repository*, not your manifest.

**Checking this repository** (fixtures, schemas, and every example in the docs):

```sh
pip install jsonschema PyYAML
python3 conformance/run_tests.py
```

## Contributing

Specification changes need the affected normative document, the schema, the
conformance fixtures and the changelog updated in the same change set. See
[CONTRIBUTING.md](./CONTRIBUTING.md).

## License

GNU General Public License v2.0 (GPL-2.0). See [LICENSE](./LICENSE).
