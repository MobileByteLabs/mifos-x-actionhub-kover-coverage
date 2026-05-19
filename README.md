# mifos-x-actionhub-kover-coverage

Reusable GitHub Actions workflow that enforces per-module line-coverage floors
on any Kover-based Kotlin Multiplatform / multi-module project.

## Why this exists

Once your project pulls in [Kover](https://kotlin.github.io/kotlinx-kover/)
for line coverage, the next question is: *how do we stop coverage from
silently regressing on every PR?* This action wraps that gate. It is
fully dynamic — discovery happens at Gradle config time via your kover
convention plugin, the workflow doesn't take a `module-paths` filter
or maintain a hardcoded module list.

## Features

- **Fully dynamic module discovery.** Whatever modules apply the Kover
  plugin (directly or via a convention plugin) produce
  `build/reports/kover/report.xml`. The checker walks all of them. No
  path filters, no hardcoded module list.
- **Two-tier floors.** A YAML file (`.kover-floor.yml` by default) sets
  explicit per-module overrides; everything else uses a single
  `default-floor` input. New modules adopt the default automatically.
- **Soft/hard failure separation.**
  - `actual < floor` → ❌ hard fail
  - Listed module with no `report.xml` → ❌ hard fail (lost measurement)
  - Unlisted module at default floor with no report → ⚠️ warn only
- **Stdlib-only checker.** No PyYAML / no node_modules. The action ships
  a single Python 3 file (`scripts/check-coverage-floor.py`).
- **Artifact upload.** Aggregated HTML coverage report attached to the
  workflow run for click-through inspection.

## Quick start

In your consumer repo:

1. Apply Kover and self-register modules via your convention plugin. The
   canonical pattern:

    ```kotlin
    // build-logic/convention/src/main/kotlin/KoverConventionPlugin.kt
    class KoverConventionPlugin : Plugin<Project> {
        override fun apply(target: Project) = with(target) {
            pluginManager.apply("org.jetbrains.kotlinx.kover")
            if (project == rootProject) {
                // configure root reports here
            } else {
                rootProject.dependencies.add("kover", project)
            }
        }
    }
    ```

    See [openMF/kmp-project-template @ feat/kover-coverage-260517][template]
    for a full reference setup including the catalog-version trap to avoid.

2. Drop a `.kover-floor.yml` at the repo root. Only list modules with
   non-default floors:

    ```yaml
    floors:
      ":core-base:store": 90      # tested module, protect at 90%
      # everything else uses --default-floor from the workflow
    ```

3. Add the workflow stub:

    ```yaml
    # .github/workflows/test-coverage.yml
    name: Test Coverage Floor
    on:
      pull_request:
        paths:
          - '**/*.kt'
          - '**/build.gradle.kts'
          - '.kover-floor.yml'
      push:
        branches: [main, dev]

    jobs:
      coverage:
        uses: MobileByteLabs/mifos-x-actionhub-kover-coverage/.github/workflows/coverage.yml@v1
        with:
          default-floor: 0
    ```

That's it. New `:feature:*` / `:core:*` modules participate automatically
via the convention plugin chain — no workflow changes needed.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `java-version` | `'17'` | JDK version installed via setup-java |
| `java-distribution` | `'temurin'` | JDK distribution |
| `report-task` | `'koverXmlReport'` | Gradle task that produces per-module XML reports |
| `gradle-args` | `'--continue --stacktrace'` | Extra args passed to the report task |
| `floor-file` | `'.kover-floor.yml'` | Repo-relative path of the floor YAML |
| `default-floor` | `0` | Floor (%) for modules not listed in the floor file |
| `upload-html-report` | `true` | Whether to upload the aggregated HTML report as an artifact |
| `html-report-path` | `'build/reports/kover/html'` | Project-relative path of the HTML report dir |
| `artifact-retention-days` | `14` | Retention for the uploaded artifact |
| `runs-on` | `'ubuntu-latest'` | Runner label |
| `timeout-minutes` | `45` | Job timeout |

## Floor file format

```yaml
# .kover-floor.yml — module → minimum line-coverage %
#
# Only list modules with explicit non-default floors. Every other module
# discovered by the kover aggregation uses the `default-floor` workflow
# input. Floors should only ratchet UPWARD over time.
floors:
  ":core-base:store": 90
  ":feature:crypto": 95
```

## Ratchet protocol

For each PR that raises coverage on module `X`:

1. Add tests to `X`.
2. In the same PR, add or update the `X` entry in `.kover-floor.yml`
   with the new measured percentage (or slightly below it to absorb
   normal fluctuation, e.g. `actual - 2`).
3. CI then protects the new floor on every subsequent PR.

To lower a floor (test deletion / scope reduction): justify the change
in the PR description. The action doesn't *prevent* lowering — that's a
review-time signal, not a hook.

## Comparison to manually wired workflows

Before:

```yaml
# Inline workflow — every consumer maintains 60+ lines of YAML
# + a Python script copy + a floor file
```

After:

```yaml
jobs:
  coverage:
    uses: MobileByteLabs/mifos-x-actionhub-kover-coverage/.github/workflows/coverage.yml@v1
    with:
      default-floor: 0
```

The script lives in this repo and is fetched at workflow runtime, pinned
to the same ref that the consumer called the workflow at. Versioning the
action versions the script in lockstep.

## Stack

- Reusable workflow: GitHub Actions `workflow_call`
- Checker: Python 3 stdlib only (`xml.etree.ElementTree`, `re`,
  `pathlib`, `argparse`) — no third-party deps
- Runs against the report XML format emitted by
  `org.jetbrains.kotlinx.kover@0.7+`

## License

MPL-2.0 (matches the openMF KMP project template conventions).

[template]: https://github.com/openMF/kmp-project-template
