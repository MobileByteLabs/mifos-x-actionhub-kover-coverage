# mifos-x-actionhub-kover-coverage

Composite GitHub Action that runs Kover's aggregated XML report on a Kotlin
Multiplatform / multi-module project and enforces per-module line-coverage
floors. Designed to be called from a reusable workflow in
[openMF/mifos-x-actionhub](https://github.com/openMF/mifos-x-actionhub),
mirroring the layout of every other `mifos-x-actionhub-*` composite action.

## Features

- **Fully dynamic module discovery.** Whatever modules apply the Kover
  plugin (directly or via a convention plugin) produce
  `build/reports/kover/report.xml`. The checker walks all of them. No
  path filters, no hardcoded module list, no `module-paths` input.
- **Two-tier floors.** A YAML file (`.kover-floor.yml` by default) sets
  explicit per-module overrides; everything else uses a single
  `default-floor` input. New modules adopt the default automatically.
- **Soft/hard failure separation.**
  - `actual < floor` → ❌ hard fail
  - Listed module with no `report.xml` AND floor > default → ❌ hard fail
    (lost measurement)
  - Listed module with no `report.xml` AND floor ≤ default → ⚠️ warn only
- **Stdlib-only checker.** The bundled `scripts/check-coverage-floor.py`
  uses only Python 3 standard library — no PyYAML, no npm.
- **Artifact upload.** Aggregated HTML coverage report attached to the
  workflow run for click-through inspection.

## Consumer usage

This action is the engine. The intended consumer-facing entry point is
the reusable workflow `openMF/mifos-x-actionhub/.github/workflows/test-coverage.yaml`,
which calls this action with sensible defaults.

If you want to call this action directly from a consumer job:

```yaml
# .github/workflows/test-coverage.yml
name: Test Coverage Floor

on:
  pull_request:
    paths:
      - '**/*.kt'
      - '**/*.kts'
      - '.kover-floor.yml'

jobs:
  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: MobileByteLabs/mifos-x-actionhub-kover-coverage@v1
        with:
          default-floor: 0
```

## Prerequisites in the consumer repo

1. **Kover convention plugin.** Each leaf module that wants coverage must
   apply the kover plugin and self-register into root's aggregation:

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

    See [openMF/kmp-project-template][template] for a full reference setup.

2. **`.kover-floor.yml` at repo root** with explicit per-module
   non-default floors only:

    ```yaml
    floors:
      ":core-base:store": 90      # tested module, protect at 90%
      # everything else uses the action's default-floor input
    ```

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `java-version` | `'17'` | JDK version installed via setup-java |
| `java-distribution` | `'temurin'` | JDK distribution |
| `report-task` | `'koverXmlReport'` | Gradle task that produces per-module XML reports |
| `gradle-args` | `'--continue --stacktrace'` | Extra args passed to the report task |
| `floor-file` | `'.kover-floor.yml'` | Repo-relative path of the floor YAML |
| `default-floor` | `'0'` | Floor (%) for modules not listed in the floor file |
| `upload-html-report` | `'true'` | Whether to upload the aggregated HTML report as an artifact |
| `html-report-path` | `'build/reports/kover/html'` | Project-relative path of the HTML report dir |
| `artifact-retention-days` | `'14'` | Retention for the uploaded artifact |

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

## Stack

- Composite action: GitHub Actions
- Checker: Python 3 stdlib only (`xml.etree.ElementTree`, `re`,
  `pathlib`, `argparse`)
- Runs against the report XML format emitted by
  `org.jetbrains.kotlinx.kover@0.7+`

## License

MPL-2.0.

[template]: https://github.com/openMF/kmp-project-template
