"""The capabilities a job's sources state, read by a model and checked by code.

A description that says "customers sign in through Auth0" states that the
application authenticates its users, and asking the owner again only wastes
an answer. The ``capabilities`` node reads the sources and the capability
table and proposes each capability the text says the application has, with
the words that say it (ADR 0086). This module is what code makes of that
proposal.

**A row only states presence.** The schema has no state field: a source is
silent about most of what an application lacks, and a "no" from one choice
already costs the owner little (ADR 0084). A wrong "present" makes a
requirement apply that does not; it cannot rule one out.

**A row carries its words, or it is dropped.** Code keeps a row only where its
key is in the table and its quote is in the submitted source its label names,
under the validity gate's own matcher. Where that source does not hold the
quote, the one submitted source that does is the label
(:func:`~katra.grounding.holding_label`); where several or none do, the row is
dropped. The answers source is not one of them: an answer writes its own capability
(:func:`~katra.fact_writes.capability_statements`), and a row that
quoted it would state that answer a second time. Each statement this module
writes has the origin ``reader``. **A statement always wins**: a capability
an answer, a closed field or another statement already names is left as it
is, and a later answer replaces what this module wrote.

The node runs as a separate pass, never inside extraction: asking extraction
for capabilities lost element identity (ADR 0051).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from katra.capabilities import CAPABILITIES, parse_capability_key
from katra.grounding import holding_label, normalize, verify_normalized
from katra.references import canonical
from katra.sources import ANSWERS_LABEL, MAX_LABEL_CHARS
from katra.system_model import (
    EXCERPT_MAX_CHARS,
    CapabilityStatement,
    SystemModel,
)


class CapabilityRow(BaseModel):
    """One capability the sources state, and the words that state it."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(
        min_length=1,
        max_length=60,
        json_schema_extra={"enum": [*sorted(CAPABILITIES)]},
    )
    source_label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    quote: str = Field(min_length=1, max_length=EXCERPT_MAX_CHARS)


class CapabilityReading(BaseModel):
    """What the ``capabilities`` node emits: one flat list of rows."""

    model_config = ConfigDict(
        extra="forbid",
        title="CapabilityReading",
        json_schema_extra={
            "description": "Each capability the sources state the application"
            " has, with the source label and the exact words."
        },
    )

    capabilities: list[CapabilityRow] = Field(default_factory=list)


def stated_keys(model: SystemModel) -> frozenset[str]:
    """Each capability a statement in ``model`` already names.

    The reader is not asked about these, and a row it writes on one is
    dropped, so both read this one set.
    """
    return frozenset(statement.capability for statement in model.capabilities)


def with_stated_capabilities(
    model: SystemModel, reading: CapabilityReading, sources: Mapping[str, str]
) -> SystemModel:
    """The model with each checked row of ``reading`` written as present.

    **The one writer of a capability the sources state.** A row is dropped
    where its key is not in the table, no submitted source holds its quote, or
    a statement already names its capability. Where the row's label names a
    source that does not hold the quote, the one submitted source that does is
    the label (:func:`~katra.grounding.holding_label`).
    """
    named = set(stated_keys(model))
    folded = {
        label: normalize(text)
        for label, text in sources.items()
        if label != ANSWERS_LABEL
    }
    updated = model.model_copy(deep=True)
    for row in reading.capabilities:
        if parse_capability_key(row.capability) is None or row.capability in named:
            continue
        label = canonical(row.source_label, list(folded))
        if not (label and verify_normalized(row.quote, folded[label])):
            # The label is a fact code can find (#2367): the one submitted
            # source that holds the quote.
            label = holding_label(row.quote, folded)
        if not label:
            continue
        updated.capabilities.append(
            CapabilityStatement(
                capability=row.capability,
                state="present",
                source_excerpt=row.quote,
                source_label=label,
                origin="reader",
            )
        )
        named.add(row.capability)
    return updated
