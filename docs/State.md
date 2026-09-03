# State Files Reference

This document is normative. It describes the state the package manager keeps on
the SD card so that update and remove can work correctly. Its machine-checkable
subset is [`schema/edgetx-state.v1.json`](../schema/edgetx-state.v1.json),
which is normative too. Terminology follows
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119), as set out in
[Manifest.md](./Manifest.md#conformance-and-terminology).

## Contents

- [Reserved namespace](#reserved-namespace)
- [`installed.yml`](#installedyml)
  - [Required and optional fields](#required-and-optional-fields)
  - [`source`](#source)
  - [`variant`](#variant)
  - [Dev content is not recorded](#dev-content-is-not-recorded)
  - [Dependency snapshot](#dependency-snapshot)
  - [`edgetx_format_version`](#edgetx_format_version)
- [`PKG/files/<package-id>.list`](#pkgfilespackage-idlist)
  - [Ownership](#ownership)
  - [Bytecode companions](#bytecode-companions)
    - [The derived-bytecode exception](#the-derived-bytecode-exception)
    - [Owned bytecode](#owned-bytecode)
- [Resource limits](#resource-limits)
- [Durability](#durability)
- [Orphan removal and dependency reasons](#orphan-removal-and-dependency-reasons)
- [Package id as a key](#package-id-as-a-key)
- [Validation summary](#validation-summary)
  - [Checked by the JSON Schema](#checked-by-the-json-schema)
  - [Checked by tooling at load time](#checked-by-tooling-at-load-time)
  - [Behavioural rules](#behavioural-rules)
- [Migration](#migration)

## Reserved namespace

All package manager state lives in a single top-level directory on the SD card:

```text
PKG/
├── installed.yml              # one entry per installed package
├── files/
│   └── <package-id>.list      # files installed by that package
└── .operation                 # present only while an operation is running
```

`PKG/` is **reserved** for the package manager. Tooling MUST reject any content
destination beginning with `PKG/`, **compared case-insensitively**, and MUST NOT
store package content there. FAT32 does not distinguish `PKG` from `pkg`, so a
case-sensitive check would let `dest: pkg/installed.yml` reach the state file.

`PKG/` sits at the SD card root alongside the other purpose-owned directories
(`SCRIPTS/`, `WIDGETS/`, `THEMES/`, `SOUNDS/`, `IMAGES/`, `MODELS/`, `RADIO/`,
`FIRMWARE/`). Keeping it separate from `RADIO/`, which holds firmware settings,
means package state has exactly one owner — and gives users a simple recovery
action: **deleting `PKG/` makes the package manager forget everything while
leaving installed files in place.** A subsequent install re-adopts them — but
those files are untracked once the state is gone, so the install needs an
explicit `overwrite` policy. Under the required `fail` default it stops and
names the first file instead, which is correct behaviour and not what a user
following this advice expects.

## `installed.yml`

One entry per installed package.

```yaml
edgetx_format_version: "1.0"
packages:
  - id: github.com/offer-shmuely/lua-scripts/log-viewer
    name: Log Viewer
    version: "1.2.0"
    variant: "edgetx.color.yml"
    reason: explicit
    installed_at: "2026-08-23T12:40:00Z"
    source:
      repo: github.com/offer-shmuely/lua-scripts
      channel: tag
      ref: "v1.2.0"
      commit: "9f1c2ab0d4e7a3b6c9f2e5a8d1b4c7e0a3f6b9c2"
      origin: null
      path: null
      manifest_path: "log-viewer/edgetx.yml"
    requires:
      - id: github.com/someone/elrs-libs
        version: "^2.0.0"
```

### Required and optional fields

Tooling MUST write every field marked required, and MUST accept an entry in
which any optional field is absent or `null`. **An absent field and an explicit
`null` are equivalent.**

| Field | Required | Description |
|---|---|---|
| `id` | **yes** | The package's canonical id, from its manifest. Primary key: at most one entry per id. |
| `version` | **yes** | The `package.version` recorded at install, or `null` when the manifest declared none. Compared against a newly resolved manifest to detect updates. |
| `reason` | **yes** | `explicit` when the user asked for this package; `dependency` when it was installed to satisfy a `requires` entry. Drives orphan cleanup. |
| `source` | **yes** | Where the package came from — see below. |
| `variant` | no | The selected variant, or `null`. See [variant](#variant). |
| `name` | no | Display name copied from the manifest. Presentation only; tooling MUST NOT key on it. |
| `installed_at` | no | RFC 3339 timestamp with the `Z` UTC designator. Offset forms such as `+00:00` MUST NOT be used, so the value sorts and compares textually. |
| `requires` | **yes** | Snapshot of the manifest's `requires` list, `[]` when the manifest declares none — see [Dependency snapshot](#dependency-snapshot). |

### `source`

| Field | Required | Description |
|---|---|---|
| `channel` | **yes** | `tag`, `branch`, `commit` or `local`. How the version was resolved. |
| `repo` | **yes** | The repository the `id` designates — the `id` **minus any subpackage path**. For `github.com/owner/repo/log-viewer` this is `github.com/owner/repo`, since that is what gets cloned. It MUST equal the `id` or be a prefix of it ending at a `/`. That is a necessary condition and not a sufficient one: how many segments a repository has is not fixed, because hosts nest differently — a GitLab subgroup makes `gitlab.com/group/sub/project` one repository — so a prefix that stops in the wrong place cannot be detected here and is caught by the fetch instead. |
| `commit` | **yes** except `local` | The full resolved commit object id in lowercase hex: 40 characters for SHA-1, 64 for a SHA-256 repository. Abbreviated ids MUST NOT be recorded. |
| `ref` | no | The tag or branch name resolution chose — a dependency resolves to a *tag*, not merely a version, and this is where that choice is recorded. `null` for `commit` and `local`. This value is read off a removable card and handed to a fetch, so it is constrained like a path: no control characters, no leading `-` that a command line would read as an option, and only characters a git refname may contain. |
| `origin` | no | Set when the package was fetched from somewhere other than its declared `id` — a fork. `null` otherwise. When present, update MUST re-resolve from `origin`, not from `repo`: the user chose the fork, and silently migrating them back upstream would install different code than they asked for. |
| `path` | no | Absolute path on the **host** filesystem, for `channel: local`. Update re-reads the package from here; when the directory is gone, tooling reports that rather than treating the package as up to date. For a local install the symlink anchor is this directory, since there is no checkout. This is the one path in state that is not an SD card path, so the [path rules](./Manifest.md#path-rules) do not apply to it — but it MUST carry no control characters. `null` otherwise. |
| `manifest_path` | **yes** | Repo-relative path of the manifest that was loaded. When a variant was selected this is the **base** manifest, so update re-runs variant selection from the same starting point. |

Tooling MUST record `source.commit` whenever it is known. Without it a
force-pushed tag or branch is undetectable, and there is no way to say what is
actually installed. `version` answers whether an update exists; `commit`
answers what is installed.

### `variant`

`variant` stores the **exact string from the base manifest's
`variants[].path`** — not a basename. If the base declares
`path: variants/color.yml`, state records `variants/color.yml`. This is what
makes `variant` comparable against the new manifest's `variants` list on
update.

### Dev content is not recorded

Whether `dev: true` content was included is deliberately **not** recorded.
`--dev` is a developer's flag; each operation states what it wants, and no
operation infers it from an earlier one. An install with `--dev` followed by a
bare update leaves only the shipped content, and that is intended. See
[Manifest.md](./Manifest.md#content-item-fields).

### Dependency snapshot

`requires` mirrors the manifest's `requires` list at install time, as `[]` when
the manifest declares none. Tooling MUST record it, and every conforming
implementation does: tooling that can fetch resolves `requires`, and tooling that
cannot still has to know what a package asked for in order to refuse it and name
what is missing. See [Manifest.md](./Manifest.md#requires--other-packages).

Without the snapshot neither rule is computable offline: deciding whether a
`reason: dependency` package is still needed means knowing what every installed
package requires, and manifests are not kept on the card. State exists to answer
questions about installed packages without going back to the network — but only
questions whose answers cannot be recomputed, which is why the snapshot is here
and a compatibility verdict is not.

### `edgetx_format_version`

`installed.yml` carries the same `edgetx_format_version` as a manifest, with the
same numbering — one number covers both formats because they are released
together. The rules differ, because state is written as well as read:

- Tooling MUST refuse to **read** state whose MAJOR is greater than its own, and
  say that newer tooling is required. Listing packages out of a format you do not
  understand invites acting on a misreading — a manifest gets the same treatment,
  see [Manifest.md](./Manifest.md#edgetx_format_version).
- Tooling MUST refuse to **write** to such state for the same reason, and because
  rewriting it would silently discard fields it does not recognise.
- Tooling MUST read state with a MAJOR less than or equal to its own, and MUST
  tolerate a higher MINOR by ignoring fields it does not recognise.
- Absence means `"1.0"`, and MUST NOT be warned about.

## `PKG/files/<package-id>.list`

One file per package, listing every file that package installed.

The package id becomes the filename with each `/` replaced by `%`, for example
`github.com%offer-shmuely%lua-scripts%log-viewer.list`. `%` is not legal in an
id segment, so the mapping is unambiguous and reversible. Package ids are
capped so that the resulting name stays within the FAT32 filename limit.

One SD-card-relative path per line, `/`-separated, LF or CRLF terminated:

```text
SCRIPTS/TOOLS/LogViewer/main.lua
SCRIPTS/TOOLS/LogViewer/lib/parse.lua
SCRIPTS/LIBS/Common/init.lua
```

- Every line MUST satisfy the [path rules](./Manifest.md#path-rules) **and MUST
  NOT be `PKG` or begin with `PKG/`**, compared case-insensitively — a file list
  records installed destinations, so it carries the destination rules and not
  merely the path rules, which deliberately permit `PKG/` for repository-relative
  paths. A line naming the state file is a delete primitive against the state
  file. The path rules exclude control characters, so no path can span or forge a
  line and no escaping mechanism is needed.
- Blank lines MUST be ignored.
- A line that violates the path rules MUST be reported and MUST NOT be acted
  on. Deleting a path read blindly from a removable card is how a state file
  becomes a weapon.

A per-package file avoids re-reading every package's inventory for every
operation, and makes removal a single file delete.

Fixtures for this format live in
[`conformance/file-lists/`](../conformance/file-lists/); it has no JSON Schema,
so the runner checks each line against the same pattern the manifest schema
applies to `dest`.

### Ownership

- Ownership is tracked **per file**, not per directory or per content item. Two
  packages MAY install into the same directory as long as no individual file
  collides.
- **Directories are never owned.** On remove, tooling deletes the package's
  files, then prunes directories that are now empty. It MUST NOT delete a
  non-empty directory and MUST NOT prune above the SD card root or into `PKG/`.
- Comparison of two paths is **case-insensitive**, after applying the path rules —
  see [Manifest.md](./Manifest.md#path-rules), which is canonical. The path rules
  remove the redundant spellings (`.` segments, doubled separators, trailing
  spaces and dots) and case folding removes the rest. Comparing case-sensitively
  here would let a package take over another's files by changing the case of a
  `dest`, which is exactly what per-file ownership exists to prevent.
- Before install, tooling MUST check every destination file against the file
  lists of other packages. Reconciliation MUST also report two lists claiming
  one destination: it cannot arise from a conforming install, but it can from a
  hand-edited card or an interrupted operation, and until it is resolved
  removing either package deletes the other's file. A collision with a file owned by a different package
  is an error naming the owner.
- A destination file that exists but is owned by no package is untracked.
  Overwriting it is destructive, so tooling MUST apply an explicit overwrite
  policy rather than deciding silently. The policy MUST be one of:

  | Policy | Behaviour |
  |---|---|
  | `fail` | Refuse the operation, naming the file. **The required default when no user is present** — CI, scripted, or agent-driven runs. |
  | `overwrite` | Overwrite the file — or, during a remove, delete it — and report each one. |
  | `prompt` | Ask, per file. Declining is equivalent to `fail`. |

  The policy is an input to the operation, never a question asked from inside
  it. See [Implementation.md](./Implementation.md#staging-and-conflict-detection)
  for the worked routine.
- Reinstalling or updating a package MAY overwrite files it already owns.

### Bytecode companions

EdgeTX runs `.luac` bytecode in preference to a `.lua` source of the same name,
so a stale `.luac` silently shadows a newer script. Two rules follow from that,
and both are about **untracked** bytecode — the radio compiles `main.lua` to
`main.luac` beside the source the first time it runs it, so a card in use is full
of the stuff, some of it derived and some of it written by the user.

Throughout this section the extension comparison is case-insensitive, like every
other destination comparison, and the sibling sought is the destination's own
spelling with `c` appended or removed.

> **Writing or deleting a `.lua`.** Tooling MUST delete the sibling `.luac` if it
> exists and no package owns it, subject to the same
> [overwrite policy](#ownership) as any other untracked file — except as the
> derived-bytecode exception below allows.
>
> **Writing a `.luac`.** Tooling MUST apply that same policy to an **untracked**
> `.lua` sibling, and to any untracked file already at the destination. Under
> `overwrite` the user's `.lua` is **left in place**, not deleted: it is being
> shadowed rather than overwritten, and removing a file the package never
> declared would be worse. The policy's job here is only to make sure somebody
> chose.
>
> Because a sibling is never in staging, the collision check cannot see it.
> Tooling MUST therefore scan for the siblings it would touch and apply the
> policy **before** writing the operation marker — a separate pass, for install,
> update, reinstall and remove alike. Refusing after the marker is written leaves
> a card permanently reporting an unfinished operation.

Without the policy a package could delete any of the user's bytecode by declaring
a `.lua` at its path, and neither the collision check nor the untracked-file
warning would see it. That applies to **remove** as much as to install, so remove
takes an overwrite policy too: otherwise a package that declares a one-line `.lua`
beside a user's hand-compiled bytecode deletes it on uninstall, and the attacker
need only wait.

#### The derived-bytecode exception

During an **install, update or reinstall**, when the operating package **already
owned the `.lua` at that destination before this operation began**, an untracked
`.luac` there is that script's own compiled output: tooling deletes or overwrites
it without applying the policy.

Without the exception the policy is unusable — every package the user has ever
run has derived bytecode beside its source, so the required `fail` default would
refuse every unattended update of every such package, and the interactive path
would prompt about a file the package itself caused to exist.

Three parts of that sentence are load-bearing:

- **Before this operation began** means the file list **on the card**, not the
  list being staged. The staged list already claims the destination — that is
  what staging is — so testing against it fires the exception on a *first*
  install, which hands back exactly the delete primitive the policy exists to
  remove. Tooling MUST read the card's list.
- **Not remove.** On remove the package always owns the `.lua`, so an exception
  scoped to ownership alone would always fire and would silently delete bytecode
  the user compiled deliberately. At remove time the radio's output and a
  deliberate override are indistinguishable, and nothing is being written that
  could shadow anything, so remove asks.
- **Deletes or overwrites**, covering the destination itself and not only the
  sibling. A package migrating from source to shipped bytecode declares `X.luac`
  where it previously declared `X.lua`, and the radio's `X.luac` is sitting at
  exactly that destination. Without this, that migration refuses under the
  required default on every card where the script has ever been run.

#### Owned bytecode

A `.luac` that *is* owned by a package is ordinary content for copying and
removal — including in a package that ships bytecode and **no source**, which is
a supported shape rather than a degraded one; see
[`binary`](./Manifest.md#content-item-fields). None of the rules above reach it.
But it is not ordinary for conflict detection:

> A destination `X.luac` collides with an owned `X.lua`, and a destination
> `X.lua` collides with an owned `X.luac`, even though the names differ. Tooling
> MUST refuse such an install, naming the owner.

Without that rule a package can ship `SCRIPTS/TOOLS/Popular.luac`, set
`binary: true`, and have the radio execute it instead of another package's
`SCRIPTS/TOOLS/Popular.lua` — arbitrary code substitution with no collision
reported, because per-file ownership compares names and these two differ. The
`.lua`/`.luac` pair is the one case where two distinct names are one executable.

## Resource limits

`PKG/installed.yml` is read on every operation and comes off a removable card,
so it gets the same treatment as a manifest — see
[Manifest.md](./Manifest.md#edgetx_format_version) for the reasoning.

State MUST NOT exceed 512 KiB, MUST NOT record more than 512 packages, and MUST
NOT record more than 64 `requires` entries for any one package. A single file
list MUST NOT exceed 1 MiB or 8192 lines — it is the larger artifact, one content
item may name a directory of any size, and every operation reads every list to
answer ownership.

That bound is checked with the other refusable checks, **before the operation
marker is written** — not at the point state is serialised, which is after the
files are already on the card. Refusing there leaves the copy done and the marker
standing, which is the wedge the ordering rule exists to prevent. It applies when
**writing** as well as reading: tooling MUST refuse an
install whose inventory would exceed it, naming the count, before anything
reaches the card. A read-side bound alone is worse than none — a package of nine
thousand files installs, and every subsequent operation on *any* package then
refuses to load the list it must read to proceed, with the offending package
removable only through the file the tooling will not open. Tooling MUST
refuse to load state that exceeds these, reporting which bound was hit rather
than failing obscurely, and MUST bound YAML alias expansion as a manifest does.

## Durability

The goal is that an interrupted operation is **detectable and recoverable by
the user**, not that it is invisible. This is a hobbyist tool writing to a FAT32
card over USB mass storage: atomic rename and `fsync` do not have meaningful
guarantees there, and a browser-based implementation has neither. Specifying a
protocol that cannot be honoured would be worse than specifying a modest one
that can.

Requirements:

1. **State writes are replace-in-place.** Write `installed.yml` and each file
   list to a temporary name in the same directory, then replace the target.
   Tooling SHOULD request a flush where the platform offers one.

2. **A state file that fails to parse MUST NOT be silently discarded.** Report
   it and stop; do not overwrite it with an empty document. Losing state
   orphans every installed file.

3. **An operation marker.** Before modifying anything on the card — and after
   every check that can refuse the operation — tooling writes `PKG/.operation`,
   and deletes it once the final state write completes. The ordering matters: a
   refusal that happens *after* the marker is written leaves the card reporting
   an unfinished operation forever, so a package that trips the overwrite policy
   could wedge an unattended tool with a single file.

   ```yaml
   operation: install
   package_id: github.com/acme/my-tool
   started_at: "2026-08-23T12:40:00Z"
   ```

   | Field | Required | Description |
   |---|---|---|
   | `operation` | **yes** | Exactly one of `install`, `update`, `remove`. |
   | `package_id` | **yes** | The package the **user asked for**. |
   | `started_at` | **yes** | RFC 3339 timestamp with the `Z` designator. Not nullable — the interruption report depends on it. |

   The marker is YAML, and it is validated against `#/$defs/operationMarker` in
   [`schema/edgetx-state.v1.json`](../schema/edgetx-state.v1.json) — **not**
   against that schema's root, which describes `installed.yml`. One schema file
   carries both formats.

   `package_id` names the package the user asked for. One marker covers the whole
   request: an install that also pulls in dependencies writes one marker for the
   requested package, not one per dependency, so an interruption is always
   reported against something the user recognises.

   That has a consequence for ordering, because "after every check that can
   refuse" and "one marker for the whole request" would otherwise conflict as
   soon as a package has dependencies. **Resolve and stage the entire batch —
   the requested package and every dependency — and run every refusable check
   over all of it, before the single marker is written.** Installing a dependency
   first and then discovering a conflict in the requester leaves a
   `reason: dependency` package that nothing requires, or a marker naming a
   package the user has never heard of.

   Within a batch, staged destinations MUST be checked against **each other** as
   well as against installed packages. Neither is installed yet, so the ownership
   check alone sees no collision — and both file lists would then claim the same
   file, so removing either would delete the other's content.

   That check covers **equal destinations**, **ancestors**, file-versus-directory
   kind, and the **`.lua`/`.luac` pair** — the same ground as the card check, and
   the last of those is the one an implementation will miss. Against the card the
   sibling test works by asking who owns the counterpart, and ownership is read
   from file lists; no batch member has one yet, so that question returns "nobody"
   for every member and the test silently passes. It has to be asked of the batch
   directly.

   Missing it is not a tidiness problem. A package declaring
   `SCRIPTS/TOOLS/Popular.luac` and naming the package that ships
   `SCRIPTS/TOOLS/Popular.lua` as a `requires` entry forces both into one batch,
   and the radio then executes the first package's bytecode wherever the second's
   script was called for — arbitrary code substitution, with two file lists that
   each look correct. Installing the same two packages one after the other is
   correctly refused, which is what makes the batch path a hole rather than a
   decision. One batch
   member staging the file `SCRIPTS/T` while another stages
   `SCRIPTS/T/inner.lua` is a collision even though no two destinations are
   equal: the copy would fail partway through with the marker already written,
   which is the outcome the ordering rule above exists to prevent. Comparing
   destinations for equality alone leaves that case open, and an ordinary
   two-item manifest reaches it.

   Unknown fields MUST be ignored, as everywhere else — a later MINOR format
   revision may add one.

4. **On startup, a present `PKG/.operation` means the last operation did not
   finish.** Tooling MUST report which package and which operation were
   interrupted, and MUST NOT silently continue as if state were consistent. It
   SHOULD offer to reconcile. Re-running the same install or remove is the
   normal fix, and is safe because both are idempotent.

5. **Reconciliation.** Tooling SHOULD provide a command that compares
   `installed.yml` and the file lists against what is on the card, and reports:
   files recorded but missing, files present but unowned, packages whose state
   no longer matches the firmware, and `reason: dependency` packages that
   nothing requires. This replaces automatic rollback: it is inspectable, it
   needs no shadow copies of user data, and it also repairs damage the package
   manager did not cause.

Deliberately **not** required: per-file backups before overwrite, per-file
checksums, lock files with process-liveness detection, and automatic
transactional rollback. Each costs SD write volume, free space and complexity
out of proportion to the failure it prevents, and none can be implemented
uniformly across firmware, desktop and browser tooling. The worst realistic
outcome without them — reinstall the package — is acceptable.

Tooling MUST serialise its own operations within a process. It is not required
to defend against a second tool writing to the same card concurrently; that is
the same hazard as unplugging the card mid-write, and the operation marker makes
it detectable.

## Orphan removal and dependency reasons

How a dependency gets recorded is covered by
[Dependency snapshot](#dependency-snapshot); this section is what that record is
*for*.

A package installed only to satisfy another package's `requires` entry is
recorded with `reason: dependency`. It is a full package with its own entry and
its own file list — dependencies are not merged into their requirer.

- On remove, tooling MAY remove a `reason: dependency` package once no remaining
  `reason: explicit` package transitively requires it, computed from the
  [dependency snapshots](#dependency-snapshot).
- Tooling MUST NOT remove a `reason: explicit` package as an orphan.
- Installing a package that is already present as `reason: dependency`, this
  time explicitly, promotes it to `reason: explicit`. This applies to the
  reinstall path too — an explicit install of an installed package goes through
  reinstall, so a reinstall that preserved `reason` unchanged would make the
  promotion unreachable.
- Removing a package MUST NOT leave another package's `requires` unsatisfied
  without saying so. Tooling SHOULD refuse, or warn and name the packages left
  without a dependency.

All of a package's content installs and is removed together, libraries
included — ownership is per file, but the unit of install and removal is the
package. See [Manifest.md](./Manifest.md#dependencies).

## Package id as a key

- `id` is the primary key. Two entries MUST NOT share an id.
- Comparison follows the id rules in
  [Manifest.md](./Manifest.md#package-id): an `id` is case-insensitive throughout
  and is lowercased before it is stored or compared.
- That rule matters twice as much here as in a manifest. File-list names are
  derived from the id, and FAT32 filenames are case-insensitive, so two ids
  differing only in case would collide on disk — one `.list` file for two state
  entries.

## Validation summary

Where each rule in this document is checked. Same three-part split as
[Manifest.md](./Manifest.md#validation-summary).

### Checked by the JSON Schema

[`schema/edgetx-state.v1.json`](../schema/edgetx-state.v1.json) holds these:

| Rule | Fixture |
|---|---|
| `id`, `version`, `reason`, `source` and `requires` are present | `missing-requires.yml` |
| `reason` is `explicit` or `dependency` | `bad-reason.yml` |
| `source.commit` is present unless `channel` is `local` | `missing-commit.yml` |
| `source.commit` is 40 or 64 lowercase hex characters | `abbreviated-commit.yml` |
| `source.path` is present when `channel` is `local` | `local-without-path.yml` |
| `source.path` is absolute and carries no control characters | `relative-local-path.yml` |
| `variant` and `source.manifest_path` satisfy the [path rules](./Manifest.md#path-rules) | `variant-path-escape.yml` |
| `requires[].version` matches the manifest's range grammar | — |
| `source.ref` is a legal git refname with no traversal | `ref-traversal.yml` |
| At most 512 packages and 64 `requires` entries per package | — |
| Timestamps use the `Z` UTC designator | `timestamp-with-offset.yml` |
| A marker declares `operation`, `package_id` and `started_at` | `marker-missing-operation.yml` |
| A marker's `operation` is one of the three values | `marker-bad-operation.yml` |
| Every file-list line satisfies the [path rules](./Manifest.md#path-rules) | `valid.list`, `valid-crlf.list`, `invalid-absolute.list`, `invalid-dotdot.list`, `invalid-backslash.list`, `invalid-reserved.list`, `invalid-dot-segment.list`, `invalid-line-separator.list` |

### Checked by tooling at load time

| Rule | Why the schema cannot | Fixture |
|---|---|---|
| No two entries share an `id` | `uniqueItems` compares whole objects, not one property | `duplicate-package-id.yml` |
| `source.repo` is the `id` or a prefix of it at a `/` boundary — necessary, not sufficient | Repository depth varies by host, so no pattern can say where the repo ends, and none can compare two values in one document | `repo-not-prefix-of-id.yml` |
| No two file lists claim the same destination | Needs every list read together | — |
| Timestamp components are in range | Needs date arithmetic, not a pattern | — |

### Behavioural rules

Normative and not expressible as a fixture: each is about what tooling *does*
with the card, not about what a state file may contain. A behavioural suite
driving a real implementation would cover them — see
[CONTRIBUTING.md](../CONTRIBUTING.md#rules-with-no-fixture).

| Rule | Stated in |
|---|---|
| `PKG/` is reserved; no content destination may target it | [Reserved namespace](#reserved-namespace) |
| `source.commit` is recorded whenever it is known | [source](#source) |
| Ownership is per file; directories are never owned | [Ownership](#ownership) |
| Every destination file is checked against other packages' lists before install | [Ownership](#ownership) |
| An untracked file is overwritten only under an explicit policy | [Ownership](#ownership) |
| A non-empty directory is never deleted; pruning never rises above the card root or into `PKG/` | [Ownership](#ownership) |
| A written or deleted `.lua` takes its untracked `.luac` sibling with it, subject to the overwrite policy | [Bytecode companions](#bytecode-companions) |
| A destination collides with an owned `.lua`/`.luac` counterpart | [Bytecode companions](#bytecode-companions) |
| The sibling policy is applied before the operation marker is written | [Bytecode companions](#bytecode-companions) |
| State over 512 KiB, or with more than 512 packages, is refused | [Resource limits](#resource-limits) |
| Blank lines in a file list are ignored; an invalid line is reported, not acted on | [PKG/files/…](#pkgfilespackage-idlist) |
| State writes are replace-in-place | [Durability](#durability) |
| An unparseable state file is reported, never silently discarded | [Durability](#durability) |
| An operation marker is written before any change and removed after the final state write | [Durability](#durability) |
| A marker present at startup is reported as an unfinished operation | [Durability](#durability) |
| Operations are serialised within a process | [Durability](#durability) |
| An orphaned `reason: dependency` package may be removed; an `explicit` one never is | [Orphan removal](#orphan-removal-and-dependency-reasons) |
| Removing a package never silently leaves another's `requires` unsatisfied | [Orphan removal](#orphan-removal-and-dependency-reasons) |
| State with a newer MAJOR is never rewritten; anything up to the tooling's own is read | [edgetx_format_version](#edgetx_format_version) |
| An `id` is lowercased before storing or comparing | [Package id as a key](#package-id-as-a-key) |
| Update re-resolves from `source.origin` when it is set, not from `repo` | [source](#source) |
| Installing a `dependency` package explicitly promotes it to `explicit` | [Orphan removal](#orphan-removal-and-dependency-reasons) |
| A reconciliation command is offered — SHOULD, not MUST | [Durability](#durability) |
| Old state layouts are migrated or ignored, never silently half-read | [Migration](#migration) |

## Migration

Two earlier layouts exist and neither is this one:

- Pre-release drafts of this specification described `EDGETX/PKG/state/` with a
  single global `files.yml`. No tooling shipped against those drafts, so no
  migration is defined. Anything written by a draft implementation should be
  deleted and the packages reinstalled.
- Shipped tooling stored `RADIO/packages.yml` with per-package lists under
  `RADIO/packages/`. Tooling that supported that layout SHOULD, when `PKG/` is
  absent and the old location is present, read the old state, write it to
  `PKG/`, and delete the old files. Fields the old layout did not record —
  notably `reason` and `requires` — are set to `explicit` and empty.

Tooling that never supported either layout MAY ignore both, in which case the
user reinstalls their packages. Deleting stale state is safe: it forgets
packages, it does not delete their files.
