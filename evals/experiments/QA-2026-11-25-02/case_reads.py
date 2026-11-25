"""Read the case-level facts of the sweeps: invalid extractions and case 14 zones.

usage: case_reads.py RUNS_DIR ARM... Each sweep wrote <arm>-r<n>.json and a
<arm>-r<n>.reports folder of extractions.
"""

import json
import sys
from pathlib import Path

CASE_14 = "14-loyalty-oauth-platform"
ELEMENT_KINDS = ("external_entities", "processes", "data_stores")


def case_14_zones(reports: Path) -> tuple[int, int, list[str]]:
    """Count the elements placed in no zone, and name the partner zones."""
    extraction = reports / f"{CASE_14}.extraction.json"
    if not extraction.exists():
        return 0, 0, ["no extraction"]
    model = json.loads(extraction.read_text())["normalized"]
    elements = [element for kind in ELEMENT_KINDS for element in model[kind]]
    unplaced = sum(e.get("trust_zone") in ("unknown", None) for e in elements)
    zones = {e.get("trust_zone") for e in elements}
    partner = sorted(zone for zone in zones if "partner" in str(zone))
    return unplaced, len(elements), partner


def main(runs: Path, arms: list[str]) -> None:
    for arm in arms:
        failed = unplaced_total = 0
        for artifact in sorted(runs.glob(f"{arm}-r[0-9].json")):
            failures = json.loads(artifact.read_text())["structural_failures"]
            invalid = sorted({failure.split(":", 1)[0] for failure in failures})
            failed += len(invalid)
            unplaced, elements, partner = case_14_zones(
                artifact.with_suffix(".reports")
            )
            unplaced_total += unplaced
            print(
                f"{artifact.stem}: case 14 unplaced {unplaced} of {elements}, {partner}"
            )
            for failure in failures:
                print(f"  {failure[:200]}")
            print(f"  invalid or stopped cases: {invalid}")
        print(
            f"{arm}: {failed} invalid or stopped cases, case 14 unplaced {unplaced_total}"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
