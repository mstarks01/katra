"""The plant writer inverts a stated control, and its frames do not give it away."""

from __future__ import annotations

import random
from functools import cache

import pytest

from evals.harness import plants
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, development_cases, load_corpus
from evals.reference_facts import facts_path, load_facts
from katra.analysis import held_state, held_text

#: Each stated control of a development case that no plant inverts, with the
#: reading that skips it. A new skip fails until it is listed here, and a
#: listed skip that stops applying fails too.
SKIPPED: dict[tuple[str, str, str], plants.PlantReading] = {
    (
        "01-payments-checkout",
        "flow:entity:shopper>process:storefront-api>place-order",
        "authentication",
    ): "qualified",
    (
        "02-iot-fleet-telemetry",
        "flow:entity:sensor-node>process:device-gateway>publish-readings",
        "authentication",
    ): "qualified",
    (
        "03-batch-data-pipeline",
        "flow:entity:insurance-partner>store:landing-bucket>push-daily-extract",
        "authentication",
    ): "qualified",
    (
        "03-batch-data-pipeline",
        "flow:entity:data-analyst>store:claims-warehouse>run-queries",
        "authentication",
    ): "qualified",
    (
        "04-ml-inference-service",
        "flow:entity:calling-service>process:inference-gateway>submit-inference-request",
        "authentication",
    ): "qualified",
    (
        "05-cookbook-queue-webapp",
        "flow:entity:browser>process:web-application>page-request",
        "encryption_in_transit",
    ): "no-mechanism",
    (
        "07-cicd-store-deploy",
        "flow:process:build-runner>process:deploy-controller>set-current-release",
        "authentication",
    ): "qualified",
    (
        "08-sso-identity-broker",
        "flow:entity:franchise-identity-provider>process:identity-broker>vouch-for-colleague",
        "authentication",
    ): "qualified",
    (
        "08-sso-identity-broker",
        "flow:entity:colleague>process:store-admin-console>change-prices-and-void",
        "authentication",
    ): "qualified",
    (
        "10-cookbook-generic-cms",
        "flow:entity:reader>process:web-server>page-requests",
        "authentication",
    ): "qualified",
    (
        "13-dispatch-control-plane",
        "flow:process:schedule-importer>process:dispatch-api>post-work-orders",
        "authentication",
    ): "qualified",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:member>process:authorization-server>sign-in-and-consent",
        "authentication",
    ): "qualified",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:member>process:authorization-server>sign-in-and-consent",
        "encryption_in_transit",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:member>entity:partner-app>return-with-authorization-code",
        "encryption_in_transit",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:process:mobile-app>process:authorization-server>token-requests",
        "authentication",
    ): "qualified",
    (
        "14-loyalty-oauth-platform",
        "flow:process:mobile-app>process:authorization-server>token-requests",
        "encryption_in_transit",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:partner-app>process:authorization-server>token-requests",
        "authentication",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:partner-app>process:authorization-server>token-requests",
        "encryption_in_transit",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:process:mobile-app>process:rewards-api>call-rewards-api",
        "authentication",
    ): "qualified",
    (
        "14-loyalty-oauth-platform",
        "flow:process:mobile-app>process:rewards-api>call-rewards-api",
        "encryption_in_transit",
    ): "unsigned",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:partner-app>process:rewards-api>call-rewards-api",
        "authentication",
    ): "qualified",
    (
        "14-loyalty-oauth-platform",
        "flow:entity:partner-app>process:rewards-api>call-rewards-api",
        "encryption_in_transit",
    ): "unsigned",
    (
        "15-multitenant-invoicing",
        "flow:entity:company-user>process:billing-app>manage-invoices",
        "authentication",
    ): "qualified",
    (
        "15-multitenant-invoicing",
        "flow:entity:company-user>process:billing-app>manage-invoices",
        "encryption_in_transit",
    ): "unsigned",
    (
        "15-multitenant-invoicing",
        "flow:entity:payer>process:billing-app>open-payment-page",
        "encryption_in_transit",
    ): "unsigned",
    (
        "15-multitenant-invoicing",
        "flow:process:billing-app>store:tenant-database>read-and-write-tenant-data",
        "authentication",
    ): "unsigned",
    (
        "15-multitenant-invoicing",
        "flow:process:billing-app>store:pdf-bucket>fetch-pdfs",
        "authentication",
    ): "unsigned",
    (
        "15-multitenant-invoicing",
        "flow:entity:support-agent>process:admin-console>use-admin-console",
        "authentication",
    ): "unsigned",
}


@cache
def _development():
    return development_cases(load_corpus(REPO_ROOT / DEFAULT_CORPUS))


def _facts(case_id):
    """A case's signed facts, or ``None`` for a case with no facts file."""
    case_dir = REPO_ROOT / DEFAULT_CORPUS / case_id
    return load_facts(case_dir) if facts_path(case_dir).is_file() else None


def _all_plants(seeds: range) -> list[plants.Plant]:
    return [
        plant
        for seed in seeds
        for case in _development()
        for plant in plants.write_plants(
            case.id, case.model, _facts(case.id), {}, random.Random(seed)
        )
    ]


@pytest.mark.parametrize(
    ("value", "reading"),
    [
        ("unknown", "not-stated"),
        ("none", "not-stated"),
        ("", "not-stated"),
        ("TLS", "plantable"),
        ("session cookie issued after email and password login", "plantable"),
        ("sign-in exists for some readers; the mechanism is not stated", "qualified"),
        ("plain HTTP, no TLS", "qualified"),
        ("HTTP without TLS", "qualified"),
        ("password, except the health endpoint", "qualified"),
        ("TLS is never enforced", "qualified"),
        ("mTLS, neither side checks the certificate", "qualified"),
        ("password; the API cannot verify tokens", "qualified"),
        ("token checked if present", "qualified"),
        ("HTTPS in production; HTTP in staging", "qualified"),
        ("API key, but the gateway doesn't check it", "qualified"),
        ("TLS, though the certificate isn't checked", "qualified"),
        ("deprecated API key", "qualified"),
        ("customer-managed key", "plantable"),
        ("the broker treats the provider's assertion as a sign-in", "no-mechanism"),
        ("encrypted (marked as the one encrypted link)", "no-mechanism"),
    ],
)
def test_a_value_reads_as_its_control_states_it(value, reading):
    assert plants.plant_reading(value) == reading


def test_the_skipped_controls_of_the_development_cases_are_the_listed_ones():
    skipped = {
        (fact.case, fact.element_id, fact.attribute): reading
        for case in _development()
        for fact, reading in plants.readings(
            case.id, case.model, _facts(case.id), {}
        ).items()
        if reading != "plantable"
    }

    assert skipped == SKIPPED


def test_each_plant_inverts_a_control_its_model_states():
    written = _all_plants(range(10))
    assert written, "the corpus gives no plant, so this checks nothing"

    models = {case.id: case.model for case in _development()}
    for plant in written:
        element = models[plant.fact.case].get(plant.fact.element_id)
        stated = getattr(element, plant.fact.attribute)
        assert held_text(stated) == plant.fact.stated
        assert held_state(stated) == "stated"
        assert plants.plant_reading(stated) == "plantable"
        assert plant.category == plants.CATEGORY[plant.fact.attribute]
        assert {
            "kind": "absent-attribute",
            "element_id": plant.fact.element_id,
            "attribute": plant.fact.attribute,
        } in plant.view()["grounds"]


def test_a_plant_records_the_fact_it_inverts_beside_its_sentence():
    case = _development()[0]
    plant = plants.write_plants(
        case.id, case.model, _facts(case.id), {}, random.Random(1)
    )[0]

    written = plant.to_json()

    assert written["fact"] == {
        "case": case.id,
        "element_id": plant.fact.element_id,
        "attribute": plant.fact.attribute,
        "stated": plant.fact.stated,
    }
    assert written["title"] == plant.title


def test_one_seed_chooses_the_same_plants_and_another_seed_can_differ():
    case = next(
        c
        for c in _development()
        if len(plants.candidates(c.id, c.model, _facts(c.id), {})) > 3
    )

    def chosen(seed):
        return [
            (plant.fact, plant.title, plant.description)
            for plant in plants.write_plants(
                case.id, case.model, _facts(case.id), {}, random.Random(seed)
            )
        ]

    assert chosen(3) == chosen(3)
    assert len({tuple(chosen(seed)) for seed in range(10)}) > 1


def test_a_batch_holds_two_or_three_plants_or_every_candidate():
    for case in _development():
        held = len(plants.candidates(case.id, case.model, _facts(case.id), {}))
        for seed in range(10):
            count = len(
                plants.write_plants(
                    case.id, case.model, _facts(case.id), {}, random.Random(seed)
                )
            )
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


def test_each_plant_inverts_a_control_a_signed_fact_states():
    """The model's value is not enough: a person signed that the source states
    the control on that element."""
    for plant in _all_plants(range(10)):
        assert (plant.fact.element_id, plant.fact.attribute) in plants.signed_controls(
            _facts(plant.fact.case)
        )


def test_a_case_with_no_signed_facts_gets_no_plant():
    case = next(
        c for c in _development() if plants.candidates(c.id, c.model, _facts(c.id), {})
    )

    assert plants.candidates(case.id, case.model, None, {}) == ()
    assert plants.write_plants(case.id, case.model, None, {}, random.Random(1)) == ()


def test_a_negated_model_value_gives_no_plant_whatever_the_signed_row_says():
    case = next(
        c for c in _development() if plants.candidates(c.id, c.model, _facts(c.id), {})
    )
    fact = plants.candidates(case.id, case.model, _facts(case.id), {})[0]
    element = case.model.get(fact.element_id)
    changed = element.model_copy(update={fact.attribute: "plain HTTP, no TLS"})
    groups = {
        group: [
            changed if e.id == element.id else e for e in getattr(case.model, group)
        ]
        for group in ("data_flows", "data_stores")
    }
    model = case.model.model_copy(update=groups)

    assert fact.element_id not in {
        f.element_id
        for f in plants.candidates(case.id, model, _facts(case.id), {})
        if f.attribute == fact.attribute
    }
