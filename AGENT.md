# Agent Guide

Context for AI agents working in this repository. Humans should start with
[README.md](./README.md) and [CONTRIBUTING.md](./CONTRIBUTING.md); everything
here is a pointer to those plus the few things an agent gets wrong without
being told.

## What this repository is

A specification, not an implementation. There is no build and no application
code — the deliverables are Markdown, two JSON Schemas, and a fixture suite.
Tooling lives in
[`EdgeTX/edgetx-package-tools`](https://github.com/EdgeTX/edgetx-package-tools)
(CLI: `edgetx-cli`).

```text
docs/Manifest.md                 normative  the edgetx.yml manifest format
docs/State.md                    normative  on-card state under PKG/
schema/edgetx-manifest.v1.json   normative  machine-checkable subset of Manifest.md
schema/edgetx-state.v1.json      normative  machine-checkable subset of State.md
docs/Implementation.md           guidance   algorithms for tooling authors
docs/GettingStarted.md           guidance   tutorial for package authors
README.md                        guidance   overview and routing
CONTRIBUTING.md                  process    how to change the specification
AGENT.md                         process    this file
CHANGELOG.md                     process    release history; editorial changes excluded
conformance/                     tests      fixtures + run_tests.py
```

## Checks

```sh
pip install jsonschema PyYAML
python3 conformance/run_tests.py

npm install -g markdownlint-cli@0.45.0
markdownlint --ignore node_modules "**/*.md"
```

Both must pass; CI runs exactly these. Use relative paths — never hardcode an
absolute or CI-runner path into a document.

`run_tests.py` runs far more than the fixtures — the full list is in
[CONTRIBUTING.md](./CONTRIBUTING.md#running-the-checks). What surprises agents:
editing a YAML example in a document, renaming a fixture, adding a heading
without regenerating a Contents list, changing a pattern in one schema and not
the other, or calling a helper in `Implementation.md`'s pseudocode that is not
declared in its Helper signatures block will each fail the suite.

## Things that are easy to get wrong here

**Normative versus guidance is load-bearing.** Only `docs/Manifest.md`,
`docs/State.md` and the two schemas define conformance. Adding a requirement to
`Implementation.md` does not make it a requirement — it makes it unfindable.
If a rule must hold, put it in a normative document.

**Use RFC 2119 terms, not emphasis.** MUST, SHOULD, MAY — never "**CRITICAL**",
which conveys no requirement level, and never bold text standing in for a
requirement.

Conformance requirements live in `Manifest.md` and `State.md`, and the schemas
repeat a few in `description` strings where a reader of the schema alone would
otherwise miss them. To extract them, match the whole keyword set, not just MUST
— `grep MUST` silently drops every SHOULD and MAY:

```sh
grep -nE 'MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|MAY|REQUIRED|RECOMMENDED|OPTIONAL' \
  docs/Manifest.md docs/State.md
```

Do not add conformance requirements to any other file. `CONTRIBUTING.md` states
its own rules without RFC 2119 keywords, deliberately, so that a keyword search
returns conformance requirements and nothing else.

**Prefer a schema rule over a prose rule.** Prose is not checked. If a
constraint is expressible in JSON Schema, put it there and add a fixture that
would fail without it. `SEMANTIC_ONLY` in `run_tests.py` is for rules that are
genuinely inexpressible — needing the source tree, or a cross-reference within
the document. Keep it small.

**Additive changes must be safely ignorable.** Before adding a field, work out
what tooling that has never heard of it does — the full rule and its worked
consequence are in
[CONTRIBUTING.md § Versioning](./CONTRIBUTING.md#versioning). It has already
changed one design decision, so read it rather than guessing.

`variants[]` is **closed**: no field may be added to a variant entry in a MINOR
bump, ever. Every field there feeds selection and specificity, and specificity
chooses which build installs, so tooling ignoring one installs a *different
variant*. The `additionalProperties: true` on that object is what lets older
tooling load a newer manifest; it is not permission to add fields. This is the
rule most likely to be violated by accident, because adding an optional field
looks additive everywhere else in the format.

**When a rule changes, fix every document that states it.** This is the single
most repeated defect in this repository's history — five review rounds in a row
found the same shape. `Implementation.md` walks the same ground as the normative
documents, so a rule changed in `Manifest.md` or `State.md` usually has a
counterpart there, and a stale counterpart is worse than none: implementers
transcribe the guide. After changing a normative rule, grep the guide for the
behaviour, not for the wording — the wording will have drifted. Where the guide
can *link* to a normative rule instead of restating it, prefer the link.

**Proportionality is a design constraint, not an afterthought.** The target is
RC-controller firmware plus browser and desktop tooling, writing to a FAT32
card, at hobbyist scale. Requirements that name POSIX APIs, assume `fsync` or
atomic-rename guarantees, or demand shadow copies of user data cannot be met
by a conforming browser implementation. An earlier draft of this spec mandated
all three. When adding a requirement, check that all three kinds of
implementation can satisfy it.

**Do not record project status in the specification.** Review histories, issue
counts and open-defect lists do not belong in published documents. They date
immediately and tell a prospective implementer the spec is unreliable. Use the
changelog for what changed, and the issue tracker for what is outstanding.

## Changing something

Follow [CONTRIBUTING.md § Making a change](./CONTRIBUTING.md#making-a-change).
It is the procedure; this file does not repeat it.

Two things that list does not make obvious, and that an agent gets wrong:

- A new manifest field usually belongs in **more than one table** in
  `Manifest.md` — the top-level, package-fields or content-item table, *and*
  the Validation summary if it carries a load-time check. A rule about tooling
  *behaviour* goes in the Behavioural rules table instead.
- The Contents lists in the three long documents are hand-maintained and checked
  by `run_tests.py` — there is no generator. Add or rename a heading and you must
  update the list by hand, indentation included, or the check fails.
- `run_tests.py` cross-checks the Validation summary: every fixture it names
  must exist, and every `SEMANTIC_ONLY` entry must be cited there. Adding a
  semantic-only fixture without a table row fails CI.

## Design context

Two things about the current state of the document that are not obvious from
reading it:

- **Cross-package dependencies (`requires`) have no implementation yet.** The
  manifest syntax, the state fields and the resolution rules are fully
  specified; the resolver walk in `Implementation.md` is deliberately advisory.
  Expect the first real implementation to surface gaps, and prefer tightening
  the normative rules over elaborating the pseudocode.
- **The reference tooling implements an earlier draft.** Divergence from
  `edgetx-package-tools` is expected and is not automatically a spec defect —
  but where that tooling shows a requirement to be impractical, that is worth
  taking seriously. It is the only evidence available about what this
  specification costs to implement.
