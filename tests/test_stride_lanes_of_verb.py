"""#442: which lanes an action verb may be filed in is a table, not a judgement."""

from __future__ import annotations

import json
from pathlib import Path

from katra.actions import ACTION_VERBS
from katra.frameworks.stride import STRIDE
from katra.frameworks.stride.record import LANES_OF_VERB, DraftThreat
from tests.factories import sample_draft

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def test_the_table_covers_every_verb_and_names_only_real_lanes():
    assert set(LANES_OF_VERB) == ACTION_VERBS
    for verb, lanes in LANES_OF_VERB.items():
        assert lanes, f"{verb} is filed nowhere"
        assert set(lanes) <= set(STRIDE.lanes), f"{verb} names a lane STRIDE lacks"


def test_no_blessed_reference_is_misfiled_by_the_table():
    """The table can never sit narrower than the corpus files its verbs."""
    misfiled = [
        (path.parent.parent.name, claim["verb"], claim["category"])
        for path in sorted(CORPUS.glob("*/claims/stride.json"))
        for claim in json.loads(path.read_text("utf-8"))
        if claim["category"] not in LANES_OF_VERB[claim["verb"]]
    ]
    assert misfiled == []


def test_a_verb_outside_its_lane_is_named_with_the_lanes_it_belongs_to():
    draft = sample_draft("S-01", verb="flood")

    reason = DraftThreat.misfiled(draft)

    assert "'flood'" in reason
    assert "denial-of-service" in reason
    assert DraftThreat.misfiled(sample_draft("S-01", verb="impersonate")) == ""


def test_no_ruled_position_disagrees_with_the_position_a_verb_fixes():
    """#2369: the table can never fix a position the corpus rules otherwise."""
    from katra.frameworks.stride.record import POSITION_OF_VERB

    ruled = [
        (path.parent.name, row["reference"]["verb"], row["position"])
        for path in sorted(CORPUS.glob("*/rulings.json"))
        for row in json.loads(path.read_text("utf-8")).get("positions", [])
    ]
    disagree = [
        (case, verb, position)
        for case, verb, position in ruled
        if verb in POSITION_OF_VERB and POSITION_OF_VERB[verb] != position
    ]
    fixed = [row for row in ruled if row[1] in POSITION_OF_VERB]

    assert disagree == []
    assert len(fixed) == 18


def test_code_writes_the_position_a_verb_fixes():
    from tests.factories import sample_proposal

    proposal = sample_proposal("I-01", "information-disclosure", verb="intercept")
    written = proposal.model_copy(update={"attacker_position": "outside"})

    again = type(proposal).model_validate(written.model_dump())

    assert again.attacker_position == "on-path"
