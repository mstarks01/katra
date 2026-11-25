"""A control field holds its state as a field (#2366).

The model writes ``state`` and ``detail``, and the live gate refuses a control
written as one string. A recorded emission, a Baseline and a stored report
hold the string, and one archive reader reads it by the first-word rule.
"""

import pytest
from pydantic import ValidationError

from katra.analysis import control_reading, held_state, held_text
from katra.compact import FULL_FORMAT, parse_extraction
from katra.fact_answers import (
    answered_control,
    control_answer,
    control_answer_issue,
)
from katra.system_model import (
    LIVE_CONTEXT,
    DataFlow,
    ElementControl,
    SystemModel,
    control_from_text,
    control_text,
)
from katra.validation import parse_and_validate
from tests.factories import valid_model


@pytest.mark.parametrize(
    ("state", "reading"),
    [("stated", "stated"), ("absent", "absent"), ("unknown", "unverified")],
)
def test_each_state_reads_through_the_one_mapping(state, reading):
    control = ElementControl(state=state, detail="the words")
    assert control_reading(control) == reading
    assert held_state(control) == reading


def test_a_stated_control_names_its_mechanism():
    with pytest.raises(ValidationError, match="mechanism"):
        ElementControl(state="stated", detail="  ")


@pytest.mark.parametrize("state", ["absent", "unknown"])
def test_an_absent_or_unknown_control_needs_no_detail(state):
    assert ElementControl(state=state).detail == ""


def test_a_state_outside_the_set_is_refused():
    with pytest.raises(ValidationError):
        ElementControl.model_validate({"state": "partial", "detail": "x"})


@pytest.mark.parametrize(
    ("archived", "state", "detail"),
    [
        ("", "unknown", ""),
        ("unknown", "unknown", ""),
        ("unknown; the team never said", "unknown", "the team never said"),
        ("none", "absent", ""),
        ("None", "absent", ""),
        (
            "none; accepted by network position",
            "absent",
            "accepted by network position",
        ),
        ("TLS 1.3", "stated", "TLS 1.3"),
        ("no MFA on the login", "stated", "no MFA on the login"),
        ("nonexistent control", "stated", "nonexistent control"),
    ],
)
def test_the_archive_reader_reads_each_old_spelling(archived, state, detail):
    assert control_from_text(archived) == ElementControl(state=state, detail=detail)


@pytest.mark.parametrize(
    "archived",
    ["unknown", "unknown; why", "none", "none; accepted by network position", "mTLS"],
)
def test_the_text_of_an_archived_control_is_the_string_it_was_read_from(archived):
    """Agents read the same words a recorded emission held."""
    assert control_text(control_from_text(archived)) == archived


def test_a_model_read_outside_the_live_context_takes_an_archived_string():
    data = valid_model().model_dump(mode="json")
    data["data_flows"][0]["authentication"] = "none; by network position"
    model = SystemModel.model_validate(data)
    assert model.data_flows[0].authentication == ElementControl(
        state="absent", detail="by network position"
    )


def test_the_live_context_refuses_a_control_written_as_a_string():
    data = valid_model().model_dump(mode="json")
    data["data_flows"][0]["authentication"] = "session cookie"
    with pytest.raises(ValidationError, match="never a string"):
        SystemModel.model_validate(data, context=LIVE_CONTEXT)


def test_the_gate_refuses_a_control_written_as_a_string():
    """A model's output reaches the gate through ``parse_and_validate``."""
    data = valid_model().model_dump(mode="json")
    data["data_stores"][0]["encryption_at_rest"] = "unknown"
    model, issues = parse_and_validate(data, normalize_ids=True)
    assert model is None
    assert [issue.code for issue in issues] == ["schema"]
    assert "encryption_at_rest" in issues[0].message


def test_the_extraction_gate_refuses_it_and_a_replay_reads_it():
    data = valid_model().model_dump(mode="json")
    data["data_flows"][0]["encryption_in_transit"] = "TLS 1.3"
    live, issues = parse_extraction(data, FULL_FORMAT, sources={}, diagrams={})
    assert live is None
    assert issues[0].code == "schema"
    replayed, _ = parse_extraction(
        data, FULL_FORMAT, sources={}, diagrams={}, archived=True
    )
    assert replayed is not None
    assert replayed.data_flows[0].encryption_in_transit == ElementControl(
        state="stated", detail="TLS 1.3"
    )


def test_an_assignment_holds_an_element_control():
    flow = valid_model().data_flows[0]
    flow.authentication = ElementControl(state="absent")
    assert isinstance(flow.authentication, ElementControl)


def test_held_text_and_held_state_refuse_a_value_of_another_shape():
    with pytest.raises(TypeError):
        held_state(["pii"])
    with pytest.raises(TypeError):
        held_text(None)


@pytest.mark.parametrize(
    ("answer", "control"),
    [
        ("none", ElementControl(state="absent")),
        ("none; we accept it", ElementControl(state="absent", detail="we accept it")),
        ("company SSO", ElementControl(state="stated", detail="company SSO")),
    ],
)
def test_an_answer_reads_as_a_control(answer, control):
    assert answered_control(answer) == control


@pytest.mark.parametrize(
    "control",
    [
        ElementControl(state="absent"),
        ElementControl(state="absent", detail="accepted by network position"),
        ElementControl(state="stated", detail="company SSO"),
    ],
)
def test_control_answer_is_the_inverse_of_answered_control(control):
    answer = control_answer(control)
    assert answer is not None
    assert answered_control(answer) == control


def test_an_unknown_control_has_no_answer():
    assert control_answer(ElementControl(state="unknown", detail="why")) is None


@pytest.mark.parametrize("answer", ["no MFA", "not encrypted", "TBD", "I don't know"])
def test_a_control_answer_that_hides_its_state_is_refused(answer):
    assert control_answer_issue(answer) is not None


@pytest.mark.parametrize(
    "answer", ["none", "none; we accept it", "company SSO", "nonexistent risk"]
)
def test_a_control_answer_that_says_its_state_passes(answer):
    assert control_answer_issue(answer) is None


def test_a_flow_built_with_controls_round_trips():
    flow = DataFlow(
        id="flow:entity:a>process:b>call",
        name="call",
        source="entity:a",
        destination="process:b",
        protocol="HTTPS",
        authentication=ElementControl(state="stated", detail="mTLS"),
        data_description="calls",
        encryption_in_transit=ElementControl(state="unknown", detail="not said"),
    )
    assert DataFlow.model_validate_json(flow.model_dump_json()) == flow
