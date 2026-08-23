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

# CRITICAL: Validate base manifest requirements (see Manifest.md context-specific validation)
# Base manifests (loaded from root source) MUST have id and description
validate_base_manifest_fields(manifest)  # Ensure package.id and package.description are present

# CRITICAL: Check if package is already installed - treat as update/reinstall
existing_package = try_find_installed_package(manifest.package.id)
if existing_package:
    # Package already exists - use update path for safe replacement
    warn("Package " + manifest.package.id + " is already installed, performing update/reinstall")
    # Delegate to update operation: skip version check to allow reinstall
    return update_package_from_manifest(existing_package, manifest, manifest_dir)

if manifest.has_variants():
    if user_specified_variant:
        selected_variant = find_variant_by_path(manifest, user_variant)
        manifest = load_variant_manifest(selected_variant, manifest, manifest_dir)
    else if radio_capabilities_available:
        selected_variant = auto_select_best_variant(manifest, radio)
        manifest = load_variant_manifest(selected_variant, manifest, manifest_dir)
    else:
        error("could not detect radio, must specify --path")

check_version_compatibility(
    manifest.min_edgetx_version,
    manifest.max_edgetx_version,
    running_edgetx_version
)
check_capabilities_compatibility(manifest.capabilities, radio_capabilities)

# CRITICAL: Determine install mode - production (default) or dev mode
# Dev items (marked dev: true) are excluded in production mode
include_dev_items = command_has_flag("--dev")

# Validate local dependencies: all depends[] entries must reference
# a library declared in this package's libraries section
validate_local_dependencies(manifest, include_dev_items)

# Stage files locally for validation and hash computation
staging_dir = stage_files_locally(manifest, manifest_dir, include_dev_items)

# Check conflicts using the staged file inventory
check_conflicts_before_install(manifest, manifest.package.id, sd_root, include_dev_items, staging_dir)

# Compile if needed (modifies staging_dir in place)
if compilation_needed:
    compile_lua_files(staging_dir)

# BEGIN TRANSACTION for crash-safe install
staged_file_list = build_staged_file_list(staging_dir)
new_state = prepare_new_state(manifest.package, selected_variant, include_dev_items, staged_file_list)
transaction = begin_transaction("install", manifest.package.id, old_state=null, staged_file_list, new_state)

# CRITICAL: Detect and remove any existing untracked .luac companions
# These could shadow newly installed .lua files with stale compiled code
luac_to_remove = []
for each staged_file in staged_file_list:
    if staged_file.path.ends_with(".lua"):
        luac_path = staged_file.path + "c"
        # Only remove if untracked (tracked .luac is replaced by package install)
        if not tracked_in_files_yml(luac_path) and file_exists(sd_root + luac_path):
            luac_to_remove.append(luac_path)

# Backup any untracked files that will be overwritten (already confirmed with user)
untracked_overwrites = find_untracked_files_to_overwrite(staged_file_list, files.yml, sd_root)
all_files_to_backup = untracked_overwrites + luac_to_remove
backup_existing_files(transaction, all_files_to_backup, sd_root)

# Delete untracked .luac companions before installing new .lua files
for each luac_path in luac_to_remove:
    full_path = sd_root + luac_path
    if file_exists(full_path):
        delete_file(full_path)
        fsync(parent_directory(full_path))

# Copy staged files to SD card
copy_staged_files_to_sd(staging_dir, sd_root)

# CRITICAL: Ensure all file writes are durable before committing transaction
# This ensures recovery can trust committed transactions have complete data
fsync_all_staged_files(sd_root, staged_file_list)

# COMMIT transaction before finalizing state
commit_transaction(transaction)

# Finalize state and clean up transaction
finalize_transaction(transaction, installed.yml, files.yml)
```

---

## Update Operation

Pseudocode for `pkg update <package>`:

```
update_package_from_query(query):
    old_package = find_installed_package(query)
    resolve_new_version(old_package) → new_manifest, manifest_dir, new_version
    return update_package_from_manifest(old_package, new_manifest, manifest_dir)

update_package_from_manifest(old_package, new_manifest, manifest_dir):
    # This helper is used by both update and reinstall paths
    
    check_spec_version(new_manifest.spec_version)
    
    # CRITICAL: Validate base manifest requirements (see Manifest.md context-specific validation)
    # Base manifests (loaded from root source) MUST have id and description
    validate_base_manifest_fields(new_manifest)  # Ensure package.id and package.description are present
    
    # CRITICAL: Verify package identity to prevent substitution attacks
    if new_manifest.package.id != old_package.id:
        error("Package identity mismatch: cannot update " + old_package.id + 
              " with manifest for " + new_manifest.package.id)
    
    # Verify repository and manifest path match if available
    if old_package.source.repo != resolve_repository(new_manifest):
        error("Repository mismatch: refusing to update from different source")
    
    new_version = new_manifest.package.version
    if new_version == old_package.version and not command_has_flag("--force"):
        return status=up_to_date
    
    # Initialize selected_variant for all paths
    selected_variant = null

if old_package.variant:
    reuse_variant = old_package.variant
    if variant_still_exists(new_manifest, reuse_variant):
        selected_variant = find_variant_by_path(new_manifest, reuse_variant)
        new_manifest = load_variant_manifest(selected_variant, new_manifest, manifest_dir)
    else:
        error("variant no longer exists in new version, reinstall to switch")
else if new_manifest.has_variants():
    selected_variant = auto_select_best_variant(new_manifest, radio)
    new_manifest = load_variant_manifest(selected_variant, new_manifest, manifest_dir)

check_version_compatibility(
    new_manifest.min_edgetx_version,
    new_manifest.max_edgetx_version,
    running_edgetx_version
)
check_capabilities_compatibility(new_manifest.capabilities, radio_capabilities)

# CRITICAL: Preserve dev mode from the original install
# Updates maintain the same mode unless explicitly changed via --dev or --no-dev
if command_has_flag("--dev"):
    include_dev_items = true
else if command_has_flag("--no-dev"):
    include_dev_items = false
else:
    include_dev_items = (old_package.dev_mode if exists else false)

# Validate local dependencies with the same mode
validate_local_dependencies(new_manifest, include_dev_items)

# NON-DESTRUCTIVE UPDATE: stage first, then atomically replace
staging_dir = stage_files_locally(new_manifest, manifest_dir, include_dev_items)
if compilation_needed:
    compile_lua_files(staging_dir)

# Verify all files staged successfully and check for conflicts
# (exclude old_package.id since we're replacing it)
verify_staging_complete(staging_dir, new_manifest)
check_conflicts_before_install(new_manifest, old_package.id, sd_root, include_dev_items, staging_dir)

# Load old files and verify integrity before proceeding
old_files = load_tracked_files_for_package(old_package.id)

# CRITICAL: Verify file integrity before destructive operations
# Refuse to overwrite user-modified files
for each file in old_files:
    validated_path = normalize_and_validate_path(file.path, sd_root)
    full_path = sd_root + validated_path
    
    if not file_exists(full_path):
        continue  # file was deleted by user - warn but continue
    
    if file.sha256 is absent:
        error(FILE_MODIFIED,
              "cannot safely replace file without recorded integrity hash: " + validated_path +
              "; use --force to override")
    
    current_hash = compute_sha256(full_path)
    if current_hash != file.sha256:
        error(FILE_MODIFIED,
              "installed file was modified locally: " + validated_path +
              "; aborting update to protect user changes. " +
              "Backup the file, remove the package, and reinstall.")

# BEGIN TRANSACTION for crash-safe update
old_state = snapshot_package_state(installed.yml, files.yml, old_package.id)
staged_file_list = build_staged_file_list(staging_dir)
new_state = prepare_updated_state(old_package, new_manifest, selected_variant, include_dev_items, staged_file_list)
transaction = begin_transaction("update", old_package.id, old_state, staged_file_list, new_state)

# Backup all existing package files AND any untracked files that will be overwritten
old_file_paths = [f.path for f in old_files]

# CRITICAL: Collect ALL potential .luac companions before any deletions
# Must check both old tracked files AND new staged files to avoid orphaned .luac
luac_companions = []

# From old tracked files: .luac companions of existing .lua files
for each file in old_files:
    if file.path.ends_with(".lua"):
        luac_path = file.path + "c"
        if not tracked_in_files_yml(luac_path) and not in_list(luac_path, luac_companions):
            # Check if .luac exists on disk (may be missing if .lua was deleted manually)
            if file_exists(sd_root + luac_path):
                luac_companions.append(luac_path)

# From new staged files: .luac companions that may already exist on disk
for each staged_file in staged_file_list:
    if staged_file.path.ends_with(".lua"):
        luac_path = staged_file.path + "c"
        if not tracked_in_files_yml(luac_path) and not in_list(luac_path, luac_companions):
            # Check if .luac exists on disk (would shadow new .lua)
            if file_exists(sd_root + luac_path):
                luac_companions.append(luac_path)

# Find untracked files that would be overwritten by new staged files
untracked_overwrites = []
for each staged_file in staged_file_list:
    if file_exists(sd_root + staged_file.path):
        owner = find_owner_in_files_yml(staged_file.path)
        if not owner or owner.id == old_package.id:
            # Already in old_file_paths or unowned
            if not owner:
                untracked_overwrites.append(staged_file.path)
all_paths_to_backup = old_file_paths + luac_companions + untracked_overwrites
backup_existing_files(transaction, all_paths_to_backup, sd_root)

# Remove old files
deleted_directories = []
for each file in old_files:
    validated_path = normalize_and_validate_path(file.path, sd_root)
    full_path = sd_root + validated_path
    if file_exists(full_path):
        parent_dir = parent_directory(full_path)
        delete_file(full_path)
        # Track parent directories that need fsync after deletions
        if parent_dir not in deleted_directories:
            deleted_directories.append(parent_dir)

# Delete all collected .luac companions (already backed up)
for each luac_path in luac_companions:
    full_path = sd_root + luac_path
    if file_exists(full_path):
        parent_dir = parent_directory(full_path)
        delete_file(full_path)
        if parent_dir not in deleted_directories:
            deleted_directories.append(parent_dir)

# CRITICAL: Ensure deletions are durable (fsync parent directories)
for each dir in deleted_directories:
    fsync(dir)

# Install new files
copy_staged_files_to_sd(staging_dir, sd_root)

# CRITICAL: Ensure all file writes are durable before committing transaction
fsync_all_staged_files(sd_root, staged_file_list)

# COMMIT transaction before finalizing state
commit_transaction(transaction)

# Finalize state and clean up transaction
finalize_transaction(transaction, installed.yml, files.yml)

cleanup_staging_dir(staging_dir)
```

**Key constraints:**
- `pkg update` always keeps the currently-installed variant. To switch variants, the user must run `pkg install` explicitly.
- Updates are non-destructive: new files are staged and verified before any SD card modifications.
- File integrity is verified before any destructive operations - user modifications prevent the update.
- Transaction protocol ensures crash recovery: incomplete updates roll back automatically on next startup.

---

## Remove Operation

Pseudocode for `pkg remove <package>`:

```
package = find_installed_package(query)
file_list = load_tracked_files_for_package(package.id)   # from files.yml

# Verify file integrity and determine which files can be deleted
files_to_delete = []
modified_files = []

for each file in file_list:
    # CRITICAL: validate every path loaded from state to prevent path traversal
    validated_path = normalize_and_validate_path(file.path, sd_root)
    full_path = sd_root + validated_path
    
    if not file_exists(full_path):
        continue  # already deleted
    
    # Verify file integrity before deletion to protect user modifications
    if file.sha256 is present:
        current_hash = compute_sha256(full_path)
        if current_hash != file.sha256:
            warn("File modified by user, skipping: " + validated_path)
            modified_files.append(validated_path)
            continue
    
    files_to_delete.append(validated_path)

# BEGIN TRANSACTION for crash-safe removal
old_state = snapshot_package_state(installed.yml, files.yml, package.id)
new_state = prepare_removal_state(package.id, modified_files)
transaction = begin_transaction("remove", package.id, old_state, staged_files=[], new_state)

# CRITICAL: Collect ALL untracked .luac companions before deletion
# Check every .lua path from file_list (not just files_to_delete) to catch orphaned .luac
luac_companions = []
for each file in file_list:
    if file.path.ends_with(".lua"):
        luac_path = file.path + "c"
        if not tracked_in_files_yml(luac_path) and not in_list(luac_path, luac_companions):
            # Include if exists on disk, even if the .lua was manually deleted
            if file_exists(sd_root + luac_path):
                luac_companions.append(luac_path)

# Backup all files before deletion (in case rollback is needed)
all_paths_to_backup = files_to_delete + luac_companions
backup_existing_files(transaction, all_paths_to_backup, sd_root)

# Delete files
deleted_directories = []
for each validated_path in files_to_delete:
    full_path = sd_root + validated_path
    parent_dir = parent_directory(full_path)
    delete_file(full_path)
    delete_luac_companion_if_untracked(validated_path + "c")
    # Track parent directories that need fsync after deletions
    if parent_dir not in deleted_directories:
        deleted_directories.append(parent_dir)

# Remove empty directories (also tracking their parents for fsync)
directories_to_check = extract_directories_from_files(file_list)
for each directory in directories_to_check (deepest first):
    validated_dir = normalize_and_validate_path(directory, sd_root)
    if remove_empty_tree_bottom_up(sd_root + validated_dir):
        # Directory was removed, track its parent for fsync
        parent_dir = parent_directory(sd_root + validated_dir)
        if parent_dir not in deleted_directories:
            deleted_directories.append(parent_dir)

# CRITICAL: Ensure deletions are durable (fsync parent directories)
for each dir in deleted_directories:
    fsync(dir)

# COMMIT transaction before finalizing state
commit_transaction(transaction)

# Finalize state and clean up transaction
finalize_transaction(transaction, installed.yml, files.yml)

# If any modified files were skipped, inform the user
if modified_files is not empty:
    warn("Package removed, but " + len(modified_files) + 
         " modified files were preserved: " + join(modified_files, ", "))
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
    # query may be a full id or GitHub shorthand for suffix matching
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

**Note**: Display-name lookup is not supported because `package.name` (the display name) is not persisted in state files. Queries use package IDs or suffixes only.

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
    # 6. CRITICAL: Allow unknown fields for forward compatibility
    
    content = read_file(file_path)
    if len(content) > MAX_MANIFEST_SIZE:  # e.g., 1MB
        error("manifest file too large: " + file_path)
    
    # Use language-specific safe YAML loader that allows unknown fields:
    # - Python: yaml.safe_load() (allows unknown fields by default)
    # - Go: gopkg.in/yaml.v3 without KnownFields (allows unknown)
    # - Rust: serde_yaml without deny_unknown_fields
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

**Forward compatibility**: After parsing, validate known fields while preserving unknown fields. See "Compatibility Checking" section for handling unknown spec versions.

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

**Version and update semantics:**

- `package.version` is optional in manifests but recommended for managed updates
- When both old and new versions are absent or equal, update returns "up to date"
- **Limitation**: State records the git ref (branch/tag name) but not the resolved commit SHA
  - This means force-pushed tags/branches cannot be reliably detected or reproduced
  - Rollback provenance is weak without immutable revision tracking
  - **Recommended enhancement**: Persist resolved commit SHA alongside ref in `installed.yml`
  - This would enable: detecting when ref was force-pushed, reproducing exact installed state, and proper rollback support

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


load_variant_manifest(variant, base_manifest, manifest_dir) → merged_manifest:
    # CRITICAL: Resolve variant.path relative to base manifest directory
    # This ensures variants are contained within the package and prevents path traversal
    variant_full_path = resolve_path_relative_to(manifest_dir, variant.path)
    validate_path_is_within(variant_full_path, manifest_dir)
    
    variant_doc = parse_yaml(variant_full_path)
    
    # Variant files must not declare their own variants
    if variant_doc.package.variants is present:
        error("variant manifest cannot itself declare variants: " + variant.path)
    
    # CRITICAL: Reject variant manifests that contain base-only metadata
    # Variants should only provide content sections and optionally description
    forbidden_fields = ["id", "name", "version", "category", "authors", "urls", 
                        "screenshots", "keywords", "license", "source_dir", "binary",
                        "min_edgetx_version", "max_edgetx_version", "capabilities"]
    for field in forbidden_fields:
        if variant_doc.package[field] is present:
            error("variant manifest cannot override " + field + ": " + variant.path)
    
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

**Note on schema validation**: The current JSON schema (`edgetx-manifest.v1.json`) validates both base and variant manifests with the same structure. It does not enforce that base manifests require `id` and `description`, or that variant manifests must not contain base-only fields. Implementations must perform these checks at runtime. A future schema revision should provide separate schemas for base vs variant contexts.

**Capability merging rules:**
```
merge_capability_requirements(base_caps, variant_caps) → merged_caps:
    # Both base and variant requirements must be satisfied
    # Conflicting explicit values must be rejected
    merged = {}
    
    if base_caps.display exists or variant_caps.display exists:
        merged.display = merge_display_requirements(
            base_caps.display if exists else {},
            variant_caps.display if exists else {}
        )
    
    return merged


merge_display_requirements(base_display, variant_display) → merged_display:
    # Merge display capability constraints - both must be satisfied
    merged = {}
    
    # Display type: both must match if both are specified
    if base_display.type exists and variant_display.type exists:
        if base_display.type != variant_display.type:
            error("Conflicting display type: base requires " + base_display.type +
                  ", variant requires " + variant_display.type)
        merged.type = base_display.type
    else if base_display.type exists:
        merged.type = base_display.type
    else if variant_display.type exists:
        merged.type = variant_display.type
    
    # Display resolution: both must match if both are specified
    if base_display.resolution exists and variant_display.resolution exists:
        if base_display.resolution != variant_display.resolution:
            error("Conflicting display resolution: base requires " + 
                  base_display.resolution + ", variant requires " + 
                  variant_display.resolution)
        merged.resolution = base_display.resolution
    else if base_display.resolution exists:
        merged.resolution = base_display.resolution
    else if variant_display.resolution exists:
        merged.resolution = variant_display.resolution
    
    # Touch: check for explicit contradictions first, then handle matches
    base_touch = base_display.touch if exists else null
    variant_touch = variant_display.touch if exists else null
    
    # Check for explicit contradictions
    if base_touch == false and variant_touch == true:
        error("Conflicting touch requirement: base requires non-touch, variant requires touch")
    else if base_touch == true and variant_touch == false:
        error("Conflicting touch requirement: base requires touch, variant requires non-touch")
    # Handle non-contradictory cases
    else if base_touch == true or variant_touch == true:
        merged.touch = true
    else if base_touch == false and variant_touch == false:
        merged.touch = false
    # else: both null, no touch constraint
    
    return merged
```

---

## Variant Selection Algorithm

```
auto_select_best_variant(manifest, radio_capabilities) → variant:
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
        return candidates[0].variant

    # Tie-break: first matching variant in manifest declaration order
    return first_in_manifest_order(candidates).variant
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
- **Source paths**: Symlinks in package source trees (local git clones) must NOT be followed if they point outside the repository root. Verify canonical containment for every source file before copying.
- **Destination paths**: Use descriptor-based file operations with `O_NOFOLLOW` or equivalent platform API to prevent TOCTOU races. Check parent directories AND create child paths relative to verified directory descriptors.
- **CRITICAL requirement**: All file operations must use non-racy descriptor-relative APIs (e.g., `openat` with `O_NOFOLLOW` on POSIX, or equivalent). Lexical path pre-checks alone cannot prevent TOCTOU attacks.

Apply this validation to:
- All `path` and `dest` fields in content items before file operations
- `source_dir` in package metadata
- Variant manifest `path` values
- Any user-provided path arguments
- **CRITICAL**: All paths loaded from state files (`files.yml`) before backup, deletion, or restore operations

**Reserved namespace**: The `EDGETX/PKG/` directory is reserved for package manager internal use (state files, transaction records, backups). Reject any content destination path that begins with `EDGETX/PKG/` to prevent state corruption.

**Note on schema validation**: The current JSON schema (`edgetx-manifest.v1.json`) does not enforce all path security rules lexically. It permits absolute paths, backslashes, and `..` segments in path fields, and does not require `dest` when `path: .`. Implementations **must** apply the runtime checks above regardless of schema validation. Future schema revisions should add stricter lexical patterns where feasible, but full security validation (symlink resolution, containment checks) can only be performed at runtime.

---

## File Conflict Detection

**Implementation requirement**: Conflict detection must check every individual destination file, not just top-level content item destinations.

```
check_conflicts_before_install(manifest, current_package_id, sd_root, include_dev_items, staging_dir):
    # Use the provided staging directory to get complete file inventory
    dest_files = []
    
    for each content_item in manifest.content_items():
        # CRITICAL: Apply same dev filtering as staging
        if content_item.dev and not include_dev_items:
            continue
        
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
stage_files_locally(manifest, manifest_dir, include_dev_items) → staging_dir:
    staging_dir = create_temp_dir()
    
    # Determine source root based on source_dir
    if manifest.package.source_dir is present:
        source_root = manifest_dir / manifest.package.source_dir
        validate_path(manifest.package.source_dir, manifest_dir)
    else:
        source_root = manifest_dir

    for each content_item in manifest.content_items():
        # CRITICAL: Filter dev items based on install mode
        if content_item.dev and not include_dev_items:
            continue
        
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

## Transaction Execution and Crash Recovery

**CRITICAL implementation requirement**: All operations (install, update, remove) must follow the transaction protocol defined in [State.md](./State.md) to ensure crash safety and atomicity.

### Transaction Protocol

Every operation must execute atomically using the following transaction protocol:

```
begin_transaction(operation, package_id, old_state, staged_files, new_state) → transaction:
    # Generate unique transaction ID
    txn_id = generate_transaction_id()  # e.g., timestamp + random
    
    # Create transaction record
    transaction = {
        id: txn_id,
        operation: operation,              # "install", "update", or "remove"
        package_id: package_id,
        timestamp: now_utc(),
        old_state: old_state,             # snapshot from installed.yml and files.yml
        backup_files: [],                 # to be populated during backup phase
        staged_files: staged_files,       # files to copy/remove with hashes
        new_state: new_state,             # target state after completion
        committed: false,                 # commit marker - starts false
    }
    
    # Write transaction record atomically
    txn_path = "EDGETX/PKG/state/.txn-" + txn_id + ".yml"
    write_yaml_atomic(txn_path, transaction)
    
    return transaction


backup_existing_files(transaction, files_to_backup, sd_root):
    # CRITICAL: Complete all backups AND make them durable before any destructive operations
    backup_dir = "EDGETX/PKG/state/.backup-" + transaction.id + "/"
    ensure_directory_exists(backup_dir)
    
    for each file_path in files_to_backup:
        validated_path = normalize_and_validate_path(file_path, sd_root)
        source = sd_root + validated_path
        
        if file_exists(source):
            dest = backup_dir + validated_path
            ensure_parent_dirs(dest)
            copy_file(source, dest)
            # CRITICAL: Ensure backup file is durable
            fsync(dest)
            fsync(parent_directory(dest))
            
            hash = compute_sha256(source)
            
            transaction.backup_files.append({
                path: validated_path,
                sha256: hash,
            })
    
    # Write backup manifest with hashes for integrity verification
    backup_manifest = {
        transaction_id: transaction.id,
        files: transaction.backup_files,
    }
    write_yaml_atomic(backup_dir + "manifest.yml", backup_manifest)
    
    # CRITICAL: Ensure backup directory and all contents are durable
    fsync(backup_dir)
    
    # Update transaction record with backup manifest
    update_transaction_record(transaction)


commit_transaction(transaction):
    # CRITICAL: Only call this after ALL file operations are complete and durable
    # Committed transactions are assumed to have complete, valid data on disk
    # Recovery trusts committed=true and will not verify file integrity
    transaction.committed = true
    txn_path = "EDGETX/PKG/state/.txn-" + transaction.id + ".yml"
    write_yaml_atomic(txn_path, transaction)
    
    # Ensure durable write (fsync) before proceeding
    fsync(txn_path)


fsync_all_staged_files(sd_root, file_list):
    # CRITICAL: Ensure all copied files are durably written before commit
    # This prevents recovery from trusting partial file writes
    for each file_entry in file_list:
        file_path = sd_root + file_entry.path
        if file_exists(file_path):
            fsync(file_path)
            # Also fsync parent directory to ensure directory entry is durable
            fsync(parent_directory(file_path))


finalize_transaction(transaction, installed_yml, files_yml):
    # Apply new state atomically to installed.yml and files.yml
    apply_state_snapshot_atomically(installed_yml, files_yml, transaction.new_state)
    
    # Clean up transaction record and backups
    cleanup_transaction(transaction)


cleanup_transaction(transaction):
    # Remove transaction record and backup directory
    txn_path = "EDGETX/PKG/state/.txn-" + transaction.id + ".yml"
    backup_dir = "EDGETX/PKG/state/.backup-" + transaction.id + "/"
    
    delete_file(txn_path)
    if directory_exists(backup_dir):
        remove_directory_recursive(backup_dir)


write_yaml_atomic(file_path, data):
    # Write to temp file, then atomic rename
    temp_path = file_path + ".tmp"
    write_yaml(temp_path, data)
    fsync(temp_path)
    atomic_rename(temp_path, file_path)
    fsync(parent_directory(file_path))


apply_state_snapshot_atomically(installed_yml, files_yml, new_state):
    # CRITICAL: Update both state files as an atomic generation
    # new_state contains COMPLETE installed.yml and files.yml content (all packages/files)
    # Write both to temp files first, then rename both
    temp_installed = installed_yml + ".tmp"
    temp_files = files_yml + ".tmp"
    
    write_yaml(temp_installed, new_state.installed)
    fsync(temp_installed)
    write_yaml(temp_files, new_state.files)
    fsync(temp_files)
    
    # Sequential renames create a state generation
    # Recovery relies on transaction record (committed flag) to determine valid generation
    atomic_rename(temp_installed, installed_yml)
    atomic_rename(temp_files, files_yml)
    fsync(parent_directory(installed_yml))
```

### Transaction Recovery on Startup

On package manager startup, before any operations, check for incomplete transactions:

```
recover_incomplete_transactions():
    txn_files = list_files("EDGETX/PKG/state/.txn-*.yml")
    
    for each txn_file in txn_files:
        try:
            transaction = load_yaml(txn_file)
        catch parse_error:
            error("Transaction record corrupted: " + txn_file +
                  "; manual recovery required. Do not proceed.")
        
        if transaction.committed == true:
            # Transaction was committed - complete the operation
            log("Completing interrupted " + transaction.operation + 
                " for " + transaction.package_id)
            finalize_transaction(transaction, installed_yml, files_yml)
        else:
            # Transaction not committed - roll back all changes
            log("Rolling back interrupted " + transaction.operation + 
                " for " + transaction.package_id)
            rollback_transaction(transaction, sd_root, installed_yml, files_yml)


rollback_transaction(transaction, sd_root, installed_yml, files_yml):
    # Restore all backed-up files
    backup_dir = "EDGETX/PKG/state/.backup-" + transaction.id + "/"
    
    # Load backup manifest first (or use empty if no backups)
    backup_manifest = { files: [] }
    if directory_exists(backup_dir):
        backup_manifest = load_yaml(backup_dir + "manifest.yml")
        
        # Verify backup integrity before restoring
        for each backed_up_file in backup_manifest.files:
            backup_path = backup_dir + backed_up_file.path
            if file_exists(backup_path):
                current_hash = compute_sha256(backup_path)
                if current_hash != backed_up_file.sha256:
                    error("Backup integrity check failed for " + backed_up_file.path +
                          "; manual recovery required")
    
    # Remove any partially copied staged files BEFORE restoring backups
    # (if operation was install/update)
    if transaction.operation in ["install", "update"]:
        backup_paths_set = [sd_root + f.path for f in backup_manifest.files]
        for each staged_file in transaction.staged_files:
            dest_path = sd_root + staged_file.path
            # Only delete if NOT in backup manifest (don't delete what we're about to restore)
            if file_exists(dest_path) and dest_path not in backup_paths_set:
                delete_file(dest_path)
                # CRITICAL: Ensure deletion is durable before restoring backups
                fsync(parent_directory(dest_path))
    
    # Restore backed-up files
    if directory_exists(backup_dir):
        for each backed_up_file in backup_manifest.files:
            backup_path = backup_dir + backed_up_file.path
            dest_path = sd_root + backed_up_file.path
            
            if file_exists(backup_path):
                ensure_parent_dirs(dest_path)
                copy_file(backup_path, dest_path)
                # CRITICAL: Ensure restored file is durable before continuing
                fsync(dest_path)
                fsync(parent_directory(dest_path))
    
    # Restore old state
    if transaction.old_state:
        apply_state_snapshot_atomically(installed_yml, files_yml, transaction.old_state)
    
    # Clean up transaction and backups - must be durable to prevent re-recovery
    cleanup_transaction(transaction)
    fsync(state_directory())  # Ensure cleanup is durable
```

**Durable writes**: All transaction record writes and state file writes must use `fsync` (or platform equivalent) to ensure durability before proceeding to the next phase.

**Idempotency**: Recovery operations must be idempotent - multiple recovery attempts for the same transaction must produce the same result.

---

## State Recording

**Note**: With the transaction protocol, state updates are performed atomically via `finalize_transaction`, which applies the complete `new_state` snapshot. The helpers below are conceptual examples showing how state entries are constructed; implementations using transactions should build the `new_state` structure during transaction creation rather than calling these helpers directly.

```
record_installed_state(installed_yml, package, manifest, selected_variant_path, dev_mode):
    entry = {
        id:           package.id,
        version:      package.version,
        variant:      selected_variant_path or null,
        installed_at: now_utc(),
        dev_mode:     dev_mode,
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


record_file_ownership(files_yml, package, selected_variant_path, staged_files):
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


update_installed_state(installed_yml, old_package, new_manifest, selected_variant_path, dev_mode):
    # Replace the existing entry for old_package.id in-place.
    entry = find_entry(installed_yml, old_package.id)
    entry.version      = new_manifest.package.version
    entry.variant      = selected_variant_path or null
    entry.dev_mode     = dev_mode
    entry.source.ref   = new_manifest.source.ref
    entry.constraints  = extract_constraints(new_manifest)
    entry.status       = { compatible: true, code: "OK", reason: "" }
    entry.last_checked_at = now_utc()
    write_yaml(installed_yml, state)


update_file_ownership(files_yml, old_package_id, new_package, selected_variant_path, staged_files):
    # Remove all old entries for old_package_id, then add new ones.
    state.files = [f for f in state.files if f.owner_id != old_package_id]
    record_file_ownership(files_yml, new_package, selected_variant_path, staged_files)


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
    dev_mode: false
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
