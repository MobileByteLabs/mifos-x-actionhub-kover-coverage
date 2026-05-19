#!/usr/bin/env python3
"""Enforce per-module line-coverage floors after Kover produces XML reports.

Discovery is fully dynamic — the script walks every
`*/build/reports/kover/report.xml` under the repo root and computes LINE
coverage per module from the kover XML. Modules don't need to be enumerated
anywhere; whatever Gradle's kover aggregation produced is what gets checked.

Floor resolution per discovered module:
  - If listed in the floor YAML → that explicit value
  - Otherwise → `--default-floor` (CLI arg)

A module listed in the floor file but with no `report.xml` is a hard failure:
the floor was set with intent and is now unmeasurable (build broke before
tests, or the module was renamed/deleted without updating the floor file).

Exit codes:
  0 — all measurable modules meet their floor
  1 — at least one module is below its floor OR a listed module has no report
"""
from __future__ import annotations
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_floor_file(path: Path) -> dict[str, float]:
    """Tiny YAML subset parser — only handles `floors:` map of `":x": N` entries.

    Avoids adding a PyYAML dependency just for this one file. If the floor
    file doesn't exist, returns an empty dict (every module then uses
    --default-floor).
    """
    if not path.exists():
        return {}
    floors: dict[str, float] = {}
    in_floors = False
    entry = re.compile(r'^\s+"([^"]+)":\s*([0-9.]+)\s*(#.*)?$')
    for line in path.read_text().splitlines():
        if line.strip() == "floors:":
            in_floors = True
            continue
        if in_floors and line and not line.startswith((" ", "\t")):
            in_floors = False
            continue
        if not in_floors:
            continue
        m = entry.match(line)
        if m:
            floors[m.group(1)] = float(m.group(2))
    return floors


def module_path_for_report(report_xml: Path, repo_root: Path) -> str:
    """`./feature/crypto/build/reports/kover/report.xml` → `:feature:crypto`."""
    rel = report_xml.relative_to(repo_root)
    # Strip the trailing "build/reports/kover/report.xml" segments.
    module_parts = rel.parts[:-4]
    return ":" + ":".join(module_parts)


def line_coverage_pct(report_xml: Path) -> float | None:
    """Return LINE coverage %, or None if no LINE counter found."""
    try:
        root = ET.parse(report_xml).getroot()
    except ET.ParseError:
        return None
    for counter in root.findall("counter"):
        if counter.get("type") == "LINE":
            missed = int(counter.get("missed", 0))
            covered = int(counter.get("covered", 0))
            total = missed + covered
            if total == 0:
                return 0.0
            return covered / total * 100.0
    return None


def discover_reports(repo_root: Path) -> list[Path]:
    """Find every kover report.xml at any module depth.

    Glob patterns cover up to 4 path segments before `/build/...` (e.g.
    `core-base/store/`, `clients/android/foo/`). Adjust if your KMP layout
    nests deeper.
    """
    seen: set[Path] = set()
    for depth in range(1, 5):
        glob = "/".join(["*"] * depth) + "/build/reports/kover/report.xml"
        for p in repo_root.glob(glob):
            seen.add(p.resolve())
    return sorted(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--floor-file",
        default=".kover-floor.yml",
        help="Path to the per-module floor YAML (relative to repo root). "
             "Missing file is OK — every module then uses --default-floor.",
    )
    ap.add_argument(
        "--default-floor",
        type=float,
        default=0.0,
        help="Line-coverage floor (%%) for any discovered module not "
             "listed in the floor file.",
    )
    ap.add_argument(
        "--repo-root",
        default=".",
        help="Project root (where build/reports/kover/report.xml dirs live).",
    )
    ap.add_argument(
        "--slack",
        type=float,
        default=0.05,
        help="Floating-point slack (percentage points) to absorb rounding.",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    floor_path = repo_root / args.floor_file
    floors = parse_floor_file(floor_path)

    reports = discover_reports(repo_root)
    if not reports:
        print(f"❌ No kover report.xml files found under {repo_root}.")
        print("   Did `./gradlew koverXmlReport` run? Did any module apply kover?")
        return 1

    observed: dict[str, float] = {}
    for r in reports:
        module = module_path_for_report(r, repo_root)
        pct = line_coverage_pct(r)
        if pct is not None:
            observed[module] = pct

    # Per-module pass/fail
    failures: list[tuple[str, float, float]] = []
    missing_hard: list[tuple[str, float]] = []
    missing_soft: list[str] = []
    listed_modules = set(floors.keys())
    observed_modules = set(observed.keys())

    # Modules listed but no report:
    #   floor > default → hard fail (real measurement lost)
    #   floor <= default → soft warn (redundant entry; file may be stale)
    for module in sorted(listed_modules - observed_modules):
        if floors[module] > args.default_floor:
            missing_hard.append((module, floors[module]))
        else:
            missing_soft.append(module)

    # Modules observed → check floor (listed or default)
    for module in sorted(observed_modules):
        floor = floors.get(module, args.default_floor)
        actual = observed[module]
        if actual + args.slack < floor:
            failures.append((module, actual, floor))

    # Pretty-print the table
    all_modules = sorted(listed_modules | observed_modules)
    print("┌─────────────────────────────────────────────────────────────────┐")
    print(f"│ Per-module line coverage (default floor = {args.default_floor:.1f}%)" + " " * 19 + "│"[-1:])
    print("├──────────────────────────────────┬──────────┬──────┬────────────┤")
    print("│ Module                           │ Coverage │ Floor│ Status     │")
    print("├──────────────────────────────────┼──────────┼──────┼────────────┤")
    for module in all_modules:
        if module in observed:
            pct = observed[module]
            floor = floors.get(module, args.default_floor)
            ok = "✅ pass" if pct + args.slack >= floor else "❌ FAIL"
            source = "" if module in floors else " (default)"
            print(f"│ {module:<32} │ {pct:7.1f}% │ {floor:4.1f}%│ {ok}{source:<10}".ljust(67) + "│")
        else:
            floor = floors[module]
            mark = "❌ MISSING" if floor > 0 else "⚠️  missing"
            print(f"│ {module:<32} │   MISSING│ {floor:4.1f}%│ {mark:<10} │")
    print("└──────────────────────────────────┴──────────┴──────┴────────────┘")

    if not failures and not missing_hard:
        if missing_soft:
            print(f"\n⚠️  {len(missing_soft)} module(s) listed in floor file produced "
                  f"no report.xml. Their floor is at-or-below the default — not "
                  f"failing, but consider removing redundant entries.")
        print(f"\n✅ All {len(observed)} measurable modules meet their coverage floor.")
        return 0

    print()
    if missing_hard:
        print("❌ Coverage data lost for modules with non-zero floors:")
        for module, floor in missing_hard:
            print(f"     {module}: floor {floor:.1f}%, but no report.xml was produced")
        print("   (build broke before tests fired, module renamed/deleted "
              "without updating .kover-floor.yml, or kover not applied to it)")
        print()
    if failures:
        print("❌ Coverage regressions:")
        for module, actual, floor in failures:
            delta = floor - actual
            print(f"     {module}: {actual:.1f}% < {floor:.1f}% floor (down {delta:.1f}pp)")
        print()
    print("Fix: write tests to restore coverage, OR justify the floor change "
          "in the PR description.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
