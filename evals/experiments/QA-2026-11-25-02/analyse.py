"""Read the extraction sweeps of two arms: one row per sweep, then the arm deltas.

usage: analyse.py RUNS_DIR BEFORE AFTER, where each arm wrote <arm>-r<n>.json.
A delta is in units of the BEFORE arm's sample standard deviation, or a raw
change where that spread is zero.
"""

import glob
import json
import statistics
import sys
from pathlib import Path

FIELDS = (
    "flow.authentication",
    "flow.encryption_in_transit",
    "store.encryption_at_rest",
)
CASE_MEANS = ("interaction_recall", "zone_recall", "crossings_recall")
NOT_SCORES = ("sweep", "cases", "charged")


def sweep_row(path: Path) -> dict:
    artifact = json.loads(path.read_text())
    aggregate = artifact["attribute_aggregate"]
    cases = artifact["mode_output"]
    recalls = [
        case["endpoint_recall"]
        for case in cases
        if case.get("endpoint_recall") is not None
    ]
    row = {
        "sweep": path.stem,
        "cases": len(cases),
        "agreement": aggregate["agreement"],
        "endpoint_recall": round(statistics.mean(recalls), 4),
        "charged": round(sum((artifact.get("node_charges") or {}).values()), 4),
    }
    for field in FIELDS:
        row[field] = aggregate["by_attribute"].get(field, {}).get("agreement")
    for key in CASE_MEANS:
        values = [
            case[key] for case in cases if isinstance(case.get(key), (int, float))
        ]
        if values:
            row[key] = round(statistics.mean(values), 4)
    return row


def spread(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def main(runs: Path, before: str, after: str) -> None:
    rows = {
        arm: [
            sweep_row(Path(p))
            for p in sorted(glob.glob(str(runs / f"{arm}-r[0-9].json")))
        ]
        for arm in (before, after)
    }
    for arm_rows in rows.values():
        for row in arm_rows:
            print(json.dumps(row))
    first = rows[before][0]
    scores = [k for k in first if k not in NOT_SCORES and first[k] is not None]
    for key in scores:
        b = [row[key] for row in rows[before] if row.get(key) is not None]
        a = [row[key] for row in rows[after] if row.get(key) is not None]
        sd = spread(b)
        change = statistics.mean(a) - statistics.mean(b)
        delta = (
            f"{change / sd:+.2f} sd" if sd else f"{change:+.4f} raw, before spread 0"
        )
        print(
            f"{key}: {before} {statistics.mean(b):.4f} sd {sd:.4f}"
            f"  {after} {statistics.mean(a):.4f} sd {spread(a):.4f}"
            f"  delta {delta}"
        )
    charged = {arm: round(sum(r["charged"] for r in rows[arm]), 4) for arm in rows}
    print("charged:", charged)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
