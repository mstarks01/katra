"""Model-tier configuration for the graph's LLM nodes.

There are two vendor-neutral tiers. ``base`` runs extraction, repair, the
assertion pass and the capability reader. ``strong`` runs each framework's lane
agents, its critic and its re-ask. Each tier selects its own ``(vendor, model)``
pair, so the two may run different vendors at once, and no vendor is
privileged. Which tier a node belongs to is fixed in code, in
:data:`NODE_TIERS`.

A node can also name its own ``(vendor, model)`` pair: an **override**, under
``[nodes."<node>"]``. A node with an override runs on that pair, and a node
without one runs on its tier's pair. An independent critic is an override on
``critic/<name>``. ``recritic/<name>`` takes no override: it always runs on
its critic's model, because a re-ask on another model than the pass it
corrects is a different judgement. A lane key ``analyze/<name>/<lane>`` is an
override too, and a lane without one runs on the model of
``analyze/<name>``.

Vendor and model are two keys rather than one router string. Three consumers
need the vendor as a key: the credential mode it implies, the family-branching
floating-form rule, and the two-argument build-time sampling gate. ``vertex_ai/``
is also not one provider, so a joined string would have to be parsed back apart
by all three. The prefix exists in exactly one place, :attr:`Vendor.prefix`.

No vendor is selected by default. The shipped config names no ``(vendor, model)``
pair for any tier, so a first run stops with :func:`_require_selected_tiers`'
message rather than reaching a vendor nobody chose. "No privileged default" is
therefore a property of the shipped values as well as of the mechanism: every
vendor is reached the same way, and none of them is what an operator gets by
doing nothing.

Loading fails closed. An unselected tier, an unknown tier, vendor or node name,
an override on a re-ask, a floating model identifier from the file or from an
env var, an undeclared credential mode for a vendor that allows more than one,
or a config version other than :data:`SUPPORTED_VERSION`
raises :class:`ModelConfigError` rather than degrading. There is no cross-tier
fallback and no compatibility shim for other schema versions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from katra.claims import FRAMEWORK_NAMES
from katra.config_files import read_toml, validation_problems
from katra.errors import ConfigError
from katra.parsing import is_version
from katra.vendors import (
    UPSTREAM_SLUG,
    VENDOR_NAMES,
    ChargeMode,
    CredentialMode,
    Vendor,
    VendorName,
    family_identifier,
    source_vendor_for_route,
    vendor_for,
)

# The only schema version this loader accepts. A file on any other version
# fails its own check rather than being migrated in place.
#
# Four tables are optional:
#
# * ``[nodes]``: the overrides, one ``[nodes."<node>"]`` table with ``vendor``
#   and ``model`` for each node that runs on its own pair. A node with no
#   table runs on its tier.
# * ``[credentials]``: the credential mode of a vendor that allows more than
#   one. Bedrock has the choice, so a file that selects it names a mode there
#   or in ``KATRA_MODEL_CREDENTIALS_BEDROCK``. No shipped file selects a
#   vendor, so every shipped file leaves the table out.
# * ``[charges]``: the arrangement a vendor charges under, where a vendor that
#   states its charge can state a different thing under another arrangement.
#   OpenRouter has the choice, so a file that selects it names an arrangement
#   there or in ``KATRA_MODEL_CHARGES_OPENROUTER``.
# * ``[upstreams]``: the upstream providers a request through an aggregator may
#   reach, and the request carries the pin. An analysis needs no pin; a
#   **Baseline** does, because it is named after the upstream that the record
#   says served it. A key for a vendor that routes to one provider is an error,
#   because there is nothing to pin.
SUPPORTED_VERSION = 10

TierName = Literal["base", "strong"]
TIER_NAMES: tuple[TierName, ...] = get_args(TierName)

#: The key of one model setting that nodes run on: the name of a tier, or the
#: key of a node with an override. Adapters, sampling blocks, execution records
#: and report rows are keyed by it. :meth:`ModelTierConfig.binding_of` decides
#: which binding a node runs on.
Binding = str


def tier_named(binding: Binding) -> TierName | None:
    """The tier that ``binding`` names, or ``None`` if it names a node."""
    return next((tier for tier in TIER_NAMES if tier == binding), None)


# How far a framework's criticism has to sit from its own analysis. A table
# rather than a chain of ``if``s, and the values are ordered weakest first so a
# reader sees that each admits strictly less than the one below it.
#
# * ``shared`` requires nothing. Criticism may run on the very model it checks,
#   which is the shipped configuration: a critic on one model still catches
#   inconsistency and unsupported claims, and it needs one tier rather than two.
# * ``distinct_model`` requires a different model. It removes a single build's
#   blind spots, and leaves those of the company that made it. Compared by the
#   identifier with any gateway segment stripped, because a slug pins the build
#   whichever route carries it.
# * ``distinct_source_vendor`` requires a model from a different **Source
#   Vendor**: the company that made the model, whichever vendor serves it. It
#   removes that company's blind spots too. :func:`source_vendor_breach` is the
#   rule.
#
# **None of these makes a review more accurate.** Independence bounds correlated
# failure; it does not make a second opinion a better one, and a deployment that
# reads ``distinct_source_vendor`` as "more correct" has read it wrong.
ReviewIndependence = Literal["shared", "distinct_model", "distinct_source_vendor"]


# The graph's LLM nodes. Deterministic FunctionNodes (validate, prepare, join,
# router, assemble) carry no model and never appear in the config. ``recritic``
# is the bounded critic re-ask: a distinct LLM node so it is pinned in its own
# right, running the same judgement as the critic and so always on the same
# tier.
#
# Three keys per framework, named for what they do. ``Analyst`` names the human
# reading the report, so it is not a node name here or anywhere else. These are
# the *tier config* keys; the graph's own node names are a separate namespace
# (they must be Python identifiers, and they carry the lane as well as the
# framework), mapped by :func:`katra.graph.tier_node_by_graph_node`,
# which is built per selection because which nodes exist is a function of it.
#
# **The keys are the service's, and there is one set per framework rather than
# one per lane.** A framework's lanes all run the same judgement on the same
# tier, so one key per lane would hold one value that nothing reads. What an
# operator chooses between is running one framework's analysis cheaper than
# another's.
#
# ``recritic/<name>`` is the bounded critic re-ask: a distinct node so it is
# pinned in its own right. It has no setting of its own, because it runs the
# critic's judgement: :meth:`ModelTierConfig.binding_of` gives it its critic's
# binding, so the two cannot run on different models.
#: A node role that each framework has a tier key for.
FrameworkRole = Literal["analyze", "critic", "recritic"]
#: Each :data:`FrameworkRole`, in the order of the tier keys.
FRAMEWORK_ROLES: tuple[FrameworkRole, ...] = get_args(FrameworkRole)


def tier_key(role: FrameworkRole, framework: str) -> str:
    """The tier-config key of one framework's node role, ``<role>/<framework>``.

    **The one spelling of a framework's tier key.** The node table, the graph's
    node table, the package check and the independence check all ask it.
    """
    return f"{role}/{framework}"


def lane_key(framework: str, lane: str) -> str:
    """The tier-config key of one lane, ``analyze/<framework>/<lane>``.

    **The one spelling of a lane's tier key.** An override may name it, and a
    lane with no override runs on the model of ``analyze/<framework>``.
    """
    return f"{tier_key('analyze', framework)}/{lane}"


def is_lane_slug(lane: str) -> bool:
    """Whether ``lane`` has the shape of a lane name: ASCII letters and digits,
    with hyphens between them.

    **The one reader of the lane-name shape.** A package's lanes and the lane
    part of a lane key both pass it, so a key that names no possible lane,
    such as one that holds a quote or a line break, is no lane key.
    """
    return bool(lane) and lane.isascii() and lane.replace("-", "").isalnum()


def framework_of_lane_key(node: str) -> str | None:
    """The framework whose lane ``node`` keys, or ``None`` if it keys no lane.

    The loader cannot list a package's lanes, because the packages import this
    module. So it accepts a lane key under every carried framework, and
    :func:`~katra.frameworks.validate_packages` refuses a lane the
    package does not declare.
    """
    return next(
        (
            name
            for name in FRAMEWORK_NAMES
            if node.startswith(lane_key(name, ""))
            and is_lane_slug(node.removeprefix(lane_key(name, "")))
        ),
        None,
    )


def framework_of_node(node: str) -> str | None:
    """The framework a node key belongs to, or ``None`` for a shared node."""
    lane_framework = framework_of_lane_key(node)
    if lane_framework is not None:
        return lane_framework
    return next(
        (
            name
            for name in FRAMEWORK_NAMES
            if node in (tier_key(role, name) for role in FRAMEWORK_ROLES)
        ),
        None,
    )


def setting_node(node: str) -> str:
    """The node whose model setting ``node`` runs on.

    **The one reader of "the re-ask follows its critic".** A re-ask runs on
    the setting of its critic; every other node runs on its own.
    """
    framework = framework_of_node(node)
    if framework is not None and node == tier_key("recritic", framework):
        return tier_key("critic", framework)
    return node


def _framework_nodes() -> tuple[str, ...]:
    return tuple(
        tier_key(role, name) for name in FRAMEWORK_NAMES for role in FRAMEWORK_ROLES
    )


FRAMEWORK_NODES: tuple[str, ...] = _framework_nodes()

#: The tier each LLM node belongs to. Fixed here and not in the config file:
#: a deployment that wants a node on another model gives it an override. The
#: workhorse nodes read sources and write rows; every framework node is
#: judgement.
_BASE: TierName = "base"
_STRONG: TierName = "strong"
NODE_TIERS: Mapping[str, TierName] = {
    **dict.fromkeys(("extract", "repair", "assert", "capabilities"), _BASE),
    **dict.fromkeys(FRAMEWORK_NODES, _STRONG),
}
#: Every LLM node, in the order of :data:`NODE_TIERS`.
LLM_NODES: tuple[str, ...] = tuple(NODE_TIERS)


def tier_of_node(node: str) -> TierName:
    """The tier a node or a lane key belongs to. A lane belongs to the tier of
    its framework's ``analyze`` node.

    **The one reader of :data:`NODE_TIERS`.**
    """
    framework = framework_of_lane_key(node)
    if framework is not None:
        node = tier_key("analyze", framework)
    return NODE_TIERS[node]


def is_override_key(node: str) -> bool:
    """Whether ``node`` is a key that can carry an override.

    Every LLM node except a re-ask, and every lane key. A re-ask runs on its
    critic's model, so a key for it would name a second model for one
    judgement.
    """
    known = node in NODE_TIERS or framework_of_lane_key(node) is not None
    return known and setting_node(node) == node


def is_binding_name(name: str) -> bool:
    """Whether ``name`` can be a binding: a tier name or an override key.

    The blessed manifest and a promotion use it to refuse a key that no
    configuration can produce.
    """
    return tier_named(name) is not None or is_override_key(name)


_ENV_PREFIX = "KATRA_MODEL_"
_VENDOR_FIELD = "VENDOR"
_MODEL_FIELD = "MODEL"
_CREDENTIALS_STEM = f"{_ENV_PREFIX}CREDENTIALS"
_CHARGES_STEM = f"{_ENV_PREFIX}CHARGES"
_UPSTREAMS_STEM = f"{_ENV_PREFIX}UPSTREAMS"


class ModelConfigError(ConfigError):
    """The model-tier configuration is invalid or unusable."""


# ``KATRA_MODEL_REVIEW_*`` names a tier that is not in this version. A
# deployment that sets one gets a message that names the critic override, not
# the generic refusal.
_RETIRED_REVIEW_PREFIX = f"{_ENV_PREFIX}REVIEW_"


def retired_review_message(variables: Iterable[str]) -> str:
    """The refusal for a ``KATRA_MODEL_REVIEW_*`` setting.

    The one wording, so the loader and the settings file reader say the same
    thing.
    """
    return (
        f"{', '.join(variables)}: the review tier is not in this version."
        " For an independent critic, give critic/<framework> an override:"
        ' a [nodes."critic/<framework>"] table with vendor and model in'
        " config/model_tiers.toml. The re-ask follows its critic."
    )


def is_retired_review_variable(name: str) -> bool:
    """Whether ``name`` is a ``KATRA_MODEL_REVIEW_*`` variable."""
    return name.startswith(_RETIRED_REVIEW_PREFIX)


def env_vars_for(tier: TierName) -> tuple[str, str]:
    """The ``(vendor, model)`` override vars for one tier."""
    stem = f"{_ENV_PREFIX}{tier.upper()}"
    return f"{stem}_{_VENDOR_FIELD}", f"{stem}_{_MODEL_FIELD}"


def credentials_env_var_for(vendor: VendorName) -> str:
    """The var declaring one vendor's credential mode.

    Keyed by vendor and not by tier, exactly as the ``[credentials]`` table is:
    a mode describes the deployment's relationship with a vendor, and a per-tier
    variable could name two identities for one vendor in one process.

    This exists so a deployment can select a multi-mode vendor from the
    environment alone. Every other selection already moves that way — a tier's
    vendor and model both do — and a credential mode that moved only in the file
    would mean a container image had to be rebuilt to run the vendor it already
    carries.
    """
    return f"{_CREDENTIALS_STEM}_{vendor.upper()}"


def upstreams_env_var_for(vendor: VendorName) -> str:
    """The variable that names one vendor's allowed upstreams from the environment.

    Keyed by vendor, as the ``[upstreams]`` table is, and holding a
    comma-separated list, because one deployment pins one set per gateway.
    """
    return f"{_UPSTREAMS_STEM}_{vendor.upper()}"


def charges_env_var_for(vendor: VendorName) -> str:
    """The var declaring one vendor's charge arrangement.

    Keyed by vendor, and movable from the environment, for the two reasons
    :func:`credentials_env_var_for` gives: an arrangement describes the
    deployment's relationship with a vendor rather than a tier's, and a
    deployment that can select a vendor from the environment must be able to
    declare everything that vendor requires from there too.
    """
    return f"{_CHARGES_STEM}_{vendor.upper()}"


def validate_model_string(value: str, vendor: VendorName, source: str) -> str:
    """Require a pinned model identifier for ``vendor``; reject floating forms.

    The rule is per-vendor data on the registry entry and is deliberately an
    open-world denylist — see :mod:`katra.vendors`. ``source`` names
    where the string came from so the error points at the right knob.
    """
    try:
        return vendor_for(vendor).validate_model(value, source)
    except ValueError as exc:
        raise ModelConfigError(str(exc)) from exc


class TierSelection(BaseModel):
    """One tier's ``(vendor, model)`` pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vendor: VendorName
    model: str

    @property
    def vendor_entry(self) -> Vendor:
        """The registry entry for this selection's vendor."""
        return vendor_for(self.vendor)

    @property
    def route(self) -> str:
        """The LiteLLM router string: the vendor's prefix joined to the model."""
        return self.vendor_entry.route(self.model)


class ModelTierConfig(BaseModel):
    """Validated per-tier selections and the node -> tier mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    tiers: dict[TierName, TierSelection]
    #: The overrides: node key -> the ``(vendor, model)`` pair that node runs
    #: on instead of its tier's. Empty in every shipped file.
    nodes: dict[str, TierSelection] = Field(default_factory=dict)
    #: Which credential mode this deployment declares for each vendor. Keyed by
    #: vendor rather than by tier: a mode describes the deployment's
    #: relationship with a vendor, and a per-tier key could name two identities
    #: for one vendor in one process.
    #:
    #: Empty in every shipped file, because no shipped file selects a vendor.
    #: :meth:`_credential_mode_problems` is what makes the table
    #: self-completing: a key for a single-mode vendor is an error, and a
    #: missing key for a multi-mode vendor is an error, so a vendor row that
    #: gains a second mode cannot ship without an operator declaring one.
    #: :func:`credentials_env_var_for` names the variable that fills it from the
    #: environment.
    credentials: dict[VendorName, CredentialMode] = Field(default_factory=dict)
    #: Which charge arrangement this deployment declares for each vendor that
    #: states what it charged. Keyed by vendor for the same reason
    #: :attr:`credentials` is, and self-completing by the same rule: a key for a
    #: vendor with nothing to choose is an error, and a missing key for a vendor
    #: with a choice is an error.
    #:
    #: Empty in every shipped file. What the declaration gives is a recorded
    #: figure that means one thing:
    #: :func:`katra.charges.records_reported_charge` records a
    #: vendor's reported charge only where the declared arrangement says the
    #: figure covers the whole call, and records nothing where it does not.
    #: :func:`charges_env_var_for` names the variable that fills it from the
    #: environment.
    charges: dict[VendorName, ChargeMode] = Field(default_factory=dict)
    #: Which upstream providers a request on each gateway vendor may reach.
    #: Keyed by vendor for the same reason :attr:`charges` is. Optional where
    #: the other two tables are required, because an analysis is an analysis
    #: whichever upstream answers; what a pin gives is a **Baseline**, which is
    #: named after the one upstream the record says served it, and a run that
    #: may land on two upstreams cannot be one. A key for a vendor whose
    #: :attr:`~katra.vendors.Vendor.upstream_pin` is ``None`` is an
    #: error, because there is nothing to pin.
    #: :func:`upstreams_env_var_for` names the variable that fills it from the
    #: environment.
    upstreams: dict[VendorName, tuple[str, ...]] = Field(default_factory=dict)
    #: How far each framework's criticism must sit from its own analysis. No
    #: default: a deployment states it, because inheriting ``shared`` is how a
    #: high-assurance install ends up reviewing itself and reporting nothing
    #: unusual. :data:`ReviewIndependence` names the three settings.
    review_independence: ReviewIndependence

    @property
    def bound_tiers(self) -> frozenset[TierName]:
        """The tiers this deployment runs something on.

        **The one reader of "is this tier bound".** A tier is bound while one
        node runs on it, that is, while one node of the tier has no override.
        A tier that every one of its nodes overrides needs no selection, no
        adapter, no credential and no SDK. The loader asks the same question of
        the raw table before validation, through :func:`tiers_in_use`, and a
        test holds the two answers equal: this one walks each node's binding,
        that one the tier of each node with no override.
        """
        return frozenset(
            tier
            for node in LLM_NODES
            if (tier := tier_named(self.binding_of(node))) is not None
        )

    @property
    def bound_vendors(self) -> tuple[VendorName, ...]:
        """Every vendor a binding selects, in binding order, without repeats.

        The question "which providers does this deployment actually call", which
        several callers ask: the credential, charge and upstream rules below,
        the build in :func:`~katra.binding.build_tier_adapters`, the settings
        save that keeps each vendor's key, and the diagnostic page that tells
        an operator which variables to set. An override's vendor is in it, and
        a vendor that only an unbound tier selects is not.
        """
        return tuple(
            dict.fromkeys(
                self.selection_for(binding).vendor for binding in self.bindings
            )
        )

    @model_validator(mode="after")
    def _check_complete(self) -> Self:
        # The tiers a node runs on, not both. `build_tier_adapters` binds no
        # adapter for an unused tier, so a demand for a selection for one would
        # ask an operator to choose a model no request reaches.
        missing_tiers = [
            tier
            for tier in TIER_NAMES
            if tier in self.bound_tiers and tier not in self.tiers
        ]
        if missing_tiers:
            raise ValueError(f"tiers missing entries for: {missing_tiers}")
        for tier, selection in self.tiers.items():
            validate_model_string(
                selection.model, selection.vendor, source=f"tiers.{tier}.model"
            )
        problems = [
            _override_key_problem(node)
            for node in sorted(self.nodes)
            if not is_override_key(node)
        ]
        if problems:
            raise ValueError("; ".join(problems))
        for node, selection in self.nodes.items():
            validate_model_string(
                selection.model, selection.vendor, source=f'nodes."{node}".model'
            )
        problems = self.independence_breaches()
        problems += self._credential_mode_problems()
        problems += self._charge_mode_problems()
        problems += self._upstream_problems()
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _credential_mode_problems(self) -> list[str]:
        """Every vendor whose declared mode is absent, spurious or not allowed.

        Both halves read :attr:`~katra.vendors.Vendor.credential_modes`,
        so the rule follows the registry rather than a second copy of it. A key for
        a single-mode vendor is an error because it is not a choice, and letting
        it sit there would let a file state a mode the registry has since
        replaced.

        Only vendors a binding selects are required to declare. A multi-mode
        vendor nobody calls needs no identity.
        :attr:`bound_vendors` is the reader that makes the rule match its own
        statement, and the same one the build uses.
        """
        problems = []
        selected = set(self.bound_vendors)
        for vendor, mode in self.credentials.items():
            allowed = vendor_for(vendor).credential_modes
            if len(allowed) == 1:
                problems.append(
                    f"credentials.{vendor} is set, but {vendor!r} allows only"
                    f" {allowed[0].value!r}, so there is nothing to choose;"
                    " remove the key"
                )
            elif mode not in allowed:
                names = ", ".join(sorted(m.value for m in allowed))
                problems.append(
                    f"credentials.{vendor} is {mode.value!r}, which {vendor!r}"
                    f" does not allow (it allows: {names})"
                )
        for vendor in sorted(selected - set(self.credentials)):
            allowed = vendor_for(vendor).credential_modes
            if len(allowed) > 1:
                names = ", ".join(sorted(m.value for m in allowed))
                bindings = ", ".join(
                    binding
                    for binding in self.bindings
                    if self.selection_for(binding).vendor == vendor
                )
                problems.append(
                    f"vendor {vendor!r} (selected by: {bindings}) allows more"
                    f" than one credential mode ({names}); declare the one this"
                    f" deployment uses in credentials.{vendor} or"
                    f" {credentials_env_var_for(vendor)}"
                )
        return problems

    def _charge_mode_problems(self) -> list[str]:
        """Every vendor whose declared arrangement is absent, spurious or not allowed.

        The mirror of :meth:`_credential_mode_problems`, reading
        :attr:`~katra.vendors.Vendor.charge_modes` so the rule
        follows the registry rather than a second copy of it. Three ways to be
        wrong rather than two: a vendor may also report no charge at all, and a
        key describing an arrangement with such a vendor describes nothing.

        Only vendors a binding selects are required to declare, exactly as with
        credentials. An undeclared arrangement does no harm until a call is
        made, and no call is made on a tier no node runs on.
        """
        problems = []
        selected = set(self.bound_vendors)
        for vendor, mode in self.charges.items():
            allowed = vendor_for(vendor).charge_modes
            if not allowed:
                problems.append(
                    f"charges.{vendor} is {mode.value!r}, but {vendor!r} states"
                    " no charge of its own, so the arrangement describes"
                    " nothing; remove the key"
                )
            elif len(allowed) == 1:
                problems.append(
                    f"charges.{vendor} is set, but {vendor!r} allows only"
                    f" {allowed[0].value!r}, so there is nothing to choose;"
                    " remove the key"
                )
            elif mode not in allowed:
                names = ", ".join(sorted(m.value for m in allowed))
                problems.append(
                    f"charges.{vendor} is {mode.value!r}, which {vendor!r}"
                    f" does not allow (it allows: {names})"
                )
        for vendor in sorted(selected - set(self.charges)):
            allowed = vendor_for(vendor).charge_modes
            if len(allowed) > 1:
                names = ", ".join(sorted(m.value for m in allowed))
                problems.append(
                    f"vendor {vendor!r} reports what it charged, and what that"
                    f" figure covers depends on the arrangement ({names}), so"
                    f" charges.{vendor} must declare which one this deployment"
                    " runs under"
                )
        return problems

    def _upstream_problems(self) -> list[str]:
        """Every declared upstream list that names nothing, or pins a direct vendor.

        Reads :attr:`~katra.vendors.Vendor.upstream_pin` so the
        rule follows the registry: a vendor that routes to one provider has
        nothing to pin, and a key for it describes nothing. Absence is never a
        problem here, because a pin is optional.
        """
        problems = []
        for vendor, names in self.upstreams.items():
            if vendor_for(vendor).upstream_pin is None:
                problems.append(
                    f"upstreams.{vendor} is set, but {vendor!r} routes to one"
                    " provider, so there is no upstream to pin; remove the key"
                )
            elif not names:
                problems.append(
                    f"upstreams.{vendor} names no upstream; list at least one, or"
                    " remove the key"
                )
            elif not all(UPSTREAM_SLUG.fullmatch(name) for name in names):
                problems.append(
                    f"upstreams.{vendor} holds an entry that is not a provider slug"
                )
        return problems

    def upstreams_for(self, vendor: VendorName) -> tuple[str, ...]:
        """The upstreams a request on one vendor may reach, or ``()`` unpinned.

        The one reader of the declaration. Empty means the gateway chooses,
        which is what every direct vendor also reads, because it has no
        choice to make.
        """
        return self.upstreams.get(vendor, ())

    def pinned_upstreams(self) -> tuple[str, ...]:
        """Every upstream a binding's request is pinned to, without repeats.

        What a job-wide bound reads: the deadline covers every tier a job runs
        on, so the slowest pinned upstream anywhere in the deployment is the
        one it has to fit. Empty where nothing is pinned.
        """
        return tuple(
            dict.fromkeys(
                name
                for vendor in self.bound_vendors
                for name in self.upstreams_for(vendor)
            )
        )

    def charge_mode(self, vendor: VendorName) -> ChargeMode | None:
        """The charge arrangement this deployment runs under for one vendor.

        ``None`` where the vendor states no charge, which is not a missing
        answer: there is no figure to describe, and the token arithmetic is what
        that vendor's cost is made of.

        The one reader of the declared-arrangement rule, on the same terms as
        :meth:`credential_mode`: a vendor with a single arrangement needs no
        declaration, and a vendor with a choice has already been required to
        make one, so the lookup never falls through to a guess.
        """
        entry = vendor_for(vendor)
        if not entry.reports_charge:
            return None
        declared = self.charges.get(vendor)
        return declared if declared is not None else entry.sole_charge_mode

    def credential_mode(self, vendor: VendorName) -> CredentialMode:
        """The credential mode this deployment uses for one vendor.

        The one reader of the declared-mode rule. A vendor with a single mode
        needs no declaration and gets that mode; a vendor with a choice has
        already been required to declare one by
        :meth:`_credential_mode_problems`, so the lookup cannot fall through to
        a guess.
        """
        declared = self.credentials.get(vendor)
        return (
            declared
            if declared is not None
            else vendor_for(vendor).sole_credential_mode
        )

    def independence_breaches(self) -> list[str]:
        """Every framework whose criticism is closer to its analysis than policy allows.

        **Fails closed at load, which is why there is no runtime warning.** A
        deployment that asked for a distinct reviewer and cannot have one has a
        configuration error, not a run to annotate — annotating it would put the
        finding in the artifact of a job somebody already paid for. What the
        report carries instead is the policy itself, so a reader of a ``shared``
        run can see that the review was same-domain rather than infer it.

        Checked per framework rather than once, because overrides are per node:
        a deployment may run one package's analysis on an override and
        another's on ``strong``, and each one's critic has to be independent of
        its own analysis, and of each lane override of that framework, rather
        than of some other package's. Each side is the node's effective
        selection, so an override is compared and not the tier under it.

        **A label is not the thing it names**, which is what a gateway makes
        true. Neither policy compares the vendor key that a deployment wrote,
        because an aggregator's vendor key says nothing about which model
        answered. ``gpt-5.6`` beside ``openai/gpt-5.6`` is two strings and one
        model, and ``openai`` beside ``openrouter`` can be one source vendor.
        So each policy reads the model ID. See :meth:`_independence_detail`.
        """
        if self.review_independence == "shared":
            return []
        breaches = []
        for name in FRAMEWORK_NAMES:
            critic = self.resolve_model(tier_key("critic", name))
            analyses = [
                tier_key("analyze", name),
                *(node for node in self.nodes if framework_of_lane_key(node) == name),
            ]
            for analysis in analyses:
                detail = self._independence_detail(self.resolve_model(analysis), critic)
                if detail is not None:
                    breaches.append(
                        f"review_independence is {self.review_independence!r}"
                        f" but {analysis} and critic/{name} are not independent:"
                        f" {detail}. Give critic/{name} an override in"
                        f' [nodes."critic/{name}"] whose model differs, or set'
                        f' review_independence to "shared" and accept a'
                        f" same-domain review"
                    )
        return breaches

    def _independence_detail(
        self, analyze: TierSelection, critic: TierSelection
    ) -> str | None:
        """Why these two are not independent under the policy, or ``None``.

        ``distinct_model`` compares the model identifiers with any gateway
        segment stripped, through the one reader of that rule
        (:func:`~katra.vendors.family_identifier`). A slug pins the
        model whichever route carries it, so ``openai/gpt-5.6`` through an
        aggregator and ``gpt-5.6`` direct are one model and a critic on the
        second removes none of the first's blind spots. The vendor is not part
        of the comparison: this policy is about the build, and two routes
        to one build share its blind spots however they are keyed.

        The limit is worth stating rather than hiding: a family a vendor spells
        its own way — Bedrock's ``anthropic.claude-opus-5`` beside
        ``claude-opus-5`` — still reads as two models here. Closing that needs a
        cross-vendor identity for a build, which nothing in this repository has,
        and a comparison that guessed at one would be the label problem again
        one level down.

        ``distinct_source_vendor`` compares the **Source Vendor** of each
        model through :func:`source_vendor_breach`, which the eval judge
        replay calls too.
        """
        if self.review_independence == "distinct_source_vendor":
            return source_vendor_breach(analyze.route, critic.route)
        shared_model = family_identifier(analyze.model)
        if shared_model == family_identifier(critic.model):
            return "both run one model"
        return None

    def binding_of(self, node: str) -> Binding:
        """The binding the named LLM node runs on.

        **The one reader of "which model setting does this node use".** The
        adapters, the sampling resolver, the execution record and the report
        row each key a node by this value. A node with an override runs on its
        own key. A re-ask runs on its critic's binding. A lane key with no
        override runs on its framework's ``analyze`` binding. Every other node
        runs on its tier.
        """
        if setting_node(node) != node:
            return self.binding_of(setting_node(node))
        if node in self.nodes:
            return node
        if node in NODE_TIERS:
            return tier_of_node(node)
        framework = framework_of_lane_key(node)
        if framework is None:
            raise ModelConfigError(f"unknown LLM node: {node!r}")
        return self.binding_of(tier_key("analyze", framework))

    @property
    def bindings(self) -> tuple[Binding, ...]:
        """Every binding a node runs on: the bound tiers, then the overrides.

        Tier order, then the override keys sorted, so the build order does not
        vary with how a config file happens to list its nodes.
        """
        return (
            *(tier for tier in TIER_NAMES if tier in self.bound_tiers),
            *sorted(self.nodes),
        )

    def selection_for(self, binding: Binding) -> TierSelection:
        """The ``(vendor, model)`` pair of one binding."""
        if binding in self.nodes:
            return self.nodes[binding]
        tier = tier_named(binding)
        if tier is None or tier not in self.tiers:
            raise ModelConfigError(f"no model selection for binding {binding!r}")
        return self.tiers[tier]

    def resolve_model(self, node: str) -> TierSelection:
        """The ``(vendor, model)`` pair the named LLM node runs on."""
        return self.selection_for(self.binding_of(node))


def source_vendor_breach(first: str, second: str) -> str | None:
    """Why the models on routes ``first`` and ``second`` share a **Source
    Vendor**, or ``None``.

    The ``distinct_source_vendor`` rule. The vendors that serve the two models
    do not matter: one source vendor through two vendors fails, and two source
    vendors through one aggregator pass. A model ID whose source vendor
    :func:`~katra.vendors.source_vendor_for_route` cannot read fails, because
    its maker is not known. The critic policy above and the eval judge replay
    (``evals/harness/judge_replay.py``) both apply it.
    """
    makers = []
    for route in (first, second):
        maker = source_vendor_for_route(route)
        if maker is None:
            return (
                f"the source vendor of {route!r} is not known: its model ID"
                " names no source vendor that its vendor row reads"
            )
        makers.append(maker)
    if makers[0] == makers[1]:
        return f"both run models from source vendor {makers[0]!r}"
    return None


def env_variables() -> tuple[str, ...]:
    """Every ``KATRA_MODEL_*`` override this loader reads.

    The one list of them: :func:`_apply_env_overrides` refuses each other
    variable under the prefix.
    """
    return (
        *(var for tier in TIER_NAMES for var in env_vars_for(tier)),
        *(credentials_env_var_for(vendor) for vendor in VENDOR_NAMES),
        *(charges_env_var_for(vendor) for vendor in VENDOR_NAMES),
        *(upstreams_env_var_for(vendor) for vendor in VENDOR_NAMES),
    )


def _apply_env_overrides(raw: dict[str, object], env: Mapping[str, str]) -> None:
    """Fold ``KATRA_MODEL_{TIER}_{VENDOR,MODEL}`` overrides into the raw tables.

    ``_MODEL`` alone is the ops case the file header exists for — retuning a
    tier's model on a deployed revision without an image rebuild. ``_VENDOR``
    alone is a **build-time error**: it is the one half-set case nothing
    downstream catches, because a cross-vendor pair like ``anthropic`` +
    ``gemini-2.5-pro`` passes the floating-form denylist and passes the
    sampling gate (an unknown model falls back to the provider's base config),
    and there is no build-time existence check — so it would die on node one of
    a paid-for job instead.

    ``KATRA_MODEL_CREDENTIALS_{VENDOR}`` folds into the ``[credentials]``
    table the same way, and the loader's own rules are what judge the result: a
    declaration for a single-mode vendor is an error whether it arrived from the
    file or from the environment, and so is a mode the vendor does not allow.
    ``KATRA_MODEL_CHARGES_{VENDOR}`` folds into ``[charges]`` under the same
    arrangement, judged by :meth:`ModelTierConfig._charge_mode_problems`.

    An unrecognised ``KATRA_MODEL_*`` variable also raises rather than being
    silently ignored while the tier quietly runs the file's model.

    That namespace check runs before the table is touched, so a typo'd override
    is reported even when the file selects nothing — which, since nothing is
    selected by default, is the state a deployment configured purely by
    environment starts from. A ``tiers`` table absent from the file is created
    empty here for the same reason: ``_VENDOR`` + ``_MODEL`` together are a
    complete selection, and requiring a file edit to make them land would mean
    no deployment could configure itself from the environment alone.
    """
    known = env_variables()
    retired = sorted(var for var in env if is_retired_review_variable(var))
    if retired:
        raise ModelConfigError(retired_review_message(retired))
    unknown = sorted(
        var for var in env if var.startswith(_ENV_PREFIX) and var not in known
    )
    if unknown:
        raise ModelConfigError(
            f"unrecognised model override(s): {unknown};"
            f" expected {sorted(known)} (schema version {SUPPORTED_VERSION})"
        )

    _apply_credential_overrides(raw, env)
    _apply_charge_overrides(raw, env)
    _apply_upstream_overrides(raw, env)

    tiers_raw = raw.setdefault("tiers", {})
    if not isinstance(tiers_raw, dict):
        # A malformed ``tiers`` shape: leave it for ModelTierConfig to reject
        # rather than applying an override against nothing.
        return

    for tier in TIER_NAMES:
        vendor_var, model_var = env_vars_for(tier)
        vendor = env.get(vendor_var)
        model = env.get(model_var)
        if vendor is not None and model is None:
            raise ModelConfigError(
                f"{vendor_var} is set without {model_var};"
                " a vendor without its model is not a usable selection"
            )
        if vendor is None and model is None:
            # Touching nothing is what lets an unselected tier stay unselected:
            # an empty table conjured here would read as a selection to
            # ``_require_selected_tiers`` and swap its message for a pydantic
            # dump about two missing fields.
            continue
        table = tiers_raw.setdefault(tier, {})
        if not isinstance(table, dict):
            raise ModelConfigError(f"tiers.{tier}: not a table")
        for var, value in ((vendor_var, vendor), (model_var, model)):
            if value is None:
                continue
            if not value.strip():
                raise ModelConfigError(f"{var} is set but empty")
            table[var.rsplit("_", 1)[-1].lower()] = value.strip()


def _apply_credential_overrides(raw: dict[str, object], env: Mapping[str, str]) -> None:
    """Fold ``KATRA_MODEL_CREDENTIALS_{VENDOR}`` into the raw table.

    The value is written through unvalidated: pydantic rejects a mode outside
    :class:`~katra.vendors.CredentialMode`, and
    :meth:`ModelTierConfig._credential_mode_problems` rejects one the vendor
    does not allow. Judging it here would be a second reader of both rules.
    """
    declared = {
        vendor: env[var]
        for vendor in VENDOR_NAMES
        if (var := credentials_env_var_for(vendor)) in env
    }
    if not declared:
        return
    table = raw.setdefault("credentials", {})
    if not isinstance(table, dict):
        raise ModelConfigError("credentials: not a table")
    for vendor, mode in declared.items():
        if not mode.strip():
            raise ModelConfigError(
                f"{credentials_env_var_for(vendor)} is set but empty"
            )
        table[vendor] = mode.strip()


def _apply_charge_overrides(raw: dict[str, object], env: Mapping[str, str]) -> None:
    """Fold ``KATRA_MODEL_CHARGES_{VENDOR}`` into the raw table.

    Written through unvalidated, exactly as the credential override is: pydantic
    rejects an arrangement outside
    :class:`~katra.vendors.ChargeMode`, and
    :meth:`ModelTierConfig._charge_mode_problems` rejects one the vendor does
    not allow.
    """
    declared = {
        vendor: env[var]
        for vendor in VENDOR_NAMES
        if (var := charges_env_var_for(vendor)) in env
    }
    if not declared:
        return
    table = raw.setdefault("charges", {})
    if not isinstance(table, dict):
        raise ModelConfigError("charges: not a table")
    for vendor, mode in declared.items():
        if not mode.strip():
            raise ModelConfigError(f"{charges_env_var_for(vendor)} is set but empty")
        table[vendor] = mode.strip()


def _apply_upstream_overrides(raw: dict[str, object], env: Mapping[str, str]) -> None:
    """Fold ``KATRA_MODEL_UPSTREAMS_{VENDOR}`` into the raw table.

    A comma-separated list, split and stripped here.
    :meth:`ModelTierConfig._upstream_problems` judges it: it rejects an empty
    list, a slug that is not one, and a vendor with nothing to pin.
    """
    declared = {
        vendor: env[var]
        for vendor in VENDOR_NAMES
        if (var := upstreams_env_var_for(vendor)) in env
    }
    if not declared:
        return
    table = raw.setdefault("upstreams", {})
    if not isinstance(table, dict):
        raise ModelConfigError("upstreams: not a table")
    for vendor, listed in declared.items():
        if not listed.strip():
            raise ModelConfigError(f"{upstreams_env_var_for(vendor)} is set but empty")
        table[vendor] = [name.strip() for name in listed.split(",") if name.strip()]


def tiers_in_use(nodes_raw: object) -> frozenset[TierName]:
    """The tiers a node runs on, given the override table.

    A tier is in use while one of its nodes has no override. A re-ask follows
    its critic, so it uses a tier only where its critic does. A tier that no
    node uses needs no selection: :func:`~katra.binding.build_tier_adapters`
    binds no adapter for it, so a pair for it is a pair no request reaches.

    Takes the raw table so the loader can ask before validation.
    :attr:`ModelTierConfig.bound_tiers` answers the same question from the
    bindings, and a test holds the two equal.
    """
    overridden = set(nodes_raw) if isinstance(nodes_raw, dict) else set()
    return frozenset(
        tier_of_node(node) for node in LLM_NODES if setting_node(node) not in overridden
    )


def _override_key_problem(node: str) -> str:
    """Why ``node`` cannot carry an override, for the loader's message."""
    if setting_node(node) != node:
        return (
            f'nodes."{node}": a re-ask runs on its critic\'s model and takes no'
            f' override; set one on [nodes."{setting_node(node)}"] and the'
            " re-ask follows it"
        )
    return (
        f'nodes."{node}": no LLM node has this key. An override is a'
        ' [nodes."<node>"] table with vendor and model, and <node> is extract,'
        " repair, assert, capabilities, analyze/<framework>, critic/<framework>"
        " or analyze/<framework>/<lane>"
    )


def _tier_map_problem(raw: Mapping[str, object]) -> str | None:
    """Why ``raw`` holds a node -> tier map or a ``review`` tier, or ``None``.

    The tier of each node is fixed in code, so a string value under
    ``[nodes]`` names a tier this file cannot set, and ``review`` is not a
    tier. Both get a message that names the override shape, because
    "unsupported version" alone does not say what to write.
    """
    nodes = raw.get("nodes")
    tiers = raw.get("tiers")
    if isinstance(nodes, dict) and any(isinstance(v, str) for v in nodes.values()):
        return (
            "[nodes] holds tier names, which this version does not read: the"
            ' tier of each node is fixed. Delete each `node = "<tier>"` line.'
            ' To run one node on its own model, write a [nodes."<node>"] table'
            ' with vendor and model, for example [nodes."critic/<framework>"].'
        )
    if isinstance(tiers, dict) and "review" in tiers:
        return (
            "[tiers.review] is not a tier in this version. For an independent"
            ' critic, write a [nodes."critic/<framework>"] table with vendor'
            " and model; the re-ask follows its critic."
        )
    return None


def _require_selected_tiers(
    path: Path | str, tiers_raw: object, nodes_raw: object
) -> None:
    """Stop with an actionable message when a tier in use names no vendor.

    Separate from :meth:`ModelTierConfig._check_complete`, which catches the
    same gap for a config built in code and reports it as a pydantic validation
    error. This one exists for the *shipped* state — a
    first run against a config that selects nothing — where the error is the
    entire onboarding instruction, so it names the vendors that are available
    and both places a selection can be made. A pydantic error dump at that
    moment would be accurate and useless.

    Vendor **names** only. The message is reached before any credential is
    read, and naming a variable's value here is how a key ends up in a log
    (OWASP A09).
    """
    selected = tiers_raw if isinstance(tiers_raw, dict) else {}
    # A *complete* pair, not merely a present table: `_MODEL` alone against an
    # unselected file leaves a tier holding a model and no vendor, which is the
    # same unmade choice and deserves the same instruction.
    in_use = tiers_in_use(nodes_raw)
    missing = [
        tier
        for tier in TIER_NAMES
        if tier in in_use
        and not (
            isinstance(selected.get(tier), dict)
            and {"vendor", "model"} <= set(selected[tier])
        )
    ]
    if not missing:
        return
    overrides = " and ".join(" + ".join(env_vars_for(tier)) for tier in missing)
    raise ModelConfigError(
        f"{path}: no vendor selected for tier(s) {missing}."
        " This service ships no default vendor, so each tier must name one"
        f" before it can run. Supported vendors: {', '.join(VENDOR_NAMES)}."
        f" Set a (vendor, model) pair per tier in the file, or set {overrides}."
        " See docs/First-Run.md step 2."
    )


def load_model_tiers(
    path: Path | str,
    env: Mapping[str, str],
) -> ModelTierConfig:
    """Load and validate the tier config, applying env-var overrides.

    Overrides are folded in before validation, so a floating identifier arriving
    via the environment is rejected exactly like one in the file. Every failure
    path raises :class:`ModelConfigError`.
    """
    raw = read_toml(path, ModelConfigError)

    # Before the overrides and the version check, so a node -> tier map or a
    # review tier gets the message that says what to write instead.
    shape = _tier_map_problem(raw)
    if shape is not None:
        raise ModelConfigError(f"{path}: {shape} Set version = {SUPPORTED_VERSION}.")

    _apply_env_overrides(raw, env)

    version = raw.get("version")
    if not is_version(version, SUPPORTED_VERSION):
        raise ModelConfigError(
            f"{path}: unsupported version {version!r}; expected {SUPPORTED_VERSION}"
        )

    # After the version check, so an old file reports the schema it is rather
    # than the selection it is missing.
    _require_selected_tiers(path, raw.get("tiers"), raw.get("nodes"))

    try:
        return ModelTierConfig(**raw)
    except ValidationError as exc:
        raise ModelConfigError(f"{path}: {validation_problems(exc)}") from exc
