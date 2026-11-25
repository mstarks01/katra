"""What a protocol guarantees by its own definition is written where a description is silent (ADR 0082)."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from katra import graph
from katra.compact import FULL_FORMAT
from katra.protocol_defaults import PROTOCOL_DEFAULTS, with_protocol_defaults
from katra.system_model import (
    UNKNOWN,
    Assumption,
    ElementControl,
    control_from_text,
    control_text,
)
from katra.validation import validate
from tests.factories import valid_model
from tests.source_tree import REPO_ROOT
from tests.test_graph import KEYS, FakeContext

FLOW = "flow:entity:customer>process:web-app>login"


def _flow_over(protocol, *, inferred=False, encryption=UNKNOWN):
    model = valid_model()
    flow = model.get(FLOW)
    flow.protocol = protocol
    flow.encryption_in_transit = control_from_text(encryption)
    flow.authentication = control_from_text(UNKNOWN)
    if inferred:
        model.assumptions.append(
            Assumption(
                assumption="the flow is HTTPS",
                element_id=FLOW,
                attribute="protocol",
                basis="the model inferred it",
            )
        )
    return with_protocol_defaults(model)


def test_a_stated_protocol_states_what_its_definition_guarantees():
    """SFTP is always encrypted, and WireGuard always authenticates its peers."""
    model = _flow_over("SFTP")
    sftp = model.get(FLOW)
    assert (
        control_text(sftp.encryption_in_transit)
        == "SSH transport encryption (intrinsic)"
    )
    assert control_text(sftp.authentication) == UNKNOWN, (
        "SSH defines a 'none' client method"
    )
    (assumption,) = [a for a in model.assumptions if a.element_id == FLOW]
    assert "rfc4253" in assumption.basis
    assert validate(model) == []
    tunnel = _flow_over("WireGuard").get(FLOW)
    assert control_text(tunnel.encryption_in_transit) == "ChaCha20-Poly1305 (WireGuard)"
    assert control_text(tunnel.authentication) == "peer public keys (WireGuard)"
    quic = _flow_over("HTTP/3").get(FLOW).encryption_in_transit
    assert control_text(quic).startswith("QUIC")


def test_a_stated_value_is_never_changed():
    assert (
        control_text(
            _flow_over("HTTPS", encryption="none").get(FLOW).encryption_in_transit
        )
        == "none"
    )


@pytest.mark.parametrize(
    "protocol", ["HTTP and HTTPS", "HTTP without TLS", "plain HTTP", "HTTP/2", "gRPC"]
)
def test_a_plain_sibling_or_a_negation_states_nothing(protocol):
    flow = _flow_over(protocol).get(FLOW)
    assert control_text(flow.encryption_in_transit) == UNKNOWN


def test_an_inferred_protocol_states_nothing():
    """A property derived from a protocol nobody stated is an inference on an
    inference."""
    assert (
        control_text(_flow_over("HTTPS", inferred=True).get(FLOW).encryption_in_transit)
        == UNKNOWN
    )


def test_every_row_says_what_it_writes_and_where_the_standard_defines_it():
    for default in PROTOCOL_DEFAULTS:
        assert default.attribute in {"encryption_in_transit", "authentication"}
        assert default.value and default.value != UNKNOWN
        assert default.basis.endswith(".")
        assert urlparse(default.source).scheme == "https"
        assert all(name == name.lower() for name in default.names)


def test_every_protocol_the_extraction_prompt_names_is_a_row_of_the_table():
    """Two readers of one rule: the prompt asks the model to write it, and the
    table writes it where the model did not. They must name the same protocols."""
    rule = next(
        line
        for line in (REPO_ROOT / "prompts/extract.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if "An encrypted protocol states" in line
    )
    encrypted, authenticating = set(), set()
    for default in PROTOCOL_DEFAULTS:
        target = (
            encrypted
            if default.attribute == "encryption_in_transit"
            else authenticating
        )
        target.update(default.names)
    for name in ("HTTPS", "TLS", "mTLS", "WSS", "FTPS", "SSH", "SFTP"):
        assert name in rule and name.lower() in encrypted, name
    assert "mTLS also states `authentication`" in rule
    assert "mtls" in authenticating


def test_the_gate_publishes_the_model_with_its_protocol_defaults():
    """The default is written after the gate, into the model the analysis
    reads, and never into what extraction emitted."""
    emitted = valid_model()
    flow = emitted.get(FLOW)
    flow.protocol = "SFTP"
    flow.encryption_in_transit = ElementControl(state="unknown")
    payload = emitted.model_dump(mode="json")
    ctx = FakeContext()
    event = graph.validate_extraction(
        ctx, KEYS, payload, source_texts={}, extraction_format=FULL_FORMAT
    )
    assert event.actions.route == graph.ROUTE_VALID
    published = {f["id"]: f for f in ctx.state[graph.STATE_VALID_MODEL]["data_flows"]}
    assert published[FLOW]["encryption_in_transit"] == {
        "state": "stated",
        "detail": "SSH transport encryption (intrinsic)",
    }
    assert payload["data_flows"][0]["encryption_in_transit"] == {
        "state": "unknown",
        "detail": "",
    }
