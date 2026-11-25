"""Recompute the -E2 draft counts and matched must-finds from the saved runs.

Offline: today's ``prepare`` over the changed model of case 01 on the signed
arm, and :func:`~evals.harness.descendants.lane_must_finds` over each saved
lane answer, as ``lane-replay`` printed them. Run from the repository root:

    PYTHONPATH=src:. python evals/experiments/QA-2026-11-25-01/e2/e2_summary.py
"""

import json
from pathlib import Path
from statistics import mean, median

from evals.harness.descendants import FRAMEWORK, lane_must_finds
from evals.harness.lane_replay import parse, prepare_today, with_system_model
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, load_case
from katra.claims import ProposalBatch

HERE = Path(__file__).parent
MODEL = HERE.parent / "case01-system-model.json"


def main() -> None:
    case = with_system_model(
        load_case(REPO_ROOT / DEFAULT_CORPUS / "01-payments-checkout"), MODEL
    )
    state = prepare_today(case, FRAMEWORK, "signed").state
    figures: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for path in sorted((HERE / "runs").glob("*.json")):
        arm, rest = path.stem.split("-", 1)
        lane, _ = rest.rsplit("-", 1)
        claims = json.loads(path.read_text(encoding="utf-8"))["claims"]
        batch = parse(json.dumps({"claims": claims}), FRAMEWORK)
        assert isinstance(batch, ProposalBatch)
        matched = lane_must_finds(case, state, lane, batch)
        figures.setdefault((lane, arm), []).append((len(claims), len(matched)))
        print(f"{path.stem}: {len(claims)} drafts, must-finds {list(matched)}")
    for (lane, arm), runs in sorted(figures.items()):
        drafts = [count for count, _ in runs]
        found = [count for _, count in runs]
        print(
            f"{lane} {arm}: mean drafts {mean(drafts):.1f},"
            f" median must-finds {median(found)}"
        )


if __name__ == "__main__":
    main()
