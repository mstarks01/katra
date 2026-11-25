"""A store's tier from its asset tags, where the extraction left it unknown (#2368)."""

from __future__ import annotations

from katra.graph import after_gate
from katra.tag_classification import with_tag_classification
from tests.factories import valid_model


def _with_store(**fields):
    model = valid_model()
    model.data_stores[0] = model.data_stores[0].model_copy(update=fields)
    return model


def test_a_store_holding_personal_data_is_confidential():
    model = with_tag_classification(
        _with_store(data_classification="unknown", assets=["pii"])
    )

    store = model.data_stores[0]
    assert store.data_classification == "confidential"
    [assumption] = [
        a for a in model.assumptions if a.attribute == "data_classification"
    ]
    assert (assumption.element_id, "pii" in assumption.basis) == (store.id, True)


def test_a_store_tagged_only_business_critical_keeps_unknown():
    model = with_tag_classification(
        _with_store(data_classification="unknown", assets=["business-critical-data"])
    )

    assert model.data_stores[0].data_classification == "unknown"


def test_a_tier_the_model_states_is_never_touched():
    model = with_tag_classification(
        _with_store(data_classification="internal", assets=["credentials"])
    )

    assert model.data_stores[0].data_classification == "internal"
    assert not [a for a in model.assumptions if a.attribute == "data_classification"]


def test_the_gate_writes_it():
    model = after_gate(_with_store(data_classification="unknown", assets=["health"]))

    assert model.data_stores[0].data_classification == "confidential"
