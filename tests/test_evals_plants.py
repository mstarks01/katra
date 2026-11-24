"""The plant writer inverts a stated control, and its frames do not give it away."""

from __future__ import annotations

import random
from functools import cache

import pytest

from evals.harness import plants
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, development_cases, load_corpus
from katra.analysis import control_state

#: Each stated control of a development case that no plant inverts, with the
#: reading that skips it. A new skip fails until it is listed here, and a
#: listed skip that stops applying fails too.
SKIPPED: dict[tuple[str, str, str], plants.PlantReading] = {
    (
        "05-cookbook-queue-webapp",
        "flow:entity:browser>process:web-application>page-request",
        "encryption_in_transit",
    ): "no-mechanism",
    (
        "08-sso-identity-broker",
        (
            "flow:entity:franchise-identity-provider>process:identity-broker"
            ">vouch-for-colleague"
        ),
        "authentication",
    ): "no-mechanism",
    (
        "10-cookbook-generic-cms",
        "flow:entity:reader>process:web-server>page-requests",
        "authentication",
    ): "limited",
}


@cache
def _development():
    return development_cases(load_corpus(REPO_ROOT / DEFAULT_CORPUS))


def _all_plants(seeds: range) -> list[plants.Plant]:
    return [
        plant
        for seed in seeds
        for case in _development()
        for plant in plants.write_plants(case.id, case.model, random.Random(seed))
    ]


@pytest.mark.parametrize(
    ("value", "reading"),
    [
        ("unknown", "not-stated"),
        ("none", "not-stated"),
        ("", "not-stated"),
        ("TLS", "plantable"),
        ("session cookie issued after email and password login", "plantable"),
        ("sign-in exists for some readers; the mechanism is not stated", "limited"),
        ("the broker accepts the provider's assertion as a sign-in", "no-mechanism"),
        ("encrypted (marked as the one encrypted link)", "no-mechanism"),
    ],
)
def test_a_value_reads_as_its_control_states_it(value, reading):
    assert plants.plant_reading(value) == reading


def test_the_skipped_controls_of_the_development_cases_are_the_listed_ones():
    skipped = {
        (fact.case, fact.flow_id, fact.attribute): reading
        for case in _development()
        for fact, reading in plants.readings(case.id, case.model).items()
        if reading != "plantable"
    }

    assert skipped == SKIPPED


def test_each_plant_inverts_a_control_its_model_states():
    written = _all_plants(range(10))
    assert written, "the corpus gives no plant, so this checks nothing"

    models = {case.id: case.model for case in _development()}
    for plant in written:
        flow = models[plant.fact.case].get(plant.fact.flow_id)
        stated = getattr(flow, plant.fact.attribute)
        assert stated == plant.fact.stated
        assert control_state(stated) == "stated"
        assert plants.plant_reading(stated) == "plantable"
        assert plant.category == plants.CATEGORY[plant.fact.attribute]
        assert {
            "kind": "absent-attribute",
            "element_id": plant.fact.flow_id,
            "attribute": plant.fact.attribute,
        } in plant.view()["grounds"]


def test_a_plant_records_the_fact_it_inverts_beside_its_sentence():
    case = _development()[0]
    plant = plants.write_plants(case.id, case.model, random.Random(1))[0]

    written = plant.to_json()

    assert written["fact"] == {
        "case": case.id,
        "flow_id": plant.fact.flow_id,
        "attribute": plant.fact.attribute,
        "stated": plant.fact.stated,
    }
    assert written["title"] == plant.title


def test_one_seed_chooses_the_same_plants_and_another_seed_can_differ():
    case = next(c for c in _development() if len(plants.candidates(c.id, c.model)) > 3)

    def chosen(seed):
        return [
            (plant.fact, plant.title, plant.description)
            for plant in plants.write_plants(case.id, case.model, random.Random(seed))
        ]

    assert chosen(3) == chosen(3)
    assert len({tuple(chosen(seed)) for seed in range(10)}) > 1


def test_a_batch_holds_two_or_three_plants_or_every_candidate():
    for case in _development():
        held = len(plants.candidates(case.id, case.model))
        for seed in range(10):
            count = len(plants.write_plants(case.id, case.model, random.Random(seed)))
            assert count <= held
            assert count in plants.PLANTS_PER_BATCH or count == held


def _five_word_runs(plant: plants.Plant) -> set[tuple[str, ...]]:
    words = f"{plant.title} {plant.description}".casefold().split()
    return {tuple(words[n : n + 5]) for n in range(len(words) - 4)}


def test_no_five_word_run_is_in_every_plant():
    """An earlier writer opened 28 of 28 plants with one frame. Each attribute
    and the whole set are read apart, because a frame shared by one
    attribute's plants gives those plants away."""
    written = _all_plants(range(20))
    groups = {
        "every plant": written,
        **{
            attribute: [p for p in written if p.fact.attribute == attribute]
            for attribute in plants.PLANTED_ATTRIBUTES
        },
    }

    for name, group in groups.items():
        assert len(group) > 1, name
        shared = set.intersection(*(_five_word_runs(plant) for plant in group))
        assert shared == set(), name


@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        ("Web server", "the web server"),
        ("MySQL database", "the MySQL database"),
        ("CDN", "the CDN"),
        ("storefront API", "the storefront API"),
        ("Reader", "the reader"),
    ],
)
def test_an_element_name_becomes_a_noun_phrase(name, phrase):
    assert plants.noun_phrase(name) == phrase


@pytest.mark.parametrize(
    "table", ["CATEGORY", "TITLES", "DESCRIPTIONS", "CONSEQUENCES"]
)
def test_each_frame_table_answers_for_every_planted_attribute(table):
    assert set(getattr(plants, table)) == set(plants.PLANTED_ATTRIBUTES)
