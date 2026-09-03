# Implementation Guide

**This document is non-normative.** It is guidance for people writing package
manager tooling: worked algorithms for the parts where independent
implementations most easily drift apart. Conformance is defined by
[Manifest.md](./Manifest.md), [State.md](./State.md) and the two JSON Schemas —
[manifest](../schema/edgetx-manifest.v1.json) and
[state](../schema/edgetx-state.v1.json). Where this document appears to disagree
with those, they win.

Pseudocode here is illustrative. It is not a required decomposition, and the
error messages are suggestions.

## Contents

- [Helper signatures](#helper-signatures)
- [Reading a manifest](#reading-a-manifest)
- [Package references](#package-references)
  - [Resolving a version](#resolving-a-version)
- [Manifest resolution](#manifest-resolution)
  - [Source roots](#source-roots)
- [Variant selection](#variant-selection)
- [Compatibility checks](#compatibility-checks)
- [Cross-package dependencies](#cross-package-dependencies)
- [Staging and conflict detection](#staging-and-conflict-detection)
- [Install, update, remove](#install-update-remove)
- [Bytecode companions](#bytecode-companions)
- [Worked state examples](#worked-state-examples)

## Helper signatures

*Non-normative throughout: these are names used by the pseudocode below, not an API this specification requires.*

Declared once so a reader working top-down cannot pick up a stale contract:

```text
read_manifest(path)                      -> manifest | error
find_manifest(repo_dir, subpath)         -> path | error
resolve_content_path(m, dir, path)       -> abs_path | error
relative_to(path, root)                  -> rel_path
capabilities_match(filter, radio)        -> {matches: bool, unknown: [field]}
specificity(filter, radio)               -> int        # declared AND determinable
select_variant(base, dir, radio, firmware) -> variant_path | NO_MATCH | AMBIGUOUS(fields)
filter_match(v, radio, firmware)         -> {matches: bool, unknown: [field]}
filter_specificity(v, radio, firmware)   -> int   # capabilities AND firmware bounds
load_selected_variant(base, dir, path)   -> manifest | error
still_installable(m, radio, firmware)    -> bool   # m's own package constraints
check_firmware_version(min, max, running) -> ok | fail(code)
check_capabilities(filter, radio)        -> ok | fail(code)
resolve_requirements(manifest, installed) -> {id: resolution} | error
solve(chosen, pending, ancestry)         -> {id: resolution} | FAIL
candidates_for(id, range, installed)     -> [resolution], highest first
load_for_radio(id, resolution, radio)    -> (manifest, dir, variant_path) | error
installed_version(id)                    -> version | null
remember_cycle(chain)                    -> void
note_conflict(text)                      -> void
stage(manifest, dir, include_dev)        -> staging_dir
validate_path(path)                      -> ok | error
owning_package(dest)                     -> package_id | null   # ASCII-folded compare
check_conflicts(staging, id, sd, policy) -> clear_first | fail(code)
check_conflicts_batch(staged, sd, policy) -> clear_first | fail(code)
prepare(m, dir, reason, replacing, opts, ...) -> (batch, staged, clear_first)
commit(verb, id, batch, staged, clear_first, replacing) -> void
check_inventory_bounds(staged)           -> ok | fail(code)   # before the marker
find_case_insensitively(dir, relpath)    -> path | null
ancestors_of(dest)                       -> [dest's parent dirs], DEEPEST FIRST
fold(dest)                               -> ASCII-case-folded dest
check_untracked_luac_siblings(staging, id, sd, policy, op) -> ok | fail(code)
check_untracked_luac_siblings_for(paths, id, sd, policy, op) -> ok | fail(code)
was_owned_before(id, dest)               -> bool   # the card's list at start
kind_in(staging, dest)                   -> file | directory | null
delete_untracked_luac_for(lua_path)      -> void
kind_on_card(dest)                       -> file | directory | null
begin_marker(operation, package_id)      -> void
write_state(manifest, resolved, variant_path, reason, files) -> void
clear_marker()                           -> void
error(msg)                               -> aborts
fail(code, msg)                          -> aborts, with an outcome code
```

Two spellings of failure appear below. `error(msg)` is an ordinary abort, and
`fail(CODE, msg)` carries a machine-readable code for a caller to act on. The
code names used here are **illustrative** — the specification defines no error
vocabulary, and a catalog and its clients that want to share one should agree it
between themselves. Neither spelling is persisted: nothing about an operation's
outcome is written to `PKG/installed.yml`, which records what is installed and
not how it went.

Four contracts are worth stating explicitly, because getting them wrong is
silent:

- **`select_variant` returns a path string, not a variant entry.** The string is
  the exact `variants[].path` value, which is also what state records — so the
  same value flows from selection through `write_state` with no conversion.
  Passing an entry object here is the most common transcription error, and it
  surfaces two operations later as an update that can never find its own variant.
- **It has two distinct failure outcomes, and one null cannot carry both.**
  `NO_MATCH` means no variant entry matches this radio: refuse.
  `AMBIGUOUS` means more than one remains and a field that would have
  discriminated is undeterminable: ask the user. Collapsing them is why an
  earlier version of this guide silently installed a colour-LCD variant on a
  radio whose display type was unknown.
- **`resolve_content_path` raises**, because once `source_dir` is declared there
  is no sensible fallback.
- **`delete_untracked_luac_for` takes the `.lua` path** — the SD-card-relative
  destination, not a staging path — and derives the sibling itself. It does not
  take the policy: `check_untracked_luac_siblings` applies that in a pass of its
  own, before the marker exists, because refusing afterwards wedges the card.

## Reading a manifest

*Normative rules: [Manifest.md § Conformance](./Manifest.md#conformance-and-terminology), [§ edgetx_format_version](./Manifest.md#edgetx_format_version).*

Manifests come from repositories you do not control, so parse defensively —
but the threat model is a malformed or careless manifest, not a targeted
attack. Reasonable precautions:

- Use your YAML library's **safe** loader: standard scalar types only, no
  custom tags, no object construction.
- Accept a single YAML document; reject a stream.
- Cap the file size at the 256 KiB the specification requires — not the 1 MB an
  earlier version of this guide suggested — and cap anchor/alias expansion at ten
  times the document size.
- **Keep unknown fields.** Do not enable strict/deny-unknown-fields modes.
  `edgetx_format_version` forward compatibility depends on unknown keys being ignored
  rather than rejected — a MINOR spec bump may add fields your version has
  never heard of.

```text
read_manifest(path) -> manifest:
    document = parse_yaml(read(path))
    check_edgetx_format_version(document.edgetx_format_version)   # before anything else
    validate against JSON Schema
    run the runtime checks in Manifest.md's validation summary
```

```text
check_edgetx_format_version(value):
    if value is absent:
        treat as "1.0"; do not warn
    (major, minor) = parse(value)
    if major > MY_MAJOR:
        fail(FORMAT_TOO_NEW,
             "this package targets EdgeTX package format <value>; upgrade your
                 EdgeTX tooling to install it"
    if major == MY_MAJOR and minor > MY_MINOR:
        report once: "written for a newer spec minor; unknown fields ignored"
        continue
```

Apply the same parsing care to `PKG/installed.yml` and the file lists: they
live on a removable card and may have been edited or truncated.

## Package references

*Normative rules: [Manifest.md § Package id](./Manifest.md#package-id), [State.md § source](./State.md#source).*

A user-supplied reference looks like:

```text
[host/]owner/repo[/subpath][@version][::variant.yml]
/absolute/path/to/package[::variant.yml]
```

- Expand GitHub shorthand: a first segment without a `.` means `github.com`.
- `@version` selects a tag, a branch, or a commit SHA.
- `::variant.yml` (or a `--path` flag) selects a variant explicitly.
- A reference beginning `/`, `./`, `../` or `~/` installs from disk, recorded as
  `channel: local`. Decide by **shape**, never by whether a directory happens to
  exist: probing makes `owner/repo` install from GitHub in one shell and from a
  directory of that name in another — and lets anyone who can create a directory
  in the user's working directory hijack a package name.

```text
parse_ref(raw):
    (rest, variant) = split_last(raw, "::")
    (rest, version) = split_last(rest, "@")
    if rest starts with "/" or "./" or "../" or "~/":
        return Local { path: absolute(expand_tilde(rest)), variant }
    if rest looks like a Windows drive path (a single letter, then ":"):
        # Shorthand expansion would otherwise turn C:/repo into github.com/C:/repo.
        return Local { path: absolute(rest), variant }
    segments = split(rest, "/")
    if first(segments) has no ".":
        segments = ["github.com"] + segments        # shorthand
    if length(segments) < 3:
        error("not a package reference: " + raw +
              " (expected host/owner/repo, or ./path for a local directory)")
    # Every segment is user input that becomes a filesystem path under the
    # checkout, so it gets the same grammar a package id's segments get. Without
    # this, `owner/repo/../../x.yml` reads a manifest outside the checkout.
    for segment in segments:
        if segment is not a valid id segment: error("bad segment " + segment)
    return Remote {
        host: segments[0], owner: segments[1], repo: segments[2],
        subpath: join(segments[3:], "/"),
        version, variant,
    }
```

### Resolving a version

`@version` may be a tag, a branch, or a commit. When it is absent, prefer the
highest semver tag, falling back to the default branch.

```text
resolve_version(ref):
    if ref.version is empty:
        tags = semver_tags(repo) sorted descending
        if tags is not empty:  return { channel: tag,    ref: tags[0] }
        else:                  return { channel: branch, ref: default_branch }
    if ref.version matches a tag:     return { channel: tag,    ref: ref.version }
    if ref.version matches a branch:  return { channel: branch, ref: ref.version }
    return { channel: commit, ref: null, commit: ref.version }
```

Always record the resolved commit SHA alongside the channel and ref. `version`
from the manifest answers *is there an update?*; the commit answers *what is
installed?*

On update, preserve how the user pinned the package: a branch keeps tracking
that branch; a non-semver tag such as `stable` keeps tracking that tag; a
semver tag lets the resolver pick the newest semver tag; a commit is a pin and
does not move.

## Manifest resolution

*Normative rules: [Manifest.md § Source and destination](./Manifest.md#source-and-destination), [§ Subpackages](./Manifest.md#subpackages).*

```text
find_manifest(repo_dir, subpath):
    if subpath is empty:
        return repo_dir / "edgetx.yml"

    if subpath ends with ".yml" or ".yaml":       # explicit variant or manifest
        return repo_dir / subpath

    # Match the on-disk name case-insensitively rather than joining literally: an
    # id is stored lowercased, and a repository may legitimately hold `LogViewer/`,
    # which a literal join never finds on a case-sensitive checkout.
    # See Manifest.md § Package id.
    candidate = find_case_insensitively(repo_dir, subpath + "/edgetx.yml")
    if candidate is set: return candidate

    error("no manifest for subpackage " + subpath +
          " (looked for " + subpath + "/edgetx.yml)")
```

A malformed `<subpath>/edgetx.yml` surfaces its parse error. There is no second
place to look and no fallback: silently installing a different package is worse
than failing.

### Source roots

```text
source_roots(manifest, manifest_dir):
    if manifest.package.source_dir is absent:
        return [manifest_dir]
    return [manifest_dir / d for d in as_list(manifest.package.source_dir)]

resolve_content_path(manifest, manifest_dir, path):
    for root in source_roots(manifest, manifest_dir):
        if exists(root / path): return root / path
    error("content path not found under any source root: " + path)
```

There is no fallback to `manifest_dir` once `source_dir` is declared. A
mistyped `source_dir` must fail loudly rather than quietly install from the
repo root.

## Variant selection

*Normative rules: [Manifest.md § Variants](./Manifest.md#variants), [§ Selection](./Manifest.md#selection).*

A variant manifest is a complete manifest, so selection is just "pick a file,
then load it normally".

A variant entry's filter is **not** just `capabilities`: `min_edgetx_version` and
`max_edgetx_version` are part of it, they filter, and they count for specificity.
Scoring `v.capabilities` alone silently ignores them, and a package that ships
precompiled `.luac` per firmware generation is then given whichever build won on
display type — which is the one outcome those bounds exist to prevent.

```text
filter_match(v, radio, firmware):
    # Returns matches + the fields that could not be determined. Firmware bounds
    # are evaluated exactly like capability fields: an undeterminable one neither
    # matches nor blocks, and it is REPORTED as unknown so the caller can refuse
    # to guess.
    r = capabilities_match(v.capabilities, radio)
    matches = r.matches
    unknown = r.unknown
    for bound in (v.min_edgetx_version, v.max_edgetx_version) that are declared:
        if firmware is not determinable:
            unknown += [that bound's field name]        # neither matches nor blocks
        else if firmware does not satisfy bound:
            matches = false
    return {matches, unknown}


filter_specificity(v, radio, firmware):
    # Leaf capability fields, plus one for each firmware bound that is declared
    # AND determinable. Same total, same rule.
    n = specificity(v.capabilities, radio)
    if firmware is determinable:
        n += count of (v.min_edgetx_version, v.max_edgetx_version) that are declared
    return n


select_variant(base, base_dir, radio, firmware):
    scored  = [(v, filter_match(v, radio, firmware)) for v in base.package.variants]
    matches = [v for (v, m) in scored if m.matches]

    # An entry whose FILTER matches but whose variant manifest's own package-level
    # constraints exclude this radio is dropped, not fatal. The author wrote both,
    # so an entry saying "for firmware 2.12" over a build saying "I need 2.13" is
    # their contradiction — and the fallback entry beside it may install fine.
    # A filter says "not this build"; a package bound says "not this package".
    matches = [v for v in matches
               if still_installable(load_selected_variant(base, base_dir, v.path),
                                    radio, firmware)]

    if matches is empty:
        return NO_MATCH

    # BEFORE ranking, not after. Specificity is computed from what could be
    # determined, so an undeterminable field lowers a score rather than being
    # visibly absent — and the winner is then chosen partly by ignorance. Testing
    # after the ranking lets a single determinable field on one entry produce a
    # lone "winner" and disarm this check entirely.
    # Over the SURVIVING entries — the ones still in `matches` after the drop
    # above — not over everything that matched the filter. An entry removed
    # because its own manifest excludes this radio is not a candidate, so an
    # undeterminable field in ITS filter cannot make the remaining choice
    # ambiguous. Computing this from the pre-drop set refuses installs that have
    # exactly one legitimate answer.
    unknown = union of m.unknown for (v, m) in scored if v in matches
    if len(matches) > 1 and unknown is not empty:
        # A tie broken by declaration order is only legitimate when every field of
        # every matching filter was determinable. Otherwise the discriminating
        # field is merely unknown, and picking would install a black-and-white
        # build on a colour radio — or bytecode for the wrong firmware —
        # deterministically and silently.
        return AMBIGUOUS(unknown)      # the caller must name these to the user

    best = max(filter_specificity(v, radio, firmware) for v in matches)
    candidates = [v for v in matches if filter_specificity(v, radio, firmware) == best]

    return candidates[0].path   # the path STRING, first in declaration order
```

Radio capabilities are typically derived by mapping a board identifier from the
SD card through a hardware catalog, so any individual field may be unavailable —
offline, or because the catalog predates the radio. Treating unknown as a
mismatch makes packages un-installable for reasons the user cannot see; treating
it as a silent match hides a real risk. Reporting it does neither: proceed, and
warn, naming the field that could not be determined.

For variant selection an unknown field contributes nothing to a filter's
specificity — it neither matches nor blocks. And if more than one candidate
survives ranking while any of their filters names an undeterminable field, the
answer is `AMBIGUOUS`: ask. See
[Manifest.md](./Manifest.md#selection) for the normative rule, which is narrower
than "nothing is determinable".

`specificity(filter, radio)` counts the fields in the filter that are declared
**and determinable for this radio**, recursively. The `radio` argument is not
optional: a field the tooling cannot determine must not raise one filter above
another on the strength of information nobody has. See
[Manifest.md](./Manifest.md#selection) for the normative rule.

**The tie-break matters.** Return the *first* matching variant in declaration
order. Several languages' "max by key" helpers return the **last** maximum on
a tie — Rust's `Iterator::max_by_key` among them — which silently picks a
different variant than the spec requires. Either iterate explicitly or use a
first-wins maximum.

```text
load_selected_variant(base, base_dir, variant_path):
    path = base_dir / variant_path
    require path stays inside base_dir
    m = read_manifest(path)
    if m.package.id != base.package.id:
        error("variant " + variant_path + " declares id " + m.package.id +
              " but its base declares " + base.package.id)
    if m.package.variants is present:
        error("variant manifests cannot declare further variants")
    return m
```

Note what is *not* here: no field inheritance and no capability merging. The
variant manifest replaces the base wholesale, and `variants[].capabilities` is
used only to choose it.

```text
capabilities_match(filter, radio) -> {matches, unknown}:
    # An omitted filter field is a wildcard. A field the RADIO cannot report is
    # NOT a mismatch — it is unknown, and is reported rather than blocking.
    if filter is null or filter.display is null:
        return {matches: true, unknown: []}

    unknown = []
    for field in [type, resolution, touch]:
        if filter.display[field] is not set:     continue      # wildcard
        if radio.display[field]  is not known:   unknown.append(field); continue
        if filter.display[field] != radio.display[field]:
            return {matches: false, unknown: unknown}
    return {matches: true, unknown: unknown}
```

## Compatibility checks

*Normative rules: [Manifest.md § Firmware version constraints](./Manifest.md#firmware-version-constraints), [§ Radio capabilities](./Manifest.md#radio-capabilities).*

```text
check_firmware_version(min, max, running):
    r = (running.major, running.minor, running.patch)   # prerelease ignored

    if min is set and r < triple(min):
        fail(EDGETX_VERSION_TOO_LOW, "requires EdgeTX >= " + min)

    if max is set:
        if max.patch == "x":
            if (r.major, r.minor) > (max.major, max.minor):
                fail(EDGETX_VERSION_TOO_HIGH, "requires EdgeTX <= " + max)
        else if r > triple(max):
            fail(EDGETX_VERSION_TOO_HIGH, "requires EdgeTX <= " + max)
```

Dropping prerelease and build metadata before comparing is deliberate: a
firmware reporting `2.13.5-rc1` should satisfy the same bounds as `2.13.5`.
Under plain semver ordering it would not, and every nightly tester would hit
spurious `EDGETX_VERSION_TOO_LOW` failures.

If the radio's firmware version cannot be determined, warn and skip the check
rather than refusing the install, exactly as for an undeterminable capability.

Capability compatibility uses the same comparison as `capabilities_match`. On a
genuine mismatch, report `CAPABILITY_MISMATCH` with both the requirement and the
actual value — "requires a touchscreen, this radio has none" is actionable;
"capability mismatch" is not. On an unknown field, say which requirement could
not be checked, and continue.

## Cross-package dependencies

*Normative rules: [Manifest.md § requires](./Manifest.md#requires--other-packages), [§ Version ranges](./Manifest.md#version-ranges), [State.md § Orphan removal](./State.md#orphan-removal-and-dependency-reasons).*

`requires` names other packages. Resolution is a small graph walk; keep it
simple and fail clearly rather than trying to be clever.

```text
resolve_requirements(root_manifest, installed):
    # A backtracking depth-first search. Not a greedy walk: choosing the highest
    # version that satisfies a range can lead into a subtree that cannot be
    # satisfied, and the only way out is to try the requirer's next-lower version.
    pending = [(r.id, r.version or "*", root_manifest.package.id)
               for r in root_manifest.requires]
    # The ROOT IS the requested package, under its own id — not an anonymous
    # sentinel. Seed both the ancestry and `chosen` with it. Otherwise a
    # dependency can require the requested package back, the search happily
    # resolves it at some OTHER version, and install() then stages that version
    # over the one the user asked for while state claims the version they
    # requested. `requires` may not name its own manifest's id, but the loop here
    # goes through a third party, so that rule does not reach it.
    root_id = root_manifest.package.id
    result  = solve({root_id: resolution_of(root_manifest)}, pending,
                    ancestry = {root_id: []})
    if result is FAIL:
        # WHICH failure to report is decided over the whole search, not at the
        # node that happened to fail last. Deciding per node makes the answer
        # depend on the order the root listed its requirements: the same graph
        # reports a cycle in one ordering and an installed-version conflict in
        # the other, and only the second names anything the user can act on.
        #
        # The search PRUNES, though, so what got noted still depends on where it
        # went. A loop found early returns before its siblings are ever visited,
        # and a perfectly nameable conflict sitting in one of them is never seen.
        # So sweep for the nameable ones directly before reporting — it is a
        # linear pass over requirements already in hand, and it does not care
        # what order anything was tried in.
        for (id, range) in every requirement in the graph, roots included:
            if installed_version(id) is set and
               not satisfies(installed_version(id), range):
                note_conflict(id + " is installed at " + installed_version(id) +
                              ", which does not satisfy " + range)
            else if no published version of id satisfies range:
                note_conflict("no version of " + id + " satisfies " + range)
        # "Noted" includes everything recorded DURING the search as well as the
        # sweep — a conflict the search actually hit is the most specific thing
        # there is to say, and discarding it in favour of the sweep's generic
        # version loses which requirer wanted what.
        if any conflict was noted:
            error("cannot satisfy: " + join(every noted conflict, "; "))
        error("dependency cycle: " + join(the remembered cycle, " -> "))
    return result without root_id


candidates_for(id, range, installed):
    # A package already on the card is PINNED to the version that is there. The
    # resolver does not get to upgrade it: something else may depend on that
    # version, and Manifest.md says moving it is the user's decision. So an
    # installed id offers exactly one candidate — and when that one does not
    # satisfy the range, this returns nothing and the search fails, which is the
    # refusal the normative rule asks for.
    if installed_version(id) is not null:
        v = installed_version(id)
        if not satisfies(v, range):
            note_conflict(id + " is installed at " + v + ", which does not " +
                          "satisfy " + range + "; update or remove it first")
            return []
        return [resolution_of_installed(id)]
    out = [every resolution of id satisfying range, HIGHEST FIRST]
    if out is empty:
        # The single most ordinary failure there is — nothing published satisfies
        # the range — and without this it is the one the user is told nothing
        # about: `reasons` stays empty, the search fails, and the report has
        # nothing to name. Manifest.md requires the range and the requirer.
        note_conflict("no version of " + id + " satisfies " + range +
                      (" (available: " + join(all versions of id, ", ") + ")"
                       if id has any versions else " (no versions published)"))
    return out


solve(chosen, pending, ancestry) -> {id: version} | FAIL:
    if pending is empty:
        return chosen                      # every requirement satisfied

    (id, range, requirer) = pending[0]
    rest                  = pending[1:]

    # A cycle is checked on EVERY arrival, before anything short-circuits. Testing
    # it only when a version changes misses the case where the second arrival
    # lands on an id already chosen — which is the common shape.
    if id == requirer or id in ancestry[requirer]:
        # FAIL, not error: this candidate loops, so the search backs out and tries
        # the requirer's next version. Aborting here refuses graphs that resolve
        # trivially through a version with no loop — reachability is over the
        # versions actually CHOSEN. Remember the loop so the top level can report
        # it if nothing else works.
        remember_cycle(ancestry[requirer] + [requirer, id])
        return FAIL

    if id in chosen:
        # Already decided. It must satisfy this range too; if it does not, an
        # earlier choice was wrong and the caller will try another.
        if satisfies(chosen[id].version, range):
            return solve(chosen, rest, ancestry)
        note_conflict(id + " chosen at " + chosen[id].version +
                      " does not satisfy " + range + " wanted by " + requirer)
        return FAIL

    for candidate in candidates_for(id, range, installed):
        sub = [(r.id, r.version or "*", id)
               for r in read_manifest_at(id, candidate).requires]
        # Depth first, declaration order: `sub` goes in front of `rest`. That
        # ordering is what makes the result deterministic for a given manifest.
        deeper = solve(chosen + {id: candidate}, sub + rest,
                       ancestry + {id: ancestry[requirer] + [requirer]})
        if deeper is not FAIL:
            return deeper                  # this candidate works; keep it

    return FAIL                            # no version of `id` works here
```

Fuzzed over 4,000 random graphs in every ordering of the root's requirements:
deciding the failure kind per node reported a different *kind* for the same graph
in 659 of them depending on that ordering; deciding it globally and sweeping
first, in 13. The residue is conflicts that exist only between two versions the
search actually chose, which no sweep can see without redoing the search — those
stay order-dependent, and that is the honest limit of this approach rather than a
defect to fix.

This is the third algorithm in this section, and the first two were wrong in
ways worth recording, because both look reasonable.

The first walked greedily and re-walked when a range narrowed an already-chosen
id. The second added provenance so that a narrowing could retract what the
abandoned version had contributed. Both share one fatal assumption: that a wrong
choice is always revealed by a *later range on the same id*. It is not. Given a
root requiring `b >=1.5.0`, where `b@2.0.0` needs a `c` that does not exist and
`b@1.5.0` needs nothing, there is one requirer and one range — no narrowing ever
happens — and both algorithms refuse a graph that resolves trivially by taking
`b@1.5.0`. Backtracking over the *requirer's* version is the only way out, and
neither could do it.

Retraction also cannot be made correct piecemeal: dropping what an abandoned
version contributed can orphan a package that a *surviving* range still requires,
and nothing re-resolves it, so the tool installs a package without its dependency.

The search above was checked against a brute-force reference over three thousand
random graphs, in every ordering of the root's requirements: no spurious refusal
of a satisfiable graph, and no result that leaves a requirement unsatisfied.

Three mistakes are easy to make here and each produces wrong answers on ordinary
inputs:

- **Tracking "currently being visited" and "already visited" with one set.** A
  cycle is a repeat along the *current path*; a diamond — A requires B and C,
  both of which require D — is a repeat across *different* paths and is
  completely normal. Conflating them reports a spurious cycle for the most
  common dependency shape there is.
- **Not re-walking when a chosen version changes.** Adding a second range can
  narrow the choice for an id already resolved, and the newly chosen version may
  have different requirements of its own.
- **Not backtracking over the requirer.** The highest version satisfying a range
  may lead into a subtree that cannot be satisfied. Refusing there is wrong when a
  lower version of the same requirer works.
- **Checking for a cycle only when a version changes.** The second arrival at an
  already-chosen id short-circuits, so the check never runs and a genuine cycle is
  reported as a clean resolution.

`read_manifest_at(id, version)` fetches that package at that version and reads
its manifest; it is `read_manifest` plus a fetch.

`candidates_for(id, range, installed)` enumerates candidates highest first — or
the single pinned one when the package is already on the card; the search tries
them in that order and backtracks, which is why there is no separate "pick the
best version" step. Where those versions come from is the next paragraph.

A **resolution** is what the search carries, and it is not just a version
number: state records `ref` and `commit` as well, so a resolution is
`{version, ref, commit}` and the re-tag rule — highest-sorting tag wins on a
version tie — is applied when the candidate list is built, not afterwards.
Returning bare version numbers from the resolver is the mistake to avoid; you
discover it when `source.ref` has nothing to put in it and the fetch has been
thrown away. See [Manifest.md § `requires`](./Manifest.md#requires--other-packages).

`load_for_radio(id, resolution, radio)` fetches a dependency and returns a
manifest ready to install — which means it runs variant selection, exactly as the
requested package's own path does, and refuses `NO_MATCH` or `AMBIGUOUS` naming
the *dependency* so the message says which package could not be chosen for. It is
easy to leave this out, and the failure is quiet rather than loud: a base manifest
that declares `variants` normally declares no content sections at all, so an
unselected dependency installs zero files and records an empty inventory. Nothing
errors. The requester simply does not work.

Enumerating "available versions" means reading `package.version` from the
dependency's manifest at each candidate tag — **not** parsing the tag name. The
two disagree precisely when an author tags without bumping, so inferring from
the tag would resolve to a version that does not exist. Warn when a semver tag
and its manifest's `version` disagree; it is almost always the author's
mistake. A candidate whose manifest declares no `version` can satisfy only `*`.

When no version satisfies every range, report each range with the package that
asked for it. "A wants ^1.0, B wants ^2.0" tells the user what to do;
"unsatisfiable constraints" does not.

Practical notes:

- Reject a range you cannot parse. Guessing at `2.x` is worse than an error.
- A dependency already installed as `reason: explicit` stays explicit. Nothing
  in the install path rewrites the state of a package it did not touch, and
  `installed(id)` keeps such a package out of the batch entirely — which is the
  mechanism, not merely the intent.
- Install dependencies before the package that requires them, so a failure
  part-way leaves fewer half-satisfied packages.
- On remove, an orphan is a `reason: dependency` package that no remaining
  `reason: explicit` package transitively requires. Compute the reachable set
  from the explicit packages and offer the difference for removal. Never
  auto-remove an explicit package.
- Tooling **predating** `requires` ignores it and installs the package alone.
  That is intended: a degraded install beats a rejection, and it is why the field
  is designed to be ignorable. Tooling that knows the field but cannot fetch is a
  different case, and the normative rule there is to refuse — see
  [Manifest.md](./Manifest.md#requires--other-packages).

## Staging and conflict detection

*Normative rules: [Manifest.md § Path rules](./Manifest.md#path-rules), [State.md § Ownership](./State.md#ownership).*

Stage into a temporary directory first. It gives you the complete file
inventory before touching the card, which is what makes per-file conflict
detection and an accurate file list possible.

```text
stage(manifest, manifest_dir, include_dev):
    staging = create_temp_dir()
    for item in all_content_items(manifest):
        if item.dev and not include_dev: continue
        src  = resolve_content_path(manifest, manifest_dir, item.path)
        dest = item.dest if set else item.path
        copy_tree(src, staging / dest,
                  exclude    = item.exclude,
                  skip_luac  = not manifest.package.binary,
                  skip_vcs   = true,        # .git, .svn, .hg, .gitignore, ...
                  skip_self  = manifest_file and its variants[].path siblings)
    return staging
```

Copy only regular files and directories, and never write a link — a FAT32
destination has none, so there is nothing to preserve.

`skip_vcs` and `skip_self` are not conveniences; both are normative — see
[Manifest.md § Content item fields](./Manifest.md#content-item-fields). They
matter because `path: .` at a repository root is the documented way to package a
theme, and without them that copies the entire `.git` directory onto the card.

For reading, canonicalise **every** source path and refuse any that resolves
outside the repository checkout root. Testing whether a path *is* a link is not
enough: with `src` itself a link, `src/id_rsa` reached through it is not a link,
and a repository shipping one committed symlink exfiltrates whatever it points
at. See [Manifest.md](./Manifest.md#path-rules) — the anchor is the checkout
root, deliberately, not any directory the manifest gets to choose.

```text
check_conflicts_batch(staged, sd_root, overwrite_policy):
    # `staged` is {package_id: staging_dir} for the whole batch. Members are
    # checked against each other as well as against installed packages: none of
    # them is installed yet, so owning_package() sees no collision between two
    # batch members, and both file lists would then claim the same file.
    #
    # Equality is not enough. One member staging the FILE `SCRIPTS/T` while
    # another stages `SCRIPTS/T/inner.lua` is a collision even though no two
    # destinations are equal — the copy fails partway through with the marker
    # already written, which is precisely the outcome the marker ordering exists
    # to prevent. So record the kind, and check ancestors both ways.
    seen        = {}    # folded dest -> (package_id, kind)
    clear_first = []    # untracked ancestor files the policy approved
    for (package_id, staging) in staged:
        for entry in walk(staging, files and directories):
            dest = fold(relative_to(entry, staging))
            kind = FILE or DIR
            if dest in seen:
                (other, other_kind) = seen[dest]
                # A shared DIRECTORY is fine and completely ordinary — a tool and
                # the library it requires both stage under SCRIPTS/. Only a file
                # claimed twice, or a path one member wants as a file and another
                # as a directory, is a conflict. Comparing package ids for every
                # entry refuses every install that has a dependency.
                if other_kind != kind or (kind == FILE and other != package_id):
                    fail(FILE_CONFLICT, dest + " is staged by both " + other +
                          " and " + package_id)
            seen[dest] = (package_id, kind)
        clear_first += check_conflicts(staging, package_id, sd_root,
                                       overwrite_policy)

    # A file staged where another member stages a directory, or the reverse. The
    # loop above catches it only when both members happen to name that exact
    # path; this catches it whenever one is an ancestor of the other.
    for (dest, (package_id, kind)) in seen:
        if kind is FILE:
            for descendant in seen where descendant is under dest:
                fail(FILE_CONFLICT, dest + " is staged as a file by " +
                      package_id + " and as a directory by " +
                      seen[descendant][0])

    # The .lua/.luac pair, between batch members. The per-member check finds an
    # owned counterpart through owning_package(), which reads FILE LISTS — and no
    # batch member has one yet. So the sibling rule that stops one package
    # shadowing another's script does not apply within a batch unless it is
    # applied here, and a package can pull its victim in as a `requires` entry to
    # force exactly that batch.
    for (dest, (package_id, kind)) in seen where kind is FILE:
        counterpart = dest + "c" if dest ends with ".lua" (any case) else
                      dest without trailing "c" if dest ends with ".luac" (any case)
                      else null
        if counterpart is not null and counterpart in seen:
            (other, other_kind) = seen[counterpart]
            if other != package_id and other_kind is FILE:
                fail(FILE_CONFLICT, dest + " from " + package_id +
                      " and " + counterpart + " from " + other +
                      ": the radio would run one in place of the other")

    return clear_first


check_conflicts(staging, package_id, sd_root, overwrite_policy):
    clear_first = []                         # returned to the caller
    # EVERY destination comparison below — ownership, the sibling test, the
    # within-package collision test — folds ASCII case first. FAT32 does not
    # distinguish SCRIPTS/Foo from SCRIPTS/foo, so comparing them literally lets
    # one package take over another's files by changing a letter's case. See
    # Manifest.md#path-rules; the fold is ASCII only, deliberately.
    for file in walk(staging):
        dest = relative_to(file, staging)
        validate_path(dest)                  # Manifest.md path rules

        owner = owning_package(dest)         # search other packages' file lists
        if owner is set and owner != package_id:
            fail(FILE_CONFLICT, dest + " is already owned by " + owner +
                  "; remove that package first")

        # The .lua/.luac pair is the one case where two distinct names are one
        # executable, because the radio prefers the bytecode. Match the extension
        # case-insensitively: a literal swap lets `Popular.LUA` past, and the
        # shadow it would cast is just as real.
        sibling = dest with its .lua/.luac extension matched case-insensitively
                  and swapped, keeping the rest of the name as written
        sibling_owner = owning_package(sibling)
        if sibling_owner is set and sibling_owner != package_id:
            fail(FILE_CONFLICT, dest + " would shadow " + sibling +
                  ", owned by " + sibling_owner)

        # Both directions. walk() yields files, so a staged `A/b.lua` never asks
        # about `A` — and if another package owns the FILE `A`, the copy destroys
        # it. Check every ancestor too.
        for ancestor in ancestors_of(dest):     # deepest first; see below
            if kind_on_card(ancestor) == file:
                # Owned or not. An owned file here means destroying another
                # package's content; an untracked one is the user's, and either way
                # the copy dies mid-operation with the marker already written.
                if owning_package(ancestor) == package_id:
                    # Our own file from a previous version, at a path this
                    # version wants to be a directory. commit() deletes the old
                    # file list before copying, so it is already going. Refusing
                    # here blocks a package from reorganising its own content —
                    # and it must NOT fall through to the overwrite policy below,
                    # which would ask the user about a file they already own.
                    continue
                if owning_package(ancestor) is set:
                    fail(FILE_CONFLICT, dest + " needs " + ancestor +
                          " to be a directory, but it is a file owned by " +
                          owning_package(ancestor))
                # Untracked: the user's file. RECORD it for the write phase — do
                # NOT delete it here. This routine runs before the marker exists
                # and before several checks that can still refuse, so deleting
                # here destroys a file the manifest never named and leaves no
                # record that it happened. Nothing may touch the card until every
                # refusable check has passed and the marker is written.
                apply overwrite_policy to ancestor
                clear_first += [ancestor]     # commit() deletes it, later

        # A file over a directory, or a directory over a file, is refused rather
        # than guessed — here, with the other collisions, before anything is
        # written. Left to the copy it surfaces as an OS error mid-operation.
        if kind_on_card(dest) is set and kind_on_card(dest) != kind_in(staging, dest):
            fail(FILE_CONFLICT, dest + " is a " + kind_on_card(dest) +
                  " on the card and a " + kind_in(staging, dest) + " in this package")

        # The derived-bytecode exception applies to the DESTINATION, not only to
        # a sibling — State.md § Bytecode companions. Without this test here, a
        # package migrating from `X.lua` to a shipped `X.luac` is refused under
        # the required `fail` default on every card where the script has ever
        # run, because the radio's own compiled output is sitting at exactly that
        # destination and nobody owns it. check_conflicts runs before the sibling
        # pass, so the sibling pass cannot rescue it.
        if owner is null and dest ends with ".luac" (any case)
           and was_owned_before(package_id, dest without trailing "c"):
            continue                          # our script's own compiled output

        if owner is null and find_case_insensitively(sd_root, dest) is not null:
            switch overwrite_policy:
                case fail:      fail(FILE_CONFLICT, "would overwrite untracked file: " + dest)
                case overwrite: warn("overwriting untracked file: " + dest)
                case prompt:    if not ask(dest): fail(FILE_CONFLICT, "declined")

    return clear_first
```

Two points worth getting right:

- **Check every file, not every content item.** Per-item checking both misses
  collisions (two items whose trees overlap on disk) and invents them (two
  packages sharing a directory without sharing a file).
- **Make the overwrite decision a parameter**, not a prompt buried in the
  algorithm. The same routine runs from an interactive CLI, a browser UI and
  CI. `fail` is the *required* default when no user is present — see
[State.md](./State.md#ownership).

## Install, update, remove

*Normative rules: [State.md § installed.yml](./State.md#installedyml), [§ Durability](./State.md#durability), [Manifest.md § Manual selection and updates](./Manifest.md#manual-selection-and-updates).*

All three follow one shape: work out what should be on the card, stage it,
check it, write the marker, change the card, write state, clear the marker.

```text
# The three installing operations differ in only three ways: which `reason` the
# requester is recorded with, which verb the marker names, and whether something
# already on the card is being replaced. Everything else is shared, and is
# written once here — the defect this file keeps producing is a rule fixed in one
# flow and left wrong in the other two.

prepare(manifest, manifest_dir, base_pkg, reason, replacing, options,
        this_operation, this_variant, this_resolution):
    # BOTH the base's package-level constraints and the selected variant's, with
    # the stricter winning. The caller rebinds `manifest` to the variant, so the
    # base's are gone unless kept — and a base declaring `min_edgetx_version:
    # "2.12.0"` over a variant that omits it would otherwise install on 2.09.
    check_firmware_version(stricter of base_pkg and manifest.package)
    check_capabilities(union of base_pkg and manifest.package)

    # The WHOLE batch is staged and checked before anything reaches the card: the
    # requested package plus every dependency resolution chose. Installing a
    # dependency and then refusing on the requester leaves a `reason: dependency`
    # package nothing requires — see State.md § Durability.
    #
    # `installed` pins what is already on the card, so resolution never proposes
    # moving it. Anything already installed is therefore out of the batch —
    # including at a version this resolution "would have" chosen, which is why
    # the test is `installed(id)` and not a version comparison. Testing the
    # version reinstalls a package that is already correct and rewrites its
    # state, demoting a `reason: explicit` package the user asked for.
    # Each member carries its OWN variant path and its OWN resolution. Both are
    # per-package and neither can be reconstructed later: a variant manifest holds
    # no record of the `variants[].path` that selected it, and a dependency's
    # ref and commit are not the requester's. Passing one `resolved` for the whole
    # batch writes every dependency's `source` as the requester's — which fails
    # State.md's own rule that `repo` is a prefix of `id`, so the tooling refuses
    # to load the state it just wrote.
    batch  = [(manifest, manifest_dir, reason, this_variant, this_resolution)]
             + [(m, dir, reason: dependency, v, r)
                for (id, r) in resolve_requirements(manifest, installed)
                for (m, dir, v) in [load_for_radio(id, r, radio)]
                if not installed(id)]
    staged = {id: stage(m, dir, options.dev) for (m, dir, _) in batch}
    if options.compile: compile_lua(each staging in staged)

    # Every check that can refuse runs HERE, before any marker exists. A refusal
    # after the marker is written leaves the card reporting an unfinished
    # operation for good.
    clear_first = check_conflicts_batch(staged, sd_root, options.on_untracked)
    check_inventory_bounds(staged)
    for (pid, staging) in staged:
        check_untracked_luac_siblings(staging, pid, sd_root,
                                      options.on_untracked, this_operation)
    if replacing is not null:
        check_untracked_luac_siblings_for(replacing.file_list, replacing.id,
                                          sd_root, options.on_untracked,
                                          this_operation)
    return (batch, staged, clear_first)


commit(marker_verb, marker_id, batch, staged, clear_first, replacing):
    begin_marker(marker_verb, marker_id)

    # Now, and only now: the untracked ancestor files the policy approved. The
    # copy cannot create a directory where a file stands, and the check phase
    # deliberately left them alone until the marker made this recoverable.
    for path in clear_first: delete(sd_root / path)

    if replacing is not null:
        delete_files(replacing.file_list)                 # then prune empty dirs
        for path in replacing.file_list where path ends with ".lua" (any case):
            delete_untracked_luac_for(path)
    for each file in staged where file ends with ".lua" (any case):
        delete_untracked_luac_for(relative_to(file, its staging dir))
    copy_to_card(each staging in staged, sd_root)

    # EVERY batch member gets its own entry and its own file list. A dependency
    # is a full package, not part of its requirer — writing only the requester's
    # state leaves the dependency's files owned by nobody, invisible to orphan
    # cleanup, and blocking the next package that touches those paths.
    for (m, dir, reason, variant, resolved) in batch:
        write_state(m, resolved, variant, reason,
                    files: inventory(staged[m.package.id]))
    clear_marker()
```

```text
install(ref, options):
    (manifest, manifest_dir, resolved) = fetch_and_load(ref)

    if already_installed(manifest.package.id):
        # Reinstall. Unlike update, this honours an explicitly requested variant
        # and does not short-circuit on an unchanged version — switching variant
        # is exactly what install-over-an-install is for.
        return reinstall(manifest, manifest_dir, resolved, options)

    base_pkg = manifest.package   # keep it: `manifest` is rebound below
    variant  = null               # bound on EVERY path: it is what state records,
                                  # and an update that finds it null re-selects
    if manifest.has_variants():
        variant = options.variant or select_variant(manifest, manifest_dir,
                                                    radio, firmware)
        if variant is NO_MATCH:
            error("no variant matches this radio; its capabilities are: " + radio +
                  ", running firmware " + (firmware or "unknown"))
        if variant is AMBIGUOUS:
            error("cannot choose a variant: " + variant.fields +
                  " could not be determined for this radio; pass one explicitly")
        manifest = load_selected_variant(manifest, manifest_dir, variant)

    (batch, staged, clear_first) =
        prepare(manifest, manifest_dir, base_pkg, reason: explicit, null, options,
                "install", variant, resolved)
    commit("install", manifest.package.id, batch, staged, clear_first, null)
```

```text
update(query, options):
    old = find_installed(query)
    # origin, when set, is the fork the user chose — go back to it. A local
    # install re-reads from the directory it came from; there is no repository to
    # re-resolve, and going to `repo` fetches a remote package that may not
    # exist, or worse, one that does.
    if old.source.channel == "local":
        if old.source.path does not exist:
            error("the source directory for " + old.id + " is gone: " +
                  old.source.path)
        (manifest, manifest_dir, resolved) = load_local(old.source.path)
    else:
        (manifest, manifest_dir, resolved) = re_resolve(old.source.origin
                                                       or old.source.repo)

    if manifest.package.id != old.id:
        error("identity mismatch: refusing to update " + old.id +
              " from a manifest for " + manifest.package.id)

    # Two nulls compare equal, so a package declaring no version would be
    # permanently up to date. Fall back to the resolved commit — and skip that
    # for a local install, where `commit` is ALWAYS null and the same two-nulls
    # trap waits one channel down. A local source is re-read every time.
    if old.version is not null and manifest.package.version == old.version
       and not options.force:
        return up_to_date
    if old.version is null and old.source.channel != "local"
       and resolved.commit == old.source.commit and not options.force:
        return up_to_date

    base_pkg = manifest.package
    variant  = null
    if old.variant is set:
        if not variant_exists(manifest, old.variant):
            error("variant " + old.variant + " is gone in the new version; " +
                  "reinstall to switch variants")
        kept = load_selected_variant(manifest, manifest_dir, old.variant)
        # An update keeps the installed variant only while it is still
        # INSTALLABLE. Firmware changes under an installed package, and a
        # bytecode package has one build per firmware generation — keeping the
        # 2.11 build across a flash to 2.12 leaves the radio unable to run it.
        # "Reinstall to switch variants" is not advice anyone can act on when
        # nothing told them something was wrong.
        if still_installable(kept, radio, firmware):
            manifest = kept
            variant  = old.variant
        else:
            variant = select_variant(manifest, manifest_dir, radio, firmware)
            if variant is NO_MATCH:
                error("the installed variant no longer runs on this radio and " +
                      "no other matches; its capabilities are: " + radio +
                      ", running firmware " + (firmware or "unknown"))
            if variant is AMBIGUOUS:
                error("cannot choose a variant: " + variant.fields +
                      " could not be determined; reinstall with an explicit one")
            report("switching variant: " + old.variant + " -> " + variant)
            manifest = load_selected_variant(manifest, manifest_dir, variant)
    else if manifest.has_variants():
        # The package gained variants between releases. Both outcomes are live:
        # no entry may match, or a field needed to choose may have become
        # undeterminable — a supported state, not an error to ignore.
        variant = select_variant(manifest, manifest_dir, radio, firmware)
        if variant is NO_MATCH:
            error("the new version declares variants and none matches this radio; "
                  "reinstall with an explicit variant")
        if variant is AMBIGUOUS:
            error("cannot choose a variant: " + variant.fields +
                  " could not be determined; reinstall with an explicit variant")
        manifest = load_selected_variant(manifest, manifest_dir, variant)

    # `old.reason`: an update never promotes. Staging everything before deleting
    # anything is what leaves a failed update with the card in its old state.
    (batch, staged, clear_first) =
        prepare(manifest, manifest_dir, base_pkg, old.reason, old, options,
                "update", variant, resolved)
    commit("update", old.id, batch, staged, clear_first, old)
```

```text
reinstall(manifest, manifest_dir, resolved, options):
    old = find_installed(manifest.package.id)

    base_pkg = manifest.package
    variant  = null
    if manifest.has_variants():
        # Explicit request wins; otherwise re-select, falling back to whatever is
        # installed. That fallback is legitimate only for NO_MATCH: on AMBIGUOUS
        # the user must choose, and silently reinstalling the previous variant is
        # what the normative rule forbids.
        variant = options.variant or select_variant(manifest, manifest_dir,
                                                    radio, firmware)
        if variant is AMBIGUOUS:
            error("cannot choose a variant: " + variant.fields +
                  " could not be determined; pass one explicitly")
        if variant is NO_MATCH:
            variant = old.variant
        if variant is null:
            error("no variant matches this radio and none is installed; "
                  "pass one explicitly")
        manifest = load_selected_variant(manifest, manifest_dir, variant)

    # `explicit`: an explicit install promotes. A dependency pulled in here is
    # still recorded as `dependency`, not promoted along with the requester.
    (batch, staged, clear_first) =
        prepare(manifest, manifest_dir, base_pkg, reason: explicit, old, options,
                "install", variant, resolved)
    commit("install", old.id, batch, staged, clear_first, old)
```

Two divisions of labour are worth being explicit about, because getting them
wrong makes a documented workflow impossible:

- **`update` never changes the variant; `install` does.** Update re-uses
  `old.variant` and returns *up to date* when the version has not moved. So
  routing an install-over-an-install into `update` would silently discard a
  variant the user explicitly asked for — and the advice "reinstall to switch
  variants" would be circular. Reinstall is its own path.
- **`update` re-resolves requirements.** A new version can add a `requires`
  entry, and an update that skipped resolution would leave the package installed
  with a dependency missing.

Stage and verify everything *before* deleting the old files. That single ordering
choice is what makes a failed update leave the card in the old state rather than
a broken one, and it costs nothing.

```text
remove(query, options):
    pkg   = find_installed(query)
    files = read_file_list(pkg.id)   # absent file = empty inventory, not an error

    # Who still needs this? State.md forbids leaving another package's `requires`
    # unsatisfied WITHOUT SAYING SO, so silence is the one thing not allowed. The
    # snapshot in each entry's `requires` is what makes this answerable without
    # refetching anything.
    dependents = [p for p in installed_packages()
                  if p.id != pkg.id and any(r.id == pkg.id for r in p.requires)]
    if dependents is not empty:
        if not options.force:
            error(pkg.id + " is required by " + join(ids of dependents, ", ") +
                  "; remove those first, or pass --force")
        for p in dependents:
            warn(p.id + " requires " + pkg.id + ", which is being removed")

    # Validate the whole file list and apply the sibling policy first: both can
    # refuse, and refusing after the marker exists wedges the card. remove is
    # idempotent only if it never stops half-way.
    for path in files:
        validate_path(path)
    check_untracked_luac_siblings_for(files, pkg.id, sd_root, options.on_untracked, remove)

    begin_marker("remove", pkg.id)
    for path in files:
        validate_path(path)                 # never trust state blindly
        delete(sd_root / path)
        if path ends with ".lua" (any case):
            delete_untracked_luac_for(path)
    prune_empty_dirs(directories_of(files))
    delete_file_list(pkg.id)
    remove_state_entry(pkg.id)
    clear_marker()

    # Each accepted orphan is a removal in its own right, so it gets its own
    # marker naming itself. State.md's "one marker for the request" governs the
    # batch the user asked for; a sweep the user then accepts is a new request.
    orphans = dependency_packages_no_longer_required()
    for orphan in orphans that the user accepts:
        remove(orphan.id, options)
```

Deleting a file that is already gone is not an error — a user may have removed
it by hand. Prune directories bottom-up, stop at the first non-empty one, and
never prune above the SD card root or into `PKG/`.

Update and remove are idempotent, which is what makes "just run it again" a
valid answer to an interrupted operation.

## Bytecode companions

*Normative rules: [State.md § Bytecode companions](./State.md#bytecode-companions).*

EdgeTX runs `.luac` bytecode in preference to a `.lua` source of the same name,
which is why two rules govern the pair. Both are normative and neither is
restated here — read them at
[State.md § Bytecode companions](./State.md#bytecode-companions):

- an **untracked** sibling is deleted when its `.lua` is written or deleted,
  subject to the overwrite policy, across all four operations, with a
  **derived-bytecode exception** for install, update and reinstall; and
- an **owned** sibling collides, so a destination `X.luac` conflicts with an
  owned `X.lua` and the reverse.

What this guide adds is where those checks go, which is the part that is easy to
get wrong: the collision test belongs with the other conflict checks
([Staging and conflict detection](#staging-and-conflict-detection)), and the
policy pass for untracked siblings must run **before** the operation marker
exists, because the sibling is never in staging and a refusal after the marker
wedges the card.

The exception is the part that is easy to get *wrong* rather than merely miss, so
it is worth writing out. Read the normative rule for what it means; this is only
where the inputs come from:

```text
was_owned_before(package_id, dest):
    # The file list ON THE CARD, as it was when the operation started — NOT the
    # list being staged. The staged list already claims every destination, so
    # testing against it makes the exception fire on a first install, and the
    # package could then delete any untracked .luac on the card by declaring a
    # .lua at that path. Read this once, before staging, and keep it.
    return dest matches, ASCII-case-folded, some entry of
           file_list_on_card_at_start(package_id)


check_untracked_luac_siblings(staging, package_id, sd, policy, operation):
    for file in walk(staging):
        dest = relative_to(file, staging)
        # Every suffix test here is case-insensitive: main.LUAC is main.luac on
        # the card and the radio prefers it either way.
        if dest ends with ".lua" (any case):
            targets = [dest + "c"]            # the bytecode this script shadows
        else if dest ends with ".luac" (any case):
            # BOTH directions. The destination itself may be sitting on the card
            # as the radio's own output, AND the .lua beside it may be a script
            # the user wrote that this bytecode would silently shadow. Checking
            # only the first lets a source-free package replace what the radio
            # executes with nothing reported.
            targets = [dest, dest without trailing "c"]
        else:
            continue
        for sibling in targets:
            existing = find_case_insensitively(sd, sibling)
            if existing is null:            continue
            if owning_package(existing) is not null: continue  # owned: a
                                        # collision, not this rule's job
            if operation != remove and
               was_owned_before(package_id, dest_lua_of(dest)):
                continue                # derived bytecode; the exception applies
            apply(policy, existing)     # fail, or overwrite with a report
```

`dest_lua_of(dest)` is `dest` itself when it ends `.lua`, and `dest` with the
trailing `c` dropped when it ends `.luac` — in both cases the source path whose
prior ownership is being tested.

`check_untracked_luac_siblings_for(paths, ...)` is the same loop over a file list
rather than a staging directory, for the files an update or remove is about to
delete. Two differences from the staging form, both from the normative rule:

- It passes `operation`, and on remove the derived-bytecode exception never
  applies.
- The `.luac` → untracked-`.lua` direction does **not** apply here. That rule is
  about *writing* a `.luac` over a script it would shadow, and this pass covers
  files being **deleted** — nothing is going to shadow anything. Running it
  anyway makes removing a bytecode-only package refuse under the required `fail`
  default whenever the user happens to have written their own `.lua` beside it,
  a file remove was never going to touch.

Package sources ship alongside bytecode because the radio discovers some script
types — widgets in particular — through the `.lua`. A package that ships bytecode
*only* is a supported shape and needs no `.lua` at all; see
[Manifest.md § Content item fields](./Manifest.md#content-item-fields).

## Worked state examples

*Normative rules: [State.md § Required and optional fields](./State.md#required-and-optional-fields), [§ source](./State.md#source), [§ Validation summary](./State.md#validation-summary).*

Fresh install, no variants, no dependencies:

```yaml
# PKG/installed.yml
edgetx_format_version: "1.0"
packages:
  - id: github.com/acme/simple-tool
    name: Simple Tool
    version: "1.0.0"
    variant: null
    reason: explicit
    requires: []
    installed_at: "2026-08-23T12:00:00Z"
    source:
      repo: github.com/acme/simple-tool
      channel: tag
      ref: "v1.0.0"
      commit: "3f9a1c0e4b7d2a5f8c1e6b0d9a4f7c2e5b8d1a03"
      origin: null
      path: null
      manifest_path: "edgetx.yml"
```

```text
# PKG/files/github.com%acme%simple-tool.list
SCRIPTS/TOOLS/simple-tool.lua
```

A package installed to satisfy another package's `requires`:

```yaml
packages:
  - id: github.com/someone/elrs-libs
    version: "2.1.0"
    variant: null
    reason: dependency          # nothing asked for it directly
    requires: []
    installed_at: "2026-08-23T12:41:00Z"
    source:
      repo: github.com/someone/elrs-libs
      channel: tag
      ref: "v2.1.0"
      commit: "a4d81f0c9e2b7a6f3d5c8e1b0a9f4c7d2e6b8a15"
      origin: null
      path: null
      manifest_path: "edgetx.yml"
```

A package fetched from a fork declares one id but came from elsewhere; record
that in `source.origin` and tell the user, because it means updates track the
fork rather than the upstream project:

```yaml
packages:
  - id: github.com/acme/new-widget
    version: "2.0.0"
    reason: explicit
    requires: []
    source:
      repo: github.com/acme/new-widget          # from package.id
      channel: branch
      ref: "experimental"
      commit: "b1e4a7c0d3f6295e8b1c4a7d0f3e6b9c2a5d8f1e"
      origin: github.com/contributor/new-widget # actually fetched from here
      path: null
      manifest_path: "edgetx.yml"
```
