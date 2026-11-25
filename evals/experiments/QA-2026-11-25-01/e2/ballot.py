"""Build the blind ballot of QA-2026-11-25-01-E2 from the 12 lane replays.

A target draft names the receipt archive or the append-receipt flow and rests
on encryption. The ballot hides the arm; ``key.csv`` holds it.
"""

import csv
import json
import random
import sys
from pathlib import Path

TARGETS = {
    "store:receipt-archive",
    "flow:process:order-service>store:receipt-archive>append-receipt",
}
DROPPED_ABSENCES = (
    "absent:store:receipt-archive:encryption_at_rest",
    "absent:flow:process:order-service>store:receipt-archive>append-receipt:encryption_in_transit",
)


def is_target(claim: dict) -> bool:
    text = " ".join([claim["title"], claim["description"], *claim["evidence_refs"]])
    named = TARGETS & set(claim["affected_element_ids"])
    return bool(named) and "encrypt" in text.lower()


def main() -> None:
    runs, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for path in sorted(runs.glob("*.json")):
        arm, rest = path.stem.split("-", 1)
        lane, run = rest.rsplit("-", 1)
        for claim in json.loads(path.read_text())["claims"]:
            if is_target(claim):
                rows.append(
                    {
                        "arm": arm,
                        "lane": lane,
                        "pass": run,
                        "title": claim["title"],
                        "description": claim["description"],
                        "evidence_refs": " ".join(claim["evidence_refs"]),
                        "cites_dropped_absence": any(
                            r in DROPPED_ABSENCES for r in claim["evidence_refs"]
                        ),
                    }
                )
    random.Random(20261125).shuffle(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "ballot-issued.csv").open("w", newline="") as handle:
        out = csv.writer(handle)
        out.writerow(
            ["row", "lane", "title", "description", "ruling (plain or conditional)"]
        )
        for number, row in enumerate(rows, 1):
            out.writerow([number, row["lane"], row["title"], row["description"], ""])
    with (out_dir / "key.csv").open("w", newline="") as handle:
        out = csv.writer(handle)
        out.writerow(
            ["row", "arm", "lane", "pass", "cites_dropped_absence", "evidence_refs"]
        )
        for number, row in enumerate(rows, 1):
            out.writerow(
                [
                    number,
                    row["arm"],
                    row["lane"],
                    row["pass"],
                    row["cites_dropped_absence"],
                    row["evidence_refs"],
                ]
            )
    print(f"{len(rows)} target drafts")


if __name__ == "__main__":
    main()
