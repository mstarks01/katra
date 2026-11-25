"""Count, per arm, the reference zone IDs each sweep writes and the elements it leaves in no zone.

Reads the archived extractions of QA-2026-11-25-02 and the corpus reference models.
Usage, from the repository root of a checkout that holds the archive:

    python3 evals/experiments/QA-2026-11-25-02/zone_ids.py \
        evals/runs/20261125T-qa-2026-11-25-02 evals/corpus
"""

import json
import sys
from collections import Counter
from pathlib import Path

ARMS = ("A", "B", "C")
ELEMENT_KINDS = ("processes", "data_stores", "external_entities")
UNPLACED = "unknown"


def placements(model: dict) -> Counter:
    return Counter(
        element.get("trust_zone")
        for kind in ELEMENT_KINDS
        for element in model.get(kind, [])
    )


def main(runs: Path, corpus: Path) -> None:
    totals: dict[str, Counter[str]] = {arm: Counter() for arm in ARMS}
    for case_dir in sorted(corpus.glob("[0-9]*")):
        reference = json.loads((case_dir / "model.json").read_text())
        zones = set(placements(reference)) - {UNPLACED, None}
        if not zones:
            continue
        cells = []
        for arm in ARMS:
            written = expected = unplaced = 0
            pattern = f"{arm}-r[0-9].reports/{case_dir.name}*extraction.json"
            for report in sorted(runs.glob(pattern)):
                model = json.loads(report.read_text()).get("normalized") or {}
                used = placements(model)
                written += len(zones & set(used))
                expected += len(zones)
                unplaced += used.get(UNPLACED, 0)
            totals[arm].update(written=written, expected=expected, unplaced=unplaced)
            cells.append(f"{arm} {written}/{expected} unplaced {unplaced}")
        print(case_dir.name.ljust(36), " | ".join(cells))
    for arm, total in totals.items():
        share = total["written"] / total["expected"]
        print(
            f"{arm}: reference zone IDs written {total['written']}/{total['expected']}"
            f" = {share:.3f}; elements in no zone {total['unplaced']}"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
