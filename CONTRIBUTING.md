# Contributing

This repository holds a specification. Changes should be precise, documented
in the same change set, and consistent with the existing package model.

## What is normative

Only these define conformance:

- [`docs/Manifest.md`](./docs/Manifest.md) — the manifest format
- [`docs/State.md`](./docs/State.md) — the on-card state format
- [`schema/edgetx-manifest.v1.json`](./schema/edgetx-manifest.v1.json) — the
  machine-checkable subset of the manifest format
- [`schema/edgetx-state.v1.json`](./schema/edgetx-state.v1.json) — the
  machine-checkable subset of the state format

[`docs/Implementation.md`](./docs/Implementation.md),
[`docs/GettingStarted.md`](./docs/GettingStarted.md) and `README.md` are
guidance. Keep normative rules out of them: a requirement that lives only in a
guidance document cannot be relied on, and it is how the two halves of a
specification drift apart.

Use [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) terms — MUST, MUST NOT,
SHOULD, MAY — in the normative documents. Do not substitute emphasis for a
requirement level; "**CRITICAL**" tells a reader nothing about whether they
can ship without it.

## Versioning

`edgetx_format_version` is what manifests declare, and moving it has consequences for
every existing manifest and every deployed tool. See
[Manifest.md](./docs/Manifest.md#edgetx_format_version) for the rules tooling follows.

The rule that binds *this repository*:

> **A MINOR addition has to be safely ignorable by older tooling.**

(This is a rule about editing this repository, not a conformance requirement —
its normative form is in
[Manifest.md](./docs/Manifest.md#edgetx_format_version).)

Before adding a field as a MINOR change, work out what tooling that has never
heard of it actually does:

- If it ignores the field and still produces a correct — possibly reduced —
  result, the change is MINOR.
- If it rejects the manifest, or acts on the field's absence in a way that is
  wrong rather than merely limited, the change is MAJOR.

This is not a formality. It is why `requires` is a separate top-level field
rather than something older tooling would choke on — see
[Manifest.md § requires](./docs/Manifest.md#requires--other-packages).

Two places are **closed to MINOR additions** because ignoring a field there is
never harmless:

- **A variant entry** (`variants[]`). Its fields decide which entries match and
  what each scores for specificity, and specificity chooses which build gets
  installed — so tooling ignoring one installs a different variant and then
  records the same package at the same version. `additionalProperties: true` on
  that object exists so older tooling can *load* a newer manifest, not so that
  fields may be added additively.
- **A closed enum** anywhere in either schema. Older tooling rejects an unknown
  value rather than ignoring it, which contradicts the requirement to process a
  higher MINOR.

Both are the same test applied honestly, and both are easy to fail: adding an
optional field looks additive everywhere else in this format.

A MAJOR bump is expensive: every existing manifest keeps its old version, and
tooling must support both. Reach for it only when the alternative is tooling
that misbehaves silently.

Record changes in [`CHANGELOG.md`](./CHANGELOG.md) **once a version is
released**: an entry exists so that someone on an earlier version knows what
moved. Before the first release there is no such reader, and an entry describing
a change against an unreleased draft documents a version nobody ran — the git log
already holds that. Editorial changes never need an entry.

## Making a change

Update all of these together. Do not leave any for a follow-up:

1. The affected normative document.
2. The matching schema — `edgetx-manifest.v1.json` or `edgetx-state.v1.json` —
   if the change is expressible in JSON Schema. Prefer a schema rule over
   prose; prose rules are not checked.

   One exception, and it is load-bearing: **do not add
   `additionalProperties: false`.** Every object in both schemas is
   deliberately permissive so that unknown keys are ignored rather than
   rejected. Closing one would mean a MINOR format bump that adds a field
   there is rejected by older tooling, which the versioning rule above
   forbids.
3. A conformance fixture — `conformance/valid/`, `conformance/invalid/`,
   `conformance/state-valid/` or `conformance/state-invalid/`. Every new
   constraint needs a fixture that would fail without it.
4. `CHANGELOG.md`.
5. `docs/GettingStarted.md`, if the change affects what package authors write.

Then check cross-document consistency: Manifest.md field definitions against the
schema, State.md formats against Implementation.md's examples, and terminology
across all of them.

**When you change a rule, add its old wording to `RETIRED_WORDINGS` in
[`run_tests.py`](./conformance/run_tests.py).** A rule is usually stated in more
than one document, and review round after review round found a change applied to
one site and not the others — each time leaving two normative artifacts saying
different things, which makes "conforming" undefined rather than merely unclear.
Grep discipline did not prevent it. Recording the superseded wording makes CI find
the other sites for you, which is the part that keeps being missed.

Four things the list above does not make obvious, each of which has been got
wrong here at least once:

- A new manifest field usually belongs in **more than one table** — the
  top-level, package-fields or content-item table, *and* the Validation summary
  if it carries a load-time check. A rule about tooling *behaviour* goes in the
  Behavioural rules table instead, where nothing pretends a fixture covers it.
- The Contents lists in `Manifest.md`, `State.md` and `Implementation.md` are
  hand-maintained and checked by `run_tests.py`. There is no generator — add or
  rename a heading and you must update the list by hand, including its
  indentation, or the check fails.
- Several constraints are **duplicated across the two schemas**. Change one and
  change the other. `run_tests.py` compares the *value* constraints — pattern,
  enum, lengths, item counts — of every node in the state schema against its
  counterpart, found by identical `$defs` name, by a declared entry in
  `CROSS_NAMED` when the two schemas reach it by different routes, or exempted
  by a declared entry in `STATE_ONLY` with a reason. Structure legitimately
  differs between the formats and is not compared. A divergence fails, and so
  does a new constraint that is neither paired nor exempted. Do not write a
  count here — an earlier version of this paragraph stated one and it was
  already stale.
- `run_tests.py` cross-checks the Validation summary in both directions: every
  fixture it names must exist, every `SEMANTIC_ONLY` fixture must be cited, and
  each cited fixture must actually behave as its half of the table claims.
  Renaming a fixture without updating the table fails CI.

## Semantic-only fixtures

Some rules cannot be expressed in JSON Schema — anything needing the source
tree, or a cross-reference within the document. Those fixtures are listed in
`SEMANTIC_ONLY` in [`conformance/run_tests.py`](./conformance/run_tests.py)
with a comment saying why.

Keep that set as small as possible. A rule the schema *can* express belongs in
the schema, not on that list. If you are adding to `SEMANTIC_ONLY`, first check
that the constraint really is inexpressible — and add a row for it in
[Manifest.md's Validation summary](./docs/Manifest.md#checked-by-tooling-at-load-time).
`run_tests.py` fails if a semantic-only fixture is not cited there.

## Rules with no fixture

Some rules in the Validation summary have no fixture, because demonstrating them
needs the network, a live filesystem, or a context no single file carries — no one
file can express "this `source_dir` is not a directory", or "this manifest was
loaded as a subpackage under a different id". Those rows carry an em-dash in the
fixture column, and Manifest.md lists its purely
[behavioural rules](./docs/Manifest.md#behavioural-rules) separately so nothing
in the table looks covered when it is not. Together these are the
weakest-covered part of the specification.

Do not put a count in this paragraph. The previous version said "eight" and the
real number had already changed.

If you are adding a rule of that shape, say so in the Validation summary with
an em-dash in the fixture column rather than leaving the row looking covered.
A behavioural suite that drives a real implementation would close this, and
would be the highest-value addition to this repository — but it needs a
reference implementation to drive, so it is deliberately not attempted here.

## Running the checks

```sh
pip install jsonschema PyYAML
python3 conformance/run_tests.py

npm install -g markdownlint-cli@0.45.0
markdownlint --ignore node_modules "**/*.md"
```

`run_tests.py` runs these; markdownlint is the other half of CI:

| Check | What it holds |
|---|---|
| Manifest fixtures | `valid/` passes the schema, `invalid/` is rejected — for the reason it names |
| State fixtures | Same, routed to `installed.yml` or `.operation` by filename and shape |
| File lists | Every line of `conformance/file-lists/*.list`, each `invalid-*` pinned by its `# expect:` directive |
| File-list examples | The `PKG/files/*.list` examples embedded in the docs |
| Fixture index | Every fixture the Validation summaries name exists; every semantic-only fixture is cited |
| Summary halves | Each cited fixture behaves as its half of the table claims |
| Shared schema patterns | Same-named `$defs` are identical across the schemas; every other state pattern is accounted for |
| Contents lists | Each Contents list matches its document's headings, indentation included |
| Links and anchors | Every relative link and cross-file anchor resolves |
| Table structure | No table broken by a paragraph inserted between its rows |
| Strict YAML | Every fixture loads under a duplicate-key-rejecting loader, as Go and Rust do |
| Retired wordings | No document still carries a wording superseded elsewhere |
| Documentation examples | Every YAML example in the docs validates, fragments included |

Each schema is also checked for being a well-formed JSON Schema — a malformed one
would silently accept everything.

Most of these exist because the defect they catch actually shipped here. Before
adding a check, make it fail: copy the repository to a scratch directory,
introduce the defect it is meant to catch, and confirm a red suite. A check that
cannot fail is worse than no check, because it is also a claim.

CI runs both commands on every pull request.

## Examples

Keep examples minimal and demonstrating one rule at a time. Every manifest
example in the docs is validated against the schema, so it must be a complete,
valid manifest — including `package.id` and `package.description` — or a
fragment that clearly is not a whole manifest.
