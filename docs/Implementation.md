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

check_spec_version(manifest.spec_version)

if manifest.has_variants():
    if user_specified_variant:
        selected_variant = find_variant_by_path(manifest, user_variant)
        manifest = load_variant_manifest(selected_variant, manifest)
    else if radio_capabilities_available:
        selected_variant = auto_select_best_variant(manifest, radio)
        manifest = load_variant_manifest(selected_variant, manifest)
    else:
        error("could not detect radio, must specify --path")

check_version_compatibility(
    manifest.min_edgetx_version,
    manifest.max_edgetx_version,
    running_edgetx_version
)
check_capabilities_compatibility(manifest.capabilities, radio_capabilities)

# Validate local dependencies: all depends[] entries must reference
# a library declared in this package's libraries section
validate_local_dependencies(manifest)

# Stage files and check conflicts at file level (not just directory level)
check_conflicts_before_install(manifest, package.id, sd_root)

stage_files_locally(manifest, manifest_dir)
if compilation_needed:
    compile_lua_files()

copy_staged_files_to_sd()

record_installed_state(installed.yml, package)
record_file_ownership(files.yml, package)
```

---

## Update Operation

Pseudocode for `pkg update <package>`:

```
old_package = find_installed_package(query)
resolve_new_version(old_package) → new_manifest, new_version

check_spec_version(new_manifest.spec_version)

# CRITICAL: Verify package identity to prevent substitution attacks
if new_manifest.package.id != old_package.id:
    error("Package identity mismatch: cannot update " + old_package.id + 
          " with manifest for " + new_manifest.package.id)

# Verify repository and manifest path match if available
if old_package.source.repo != resolve_repository(new_manifest):
    error("Repository mismatch: refusing to update from different source")

if new_version == old_version:
    return status=up_to_date

if old_package.variant:
    reuse_variant = old_package.variant
    if variant_still_exists(new_manifest, reuse_variant):
        selected_variant = find_variant_by_path(new_manifest, reuse_variant)
        new_manifest = load_variant_manifest(selected_variant, new_manifest)
    else:
        error("variant no longer exists in new version, reinstall to switch")
else if new_manifest.has_variants():
    selected_variant = auto_select_best_variant(new_manifest, radio)
    new_manifest = load_variant_manifest(selected_variant, new_manifest)

check_version_compatibility(
    new_manifest.min_edgetx_version,
    new_manifest.max_edgetx_version,
    running_edgetx_version
)
check_capabilities_compatibility(new_manifest.capabilities, radio_capabilities)

# NON-DESTRUCTIVE UPDATE: stage first, then atomically replace
staging_dir = stage_files_locally(new_manifest, manifest_dir)
if compilation_needed:
    compile_lua_files(staging_dir)

# Verify all files staged successfully and check for conflicts
# (exclude old_package.id since we're replacing it)
verify_staging_complete(staging_dir, new_manifest)
check_conflicts_before_install(new_manifest, old_package.id, sd_root)

# Create backup of old package state for potential rollback
backup_dir = create_backup_dir()
old_files = load_tracked_files_for_package(old_package.id)
for each file in old_files:
    validated_path = normalize_and_validate_path(file.path, sd_root)
    backup_file(sd_root + validated_path, backup_dir)
backup_state_files(backup_dir, installed.yml, files.yml)

# Build list of new file destinations for cleanup on rollback
new_file_list = build_destination_file_list(staging_dir, new_manifest)

try:
    # Remove old files
    remove_old_package_files(old_package)
    
    # Install new files
    copy_staged_files_to_sd(staging_dir, sd_root)
    
    # Update state files atomically
    update_installed_state_atomic(installed.yml, old_package, new_manifest)
    update_file_ownership_atomic(files.yml, old_package.id, new_manifest)
    
    # Commit successful - remove backup
    remove_backup_dir(backup_dir)
    
catch error:
    # Rollback on failure: remove newly created files, restore old files and state
    warn("update failed: " + error + ", rolling back")
    for each new_file in new_file_list:
        if file_exists(sd_root / new_file) and new_file not in old_files:
            delete_file(sd_root / new_file)
    restore_from_backup(backup_dir, sd_root)
    restore_state_files(backup_dir, installed.yml, files.yml)
    throw error
finally:
    cleanup_staging_dir(staging_dir)
```

**Key constraints:**
- `pkg update` always keeps the currently-installed variant. To switch variants, the user must run `pkg install` explicitly.
- Updates are non-destructive: new files are staged and verified before any SD card modifications.
- If an update fails, the old package is restored from backup.
- State files should be written atomically (write to temp file, then rename).

**Interrupted operation recovery:**
- If tooling crashes during update, the backup directory remains in place
- On next startup, tooling should detect incomplete updates and offer to:
  1. Complete the update (if new files are intact), or
  2. Roll back to the backup (if update was interrupted)

---

## Remove Operation

Pseudocode for `pkg remove <package>`:

```
package = find_installed_package(query)
file_list = load_tracked_files_for_package(package.id)   # from files.yml

for each file in file_list:
    # CRITICAL: validate every path loaded from state to prevent path traversal
    validated_path = normalize_and_validate_path(file.path, sd_root)
    full_path = sd_root + validated_path
    
    # Verify file integrity before deletion to protect user modifications
    if file.sha256 is present and file_exists(full_path):
        current_hash = compute_sha256(full_path)
        if current_hash != file.sha256:
            warn("File modified by user, skipping: " + validated_path)
            continue
    
    delete_file(full_path)
    delete_luac_companion_if_untracked(validated_path + "c")

for each directory in file_list (deepest first):
    validated_dir = normalize_and_validate_path(directory, sd_root)
    remove_empty_tree_bottom_up(sd_root + validated_dir)

remove_package_from_installed_state(package.id)
remove_tracked_file_entries(files.yml, package.id)
```

---

## Package Resolution

```
resolve_package_ref(pkg_ref) → (manifest, manifest_dir, metadata):
    # pkg_ref may be:
    #   github.com/owner/repo[@ref][::variant_path]
    #   owner/repo (GitHub shorthand — expanded to github.com/owner/repo)

    (repo_id, ref, variant_override) = parse_pkg_ref(pkg_ref)
    clone_url = "https://" + repo_id + ".git"

    fetch_or_update_local_cache(clone_url, ref)
    manifest_dir = resolve_manifest_dir(repo_id, ref)

    # subpackage: try subdirectory form first, then flat-file fallback
    manifest_path = find_manifest_file(manifest_dir, repo_id)

    manifest = parse_yaml(manifest_path)
    metadata = { clone_url, ref, manifest_path }
    return (manifest, manifest_dir, metadata)


find_manifest_file(manifest_dir, repo_id) → path:
    subpath = extract_subpath(repo_id)         # segments after host/owner/repo
    if subpath:
        candidate = manifest_dir / subpath / "edgetx.yml"
        if exists(candidate): return candidate
        # flat-file fallback: a/b → edgetx.a.b.yml
        flat_name = "edgetx." + subpath.replace("/", ".") + ".yml"
        candidate = manifest_dir / flat_name
        if exists(candidate): return candidate
        error("manifest not found for subpackage " + subpath)
    else:
        return manifest_dir / "edgetx.yml"
```

---

## Installed Package Lookup

```
find_installed_package(query) → package:
    # query may be a full id, GitHub shorthand, or display name
    state = load_state(installed.yml)

    # exact id match
    for each pkg in state.packages:
        if pkg.id == normalize_id(query):
            return pkg

    # partial suffix match (e.g. "log-viewer" matches "github.com/owner/repo/log-viewer")
    matches = [pkg for pkg in state.packages if pkg.id.ends_with("/" + query)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        error("ambiguous package query '" + query + "', be more specific")

    error("package not found: " + query)
```

---

## YAML Parsing Security

**CRITICAL security requirement**: All YAML parsing of untrusted manifests (from remote repositories or user-provided files) must use a safe parser configuration.

```
parse_yaml(file_path) → document:
    # REQUIRED security properties:
    # 1. Reject YAML custom tags (!<tag> syntax) - prevents code execution
    # 2. Limit document size (e.g., max 1MB for manifests)
    # 3. Limit alias/anchor expansion depth and count to prevent DoS
    # 4. Only accept single-document YAML files (reject --- separators)
    # 5. Use safe loading mode that constructs only standard types
    
    content = read_file(file_path)
    if len(content) > MAX_MANIFEST_SIZE:  # e.g., 1MB
        error("manifest file too large: " + file_path)
    
    # Use language-specific safe YAML loader:
    # - Python: yaml.safe_load()
    # - Go: gopkg.in/yaml.v3 with KnownFields(true)
    # - Rust: serde_yaml with deny_unknown_fields
    # - C++: yaml-cpp with safe mode
    document = safe_yaml_parse(content)
    
    if document is None or not is_mapping(document):
        error("invalid YAML: " + file_path)
    
    return document
```

Apply these security requirements to:
- Base package manifests (`edgetx.yml`)
- Variant manifests
- State files (`installed.yml`, `files.yml`)

---

## Version Resolution

```
resolve_new_version(old_package) → (new_manifest, new_version):
    fetch_or_update_local_cache(old_package.source.repo)
    latest_ref = resolve_latest_ref(old_package.source.repo)
    new_manifest = load_manifest(old_package.source.repo, latest_ref,
                                 old_package.source.manifest_path)
    new_version = new_manifest.package.version
    return (new_manifest, new_version)
```

---

## Variant Lookup Helpers

```
find_variant_by_path(manifest, path) → variant:
    for each variant in manifest.variants:
        if variant.path == path:
            return variant
    error("variant '" + path + "' not declared in manifest")


variant_still_exists(manifest, path) → bool:
    for each variant in manifest.variants:
        if variant.path == path:
            return true
    return false


load_variant_manifest(variant, base_manifest) → merged_manifest:
    variant_doc = parse_yaml(variant.path)
    
    # Variant files must not declare their own variants
    if variant_doc.package.variants is present:
        error("variant manifest cannot itself declare variants: " + variant.path)
    
    # variant file inherits id from base; only content sections are overridden
    merged = base_manifest.copy()
    merged.tools     = variant_doc.tools     if present else []
    merged.widgets   = variant_doc.widgets   if present else []
    merged.libraries = variant_doc.libraries if present else []
    merged.telemetry = variant_doc.telemetry if present else []
    merged.functions = variant_doc.functions if present else []
    merged.mixes     = variant_doc.mixes     if present else []
    merged.sounds    = variant_doc.sounds    if present else []
    merged.themes    = variant_doc.themes    if present else []
    
    if variant_doc.package.description is present:
        merged.package.description = variant_doc.package.description
    
    # CRITICAL: Merge base and variant capabilities as intersection/requirements
    # Both base and variant capability constraints must be satisfied
    if variant.capabilities is present:
        if merged.package.capabilities is present:
            # Merge capabilities: both base and variant constraints apply
            merged.package.capabilities = merge_capability_requirements(
                merged.package.capabilities,
                variant.capabilities
            )
        else:
            merged.package.capabilities = variant.capabilities
    
    return merged
```

**Capability merging rules:**
```
merge_capability_requirements(base_caps, variant_caps) → merged_caps:
    # Both base and variant requirements must be satisfied
    # For conflicting values, the intersection or stricter requirement applies
    merged = {}
    
    for each capability_key in union(base_caps.keys, variant_caps.keys):
        base_value = base_caps[capability_key]
        variant_value = variant_caps[capability_key]
        
        if base_value exists and variant_value exists:
            # Both specify the same capability
            if capability_key == "touch":
                # Boolean: both must be true, or both must be false/absent
                if base_value == true or variant_value == true:
                    merged[capability_key] = true
            else if capability_key == "display":
                # Nested object: merge recursively
                merged[capability_key] = merge_display_requirements(
                    base_value, variant_value
                )
            else:
                # For other capabilities, both must match or error
                if base_value != variant_value:
                    error("Conflicting capability: " + capability_key)
                merged[capability_key] = base_value
        else if base_value exists:
            merged[capability_key] = base_value
        else:
            merged[capability_key] = variant_value
    
    return merged
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

    # Tie-break: first matching variant in manifest declaration order
    return first_in_manifest_order(candidates).variant.path
```

`count_specified_fields` counts non-null fields in `capabilities` (recursively) so that a variant declaring `{type, resolution, touch}` scores higher than one declaring only `{type}`.

---

## Capabilities Matching

```
capabilities_match(filter, radio) → bool:
    # An omitted filter field is a wildcard — it matches anything.
    if filter is null or filter is empty:
        return true

    if filter.display:
        if filter.display.type is present:
            if filter.display.type != radio.display.type:
                return false
        if filter.display.resolution is present:
            if filter.display.resolution != radio.display.resolution:
                return false
        if filter.display.touch is present:
            # touch: true requires touchscreen, touch: false requires non-touch
            if filter.display.touch != radio.display.touch:
                return false

    return true
```

---

## Compatibility Checking

```
SUPPORTED_SPEC_VERSIONS = ["1.0"]

check_spec_version(manifest_spec_version):
    if manifest_spec_version is absent:
        warn("manifest has no spec_version — treating as pre-1.0 legacy manifest")
        return   # continue with pre-1.0 compatible behaviour

    if manifest_spec_version not in SUPPORTED_SPEC_VERSIONS:
        warn("manifest targets spec version " + manifest_spec_version
             + " which this tooling does not fully understand (supports: "
             + SUPPORTED_SPEC_VERSIONS + "); proceeding with best-effort processing")
        # do not abort — process recognised fields and ignore unrecognised ones


check_version_compatibility(min_version, max_version, running_version):
    if min_version and not version_ge(running_version, min_version):
        error(EDGETX_VERSION_TOO_LOW,
              "package requires EdgeTX >= " + min_version)
    if max_version and not version_le(running_version, max_version):
        error(EDGETX_VERSION_TOO_HIGH,
              "package requires EdgeTX <= " + max_version)


check_capabilities_compatibility(manifest_capabilities, radio_capabilities):
    if manifest_capabilities is null:
        return   # no capability requirement declared

    if manifest_capabilities.display:
        cap = manifest_capabilities.display
        if cap.type and cap.type != radio_capabilities.display.type:
            error(CAPABILITY_MISMATCH,
                  "requires display type " + cap.type
                  + ", radio has " + radio_capabilities.display.type)
        if cap.resolution and cap.resolution != radio_capabilities.display.resolution:
            error(CAPABILITY_MISMATCH,
                  "requires display resolution " + cap.resolution
                  + ", radio has " + radio_capabilities.display.resolution)
        if cap.touch is present:
            # touch: true requires touchscreen, touch: false requires non-touch
            if cap.touch != radio_capabilities.display.touch:
                expected = "touchscreen" if cap.touch else "non-touch"
                actual = "touchscreen" if radio_capabilities.display.touch else "non-touch"
                error(CAPABILITY_MISMATCH,
                      "requires " + expected + " display, radio has " + actual)
```

Version comparison uses semantic versioning rules. The `x` wildcard in `max_edgetx_version` (e.g. `"2.13.x"`) matches any patch level within that minor version.

`check_spec_version` must be called before all other compatibility checks. `spec_version` is a top-level field — not inside `package:` — because it describes the file format, not the package itself. Absence means the manifest predates the 1.0 release; tooling warns and applies pre-1.0 compatibility behaviour. An unknown future version should also produce a warning rather than a hard failure, so that older tooling degrades gracefully when encountering manifests written for newer spec versions.

---

## Local Library Dependency Validation

```
validate_local_dependencies(manifest, include_dev_items):
    # Verify all depends[] entries reference a library declared in this manifest
    # and that non-dev items don't depend on dev-only libraries
    declared_libs = {lib.name: lib.dev for lib in manifest.libraries}
    
    for each content_item in manifest.content_items():
        # Skip dev items if not installing with --dev
        if content_item.dev and not include_dev_items:
            continue
            
        if content_item.depends:
            for each dep_name in content_item.depends:
                if dep_name not in declared_libs:
                    error(DEPENDENCY_MISSING,
                          content_item.name + " depends on '" + dep_name
                          + "' but no library with that name is declared in this package")
                
                # Prevent non-dev items from depending on dev-only libraries
                if not content_item.dev and declared_libs[dep_name]:
                    error(DEPENDENCY_INVALID,
                          "non-dev item '" + content_item.name
                          + "' cannot depend on dev-only library '" + dep_name + "'")
```

Dependencies in the manifest are **local to the package** — the `depends` field references library entries declared in the same manifest's `libraries` section. All declared libraries and dependent content items (excluding those marked `dev: true` unless `--dev` is passed) are installed together as part of the package, with file ownership tracked per package.

---

## Path Security and Validation

**Critical implementation requirement**: All path operations must prevent directory traversal attacks and ensure files remain within the SD card root.

```
normalize_and_validate_path(path, root_dir) → validated_path:
    # 1. Reject absolute paths
    if is_absolute(path):
        error("absolute paths not allowed: " + path)
    
    # 2. Reject backslashes (use forward slash separator)
    if path contains "\\":
        error("backslash separator not allowed: " + path)
    
    # 3. Normalize the path (resolve ., .., empty segments)
    normalized = normalize_path(path)
    
    # 4. Ensure normalized path does not escape root (lexical check)
    if normalized contains ".." or starts_with("/"):
        error("path escapes root directory: " + path)
    
    # 5. CRITICAL: For destination paths, verify EVERY path component to prevent
    #    symlink bypass. Check parent directories before creating children.
    #    This prevents TOCTOU races and symlinked-parent escapes.
    full_path = join_paths(root_dir, normalized)
    
    # Verify each existing component in the path from root to target
    current = root_dir
    for component in split_path_components(normalized):
        current = join_paths(current, component)
        if path_exists(current):
            canonical = canonicalize_path(current)
            if not is_within_directory(canonical, canonicalize_path(root_dir)):
                error("path escapes root via symlink: " + path)
    
    return normalized


is_within_directory(path, root) → bool:
    # After canonicalization, verify the absolute path is within root
    # Use path component comparison, not string prefix, to avoid false positives
    return path == root or path.starts_with(root + "/")
```

**Symlink handling policy:**
- **Source paths**: Symlinks in package source trees (local git clones) are followed during copy staging
- **Destination paths**: Before writing to SD card, verify each path component from root to target to prevent escapes via symlinked parent directories. Check symlinks BEFORE creating child paths, not after.
- **Recommendation**: For maximum security on non-FAT filesystems (dev/test environments), use descriptor-based file operations with `O_NOFOLLOW` and `openat`-style APIs to traverse directories safely

Apply this validation to:
- All `path` and `dest` fields in content items before file operations
- `source_dir` in package metadata
- Variant manifest `path` values
- Any user-provided path arguments
- **CRITICAL**: All paths loaded from state files (`files.yml`) before backup, deletion, or restore operations

---

## File Conflict Detection

**Implementation requirement**: Conflict detection must check every individual destination file, not just top-level content item destinations.

```
check_conflicts_before_install(manifest, current_package_id, sd_root):
    # Build complete inventory of destination files after staging
    staging_dir = stage_files_locally(manifest, manifest_dir)
    dest_files = []
    
    for each content_item in manifest.content_items():
        dest_rel = content_item.dest if present else content_item.path
        staged_path = staging_dir / dest_rel
        
        # Walk the staged tree to get all individual files
        for each file in walk(staged_path):
            dest_file_path = dest_rel / relative_path(file, staged_path)
            dest_files.append(dest_file_path)
    
    # Check for duplicates within this package
    if dest_files has duplicates:
        error(FILE_CONFLICT,
              "package maps multiple source items to the same destination: "
              + duplicate_paths)
    
    # Check ownership of each destination file
    # CRITICAL: Cross-package overwrites are NOT ALLOWED to prevent
    # inconsistent ownership and deletion risks
    for each dest_path in dest_files:
        owner = find_owner_in_files_yml(dest_path)
        if owner and owner.id != current_package_id:
            error(FILE_CONFLICT,
                  "file conflict: " + dest_path +
                  " is already owned by " + owner.id +
                  ". Remove that package first or use a different variant.")
        
        # Check for untracked files that would be overwritten
        if file_exists(sd_root / dest_path) and not owner:
            warn("would overwrite untracked file: " + dest_path)
            if not user_confirmed_overwrite():
                error(FILE_CONFLICT,
                      "aborting install due to untracked file: " + dest_path)
```

In non-interactive mode (e.g. CI pipelines or AI-agent usage), treat absence of user confirmation as implicit rejection and abort.

---

## File Staging and Copy

```
stage_files_locally(manifest, manifest_dir) → staging_dir:
    staging_dir = create_temp_dir()
    
    # Determine source root based on source_dir
    if manifest.package.source_dir is present:
        source_root = manifest_dir / manifest.package.source_dir
        validate_path(manifest.package.source_dir, manifest_dir)
    else:
        source_root = manifest_dir

    for each content_item in manifest.content_items():
        # Try source_root first, then fall back to manifest_dir
        src = first_existing(source_root / content_item.path,
                             manifest_dir  / content_item.path)
        if src does not exist:
            error("source path not found: " + content_item.path)

        dest_rel = content_item.dest if present else content_item.path
        copy_tree(src, staging_dir / dest_rel,
                  exclude=content_item.exclude,
                  skip_luac=(not manifest.package.binary))

    return staging_dir


copy_staged_files_to_sd(staging_dir, sd_root):
    for each file in walk(staging_dir):
        dest = sd_root / relative_path(file, staging_dir)
        ensure_parent_dirs(dest)
        copy_file(file, dest)
        compute_sha256(file)   # stored in files.yml during record_file_ownership


delete_luac_companion_if_untracked(luac_path):
    # When a .lua file is removed, also delete the matching .luac if it exists
    # on the SD card but is NOT tracked in files.yml (i.e. was compiled in place).
    if file_exists(sd_root + luac_path) and not tracked_in_files_yml(luac_path):
        delete_file(sd_root + luac_path)


remove_empty_tree_bottom_up(directory):
    # Walk upward from directory, removing each level that is now empty,
    # stopping at sd_root or the first non-empty directory.
    current = directory
    while current != sd_root and is_empty_dir(current):
        remove_dir(current)
        current = parent(current)
```

---

## State Recording

```
record_installed_state(installed_yml, package, resolved_libs):
    entry = {
        id:           package.id,
        version:      package.version,
        variant:      selected_variant_path or null,
        installed_at: now_utc(),
        source: {
            repo:          package.source.repo,
            ref:           package.source.ref,
            manifest_path: package.source.manifest_path,
        },
        constraints: {
            min_edgetx_version: manifest.min_edgetx_version or null,
            max_edgetx_version: manifest.max_edgetx_version or null,
            capabilities:       manifest.capabilities or null,
        },
        status: {
            compatible:   true,
            code:         "OK",
            reason:       "",
        },
        last_checked_at: now_utc(),
    }
    state.packages.append(entry)
    write_yaml(installed_yml, state)


record_file_ownership(files_yml, package, staged_files):
    for each file in staged_files:
        entry = {
            path:          sd_relative_path(file),
            owner_id:      package.id,
            owner_version: package.version,
            owner_variant: selected_variant_path or null,
            sha256:        sha256_of(file),
        }
        state.files.append(entry)
    write_yaml(files_yml, state)


update_installed_state(installed_yml, old_package, new_manifest):
    # Replace the existing entry for old_package.id in-place.
    entry = find_entry(installed_yml, old_package.id)
    entry.version      = new_manifest.package.version
    entry.variant      = selected_variant_path or null
    entry.source.ref   = new_manifest.source.ref
    entry.constraints  = extract_constraints(new_manifest)
    entry.status       = { compatible: true, code: "OK", reason: "" }
    entry.last_checked_at = now_utc()
    write_yaml(installed_yml, state)


update_file_ownership(files_yml, old_package_id, new_manifest):
    # Remove all old entries for old_package_id, then add new ones.
    state.files = [f for f in state.files if f.owner_id != old_package_id]
    record_file_ownership(files_yml, new_manifest, newly_staged_files)


load_tracked_files_for_package(package_id) → file_list:
    state = load_yaml(files_yml)
    return [f for f in state.files if f.owner_id == package_id]


remove_package_from_installed_state(package_id):
    state.packages = [p for p in state.packages if p.id != package_id]
    write_yaml(installed_yml, state)


remove_tracked_file_entries(files_yml, package_id):
    state.files = [f for f in state.files if f.owner_id != package_id]
    write_yaml(files_yml, state)
```

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

**Note**: Local libraries declared in a package's manifest are installed as regular files owned by that package. They are tracked in `files.yml` like any other content and removed when the owning package is removed.

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
