"""Write the built input of QA-2026-11-25-01: case 01's blessed model with two
stated controls set to ``absent``, as an extraction that missed them writes.

The signed rows of case 01 state both controls, so today's ``prepare`` holds
each field open: the catalog offers no ``stated absent`` entry, and it offers
the row as an open question. The script prints what the lanes read for the
two fields on each catalog arm, and the signed arm's figures by
:func:`census.count`, the census's own counter (``build.txt``). Run from the
repository root:

    PYTHONPATH=src:. python evals/experiments/QA-2026-11-25-01/build.py
"""

import json
from collections import Counter
from pathlib import Path

from census import count

from evals.harness.lane_replay import built_input, prepare_today
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, load_case
from katra.graph import held_assertions
from katra.open_facts import prepared_model
from katra.system_model import ElementControl

CASE = "01-payments-checkout"
BUILT = (
    ("store:receipt-archive", "encryption_at_rest"),
    (
        "flow:process:order-service>store:receipt-archive>append-receipt",
        "encryption_in_transit",
    ),
)
OUT = Path(__file__).with_name("case01-built-model.json")


def main() -> None:
    model = load_case(REPO_ROOT / DEFAULT_CORPUS / CASE).model.model_copy(deep=True)
    elements = {element.id: element for element in model.elements()}
    for element_id, attribute in BUILT:
        setattr(elements[element_id], attribute, ElementControl(state="absent"))
    OUT.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    case = built_input(load_case(REPO_ROOT / DEFAULT_CORPUS / CASE), OUT)
    for arm in ("none", "signed"):
        material = json.dumps(prepare_today(case, "stride", arm).material)
        lines = material.replace("\\n", "\n").split("\n")
        print(f"== {arm}")
        for line in sorted(set(lines)):
            about = "receipt-archive" in line and "encryption" in line
            if line.startswith("|") and about:
                print(line)
    rows = held_assertions(prepare_today(case, "stride", "signed").state)
    counts: Counter[str] = Counter()
    count(prepared_model(case.model, rows), rows, counts)
    print("== signed, counted")
    for name, figure in counts.items():
        print(f"{name}: {figure}")


if __name__ == "__main__":
    main()
