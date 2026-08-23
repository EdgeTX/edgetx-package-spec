# Implementation Guide

This document provides implementation guidance for package manager authors targeting the EdgeTX package specification. It describes the algorithms, state transitions, and edge cases that conforming tooling must handle.

For the normative manifest format see [Manifest.md](./Manifest.md).
For the normative state file format see [State.md](./State.md).

---

## Overview

A conforming package manager implements three core operations against a connected radio SD card:

- **install** — fetch a package, resolve its variant, check compatibility, copy files to the SD card, and record state.
- **update** — fetch a newer version of an installed package, preserve the selected variant, replace files, and update state.
- **remove** — delete all tracked files for a package, clean up orphaned libraries, and remove state records.

All three operations share common sub-routines for variant resolution, compatibility checking, conflict detection, library dependency management, and state persistence.

---

## Install Operation

Pseudocode for `pkg install <pkg_ref>`:

```
resolve_package_ref(pkg_ref) → (manifest, manifest_dir, metadata)

if manifest.has_variants():
    if user_specified_variant:
        selected_variant = find_variant_by_path(manifest, user_variant)
    else if radio_capabilities_available:
        selected_variant = auto_select_best_variant(manifest, radio)
    else:
        error("could not detect radio, must specify --path")
    load_variant_manifest(selected_variant)

check_version_compatibility(
    manifest.min_edgetx_version,
    manifest.max_edgetx_version,
    running_edgetx_version
)
check_capabilities_compatibility(manifest.capabilities, radio_capabilities)

for each content_item in manifest.content_items():
    check_file_not_owned_by_other_package(content_item.dest)

resolved_libs = resolve_library_dependencies(manifest, state)

stage_files_locally(manifest, manifest_dir)
if compilation_needed:
    compile_lua_files()

copy_staged_files_to_sd()

record_installed_state(installed.yml):
    - id, version, variant, source, constraints, status=OK, resolved_libs
record_file_ownership(files.yml):
    - each installed file with owner_id, owner_version, owner_variant, sha256
```

---

## Update Operation

Pseudocode for `pkg update <package>`:

```
old_package = find_installed_package(query)
resolve_new_version(old_package) → new_manifest, new_version

if new_version == old_version:
    return status=up_to_date

if old_package.variant:
    reuse_variant = old_package.variant
    if variant_still_exists(new_manifest, reuse_variant):
        load_variant_manifest(reuse_variant)
    else:
        error("variant no longer exists in new version, reinstall to switch")
else:
    auto_select_best_variant(new_manifest, radio)

check_version_compatibility(new_manifest)
check_capabilities_compatibility(new_manifest, radio_capabilities)
check_file_not_owned_by_other_package(skip_id=old_package.id)

remove_old_package_files(old_package)       # see Remove Operation
install_new_package_files(new_manifest)     # see Install Operation

update_installed_state(installed.yml)       # overwrite existing record
update_file_ownership(files.yml)            # replace old file entries

cleanup_unreferenced_libraries(state)
```

**Key constraint:** `pkg update` always keeps the currently-installed variant. To switch variants, the user must run `pkg install` explicitly.

---

## Remove Operation

Pseudocode for `pkg remove <package>`:

```
package = find_installed_package(query)
file_list = load_tracked_files_for_package(package.id)   # from files.yml

for each file in file_list:
    delete_file(sd_root + file.path)
    delete_luac_companion_if_untracked(file.path + "c")

for each directory in file_list (deepest first):
    remove_empty_tree_bottom_up(directory)

for each lib in package.resolved_libs:
    remove_package_from_lib_requested_by(lib.id, lib.version, package.id)
    if lib.requested_by is now empty:
        delete_library_files(lib.path)
        remove_lib_from_state(lib.id, lib.version)

remove_package_from_installed_state(package.id)
remove_tracked_file_entries(files.yml, package.id)
```

---

## Variant Selection Algorithm

```
auto_select_best_variant(manifest, radio_capabilities) → variant_path:
    matching_variants = []
    for each variant in manifest.variants:
        if capabilities_match(variant.capabilities, radio_capabilities):
            specificity = count_specified_fields(variant.capabilities)
            matching_variants.push({ variant, specificity })

    if matching_variants is empty:
        error("no matching variant for radio capabilities")

    max_specificity = max(matching_variants, key=specificity)
    candidates = filter(matching_variants, specificity == max_specificity)

    if len(candidates) == 1:
        return candidates[0].variant.path

    # Tie-break: lexically first path in manifest order
    return first_in_manifest_order(candidates).variant.path
```

`capabilities_match(filter, radio)` returns true if every field declared in `filter` matches the corresponding field in `radio`. Omitted filter fields are treated as wildcards.

`count_specified_fields` counts non-null fields in `capabilities` (recursively) so that a variant declaring `{type, resolution, touch}` scores higher than one declaring only `{type}`.

---

## Compatibility Checking

```
check_version_compatibility(min_version, max_version, running_version):
    if min_version and not version_ge(running_version, min_version):
        error(EDGETX_VERSION_TOO_LOW,
              "package requires EdgeTX >= " + min_version)
    if max_version and not version_le(running_version, max_version):
        error(EDGETX_VERSION_TOO_HIGH,
              "package requires EdgeTX <= " + max_version)


check_capabilities_compatibility(manifest_capabilities, radio_capabilities):
    if manifest_capabilities.display:
        cap = manifest_capabilities.display
        if cap.type and cap.type != radio_capabilities.display.type:
            error(CAPABILITY_MISMATCH,
                  "requires display type " + cap.type)
        if cap.resolution and cap.resolution != radio_capabilities.display.resolution:
            error(CAPABILITY_MISMATCH,
                  "requires display resolution " + cap.resolution)
        if cap.touch and not radio_capabilities.display.touch:
            error(CAPABILITY_MISMATCH,
                  "requires touchscreen display")
```

Version comparison uses semantic versioning rules. The `x` wildcard in `max_edgetx_version` (e.g. `"2.13.x"`) matches any patch level within that minor version.

---

## Library Dependency Resolution

```
resolve_library_dependencies(package, state) → resolved_libs:
    resolved_libs = []
    for each lib_dep in package.dependencies.libraries:
        installed_versions = find_installed_lib_versions(state, lib_dep.id)

        matching_versions = filter_by_semver_constraint(
            installed_versions, lib_dep.constraint
        )
        if matching_versions is not empty:
            chosen = max_by_semver(matching_versions)
        else:
            chosen = install_library(lib_dep.id, lib_dep.constraint)

        resolved_libs.push({
            id:               lib_dep.id,
            constraint:       lib_dep.constraint,
            resolved_version: chosen.version,
            path:             chosen.path
        })

        add_to_lib_requested_by(
            state, lib_dep.id, chosen.version,
            package.id, package.version
        )

    return resolved_libs
```

---

## Library Cleanup

```
cleanup_unreferenced_libraries(state):
    for each lib in state.libraries:
        if lib.requested_by is empty:
            delete_files(lib.path)
            remove_from_state(state, lib.id, lib.version)
```

This routine is called at the end of both `update` and `remove` to remove library versions that no longer have any dependent packages.

---

## File Conflict Detection

```
check_file_not_owned_by_other_package(dest_path, current_package_id):
    owner = find_owner_in_files_yml(dest_path)
    if owner and owner.id != current_package_id:
        warn("file conflict: " + dest_path
             + " is already owned by " + owner.id)
        if not user_confirmed_overwrite():
            error(FILE_CONFLICT,
                  "aborting install due to file conflict on " + dest_path)
```

In non-interactive mode (e.g. CI pipelines or AI-agent usage), treat absence of user confirmation as implicit rejection and abort.

---

## State File Format Examples

All examples reference the state schema defined in [State.md](./State.md).

### Fresh install — single package, no variants

```yaml
# EDGETX/PKG/state/installed.yml
schema_version: 1
packages:
  - id: github.com/acme/simple-tool
    version: "1.0.0"
    variant: null
    installed_at: "2026-08-23T12:00:00Z"
    source:
      repo: github.com/acme/simple-tool
      ref: "v1.0.0"
      manifest_path: "edgetx.yml"
    constraints:
      min_edgetx_version: "2.11.0"
      max_edgetx_version: null
      capabilities: null
    status:
      compatible: true
      code: "OK"
      reason: ""
    last_checked_at: "2026-08-23T12:00:05Z"
```

```yaml
# EDGETX/PKG/state/files.yml
schema_version: 1
files:
  - path: "SCRIPTS/TOOLS/simple-tool.lua"
    owner_id: "github.com/acme/simple-tool"
    owner_version: "1.0.0"
    owner_variant: null
    sha256: "a1b2c3d4..."
```

---

### Package with variant persisted

```yaml
# EDGETX/PKG/state/installed.yml (excerpt)
packages:
  - id: github.com/yaapu/FrskyTelemetryScript
    version: "3.0.1"
    variant: "edgetx.color-touch.yml"
    installed_at: "2026-08-23T13:00:00Z"
    source:
      repo: github.com/yaapu/FrskyTelemetryScript
      ref: "v3.0.1"
      manifest_path: "edgetx.yml"
    constraints:
      min_edgetx_version: "2.11.0"
      max_edgetx_version: null
      capabilities:
        display:
          type: colorlcd
          touch: true
    status:
      compatible: true
      code: "OK"
      reason: ""
    last_checked_at: "2026-08-23T13:00:10Z"
```

---

### Library reverse-dependency tracking

```yaml
# EDGETX/PKG/state/installed.yml (excerpt)
schema_version: 1
libraries:
  - lib_id: github.com/edgetx/lib-json
    version: "2.1.3"
    path: SCRIPTS/LIBS/pkg/edgetx.json/2.1.3
    requested_by:
      - package_id: github.com/acme/tool-a
        package_version: "1.0.0"
      - package_id: github.com/acme/tool-b
        package_version: "3.2.0"

package_deps:
  - package_id: github.com/acme/tool-a
    package_version: "1.0.0"
    libs:
      - lib_id: github.com/edgetx/lib-json
        constraint: "^2.1.0"
        resolved_version: "2.1.3"
  - package_id: github.com/acme/tool-b
    package_version: "3.2.0"
    libs:
      - lib_id: github.com/edgetx/lib-json
        constraint: "^2.0.0"
        resolved_version: "2.1.3"
```

---

### Multiple packages and shared libraries

After installing `tool-a` and `tool-b` both depending on `lib-json`:

```yaml
schema_version: 1
packages:
  - id: github.com/acme/tool-a
    version: "1.0.0"
    variant: null
    # ...
  - id: github.com/acme/tool-b
    version: "3.2.0"
    variant: null
    # ...
libraries:
  - lib_id: github.com/edgetx/lib-json
    version: "2.1.3"
    path: SCRIPTS/LIBS/pkg/edgetx.json/2.1.3
    requested_by:
      - package_id: github.com/acme/tool-a
        package_version: "1.0.0"
      - package_id: github.com/acme/tool-b
        package_version: "3.2.0"
```

After removing `tool-a`:

```yaml
libraries:
  - lib_id: github.com/edgetx/lib-json
    version: "2.1.3"
    path: SCRIPTS/LIBS/pkg/edgetx.json/2.1.3
    requested_by:
      - package_id: github.com/acme/tool-b
        package_version: "3.2.0"
```

After removing `tool-b`, the library's `requested_by` becomes empty, so the library files are deleted and the library entry is removed from state.

---

### Incompatible package after firmware update

When a firmware downgrade makes a previously-compatible package incompatible:

```yaml
packages:
  - id: github.com/acme/new-widget
    version: "2.0.0"
    variant: "edgetx.color.yml"
    installed_at: "2026-08-23T14:00:00Z"
    source:
      repo: github.com/acme/new-widget
      ref: "v2.0.0"
      manifest_path: "edgetx.yml"
    constraints:
      min_edgetx_version: "2.13.0"
      max_edgetx_version: null
      capabilities:
        display:
          type: colorlcd
    status:
      compatible: false
      code: "EDGETX_VERSION_TOO_LOW"
      reason: "installed firmware is 2.12.1, package requires >= 2.13.0"
    last_checked_at: "2026-08-23T15:00:00Z"
```

Tooling should re-evaluate `status` whenever firmware version changes and surface incompatible packages to the user.
