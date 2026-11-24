"""The #2204 Phase 1 trace of QA-2026-11-24-01: one row per STRIDE must-find.

Usage::

    KATRA_OFFLINE=1 PYTHONPATH=src:. python trace.py <run dir> <corpus> <verb rows csv> <out dir>

``<run dir>`` holds the case artifacts of the 2026-10-24 sweep. ``<verb rows
csv>`` is ``evals/experiments/QA-2026-11-17-13/verb-rows.csv``. The script
writes ``trace.csv`` and ``summary.txt`` into ``<out dir>``.

Each row joins two shipped readings, the scorecard and the delivery trace, with
the verb-row rulings and classification that QA-2026-11-17-13 recorded. The
``attribution`` column applies the rules in :func:`attribute` to those
readings; it is not a ruling.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

from evals.harness import delivery, ledger
from evals.harness.artifact import load_artifact
from evals.harness.reference import development_cases, load_corpus
from evals.harness.run import scorecard_of

#: The draft mechanisms that the QA-2026-11-17-13 design targets.
TARGETED = frozenset({"on-path", "storage-copy"})

#: What the sweep's mode shows for every row: the lanes read the signed model.
SOURCE = "analysis mode: the lanes read the signed model; extraction is not on the path"

FIELDS = (
    "case",
    "reference",
    "lane",
    "verb",
    "elements",
    "ruled_position",
    "status",
    "cause",
    "lead_rules",
    "source",
    "delivery",
    "drafted",
    "reported",
    "draft",
    "verb_ruling",
    "draft_mechanism",
    "downstream",
    "attribution",
    "evidence",
    "uncertainty",
    "next_action",
)


def attribute(row, verb_row):
    """The attribution, evidence, uncertainty and next action of one row.

    A matched row and the causes ``unstated``, ``verb``, ``place`` and ``unled``
    each have a rule. Any other cause of ``losses.Cause``, and a ``verb`` row
    that QA-2026-11-17-13 did not read, raise: this audit has no evidence for
    them.
    """
    cause = row["cause"]
    if row["status"] == "matched":
        return (
            "none: a structural match",
            "run.py scorecard",
            "the meaning is unreviewed, and the archive states no position",
            "rule the position on a sweep of today's contract",
        )
    if cause == "unstated":
        return (
            "reference or scorer mismatch: the archive has no position field",
            "run.py scorecard",
            "the earliest loss is unknown",
            "a sweep of today's contract",
        )
    if cause == "verb" and verb_row is not None:
        if verb_row["ruling"] != "different":
            return (
                "reference or scorer mismatch: the ruled position is unstated",
                "QA-2026-11-17-13 verb-rows.csv; run.py delivery",
                "no ruling can move it on the archive",
                "a sweep of today's contract",
            )
        mechanism = verb_row["draft_mechanism"]
        return (
            f"generation substitution: the draft states {mechanism}",
            (
                "maintainer ruling 'different'; QA-2026-11-17-13 verb-rows.csv;"
                " run.py delivery"
            ),
            "the mechanism label is a classification no person reviewed",
            "a Phase 2 target"
            if mechanism in TARGETED
            else "a second signature; read, not targeted",
        )
    if cause == "place":
        return (
            "unresolved: associated with the generation outcome",
            "run.py delivery; QA-2026-11-17-12-E4",
            "a rule led the lane to the place, and the lane filed no draft there",
            "a sweep of today's contract",
        )
    if cause == "unled":
        return (
            "unresolved: associated with the generation outcome",
            "run.py delivery; QA-2026-11-17-12-E4",
            (
                "no rule led the lane to the place; the facts that would lead it"
                " are not traced"
            ),
            "authority facts (#2054 group 2)"
            if row["lane"] == "elevation-of-privilege"
            else "a lead rule for the place, priced offline",
        )
    raise ValueError(
        f"{row['case']} #{row['reference_index']}: no attribution rule for"
        f" status {row['status']!r}, cause {cause!r}"
    )


def delivered(traced):
    """One traced miss as the delivery command words it."""
    comparison = traced.lane.comparison
    compared = "untraced" if comparison is None else comparison.describe()
    return f"{compared}; {traced.place_facts.describe()}"


def downstream(card):
    """What the fan-in and the critic did to one case's reference-matched drafts."""
    fan_in, loss = card.fan_in, card.critic.reference_loss
    return (
        f"fan-in: {fan_in.accounted} of {fan_in.inspected} proposals accounted,"
        f" {fan_in.unexplained} unexplained; critic: {loss.denominator}"
        " reference-matched drafts left the report"
    )


def case_rows(artifact_path, corpus, cases, verb_rows):
    """Every must-find row of one case artifact."""
    card = scorecard_of(artifact_path, corpus, ledger.Ledger())
    traced = delivery.trace(card, load_artifact(artifact_path), cases, corpus)
    by_key = {
        (row.reference.case, row.reference.reference_index): delivered(row)
        for row in traced.rows
    }
    below = downstream(card)
    for reference in card.rows:
        row = reference.to_json()
        key = (row["case"], row["reference_index"])
        verb_row = verb_rows.get(key)
        attribution, evidence, uncertainty, action = attribute(row, verb_row)
        yield {
            "case": row["case"],
            "reference": row["reference_index"],
            "lane": row["lane"],
            "verb": row["verb"],
            "elements": " | ".join(row["elements"]),
            "ruled_position": row["ruled_position"] or "",
            "status": row["status"],
            "cause": row["cause"] or "",
            "lead_rules": " | ".join(row["lead_rules"]),
            "source": SOURCE,
            "delivery": by_key.get(key, "not a charged miss"),
            "drafted": row["stages"]["drafted"],
            "reported": row["stages"]["reported"],
            "draft": verb_row["draft"] if verb_row else "",
            "verb_ruling": verb_row["ruling"] if verb_row else "",
            "draft_mechanism": verb_row["draft_mechanism"] if verb_row else "",
            "downstream": below,
            "attribution": attribution,
            "evidence": evidence,
            "uncertainty": uncertainty,
            "next_action": action,
        }


def main(run_dir, corpus, verb_csv, out_dir):
    with verb_csv.open(encoding="utf-8", newline="") as handle:
        verb_rows = {
            (row["case"], int(row["reference"])): row for row in csv.DictReader(handle)
        }
    cases = development_cases(load_corpus(corpus))
    rows = sorted(
        (
            row
            for path in sorted(run_dir.glob("[0-9]*.json"))
            for row in case_rows(path, corpus, cases, verb_rows)
        ),
        key=lambda row: (row["case"], row["reference"]),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "trace.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    by_attribution = Counter(row["attribution"].split(":")[0] for row in rows)
    by_action = Counter(row["next_action"] for row in rows)
    lines = [f"{len(rows)} must-finds", "", "by attribution:"]
    lines += [f"  {count:3d}  {name}" for name, count in by_attribution.most_common()]
    lines += ["", "by next action:"]
    lines += [f"  {count:3d}  {name}" for name, count in by_action.most_common()]
    (out_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(*(Path(argument) for argument in sys.argv[1:5]))
