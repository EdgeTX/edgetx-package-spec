# Getting Started — Creating an EdgeTX Package

This guide helps you create your first EdgeTX package manifest and make your Lua scripts installable via the EdgeTX package manager.

## Prerequisites

- A git repository containing your EdgeTX Lua scripts
- Basic understanding of YAML syntax
- Your scripts organized in standard EdgeTX directories (`SCRIPTS/TOOLS/`, `WIDGETS/`, etc.)

## Quick Start

### 1. Create `edgetx.yml` in your repository root

Start with this minimal template:

```yaml
spec_version: "1.0"

package:
  id: github.com/your-username/your-repo-name
  description: A brief description of what your package does

tools:
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool
```

### 2. Fill in Required Fields

At minimum, you need:

- **`package.id`**: Your repository location (format: `host/owner/repo`)
- **`package.description`**: A clear description of your package

### 3. Add Optional Metadata

Enhance discoverability and provide context:

```yaml
spec_version: "1.0"

package:
  id: github.com/your-username/your-repo-name
  name: "My Amazing Tool"           # Human-friendly display name
  version: "1.0.0"                  # Semantic version (recommended!)
  description: A tool for managing telemetry data on EdgeTX radios
  category: telemetry               # Helps users discover your package
  license: GPL-3.0-only             # SPDX license identifier
  authors:
    - name: Your Name
      email: you@example.com
  urls:
    - name: Homepage
      url: https://github.com/your-username/your-repo-name
  keywords: ["telemetry", "logging", "racing"]
  min_edgetx_version: "2.12.0"      # Minimum compatible EdgeTX version
```

### 4. Declare Your Content

Tell the package manager what to install:

```yaml
# Libraries (shared code used by other scripts)
libraries:
  - name: MyLib
    path: SCRIPTS/LIBS/MyLib

# Tools (scripts in the Tools menu)
tools:
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool
    depends:                        # Optional: declare dependencies
      - MyLib

# Widgets (for color LCD radios)
widgets:
  - name: MyWidget
    path: WIDGETS/MyWidget
    depends:
      - MyLib

# Telemetry scripts
telemetry:
  - name: MyTelem
    path: SCRIPTS/TELEMETRY/MyTelem

# Function scripts
functions:
  - name: MyFunc
    path: SCRIPTS/FUNCTIONS/MyFunc

# Mix scripts
mixes:
  - name: MyMix
    path: SCRIPTS/MIXES/MyMix

# Sound packs
sounds:
  - name: sounds-en
    path: SOUNDS/en

# Themes
themes:
  - name: MyTheme
    path: THEMES/MyTheme
```

## Common Patterns

### Hardware-Specific Variants

If your package supports different radio types (B&W vs color LCD), use variants:

```yaml
# edgetx.yml (base manifest)
spec_version: "1.0"
package:
  id: github.com/your-username/your-repo-name
  description: Multi-platform widget
  variants:
    - path: edgetx.bw128x64.yml
      capabilities:
        display:
          type: bw
          resolution: 128x64
    - path: edgetx.color.yml
      capabilities:
        display:
          type: colorlcd
```

Then create variant files that only list their specific content:

```yaml
# edgetx.color.yml
package:
  description: My Widget (Color LCD)

widgets:
  - name: MyWidget
    path: WIDGETS/MyWidget-color
```

### Subpackages

Multiple independent packages in one repository:

```
your-repo/
├── tool-a/
│   └── edgetx.yml              # id: github.com/.../your-repo/tool-a
└── tool-b/
    └── edgetx.yml              # id: github.com/.../your-repo/tool-b
```

Each subpackage has its own full manifest with a unique ID that includes the subdirectory path.

### Development Dependencies

Mark libraries or tools that are only needed during development:

```yaml
libraries:
  - name: TestUtils
    path: SCRIPTS/TestUtils
    dev: true                     # Won't be installed by default
```

## Validation

### Local Validation

1. Install dependencies:
   ```bash
   pip install jsonschema PyYAML
   ```

2. Download the schema:
   ```bash
   curl -O https://raw.githubusercontent.com/EdgeTX/edgetx-package-spec/main/schema/edgetx-manifest.v1.json
   ```

3. Validate your manifest:
   ```python
   import json
   import jsonschema
   import yaml
   
   schema = json.load(open('edgetx-manifest.v1.json'))
   manifest = yaml.safe_load(open('edgetx.yml'))
   
   jsonschema.Draft202012Validator(schema).validate(manifest)
   print("✓ Valid manifest!")
   ```

### CI/CD Integration

Add GitHub Actions workflow to validate on every commit:

```yaml
# .github/workflows/validate-manifest.yml
name: Validate Package Manifest

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install jsonschema PyYAML
      
      - name: Download schema
        run: |
          curl -o schema.json https://raw.githubusercontent.com/EdgeTX/edgetx-package-spec/main/schema/edgetx-manifest.v1.json
      
      - name: Validate manifest
        run: |
          python -c "
          import json, sys
          import jsonschema, yaml
          schema = json.load(open('schema.json'))
          manifest = yaml.safe_load(open('edgetx.yml'))
          try:
              jsonschema.Draft202012Validator(schema).validate(manifest)
              print('✓ Valid manifest')
          except jsonschema.ValidationError as e:
              print(f'✗ Invalid manifest: {e.message}')
              sys.exit(1)
          "
```

## Best Practices

1. **Always specify `spec_version`**: Use `spec_version: "1.0"` to indicate your manifest follows the 1.0 spec.

2. **Include a version field**: While optional, `package.version` is strongly recommended for update detection.

3. **Choose the right category**: Use the most specific category that fits your package (helps users discover it).

4. **Declare dependencies**: If your script uses shared libraries, declare them in `depends`.

5. **Set version constraints**: Use `min_edgetx_version` if your package requires specific EdgeTX features.

6. **Test on target hardware**: Validate your package installs correctly on the actual radio types you support.

7. **Use variants wisely**: Only create variants when you truly have hardware-specific implementations, not just for different user preferences.

8. **Keep it simple**: Start minimal and add fields as needed. Don't pre-optimize.

## Examples

See the [conformance test fixtures](https://github.com/EdgeTX/edgetx-package-spec/tree/main/conformance/valid) for complete working examples:

- **[simple-tool.yml](../conformance/valid/simple-tool.yml)**: Absolute minimum manifest
- **[with-library-deps.yml](../conformance/valid/with-library-deps.yml)**: Package with library dependencies
- **[multi-variant.yml](../conformance/valid/multi-variant.yml)**: B&W and color LCD variants
- **[max-fields.yml](../conformance/valid/max-fields.yml)**: Comprehensive example with all fields

## Need Help?

- 📖 Full specification: [docs/Manifest.md](./Manifest.md)
- 🔧 Implementation guide: [docs/Implementation.md](./Implementation.md)
- 🐛 Report issues: [GitHub Issues](https://github.com/EdgeTX/edgetx-package-spec/issues)
- 💬 Ask questions: EdgeTX Discord #lua-development channel

## Next Steps

Once you have a valid `edgetx.yml`:

1. Commit it to your repository
2. Tag a release (e.g., `v1.0.0`)
3. Submit your package to the EdgeTX package catalog (coming soon)
4. Users can install via: `pkg install your-username/your-repo-name`
