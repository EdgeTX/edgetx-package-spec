# Getting Started — Creating an EdgeTX Package

This guide walks through making your Lua scripts installable by EdgeTX package
tooling. It is a tutorial, not the specification — for the exact rules see
[Manifest.md](./Manifest.md).

You need a git repository containing your scripts, laid out in the standard
EdgeTX directories (`SCRIPTS/TOOLS/`, `WIDGETS/`, and so on).

One thing worth knowing before you start: **YAML cares about indentation.**
Nesting is expressed by leading spaces, never tabs, and a line indented by the
wrong amount means something different rather than being a syntax error. If you
get a validation message that makes no sense, check the indentation against the
examples here first — it is the most common cause.

## 1. The smallest manifest that works

Create `edgetx.yml` in your repository root:

```yaml
edgetx_format_version: "1.0"

package:
  id: github.com/your-username/your-repo
  description: A brief description of what your package does

tools:
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool
```

Three things are doing the work here:

- **`id`** is your repository location — the clone URL without `https://` or
  `.git`. It is both your package's identity and where tooling fetches it from,
  so it must match the real repository.
- **`description`** is required and must be non-empty.
- **`path`** is where your files live *and*, by default, where they are
  installed on the SD card. `SCRIPTS/TOOLS/MyTool` in your repo installs to
  `SCRIPTS/TOOLS/MyTool` on the card.

## 2. Add a version

```yaml
package:
  id: github.com/your-username/your-repo
  description: A tool for managing telemetry data
  version: "1.0.0"
```

`version` is optional, but **update detection compares it**. Without it,
tooling cannot tell that a new release exists. Bump it on every release —
tagging without bumping is the most common packaging mistake, and good tooling
will warn you about it.

## 3. Add the metadata that helps people find you

```yaml
edgetx_format_version: "1.0"

package:
  id: github.com/your-username/your-repo
  name: "My Amazing Tool"           # display name; may contain spaces
  version: "1.0.0"
  description: A tool for managing telemetry data on EdgeTX radios
  license: GPL-3.0-only             # SPDX expression
  authors:
    - name: Your Name
      email: you@example.com
  urls:
    - name: Homepage
      url: https://github.com/your-username/your-repo
  keywords: ["telemetry", "logging", "racing"]
  min_edgetx_version: "2.12.0"      # only if you need a specific version
```

Only set `min_edgetx_version` if your scripts actually need a firmware
feature — it stops people on older firmware from installing, so an unnecessary
bound just loses you users.

## 4. Declare your content

Ten sections are available. Put each item in the most specific one that fits:

```yaml
libraries:                          # shared code used by your other scripts
  - name: MyLib
    path: SCRIPTS/LIBS/MyLib

tools:                              # scripts in the Tools menu
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool

widgets:                            # screen widgets (color LCD radios)
  - name: MyWidget
    path: WIDGETS/MyWidget

telemetry:
  - name: MyTelem
    path: SCRIPTS/TELEMETRY/MyTelem

functions:
  - name: MyFunc
    path: SCRIPTS/FUNCTIONS/MyFunc

mixes:
  - name: MyMix
    path: SCRIPTS/MIXES/MyMix

sounds:
  - name: sounds-en
    path: SOUNDS/en

images:
  - name: splash
    path: IMAGES/splash

themes:                             # color LCD only
  - name: MyTheme
    path: THEMES/MyTheme

files:                              # anything with no home above
  - name: docs
    path: extras/manual.pdf
    dest: DOCS/manual.pdf
```

A note on `name`: it identifies the item in diagnostics and **never** affects
where files are installed — that is `path`, or `dest` if you set one. Naming a
theme entry `MyTheme` does not put it in `THEMES/MyTheme`; its `path` does.

Reach for `files` last. It is the escape hatch, and using it where a specific
section applies makes your package harder for people to understand.

## Common patterns

### Installing somewhere other than the source location

Set `dest`. This matters most when the manifest lives inside the content
directory — common for themes:

```yaml
# THEMES/Bionic_Theme/edgetx.yml
package:
  id: github.com/your-username/bionic-theme
  description: Bionic theme for color LCD radios
themes:
  - name: Bionic_Theme
    path: .                       # the manifest's own directory
    dest: THEMES/Bionic_Theme     # required, because path is '.'
```

`dest` is relative to the SD card root and never inherits `source_dir`.

`path: .` does not put your `.git` directory on the card. Version-control
metadata and the manifest files themselves are skipped automatically — you do
not need to `exclude` them.

### Source in a subdirectory

If your scripts live under `src/`, declare it:

```yaml
package:
  source_dir: src                 # or a list: [src, shared]
```

All `path` values then resolve under `src/`. There is **no fallback** to the
repository root: if a `path` does not exist under a declared `source_dir`, that
is an error. This is deliberate — a typo in `source_dir` fails loudly instead
of quietly installing the wrong files.

### Hardware variants

If you ship genuinely different builds for black-and-white and color LCD
radios, declare variants. The base manifest lists them with a hardware filter:

```yaml
# edgetx.yml — base
edgetx_format_version: "1.0"
package:
  id: github.com/your-username/your-repo
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

Each variant is a **complete manifest** that repeats the same `id` and lists
only its own content:

```yaml
# edgetx.color.yml
edgetx_format_version: "1.0"
package:
  id: github.com/your-username/your-repo    # same id as the base
  description: My Widget (Color LCD)
widgets:
  - name: MyWidget
    path: WIDGETS/MyWidget-color
```

Tooling picks the best match for the connected radio, preferring the most
specific filter. Only use variants when you really have hardware-specific
implementations — if one build works everywhere, declaring
`capabilities.display.type` on the package is simpler.

### Shipping precompiled bytecode

If you ship `.luac` instead of Lua source, set `binary: true` — without it every
`.luac` is skipped and your package installs nothing. Bytecode is not portable
across firmware generations, so ship one build per generation and let the
firmware bounds on each variant entry choose:

```yaml
package:
  id: github.com/your-username/your-repo
  description: Precompiled widget
  binary: true
  variants:
    - path: edgetx.etx211.yml
      min_edgetx_version: "2.11.0"
      max_edgetx_version: "2.11.x"
    - path: edgetx.etx212.yml
      min_edgetx_version: "2.12.0"
```

Put `binary: true` in each **variant** manifest, not the base — variant manifests
are self-contained and inherit nothing, so a flag on a base that declares no
content does nothing and your `.luac` files are silently skipped.

The bounds on a variant *entry* only **choose** a build. To say your package will
not run on a firmware version at all, set `min_edgetx_version` on `package` in
the variant's own manifest — that is the one that **enforces** it and produces an
error the user sees. Setting both is normal, and both are checked.

### Requiring another package

Use `requires` when your scripts need a library that ships as a *separate*
package:

```yaml
requires:
  - id: github.com/someone/elrs-libs
    version: "^2.0.0"             # optional; omit to accept any version
```

Tooling installs it before your package. Ranges may be exact (`1.2.3`), caret
(`^1.2.0`), tilde (`~1.2.0`), a comparison (`>=1.2.0`), or two comparators for a
bounded range (`>=1.2.0 <2.0.0`). What each form matches exactly is in
[Manifest.md § Version ranges](./Manifest.md#version-ranges) — caret and tilde
differ between package managers, so it is worth checking rather than assuming.

`requires` is only for another repository. Code inside your own manifest needs
no declaration — everything a package ships installs and is removed together.

### Development-only content

Mark test harnesses and debug tools so they do not reach users. Nothing else
in your manifest needs to know: all of a package's content installs and is
removed together.

```yaml
libraries:
  - name: TestUtils
    path: SCRIPTS/TestUtils
    dev: true
```

Dev items are skipped by install and update unless `--dev` is passed to *that*
invocation — it is never remembered from a previous one.

### Excluding files

```yaml
tools:
  - name: MyTool
    path: SCRIPTS/TOOLS/MyTool
    exclude:
      - "*.md"          # top-level .md only; use **/*.md for every depth
      - "test/**"       # the whole subtree — so would "test/*", since a
                        # directory match takes its contents with it
      - "src/**/tmp"    # `**/` matches zero directories too, so this also
                        # excludes src/tmp
```

## Validation

Validate against the schema from a **specific tagged release**. Both `main` and
`releases/latest` move, so neither is reproducible — put the version you want in
the URL and change it when you choose to.

> **Until the first release is tagged**, no release asset exists. Use the schema
> from the repository — `curl -LO`
> `https://raw.githubusercontent.com/EdgeTX/edgetx-package-spec/main/schema/edgetx-manifest.v1.json`
> — and switch to the pinned form below as soon as `v1.0.0` exists.

```sh
pip install check-jsonschema
curl -LO https://github.com/EdgeTX/edgetx-package-spec/releases/download/v1.0.0/edgetx-manifest.v1.json
check-jsonschema --schemafile edgetx-manifest.v1.json edgetx.yml
```

On Windows, the same thing in PowerShell:

```powershell
pip install check-jsonschema
Invoke-WebRequest -OutFile edgetx-manifest.v1.json https://github.com/EdgeTX/edgetx-package-spec/releases/download/v1.0.0/edgetx-manifest.v1.json
check-jsonschema --schemafile edgetx-manifest.v1.json edgetx.yml
```

As a GitHub Actions step:

```yaml
- uses: actions/checkout@v4
- name: Validate edgetx.yml
  run: |
    pip install check-jsonschema
    curl -LO https://github.com/EdgeTX/edgetx-package-spec/releases/download/v1.0.0/edgetx-manifest.v1.json
    check-jsonschema --schemafile edgetx-manifest.v1.json edgetx.yml
```

Substitute the release you want for `v1.0.0`. The schema's own `$id` points at
`main`, but that is an identifier, not a fetch instruction — what matters is the
file you actually download, and pinning that means a spec change cannot break
your build without you choosing it.

The schema catches structural problems: missing required fields, bad version
strings, unsafe paths. Some rules need your source tree present and are
checked by tooling at install time — that your content paths exist, and that
screenshots are where you said. Others need only the manifest but still cannot
be expressed in a schema, such as whether two content items would install to the
same place. Running an install against a simulator SD card is the real test.

## Checklist before you publish

- `id` matches your real repository URL
- `version` is set, and you remember to bump it each release
- `min_edgetx_version` is set only if you genuinely need it
- every `path` exists
- you installed it onto a real SD card, or a simulator one, and it worked

## Publishing

1. Commit `edgetx.yml`.
2. Tag a release: `git tag v1.0.0 && git push --tags`.
3. Users install with `edgetx-cli pkg install your-username/your-repo`.

Tooling resolves the highest semver tag by default, so tagging is what makes a
release visible. Users can pin explicitly with
`your-username/your-repo@v1.0.0`.

## Examples

Complete working manifests live in
[`conformance/valid/`](../conformance/valid/):

| Fixture | Shows |
|---|---|
| `simple-tool.yml` | The minimum viable manifest |
| `with-library-deps.yml` | A shared library beside the scripts that use it |
| `with-requires.yml` | Depending on another package |
| `multi-variant.yml` | Black-and-white and color LCD variants |
| `variant-standalone.yml` | What a variant manifest looks like |
| `all-sections.yml` | Every content section |
| `max-fields.yml` | Every package-level field populated |
| `unknown-fields.yml` | Why an unknown field does not break your manifest |
| `bytecode-variants.yml` | Precompiled `.luac`, one build per firmware generation |
| `bytecode-variant-standalone.yml` | One bytecode variant manifest, with `binary` where it belongs |
| `pkg-dir-as-source.yml` | A repo with its own `PKG/` directory, installed elsewhere |

## Help

- Specification: [Manifest.md](./Manifest.md)
- Tooling guidance: [Implementation.md](./Implementation.md)
- Issues: <https://github.com/EdgeTX/edgetx-package-spec/issues>
- EdgeTX Discord, `#lua-development`
