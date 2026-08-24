# File-list fixtures

`PKG/files/<package-id>.list` is a normative format — see
[State.md](../../docs/State.md#pkgfilespackage-idlist) — but it is a
line-oriented text file, so no JSON Schema reaches it. These fixtures give it the
same treatment the YAML formats get.

The runner checks each line against the same `safeRelativeDest` pattern the
manifest schema applies to `dest`, which is exactly the guarantee State.md asks
for: a path read back from a removable card is not trusted input.

## Naming

| Name | Expectation |
|---|---|
| `valid*.list` | Every line must be accepted. |
| `invalid-*.list` | At least one line must be rejected — and it must be the line the fixture names. |

## The `# expect:` directive

The first line of every `invalid-*.list` is a directive naming the rule the
fixture pins:

```text
# expect: PKG/installed\.yml
SCRIPTS/TOOLS/ok.lua
PKG/installed.yml
```

The value is a regular expression matched against the runner's report of the
first rejected line. Without it, a fixture named for one rule could be credited
for violating a different one, and a regression in the named rule would pass
unnoticed — which is what happened before the directive existed.

**A directive is required.** The runner fails an `invalid-*.list` that has none.

## A note on `#` lines

The runner skips lines beginning with `#`, which is how the directive stays out
of the data. This is a convention of these fixtures **only** — `State.md` defines
no comment syntax for the format, and a real `PKG/files/*.list` has none. A path
beginning with `#` is legal on an SD card and cannot be expressed in a fixture;
that is an accepted limitation of the harness, not a rule about the format.
