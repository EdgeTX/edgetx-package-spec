# AI Agent Guide for EdgeTX Package Specification

This document provides context and commands for AI agents working on this project.

## Project Overview

The EdgeTX Package Specification defines a package management system for EdgeTX radio firmware. The specification consists of:

- **docs/Manifest.md** - Package manifest format (edgetx.yml)
- **docs/Implementation.md** - Implementation guidance for package managers
- **docs/State.md** - Runtime state file formats
- **docs/GettingStarted.md** - User guide for package authors
- **schema/edgetx-manifest.v1.json** - JSON Schema for manifest validation
- **conformance/** - Conformance test suite

## Repository Structure

```
edgetx-package-spec/
├── docs/
│   ├── Manifest.md          # Normative manifest specification
│   ├── Implementation.md    # Implementation algorithms and requirements
│   ├── State.md            # State file formats
│   └── GettingStarted.md   # Author's guide
├── schema/
│   └── edgetx-manifest.v1.json  # JSON Schema for validation
├── conformance/
│   ├── valid/              # Valid manifest test cases
│   ├── invalid/            # Invalid manifest test cases
│   └── run_tests.py        # Test runner
├── CONTRIBUTING.md         # Contribution guidelines
├── README.md              # Project overview
└── AGENT.md              # This file

```

## Key Concepts

### Package Manifest
- YAML format (edgetx.yml)
- Declares package metadata, content items (tools, widgets, libraries, etc.)
- Supports variants for different hardware configurations
- Local dependency model (libraries are files within the package)

### State Files
- `EDGETX/PKG/state/installed.yml` - Installed package registry
- `EDGETX/PKG/state/files.yml` - File ownership tracking
- Transaction records for crash recovery

### Security Requirements
- Path traversal prevention (no .., absolute paths, or backslash separators)
- Symlink protection using descriptor-relative APIs with O_NOFOLLOW
- YAML parsing security (reject custom tags, limit size/depth)
- Reserved namespace: EDGETX/PKG/ for package manager internal use

## Validation Commands

### Schema Validation
```bash
cd /home/runner/work/edgetx-package-spec/edgetx-package-spec
python conformance/run_tests.py
```

### Linting
```bash
# Markdown linting (if configured)
markdownlint docs/
```

## Making Changes

### When updating documentation:

1. **Always update related files together**:
   - If changing Manifest.md, check if Implementation.md needs updates
   - If changing State.md, check if Implementation.md references need updates
   - If changing algorithms in Implementation.md, verify examples in GettingStarted.md

2. **Maintain consistency**:
   - Terminology must match across all documents
   - Examples must conform to the normative specification
   - Schema must align with documentation (within its limitations)

3. **Security-critical sections**:
   - Path Security and Validation (Implementation.md)
   - Transaction safety and crash recovery (State.md)
   - YAML Parsing Security (Implementation.md)
   - File Conflict Detection (Implementation.md)

4. **Update this AGENT.md**:
   - Add new sections if project structure changes
   - Update "Current Status" section below
   - Document any new commands or workflows

## Current Status

### Specification Maturity
The specification has undergone multiple review cycles:
- **Initial state**: 28 issues (4 critical, 10 major, 14 minor)
- **After first fix cycle**: 17 issues (4 critical, 10 major, 3 minor)
- **After second fix cycle**: 9 issues (3 critical, 6 major)
- **After third fix cycle**: ~5 issues (2-3 critical, 2-3 major)

### Recent Major Improvements
- ✅ Path traversal protection with mandatory descriptor-relative APIs
- ✅ Source symlink containment checks
- ✅ Transaction-based crash recovery protocol
- ✅ Hash verification before file deletion (user modification protection)
- ✅ Capability merging rules for base + variant requirements
- ✅ Dev mode filtering throughout install/update
- ✅ Package identity verification in updates
- ✅ YAML parsing security requirements
- ✅ Reserved namespace protection (EDGETX/PKG/)

### Known Remaining Issues

**Critical (requires deeper algorithmic changes):**
1. Transaction protocol defined in State.md but not integrated into Install/Update/Remove operation algorithms
2. Update operation doesn't verify file hashes before overwriting (can lose user modifications)
3. State recording signature mismatch for dev_mode parameter

**Major:**
1. Update operation calls conflict detection with wrong signature (missing staging_dir)
2. Conformance suite has 2 failing tests due to schema limitations (base vs variant validation)

**Note**: The schema cannot fully validate path security or base vs variant requirements - these must be checked at runtime by implementations.

## Common Tasks

### Running the Specification Review Agent

To get a comprehensive review of the specification for flaws:

```bash
# This is done via AI task delegation, not a command-line tool
# In the AI session, launch a rubber-duck agent with the specification review prompt
```

### Checking Cross-References

Key cross-references to verify:
- Manifest.md content item structure ↔ Implementation.md staging/conflict detection
- State.md file formats ↔ Implementation.md state recording/loading
- Implementation.md operation algorithms ↔ State.md transaction protocol
- Schema definitions ↔ Manifest.md field descriptions

### Testing Changes

```bash
# Run conformance tests
cd /home/runner/work/edgetx-package-spec/edgetx-package-spec
python conformance/run_tests.py

# Expected: 2 known failures (missing-id.yml, missing-description.yml)
# These require schema separation or context-aware validation
```

## Review Checklist

When making specification changes, verify:

- [ ] All operation algorithms are executable (no undefined functions/variables)
- [ ] State format examples include all required fields
- [ ] Security requirements are normative (use "must", not "should" or "recommended")
- [ ] Pseudocode signatures match their call sites
- [ ] Error codes are defined in State.md status vocabulary
- [ ] Path validation applies to all user-controlled paths
- [ ] Dev mode filtering is consistent across install/update/staging/conflict-detection
- [ ] Transaction protocol is referenced in operation algorithms
- [ ] Examples match the normative specification
- [ ] Cross-document terminology is consistent

## Related Resources

- **EdgeTX Project**: https://github.com/EdgeTX/edgetx
- **Package Repository Format**: See Manifest.md for GitHub repo structure
- **JSON Schema Draft**: https://json-schema.org/draft/2020-12/schema

## AI Agent Workflow

### For Future Sessions

1. **Start by reading**:
   - This AGENT.md file
   - Current Status section above
   - Any open issues or PRs

2. **For specification fixes**:
   - Read the relevant docs/ files
   - Make changes that address issues comprehensively
   - Update examples to match
   - Run conformance tests if schema changed
   - Update AGENT.md Current Status section

3. **For new features**:
   - Update Manifest.md with field definitions
   - Update Implementation.md with algorithms
   - Update State.md if persistence is needed
   - Add examples to GettingStarted.md
   - Consider schema changes (but note limitations)
   - Add conformance test cases
   - Update this AGENT.md

4. **Before completing work**:
   - Check cross-references between documents
   - Verify terminology consistency
   - Update Current Status section
   - Document any remaining known issues

## Contact

For questions about this specification, see CONTRIBUTING.md or open an issue in the repository.

---

**Last Updated**: 2026-08-23
**Last Major Review**: Third review cycle complete, ~5 issues remaining
