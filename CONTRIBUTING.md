# Contributing

This repository contains specification documents. Proposed changes should be precise, documentation-first, and consistent with the existing package model.

## Proposing specification changes

- Submit changes as a pull request with a clear description of the behavior being added, clarified, or corrected.
- Update the affected reference document in the same change set:
  - [`docs/Manifest.md`](./docs/Manifest.md) for manifest format and package layout changes
  - [`docs/State.md`](./docs/State.md) for install, update, remove, or state tracking changes
- Update `README.md` only when repository-level scope, references, or high-level summaries need to change.

## Examples

- Keep examples minimal and unambiguous.
- Prefer valid, complete snippets that demonstrate one rule or interaction at a time.
- Ensure example field names, paths, and behavior remain consistent with the normative text.

## Compatibility and documentation

- Preserve backward compatibility where possible.
- Call out incompatible or behavior-changing updates explicitly in the pull request and the affected documentation.
- When a change affects both manifest behavior and runtime state behavior, update both reference documents as applicable.
- Do not leave documentation updates for follow-up changes; normative text and examples should be updated together.
