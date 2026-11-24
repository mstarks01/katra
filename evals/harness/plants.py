"""Plants: false findings that code writes from a case's model (#764).

A **Plant** inverts one control that a case's **System Model** states. It says
that a **Data Flow** has no authentication, that a flow carries its data in
clear text, or that a **Data Store** keeps its data unencrypted at rest. The
source states the opposite, so a judge that reads the source must reject the
plant. The judge replay (``evals/harness/judge_replay.py``) mixes plants into
each judge batch as known negatives. Plants never go into a **Case Sitting**.

**Two readings must agree before a fact is a candidate.**

1. :func:`plant_reading` reads the model's value. It refuses a value that
   :func:`~katra.analysis.control_state` does not read as ``stated``, a value
   with a negating or limiting word anywhere in it (``no``, ``without``,
   ``except``, ``only``, ``some`` and the like), and a value that names no
   mechanism. A word list cannot prove a control. It only removes candidates:
   "plain HTTP, no TLS" names TLS and still reads ``qualified``.
2. A signed row of the case's ``facts.json`` must state the control on the same
   element. The row is ``stated``, has no scope, has a reviewer, reaches the
   attribute through :func:`~katra.assertions.projected_attribute`, and its
   value passes :func:`plant_reading` too. A person signed that the source
   states this value, so the plant contradicts the source and not only the
   model.

A fact that fails either reading gives no plant. ``tests/test_evals_plants.py``
lists each stated value of the development cases that the readings skip.

**The frame of a plant must not give it away.** Each attribute has several
title frames, description frames and closing sentences, and
:func:`write_plants` chooses one of each at random. A description names the
attacker's means, as the real findings do, and cites the elements by their
IDs. A title names the elements as noun phrases. ``tests/test_evals_plants.py``
measures that no sequence of five words appears in every plant over the
development cases.

**The choice is random.** The command passes ``random.SystemRandom()``, so a
reader of this code cannot compute which facts a run plants. A test passes a
seeded ``random.Random``.
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from evals.reference_facts import ReferenceFacts
from katra.analysis import control_state
from katra.assertions import projected_attribute
from katra.claims import Ground
from katra.frameworks.stride.record import StrideCategory
from katra.system_model import DataFlow, DataStore, Element, SystemModel

#: The control attributes a plant inverts: each control attribute of
#: :data:`~katra.analysis.CONTROL_ATTRIBUTES` whose stated value names a
#: mechanism. ``exposure`` and ``data_classification`` name no mechanism.
PlantedAttribute = Literal[
    "authentication", "encryption_in_transit", "encryption_at_rest"
]
PLANTED_ATTRIBUTES: tuple[PlantedAttribute, ...] = get_args(PlantedAttribute)

#: How a candidate reads. :func:`plant_reading` gives the first four, and
#: ``unsigned`` is a plantable value that no signed fact states.
PlantReading = Literal[
    "plantable", "not-stated", "qualified", "no-mechanism", "unsigned"
]

#: The number of plants in one batch, as #764 states it: two or three. A case
#: with fewer candidates gets all of them.
PLANTS_PER_BATCH: tuple[int, ...] = (2, 3)

#: Words that negate, limit or qualify a stated control. A value with one of
#: them anywhere in it gives no plant.
QUALIFYING_WORDS: frozenset[str] = frozenset(
    {
        "absent",
        "anonymous",
        "but",
        "certain",
        "disabled",
        "except",
        "excluding",
        "few",
        "lacks",
        "may",
        "might",
        "missing",
        "most",
        "no",
        "none",
        "not",
        "nothing",
        "only",
        "optional",
        "optionally",
        "partial",
        "partially",
        "plain",
        "plaintext",
        "selected",
        "some",
        "sometimes",
        "unauthenticated",
        "unclear",
        "unencrypted",
        "unknown",
        "unless",
        "unverified",
        "without",
    }
)

#: Words that name an authentication, transport or storage mechanism.
MECHANISM_WORDS: frozenset[str] = frozenset(
    {
        "account",
        "aes",
        "bitlocker",
        "certificate",
        "certificates",
        "cmk",
        "code",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "https",
        "jwt",
        "key",
        "keys",
        "kms",
        "luks",
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
        "tde",
        "tls",
        "token",
        "tokens",
    }
)

#: The STRIDE category of the finding that inverts each attribute.
CATEGORY: dict[PlantedAttribute, StrideCategory] = {
    "authentication": "spoofing",
    "encryption_in_transit": "information-disclosure",
    "encryption_at_rest": "information-disclosure",
}

#: The title frames of each attribute. ``{source}`` and ``{target}`` are a
#: flow's endpoints as noun phrases, and ``{store}`` is a data store.
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
    "encryption_at_rest": (
        "A storage-layer copy of {store} exposes its data in clear text",
        "Anyone who obtains the disks or backups of {store} can read its contents",
        "Unencrypted storage lets an attacker read {store} directly",
        "{Store} keeps its data at rest with no encryption",
        "A stolen snapshot of {store} discloses everything it holds",
    ),
}

#: The description frames of each attribute. ``{flow}``, ``{source_id}``,
#: ``{target_id}`` and ``{store_id}`` are element IDs, which the frame puts in
#: backticks.
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
    "encryption_at_rest": (
        (
            "`{store_id}` stores its data without encryption at rest. An attacker"
            " who obtains a copy of the underlying volume, a backup or a snapshot"
            " reads every record in it and never goes through an application."
        ),
        (
            "Nothing protects the contents of `{store_id}` at rest. An operator of"
            " the hosting platform, or an attacker who reaches the storage layer,"
            " reads the stored data in clear text."
        ),
        (
            "`{store_id}` writes its contents to disk in readable form. A copy"
            " taken from the storage media or from a backup job is readable as it"
            " is, with no key to obtain first."
        ),
        (
            "The data in `{store_id}` sits unencrypted on its storage. An attacker"
            " with access to the media bypasses the access checks of every process"
            " that reads `{store_id}`."
        ),
    ),
}

#: The closing sentence of a description: what the attack reaches. ``{data}``
#: is a flow's ``data_description``.
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
    "encryption_at_rest": (
        "Every record that `{store_id}` holds is disclosed in one step.",
        "The exposure covers backups and snapshots as well as the live store.",
        (
            "Second-order, the attacker can use what the copy holds against the"
            " processes that read `{store_id}`."
        ),
    ),
}

_WORD = re.compile(r"[a-z0-9]+")


def plant_reading(value: str) -> PlantReading:
    """Whether a plant may invert the control ``value`` states, and why not."""
    if control_state(value) != "stated":
        return "not-stated"
    words = set(_WORD.findall(value.casefold()))
    if words & QUALIFYING_WORDS:
        return "qualified"
    if not words & MECHANISM_WORDS:
        return "no-mechanism"
    return "plantable"


@dataclass(frozen=True)
class PlantedFact:
    """The stated control a plant inverts, so a reader can check the plant."""

    case: str
    element_id: str
    attribute: PlantedAttribute
    stated: str

    def to_json(self) -> dict[str, str]:
        return {
            "case": self.case,
            "element_id": self.element_id,
            "attribute": self.attribute,
            "stated": self.stated,
        }


def signed_controls(facts: ReferenceFacts | None) -> set[tuple[str, str]]:
    """Each ``(element ID, attribute)`` that a signed, stated, unscoped row of
    ``facts`` states with a plantable value."""
    if facts is None:
        return set()
    return {
        (row.assertion.subject, attribute)
        for row in facts.rows
        if row.reviewed_by is not None
        and row.assertion.basis == "stated"
        and not row.assertion.scope
        and (
            attribute := projected_attribute(
                row.assertion.predicate, row.assertion.subject
            )
        )
        and plant_reading(row.assertion.value) == "plantable"
    }


def readings(
    case_id: str,
    model: SystemModel,
    facts: ReferenceFacts | None,
    renamed: Mapping[str, str],
) -> dict[PlantedFact, PlantReading]:
    """Each stated control of ``model`` that a plant inverts, with its reading.

    ``renamed`` maps an element ID of ``model`` to the ID the signed facts
    spell, where the two differ: an archived model can spell its flows under an
    older flow identity version.
    """
    signed = signed_controls(facts)
    found: dict[PlantedFact, PlantReading] = {}
    for element in model.elements():
        for attribute in PLANTED_ATTRIBUTES:
            value = getattr(element, attribute, None)
            if not isinstance(value, str):
                continue
            reading = plant_reading(value)
            if reading == "not-stated":
                continue
            current = renamed.get(element.id, element.id)
            if reading == "plantable" and (current, attribute) not in signed:
                reading = "unsigned"
            found[PlantedFact(case_id, element.id, attribute, value)] = reading
    return found


def candidates(
    case_id: str,
    model: SystemModel,
    facts: ReferenceFacts | None,
    renamed: Mapping[str, str],
) -> tuple[PlantedFact, ...]:
    """The facts of ``model`` that a plant may invert, in model order."""
    return tuple(
        fact
        for fact, reading in readings(case_id, model, facts, renamed).items()
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


def _names(element: Element, model: SystemModel) -> dict[str, str]:
    """The words a frame fills in for ``element``: noun phrases and element IDs."""
    if isinstance(element, DataStore):
        store = noun_phrase(element.name)
        return {"store": store, "Store": _upper_first(store), "store_id": element.id}
    if not isinstance(element, DataFlow):
        raise TypeError(f"{element.id} is neither a data flow nor a data store")
    source = model.get(element.source)
    target = model.get(element.destination)
    if source is None or target is None:
        raise ValueError(f"{element.id} names an endpoint the model does not hold")
    target_phrase = noun_phrase(target.name)
    return {
        "source": noun_phrase(source.name),
        "target": target_phrase,
        "Target": _upper_first(target_phrase),
        "flow": element.id,
        "source_id": source.id,
        "target_id": target.id,
        "data": _lower_first(element.data_description),
    }


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _plant(fact: PlantedFact, model: SystemModel, rng: random.Random) -> Plant:
    element = model.get(fact.element_id)
    if element is None:
        raise ValueError(f"{fact.element_id} is not in the model")
    names = _names(element, model)
    grounds = [
        Ground(kind="absent-attribute", element_id=element.id, attribute=fact.attribute)
    ]
    affected: tuple[str, ...] = (element.id,)
    if isinstance(element, DataFlow):
        if rng.random() < 0.5:
            grounds.append(Ground(kind="derived-fact", flow_id=element.id))
        affected = (
            (names["source_id"], element.id, names["target_id"])
            if rng.random() < 0.5
            else (element.id, names["target_id"])
        )
    return Plant(
        fact=fact,
        category=CATEGORY[fact.attribute],
        title=rng.choice(TITLES[fact.attribute]).format(**names),
        description=" ".join(
            (
                rng.choice(DESCRIPTIONS[fact.attribute]).format(**names),
                rng.choice(CONSEQUENCES[fact.attribute]).format(**names),
            )
        ),
        affected_element_ids=affected,
        grounds=tuple(grounds),
    )


def write_plants(
    case_id: str,
    model: SystemModel,
    facts: ReferenceFacts | None,
    renamed: Mapping[str, str],
    rng: random.Random,
) -> tuple[Plant, ...]:
    """Two or three plants for one batch, chosen with ``rng``.

    ``facts`` is the case's signed facts, or ``None`` for a case with none, which
    gets no plant. ``renamed`` is as :func:`readings` states it. A case with
    fewer candidates than the count gets a plant for each one.
    """
    facts_found = candidates(case_id, model, facts, renamed)
    chosen = rng.sample(
        facts_found, min(rng.choice(PLANTS_PER_BATCH), len(facts_found))
    )
    return tuple(_plant(fact, model, rng) for fact in chosen)
