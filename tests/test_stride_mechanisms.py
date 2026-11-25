"""The attacker mechanisms a STRIDE lane accounts for at each led place (#2204).

The list is code's own reading of the System Model: each position needs a path
the model shows. The tests hold that reading on the corpus's blessed models,
and they hold the list to the six must-finds QA-2026-11-24-01 traced to a lane
that wrote another attacker at the same place. Only the tests read a
reference; the list is built from the model alone.
"""

import json

import pytest

from evals.harness.lane_replay import prepare_today
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, load_case, load_corpus
from katra.candidates import Mechanism, no_mechanisms
from katra.frameworks import PACKAGES
from katra.frameworks.stride.record import STRIDE_CATEGORIES
from katra.frameworks.stride.rules import MECHANISM_LANES, mechanisms_at
from katra.graph import unfence


def model_of(case_id):
    return load_case(REPO_ROOT / DEFAULT_CORPUS / case_id).model


def listed(model, lane, place):
    return {
        (one.position, one.via) for one in mechanisms_at(model, lane, [place])[place]
    }


CMS = "10-cookbook-generic-cms"
READER_FLOW = "flow:entity:reader>process:web-server>page-requests"


def test_each_lane_states_whether_its_leads_carry_the_list():
    assert set(MECHANISM_LANES) == set(STRIDE_CATEGORIES)
    assert {lane for lane, carried in MECHANISM_LANES.items() if carried} == {
        "tampering",
        "information-disclosure",
    }


def test_a_lane_without_the_list_gets_none():
    model = model_of(CMS)
    assert mechanisms_at(model, "spoofing", ["process:web-server"]) == {}


def test_an_unknown_lane_is_refused():
    with pytest.raises(KeyError):
        mechanisms_at(model_of(CMS), "no-such-lane", ["process:web-server"])


def test_a_package_whose_claims_name_no_position_lists_none():
    assert PACKAGES["asvs"].mechanisms is no_mechanisms
    assert no_mechanisms(model_of(CMS), "anything", ["process:web-server"]) == {}


def test_a_flow_lists_its_path_its_ends_and_an_outside_party_on_a_crossing():
    assert listed(model_of(CMS), "tampering", READER_FLOW) == {
        ("on-path", READER_FLOW),
        ("authorized-principal", "entity:reader"),
        ("in-component", "process:web-server"),
        ("outside", READER_FLOW),
    }


def test_a_store_lists_a_copy_and_every_element_with_a_flow_to_it():
    assert listed(model_of(CMS), "information-disclosure", "store:mysql-database") == {
        ("storage-copy", "store:mysql-database"),
        ("in-component", "process:web-server"),
        ("authorized-principal", "process:web-server"),
        ("on-path", "flow:process:web-server>store:mysql-database>cms-data"),
        ("authorized-principal", "entity:admin"),
        ("on-path", "flow:entity:admin>store:mysql-database>direct-administration"),
    }


def test_a_process_lists_its_own_code_and_each_caller():
    assert listed(model_of(CMS), "tampering", "process:web-server") == {
        ("in-component", "process:web-server"),
        ("authorized-principal", "entity:reader"),
        ("on-path", READER_FLOW),
        ("outside", READER_FLOW),
    }


def test_an_entity_is_no_led_place():
    assert mechanisms_at(model_of(CMS), "tampering", ["entity:reader"]) == {}


@pytest.mark.parametrize(
    "case_id", [case.id for case in load_corpus(REPO_ROOT / DEFAULT_CORPUS)]
)
def test_every_listed_mechanism_names_a_path_the_model_shows(case_id):
    """No mechanism names an element the model lacks, and an outside party
    comes only through a decided crossing."""
    model = model_of(case_id)
    ids = {element.id for element in model.elements()}
    crossing = {found.flow_id for found in model.boundary_crossings() if found.decided}
    for lane in ("tampering", "information-disclosure"):
        for entries in mechanisms_at(model, lane, sorted(ids)).values():
            assert len(entries) == len(set(entries))
            for one in entries:
                assert one.via in ids
                if one.position == "outside":
                    assert one.via in crossing


#: The six target rows of QA-2026-11-17-13: the place the lane was led to,
#: and the mechanism a correct draft takes there.
TARGETS = [
    (
        "02-iot-fleet-telemetry",
        "store:firmware-bucket",
        "tampering",
        Mechanism(position="authorized-principal", via="entity:sensor-node"),
    ),
    (
        "03-batch-data-pipeline",
        "store:claims-warehouse",
        "information-disclosure",
        Mechanism(position="authorized-principal", via="entity:data-analyst"),
    ),
    (
        "06-cookbook-online-game",
        "flow:process:game-client>process:game-server>gameplay-traffic",
        "tampering",
        Mechanism(position="in-component", via="process:game-client"),
    ),
    (
        "09-cookbook-sokify-retail",
        "flow:process:catalogue-spreadsheet>process:web-api>sql-statements",
        "tampering",
        Mechanism(position="in-component", via="process:catalogue-spreadsheet"),
    ),
    (
        CMS,
        "process:web-server",
        "tampering",
        Mechanism(position="outside", via=READER_FLOW),
    ),
    (
        "13-dispatch-control-plane",
        "flow:process:dispatch-console>process:dispatch-api>dispatch-requests",
        "information-disclosure",
        Mechanism(
            position="outside",
            via="flow:process:dispatch-console>process:dispatch-api>dispatch-requests",
        ),
    ),
]


@pytest.mark.parametrize(("case_id", "place", "lane", "expected"), TARGETS)
def test_the_lane_block_lists_the_target_mechanism(case_id, place, lane, expected):
    """Through the graph's own reader of what a lane is given."""
    prepared = prepare_today(
        load_case(REPO_ROOT / DEFAULT_CORPUS / case_id), "stride", "none"
    )
    key = f"candidates_stride_{lane.replace('-', '_')}"
    block = json.loads(unfence(prepared.state[key]))
    assert expected.model_dump() in block["mechanisms"][place]


def test_a_lane_with_no_list_gets_no_mechanisms_key():
    prepared = prepare_today(
        load_case(REPO_ROOT / DEFAULT_CORPUS / CMS), "stride", "none"
    )
    block = json.loads(unfence(prepared.state["candidates_stride_spoofing"]))
    assert "mechanisms" not in block
