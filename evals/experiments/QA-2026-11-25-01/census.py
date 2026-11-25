"""Count, over archived reports, the inputs that #2307's prompt sentences
govern: a field the rows hold open, and an absence the catalog drops.

Each report's catalog is rebuilt with today's code, with and without its
assertion rows, through the production readers. Then today's ``prepare`` runs
over each case with signed facts, on both catalog arms, as ``lane-replay
--prepare-today`` runs it, and its model and rows are counted the same way.
It reads ``evals/runs/``, which git does not track, so the archive figures
hold for this machine's archive. Run from the repository root:

    PYTHONPATH=src:. python evals/experiments/QA-2026-11-25-01/census.py evals/runs evals/baselines
"""

import sys
from collections import Counter
from pathlib import Path

from evals.harness.assertion_use import report_paths
from evals.harness.bundle import UnreadableReport, read_report
from evals.harness.lane_replay import prepare_today
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, load_case
from katra.assertions import AssertionCatalog, hidden_qualifications
from katra.evidence import evidence_catalog
from katra.graph import held_assertions
from katra.open_facts import prepared_model
from katra.system_model import SystemModel


def count(model: SystemModel, rows: AssertionCatalog, counts: Counter[str]) -> None:
    """Add one catalog's hidden qualifications and dropped absences to ``counts``."""
    bare = evidence_catalog(model)
    full = evidence_catalog(model, rows)
    counts["rows"] += len(rows.entries)
    counts["hidden qualifications"] += len(hidden_qualifications(rows, model))
    counts["dropped absences"] += sum(
        ground.kind == "absent-attribute" and ref not in full
        for ref, ground in bare.items()
    )


def archive(roots: list[str]) -> Counter[str]:
    """Each archived report with an assertion pass."""
    counts: Counter[str] = Counter()
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
        count(report.system_model, report.assertions.catalog, counts)
    return counts


def signed_cases() -> Counter[str]:
    """Today's ``prepare`` on the signed arm over each case with signed facts."""
    counts: Counter[str] = Counter()
    for facts in sorted((REPO_ROOT / DEFAULT_CORPUS).glob("*/facts.json")):
        case = load_case(facts.parent)
        rows = held_assertions(prepare_today(case, "stride", "signed").state)
        counts["cases"] += 1
        count(prepared_model(case.model, rows), rows, counts)
    return counts


def main(roots: list[str]) -> None:
    for title, counts in (("archive", archive(roots)), ("signed", signed_cases())):
        print(f"== {title}")
        for name, figure in counts.items():
            print(f"{name}: {figure}")


if __name__ == "__main__":
    main(sys.argv[1:])
