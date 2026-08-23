#!/usr/bin/env python3
"""
EdgeTX Package Spec — conformance test runner.

Usage:
    python conformance/run_tests.py

Exit codes:
    0  All tests passed
    1  One or more tests failed

Schema validated: schema/edgetx-manifest.v1.json
Valid examples:   conformance/valid/    — all must pass JSON Schema validation
Invalid examples: conformance/invalid/  — all must fail JSON Schema validation
Semantic cases:   conformance/semantic/ — structurally valid but semantically invalid;
                                          not tested here (require semantic analysis)
"""

import json
import pathlib
import sys

import jsonschema
import yaml

REPO_ROOT = pathlib.Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "edgetx-manifest.v1.json"
VALID_DIR = REPO_ROOT / "conformance" / "valid"
INVALID_DIR = REPO_ROOT / "conformance" / "invalid"


def load_schema() -> dict:
    with SCHEMA_PATH.open() as fh:
        return json.load(fh)


def validate(instance: dict, schema: dict) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(instance)]


def run() -> bool:
    schema = load_schema()
    passed = 0
    failed = 0

    print(f"Schema: {SCHEMA_PATH.relative_to(REPO_ROOT)}\n")

    # ---- valid fixtures: must ALL pass ----
    print("=== Valid manifests (must pass) ===")
    for path in sorted(VALID_DIR.glob("*.yml")):
        with path.open() as fh:
            instance = yaml.safe_load(fh)
        errors = validate(instance, schema)
        rel = path.relative_to(REPO_ROOT)
        if errors:
            print(f"  FAIL  {rel}")
            for e in errors:
                print(f"        {e}")
            failed += 1
        else:
            print(f"  PASS  {rel}")
            passed += 1

    print()

    # ---- invalid fixtures: must ALL fail ----
    print("=== Invalid manifests (must fail) ===")
    for path in sorted(INVALID_DIR.glob("*.yml")):
        with path.open() as fh:
            instance = yaml.safe_load(fh)
        errors = validate(instance, schema)
        rel = path.relative_to(REPO_ROOT)
        if errors:
            print(f"  PASS  {rel}  (rejected as expected)")
            passed += 1
        else:
            print(f"  FAIL  {rel}  (should have been rejected but passed validation)")
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
