#!/usr/bin/env python3
"""
EdgeTX Package Spec — conformance test runner.

Usage:
    python3 conformance/run_tests.py

Exit codes:
    0  All tests passed
    1  One or more tests failed

What is checked:

  manifests      conformance/valid/          must pass  schema/edgetx-manifest.v1.json
                 conformance/invalid/        must fail  (except SEMANTIC_ONLY)
  state files    conformance/state-valid/    must pass  schema/edgetx-state.v1.json
                 conformance/state-invalid/  must fail
  file lists     conformance/file-lists/valid.list     every line must be a
                                                       valid installed path
                 conformance/file-lists/invalid-*.list  at least one line must
                                                       be rejected
  documentation  every manifest and state example embedded in a .md file must
                 validate against the matching schema. A fragment showing one
                 section is completed with a placeholder `package` block so its
                 own fields are still checked.

The documentation check exists because examples drifting from the schema is the
inconsistency a reader notices first.
"""

import json
import pathlib
import re
import sys

import jsonschema
import yaml

REPO_ROOT = pathlib.Path(__file__).parent.parent
MANIFEST_SCHEMA = REPO_ROOT / "schema" / "edgetx-manifest.v1.json"
STATE_SCHEMA = REPO_ROOT / "schema" / "edgetx-state.v1.json"

# Fixtures whose invalidity is semantic (not detectable by JSON Schema alone).
# These live in invalid/ to document the rule, but the violation can only be
# caught by tooling at load time. Keep this set as small as possible: a rule the
# schema can express belongs in the schema.
SEMANTIC_ONLY = {
    # `path` exists in the repo but not under any declared `source_dir`.
    "source-dir-no-fallback.yml",
    # `requires` names the package's own id.
    "requires-self.yml",
    # min_edgetx_version > max_edgetx_version; both are individually well-formed.
    "inverted-version-range.yml",
    # Variant manifest declares its own `variants` (no nesting allowed).
    "nested-variants.yml",
    # A variant manifest declaring an id that differs from its base. Valid as a
    # standalone manifest; invalid only in the context it is loaded from.
    "variant-id-mismatch.yml",
    # Two package-state files sharing one `(id, commit)` key. Each file is valid
    # alone; the duplicate exists only across the pair.
    "duplicate-package-key-a.yml",
    "duplicate-package-key-b.yml",
    # `source.repo` that is not a path prefix of `id`. Repository depth varies by
    # host, so no pattern can say where the repo ends and the subpackage begins;
    # comparing the two values can.
    "repo-not-prefix-of-id.yml",
    # Two `requires` entries naming the same id. `uniqueItems` compares whole
    # objects, so JSON Schema cannot express uniqueness by one property.
    "duplicate-requires-id.yml",
    # `license` must parse as an SPDX expression, which needs the identifier list.
    "malformed-license.yml",
    # Two comparators that form an empty range. The schema checks the comparator
    # shape, not that the pair is satisfiable.
    "inverted-requires-range.yml",
    # Two content items sharing a name, so no diagnostic can identify one.
    "duplicate-content-name.yml",
    # Two content items resolving to one destination.
    "duplicate-destination.yml",
    # A single-file destination that is an ancestor of another item's. Distinct
    # paths, so the same-destination rule does not fire; needs the source tree to
    # know which items are single files.
    "ancestor-destination-overlap.yml",
    # A variant entry whose firmware bounds are inverted. The schema checks each
    # bound's grammar; comparing the two is not a pattern.
    "inverted-variant-range.yml",
    # Two destinations differing only in case, which FAT32 does not distinguish.
    "case-only-destination-collision.yml",
    # A single-file source whose dest names an existing directory.
    "dest-kind-mismatch.yml",
}

STATE_MULTIFILE_EXPECTED = {
    "duplicate-package-key-a.yml": "PKG/packages/github.com%acme%simple-tool~3f9a1c0e.yml",
    "duplicate-package-key-b.yml": "PKG/packages/github.com%acme%simple-tool~3f9a1c0e.yml",
}


# Set once in run(): the loaded state schema, used as a sentinel so check_dir
# knows a directory holds state-family documents (a package-state file or
# .operation).
STATE_FAMILY: dict = {}
ALL_SCHEMAS: dict = {}


def markdown_files() -> list[pathlib.Path]:
    """Every tracked Markdown file, so no check quietly covers fewer than another.

    Three checks scanned root + docs/, one added conformance/**, and markdownlint
    scanned everything — so a table in conformance/file-lists/README.md was seen
    by the linter and by no structural check.
    """
    out = sorted(REPO_ROOT.glob("*.md"))
    for sub_dir in ("docs", "conformance", ".claude"):
        out += sorted((REPO_ROOT / sub_dir).rglob("*.md"))
    return out


def load_schema(path: pathlib.Path) -> dict:
    with path.open() as fh:
        schema = json.load(fh)
    # A schema that is itself malformed would silently accept everything.
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def validator(schema: dict) -> jsonschema.Draft202012Validator:
    # format_checker enables `format: email`, which jsonschema can check with no
    # extra dependency. `format: uri` needs rfc3987 and is inert without it, so
    # projectUrl carries a `pattern` as well and that is what actually holds —
    # otherwise CI would be laxer than check-jsonschema, which package authors
    # are told to use and which bundles the format libraries.
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def errors_for(instance, schema: dict) -> list[str]:
    return [e.message for e in validator(schema).iter_errors(instance)]


def manifest_top_level(schema: dict) -> set[str]:
    """Valid manifest top-level keys, read from the schema.

    Derived rather than hardcoded: a duplicate list here would silently
    reclassify doc examples using a newly added section as "not a document",
    turning a coverage regression into a SKIP instead of a FAIL.
    """
    return set(schema["properties"].keys())


def looks_like_manifest(doc, top_level: set[str]) -> bool:
    """A manifest example, whole or partial.

    True for any mapping whose keys are all valid manifest top-level fields.
    That deliberately includes fragments showing a single section — those are
    the newest, least-exercised syntax in the docs, so they are exactly what
    must not escape validation.
    """
    return (isinstance(doc, dict) and bool(doc)
            and set(doc.keys()) <= top_level)


def looks_like_content(doc) -> bool:
    """A block that is clearly manifest content but has an unrecognised key."""
    if not isinstance(doc, dict):
        return False
    if isinstance(doc.get("package"), dict):
        return True
    for value in doc.values():
        if isinstance(value, list) and any(
                isinstance(i, dict) and ("path" in i or "dest" in i) for i in value):
            return True
    return False


def as_whole_manifest(doc: dict) -> dict:
    """Complete a manifest fragment so it can be validated as a document.

    A fragment omits the required `package` block, or shows only part of it.
    Filling in the required fields lets the fragment's OWN fields be checked
    without weakening the schema.
    """
    filled = {k: v for k, v in doc.items() if k != "package"}
    package = {"id": "example.com/placeholder/placeholder",
               "description": "placeholder"}
    declared = doc.get("package")
    if isinstance(declared, dict):
        package.update(declared)
    filled["package"] = package
    return filled


def looks_like_state(doc) -> bool:
    return isinstance(doc, dict) and (
        isinstance(doc.get("packages"), list)
        or ("id" in doc and "reason" in doc and isinstance(doc.get("source"), dict))
    )


def state_family_schema(doc, state_schema: dict, name: str = "") -> dict:
    """Pick the right schema for a state-family document.

    PKG/packages/<package-key>.yml and PKG/.operation are separate formats that
    both live under State.md, so the directory alone cannot say which one a
    fixture is.

    A fixture named `marker-*` is ALWAYS a marker. Discriminating only on a key
    lets a fixture that omits that key dodge its own schema: a marker missing
    `operation` was routed to the package-state schema and "rejected as
    expected" for a different reason, leaving the marker's own contract
    untested — the exact failure this function's design was meant to prevent.
    """
    if name.startswith("marker-"):
        # Validate against the sub-schema alone: keep $defs so internal $refs
        # resolve, drop the document-level rules of the package-state file.
        return {"$schema": state_schema["$schema"],
                "$defs": state_schema["$defs"],
                "$ref": "#/$defs/operationMarker"}
    if name:
        return state_schema
    if ("operation" in (doc or {})
            and not {"id", "reason", "source", "requires"} <= set((doc or {}).keys())):
        return {"$schema": state_schema["$schema"],
                "$defs": state_schema["$defs"],
                "$ref": "#/$defs/operationMarker"}
    return state_schema


def looks_like_marker(doc) -> bool:
    """PKG/.operation — a normative format, so its examples get validated too.

    Routes on the discriminant rather than on the whole key set. A closed key set
    would reject a legal marker carrying a field from a later MINOR bump — which
    State.md requires tooling to tolerate — and would route an invalid marker to
    the package-state schema, where it fails for an unrelated reason and its own
    contract goes untested.
    """
    return (isinstance(doc, dict)
            and "operation" in doc
            and not {"id", "reason", "source", "requires"} <= set(doc.keys()))


def check_state_multifile_semantics() -> tuple[int, int]:
    """Exercise load-time-only rules that exist only across multiple state files."""
    directory = REPO_ROOT / "conformance" / "state-invalid"
    files = sorted(directory.glob("duplicate-package-key-*.yml"))
    if not files:
        return (0, 0)
    if len(files) < 2:
        print(f"  FAIL  duplicate-package-key: expected at least 2 fixtures, found {len(files)}")
        return (0, 1)
    docs = [yaml.safe_load(path.read_text()) for path in files]

    def expected_state_file(doc: dict) -> str:
        pkg_id = doc.get("id", "").lower().replace("/", "%")
        suffix = ((doc.get("source") or {}).get("commit") or "local")
        if suffix != "local":
            suffix = suffix[:8]
        return f"PKG/packages/{pkg_id}~{suffix}.yml"

    keys = [(doc.get("id", "").lower(),
             ((doc.get("source") or {}).get("commit") or "local"))
            for doc in docs]
    if len(set(keys)) != 1:
        print("  FAIL  duplicate-package-key: fixtures do not share one (id, commit) key")
        return (0, 1)
    declared_paths = [STATE_MULTIFILE_EXPECTED.get(path.name) for path in files]
    expected_paths = [expected_state_file(doc) for doc in docs]
    if declared_paths != expected_paths:
        print("  FAIL  duplicate-package-key: fixture state_file path does not match "
              "the derived package key")
        return (0, 1)
    if len(set(declared_paths)) != 1:
        print("  FAIL  duplicate-package-key: fixtures do not target one on-disk "
              "package-state path")
        return (0, 1)
    print(f"  PASS  duplicate-package-key  ({len(files)} files share one (id, commit) key)")
    return (1, 0)


def doc_examples(top_level: set[str]) -> list[tuple[str, object, str]]:
    """Every YAML example embedded in the docs, tagged with what it is.

    Fragments that are neither a whole manifest nor a whole state file are
    reported as skipped rather than silently ignored, so a new example cannot
    quietly escape validation.
    """
    found = []
    files = markdown_files()
    for md in files:
        blocks = re.findall(r"```ya?ml\n(.*?)```", md.read_text(), re.S)
        for n, block in enumerate(blocks, start=1):
            label = f"{md.relative_to(REPO_ROOT)} block {n}"
            try:
                doc = yaml.safe_load(block)
            except yaml.YAMLError as exc:
                found.append((label, exc, "unparseable"))
                continue
            if looks_like_marker(doc):
                found.append((label, doc, "marker"))
            elif looks_like_state(doc):
                found.append((label, doc, "state"))
            elif looks_like_manifest(doc, top_level):
                whole = isinstance(doc.get("package"), dict) and \
                    {"id", "description"} <= doc["package"].keys()
                found.append((label, as_whole_manifest(doc),
                              "manifest" if whole else "manifest fragment"))
            elif looks_like_content(doc):
                # A block that carries content-item or package keys but an
                # unrecognised top-level key is almost always a typo in the
                # documentation — `librarys:` for `libraries:`. A manifest may
                # legally carry unknown keys, but this repository's own examples
                # may not, or they would teach a section that installs nothing.
                found.append((label, doc, "misspelled key"))
            else:
                found.append((label, doc, "not a document"))
    return found


# Phrases jsonschema emits for almost any failure. A directive made of these
# pins nothing: `does not match` appears in every `pattern` violation.
VACUOUS_EXPECT = ("does not match", "is not valid", "is not of type",
                  "is a required property", "^$", ".*", "is not one of")


def is_vacuous(expect: str, foreign_errors: list[str]) -> bool:
    """A directive must pin THIS fixture's rule and no other fixture's.

    Two earlier versions were evaded. An exact blocklist fell to `.+` and to an
    alternation of jsonschema phrases. Scoring against synthetic strings fell to
    `does not match '`, which matched exactly one synthetic and so scored as
    specific — while in reality 23 of 29 fixtures could share it.

    So the test is empirical, not synthetic: a directive that matches the actual
    rejection of any OTHER invalid fixture is by definition not specific to this
    one. There is nothing left to guess a threshold about.
    """
    stripped = expect.strip().strip("^$")
    if stripped in ("", ".*", ".+") or expect.strip() in VACUOUS_EXPECT:
        return True
    try:
        return any(re.search(expect, e) for e in foreign_errors)
    except re.error:
        return False                  # an unparseable regex fails elsewhere


def foreign_errors(exclude: pathlib.Path, schemas: dict) -> list[str]:
    """Every rejection message produced by the OTHER invalid fixtures."""
    out = []
    for sub_dir in ("invalid", "state-invalid"):
        for path in sorted((REPO_ROOT / "conformance" / sub_dir).glob("*.y*ml")):
            if path == exclude or path.name in SEMANTIC_ONLY:
                continue
            try:
                instance = yaml.safe_load(path.read_text())
            except yaml.YAMLError:
                continue
            schema = schemas["state" if sub_dir.startswith("state") else "manifest"]
            if sub_dir.startswith("state"):
                schema = state_family_schema(instance, schema, path.name)
            out.extend(errors_for(instance, schema))
    return out


def check_dir(directory: pathlib.Path, schema: dict, must_pass: bool,
              allow_semantic: bool = False) -> tuple[int, int, int]:
    passed = failed = skipped = 0
    if not directory.is_dir():
        return (0, 0, 0)
    for path in sorted(list(directory.glob("*.yml")) + list(directory.glob("*.yaml"))):
        rel = path.relative_to(REPO_ROOT)
        if allow_semantic and path.name in SEMANTIC_ONLY:
            print(f"  SKIP  {rel}  (semantic-only: schema cannot detect this)")
            skipped += 1
            continue
        raw = path.read_text()
        instance = yaml.safe_load(raw)
        # `# expect: <regex>` on the first line pins WHICH rule the fixture
        # tests, so a second violation in the same file cannot stand in for it.
        expect = None
        first = raw.split("\n", 1)[0]
        m_exp = re.match(r"#\s*expect:\s*(.+)$", first)
        if m_exp:
            expect = m_exp.group(1).strip()
        effective = schema
        if schema is STATE_FAMILY:
            effective = state_family_schema(instance, STATE_FAMILY, path.name)
        errs = errors_for(instance, effective)
        if must_pass:
            if expect is not None:
                print(f"  FAIL  {rel}  (a must-pass fixture carries a `# expect:` "
                      f"directive; it pins a rejection that will never happen)")
                failed += 1
                continue
            if errs:
                print(f"  FAIL  {rel}")
                for e in errs:
                    print(f"        {e}")
                failed += 1
            else:
                print(f"  PASS  {rel}")
                passed += 1
        else:
            if not errs:
                print(f"  FAIL  {rel}  (should have been rejected but passed)")
                failed += 1
            elif expect is None:
                print(f"  FAIL  {rel}  (no `# expect:` first line, so the rule it "
                      f"names is not pinned — any rejection would satisfy it)")
                failed += 1
            elif is_vacuous(expect, foreign_errors(path, ALL_SCHEMAS)):
                print(f"  FAIL  {rel}  (`# expect: {expect}` matches almost any "
                      f"rejection; name the value or the rule instead)")
                failed += 1
            elif not any(re.search(expect, e) for e in errs):
                print(f"  FAIL  {rel}  (rejected for the wrong reason: expected "
                      f"/{expect}/, got {errs[0][:70]})")
                failed += 1
            else:
                print(f"  PASS  {rel}  (rejected as expected)")
                passed += 1
    return (passed, failed, skipped)


def check_file_list_examples(manifest_schema: dict) -> tuple[int, int]:
    """Check the ```text file-list examples embedded in the docs.

    check_file_lists covers the fixtures; this covers the copies a reader
    actually reads. A block counts as a file-list example when every non-blank
    line looks like a bare SD-card path — no YAML punctuation, no prose.
    """
    path_schema = {"$schema": manifest_schema["$schema"],
                   "$defs": manifest_schema["$defs"],
                   "$ref": "#/$defs/safeRelativeDest"}
    passed = failed = 0
    files = markdown_files()
    for md in files:
        # conformance/file-lists/README.md documents what an INVALID line looks
        # like, on purpose — it is the fixture guide, not a worked example.
        if md.parent.name == "file-lists":
            continue
        text = md.read_text()
        # Select by POSITION, not by whether the contents happen to be valid: a
        # content-based gate skips an all-invalid example instead of failing it,
        # which is the opposite of the point. A ```text block counts when the
        # prose introducing it names the file-list format.
        for m in re.finditer(r"(?s)(.{0,900}?)```text\n(.*?)```", text):
            preamble, block = m.group(1), m.group(2)
            first_line = block.split("\n")[0]
            mentions_file_list = (
                "PKG/files" in preamble
                or ("PKG/packages/" in preamble and ".list" in preamble)
                or "files/" in first_line
                or "packages/" in first_line
            )
            if not mentions_file_list:
                continue
            lines = [l for l in block.split("\n")
                     if l.strip() and not l.lstrip().startswith("#")]
            if not lines:
                continue
            if not re.match(r"^[A-Za-z0-9_.-]+/", lines[0]):
                continue
            # A block showing the path of the .list file itself is not a file
            # list example; file lists contain installed SD-card paths, never
            # PKG/ paths.
            if lines[0].startswith("PKG/"):
                continue
            # A directory tree also sits under a PKG/ heading. A file list holds
            # files: no box-drawing characters, and no line naming a directory.
            if any(c in block for c in "\u251c\u2514\u2502") or \
                    any(l.rstrip().endswith("/") for l in lines):
                continue
            label = f"{md.relative_to(REPO_ROOT)}:{text[:m.start()].count(chr(10)) + 1}"
            bad = [f"{l!r}" for l in lines if errors_for(l, path_schema)]
            if bad:
                print(f"  FAIL  {label}: {bad[0]} is not a valid installed path")
                failed += 1
            else:
                print(f"  PASS  {label}  ({len(lines)} paths)")
                passed += 1
    # State.md documents the format and Implementation.md works an example, so
    # fewer than two means the selector stopped seeing one — which is how a
    # rewritten example full of forbidden paths passed as "no examples found".
    if passed + failed < 2:
        print(f"  FAIL  only {passed + failed} file-list example(s) found; expected at "
              f"least 2 (State.md and Implementation.md). The selector is broken, or "
              f"an example was removed.")
        failed += 1
    return (passed, failed)


def check_file_lists(manifest_schema: dict) -> tuple[int, int]:
    """Check PKG/files/*.list fixtures line by line.

    The file list is a normative format with no JSON Schema of its own, so it
    would otherwise be the only one with no machine-checkable coverage. Each
    line is held to the same pattern the manifest schema applies to `dest`,
    which is the guarantee State.md asks for: a path read back from a removable
    card is not trusted input.
    """
    directory = REPO_ROOT / "conformance" / "file-lists"
    if not directory.is_dir():
        return (0, 0)
    path_schema = {"$schema": manifest_schema["$schema"],
                   "$defs": manifest_schema["$defs"],
                   "$ref": "#/$defs/safeRelativeDest"}
    passed = failed = 0

    def expected_offender(list_path: pathlib.Path) -> str | None:
        """A `# expect: <regex>` first line pins WHICH line must be rejected."""
        first = list_path.read_text().split("\n", 1)[0]
        m = re.match(r"#\s*expect:\s*(.+)$", first)
        return m.group(1).strip() if m else None

    def offending(list_path: pathlib.Path) -> list[str]:
        bad = []
        # Split on LF/CRLF only, as State.md specifies. str.splitlines() also
        # breaks on U+0085/U+2028/U+2029, which would report a line number the
        # file does not have.
        raw = list_path.read_text().replace("\r\n", "\n")
        for n, line in enumerate(raw.split("\n"), start=1):
            if not line.strip():
                continue          # State.md: blank lines are ignored
            if line.startswith("#"):
                continue          # fixture directive / comment, not a path
            if errors_for(line, path_schema):
                bad.append(f"line {n}: {line!r}")
        return bad

    for list_path in sorted(directory.glob("*.list")):
        rel = list_path.relative_to(REPO_ROOT)
        bad = offending(list_path)
        # `valid*` so more than one accepted fixture is possible — State.md names
        # both LF and CRLF, and neither could be covered before.
        must_pass = list_path.name.startswith("valid")
        if must_pass:
            if bad:
                print(f"  FAIL  {rel}")
                for b in bad:
                    print(f"        {b}")
                failed += 1
            else:
                print(f"  PASS  {rel}")
                passed += 1
        else:
            # An invalid fixture must be rejected for the rule it names, not for
            # any rule at all: otherwise a regression in one rule is masked by
            # another violation in the same file.
            want = expected_offender(list_path)
            if want is None:
                print(f"  FAIL  {rel}  (no `# expect:` directive, so the rule it "
                      f"names is not actually pinned)")
                failed += 1
                continue
            if not bad:
                print(f"  FAIL  {rel}  (should have been rejected but every line passed)")
                failed += 1
            elif want and not re.search(want, bad[0]):
                print(f"  FAIL  {rel}  (rejected the wrong line: expected /{want}/, "
                      f"got {bad[0]})")
                failed += 1
            else:
                print(f"  PASS  {rel}  (rejected: {bad[0]})")
                passed += 1
    return (passed, failed)


def check_fixture_index() -> tuple[int, int]:
    """Keep SEMANTIC_ONLY and the Validation summary table honest.

    Manifest.md's Validation summary is the repo's only rule index. An index
    nobody checks drifts, so CI checks it: every SEMANTIC_ONLY entry must name a
    real file and be cited in the table, and every fixture the table names must
    exist.
    """
    passed = failed = 0
    invalid_dirs = [REPO_ROOT / "conformance" / "invalid",
                    REPO_ROOT / "conformance" / "state-invalid"]
    # Scan the Validation summary only. Scanning the whole document swept up
    # real SD-card paths discussed in prose (`PKG/packages/...`) and called them
    # missing fixtures.
    summary = ""
    extra_failures: list[str] = []
    for doc in ("Manifest.md", "State.md"):
        full = (REPO_ROOT / "docs" / doc).read_text()
        marker = "## Validation summary"
        if marker not in full:
            print(f"  FAIL  docs/{doc} has no Validation summary section")
            return (0, 1)
        start = full.index(marker)
        # Stop at the next top-level heading, and also at "Behavioural rules":
        # that part's premise is that no fixture can express its rules, so a
        # citation there is a mislabelling, not coverage.
        stops = [x for x in (full.find("\n## ", start + len(marker)),
                             full.find("\n### Behavioural rules", start)) if x != -1]
        summary += full[start:min(stops) if stops else len(full)]
        # A fixture named in the Behavioural part is a contradiction; catch it.
        beh = full.find("### Behavioural rules", start)
        if beh != -1:
            beh_end = full.find("\n## ", beh)
            cited_in_beh = [n for n in re.findall(
                r"`([A-Za-z0-9._/-]+\.(?:ya?ml|list))`",
                full[beh:beh_end if beh_end != -1 else len(full)])
                if not n.rsplit("/", 1)[-1].startswith("edgetx.")]
            for bad in cited_in_beh:
                print(f"  FAIL  docs/{doc} cites {bad} under Behavioural rules, whose "
                      f"premise is that no fixture can express those rules")
                extra_failures.append(bad)

    for name in sorted(SEMANTIC_ONLY):
        if not any((d / name).exists() for d in invalid_dirs):
            print(f"  FAIL  SEMANTIC_ONLY names {name}, which does not exist")
            failed += 1
        elif f"`{name}`" not in summary:
            print(f"  FAIL  {name} is semantic-only but is not cited in "
                  f"Manifest.md's Validation summary")
            failed += 1
        else:
            print(f"  PASS  {name} exists and is cited in the Validation summary")
            passed += 1

    # Any case, underscores, and an optional directory prefix. The previous
    # character class saw only [a-z0-9.-], so renaming a fixture to
    # `Malformed_URL.yml` made the citation invisible and deleting the file
    # still passed.
    cited = {n.rsplit("/", 1)[-1]
             for n in re.findall(r"`([A-Za-z0-9._/-]+\.(?:ya?ml|list))`", summary)
             if not n.rsplit("/", 1)[-1].startswith("edgetx.")}
    # The tutorial's Examples table names fixtures too, and renaming one used to
    # rot that citation silently.
    tutorial = (REPO_ROOT / "docs" / "GettingStarted.md").read_text()
    cited |= {n for n in re.findall(r"`([A-Za-z0-9._-]+\.ya?ml)`", tutorial)
              if not n.startswith("edgetx.")}
    searched = [REPO_ROOT / "conformance" / d
                for d in ("valid", "invalid", "state-valid", "state-invalid", "file-lists")]
    missing = 0
    for name in sorted(cited):
        if not any((d / name).exists() for d in searched):
            print(f"  FAIL  Validation summary cites {name}, which does not exist")
            failed += 1
            missing += 1
        else:
            passed += 1
    failed += len(extra_failures)
    if missing:
        print(f"  FAIL  {missing} of {len(cited)} cited fixtures are missing")
    else:
        print(f"  PASS  all {len(cited)} cited fixtures exist")
    return (passed, failed)


def check_summary_halves(manifest_schema: dict, state_schema: dict) -> tuple[int, int]:
    """Every fixture must be cited in the half that matches its actual behaviour.

    Manifest.md splits the Validation summary into "Checked by the JSON Schema"
    and "Checked by tooling at load time". Without this check, moving a row
    between the halves is an undetectable lie about what is enforced.
    """
    passed = failed = 0
    halves = {"schema": "", "load": ""}
    # Both normative documents carry a Validation summary. Reading only one let
    # the other's table claim the schema enforces something it cannot.
    for doc in ("Manifest.md", "State.md"):
        full = (REPO_ROOT / "docs" / doc).read_text()
        try:
            schema_half = full.index("### Checked by the JSON Schema")
            load_half = full.index("### Checked by tooling at load time")
        except ValueError:
            print(f"  FAIL  docs/{doc} is missing a Validation summary subsection")
            return (0, 1)
        # Stop the load half at the next subsection: a third part (Behavioural
        # rules) must not be swallowed into it, or a fixture cited there is
        # judged against the wrong expectation.
        nxt = full.find("\n### ", load_half + 1)
        halves["schema"] += full[schema_half:load_half]
        halves["load"] += full[load_half:nxt if nxt != -1 else len(full)]
    dirs = {d: REPO_ROOT / "conformance" / d
            for d in ("valid", "invalid", "state-valid", "state-invalid")}

    for half, text in halves.items():
        for name in sorted({n.rsplit("/", 1)[-1]
                            for n in re.findall(r"`([A-Za-z0-9._/-]+\.ya?ml)`", text)
                            if not n.rsplit("/", 1)[-1].startswith("edgetx.")}):
            path = next((d / name for d in dirs.values() if (d / name).exists()), None)
            if path is None:
                continue          # missing files are reported by check_fixture_index
            with path.open() as fh:
                instance = yaml.safe_load(fh)
            schema = (state_family_schema(instance, state_schema, name)
                      if path.parent.name.startswith("state") else manifest_schema)
            rejected = bool(errors_for(instance, schema))
            if half == "schema" and not rejected:
                print(f"  FAIL  {name} is cited as schema-checked but the schema accepts it")
                failed += 1
            elif half == "load" and rejected:
                print(f"  FAIL  {name} is cited as load-time-only but the schema rejects it")
                failed += 1
            else:
                passed += 1
    if not failed:
        print("  PASS  every cited fixture behaves as its half of the table claims")
    return (passed, failed)


# Patterns that legitimately exist only in the state schema, with the reason.
# Anything else in the state schema must appear verbatim in the manifest schema.
# $defs names (or property names) whose pattern legitimately exists only in the
# state schema, each with its reason. Anything else must match the manifest
# schema verbatim.
# JSON pointers into the STATE schema whose constraints legitimately have no
# counterpart in the manifest schema, each with the reason. Keyed on the full
# pointer, not a leaf name: keying on "path" exempted every present and future
# property called `path`, at any depth.
# Each entry pins the constraint's VALUE, not merely its presence. Asserting only
# that a declared node still carries "some" constraint let a cap be raised to
# 999999 and a control-character ban be replaced by ^.+$ with a green suite.
def ref_pattern() -> str:
    """The git-refname constraint, kept in one place so the pin cannot drift."""
    return ("^(?![\\s\\S]*[\\x00-\\x20\\x7f-\\x9f\\u2028\\u2029])(?!-)(?!/)"
            "(?!.*//)(?!.*\\.\\.)(?!.*@\\{)(?!.*(?:^|/)\\.)(?!.*(?:^|/)"
            "[^/]*\\.lock(?:/|$))(?!.*[/.]$)(?!@$)[^~^:?*\\[\\\\]+$")


STATE_ONLY = {
    "/$defs/timestamp": (
        "state records when things happened; a manifest does not",
        {"pattern": "^(?![\\s\\S]*[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029])[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"}),
    "/$defs/requiredTimestamp": (
        "as above, non-nullable for the operation marker",
        {"pattern": "^(?![\\s\\S]*[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029])[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"}),
    "/$defs/source/properties/commit": (
        "state records what is installed",
        {"pattern": "^(?![\\s\\S]*[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029])([0-9a-f]{40}|[0-9a-f]{64})$"}),
    "/$defs/requirement/properties/commit": (
        "state may record which resolved dependency version was chosen",
        {"pattern": "^(?![\\s\\S]*[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029])([0-9a-f]{40}|[0-9a-f]{64})$"}),
    "/$defs/localAbsolutePath": (
        "an absolute host path; the only non-SD path",
        {"pattern": "^(?![\\s\\S]*[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029])(?:/(?:.*)?|[A-Za-z]:(?:[\\\\/].*)?)$", "minLength": 1, "maxLength": 4096}),
    "/$defs/operationMarker/properties/operation": (
        "the marker's own enum",
        {"enum": ["install", "update", "remove"]}),
    "/$defs/installedPackage/properties/reason": (
        "explicit vs dependency; state-only",
        {"enum": ["explicit", "dependency"]}),
    "/$defs/source/properties/channel": (
        "how a version resolved; a manifest has no channel",
        {"enum": ["tag", "branch", "commit", "local"]}),
    "/$defs/gitRefName": (
        "the tag or branch installed from; state-only, and fed to a fetch",
        {"pattern": ref_pattern(), "minLength": 1, "maxLength": 255}),
}

# Cross-named duplicates: the same constraint reached by a different route in each
# schema. Derived pairing is impossible here — only a human knows that `semver`
# and `packageBlock.properties.version` are the same rule — so they are declared,
# and anything NOT declared and NOT in STATE_ONLY fails.
CROSS_NAMED = {
    "/$defs/variantPath": "/$defs/variant/properties/path",
    "/properties/edgetx_format_version": "/properties/edgetx_format_version",
    # A display name is the same field in both formats, so the same bound applies.
    "/$defs/installedPackage/properties/name": "/$defs/packageBlock/properties/name",
    # The snapshot mirrors the manifest's requires list, so it carries the same cap.
    "/$defs/installedPackage/properties/requires": "/properties/requires",
}

# Only *value* constraints. `type` on a container and the branches of an
# `if`/`then` are structural, and structure legitimately differs between the two
# formats — comparing them buried the signal this check exists for.
CONSTRAINT_KEYS = ("pattern", "enum", "minLength", "maxLength", "format",
                   "maxItems", "minItems", "uniqueItems", "const")


def resolve_pointer(doc: dict, pointer: str):
    node = doc
    for part in pointer.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def constraints_of(node) -> dict:
    if not isinstance(node, dict):
        return {}
    return {k: json.dumps(node[k], sort_keys=True) for k in CONSTRAINT_KEYS if k in node}


def check_shared_patterns() -> tuple[int, int]:
    """Nothing may differ between the two schemas without being declared.

    Three generations of this check were defeated because each compared a
    hand-picked subset. This one inverts the burden: EVERY constrained node in the
    state schema must either match a same-named `$defs`, match a declared
    cross-named counterpart, or be declared state-only. An undeclared divergence
    fails, and so does an undeclared new constraint — loudly, which is the point.
    """
    m = json.loads(MANIFEST_SCHEMA.read_text())
    s = json.loads(STATE_SCHEMA.read_text())
    passed = failed = 0

    def walk(node, pointer=""):
        found = {}
        if isinstance(node, dict):
            c = constraints_of(node)
            if c:
                found[pointer] = c
            for k, v in node.items():
                found.update(walk(v, f"{pointer}/{k}"))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                found.update(walk(v, f"{pointer}/{i}"))
        return found

    # A declared pointer whose constraint was DELETED simply vanishes from the
    # walk and was never visited — so deleting six constraints from the state
    # schema passed silently. Assert every declaration still resolves.
    for pointer in sorted(set(STATE_ONLY) | set(CROSS_NAMED)):
        if resolve_pointer(s, pointer) is None:
            print(f"  FAIL  state{pointer} is declared in STATE_ONLY or CROSS_NAMED "
                  f"but no longer exists — remove the declaration, or restore the node")
            failed += 1
        elif pointer in STATE_ONLY:
            _reason, pinned = STATE_ONLY[pointer]
            node = resolve_pointer(s, pointer)
            actual = {k: json.loads(v) for k, v in constraints_of(node).items()}
            if actual != pinned:
                print(f"  FAIL  state{pointer} no longer matches its declared value")
                print(f"        declared: {json.dumps(pinned, sort_keys=True)}")
                print(f"        actual:   {json.dumps(actual, sort_keys=True)}")
                failed += 1
            else:
                passed += 1
        elif not constraints_of(resolve_pointer(s, pointer)):
            print(f"  FAIL  state{pointer} is declared but now carries no constraint "
                  f"— was it deleted?")
            failed += 1
        else:
            passed += 1

    for pointer, got in sorted(walk(s).items()):
        if "/allOf/" in pointer or "/if/" in pointer or "/then/" in pointer:
            continue          # structural logic, not a shared value constraint
        if pointer in STATE_ONLY:
            passed += 1
            continue
        counterpart = CROSS_NAMED.get(pointer, pointer)
        want = constraints_of(resolve_pointer(m, counterpart))
        if not want:
            print(f"  FAIL  state{pointer} has constraints with no manifest counterpart.")
            print(f"        Declare it in STATE_ONLY with a reason, or in CROSS_NAMED "
                  f"with its manifest pointer.")
            failed += 1
            continue
        differing = {k for k in set(got) | set(want) if got.get(k) != want.get(k)}
        if differing:
            print(f"  FAIL  state{pointer} differs from manifest{counterpart} "
                  f"on {sorted(differing)}")
            for k in sorted(differing):
                print(f"        {k}: state={got.get(k)}  manifest={want.get(k)}")
            failed += 1
        else:
            passed += 1

    # A $defs nobody references is dead weight that inflates this check's count.
    for name in sorted(s.get("$defs", {})):
        if name == "operationMarker":
            continue          # the marker entry point, referenced externally
        if f'"#/$defs/{name}"' not in json.dumps(s):
            print(f"  FAIL  state $defs/{name} is referenced by nothing — delete it "
                  f"or $ref it")
            failed += 1
    if not failed:
        print(f"  PASS  {passed} state-schema constraints all match a declared "
              f"counterpart or a declared exception")
    return (passed, failed)


# Words that appear as `name(` in Implementation.md's pseudocode but are language
# rather than helpers.
PSEUDOCODE_KEYWORDS = {
    "if", "for", "while", "return", "switch", "case", "not", "and", "or", "in",
    "is", "else", "print", "len", "max", "min", "any", "all", "sum", "sorted",
    "join", "split", "set", "list", "dict", "int", "str", "bool", "error", "warn",
    "report", "fail", "ok", "union", "count", "every", "some",
}

# Primitives the pseudocode uses without declaring them in the Helper signatures
# block, because they are self-evident I/O or list operations and declaring all
# of them would bury the handful that carry real contracts. Frozen deliberately:
# anything NOT here and NOT declared is a dangling name, which is how `owner_of`
# reached a published document. Adding to this set is a choice someone makes, not
# something that happens by accident.
PSEUDOCODE_PRIMITIVES = {
    "absolute", "all_content_items", "already_installed", "append", "apply",
    "as_list", "ask", "compile_lua", "copy_to_card", "copy_tree",
    "create_temp_dir", "delete", "delete_file_list", "delete_files",
    "dependency_packages_no_longer_required", "dest_lua_of", "directories_of",
    "exists", "expand_tilde", "fetch_and_load", "file_list_on_card_at_start",
    "find_installed", "first", "has_variants", "installed", "installed_packages",
    "inventory", "length", "load_local", "of", "parse", "parse_yaml", "path",
    "prune_empty_dirs", "re_resolve", "read", "read_file_list",
    "read_manifest_at", "remove_state_entry", "resolution_of",
    "resolution_of_installed", "satisfies", "semver_tags",
    "split_last", "triple", "variant_exists", "walk",
}

# Top-level routines: declared and defined here, called by a user rather than by
# other pseudocode, so "declared but never called" is correct for them.
PSEUDOCODE_ENTRY_POINTS = {
    "find_manifest", "install", "parse_ref", "resolve_version", "update",
}


def _pseudocode_blocks() -> list[str]:
    return re.findall(r"```text\n(.*?)```",
                      (REPO_ROOT / "docs" / "Implementation.md").read_text(),
                      re.DOTALL)


def check_pseudocode_helpers() -> tuple[int, int]:
    """Every name called in Implementation.md's pseudocode resolves to something.

    Three review rounds running, a fix to that file introduced a call to a helper
    that does not exist, or left a helper declared after deleting the algorithm
    that used it. Neither is visible to any other check here — the pseudocode is
    prose as far as the rest of this suite is concerned, and it is also the thing
    implementers actually transcribe.

    What it catches: a called name that resolves to nothing, and a declared helper
    nothing calls. What it does NOT catch, and nothing here does: a wrong
    algorithm, or a *variable* used before assignment — `base_pkg` assigned only
    inside a branch and read outside it slipped through a review round and would
    slip through this. Reviewing the pseudocode by transcribing and running it is
    still the only thing that finds those.
    """
    blocks = _pseudocode_blocks()
    if not blocks:
        print("  FAIL  docs/Implementation.md  (no ```text pseudocode blocks)")
        return 0, 1

    declared, called = set(), {}
    for block in blocks:
        for line in block.splitlines():
            m = re.match(r"^([a-z_][a-z0-9_]*)\(.*?\)\s*(->|:\s*$)", line)
            if m:
                declared.add(m.group(1))
                continue
            code = line.split("#", 1)[0]
            for name in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", code):
                called.setdefault(name, line.strip())

    failures = 0
    known = declared | PSEUDOCODE_KEYWORDS | PSEUDOCODE_PRIMITIVES
    for name, line in sorted(called.items()):
        if name not in known:
            print(f"  FAIL  docs/Implementation.md  `{name}(` is called but is "
                  f"neither declared in the Helper signatures block nor listed in "
                  f"PSEUDOCODE_PRIMITIVES\n        {line}")
            failures += 1

    for name in sorted(declared - set(called) - PSEUDOCODE_ENTRY_POINTS):
        print(f"  FAIL  docs/Implementation.md  `{name}` is declared but never "
              f"called — a stale contract a reader takes as current")
        failures += 1

    stale = sorted((PSEUDOCODE_PRIMITIVES | PSEUDOCODE_ENTRY_POINTS) - set(called)
                   - declared)
    for name in stale:
        print(f"  FAIL  conformance/run_tests.py  `{name}` is listed in this "
              f"file's pseudocode tables but appears in no pseudocode block")
        failures += 1

    if failures:
        return 0, failures
    print(f"  PASS  {len(called)} pseudocode calls resolve; "
          f"{len(declared)} helpers declared, none stale")
    return 1, 0


# The three documents README.md names as guidance. A conformance requirement in
# any of them is unfindable: AGENT.md tells an agent to extract requirements by
# grepping the RFC 2119 keyword set over the normative documents, so a MUST that
# lives here is one nobody will read as binding.
NON_NORMATIVE_DOCS = ("docs/Implementation.md", "docs/GettingStarted.md", "README.md")

RFC2119 = re.compile(r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|MAY|"
                     r"REQUIRED|RECOMMENDED|OPTIONAL)\b")


def check_normative_language() -> tuple[int, int]:
    """RFC 2119 keywords appear only in the documents that define conformance."""
    failures = 0
    for rel in NON_NORMATIVE_DOCS:
        text = (REPO_ROOT / rel).read_text()
        for n, line in enumerate(text.splitlines(), 1):
            m = RFC2119.search(line)
            if m:
                print(f"  FAIL  {rel}:{n}  carries the RFC 2119 keyword "
                      f"`{m.group(0)}`, but this document is non-normative — "
                      f"state the rule in Manifest.md or State.md and link to it")
                failures += 1
    if failures:
        return 0, failures
    print(f"  PASS  {len(NON_NORMATIVE_DOCS)} guidance documents carry no "
          f"conformance keywords")
    return 1, 0



def check_table_structure() -> tuple[int, int]:
    """Catch a table broken by a paragraph inserted between its rows.

    A round-1 defect lost seven normative field definitions this way: the
    orphaned rows render as literal text, and no markdownlint table rule fires
    because an orphan block is not a table.

    Run-based, not a state machine: collect each maximal run of consecutive
    pipe-lines and require its delimiter to be the run's SECOND line. That
    catches a run of ONE orphaned row, which the first version of this check
    missed and which is the likelier shape of a future edit.
    """
    passed = failed = 0
    files = markdown_files()

    def is_delim(line: str) -> bool:
        # Strip ALL pipes, not just the outer ones: "|---|---|" leaves an
        # internal pipe behind if only the ends are stripped, which made every
        # header row look like an orphan.
        body = line.strip().replace("|", "").replace(" ", "")
        return bool(body) and set(body) <= {"-", ":"}

    for md in files:
        problems, runs, current = [], [], []
        in_fence = False
        for n, line in enumerate(md.read_text().split("\n"), start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                current = []
                continue
            # GFM rows need not carry outer pipes. Gating on a leading "|" missed
            # a whole table written without them — the same defect in the shape the
            # check was not looking for.
            # Strip blockquote markers first: State.md carries its most
            # load-bearing rules in blockquotes, so a table added inside one is
            # exactly the shape this check exists for.
            stripped = re.sub(r"^(\s*>\s*)+", "", line).strip()
            is_row = ("|" in stripped
                      and not stripped.startswith(("-", "*", "#")))
            if not in_fence and is_row:
                current.append((n, line))
            else:
                if current:
                    runs.append(current)
                current = []
        if current:
            runs.append(current)

        for run in runs:
            if len(run) < 2 or not is_delim(run[1][1]):
                n, line = run[0]
                problems.append(f"line {n}: {len(run)} table row(s) with no header "
                                f"delimiter beneath — these render as literal text: "
                                f"{line.strip()[:60]}")
        if problems:
            print(f"  FAIL  {md.relative_to(REPO_ROOT)}")
            for pr in problems:
                print(f"        {pr}")
            failed += 1
        else:
            passed += 1
    if not failed:
        print(f"  PASS  {passed} files have well-formed tables")
    return (passed, failed)


def slugify(heading: str) -> str:
    """GitHub's heading-anchor algorithm, as far as this repository needs it."""
    h = re.sub(r"`|\*|\[|\]|\(|\)|<|>", "", heading).strip().lower()
    return re.sub(r"[^a-z0-9 _-]", "", h).replace(" ", "-")


def unique_slugs(text: str) -> set[str]:
    """Anchors as the renderer produces them, including -1 for a repeated heading."""
    seen: dict[str, int] = {}
    out = set()
    for _, title in headings(text):
        base = slugify(title)
        n = seen.get(base, 0)
        out.add(base if n == 0 else f"{base}-{n}")
        seen[base] = n + 1
    return out


def headings(text: str) -> list[tuple[int, str]]:
    """(depth, title) for every heading outside a fenced block."""
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6}) (.+)$", line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def check_strict_yaml() -> tuple[int, int]:
    """Every fixture must load under a duplicate-key-rejecting YAML loader.

    PyYAML silently takes the last of two identical keys; Go's yaml.v3 and Rust's
    serde_yaml reject the document. A fixture with duplicate keys therefore makes
    every strict-loader implementation fail conformance on a file it MUST accept —
    which one shipped fixture did, unnoticed, because the runner uses PyYAML.
    """
    class Strict(yaml.SafeLoader):
        pass

    def no_duplicate_keys(loader, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.YAMLError(
                    f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    Strict.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_duplicate_keys)

    passed = failed = 0
    for path in sorted((REPO_ROOT / "conformance").rglob("*.yml")):
        try:
            yaml.load(path.read_text(), Loader=Strict)
            passed += 1
        except yaml.YAMLError as exc:
            print(f"  FAIL  {path.relative_to(REPO_ROOT)}: {exc}")
            failed += 1
    if not failed:
        print(f"  PASS  all {passed} fixtures load under a strict YAML loader")
    return (passed, failed)


# Wordings that were once correct and are now wrong. Every entry here is a rule
# that was changed in one document and left standing in another — which has
# happened in four consecutive review rounds and each time left "conforming"
# undefined, because two normative artifacts said different things.
#
# The discipline this encodes: when you change a rule, add its OLD wording here.
# CI then finds every other site for you, which is the part a human keeps missing.
RETIRED_WORDINGS = {
    # Keep each entry the SHORTEST DISTINCTIVE PHRASE, not a whole sentence.
    # Matching is whitespace-normalised and case-insensitive, so a reflow or a
    # lowercased keyword cannot evade it — both of which happened in round six.
    "host segment is lowercased":
        "an id is case-insensitive throughout — Manifest.md#package-id",
    "the rest is case-sensitive":
        "an id is case-insensitive throughout — Manifest.md#package-id",
    "comparison of two paths is **textual**":
        "destinations compare case-insensitively — Manifest.md#path-rules",
    "exactly one spelling":
        "the path rules remove redundant spellings; case folding removes the rest",
    "512 content items in total":
        "512 content items in any ONE section, matching the schema's maxItems",
    "valid RFC 5321 address":
        "email SHOULD look like an address; tooling MUST NOT reject over one",
    "each must exist relative to the manifest directory":
        "screenshots are a SHOULD: a missing one warns, it does not block install",
    "leaves the source tree":
        "resolves outside the repository CHECKOUT ROOT — nothing under a link is outside it",
    "package's source tree":
        "the repository checkout root — nothing under a link is outside the link",
    "disables the default `*.luac` exclusion":
        "skip .luac at ANY depth; *.luac alone is top-level only",
    "null rather than raising":
        "select_variant returns NO_MATCH or AMBIGUOUS; one null cannot carry both",
    "may return null here":
        "select_variant returns NO_MATCH or AMBIGUOUS",
    "control character, including newline":
        "name the set: U+0000-U+001F, U+007F-U+009F, U+2028, U+2029",
    "1 mb is generous":
        "256 KiB, which is what the specification requires",
    "implementing `requires` is required for conformance":
        "tooling that can fetch MUST; tooling that cannot refuses and names what is missing",
    "included by default when syncing a working tree":
        "no sync operation is defined; --dev applies per invocation",
    "and the json schema.":
        "there are TWO normative schemas — say 'the two JSON Schemas'",
    "and the schema define":
        "there are TWO normative schemas — say 'the two JSON Schemas'",
    "`docs/state.md`, and the json schema":
        "there are TWO normative schemas — say 'the two JSON Schemas'",
    "are generated from their headings":
        "hand-maintained and checked by run_tests.py; there is no generator",
    "each generated contents list":
        "hand-maintained and checked by run_tests.py; there is no generator",
    "state_only_patterns":
        "the identifier is STATE_ONLY",
    # Round 7: both of these evaded the table by dropping a possessive or a
    # plural. Keys are now the shortest fragment that cannot be reworded away.
    "generated from the headings":
        "hand-maintained and checked by run_tests.py; there is no generator",
    "is content, and is handled like any other file":
        "an owned .luac COLLIDES with an owned .lua — State.md#bytecode-companions",
    "covers all three operations":
        "install, update, reinstall and remove — four",
}


def normalise(text: str) -> str:
    """Collapse whitespace and fold case, so drift cannot hide behind a reflow.

    The first version of this check matched exact literals in the source text.
    A round-six reviewer evaded it three ways in one sitting: lowercasing one
    word, letting a paragraph rewrap across a line break, and paraphrasing.
    """
    # Strip line-lead markers before collapsing: a retired phrase spanning a
    # pseudocode comment became "may return # null here" and evaded the table.
    text = re.sub(r"(?m)^\s*[#>*\-]+\s*", " ", text)
    return re.sub(r"\s+", " ", text).lower()


def retired_hits(text: str, strip_quotes: bool = False) -> list[tuple[str, str]]:
    haystack = normalise(text)
    if strip_quotes:
        # Quoted spans wrap across source lines, so strip them AFTER normalising
        # — before, the regex never matches a span that spans a line break.
        haystack = re.sub(r"`[^`]*`|\"[^\"]*\"", " ", haystack)
    return [(old, repl) for old, repl in RETIRED_WORDINGS.items()
            if normalise(old) in haystack]


def check_retired_wordings() -> tuple[int, int]:
    """No document may still carry a wording that was superseded elsewhere.

    Round after round found a rule changed in one document and left in another.
    Grep discipline did not prevent it; this does.
    """
    passed = failed = 0
    for md in markdown_files():
        # This README documents what an INVALID line looks like, on purpose.
        if md.parent.name == "file-lists":
            continue
        # The changelog may QUOTE a retired wording as history, but must not
        # assert one — a reader building from the release notes would implement
        # the superseded rule. So it is checked with quoted spans removed rather
        # than exempted wholesale. Agent prompts are exempt: they are not spec.
        if ".claude" in str(md):
            continue
        hits = retired_hits(md.read_text(),
                            strip_quotes=md.name == "CHANGELOG.md")
        if hits:
            print(f"  FAIL  {md.relative_to(REPO_ROOT)}")
            for old, repl in hits:
                print(f"        still says {old!r}")
                print(f"        superseded by: {repl}")
            failed += 1
        else:
            passed += 1
    for schema in (MANIFEST_SCHEMA, STATE_SCHEMA):
        text = schema.read_text()
        hits = retired_hits(text)
        if hits:
            print(f"  FAIL  {schema.relative_to(REPO_ROOT)}")
            for old, repl in hits:
                print(f"        still says {old!r} — superseded by: {repl}")
            failed += 1
        else:
            passed += 1
    if not failed:
        print(f"  PASS  no superseded wording survives in {passed} files "
              f"({len(RETIRED_WORDINGS)} retired wordings checked)")
    return (passed, failed)


def check_contents_lists() -> tuple[int, int]:
    """Each Contents list must match its document's headings exactly.

    CONTRIBUTING.md calls these lists "generated". Nothing generated them and
    nothing checked them, so the claim was an unenforced invariant in a
    repository whose whole thesis is that unenforced invariants drift.
    """
    passed = failed = 0
    for name in ("Manifest.md", "State.md", "Implementation.md"):
        md = REPO_ROOT / "docs" / name
        text = md.read_text()
        m = re.search(r"## Contents\n\n((?:\s*- .*\n)+)", text)
        if not m:
            print(f"  FAIL  docs/{name} has no Contents list")
            failed += 1
            continue
        depths = {d for d, _ in headings(text) if d >= 2} - {1}
        max_depth = max(depths) if depths else 2
        expected = [("  " * (depth - 2)) + f"- [{title}](#{slugify(title)})"
                    for depth, title in headings(text)
                    if 2 <= depth <= max_depth and title != "Contents"]
        # Compare including indentation: stripping it let the whole hierarchy be
        # flattened while still "matching", and hierarchy is the point of a
        # contents list for a 985-line document.
        got = [l.rstrip() for l in m.group(1).rstrip("\n").split("\n")]
        if got != expected:
            missing = [e for e in expected if e not in got]
            stale = [g for g in got if g not in expected]
            print(f"  FAIL  docs/{name}: Contents list does not match its headings")
            for x in missing[:5]:
                print(f"        missing: {x}")
            for x in stale[:5]:
                print(f"        stale:   {x}")
            failed += 1
        else:
            print(f"  PASS  docs/{name}  ({len(expected)} entries match)")
            passed += 1
    return (passed, failed)


def check_links() -> tuple[int, int]:
    """Every relative link must resolve, including its cross-file anchor.

    markdownlint's MD051 checks same-file fragments only. A link to a renamed
    file, or to a heading that moved in another document, went unnoticed — and
    cross-file anchors are the dominant link form here.
    """
    passed = failed = 0
    files = markdown_files()
    anchors: dict[pathlib.Path, set[str]] = {}
    for md in files:
        hs = unique_slugs(md.read_text())
        # An em-dash heading yields a doubled hyphen on GitHub; accept both.
        anchors[md.resolve()] = hs | {h.replace("--", "-") for h in hs}

    for md in files:
        problems = []
        text = md.read_text()
        # Fenced blocks are code, not prose: `seen[dest]` in a pseudocode block
        # is an index expression, and a label pattern that spans newlines will
        # happily pair it with the next `](` several lines below. Strip them
        # first — a link inside a code fence is not a link.
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        targets = [(lbl, tgt) for lbl, tgt in
                   re.findall(r"\[([^\]\n]*(?:\][^\]\n]*)*?)\]\(([^)\s]+)\)",
                              prose)]
        # Reference-style definitions and raw HTML hrefs were invisible, and both
        # are natural for the repeated cross-document links this repo is full of.
        targets += [("reference definition", tgt)
                    for tgt in re.findall(r"^\s*\[[^\]]+\]:\s*(\S+)", prose, re.M)]
        targets += [("html href", tgt)
                    for tgt in re.findall(r"<a\s[^>]*href=[\"']([^\"']+)[\"']", prose)]
        for label, target in targets:
            if target.startswith(("http://", "https://", "<", "mailto:")):
                continue
            path, _, frag = target.partition("#")
            resolved = (md.parent / path).resolve() if path else md.resolve()
            if not resolved.exists():
                problems.append(f"[{label}]({target}) -> no such file")
                continue
            if frag and resolved.suffix == ".md":
                known = anchors.get(resolved)
                if known is None:
                    known = unique_slugs(resolved.read_text())
                    known |= {h.replace("--", "-") for h in known}
                if frag not in known and frag.replace("--", "-") not in known:
                    problems.append(f"[{label}]({target}) -> no such heading")
        if problems:
            print(f"  FAIL  {md.relative_to(REPO_ROOT)}")
            for pr in problems:
                print(f"        {pr}")
            failed += 1
        else:
            passed += 1
    if not failed:
        print(f"  PASS  every relative link and cross-file anchor in {passed} files resolves")
    return (passed, failed)


def run() -> bool:
    global STATE_FAMILY
    manifest_schema = load_schema(MANIFEST_SCHEMA)
    state_schema = load_schema(STATE_SCHEMA)
    STATE_FAMILY = state_schema
    global ALL_SCHEMAS
    ALL_SCHEMAS = {"manifest": manifest_schema, "state": state_schema}
    passed = failed = skipped = 0

    sections = [
        ("Valid manifests (must pass)", "valid", manifest_schema, True, False),
        ("Invalid manifests (must fail)", "invalid", manifest_schema, False, True),
        ("Valid state files (must pass)", "state-valid", state_schema, True, False),
        ("Invalid state files (must fail)", "state-invalid", state_schema, False, True),
    ]
    for title, subdir, schema, must_pass, semantic in sections:
        print(f"=== {title} ===")
        p, f, s = check_dir(REPO_ROOT / "conformance" / subdir, schema, must_pass, semantic)
        passed, failed, skipped = passed + p, failed + f, skipped + s
        print()

    print("=== File lists ===")
    p, f = check_file_lists(manifest_schema)
    passed, failed = passed + p, failed + f
    print()

    print("=== State multi-file semantics ===")
    p, f = check_state_multifile_semantics()
    passed, failed = passed + p, failed + f
    print()

    print("=== File-list examples in the docs ===")
    p, f = check_file_list_examples(manifest_schema)
    passed, failed = passed + p, failed + f
    print()

    print("=== Fixture index (Validation summary must stay honest) ===")
    p, f = check_fixture_index()
    passed, failed = passed + p, failed + f
    print()

    print("=== Validation summary halves ===")
    p, f = check_summary_halves(manifest_schema, state_schema)
    passed, failed = passed + p, failed + f
    print()

    print("=== Shared schema patterns ===")
    p, f = check_shared_patterns()
    passed, failed = passed + p, failed + f
    print()

    print("=== Strict YAML ===")
    p, f = check_strict_yaml()
    passed, failed = passed + p, failed + f
    print()

    print("=== Retired wordings ===")
    p, f = check_retired_wordings()
    passed, failed = passed + p, failed + f
    print()

    print("=== Contents lists ===")
    p, f = check_contents_lists()
    passed, failed = passed + p, failed + f
    print()

    print("=== Links and anchors ===")
    p, f = check_links()
    passed, failed = passed + p, failed + f
    print()

    print("=== Pseudocode helper contracts ===")
    p, f = check_pseudocode_helpers()
    passed, failed = passed + p, failed + f
    print()

    print("=== Normative language confined to normative documents ===")
    p, f = check_normative_language()
    passed, failed = passed + p, failed + f
    print()

    print("=== Table structure ===")
    p, f = check_table_structure()
    passed, failed = passed + p, failed + f
    print()

    print("=== Documentation examples (must pass) ===")
    for label, doc, kind in doc_examples(manifest_top_level(manifest_schema)):
        if kind == "unparseable":
            print(f"  FAIL  {label}: unparseable YAML: {doc}")
            failed += 1
            continue
        if kind == "misspelled key":
            keys = ", ".join(sorted(doc.keys()))
            print(f"  FAIL  {label}: manifest content under an unrecognised "
                  f"top-level key (has: {keys})")
            failed += 1
            continue
        if kind == "not a document":
            keys = ", ".join(sorted(doc.keys())) if isinstance(doc, dict) else type(doc).__name__
            print(f"  SKIP  {label}  (not a manifest, state file or marker; has: {keys})")
            skipped += 1
            continue
        if kind in ("marker", "state"):
            schema = state_family_schema(doc, state_schema)
        else:
            schema = manifest_schema
        errs = errors_for(doc, schema)
        if errs:
            print(f"  FAIL  {label}  ({kind})")
            for e in errs:
                print(f"        {e}")
            failed += 1
        else:
            print(f"  PASS  {label}  ({kind})")
            passed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
