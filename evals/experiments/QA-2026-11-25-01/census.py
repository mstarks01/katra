"""Count, over archived reports, the inputs that #2307's prompt sentences
govern: a field the rows hold open, and an absence the catalog drops.

Each report's catalog is rebuilt with today's code, with and without its
assertion rows, through the production readers. It reads ``evals/runs/``,
which git does not track, so the figures hold for this machine's archive.
Run from the repository root:

    PYTHONPATH=src:. python evals/experiments/QA-2026-11-25-01/census.py evals/runs evals/baselines
"""

import sys
from collections import Counter
from pathlib import Path

from evals.harness.assertion_use import report_paths
from evals.harness.bundle import UnreadableReport, read_report
from katra.assertions import hidden_qualifications
from katra.evidence import evidence_catalog, held_value
from katra.system_model import ModelIndex


def main(roots: list[str]) -> None:
    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    for path in report_paths([Path(root) for root in roots]):
        try:
            report = read_report(path)
        except UnreadableReport:
            counts["refused"] += 1
            continue
        counts["read"] += 1
        if report.assertions is None:
            counts["no assertion pass"] += 1
            continue
        model = report.system_model
        rows = report.assertions.catalog
        index = ModelIndex.of(model)
        bare = evidence_catalog(model)
        full = evidence_catalog(model, rows)
        kinds.update(ground.kind for ground in full.values())
        counts["rows"] += len(rows.entries)
        counts["hidden qualifications"] += len(hidden_qualifications(rows, model))
        counts["held-open entries"] += sum(
            held_value(ground, index) is not None for ground in full.values()
        )
        counts["dropped absences"] += sum(
            ground.kind == "absent-attribute" and ref not in full
            for ref, ground in bare.items()
        )
    for name, count in counts.items():
        print(f"{name}: {count}")
    print("catalog entries with rows:", dict(kinds))


if __name__ == "__main__":
    main(sys.argv[1:])
