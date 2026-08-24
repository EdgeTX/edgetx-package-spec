# Changelog

Changes to the EdgeTX package specification.

`edgetx_format_version` is the version manifests and state files declare. It
moves as described in
[Manifest.md](./docs/Manifest.md#edgetx_format_version): MAJOR for a breaking
change, MINOR for an additive one. Editorial changes that do not affect what
tooling must accept do not move it.

## Unreleased — `edgetx_format_version` 1.0

Not yet tagged. Until it is, the release-asset URLs in
[GettingStarted](./docs/GettingStarted.md#validation) have nothing to fetch;
that section says so and gives the interim form.

**First specification release.** There is no prior released version, so there is
nothing to describe changes against — the format is defined by
[Manifest.md](./docs/Manifest.md), [State.md](./docs/State.md) and the two JSON
Schemas, and this entry records only what a reader of a later version needs to
know about where 1.0 started.

What 1.0 covers:

- package identity as repository location, with no separate name registry
- ten content sections, source and destination paths, and `exclude` patterns
- hardware capability requirements and firmware version bounds
- hardware variants of one package, selected by capabilities and firmware
- precompiled `.luac` packages, with one build per firmware generation
- cross-package dependencies (`requires`) with semver ranges
- subpackages: several independent packages in one repository
- the on-card state under `PKG/` that makes update and remove correct

Deliberately **not** in 1.0, each of which can arrive as a MINOR addition when a
real package needs it: a `depends` field for libraries inside one manifest, a
flat-file spelling of subpackages, a `category` enum, and any caching of a
package's compatibility verdict in state. Detailed rationale for each is in the
git history; the short version is that no packages exist yet, so every feature
was speculative, and a speculative feature costs once per client implementation.

Development history before this release is in the git log rather than here.
Entries describing changes against unreleased drafts would document a version
nobody ran.
