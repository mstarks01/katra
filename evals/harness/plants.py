"""Plants: false STRIDE claims that code writes from a case's stated controls.

A plant inverts one control that the case's **System Model** states. The
model says that a **Data Flow** carries authentication or encryption in
transit, and the plant says that the flow carries none. A reader who reads the
model against the plant marks it ``reject``. A sitting mixes plants into the
recorded findings it asks a reader to mark (``evals/BLESSING.md``), so the
plant marks show whether the reader tests each claim against the model.

The plants are STRIDE plants only. A STRIDE claim names a mechanism at a model
element, so a stated control can contradict it. A catalog claim names a
requirement and its applicability, and no stated control contradicts it.

The choice is deterministic: one case gives the same plants on each call. The
ballot shuffles the rows, so the order on the page tells the reader nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import chain, zip_longest
from typing import Literal, get_args

from evals.harness.reference import GoldenCase
from katra.actions import ActionVerb
from katra.analysis import control_state
from katra.claims import FrameworkName
from katra.frameworks.stride.record import StrideCategory
from katra.system_model import DataFlow, ModelIndex

#: The most plants one ballot carries. Two or three plants in a set of about
#: twenty findings test the reader and do not change the set.
PLANTS_PER_CASE = 3

#: The **Framework** whose claims a plant imitates.
PLANT_FRAMEWORK: FrameworkName = "stride"

#: The flow controls a plant can invert, in the order the choice alternates.
PlantAttribute = Literal["authentication", "encryption_in_transit"]
PLANT_ATTRIBUTES: tuple[PlantAttribute, ...] = get_args(PlantAttribute)


@dataclass(frozen=True)
class Template:
    """How a plant reads for one inverted control."""

    category: StrideCategory
    verb: ActionVerb
    #: A ``str.format`` text with the fields ``source``, ``destination`` and
    #: ``flow``: the element names from the model.
    text: str


#: One template for each attribute a plant inverts. The claim says that the
#: control is absent, and the model states it.
TEMPLATES: Mapping[PlantAttribute, Template] = {
    "authentication": Template(
        category="spoofing",
        verb="impersonate",
        text=(
            "An attacker who reaches the {destination} sends {flow} traffic as"
            " the {source}, because that flow carries no authentication."
        ),
    ),
    "encryption_in_transit": Template(
        category="information-disclosure",
        verb="intercept",
        text=(
            "An attacker on the path between the {source} and the {destination}"
            " reads the {flow} traffic in cleartext, because that flow carries"
            " no encryption in transit."
        ),
    ),
}


@dataclass(frozen=True)
class Plant:
    """One false claim, and the stated fact it contradicts."""

    #: The key a plant's mark files under. It starts with ``plant:``, and no
    #: claim fingerprint does, so a plant key never names a recorded finding.
    key: str
    case_id: str
    framework: FrameworkName
    category: StrideCategory
    verb: ActionVerb
    element_ids: tuple[str, ...]
    claim: str
    #: The flow whose control the plant inverts.
    element_id: str
    attribute: PlantAttribute
    #: The control value the model states for that attribute.
    stated: str


def plants_for(case: GoldenCase, count: int = PLANTS_PER_CASE) -> tuple[Plant, ...]:
    """Up to ``count`` plants for one case, from the controls its model states.

    A candidate is a data flow whose attribute reads ``stated`` under
    :func:`~katra.analysis.control_state`. The candidates of each attribute
    sort by flow ID, and the choice takes them in turn from each attribute.
    A case with fewer candidates gets fewer plants, and a case with no STRIDE
    set gets none.
    """
    if PLANT_FRAMEWORK not in case.frameworks:
        return ()
    index = ModelIndex.of(case.model)
    flows = sorted(case.model.data_flows, key=lambda flow: flow.id)
    candidates = [
        [
            (flow, attribute)
            for flow in flows
            if control_state(getattr(flow, attribute)) == "stated"
        ]
        for attribute in PLANT_ATTRIBUTES
    ]
    alternated = [
        pair for pair in chain.from_iterable(zip_longest(*candidates)) if pair
    ]
    return tuple(
        _plant(case.id, index, flow, attribute)
        for flow, attribute in alternated[:count]
    )


def _plant(
    case_id: str, index: ModelIndex, flow: DataFlow, attribute: PlantAttribute
) -> Plant:
    template = TEMPLATES[attribute]
    return Plant(
        key=f"plant:{case_id}:{flow.id}:{attribute}",
        case_id=case_id,
        framework=PLANT_FRAMEWORK,
        category=template.category,
        verb=template.verb,
        element_ids=(flow.id,),
        claim=template.text.format(
            source=_name(index, flow.source),
            destination=_name(index, flow.destination),
            flow=flow.name,
        ),
        element_id=flow.id,
        attribute=attribute,
        stated=getattr(flow, attribute),
    )


def _name(index: ModelIndex, element_id: str) -> str:
    """The name the model gives one flow endpoint."""
    element = index.get(element_id)
    if element is None:
        raise ValueError(f"{element_id}: a flow names an element the model lacks")
    return element.name
