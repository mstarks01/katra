"""Count, over archived reports, the inputs that #2307's prompt sentences
govern: a field the rows hold open, and an absence the catalog drops.

Each report's catalog is rebuilt with today's code, with and without its
assertion rows, through the production readers. Then today's ``prepare`` runs
over each case with signed facts, on both catalog arms, as ``lane-replay
--prepare-today`` runs it. It reads ``evals/runs/``,
which git does not track, so the figures hold for this machine's archive.
Run from the repository root:

    PYTHONPATH=src:. python evals/experiments/QA-2026-11-25-01/census.py evals/runs evals/baselines
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from evals.harness.assertion_use import report_paths
from evals.harness.bundle import UnreadableReport, read_report
from evals.harness.lane_replay import prepare_today
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, load_case
from katra.assertions import hidden_qualifications
from katra.evidence import evidence_catalog, held_value
from katra.system_model import ModelIndex

ABSENT = re.compile(r"`(absent:[^`]+)`")
HELD = re.compile(r"but the sources leave it open")


def signed_cases() -> None:
    """Dropped absences and held-open entries in today's prepared material."""
    cases = sorted((REPO_ROOT / DEFAULT_CORPUS).glob("*/facts.json"))
    dropped = held = 0
    for facts in cases:
        case = load_case(facts.parent)
        none, signed = (
            json.dumps(prepare_today(case, "stride", arm).material)
            for arm in ("none", "signed")
        )
        dropped += len(set(ABSENT.findall(none)) - set(ABSENT.findall(signed)))
        held += len(HELD.findall(signed))
    print(f"cases with signed facts: {len(cases)}")
    print(f"dropped absences on the signed arm: {dropped}")
    print(f"held-open entries on the signed arm: {held}")


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
    signed_cases()


if __name__ == "__main__":
    main(sys.argv[1:])
