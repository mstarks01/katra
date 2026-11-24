"""Plants: false findings that code writes from a case's model (#764).

A **Plant** inverts one control that a case's **System Model** states on a
**Data Flow**: it says that the flow has no authentication, or that the flow
carries its data in clear text. The source states the opposite, so a judge
that reads the source must reject the plant. The judge replay
(``evals/harness/judge_replay.py``) mixes plants into each judge batch as known
negatives. Plants never go into a **Case Sitting**.

**A candidate is a control the model states for every caller of the flow, with
a mechanism the value names.** :func:`plant_reading` decides this from the
value alone, with two word lists:

* A value that limits the control to some callers is ``limited``. Case 10's
  "sign-in exists for some readers" is one: a plant against it is true for the
  other readers.
* A value that names no mechanism is ``no-mechanism``. Case 08's "vouch for
  colleague" flow is one: the value describes a trust decision, and a plant
  against it is a claim about something the source does not state.

Both lists only remove candidates. A value that the lists do not read
correctly gives fewer plants, never a plant that the source supports.
``tests/test_evals_plants.py`` lists each value of the development corpus that
the reading skips.

**The frame of a plant must not give it away.** Each attribute has several
title frames, description frames and closing sentences, and
:func:`write_plants` chooses one of each at random. A description names the attacker's means, as the real
findings do, and cites the elements by their IDs. A title names the flow's two
endpoints as noun phrases. ``tests/test_evals_plants.py`` measures that no
sequence of five words appears in every plant over the development cases.

**The choice is random.** The command passes ``random.SystemRandom()``, so a
reader of this code cannot compute which facts a run plants. A test passes a
seeded ``random.Random``.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Literal, get_args

from katra.analysis import control_state
from katra.claims import Ground
from katra.frameworks.stride.record import StrideCategory
from katra.system_model import DataFlow, SystemModel

#: The flow attributes a plant inverts.
PlantedAttribute = Literal["authentication", "encryption_in_transit"]
PLANTED_ATTRIBUTES: tuple[PlantedAttribute, ...] = get_args(PlantedAttribute)

#: How :func:`plant_reading` reads one stated or unstated control value.
PlantReading = Literal["plantable", "not-stated", "limited", "no-mechanism"]

#: The number of plants in one batch, as #764 states it: two or three. A case
#: with fewer candidates gets all of them.
PLANTS_PER_BATCH: tuple[int, ...] = (2, 3)

#: Words that limit a stated control to some callers of a flow.
LIMITING_WORDS: frozenset[str] = frozenset(
    {
        "certain",
        "few",
        "most",
        "only",
        "optional",
        "optionally",
        "selected",
        "some",
        "sometimes",
    }
)

#: Words that name an authentication or a transport mechanism.
MECHANISM_WORDS: frozenset[str] = frozenset(
    {
        "account",
        "certificate",
        "certificates",
        "code",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "https",
        "jwt",
        "key",
        "keys",
        "mfa",
        "mtls",
        "oauth",
        "password",
        "passwords",
        "saml",
        "secret",
        "sftp",
        "ssh",
        "sso",
        "tls",
        "token",
        "tokens",
    }
)

#: The STRIDE category of the finding that inverts each attribute.
CATEGORY: dict[PlantedAttribute, StrideCategory] = {
    "authentication": "spoofing",
    "encryption_in_transit": "information-disclosure",
}

#: The title frames of each attribute. ``{source}`` and ``{target}`` are the
#: flow's endpoints as noun phrases.
TITLES: dict[PlantedAttribute, tuple[str, ...]] = {
    "authentication": (
        "An attacker can act as {source} toward {target} with no credential",
        "Unauthenticated calls let an attacker pose as {source} to {target}",
        "{Target} accepts forged requests that claim to come from {source}",
        "Anyone who reaches {target} can submit requests in the name of {source}",
        "Missing caller authentication lets an attacker impersonate {source}",
    ),
    "encryption_in_transit": (
        "Traffic from {source} to {target} is readable in transit",
        "An on-path attacker can read what {source} sends to {target}",
        "Plaintext transport exposes data passing between {source} and {target}",
        "Data that {source} sends to {target} may be captured on the network",
        "An unencrypted link lets an attacker intercept traffic to {target}",
    ),
}

#: The description frames of each attribute. ``{flow}``, ``{source_id}`` and
#: ``{target_id}`` are element IDs, which the frame puts in backticks.
DESCRIPTIONS: dict[PlantedAttribute, tuple[str, ...]] = {
    "authentication": (
        (
            "An attacker who can reach `{target_id}` sends crafted requests over"
            " `{flow}` and claims to be `{source_id}`. `{target_id}` asks the"
            " caller for no credential on this flow, so it cannot tell a forged"
            " request from a real one. The attacker then performs every action"
            " that `{source_id}` can perform."
        ),
        (
            "`{flow}` carries no authentication. A script that replays the request"
            " format of `{source_id}` is enough for an attacker to be accepted by"
            " `{target_id}` as that caller. Each forged call reaches `{target_id}`"
            " with the same authority as a genuine one."
        ),
        (
            "Because `{target_id}` does not check who sends traffic on `{flow}`, an"
            " attacker with network reach to it can impersonate `{source_id}`."
            " Nothing stands between the attacker and the operations that"
            " `{source_id}` triggers."
        ),
        (
            "`{target_id}` admits any caller on `{flow}` without proof of identity."
            " An attacker on the network sends requests that name `{source_id}` as"
            " their origin, and `{target_id}` processes them as if `{source_id}`"
            " had sent them."
        ),
    ),
    "encryption_in_transit": (
        (
            "`{flow}` sends its data without transport encryption. An attacker in"
            " an on-path position between `{source_id}` and `{target_id}` captures"
            " the packets and reads every request and response in clear text. Any"
            " personal data or secret on the flow is disclosed."
        ),
        (
            "Nothing encrypts the traffic that `{source_id}` sends to `{target_id}`"
            " on `{flow}`. An attacker who can observe that network segment, for"
            " example with a packet capture on a shared link, reads the traffic as"
            " it passes."
        ),
        (
            "The link that carries `{flow}` is plaintext. An attacker who sits on"
            " the path from `{source_id}` to `{target_id}` intercepts the messages,"
            " reads their contents and can reuse any secret they carry."
        ),
        (
            "`{source_id}` reaches `{target_id}` over `{flow}` with no"
            " confidentiality protection in transit. An attacker who taps the"
            " network between the two reads the exchanged data and is not"
            " detected."
        ),
    ),
}

#: The closing sentence of a description: what the attack reaches. ``{data}``
#: is the flow's ``data_description``.
CONSEQUENCES: dict[PlantedAttribute, tuple[str, ...]] = {
    "authentication": (
        (
            "Second-order, the attacker supplies what the flow carries ({data}),"
            " and `{target_id}` acts on it."
        ),
        (
            "The same flow carries {data}, so the attacker can read or change it"
            " in the name of `{source_id}`."
        ),
        "That puts {data} under the attacker's control.",
    ),
    "encryption_in_transit": (
        "What the attacker reads includes {data}.",
        "The captured traffic holds {data}, which the attacker can use later.",
        (
            "The link carries {data}; with it, the attacker can act against"
            " `{target_id}` directly."
        ),
    ),
}

_WORD = re.compile(r"[a-z0-9]+")


def plant_reading(value: str) -> PlantReading:
    """Whether a plant may invert the control ``value`` states, and why not."""
    if control_state(value) != "stated":
        return "not-stated"
    words = set(_WORD.findall(value.casefold()))
    if words & LIMITING_WORDS:
        return "limited"
    if not words & MECHANISM_WORDS:
        return "no-mechanism"
    return "plantable"


@dataclass(frozen=True)
class PlantedFact:
    """The stated control a plant inverts, so a reader can check the plant."""

    case: str
    flow_id: str
    attribute: PlantedAttribute
    stated: str

    def to_json(self) -> dict[str, str]:
        return {
            "case": self.case,
            "flow_id": self.flow_id,
            "attribute": self.attribute,
            "stated": self.stated,
        }


def readings(case_id: str, model: SystemModel) -> dict[PlantedFact, PlantReading]:
    """Each stated control of each flow of ``model``, with its reading."""
    return {
        PlantedFact(case_id, flow.id, attribute, value): plant_reading(value)
        for flow in model.data_flows
        for attribute in PLANTED_ATTRIBUTES
        if plant_reading(value := getattr(flow, attribute)) != "not-stated"
    }


def candidates(case_id: str, model: SystemModel) -> tuple[PlantedFact, ...]:
    """The facts of ``model`` that a plant may invert, in model order."""
    return tuple(
        fact
        for fact, reading in readings(case_id, model).items()
        if reading == "plantable"
    )


@dataclass(frozen=True)
class Plant:
    """One false finding, and the fact it inverts."""

    fact: PlantedFact
    category: StrideCategory
    title: str
    description: str
    affected_element_ids: tuple[str, ...]
    grounds: tuple[Ground, ...]

    def view(self) -> dict[str, Any]:
        """The plant as a judge sees a finding."""
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "affected_element_ids": list(self.affected_element_ids),
            "grounds": [
                ground.model_dump(exclude_defaults=True) for ground in self.grounds
            ],
        }

    def to_json(self) -> dict[str, Any]:
        return {"fact": self.fact.to_json(), **self.view()}


def noun_phrase(name: str) -> str:
    """An element name as a noun phrase with an article: ``the web server``.

    A first word in title case loses its capital, and a word in another case,
    such as ``MySQL`` or ``CDN``, keeps it.
    """
    phrase = _lower_first(name)
    return phrase if phrase.startswith("the ") else f"the {phrase}"


def _lower_first(text: str) -> str:
    """``text`` with its first word in lower case where that word is in title case."""
    first, _, rest = text.strip().partition(" ")
    if first[:1].isupper() and first[1:].islower():
        first = first.lower()
    return f"{first} {rest}".strip()


def _plant(
    fact: PlantedFact, flow: DataFlow, model: SystemModel, rng: random.Random
) -> Plant:
    source = model.get(flow.source)
    target = model.get(flow.destination)
    if source is None or target is None:
        raise ValueError(f"{flow.id} names an endpoint the model does not hold")
    names = {
        "source": noun_phrase(source.name),
        "target": noun_phrase(target.name),
    }
    names["Target"] = names["target"][:1].upper() + names["target"][1:]
    ids = {"flow": flow.id, "source_id": source.id, "target_id": target.id}
    grounds = [
        Ground(kind="absent-attribute", element_id=flow.id, attribute=fact.attribute)
    ]
    if rng.random() < 0.5:
        grounds.append(Ground(kind="derived-fact", flow_id=flow.id))
    affected = (
        (source.id, flow.id, target.id) if rng.random() < 0.5 else (flow.id, target.id)
    )
    return Plant(
        fact=fact,
        category=CATEGORY[fact.attribute],
        title=rng.choice(TITLES[fact.attribute]).format(**names),
        description=" ".join(
            (
                rng.choice(DESCRIPTIONS[fact.attribute]).format(**ids),
                rng.choice(CONSEQUENCES[fact.attribute]).format(
                    data=_lower_first(flow.data_description), **ids
                ),
            )
        ),
        affected_element_ids=affected,
        grounds=tuple(grounds),
    )


def write_plants(
    case_id: str, model: SystemModel, rng: random.Random
) -> tuple[Plant, ...]:
    """Two or three plants for one batch, chosen with ``rng``.

    A case with fewer candidates than the count gets a plant for each one, and
    a case with none gets no plant.
    """
    facts = candidates(case_id, model)
    chosen = rng.sample(facts, min(rng.choice(PLANTS_PER_BATCH), len(facts)))
    flows = {flow.id: flow for flow in model.data_flows}
    return tuple(_plant(fact, flows[fact.flow_id], model, rng) for fact in chosen)
