"""The #2204 Phase 1 trace of QA-2026-11-24-01: one row per STRIDE must-find.

Usage::

    KATRA_OFFLINE=1 PYTHONPATH=src:. python trace.py <run dir> <corpus> <verb rows csv | -> <out dir>

``<run dir>`` holds the case artifacts of one run. ``<verb rows csv>`` is
``evals/experiments/QA-2026-11-17-13/verb-rows.csv`` for the 2026-10-24 sweep,
and ``-`` for a run that no verb ruling reads. The script writes ``trace.csv``
and ``summary.txt`` into ``<out dir>``.

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

#: The six references the QA-2026-11-17-13 design targets, by case ID and
#: reference index.
TARGET_REFERENCES = frozenset(
    {
        ("02-iot-fleet-telemetry", 3),
        ("03-batch-data-pipeline", 8),
        ("06-cookbook-online-game", 3),
        ("09-cookbook-sokify-retail", 4),
        ("10-cookbook-generic-cms", 17),
        ("13-dispatch-control-plane", 19),
    }
)

#: The causes QA-2026-11-19-01-E4 found for the ``unled`` references it traced,
#: with the maintainer's decision of 2026-11-19, by case ID and reference index.
UNLED_CAUSES = {
    ("06-cookbook-online-game", 15): (
        "the fact is present and no rule leads it (QA-2026-11-19-01-E4)",
        "lead rule C1a, kept to batch (QA-2026-11-19-01-E5)",
    ),
    ("09-cookbook-sokify-retail", 18): (
        "the fact is present and no rule leads it (QA-2026-11-19-01-E4)",
        "lead rule C5b, kept to batch (QA-2026-11-19-01-E5)",
    ),
    ("08-sso-identity-broker", 19): (
        "the extraction did not produce the credential placement (QA-2026-11-19-01-E4)",
        "an extraction gap, by the maintainer's decision of 2026-11-19",
    ),
}

#: What each run mode shows for every row of its run.
SOURCES = {"analysis": "analysis mode: the lanes read the case's blessed model"}

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

    A matched row and the causes ``unstated``, ``verb``, ``position``,
    ``place`` and ``unled`` each have a rule. A verb ruling is ``different`` or
    empty. Any other cause of ``losses.Cause``, and any other ruling, raise:
    this audit has no evidence for them.
    """
    cause = row["cause"]
    key = (row["case"], row["reference_index"])
    if verb_row is not None and cause != "verb":
        raise ValueError(
            f"{row['case']} #{row['reference_index']}: a verb ruling on a row"
            f" charged to {cause!r}"
        )
    if row["status"] == "matched":
        return (
            "none: a structural match",
            "run.py scorecard",
            "the meaning is unreviewed",
            "rule the match by meaning",
        )
    if cause == "unstated":
        return (
            "reference or scorer mismatch: the draft states no attacker position",
            "run.py scorecard",
            "the earliest loss is unknown",
            "a run of today's contract",
        )
    if cause == "verb" and verb_row is None:
        return (
            "generation: another verb at the place",
            "run.py scorecard; run.py delivery",
            "the meaning is unruled",
            "a Phase 2 target" if key in TARGET_REFERENCES else "rule by meaning",
        )
    if cause == "verb" and verb_row["ruling"] == "":
        return (
            "reference or scorer mismatch: the draft at the place states no attacker position",
            "QA-2026-11-17-13 verb-rows.csv; run.py delivery",
            "no ruling can move it on the archive",
            "a run of today's contract",
        )
    if cause == "verb" and verb_row["ruling"] == "different":
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
    if cause == "position":
        return (
            "generation: the draft states another attacker position",
            "run.py scorecard; run.py delivery",
            "a corpus ruling on the reference's position is the alternative",
            "a Phase 2 target"
            if key in TARGET_REFERENCES
            else "rule the reference's position or the draft",
        )
    if cause == "place":
        return (
            "unresolved: the lane had the place and filed no draft there",
            "run.py delivery",
            "a rule led the lane to the place",
            "a run of today's contract",
        )
    if cause == "unled":
        uncertainty, action = UNLED_CAUSES.get(
            key,
            (
                "no traced cause: QA-2026-11-19-01-E4 did not read this reference",
                "trace the cause",
            ),
        )
        return (
            "unresolved: no lead reached the place",
            "run.py delivery",
            uncertainty,
            action,
        )
    raise ValueError(
        f"{row['case']} #{row['reference_index']}: no attribution rule for"
        f" status {row['status']!r}, cause {cause!r},"
        f" ruling {None if verb_row is None else verb_row['ruling']!r}"
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
    artifact = load_artifact(artifact_path)
    source = SOURCES[artifact.mode]
    traced = delivery.trace(card, artifact, cases, corpus)
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
            "source": source,
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


def read_verb_rows(verb_csv):
    """The QA-2026-11-17-13 verb rows by case and reference, or none for ``-``."""
    if str(verb_csv) == "-":
        return {}
    with verb_csv.open(encoding="utf-8", newline="") as handle:
        return {
            (row["case"], int(row["reference"])): row for row in csv.DictReader(handle)
        }


def main(run_dir, corpus, verb_csv, out_dir):
    verb_rows = read_verb_rows(verb_csv)
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
