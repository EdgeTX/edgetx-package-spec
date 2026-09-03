# Manifest Reference (`edgetx.yml`)

The `edgetx.yml` file describes a package and its contents. It is authored by
the package maintainer and lives in the package repository.

For the state files written to the SD card by install, update and remove, see
[State Files Reference](./State.md). For non-normative algorithms and worked
examples, see the [Implementation Guide](./Implementation.md).

## Contents

- [Conformance and terminology](#conformance-and-terminology)
- [`edgetx_format_version`](#edgetx_format_version)
  - [Version history](#version-history)
- [Manifest format](#manifest-format)
  - [Top-level fields](#top-level-fields)
  - [Package fields](#package-fields)
  - [Package id](#package-id)
  - [Package references](#package-references)
  - [Package version](#package-version)
- [Content sections](#content-sections)
  - [Content item fields](#content-item-fields)
    - [`exclude` patterns](#exclude-patterns)
- [Source and destination](#source-and-destination)
  - [Path rules](#path-rules)
  - [Source and destination examples](#source-and-destination-examples)
- [Dependencies](#dependencies)
  - [`requires` — other packages](#requires--other-packages)
    - [Version ranges](#version-ranges)
    - [Resolving a requirement to a version](#resolving-a-requirement-to-a-version)
    - [`requires` validation rules](#requires-validation-rules)
- [Radio capabilities](#radio-capabilities)
- [Firmware version constraints](#firmware-version-constraints)
- [Variants](#variants)
  - [Selection](#selection)
  - [Manual selection and updates](#manual-selection-and-updates)
- [Subpackages](#subpackages)
- [Validation summary](#validation-summary)
  - [Checked by the JSON Schema](#checked-by-the-json-schema)
  - [Checked by tooling at load time](#checked-by-tooling-at-load-time)
  - [Behavioural rules](#behavioural-rules)

## Conformance and terminology

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**,
**SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY** and **OPTIONAL** in this
document are to be interpreted as described in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

**Normative documents.** Only these define conformance:

- this document (`docs/Manifest.md`) — the manifest format
- [`docs/State.md`](./State.md) — the on-card state format
- [`schema/edgetx-manifest.v1.json`](../schema/edgetx-manifest.v1.json) — the
  machine-checkable subset of this document
- [`schema/edgetx-state.v1.json`](../schema/edgetx-state.v1.json) — the
  machine-checkable subset of `docs/State.md`

**Non-normative.** [`docs/Implementation.md`](./Implementation.md),
[`docs/GettingStarted.md`](./GettingStarted.md) and `README.md` are guidance.
`CONTRIBUTING.md`, `AGENT.md` and `CHANGELOG.md` are process documents about
editing this repository. Neither kind defines conformance, and where either
appears to disagree with a normative document, the normative document wins.

When given only a directory, tooling looks for `edgetx.yml` — that exact name,
not `edgetx.yaml`. This applies to a package's own manifest and to a
subpackage's, both of which are found by construction rather than by an explicit
path.

A **variant** manifest is different: it is referenced by name from
`variants[].path`, so it MAY use either `.yml` or `.yaml`.

Two exceptions, because rules would otherwise contradict.
`conformance/invalid/malformed-license.yml` and
`conformance/invalid/malformed-email.yml` demonstrate rules this specification
deliberately states as SHOULD — an unparseable license or address is reported,
not fatal — so an implementation that **accepts** either file is still
conforming. They live in `invalid/` because they are what a validator with
stricter settings catches, and because the rule is worth pinning.
`malformed-email.yml` is additionally rejected only by a validator that asserts
`format` keywords. `format` is an annotation in JSON Schema 2020-12, and
this specification deliberately does not require rejecting a manifest over an
unparseable address — so an implementation that accepts that one file is still
conforming. Everything else in `invalid/` MUST be rejected.

A conforming implementation MUST accept everything in
[`conformance/valid/`](../conformance/valid/) and
[`conformance/state-valid/`](../conformance/state-valid/), and MUST reject
everything in [`conformance/invalid/`](../conformance/invalid/),
[`conformance/state-invalid/`](../conformance/state-invalid/) and the
`invalid-*.list` files in
[`conformance/file-lists/`](../conformance/file-lists/).

Compatibility is evaluated from the **EdgeTX firmware version**
(`min_edgetx_version`, `max_edgetx_version`) and declared hardware
capabilities only. This specification does not define a firmware API version.

## `edgetx_format_version`

`edgetx_format_version` is a top-level field naming the revision of the EdgeTX
package file format that the manifest conforms to. It is the forward-compatibility gate: it lets
future tooling and firmware adapt their handling, or refuse a manifest they
cannot process correctly, rather than guessing.

```yaml
edgetx_format_version: "1.1"
```

It belongs at the top level, not inside `package:`, because it describes the
*file format*, not the package.

- The value MUST be `MAJOR.MINOR`.
- **MAJOR** is incremented only for a breaking change: a field whose meaning
  changed, a field removed, or a new required field.
- **MINOR** is incremented only for an additive change that older tooling can
  ignore: a new optional field, or a new content section.
- **Widening a closed enum is a MAJOR change**, not a minor one. `display.type`
  and the state enums are closed in the schemas, so older tooling
  *rejects* an unknown value rather than ignoring it — while the rule below
  requires it to process a higher MINOR rather than refuse. The two cannot both
  hold. Shipping `display.type: eink` therefore needs a MAJOR bump, or a new
  optional field beside `type` that older tooling ignores.
- **Adding any field to a variant entry's selection filter is a MAJOR change.**
  This is the enum argument one level up, and it holds for the whole filter, not
  just for `display`: only `capabilities`, `min_edgetx_version` and
  `max_edgetx_version` participate in selection and specificity, and adding
  another such field would change which build installs. Tooling that ignores a
  filter field does not merely lose a check — it keeps a candidate it should
  have dropped, scores it wrong, and installs a *different variant* than tooling
  that reads the field. Acting on a field's absence in a way that is wrong,
  rather than merely limited, is the definition of a breaking change.

  The `additionalProperties: true` on a variant entry is what lets older tooling
  *load* a newer manifest rather than crash on it; it is not permission to add
  new selection fields in a MINOR. Non-selection overlay fields such as
  `capabilities_tighten` and content sections are different: they do not affect
  variant choice.
- Tooling MUST refuse a manifest whose MAJOR it does not know, with a message
  telling the user that newer tooling is required. It MUST NOT process such a
  manifest partially.
- Tooling MUST support every MAJOR up to and including its own.
- Tooling MUST process a manifest with a known MAJOR and a higher MINOR,
  ignoring fields it does not recognise, and SHOULD report once that it did so.
- Absence means `"1.0"`. Tooling MUST NOT warn about absence: manifests
  written before this field existed are 1.0-shaped by definition.

This scheme constrains the specification as much as it constrains tooling:
**a MINOR addition MUST be safely ignorable by older tooling.** A change that
older tooling would reject, or silently act on incorrectly, requires a MAJOR
bump. See [CONTRIBUTING.md](../CONTRIBUTING.md).

A manifest MUST NOT exceed 256 KiB, MUST NOT declare more than 512 content items
**in any one section**, and MUST NOT declare more than 64 `requires` entries.
Tooling MUST refuse one that does. It MUST also bound YAML anchor and alias
expansion: refuse a document whose expanded scalar content exceeds **ten times**
the file's byte size. Measure it as the total bytes of all scalar values after
aliases are resolved, counting a repeated node once per reference — that is the
quantity an alias bomb inflates, and it is cheap to accumulate while parsing. No
honest manifest approaches it. These bounds are far above any real
package and low enough that a radio can refuse a hostile manifest before running
out of memory.

A mapping MUST NOT contain a duplicate key, and tooling MUST reject one that
does. YAML libraries disagree here — some take the first value, some the last,
some refuse the document — so a manifest with `dest` twice would install to
different places depending on the implementation.

Unknown keys are therefore permitted anywhere in a manifest and MUST be ignored
rather than rejected. Tooling MAY report them, and reporting them is useful —
with unknown keys accepted, a misspelled field name is otherwise silent. But an
unknown key MUST NOT make a manifest invalid.

### Version history

| Version | Change |
|---|---|
| `1.0` | First version of the format. |
| `1.1` | Added multi-version dependency resolution, per-package state files under `PKG/packages/`, and explicit variant overlays via `base_capabilities`, `capabilities_tighten`, and merged content sections. |

## Manifest format

```yaml
edgetx_format_version: "1.1"

package:
  id: github.com/ExpressLRS/Lua-Scripts                       # required
  name: "ExpressLRS"                                          # optional: display name
  version: "3.1.2"                                            # optional: semver, drives update detection
  description: ExpressLRS Lua scripts and widgets for EdgeTX  # required
  authors:                                                    # optional
    - name: ExpressLRS Team
      email: info@expresslrs.org
  urls:                                                       # optional
    - name: Homepage
      url: "https://www.expresslrs.org"
  screenshots:                                                # optional
    - assets/screen1.png
  keywords: ["telemetry", "elrs", "crossfire"]                # optional
  license: GPL-3.0-only                                       # optional: SPDX expression
  source_dir: src                                             # optional: string or list
  min_edgetx_version: "2.12.0"                                # optional
  max_edgetx_version: "2.13.x"                                # optional
  binary: false                                               # optional: allow .luac

requires:                                                     # optional: OTHER packages
  - id: github.com/someone/elrs-libs
    version: "^2.0.0"

libraries:
  - name: ELRS
    path: SCRIPTS/ELRS
  - name: TestUtils
    path: SCRIPTS/TestUtils
    dev: true

tools:
  - name: ExpressLRS
    path: SCRIPTS/TOOLS/ExpressLRS

widgets:
  - name: ELRSTelemetry
    path: WIDGETS/ELRSTelemetry
```

### Top-level fields

| Field | Required | Description |
|---|---|---|
| `edgetx_format_version` | no | Format revision this manifest targets. Absent means `"1.0"`. See [edgetx_format_version](#edgetx_format_version). |
| `package` | **yes** | Package metadata — see [Package fields](#package-fields). |
| `base_capabilities` | no | Install-time hardware requirements inherited by every selected variant. Same shape as `package.capabilities`. See [Variants](#variants). |
| `requires` | no | Dependencies on **other packages**. See [requires](#requires--other-packages). |
| content sections | no | `libraries`, `tools`, `widgets`, `telemetry`, `functions`, `mixes`, `sounds`, `images`, `themes`, `files`. See [Content sections](#content-sections). |

### Package fields

| Field | Required | Description |
|---|---|---|
| `id` | **yes** | Canonical package identity and location. See [Package id](#package-id). |
| `description` | **yes** | Non-empty description. |
| `name` | no | Display name. Falls back to `id`. Never affects install destinations. |
| `version` | no | semver. Update detection compares this value — see [Package version](#package-version). |
| `authors` | no | Array of `{name, email?}`. `email` SHOULD look like an address, but tooling MUST NOT reject a manifest over one it cannot parse — see the note under [Checked by the JSON Schema](#checked-by-the-json-schema). |
| `urls` | no | Array of `{name, url}`. `url` MUST be an absolute URL using the `http` or `https` scheme. Tooling may render these as links, and `javascript:` or `data:` would be an active-content sink for metadata from a repository it does not control. |
| `screenshots` | no | Relative paths to image files, resolved against the manifest directory. Tooling SHOULD warn about one that is missing and MUST NOT refuse the install: a stripped tarball or a shallow fetch legitimately lacks them, and a typo in a screenshot path should not make a working package uninstallable. |
| `keywords` | no | Keyword strings for discovery. |
| `license` | no | SPDX license expression. Compound expressions such as `"MIT OR Apache-2.0"` are valid. Tooling SHOULD warn on one it cannot parse and MUST NOT refuse the package: the SPDX list grows, so a MUST would make a manifest's validity depend on the age of the tooling reading it, and the field affects no behaviour. |
| `source_dir` | no | Source root, or list of source roots, relative to the manifest. See [Source and destination](#source-and-destination). |
| `min_edgetx_version` | no | Minimum firmware version. Complete semver, no wildcard. See [Firmware version constraints](#firmware-version-constraints). |
| `max_edgetx_version` | no | Maximum firmware version. `x` allowed in the patch position. See [Firmware version constraints](#firmware-version-constraints). |
| `binary` | no | `true` allows `.luac` bytecode to be installed. Default `false`. |
| `capabilities` | no | Hardware requirements. See [Radio capabilities](#radio-capabilities). |
| `variants` | no | Alternate manifests per hardware profile. See [Variants](#variants). |

**Length limits.** `name` and each `authors[].name` are at most 128 characters;
`description` 1024; `license` 128; each `keywords` entry 64; `authors[].email`
254; `urls[].name` 64; `urls[].url` 2048; a content item's `name` and each
`id` 241; any path 255. These are counted in Unicode code
points, which for a path is **not** the same as FAT32's 255 UTF-16 units — a path
of astral characters can satisfy this rule and still exceed what the card
accepts. Keep installed paths ASCII.

### Package id

`id` is both the package's identity and its location: the git clone URL minus
the scheme and any `.git` suffix, plus the subpackage path when the package
lives in a subdirectory.

| Repository layout | Example id |
|---|---|
| Single-package repo | `github.com/ExpressLRS/Lua-Scripts` |
| Subpackage in a multi-package repo | `github.com/offer-shmuely/lua-scripts/log-viewer` |
| Self-hosted Gitea / GitLab | `gitea.example.com/Team/widget-pack` |

- `id` MUST have at least three `/`-separated segments (`host/owner/repo`).
- The first segment MUST contain a `.` — it is a host.
- Every segment MUST match `^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`.
- Segments beyond the third form the subpackage path.
- **No segment** of an `id` may end in `.git`, compared case-insensitively. The
  suffix is part of a clone URL, not of the identity; permitting both spellings
  would alias one repository to two packages. This applies to every segment, not
  only the last: `github.com/acme/my.git/subpkg` is rejected.
- An `id` is case-insensitive **throughout**, and MUST be lowercased before it is
  stored or compared. `GitHub.com/Acme/Tool`, `github.com/Acme/Tool` and
  `github.com/acme/tool` are all one package.

  Locating files is not comparing. When an `id`'s subpackage segments are used to
  find a subpackage directory in a checkout, tooling MUST match the
  on-disk name **case-insensitively** rather than lowercasing the segments first —
  a repository may legitimately hold `log-viewer/` or `LogViewer/`, and a
  case-sensitive checkout finds neither if the segments are folded before the
  lookup. The stored id stays lowercase either way.

  This is not merely a convenience. The `id` becomes part of a filename in
  [`PKG/packages/`](./State.md#pkgpackagespackage-keyyml) and FAT32 is
  case-insensitive, so two ids differing only in case cannot have separate
  state or inventory files on the card however this specification defines
  equality — treating them as distinct packages would give two package-state
  files one prefix.
  The major forges treat owner and repository names case-insensitively too.
- An `id` MUST NOT exceed 241 characters, so that the derived
  `PKG/packages/<package-key>.list` name stays within the FAT32 filename limit — see
  [State.md](./State.md#package-keys-and-filenames).

A host with a non-default port cannot currently be expressed: `:` is excluded
from paths and ids because FAT32 forbids it in a name. Self-hosted instances
must therefore be reachable on the default port, or be given a hostname.

Tooling MAY accept GitHub shorthand (`ExpressLRS/Lua-Scripts`) as *user input*
and expand it, but a manifest MUST declare the full form including the host.

### Package references

A manifest declares an `id`; a *user* names a package with a reference, which
adds a version and an optional variant selector:

```text
[host/]owner/repo[/subpath][@version][::variant.yml]
```

| Part | Meaning |
|---|---|
| `host/` | Optional. A first segment without a `.` is GitHub shorthand and expands to `github.com`. |
| `owner/repo` | Required. |
| `/subpath` | Selects a [subpackage](#subpackages). |
| `@version` | A tag, a branch, or a commit id. Absent means the highest semver tag, falling back to the default branch. |
| `::variant.yml` | Selects a [variant](#variants) explicitly, equivalent to `--path`. |

A **local** reference is a second form, and it is what produces
`channel: local`:

```text
<path-to-directory>[::variant.yml]
```

The two forms are told apart by shape, not by probing the filesystem: a reference
is local when it begins with `/`, `./`, `../` or `~/`, and remote otherwise.
Deciding by whether a directory happens to exist would make `owner/repo` install
from GitHub in one shell and from disk in another, which is exactly the
divergence this grammar exists to prevent.

A reference may also name a **fork**: the repository to fetch from, when that is
not the one the package's `id` designates. Tooling that offers this MUST record
the fetched-from repository in [`source.origin`](./State.md#source), so a later
update goes back to the fork the user chose rather than silently migrating them
upstream. Without such a reference form, `origin` is never set and the field is
inert — which is a valid implementation.

This grammar is normative because `source.channel` in
[State.md](./State.md#source) records how a reference resolved: two tools that
parse the same reference differently write different state for one card. A
reference naming a local directory installs from disk and records
`channel: local`.

### Package version

`package.version` is the update signal. Tooling compares the installed value
against the value in the newly resolved manifest to decide whether an update
is available.

- A package intended to be updatable SHOULD declare `version`, and MUST bump
  it on each release. Update detection does not work without it.
- Tooling SHOULD warn when a newly resolved ref carries a `version` equal to
  the installed one, since tagging a release without bumping the version is
  the common authoring mistake.
- `version` describes the package. It is unrelated to `edgetx_format_version`, which
  describes the file format.

Because a git ref is mutable, `version` alone cannot identify what is installed.
State therefore also records the resolved commit — see
[State.md](./State.md#source). The two answer different questions: `version`
answers *is there an update?*, the commit answers *what exactly is installed?*

Two consequences of omitting `version` that are specified elsewhere, collected
here because this is where a reader looks:

- The package **cannot satisfy any dependency range except `*`** — see
  [Resolving a requirement to a version](#resolving-a-requirement-to-a-version).
- State still records the field, as `null`. `version` is a **required key** in
  each `PKG/packages/<package-key>.yml` file even when its value is absent — see
  [State.md](./State.md#required-and-optional-fields).

## Content sections

A manifest MAY declare any of these sections. Each is a list of content items.

Themes only work on color LCD radios, so a package shipping them SHOULD declare
`capabilities.display.type: colorlcd` — see
[Radio capabilities](#radio-capabilities). Tooling can then refuse the install
on a black-and-white radio instead of leaving dead files on the card.

A manifest that declares no content sections is valid. It installs no files, and
is useful as a metapackage: a package whose only purpose is to pull in others
through `requires`.

| Section | Contains |
|---|---|
| `libraries` | Shared Lua code used by other items in the same package. |
| `tools` | Scripts that appear in the radio's Tools menu. |
| `widgets` | Screen widgets (color LCD radios). |
| `telemetry` | Telemetry scripts. |
| `functions` | Special-function scripts. |
| `mixes` | Mix scripts. |
| `sounds` | Sound packs. |
| `images` | Image assets. |
| `themes` | UI themes. Color LCD only — see the note below. |
| `files` | Content with no EdgeTX-defined home. A more specific section MUST be preferred wherever one applies. |

### Content item fields

| Field | Required | Description |
|---|---|---|
| `name` | **yes** | Identifies the item. MUST be unique across every content section in the manifest, so that diagnostics can name one item unambiguously. It **never** contributes to the install destination. |
| `path` | **yes** | Source location, relative to the source root. Also the destination when `dest` is absent. Must satisfy the [path rules](#path-rules). |
| `dest` | no | Destination, relative to the SD card root. **Required when `path` is `.`**. Must satisfy the [path rules](#path-rules), and must not be `PKG` or begin with `PKG/`, compared case-insensitively. |
| `exclude` | no | Glob patterns skipped during copy — see [exclude patterns](#exclude-patterns). |
| `dev` | no | `true` marks a development-only item: test harnesses, debug tools, mock libraries. Excluded from install and update unless `--dev` is passed. |

The destination checks — the same-destination rule, the ancestor rule, and the
kind check — apply across **every** item the manifest declares, `dev: true`
included, regardless of whether this invocation was passed `--dev`. They are
checks on the manifest, and a manifest whose validity depended on which flags
were passed would pass CI and fail for the one developer who ran with `--dev`.

Whether dev content was included is not recorded in state, and no operation
infers it from a previous one: an install or update includes `dev` items only
when `--dev` is passed to *that* invocation.

`name` never affects where files land. A `themes` entry named `MyTheme` with
`path: THEMES/MyTheme` installs to `THEMES/MyTheme` because that is its `path`,
not because of its name. To install somewhere else, set `dest`.

`binary: true` on the package allows compiled bytecode to be installed. When it
is absent or false, tooling MUST skip every `.luac` file **at any depth and
whatever the case of its extension** — `main.LUAC` is `main.luac` on the card, and
the radio prefers it either way. The pattern is `**/*.luac` and not `*.luac` — the latter would match only an item's top
level, so a nested `lib/util.luac` would install and then shadow the newer
`lib/util.lua` beside it. This is a rule about copying, not an `exclude` pattern
the author writes.

`binary` is read from the manifest file that **declares the content being
installed**. Base content sections and any content sections declared inline on a
selected `variants[]` entry therefore use the base manifest's `package.binary`;
content declared in the selected variant manifest uses that variant manifest's
own `package.binary`. A `binary: true` on a variant manifest does not permit
`.luac` shipped only by the base, and a `binary: true` on the base does not
permit `.luac` shipped only by the variant. This is the same rule as every other
package field; it is called out because a base manifest is where an author's eye
lands first, and getting it wrong installs nothing rather than failing.

A package MAY ship bytecode **and no source at all**. That is what `binary: true`
is for, and nothing about it is a degraded case: the `.luac` files are ordinary
content, owned by the package, listed in its inventory, and removed with it. In
particular tooling MUST NOT infer that an owned `.luac` is derived from anything,
MUST NOT treat one as stale because no `.lua` sits beside it, and MUST NOT
regenerate it. The [bytecode companion rules](./State.md#bytecode-companions) are
about *untracked* bytecode — the radio's own compilation output — and an owned
`.luac` is not that.

Because bytecode is not portable across every firmware release, such a package
normally ships one build per firmware generation and selects between them with
the firmware bounds on a [variant entry](#variants). Skipping `.luac` when
`binary` is absent means a package that forgets the flag installs *nothing*
rather than something broken, which is the right way round.

Where tooling offers to compile `.lua` to `.luac` itself, it MUST NOT overwrite a
`.luac` the package ships. The author's build is authoritative — they may have
compiled it for a target the host cannot reproduce, which is the whole reason the
package ships bytecode.

#### `exclude` patterns

An `exclude` pattern is matched against each file's path **relative to the
content item's `path`**, using `/` separators. Without a precise rule two
implementations produce different installed file sets from the same manifest,
so:

- `*` matches any run of characters **except `/`**, including an **empty** run.
  So `test*` matches `test`, and `*.md` matches `.md`. Every mainstream glob does
  this, and the `**` rule below is defined in terms of it, so leaving it implicit
  would make `**.md` match `a.md` in one implementation and not another.
- `**` matches any run of characters **including `/`**. As a special case, a
  `**/` component also matches **zero** directories, wherever it appears. So
  `**/*.md` matches `README.md` as well as `docs/notes.md`, and `a/**/b.lua`
  matches `a/b.lua` as well as `a/x/b.lua`. Without that case the two are
  inexpressible in one pattern, and every other glob implementation makes the
  same exception.
- A `**` that is *not* a whole component — `a**b`, `**.md` — is not special. It
  is read as two `*`s, so it matches within one segment and no further. Authors
  should write `**/` when they mean any depth; the two spellings are easy to
  confuse and this says which one wins.
- `?` matches exactly one character other than `/`.
- Matching is against the whole relative path, not the basename. A pattern with
  no `/` therefore matches only files at the item's top level: `*.md` excludes
  `README.md` but not `docs/notes.md`. Use `**/*.md` for both.
- A pattern matching a directory excludes that directory and everything under
  it. `test/**` and `test` both exclude the whole subtree.
- Matching is **case-insensitive**, ASCII-only, for the same reason and by the
  same rule as destination comparison — see [Path rules](#path-rules).
- Patterns exclude only; there is no negation or re-inclusion syntax.

Examples, for an item with `path: SCRIPTS/TOOLS/MyTool`:

| Pattern | Excludes |
|---|---|
| `*.luac` | `main.luac`, but not `lib/util.luac` |
| `**/*.luac` | every `.luac` at any depth |
| `test/**` | the whole `test/` subtree |
| `test/*` | also the whole `test/` subtree: `*` matches the directory `test/sub`, and a directory match takes its contents with it |
| `presets.txt` | that one file at the item's top level |

## Source and destination

`path` says where to **read**; `dest` says where to **write** on the SD card.

**Source root.** When `source_dir` is declared, the source roots are
`manifest_dir/<source_dir>` for each declared value, in declaration order.
When it is absent, the single source root is `manifest_dir`.

- Declaring `source_dir` MUST NOT introduce a fallback to `manifest_dir`. A
  content `path` that does not exist under any declared source root is an
  error. This keeps a mistyped `source_dir` a diagnostic rather than a silent
  install from the wrong tree.
- With a list, the first source root containing the path wins.

**Source of a content item** = `<source_root>/<path>`, using the first source
root where it exists.

**Destination of a content item** = `<sd_root>/<dest, or path when dest is
absent>`. `dest` never inherits `source_dir` — it is always relative to the SD
card root.

A content `path` MAY name a single file rather than a directory. When it does,
`dest` names the destination **file**; when `path` names a directory, `dest`
names the destination **directory** and the tree is copied inside it. Tooling
MUST refuse to install a file over an existing directory, or a directory over an
existing file, rather than guessing. `exclude` has no effect on a single-file
item.

Two things are skipped when copying a directory, whether or not `exclude`
mentions them:

- **Version-control metadata** — a path component named `.git`, `.svn` or `.hg`,
  or a file named `.gitignore`, `.gitattributes` or `.gitmodules`. Both apply at
  **any depth**, so `assets/.gitignore` is skipped as surely as a top-level one,
  and both are compared with the same ASCII case fold as every other path
  comparison here, so `.GIT` and `.Gitignore` are skipped too.
- **Every manifest involved in this install** — the one being installed, the base
  manifest when a variant was selected, and every path any of them names in
  `variants[].path`. Naming only "the manifest being installed" would ship the
  *base* onto the card whenever a variant was chosen, since a variant manifest
  names no siblings of its own.

Both matter because `path: .` at a repository root is the documented way to
package a theme, and without this rule that copies the entire `.git` directory —
thousands of files — onto the card. Authors would have to write the same
`exclude` list in every such manifest, and the ones who forgot would ship it.
Nothing else is skipped implicitly: dotfiles in general are ordinary content,
since EdgeTX packages legitimately ship them.

Because `path` is the destination when `dest` is absent, `path` is subject to the
destination rules too in that case: in particular it MUST NOT begin with `PKG/`.
**With `dest` set, it is a pure source path and `PKG/` is not reserved in it** —
nothing at that path is written to the card under that name, and a repository is
entitled to a `PKG/` directory of its own. Applying the reservation
unconditionally makes such a repository unpackageable for a reason that does not
apply to it.

Two content items in one manifest MUST NOT resolve to the same destination.
Tooling MUST reject that rather than pick a winner.

Nor may one item that resolves to a **single file** have a destination that is an
**ancestor** of another item's destination. `dest: SCRIPTS/T` from a single file
and `dest: SCRIPTS/T/inner.lua` are different destinations, so the rule above does
not catch them, but one wants `SCRIPTS/T` to be a file and the other wants it to
be a directory. Staging merges them and which one survives depends on the order
the implementation happened to walk the sections in; on the card the copy fails
partway through. Two conforming tools install different content from the same
manifest. Tooling MUST reject it.

Two definitions this rule depends on, because a loose reading of either changes
which manifests are legal:

- **Ancestor means at a component boundary.** `A` is an ancestor of `B` when `B`
  begins with `A` followed by `/`. `SCRIPTS/T` is *not* an ancestor of
  `SCRIPTS/TOOLS/a.lua`, and testing with a plain string prefix would reject that
  perfectly ordinary pair. Case is folded first, as in every other destination
  comparison.
- **Only a single-file item triggers it.** Two items whose destinations nest and
  both resolve to *directories* are legal: they merge, and any individual file
  that genuinely collides is caught by the same-destination rule. Two packages
  are likewise allowed to install into one directory — see
  [State.md § Ownership](./State.md#ownership) — so a rule that rejected all
  nesting would forbid within one manifest what it permits across two. Which
  items are single files needs the source tree, so this check happens when that
  is available, alongside the other kind checks.

### Path rules

These apply to every `path`, `dest`, `source_dir`, `screenshots` entry,
`variants[].path`, every path read back from a state file, and — this is the
one that is easy to miss — **every path discovered while copying a content
directory**, not merely the ones the manifest declares.

That last case is the one that bites. A manifest declaring only
`path: SCRIPTS/TOOLS/MyTool` can contain, inside that directory, a file or
directory whose own name holds a newline. Every declared path is legal, the copy
proceeds, and the resulting file list has an extra line naming any file on the
card — which the next remove deletes. Tooling MUST therefore validate each
destination it is about to write, and MUST refuse the operation on one that
fails, rather than validating only what the manifest spelled out.

- A path MUST be relative — no leading `/`.
- A path MUST use `/` as its only separator. `\` is forbidden, since these are
  FAT32 paths.
- A path MUST NOT contain a `.` or `..` segment. The single exception is a
  `path` whose entire value is `.`, meaning the source root itself — see below.
- A path MUST NOT contain an empty segment or a trailing `/`.
- A path MUST NOT contain any of `U+0000`-`U+001F`, `U+007F`-`U+009F`, `U+2028`
  or `U+2029`. Not all of these are *control* characters — `U+2028` and
  `U+2029` are line separators — but every one of them ends a line for some
  reader, and state records one path per line.
- A path MUST NOT have a segment ending in an ASCII space (U+0020) or a dot.
- A path MUST NOT use the characters FAT32 forbids in a name: `: * ? " < > |`.
- No path segment may be a reserved device name — `CON`, `PRN`, `AUX`, `NUL`,
  `COM1`-`COM9`, `LPT1`-`LPT9` — with or without an extension, compared
  case-insensitively. These cannot be created on Windows, so tooling there could
  neither install nor honestly refuse a package that declares one.
- A path MUST NOT exceed 255 characters. FAT32 limits each *component* to 255
  UTF-16 units; bounding the whole path is stricter and simpler to check.

The last three deserve their reasons, because they look like fussiness:

- **Control characters.** State records one installed file per line. A newline
  inside a path would forge an extra entry in a file list, so a package could
  make tooling delete a file it never installed.
- **Trailing space or dot.** FAT32 strips both when creating a name. Writing
  `SCRIPTS/tool␠` — where `␠` marks a trailing space — creates
  `SCRIPTS/tool` on the card, but state would record the name as declared. The
  two never match again, so remove would silently skip the file forever.
- **No `.` segments.** Together with the ban on empty segments, this removes the
  redundant spellings of one location: `THEMES/X` and `./THEMES/X` must not be
  able to name the same file.

Tooling MUST reject a path violating these rules rather than repairing it.

**Destinations are compared case-insensitively.** The rules above remove the
redundant spellings of a path but not the case variants, and FAT32 is
case-insensitive: `SCRIPTS/TOOLS/Foo/main.lua` and `SCRIPTS/tools/Foo/MAIN.LUA`
are one file on the card. Comparing them as distinct would let one package
overwrite another's file while both file lists claimed to own it, and removing
either package would delete the other's content — which would defeat per-file
ownership entirely. So wherever this specification compares destinations — the
collision check within a manifest, the ownership check against other packages,
and the reserved-namespace check — the comparison MUST be case-insensitive.
Paths are still *stored* as the author wrote them.

This covers **looking a destination up on the card**, not only comparing two
strings. Asking whether `SCRIPTS/FOO.LUA` exists must find an existing
`SCRIPTS/Foo.lua`, because on the card they are one file — so an implementation
working against a case-sensitive host filesystem needs a folded index rather than
a literal `stat`. The untracked-file check and the bytecode-sibling lookup are
exactly where this bites: a literal lookup misses the file, the overwrite policy
never fires, and a package silently replaces something the user wrote by changing
one letter's case.

**The fold is ASCII only**: `A`-`Z` map to `a`-`z` and nothing else changes. Not
Unicode `casefold()`, which would make `STRASSE` and `STRAßE` one path and so
decide real ownership answers differently between two conforming
implementations. ASCII folding is deterministic, matches what the schemas
enforce for the reserved namespace, and covers every path an EdgeTX directory
convention produces. A consequence worth stating: two paths differing only
outside ASCII are distinct owners here and may still be one file on the card,
which is why installed paths should stay ASCII.

Unicode is a different matter, and this specification does not solve it. NFC and
NFD spellings of one accented name are distinct strings naming one file, so two
packages could each appear to own one spelling; tooling SHOULD compare paths
after NFC normalisation. Normalisation does not help with the format-control and
zero-width characters either — a zero-width space or a bidirectional override is
invisible to the user and survives NFC. Package authors are strongly advised to
keep installed paths ASCII, which is what every EdgeTX directory convention
already is. This applies equally to paths read back
from state, which live on a removable card and are not trusted input.

Additionally:

- `path` MAY be the single value `.`, meaning the source root itself. `dest`
  MUST NOT be `.`.
- `dest` is REQUIRED when `path` is `.`, because the implied destination would
  otherwise be the SD card root.
- No `dest` may be `PKG` or begin with `PKG/`, **compared case-insensitively**.
  The bare name is excluded too: a file called `PKG` at the card root would
  collide with the directory the package manager needs. FAT32 does
  not distinguish `PKG` from `pkg`, so a case-sensitive check would let
  `dest: pkg/installed.yml` reach the state file. See
  [reserved namespace](./State.md#reserved-namespace).
- Tooling MUST NOT read through a symbolic link that resolves outside the
  **repository checkout root**, and MUST NOT write a symbolic link to the card.
  FAT32 has no links, so there is nothing to preserve — and a link pointing at
  `/etc/passwd` would otherwise copy a host file onto the card.

  The anchor is the checkout root, deliberately, and not any directory the
  manifest names: the manifest chooses `source_dir` and every content `path`, so anchoring
  to those lets a repository containing a single committed symlink — `src` →
  somewhere on the host — declare `source_dir: src` and exfiltrate whatever it
  points at. Nothing under a link is outside the link.
- After resolution, every destination MUST lie inside the SD card root.
  Tooling MUST reject any path that escapes it, however the escape is
  constructed. The specification does not mandate a mechanism; the guarantee is
  what conformance requires.

Declaring `source_dir: "."` is permitted and means the manifest directory — the
same as omitting `source_dir`. It does not reintroduce a fallback: exactly one
source root is in effect either way.

### Source and destination examples

Source equals destination:

```yaml
tools:
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool
# read:  <source_root>/SCRIPTS/TOOLS/MyTool
# write: <sd_root>/SCRIPTS/TOOLS/MyTool
```

Manifest living inside the content directory:

```yaml
# THEMES/Bionic_Theme/edgetx.yml
package:
  id: github.com/acme/bionic-theme
  description: Bionic theme for color LCD radios
themes:
  - name: Bionic_Theme
    path: .                             # the source root — here, the manifest directory
    dest: THEMES/Bionic_Theme           # explicit, because path is '.'
```

## Dependencies

The specification distinguishes two kinds, which are declared separately.

### `requires` — other packages

`requires` is a top-level list naming **other packages** this package needs.
Tooling fetches and installs them.

```yaml
requires:
  - id: github.com/someone/elrs-libs
    version: "^2.0.0"
  - id: github.com/someone/chart-libs      # any version
```

| Field | Required | Description |
|---|---|---|
| `id` | **yes** | Canonical package id, same form as `package.id`. |
| `version` | no | semver range over the dependency's `package.version`. Absent or `*` means any version. |

Requirements are on **packages, not on libraries inside them**. A depended-on
package installs as a whole, so package granularity is sufficient.

#### Version ranges

A range is one comparator, or two space-separated comparators forming a bounded
range. Tooling MUST reject a range it cannot parse rather than guessing.

| Form | Matches |
|---|---|
| `1.2.3` or `=1.2.3` | exactly `1.2.3` |
| `>=1.2.0`, `>1.2.0`, `<=2.0.0`, `<2.0.0` | as written |
| `^1.2.3` | `>=1.2.3` and `<2.0.0` |
| `^0.2.3` | `>=0.2.3` and `<0.3.0` |
| `^0.0.3` | `>=0.0.3` and `<0.0.4` |
| `~1.2.3` | `>=1.2.3` and `<1.3.0` |
| `>=1.2.0 <2.0.0` | both comparators |
| `*` or absent | any released version; prereleases are excluded |

The caret and tilde rows are spelled out because implementations disagree
otherwise: `^0.2.3` and `^0.0.3` differ between npm and Cargo, and `~1.2.3`
differs between npm and Composer. These definitions are normative.

Comparison rules:

- **Build metadata is ignored.** `1.2.3+build.7` and `1.2.3` are the same
  version for range matching. A range MUST NOT carry build metadata.
- **A prerelease satisfies a range only when the range names a prerelease with
  the same `MAJOR.MINOR.PATCH`.** This holds for `*` too: a package that has only
  ever shipped prereleases cannot be depended on until it makes a release, which
  is the honest outcome — the alternative is that asking for "any version"
  silently installs a release candidate. `1.3.0-rc1` does not satisfy `^1.2.0`;
  `1.3.0-rc2` does satisfy `>=1.3.0-rc1`. Without this rule an author pinning
  `^1.2.0` silently receives release candidates.
- Ordering follows semver throughout, prereleases included: `1.3.0-rc2` is above
  `1.3.0-rc1` and below `1.3.0`. `pick_version` needs this to choose between two
  prereleases that both satisfy a range.
- In a two-comparator range, a **bare version is a lower bound**, equivalent to
  `>=`. So `1.2.3 <2.0.0` admits `1.5.0`. A bare version *alone* still means
  exactly that version.
- `^` and `~` MUST NOT appear in a two-comparator range: they already denote a
  bounded range, and pairing one with another bound has no agreed meaning.
- The lower bound MUST come first. `<2.0.0 >=1.2.0` is not a range.

> **This is the opposite of the firmware rule.** A dependency range admits a
> prerelease only when the range itself names a prerelease at the same
> `MAJOR.MINOR.PATCH`; firmware bounds *ignore* the prerelease entirely, so
> `2.13.5-rc1` satisfies a bound of `2.13.5` — see
> [Firmware version constraints](#firmware-version-constraints). The two are
> deliberately different: an author pinning a dependency does not want release
> candidates, whereas a user running a nightly firmware build does want their
> packages to install. Do not unify them.

#### Resolving a requirement to a version

Tooling determines a dependency's available versions by reading
`package.version` from that package's manifest at each candidate git tag. It
MUST NOT infer the version from the tag name.

This matters because the two disagree exactly when an author tags a release
without bumping `version` — which is the common authoring mistake. A tag named
`v2.1.0` whose manifest still says `2.0.0` provides version `2.0.0`, and
tooling SHOULD warn about the discrepancy rather than quietly treating the tag
as authoritative.

A candidate tag whose manifest declares no `version` cannot satisfy any range
except `*`.

Resolution yields a **tag**, not just a version: state records the ref and the
commit, so tooling must carry them through. When two tags carry manifests
declaring the same `version` — which happens whenever a release is re-tagged —
tooling MUST pick the one whose tag sorts highest under semver tag ordering, and
SHOULD say that it did.

#### `requires` validation rules

- A `requires` entry MUST NOT name the manifest's own `package.id`.
- Two comparators MUST form a non-empty bounded range: one lower bound (`>`,
  `>=`, or a bare version, both meaning `>=`) and one upper bound (`<` or `<=`).
  Non-empty means at least one version satisfies both, which depends on whether
  each bound is inclusive: `>=2.0.0 <2.0.0` and `>1.2.0 <=1.2.0` are both empty
  and MUST be rejected, though the lower bound is not *above* the upper in
  either. `=` is not a comparator in a two-comparator range — it is an equality,
  and pairing it with a bound has no meaning.

  "Non-empty" means **at least one admissible version exists** — admissible by
  the same prerelease rule that governs matching, not merely numerically between
  the bounds. So `>1.2.0 <1.2.1` is empty: the only versions between those bounds
  are prereleases of `1.2.1`, and a range that does not name a prerelease of
  `1.2.1` cannot match one. But `>=1.2.0-rc1 <1.2.0` is **not** empty, even though
  no released version qualifies: the lower bound names a prerelease of `1.2.0`, so
  `1.2.0-rc1` is admissible and satisfies both bounds.

  Stated as a decision procedure, because "does an admissible version exist"
  otherwise quantifies over an unbounded space of prerelease identifiers and two
  implementations would draw the line in different places. A pair is **non-empty**
  exactly when both of these hold:

  1. the lower bound sorts strictly below the upper bound under semver ordering,
     and
  2. either some released version lies between them, or **either bound names a
     prerelease**.

  Clause 2's second half is deliberately generous: once a bound names a
  prerelease, prereleases of that version are admissible, and whether one exists
  in the gap depends on identifiers nobody can enumerate — `>1.2.0-rc1
  <1.2.0-rc2` admits `1.2.0-rc1.1`. Accepting the pair is safe, because a range
  that genuinely matches nothing is caught at resolution with a message naming the
  package; rejecting a valid manifest at load time is not recoverable at all. This
  rule is what tooling MUST implement, not merely a way of arriving at the same
  answer. `>=1.2.0 <2.0.0` is a range; `>=2.0.0 <1.0.0` is
  empty by construction and `1.2.3 1.2.4` is two lower bounds. The schema checks
  the comparator *shape*; tooling MUST reject a pair that is not a range.
- Two entries MUST NOT name the same `id`, even with different ranges. Combining
  them is the author's job, not the resolver's: write `>=1.2.0 <2.0.0`, not two
  entries.
- Resolution is transitive.
- Tooling MUST detect a dependency cycle across packages and refuse, naming the
  cycle. A package reachable from itself is a cycle; a package reachable by two
  different routes is not.
- **Reachability is over the versions actually chosen**, not over every version
  that exists. A loop through a version the resolver did not select is not a
  cycle, and MUST NOT be reported as one: if `a@2.0.0` loops back through `b`
  while `a@1.0.0` requires nothing, then `a@1.0.0` is a perfectly good answer and
  refusing the whole install would be wrong. Only when no combination avoids the
  loop is there a cycle to report.
- When two packages require different ranges of the same dependency, tooling
  MUST resolve each requirement against the versions actually available. If one
  version satisfies both, one install is enough. If the ranges do not overlap
  but each has a satisfying release, tooling MAY install both versions side by
  side rather than refuse.
- When two resolved versions of one dependency coexist, tooling MUST keep their
  installed files disjoint. In particular, libraries from those packages install
  to version-scoped paths under `SCRIPTS/LIBS/pkg/`, for example
  `SCRIPTS/LIBS/pkg/github.com.acme.lib-json.1.2.3/`.
- Tooling MUST refuse only when a requirement has no satisfying version, or when
  the resolved versions would still collide on installed destinations, and it
  MUST name both requirers with their ranges. "A needs ^1.0, B needs ^2.0" is
  actionable; "unsatisfiable constraints" is not.
- A graph can be **both** cyclic and unsatisfiable, and the two rules above then
  both apply. When that happens tooling MUST report the unsatisfiable ranges, and
  MUST name a cycle only when no range conflict can be named. A conflict tells the
  user something they can change; a cycle in a package neither they nor its author
  can restructure does not, and a resolver that reports whichever it stumbled into
  first gives the same graph a different answer depending on the order the
  requirements happened to be listed in. Reporting both is permitted; reporting
  only the cycle when a conflict exists is not.
- Tooling MUST install a dependency before the package requiring it.
- A dependency already on the card counts for a requirement only if its
  installed version **satisfies** that range. When it does not, tooling MUST
  resolve another version for that requirement or refuse, naming the installed
  version, the range and the package that wants it. It MUST NOT install the
  requirer against a version that does not satisfy it, and MUST NOT silently
  replace another installed version — something else on the card may depend on
  the version that is there.
- A package installed only to satisfy a requirement is recorded with
  `reason: dependency`, along with a snapshot of its own `requires` — see
  [State.md](./State.md#dependency-snapshot). Tooling MAY remove such a package
  once no `reason: explicit` package transitively requires it, and MUST NOT
  remove an `explicit` package as an orphan.

Tooling that can fetch from a repository MUST implement `requires`: a package
declaring it and not getting its dependencies is broken, not degraded.

Tooling that cannot fetch — firmware running on the radio, with no network —
MUST instead refuse to install a package declaring `requires` whose dependencies
are not already present, and say which are missing. Silently installing a package
without its dependencies is the one outcome to avoid; requiring a network stack
on a radio to avoid it is not proportionate.

The field is designed to be ignorable, and that is worth recording: tooling that
has never heard of `requires` installs the package alone — a degraded install
rather than a rejected one. That property is what lets the feature evolve by
MINOR bumps; see [CONTRIBUTING.md](../CONTRIBUTING.md#versioning).

## Radio capabilities

```yaml
package:
  capabilities:
    display:
      type: colorlcd          # "bw" or "colorlcd"
      resolution: 480x272     # optional, exact
      touch: true             # optional
```

Every field inside `display` is optional; an omitted field matches anything.
Matching is an AND over the declared fields:

- `touch: true` requires a touchscreen
- `touch: false` requires a non-touchscreen device
- `touch` omitted matches either

Tooling determines the radio's capabilities and MUST refuse to install a package
whose declared capabilities do not match, unless the user explicitly overrides.

**When a capability cannot be determined, it MUST NOT be treated as a
mismatch.** Tooling identifies the radio from the SD card, but mapping a board
to its display geometry and touch support may require a hardware catalog that is
unavailable offline, incomplete, or newer than the tooling. Treating an unknown
value as "does not match" makes packages silently un-installable for reasons the
user cannot see or fix.

So, per capability field:

- **Known, and it matches** — proceed.
- **Known, and it does not match** — refuse, naming both the requirement and the
  actual value.
- **Not determinable** — proceed, and warn that the requirement could not be
  checked, naming the capability. Silence here is what makes an unexplained
  failure on the radio look like a broken package.

The same rule applies to variant selection: a variant filter naming a capability
the tooling cannot determine neither matches nor blocks, so it contributes
nothing to that filter's specificity — see [Selection](#selection) for what
tooling must do when that leaves no usable choice.

## Firmware version constraints

`min_edgetx_version` and `max_edgetx_version` bound the firmware versions a
package supports.

- `min_edgetx_version` MUST be a complete semver. A minimum with an open patch
  level is meaningless, so no wildcard is allowed.
- `max_edgetx_version` MAY use `x` in the **patch position only**:
  `"2.13.x"` bounds the package at any patch level within 2.13.

**Comparison ignores prerelease and build metadata**, for both bounds. A
firmware reporting `2.13.5-rc1` compares as `2.13.5`. Plain semver ordering
would place `2.13.0-rc1` below `2.13.0` and so fail a
`min_edgetx_version: "2.13.0"` check, which would surprise anyone testing a
release candidate or nightly.

> **This is the opposite of the dependency rule.** Firmware bounds ignore the
> prerelease; dependency version ranges exclude unrequested prereleases, so
> `1.3.0-rc1` does not satisfy `^1.2.0` — see
> [Version ranges](#version-ranges). Applying this section's rule to dependency
> resolution would hand users release candidates they never asked for.

**Wildcard expansion.** `MAJOR.MINOR.x` matches any running version whose
`(major, minor)` equals that pair, at any patch level — equivalently an
inclusive upper bound of `(MAJOR, MINOR, ∞)`.

**Range validity.** When both bounds are present, compare
`(major, minor, patch)` with `x` treated as `+∞`. Tooling MUST reject a
manifest where `min` exceeds `max`.

## Variants

Variants are the **same logical package** built for different radio hardware —
black-and-white versus color LCD, or different resolutions. All variants share
one `id`; which one to install is decided at install time.

Three things are called "variant", and keeping them apart makes the rest of this
section unambiguous:

| Term | What it is |
|---|---|
| **variant entry** | An item in the base manifest's `variants` list: a `path` plus a selection filter — capabilities, firmware bounds, or both. Used to *choose*. |
| **variant manifest** | The file that entry's `path` points at. It still declares its own `package.id` and `description`, and its content is merged with the base's explicit overlay fields after selection. |
| **selected variant** | The `variants[].path` string recorded in state, so update keeps the same choice. See [State.md](./State.md#variant). |

**A selected variant is now loaded as base + explicit overlays.** The base
manifest MAY declare:

- `base_capabilities`: install-time hardware requirements inherited by every
  selected variant
- top-level content sections: common content inherited by every selected variant
- content sections on a `variants[]` entry: inline variant-only content appended
  to the inherited base content
- `variants[].capabilities_tighten`: install-time capability fields merged with
  `base_capabilities`

There is still **no general field inheritance**. A variant manifest still
declares its own `package.id` — the same id as its base — and its own
`description`, and its own package block, `requires`, `binary`, `source_dir` and
package-level constraints mean only what that variant manifest says. The merge is
limited to `base_capabilities` plus `capabilities_tighten`, and to the content
sections named above.

```yaml
# edgetx.yml — base manifest
edgetx_format_version: "1.1"
base_capabilities:
  display:
    type: colorlcd
    touch: false
package:
  id: github.com/yaapu/FrskyTelemetryScript
  description: Yaapu Telemetry Script and Widget
  license: GPL-3.0-only
  source_dir: OTX_ETX
  min_edgetx_version: "2.11.0"
  variants:
    - path: edgetx.color.yml
      capabilities:
        display:
          type: colorlcd
      capabilities_tighten:
        display:
          resolution: 480x272
      tools:
        - name: ColorLoader
          path: SCRIPTS/TOOLS/ColorLoader
    - path: edgetx.color-touch.yml
      capabilities:
        display:
          type: colorlcd
          touch: true
      capabilities_tighten: {}
      tools:
        - name: TouchLoader
          path: SCRIPTS/TOOLS/TouchLoader
libraries:
  - name: Common
    path: SCRIPTS/LIBS/yaapu-common
```

```yaml
# edgetx.color.yml — same id as the base; its content is merged after the base
# content and the selected entry's inline content
edgetx_format_version: "1.1"
package:
  id: github.com/yaapu/FrskyTelemetryScript
  description: Yaapu Telemetry (Color LCD)
  license: GPL-3.0-only
  min_edgetx_version: "2.11.0"
widgets:
  - name: yaapu
    path: WIDGETS/yaapu
```

Normative rules:

- A variant entry's selection filter is `capabilities`, `min_edgetx_version`,
  `max_edgetx_version`, or any combination. An entry with none of them matches
  every radio, at specificity 0 — that is the fallback slot.
- `variants[].capabilities_tighten` is **not** part of selection. It merges with
  the base manifest's `base_capabilities` only after a variant has already been
  chosen.
- A variant entry MAY declare any content section (`libraries`, `tools`,
  `widgets`, `telemetry`, `functions`, `mixes`, `sounds`, `images`, `themes`,
  `files`). These do **not** affect selection or specificity; they are inline
  content overlays merged only for the selected entry.
- `base_capabilities` has the same shape as `package.capabilities`. It is an
  install-time overlay only: tooling MUST NOT use it to choose between variants.
- `base_capabilities` merged with `variants[].capabilities_tighten` is a union of
  declared leaf fields. Repeating the same value is allowed; adding a previously
  undeclared field is how a variant tightens the base. Declaring the **same** leaf
  with a different value is invalid and tooling MUST reject it, naming both
  declarations. `capabilities_tighten: {}` is exactly equivalent to omitting the
  field.
- When a variant is selected, tooling forms the final install input in this
  order:

  1. load the base manifest
  2. choose one variant entry
  3. load that entry's variant manifest
  4. merge `base_capabilities` with that entry's `capabilities_tighten`
  5. merge every content section as **base content**, then the selected entry's
     inline content, then the selected variant manifest's own content
  6. validate the merged content before copying anything

  The merge is explicit and narrow. Everything else still follows the existing
  rule: `requires`, package metadata, package-level firmware bounds and
  package-level `capabilities` are read where they are declared, not inherited.

  Inline content declared on a `variants[]` entry behaves exactly like content
  declared at the base manifest's top level for path resolution and copy rules:
  its `path` values resolve against the base manifest's directory and source
  roots, and the base manifest's `package.binary` governs any `.luac` it names.
  Content declared in the selected variant manifest uses that variant manifest's
  own directory, source roots and `package.binary`.

  Collision checks run on the **merged** content set. A selected variant MUST
  NOT introduce:

  - the same content-item `name` as any inherited base item, inline overlay item,
    or item already declared by the selected variant manifest
  - the same destination path as any inherited or selected item, compared
    case-insensitively as everywhere else in this specification

  "Both, stricter winning" needs saying precisely, because the two kinds combine
  differently. For the **firmware bounds** it is the intersection: the higher of
  the two minimums, the lower of the two maximums. For **capabilities** it is the
  union of declared fields — a field either manifest declares is required — and
  where both declare the same field with **different values** the manifest is
  invalid and tooling MUST reject it, naming both. There is no radio satisfying
  `display.type: bw` and `display.type: colorlcd` at once, so treating one as
  "stricter" would be inventing an answer; the author has contradicted
  themselves and only they can say which they meant. The
  distinction is not pedantry: a filter that excludes a radio means "not this
  build", while a package-level bound means "not this package", and only the
  second is an error the user should see.
- `variants[].min_edgetx_version` MUST NOT exceed `variants[].max_edgetx_version`
  after wildcard expansion, exactly as at package level, and tooling MUST reject a
  manifest where it does. An inverted pair is not merely useless: the entry can
  never match, so the build it names is silently unreachable and the package
  installs a fallback — or nothing — with no diagnostic pointing at the typo.
- `variants[].min_edgetx_version` and `variants[].max_edgetx_version` use the
  same grammar as their package-level counterparts — a complete semver for the
  minimum, `x` permitted in the patch position of the maximum — and the same
  comparison, including stripping any prerelease from the running firmware
  version. See [Firmware version constraints](#firmware-version-constraints).

  These exist because a package may ship **precompiled `.luac`** rather than Lua
  source, and bytecode is not portable across every firmware release. Such a
  package has one build per firmware generation and nothing in `capabilities`
  distinguishes them: the radio is the same radio. Without a firmware filter the
  author's only recourse is a separate package per release, each with a different
  `id`, which breaks update.
- A variant manifest MUST declare the same `package.id` as its base. Tooling
  MUST refuse a mismatch.
- A variant entry whose selection filter matches, but whose variant manifest's
  own package-level constraints exclude this radio, MUST be **dropped and
  selection re-run over the rest** — not treated as a refusal of the install.
  The author wrote both, so the entry saying "this build is for firmware 2.12"
  and the build itself saying "I need 2.13" is a contradiction the author
  introduced, and the fallback entry beside it may install perfectly well.
  Refusing outright would make an unreachable entry poison a working package, and
  the rest of this section is built on the principle that a filter says "not this
  build" while a package-level bound says "not this package" — an entry that says
  both means only the first. Only when no entry survives is it `NO_MATCH`.
- When a variant is selected, tooling MUST enforce the package-level
  `capabilities`, `min_edgetx_version` and `max_edgetx_version` of **both** the
  base manifest and the selected variant manifest, with the stricter result
  winning exactly as before. This check is separate from
  `base_capabilities`/`capabilities_tighten`, which are explicit overlay fields.
- **Variant nesting is not allowed.** A manifest loaded through a
  `variants[].path` reference MUST NOT itself declare `variants`. Resolution is
  exactly one level deep.
- `variants[].path` is resolved against the base manifest's directory and MUST
  NOT escape it.

### Selection

When the base manifest declares `variants`, tooling:

1. determines the radio's capabilities and its running firmware version
2. keeps every **variant entry** whose filter matches — every declared
   capability field *and* both firmware bounds must be satisfied
3. picks the match with the highest specificity, defined below
4. on a tie, picks the **first matching variant entry in manifest declaration
   order** — selection MUST be deterministic

The result is a variant entry, and what tooling carries forward is that entry's
`path` string: it is what gets loaded, and what state records as the selected
variant.

**Specificity** is the number of fields in a variant's filter that are both
declared *and* determinable for this radio. A field the tooling cannot determine
contributes nothing: it neither matches nor blocks, so it cannot make one filter
look more specific than another on the strength of information nobody has. Only
**leaf** fields count. Container objects such as `display` are not counted, so a
filter declaring `{type, resolution, touch}` scores 3 against a radio that
reports all three, and 2 against one that cannot report touch. A filter of
`capabilities: {display: {}}` scores 0.

`min_edgetx_version` and `max_edgetx_version` are leaf fields for this purpose
and count 1 each, determinable when the running firmware version is known. They
are counted the same way as capability fields and against the same total, so a
filter naming both bounds outranks one naming `display.type` alone — which is
what a `.luac` package needs, since the firmware generation is the thing that
actually decides whether its bytecode runs.

Two cases tooling MUST NOT resolve by guessing:

- **No variant entry matches.** Refuse, and say which capabilities the radio
  reported and which firmware version it is running. Installing an arbitrary
  variant on unsupported hardware is worse than installing nothing.
- **A field needed to choose cannot be determined.** Concretely: if more than one
  variant entry **matches** *and* any matching entry's filter names a field this
  radio cannot report, tooling MUST require an explicit selection from the user
  rather than picking one.

  This test runs on the matching entries, **before** ranking by specificity, and
  the ordering is the whole point. Specificity is computed from what could be
  determined, so an undeterminable field does not announce itself in the ranking —
  it lowers a score, and the winner is then chosen partly out of ignorance.
  Applied after ranking, the test asks only whether the *survivors* tie, so a
  single determinable field on one entry produces a lone winner and the check
  never fires at all.

  A worked case, because this is easy to get wrong: a bytecode package declares
  entry A bounded to firmware 2.11, entry B bounded to 2.12 *and* filtering
  `display.type: colorlcd`, and entry C with no filter as a fallback. On a
  colour-LCD radio whose firmware version cannot be determined, all three match —
  undeterminable bounds neither match nor block — and their specificities are 0,
  1 and 0. Ranked first, B stands alone and installs silently: bytecode for a
  firmware generation nobody checked. Tested first, two of the three matching
  entries name an undeterminable bound, and tooling asks. An unknown firmware
  version must never be resolved by guessing, and a capability field on one entry
  must not be able to disarm that.

  The declaration-order tie-break above applies only to a *genuine* tie — one
  where every field of every remaining filter was determinable and the entries
  are simply equally specific. Falling back to declaration order when the
  discriminating field is merely unknown would install a black-and-white build on
  a color-LCD radio, or the reverse, deterministically and silently.

  A capability field the tooling does not **recognise** is ignored for *matching*:
  it neither matches nor blocks, exactly as any unknown key is ignored.

  But **adding a field to `display` is a MAJOR change**, for the same reason
  widening a closed enum is. Ignoring a field changes a filter's specificity, and
  specificity chooses which build installs — so an older implementation would not
  merely lose a capability check, it would install a *different variant* than a
  newer one reading the same manifest. Acting on a field's absence in a way that
  is wrong rather than merely limited is the definition of a breaking change.
  Only a *recognised* field whose value this radio cannot report counts as
  undeterminable.

  With no user present — CI, a script, an agent — there is nobody to ask, so
  tooling MUST refuse and report which field it could not determine. It MUST NOT
  fall back to declaration order. A package that needs to install unattended
  should declare its hardware requirement in `package.capabilities` and ship one
  manifest, rather than relying on a variant filter the tooling may be unable to
  evaluate.

### Manual selection and updates

Two equivalent forms override auto-selection:

```sh
edgetx-cli pkg install yaapu/FrskyTelemetryScript --path edgetx.bw128x64.yml
edgetx-cli pkg install yaapu/FrskyTelemetryScript::edgetx.bw128x64.yml
```

Update keeps the installed variant. Switching variants requires an explicit
install — **except** when the installed variant is no longer installable on this
radio. Then update MUST re-run selection rather than keep it or fail.

That exception exists because a variant's correctness is not a property of the
package alone. Firmware changes under an installed package, and a package
shipping precompiled `.luac` has one build per firmware generation: keeping the
2.11 build across a flash to 2.12 leaves bytecode the radio will not execute, and
"reinstall to switch variants" is not advice a user can act on when nothing told
them anything was wrong.

Concretely, update MUST evaluate the selected variant manifest's own
`capabilities`, `min_edgetx_version` and `max_edgetx_version` against the current
radio. If they still hold, the variant is kept. If they do not, update re-runs
selection from the base and reports the switch, and the `NO_MATCH` and
`AMBIGUOUS` rules apply as they do at install. An explicit variant the user chose
is preserved by the first branch in every case where it still works, which is
what "update never changes the variant" was protecting.

Compatibility is evaluated against the radio in front of you, every time — it is
not recorded on the card. A cached verdict has to be invalidated by every
firmware flash and every install, and it is cheap to recompute from the manifest
that is already in hand.

## Subpackages

Subpackages are **distinct packages in one repository**, each with its own
manifest and its own `id` including the subpackage path. They install, update
and remove independently, and may be pinned to different versions. A
subpackage MAY declare its own variants.

```text
offer-shmuely/lua-scripts/
├── log-viewer/
│   ├── edgetx.yml                    # id: …/lua-scripts/log-viewer
│   ├── edgetx.bw128x64.yml
│   └── edgetx.color.yml
└── cell-mix/
    └── edgetx.yml                    # id: …/lua-scripts/cell-mix
```

```sh
edgetx-cli pkg install offer-shmuely/lua-scripts/log-viewer@v1.0.0
edgetx-cli pkg install offer-shmuely/lua-scripts/cell-mix@v2.0.0
```

Tooling parses four or more `id` segments as `host/owner/repo/subpath`. The
clone URL is `https://host/owner/repo.git`; the manifest is loaded from within
`subpath`.

**A manifest loaded as a subpackage MUST declare the `id` that was requested.**
Tooling MUST refuse a mismatch. A checkout is a directory of files and a
subpackage path is user input, so without this check a request can land on a
manifest that was never meant to answer it — and installing the wrong package
silently is worse than failing.

## Validation summary

Every rule that a single file can demonstrate is checked, and this table says
where. Rules about *behaviour* — what tooling does with a manifest, rather than
what a manifest may contain — cannot be pinned by a fixture at all; they are
listed under [Behavioural rules](#behavioural-rules) below, so that nothing here
looks covered when it is not.

### Checked by the JSON Schema

Run [`schema/edgetx-manifest.v1.json`](../schema/edgetx-manifest.v1.json) and
these hold without any further work:

| Rule | Fixture |
|---|---|
| `package`, `package.id` and `package.description` are present | `missing-id.yml`, `missing-description.yml` |
| `id` shape, length, and no `.git` on any segment | `invalid-id-format.yml`, `id-with-git-suffix.yml`, `id-with-git-mid-segment.yml` |
| `edgetx_format_version` is `MAJOR.MINOR` with no leading zeros | `invalid-format-version.yml`, `format-version-leading-zero.yml` |
| `version` is strict semver | `invalid-version-format.yml`, `version-leading-zero-prerelease.yml` |
| `min_edgetx_version` carries no wildcard | `wildcard-in-min-version.yml` |
| A variant entry's `min_edgetx_version` carries no wildcard | `wildcard-in-variant-min-version.yml` |
| Every [path rule](#path-rules), `reserved-device-name.yml` | `absolute-path.yml`, `backslash-path.yml`, `dotdot-in-dest.yml`, `dot-segment-in-path.yml`, `control-char-in-path.yml`, `trailing-space-in-dest.yml`, `reserved-device-name.yml` |
| `dest` is required when `path` is `.` | `path-dot-without-dest.yml` |
| `dest` is outside `PKG/`, case-insensitively | `dest-in-reserved-pkg.yml`, `dest-in-reserved-pkg-lowercase.yml` |
| `path` is outside `PKG/` too, since it is the destination when `dest` is absent | `path-in-reserved-pkg.yml` |
| `dest` is not `.` | `dest-is-dot.yml` |
| `variants[].path` ends in `.yml`/`.yaml` and stays inside the manifest directory | `invalid-variant-path.yml`, `dotdot-in-variant-path.yml` |
| `requires[].id` is a canonical package id | `requires-bad-id.yml` |
| `requires[].version` matches a supported comparator shape | `requires-bad-version-range.yml`, `requires-leading-zero-prerelease.yml` |
| `requires[].version` carries no build metadata | `requires-with-build-metadata.yml` |
| At most 512 content items in any one section | `too-many-content-items.yml` |
| At most 64 `requires` entries | `too-many-requires.yml` |
| A two-comparator range is a lower bound then an upper bound | `caret-in-two-comparator-range.yml` |
| `authors[].email` is a valid address | `malformed-email.yml` |
| `urls[].url` is an absolute HTTP(S) URL with an authority | `malformed-url.yml`, `malformed-http-url-no-authority.yml`, `malformed-http-url-empty-authority.yml` |

**A note on the two `format` keywords.** `urls[].url` carries both a `pattern`
and `format: uri`; the pattern is what actually holds, because `format` is an
annotation in JSON Schema 2020-12 and the `uri` assertion needs an optional
dependency. `authors[].email` carries `format: email` and no pattern, so it is
**not** reliably enforced — deliberately. An address is metadata, and rejecting
a whole package because one author wrote something a parser dislikes is worse
than accepting it. `malformed-email.yml` is therefore rejected only by a
validator with format checking enabled, which is what this repository's runner
and `check-jsonschema` both do.

### Checked by tooling at load time

No schema can express these. A conforming implementation MUST check them
itself.

| Rule | Why the schema cannot | Fixture |
|---|---|---|
| Every declared `source_dir` is a directory | Needs the source tree | — |
| Every `path` resolves under some declared source root, with no fallback | Needs the source tree | `source-dir-no-fallback.yml` |
| Every `screenshots` entry resolves to a file — SHOULD, not MUST | Needs the source tree | — |
| `min_edgetx_version` ≤ `max_edgetx_version` after wildcard expansion | Comparing two values | `inverted-version-range.yml` |
| No `requires` entry names the manifest's own `id` | Comparing two values | `requires-self.yml` |
| No two `requires` entries name the same `id` | `uniqueItems` compares whole objects, not one property | `duplicate-requires-id.yml` |
| Two comparators form a non-empty range | The schema checks comparator shape, not satisfiability | `inverted-requires-range.yml` |
| Content-item `name` values are unique, including across base + selected variant overlays | Cross-reference within the document, the selected variant entry, and the selected variant manifest | `duplicate-content-name.yml`, `variant-overlay-duplicate-name.yml`, `variant-overlay-entry-manifest-duplicate-name.yml` |
| No two content items resolve to one destination, compared case-insensitively, including across base + selected variant overlays | Needs both destinations resolved | `duplicate-destination.yml`, `case-only-destination-collision.yml`, `variant-overlay-duplicate-destination.yml` |
| No single-file item's destination is an ancestor of another item's, compared the same way at a `/` boundary | Needs the source tree, to know which items are single files | `ancestor-destination-overlap.yml` |
| A variant entry's `min_edgetx_version` ≤ its `max_edgetx_version` after wildcard expansion | Comparing two values | `inverted-variant-range.yml` |
| A file is not installed over a directory, or a directory over a file — checked with the other collisions, before anything is written. Both directions, and for **every ancestor** of a staged file, owned or not: a package installing `A/b.lua` destroys another package's file `A`, and a user's own file at `A` kills the copy after the marker is written. Batch members are checked against each other the same way, not merely for equal destinations | Needs the source tree and the card | `dest-kind-mismatch.yml` |
| `license` parses as an SPDX expression — SHOULD, not MUST | Needs the SPDX identifier list | `malformed-license.yml` |
| A variant manifest declares the same `id` as its base | Needs the other manifest | `variant-id-mismatch.yml` |
| A manifest loaded as a variant declares no `variants` | Depends on how it was loaded | `nested-variants.yml` |
| A manifest loaded as a subpackage declares the requested `id` | Depends on how it was loaded | — |
| Every resolved destination lies inside the SD card root | Needs the resolved filesystem | — |

Rows with no fixture need the network, a live filesystem, or the tooling's own
version to demonstrate, so no single file can express them. `run_tests.py`
enforces the rest of this table: every fixture named above must exist, and every
fixture the runner treats as load-time-only must appear here. An index nobody
checks drifts.

### Behavioural rules

These are normative and no fixture can express them: each is about what tooling
*does*, not about what a manifest may contain. A behavioural suite driving a real
implementation would cover them, and would be the most valuable addition to this
repository — see
[CONTRIBUTING.md](../CONTRIBUTING.md#rules-with-no-fixture).

| Rule | Stated in |
|---|---|
| Unknown keys are ignored; an unknown key never makes a manifest invalid | [edgetx_format_version](#edgetx_format_version) |
| An unknown MAJOR is refused; an unknown MINOR is processed | [edgetx_format_version](#edgetx_format_version) |
| The manifest filename is `edgetx.yml` exactly | [Conformance and terminology](#conformance-and-terminology) |
| An `id` is lowercased before storing or comparing | [Package id](#package-id) |
| A dependency's version comes from its manifest, never from a tag name | [Resolving a requirement to a version](#resolving-a-requirement-to-a-version) |
| Dependencies are installed before the package requiring them | [requires validation rules](#requires-validation-rules) |
| No dependency cycle across packages | [`requires` validation rules](#requires-validation-rules) |
| No two packages require incompatible ranges of one dependency | [`requires` validation rules](#requires-validation-rules) |
| A package whose declared capabilities do not match is refused | [Radio capabilities](#radio-capabilities) |
| Version-control metadata and the manifest files themselves are skipped when copying a directory | [Content item fields](#content-item-fields) |
| An owned `.luac` is never treated as derived, stale or regenerable | [Content item fields](#content-item-fields) |
| Tooling's own compile never overwrites a `.luac` the package ships | [Content item fields](#content-item-fields) |
| Variant selection matches a firmware bound and counts each as one leaf field | [Selection](#selection) |
| A matching entry whose variant manifest excludes this radio is dropped and selection re-run | [Variants](#variants) |
| `base_capabilities` and `capabilities_tighten` merge only by adding fields or repeating the same value; a conflicting leaf is rejected | [Variants](#variants) |
| Destination checks cover `dev` items whether or not `--dev` was passed | [Content item fields](#content-item-fields) |
| Batch members are checked against each other for the `.lua`/`.luac` pair, which ownership cannot see | [State.md § Durability](./State.md#durability) |
| The inventory bound is checked before the operation marker is written | [State.md § Resource limits](./State.md#resource-limits) |
| When a graph is both cyclic and unsatisfiable, the range conflict is reported and the cycle only if none can be named | [`requires` validation rules](#requires-validation-rules) |
| Nothing on the card is modified until every refusable check has passed and the marker is written | [State.md § Durability](./State.md#durability) |
| Both the base manifest's and the selected variant's package constraints are enforced, stricter winning | [Variants](#variants) |
| Update re-runs selection when the installed variant is no longer installable | [Manual selection and updates](#manual-selection-and-updates) |
| A `.luac` destination replacing bytecode derived from a `.lua` the package already owned skips the overwrite policy | [State.md § Bytecode companions](./State.md#bytecode-companions) |
| An undeterminable capability is not treated as a mismatch | [Radio capabilities](#radio-capabilities) |
| Variant selection is deterministic, and never guesses | [Selection](#selection) |
| Every `exclude` matching rule | [`exclude` patterns](#exclude-patterns) |
| A more specific content section is preferred over `files` | [Content sections](#content-sections) |
| A path violating the rules is rejected, never repaired | [Path rules](#path-rules) |
| Tooling that can fetch implements `requires`; tooling that cannot refuses a package whose dependencies are absent and names them | [`requires` validation rules](#requires-validation-rules) |
| Prerelease handling, which differs between the two version comparisons | [Version ranges](#version-ranges), [Firmware version constraints](#firmware-version-constraints) |
| A package reference is parsed per the reference grammar | [Package references](#package-references) |
| Paths are compared after NFC normalisation — SHOULD, not MUST | [Path rules](#path-rules) |
| Duplicate mapping keys are rejected | [edgetx_format_version](#edgetx_format_version) |
| A manifest over 256 KiB is refused | [edgetx_format_version](#edgetx_format_version) |
| YAML alias expansion is bounded at ten times the file's size | [edgetx_format_version](#edgetx_format_version) |
