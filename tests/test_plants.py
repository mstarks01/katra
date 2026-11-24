"""Plants invert a control the case's model states, and never name a finding."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.harness import plants
from evals.harness.plants import (
    PLANT_ATTRIBUTES,
    PLANTS_PER_CASE,
    TEMPLATES,
    plants_for,
)
from evals.harness.reference import development_cases, load_corpus
from evals.harness.sitting import mark_targets
from katra.actions import ACTION_VERBS
from katra.analysis import CONTROL_ATTRIBUTES, control_state
from katra.frameworks.stride.record import LANES_OF_VERB, STRIDE_CATEGORIES
from katra.system_model import ModelIndex

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"
CASES = development_cases(load_corpus(CORPUS))

#: The words each template uses to say that the control is absent.
ABSENCE = {
    "authentication": "carries no authentication",
    "encryption_in_transit": "carries no encryption in transit",
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_each_plant_inverts_a_control_the_model_states(case):
    index = ModelIndex.of(case.model)
    for plant in plants_for(case):
        flow = index.get(plant.element_id)
        stated = getattr(flow, plant.attribute)
        assert control_state(stated) == "stated"
        assert plant.stated == stated
        assert ABSENCE[plant.attribute] in plant.claim
        assert flow.name in plant.claim


def test_the_corpus_gives_at_most_three_plants_a_case_and_some_cases_none():
    counts = {case.id: len(plants_for(case)) for case in CASES}
    assert all(count <= PLANTS_PER_CASE for count in counts.values())
    assert max(counts.values()) == PLANTS_PER_CASE
    assert 0 in counts.values()


def test_no_plant_key_names_a_recorded_finding():
    fingerprints = {
        name
        for case in load_corpus(CORPUS)
        for target in mark_targets(case)
        for name in (target.fingerprint, *target.aliases)
    }
    keys = [plant.key for case in load_corpus(CORPUS) for plant in plants_for(case)]
    assert keys
    assert not fingerprints & set(keys)
    assert len(set(keys)) == len(keys)


def test_the_choice_alternates_the_two_attributes_where_both_exist():
    case = next(case for case in CASES if case.id.startswith("14-"))
    assert [plant.attribute for plant in plants_for(case)] == [
        "authentication",
        "encryption_in_transit",
        "authentication",
    ]
    assert plants_for(case) == plants_for(case)


def test_a_case_with_no_stride_set_gets_no_plants(monkeypatch):
    case = CASES[0]
    monkeypatch.setattr(type(case), "frameworks", property(lambda self: ("asvs",)))
    assert plants_for(case) == ()


def test_the_template_table_is_keyed_by_the_attribute_literal():
    assert tuple(TEMPLATES) == PLANT_ATTRIBUTES
    assert set(PLANT_ATTRIBUTES) <= set(CONTROL_ATTRIBUTES)


def test_each_template_files_a_shipped_verb_in_a_lane_the_verb_allows():
    for template in TEMPLATES.values():
        assert template.category in STRIDE_CATEGORIES
        assert template.verb in ACTION_VERBS
        assert template.category in LANES_OF_VERB[template.verb]
    assert plants.PLANT_FRAMEWORK == "stride"
