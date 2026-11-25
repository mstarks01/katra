"""A store's data classification, written from its asset tags (#2368).

``prompts/extract.md`` defines ``confidential`` by what a store holds:
personal, payment or health data, credentials and secrets. The asset tags
name the same contents, so a store tagged with one of them is
``confidential`` by that definition, and code writes the tier where the
extraction left it ``unknown``. ``public``, ``internal`` and a store tagged
only ``business-critical-data`` stay with the model, because no tag settles
them.

Like a protocol default (:mod:`katra.protocol_defaults`), each value it writes
takes one :class:`~katra.system_model.Assumption`, which names the tags as its
basis, and a tier the model already states is never touched.
"""

from __future__ import annotations

from katra.field_capabilities import SENSITIVE_TAGS
from katra.system_model import UNKNOWN, Assumption, SystemModel


def with_tag_classification(model: SystemModel) -> SystemModel:
    """The model with ``confidential`` written on each unknown-tier store whose
    asset tags name contents ``extract.md`` defines as confidential."""
    updated = model.model_copy(deep=True)
    for store in updated.data_stores:
        tags = sorted(set(store.assets) & SENSITIVE_TAGS)
        if store.data_classification != UNKNOWN or not tags:
            continue
        store.data_classification = "confidential"
        updated.assumptions.append(
            Assumption(
                assumption=f"{store.name}: confidential, because it holds"
                f" {', '.join(tags)}.",
                element_id=store.id,
                attribute="data_classification",
                basis=f"the store's asset tags: {', '.join(tags)}",
            )
        )
    return updated
