"""Ask a model judge whether a sweep's STRIDE findings are supported (#764).

The judge answers one question for each finding: does the source support it?
It is a judge of substance. It never decides whether two claims are one finding (ADR
0003 retired that judge), and its verdicts never enter the **Ledger**, a
recall figure or a gate. They have their own standing, in the output file.

**One batch per case and sample.** A batch holds the case's sources, its
**System Model** and three populations, shuffled together:

* the report's unlisted findings: the unmatched claims of
  :func:`~evals.harness.scorer.score_case`;
* the report's matched findings, as known positives;
* the plants of :func:`~evals.harness.plants.write_plants`, as known
  negatives (see **Plant**).

A lane error and a finding that cites a foreign element are in neither
population. The output counts them under ``left_out``. The judge sees each
finding's category, title, description, elements and grounds, and never the
critic's verdict or its reason.

**Two samples, each in its own order.** A finding that the valid samples answer
differently reads ``unsure``, and the output states the agreement rate. A
sample in which the judge supports a plant is void: its verdicts count for no
finding, and the output names the batch.

**STRIDE only.** The populations are STRIDE findings at model elements, read
through :func:`~evals.harness.bundle.stride_threats`. ASVS writes exclusions,
which are not findings at an element, and #764 names them as a later
population.

**A different source vendor.** The judge runs on the model that ``--judge``
names, at the sampling :data:`JUDGE_SAMPLING` pins, and the output records
both. The
command refuses to send when :func:`~katra.model_tiers.source_vendor_breach`
finds that the judge's model and a model that wrote the sweep come from one
**Source Vendor**. The writers are the routes that the sweep's provenance
records as requested. The vendor that serves each model does not matter, so a
judge or a writer through an aggregator passes when the source vendors differ.
A sweep whose provenance records no requested model is refused, because its
writer is not known. The replay test runs on ``d4edd64-gpt-5.6-terra-fd1c49af``.

**Moved sources.** Where the sweep records a digest of each case's rendered
sources, a case whose sources differ today is left out and named under
``moved_sources``: its findings were written against other text than the
judge would read. :func:`~evals.harness.artifact.rendered_sources` computes
today's digest.

**Paid, with consent.** The command builds every request offline and states an
estimate through :class:`~evals.harness.consent.Estimate`. ``--dry-run``
writes the requests and sends nothing. A live run takes consent through
:func:`~evals.harness.consent.gate`, and ``KATRA_OFFLINE`` refuses its first
call. A judge route with no price, such as one through ``openrouter``, has
no estimate. Where its vendor reports the whole charge of each call,
:func:`~evals.harness.consent.charged` labels the estimate ``charged``, and an
accepted amount caps the run. Before each call it runs the sweep's hold,
:func:`~evals.harness.consent.hold`, over the calls made so far: it prices the
token usage and the attempts each call reported (a call that reported no usage
counts at its estimate, and each failed attempt counts as one more prompt), or
on a route with no price it counts the reported charge once for each attempt.
It stops, or asks again, when the spend so far plus the dearest call so far
passes the accepted amount. The first call runs with no bound, and a call on a
route with no price that reports no charge stops the run. It writes the output file
after each answer. A provider failure stops the run, and the output keeps the
answers so far and names each call that did not run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self, get_args

from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evals.harness import consent
from evals.harness.artifact import (
    CORPUS_DIR,
    EvalArtifact,
    ProvenanceError,
    corpus_digest,
    load_artifact,
    recorded_sources,
    rendered_sources,
)
from evals.harness.bundle import check_out, finished_file, read_report, stride_threats
from evals.harness.flow_ids import (
    MigrationError,
    flow_id_version_of_graph,
    table_between,
)
from evals.harness.identity import SubsetVerbIdentity
from evals.harness.ledger import Ledger
from evals.harness.modes import EvalRunError
from evals.harness.node_call import NodeCall, selection_call, spent_line
from evals.harness.plants import Plant, write_plants
from evals.harness.prices import price_calls, unit_prices
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import (
    CorpusError,
    flows_by_case,
    load_case,
    refuse_holdout,
)
from evals.harness.run_record import Selections, run_record_for
from evals.harness.scorer import score_case
from evals.reference_facts import facts_path, load_facts
from katra.claim_identity import report_rows
from katra.deployment import Deployment
from katra.execution import seed_state
from katra.frameworks.stride.record import Threat
from katra.graph import STATE_INPUT_TEXT, STATE_SOURCE_TEXTS, render_model
from katra.grounding import normalize, verify_normalized
from katra.model_tiers import (
    ModelConfigError,
    TierSelection,
    source_vendor_breach,
    validate_model_string,
)
from katra.offline import LiveInferenceRefused
from katra.report import NodeRun, TokenUsage
from katra.sampling import TierSampling
from katra.sources import text_digest
from katra.system_model import EXCERPT_MAX_CHARS, FLOW_ID_VERSION, SystemModel
from katra.vendors import VENDOR_NAMES

#: The node name a judge call takes in the node runs the spend hold prices.
JUDGE_NODE = "judge"

#: The judge's sampling, pinned here because the judge is no node and has no
#: block in ``config/sampling.toml``. It holds the values of the ``strong``
#: and ``review`` blocks of that file: a pinned output cap and every other
#: param at its default.
JUDGE_SAMPLING = TierSampling(max_output_tokens=64000)

#: Where an error message sends an operator who must change the judge's sampling.
JUDGE_SAMPLING_SOURCE = "JUDGE_SAMPLING in evals/harness/judge_replay.py"

#: The judge's instruction. It is eval-only text, so it sits under ``evals/``.
INSTRUCTION = REPO_ROOT / "evals" / "prompts" / "judge.md"

#: The samples of each case that #764 asks for.
DEFAULT_SAMPLES = 2

#: The characters of request text that the estimate counts as one token. No
#: tokenizer runs offline for every vendor, so the estimate states this rate.
CHARS_PER_TOKEN = 4

#: The output tokens the estimate allows for one finding's answer: its verdict,
#: reason and quote, and the reasoning a model writes before them. No paid run
#: measured this figure, and the estimate says so.
OUTPUT_TOKENS_PER_FINDING = 300

#: The answer the judge gives one finding.
JudgeVerdict = Literal["supported", "rejected", "unsure"]
VERDICTS: tuple[JudgeVerdict, ...] = get_args(JudgeVerdict)

#: Where a finding in a batch comes from.
Population = Literal["matched", "unlisted", "plant"]
POPULATIONS: tuple[Population, ...] = get_args(Population)

#: The count of plants that a readable sample left with no answer.
NO_ANSWER = "no_answer"

#: How a judge's quote stands against the case's sources.
QuoteState = Literal["verified", "unverifiable", "absent"]
QUOTE_STATES: tuple[QuoteState, ...] = get_args(QuoteState)

#: The fields of a report finding that the judge sees. The critic's verdict and
#: its reason are not in the list, so the judge is blind to the critic.
VIEW_FIELDS: tuple[str, ...] = (
    "category",
    "title",
    "description",
    "affected_element_ids",
    "grounds",
)


class FindingAnswer(BaseModel):
    """The judge's answer to one finding."""

    model_config = ConfigDict(extra="forbid")

    finding: str = Field(max_length=16)
    verdict: JudgeVerdict
    reason: str = Field(max_length=2000)
    quote: str = Field(max_length=EXCERPT_MAX_CHARS)


class JudgeAnswer(BaseModel):
    """The judge's answer to one batch: the schema the provider receives."""

    model_config = ConfigDict(extra="forbid")

    findings: list[FindingAnswer]


@dataclass(frozen=True)
class Item:
    """One finding in a case's batch, with the population it comes from."""

    key: str
    population: Population
    view: Mapping[str, Any]


@dataclass(frozen=True)
class CaseInput:
    """Everything one case's batches hold, built offline."""

    case: str
    input_text: str
    #: Each source's text, folded once by :func:`~katra.grounding.normalize`
    #: for the quote check.
    folded_sources: tuple[str, ...]
    model_text: str
    items: tuple[Item, ...]
    plants: tuple[Plant, ...]
    #: The report's findings that are in no population, by the scorer's reason.
    left_out: Mapping[str, int]


@dataclass(frozen=True)
class Request:
    """One batch as the judge receives it."""

    case: str
    sample: int
    #: Each label in the batch, with the key of the finding it stands for.
    labels: tuple[tuple[str, str], ...]
    text: str

    def turn(self) -> types.Content:
        return types.Content(role="user", parts=[types.Part(text=self.text)])


def view(threat: Threat) -> dict[str, Any]:
    """The fields of ``threat`` that the judge sees."""
    dumped = threat.model_dump(mode="json")
    seen = {name: dumped[name] for name in VIEW_FIELDS}
    seen["grounds"] = [
        ground.model_dump(exclude_defaults=True) for ground in threat.grounds
    ]
    return seen


def current_flow_ids(model: SystemModel) -> dict[str, str]:
    """Each flow ID of an archived model against the ID this code writes, where
    the two differ, through :func:`~evals.harness.flow_ids.table_between`."""
    raw = model.model_dump(mode="json")
    try:
        version = flow_id_version_of_graph(raw)
    except MigrationError as error:
        raise EvalRunError(str(error)) from error
    return table_between(raw, version, FLOW_ID_VERSION)


def case_input(artifact: EvalArtifact, case_id: str, rng: random.Random) -> CaseInput:
    """One case's populations, plants and sources, read from the sweep."""
    refuse_holdout(case_id)
    path = finished_file(artifact, case_id, "report")
    if path is None:
        raise EvalRunError(f"{case_id}: the sweep wrote no report for the case")
    report = read_report(path)
    case = load_case(CORPUS_DIR / case_id)
    produced = stride_threats(report)
    flows = flows_by_case([case], {case.id: report.system_model})
    score = score_case(
        case, produced, SubsetVerbIdentity(flows), Ledger(), report_rows(report)
    )
    by_id = {threat.id: threat for threat in produced}
    case_dir = CORPUS_DIR / case_id
    facts = load_facts(case_dir) if facts_path(case_dir).is_file() else None
    plants = write_plants(
        case_id, report.system_model, facts, current_flow_ids(report.system_model), rng
    )
    items = (
        *(
            Item(pair.threat_id, "matched", view(by_id[pair.threat_id]))
            for pair in score.matched
        ),
        *(
            Item(entry.threat_id, "unlisted", view(by_id[entry.threat_id]))
            for entry in score.unlisted
        ),
        *(
            Item(f"plant-{n}", "plant", plant.view())
            for n, plant in enumerate(plants, 1)
        ),
    )
    seeded = seed_state(case.sources)
    return CaseInput(
        case=case_id,
        input_text=seeded[STATE_INPUT_TEXT],
        folded_sources=tuple(
            normalize(text) for text in seeded[STATE_SOURCE_TEXTS].values()
        ),
        model_text=render_model(report.system_model.model_dump(mode="json")),
        items=items,
        plants=plants,
        left_out={"lane_errors": len(score.lane_errors), "foreign": len(score.foreign)},
    )


def requests_for(
    inputs: Sequence[CaseInput], samples: int, rng: random.Random
) -> list[Request]:
    """Each case's batch once per sample, each sample in its own order."""
    requests = []
    for held in inputs:
        width = max(2, len(str(len(held.items))))
        for sample in range(1, samples + 1):
            order = rng.sample(held.items, len(held.items))
            labelled = [(f"F-{n:0{width}d}", item) for n, item in enumerate(order, 1)]
            findings = [{"label": label, **item.view} for label, item in labelled]
            text = (
                f"# Source\n\n{held.input_text}\n\n"
                f"# System model\n\n{held.model_text}\n\n"
                f"# Findings\n\n```json\n{json.dumps(findings, indent=2)}\n```\n"
            )
            requests.append(
                Request(
                    held.case,
                    sample,
                    tuple((label, item.key) for label, item in labelled),
                    text,
                )
            )
    return requests


def request_usage(instruction: str, request: Request) -> TokenUsage:
    """The tokens the estimate counts for one request."""
    prompt = math.ceil((len(instruction) + len(request.text)) / CHARS_PER_TOKEN)
    completion = OUTPUT_TOKENS_PER_FINDING * len(request.labels)
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def request_costs(
    instruction: str, requests: Sequence[Request], route: str
) -> list[float] | None:
    """Each request's estimated price on ``route``, or ``None`` where the price
    map holds no rate for it."""
    if unit_prices(route) is None:
        return None
    return [
        price_calls([(route, route, request_usage(instruction, request))]).total_usd
        for request in requests
    ]


def estimate(
    instruction: str, requests: Sequence[Request], route: str
) -> consent.Estimate:
    """What sending ``requests`` on ``route`` is expected to cost."""
    usages = [request_usage(instruction, request) for request in requests]
    prompt = sum(usage.prompt_tokens for usage in usages)
    completion = sum(usage.completion_tokens for usage in usages)
    lines = [
        (
            f"{len(requests)} judge calls on {route}: about {prompt} prompt tokens"
            f" and {completion} output tokens"
        ),
        (
            f"prompt tokens are characters / {CHARS_PER_TOKEN}; output tokens are"
            f" {OUTPUT_TOKENS_PER_FINDING} a finding, a figure no paid run measured"
        ),
    ]
    costs = request_costs(instruction, requests, route)
    if costs is None:
        lines.append(f"the price map holds no rate for {route}")
        return consent.Estimate(label="unpriced", amount_usd=None, lines=tuple(lines))
    by_case: dict[str, float] = defaultdict(float)
    for request, cost in zip(requests, costs, strict=True):
        by_case[request.case] += cost
    lines += [f"{case}: ${amount:.4f}" for case, amount in by_case.items()]
    return consent.Estimate(
        label="estimated", amount_usd=sum(costs), lines=tuple(lines)
    )


def writer_routes(artifact: EvalArtifact) -> tuple[str, ...]:
    """Each route the sweep's nodes requested, from its provenance."""
    return tuple(
        sorted(
            {
                route
                for identity in artifact.provenance.tier_identities().values()
                for route in identity.requested_models
            }
        )
    )


def independence_breach(writers: Iterable[str], judge: str) -> str | None:
    """Why the judge's route shares a source vendor with a writer's, or ``None``.

    A sweep that names no writer fails closed: its writer is not known.
    """
    writers = tuple(writers)
    if not writers:
        return (
            "the sweep's provenance records no requested model, so the model"
            " that wrote it is not known"
        )
    for writer in writers:
        detail = source_vendor_breach(writer, judge)
        if detail is not None:
            return detail
    return None


@dataclass(frozen=True)
class Answered:
    """The judge's answer to one finding in one sample."""

    verdict: JudgeVerdict
    reason: str
    quote: str
    quote_state: QuoteState


def quote_state(quote: str, folded_sources: Sequence[str]) -> QuoteState:
    """Whether ``quote`` appears in one of the sources, by the fan-in's check.

    ``folded_sources`` holds each source folded once by
    :func:`~katra.grounding.normalize`, as :func:`~katra.grounding.verify_quote`
    asks of a caller that checks many quotes.
    """
    if not quote.strip():
        return "absent"
    found = any(verify_normalized(quote, folded) for folded in folded_sources)
    return "verified" if found else "unverifiable"


@dataclass(frozen=True)
class SampleReading:
    """One sample's answer, read against its batch."""

    sample: int
    #: The answer to each finding, by its key.
    answers: Mapping[str, Answered]
    #: The keys of the findings the judge did not answer.
    unanswered: tuple[str, ...]
    #: The labels the judge answered that are not in the batch, or that it
    #: answered twice.
    stray: tuple[str, ...]
    #: Whether the answer did not parse under :class:`JudgeAnswer`.
    unreadable: bool
    #: Whether the judge supported a plant, which voids the sample.
    void: bool

    def to_json(
        self, items: Sequence[Item], labels: Mapping[str, str]
    ) -> dict[str, Any]:
        return {
            "sample": self.sample,
            "void": self.void,
            "unreadable": self.unreadable,
            "stray": list(self.stray),
            "findings": [
                {
                    "key": item.key,
                    "population": item.population,
                    "label": labels[item.key],
                    **(
                        {
                            "verdict": answer.verdict,
                            "reason": answer.reason,
                            "quote": answer.quote,
                            "quote_state": answer.quote_state,
                        }
                        if (answer := self.answers.get(item.key))
                        else {"verdict": None}
                    ),
                }
                for item in items
            ],
        }


def read_answer(
    raw: str, request: Request, items: Sequence[Item], folded_sources: Sequence[str]
) -> SampleReading:
    """One sample's answer, checked against its batch and the sources.

    A quote that the sources do not hold is counted, never repaired.
    """
    try:
        answer = JudgeAnswer.model_validate_json(raw)
    except ValidationError:
        keys = tuple(key for _, key in request.labels)
        return SampleReading(request.sample, {}, keys, (), True, False)
    keyed = dict(request.labels)
    answers: dict[str, Answered] = {}
    stray: list[str] = []
    for given in answer.findings:
        key = keyed.get(given.finding)
        if key is None or key in answers:
            stray.append(given.finding)
            continue
        answers[key] = Answered(
            given.verdict,
            given.reason,
            given.quote,
            quote_state(given.quote, folded_sources),
        )
    plants = {item.key for item in items if item.population == "plant"}
    return SampleReading(
        sample=request.sample,
        answers=answers,
        unanswered=tuple(key for _, key in request.labels if key not in answers),
        stray=tuple(stray),
        unreadable=False,
        void=any(answers[key].verdict == "supported" for key in plants & set(answers)),
    )


@dataclass
class Numbers:
    """The four numbers of #764, each with its denominator."""

    plants: Counter[str] = field(default_factory=Counter)
    matched: Counter[str] = field(default_factory=Counter)
    unlisted: Counter[str] = field(default_factory=Counter)
    agreement: Counter[str] = field(default_factory=Counter)
    quotes: Counter[str] = field(default_factory=Counter)

    def __iadd__(self, other: Numbers) -> Self:
        for name in ("plants", "matched", "unlisted", "agreement", "quotes"):
            getattr(self, name).update(getattr(other, name))
        return self

    def to_json(self) -> dict[str, Any]:
        def tally(counts: Counter[str], keys: Iterable[str]) -> dict[str, int]:
            return {key: counts[key] for key in keys} | {"of": counts["of"]}

        return {
            "plants": tally(
                self.plants, ("rejected", "supported", "unsure", NO_ANSWER)
            ),
            "matched": tally(self.matched, VERDICTS),
            "unlisted": tally(self.unlisted, VERDICTS),
            "self_agreement": tally(self.agreement, ("agreed",)),
            "quotes": {state: self.quotes[state] for state in QUOTE_STATES},
        }


def final_verdict(key: str, valid: Sequence[SampleReading]) -> JudgeVerdict:
    """The verdict the valid samples give a finding: theirs where all agree,
    otherwise ``unsure``. A sample that left the finding unanswered disagrees."""
    given = {
        reading.answers[key].verdict if key in reading.answers else None
        for reading in valid
    }
    verdict = given.pop() if len(given) == 1 else None
    return verdict or "unsure"


def case_numbers(items: Sequence[Item], readings: Sequence[SampleReading]) -> Numbers:
    """One case's numbers.

    The plant counts read every sample the judge answered readably, void or
    not, because a void comes from a plant. The other counts read the valid
    samples only: readable and not void. A case with no valid sample adds to
    no count but the plants, and a case with one valid sample adds no
    agreement.
    """
    numbers = Numbers()
    readable = [reading for reading in readings if not reading.unreadable]
    valid = [reading for reading in readable if not reading.void]
    for reading in readable:
        numbers.quotes.update(answer.quote_state for answer in reading.answers.values())
        for item in items:
            if item.population != "plant":
                continue
            answer = reading.answers.get(item.key)
            numbers.plants[answer.verdict if answer else NO_ANSWER] += 1
            numbers.plants["of"] += 1
    if not valid:
        return numbers
    for item in items:
        if item.population == "plant":
            continue
        counts = numbers.matched if item.population == "matched" else numbers.unlisted
        counts[final_verdict(item.key, valid)] += 1
        counts["of"] += 1
        if len(valid) > 1:
            answers = [reading.answers.get(item.key) for reading in valid]
            numbers.agreement["agreed"] += all(answers) and (
                len({answer.verdict for answer in answers if answer}) == 1
            )
            numbers.agreement["of"] += 1
    return numbers


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "artifact", type=Path, help="the sweep or Baseline sweep to judge"
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="write the requests or the verdicts here",
    )
    parser.add_argument(
        "--judge",
        required=True,
        help="the judge's model as <vendor>/<model>, where <vendor> is a vendor"
        " name of the tier config. JUDGE_SAMPLING pins its sampling",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=f"samples of each case, each in its own order (default {DEFAULT_SAMPLES})",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="judge only this case; repeat it for more. Default: every case the"
        " sweep finished",
    )
    sending = parser.add_mutually_exclusive_group()
    sending.add_argument(
        "--dry-run",
        action="store_true",
        help="build every request, print the estimate and write the requests;"
        " send nothing",
    )
    sending.add_argument(
        "--accept-cost",
        help="the amount you accept, or 'unknown' for a route the price map does"
        " not price. Without it, the command asks you to type the amount",
    )


def _cases(artifact: EvalArtifact, named: Sequence[str] | None) -> list[str]:
    finished = [case for case in artifact.cases if case not in artifact.failed_cases()]
    if named is None:
        return finished
    unknown = sorted(set(named) - set(finished))
    if unknown:
        raise EvalRunError(f"the sweep finished no case named {', '.join(unknown)}")
    return list(named)


def moved_sources(artifact: EvalArtifact, cases: Sequence[str]) -> list[str]:
    """The cases whose sources the sweep recorded under another digest.

    Read as ``fan_in_accounting.py`` reads it: the sweep's own record through
    :func:`~evals.harness.artifact.recorded_sources`, against today's digest
    from :func:`~evals.harness.artifact.rendered_sources`. A sweep that records
    no digest moves no case.
    """
    recorded = recorded_sources(artifact) or {}
    return [
        case_id
        for case_id in cases
        if (digest := recorded.get(case_id)) is not None
        and digest != rendered_sources([load_case(CORPUS_DIR / case_id)])[case_id]
    ]


def judge_selection(named: str) -> TierSelection:
    """The judge's ``(vendor, model)`` pair from ``--judge <vendor>/<model>``.

    The vendor is the text before the first ``/``. An aggregator's model
    carries a slash of its own, so the rest is the model as the vendor spells
    it. The model must be pinned, as a tier's model must be.
    """
    vendor, _, model = named.partition("/")
    if vendor not in VENDOR_NAMES or not model:
        raise EvalRunError(
            f"--judge {named!r} is not <vendor>/<model>; the vendors are"
            f" {', '.join(VENDOR_NAMES)}"
        )
    try:
        validate_model_string(model, vendor, source="--judge")
    except ModelConfigError as error:
        raise EvalRunError(str(error)) from error
    return TierSelection(vendor=vendor, model=model)


def measured_run(
    entry: Mapping[str, Any] | None, fallback: TokenUsage, route: str
) -> NodeRun:
    """One judge call as a node run that :func:`~evals.harness.consent.hold`
    prices: the usage the provider reported, as ``seen`` records it, or
    ``fallback``, the call's estimate, where it reported none. The attempts and
    re-asks the retry driver stamped go on the run too, so the hold prices each
    failed attempt as a graph run's node run does. The charge the provider
    reported goes on the run as ``reported_charge_usd``, which the hold counts
    where the price map holds no rate for the route."""
    if entry is None:
        usage, attempts, reasks, charge = fallback, 1, 0, None
    else:
        reported = entry["usage"]
        usage = fallback if reported is None else TokenUsage.model_validate(reported)
        attempts, reasks = entry["attempts"], entry["reasks"]
        charge = entry["reported_charge_usd"]
    return NodeRun(
        node=JUDGE_NODE,
        model=route,
        requested_model=route,
        duration_ms=0,
        usage=usage,
        attempts=attempts,
        reasks=reasks,
        reported_charge_usd=charge,
    )


async def _ask(call: NodeCall, instruction: str, request: Request) -> str:
    """One judge call, as a coroutine that an event loop runs."""
    return await call(instruction, request.turn())


def estimate_lines(cost: consent.Estimate) -> list[str]:
    """The estimate as the dry run prints it."""
    amount = "no amount" if cost.amount_usd is None else f"${cost.amount_usd:.2f}"
    return [
        f"the judge replay is expected to cost {amount} [{cost.label}]",
        *(f"  {line}" for line in cost.lines),
    ]


def dry_cases(
    inputs: Sequence[CaseInput], requests: Sequence[Request]
) -> list[dict[str, Any]]:
    """Each case's plants, populations and the requests a live run sends."""
    return [
        {
            "case": held.case,
            "plants": [plant.to_json() for plant in held.plants],
            "populations": dict(Counter(item.population for item in held.items)),
            "left_out": dict(held.left_out),
            "requests": [
                {
                    "sample": request.sample,
                    "labels": dict(request.labels),
                    "text": request.text,
                }
                for request in requests
                if request.case == held.case
            ],
        }
        for held in inputs
    ]


def judged(
    inputs: Sequence[CaseInput],
    requests: Sequence[Request],
    raws: Sequence[str | None],
) -> dict[str, Any]:
    """The verdicts of every batch, and the numbers per case and pooled.

    A ``None`` answer is a call that did not run. It counts for nothing, and the
    result names it under ``not_run``.
    """
    pooled = Numbers()
    cases = []
    void: list[dict[str, Any]] = []
    for held in inputs:
        sent = [
            (request, raw)
            for request, raw in zip(requests, raws, strict=True)
            if request.case == held.case and raw is not None
        ]
        readings = [
            read_answer(raw, request, held.items, held.folded_sources)
            for request, raw in sent
        ]
        numbers = case_numbers(held.items, readings)
        pooled += numbers
        void += [
            {"case": held.case, "sample": reading.sample}
            for reading in readings
            if reading.void
        ]
        cases.append(
            {
                "case": held.case,
                "plants": [plant.to_json() for plant in held.plants],
                "left_out": dict(held.left_out),
                "numbers": numbers.to_json(),
                "samples": [
                    reading.to_json(
                        held.items, {key: label for label, key in request.labels}
                    )
                    for reading, (request, _) in zip(readings, sent, strict=True)
                ],
            }
        )
    return {
        "not_run": [
            {"case": request.case, "sample": request.sample}
            for request, raw in zip(requests, raws, strict=True)
            if raw is None
        ],
        "void_batches": void,
        "unplanted": [held.case for held in inputs if not held.plants],
        "pooled": pooled.to_json(),
        "cases": cases,
    }


def summary_lines(result: Mapping[str, Any]) -> list[str]:
    """One line per case and one pooled, each count over its denominator."""

    def line(name: str, numbers: Mapping[str, Any]) -> str:
        plants, matched = numbers["plants"], numbers["matched"]
        unlisted, agreement = numbers["unlisted"], numbers["self_agreement"]
        return (
            f"{name}: plants rejected {plants['rejected']} of {plants['of']};"
            f" matched supported {matched['supported']} of {matched['of']};"
            f" unlisted supported {unlisted['supported']}, rejected"
            f" {unlisted['rejected']}, unsure {unlisted['unsure']} of {unlisted['of']};"
            f" self-agreement {agreement['agreed']} of {agreement['of']};"
            f" unverifiable quotes {numbers['quotes']['unverifiable']}"
        )

    lines = [line(case["case"], case["numbers"]) for case in result["cases"]]
    lines.append(line("pooled", result["pooled"]))
    lines += [
        f"void: {batch['case']} sample {batch['sample']}"
        for batch in result["void_batches"]
    ]
    return lines


def command_judge_replay(args: argparse.Namespace) -> int:
    """Build the judge's batches; send them only with consent."""
    instruction = INSTRUCTION.read_text(encoding="utf-8")
    try:
        if args.samples < 1:
            raise EvalRunError("--samples must be 1 or more")
        check_out(args.out)
        artifact = load_artifact(args.artifact)
        if artifact.mode != "analysis":
            raise EvalRunError(
                f"{artifact.path} is a {artifact.mode} sweep; a plant inverts the"
                " blessed model, which only an analysis sweep's reports carry"
            )
        judge = judge_selection(args.judge)
        deployment = Deployment.from_env()
        rng = random.SystemRandom()
        named = _cases(artifact, args.case)
        moved = moved_sources(artifact, named)
        inputs = [
            case_input(artifact, case, rng) for case in named if case not in moved
        ]
        requests = requests_for(inputs, args.samples, rng)
        report_paths: dict[Path, Selections] = {
            path: {}
            for held in inputs
            if (path := finished_file(artifact, held.case, "report")) is not None
        }
        record = run_record_for(
            [args.out],
            "judge-replay",
            {
                "samples": args.samples,
                "cases": [held.case for held in inputs],
                "dry_run": args.dry_run,
                "corpus_digest": corpus_digest(),
                "sweep_corpus_digest": artifact.corpus_digest,
            },
            {artifact.path: {}, INSTRUCTION: {}, **report_paths},
        )
    except (CorpusError, EvalRunError, ProvenanceError) as error:
        print(error, file=sys.stderr)
        return 1
    writers = writer_routes(artifact)
    breach = independence_breach(writers, judge.route)
    cost = consent.charged(
        estimate(instruction, requests, judge.route), [judge], deployment.tiers
    )
    for case in moved:
        print(f"{case}: left out; the sweep read other sources than the corpus holds")
    for held in inputs:
        sizes = Counter(item.population for item in held.items)
        print(
            f"{held.case}: {len(held.items)} findings a batch;"
            + "".join(
                f" {population} {sizes[population]}" for population in POPULATIONS
            )
        )
    print(
        f"judge {judge.route}; writers {', '.join(writers)};"
        f" independence {'refused: ' + breach if breach else 'distinct source vendors'}"
    )
    head = {
        "record": record,
        "instruction_sha256": text_digest(instruction),
        "judge": {"route": judge.route, "sampling": JUDGE_SAMPLING.model_dump()},
        "writers": list(writers),
        "independence_breach": breach,
        "moved_sources": moved,
        "estimate": {
            "label": cost.label,
            "amount_usd": cost.amount_usd,
            "lines": list(cost.lines),
        },
    }
    if args.dry_run:
        for line in estimate_lines(cost):
            print(line)
        written = head | {"dry_run": True, "cases": dry_cases(inputs, requests)}
        args.out.write_text(json.dumps(written, indent=2) + "\n", encoding="utf-8")
        return 0
    if breach is not None:
        print(
            f"refused: the judge must run a model from a source vendor other than"
            f" the source vendor of each model that wrote the sweep; {breach}."
            f" Name a model from another source vendor in --judge",
            file=sys.stderr,
        )
        return 1
    try:
        accepted = consent.gate(cost, args.accept_cost, None)
    except consent.Refused as refusal:
        print(refusal, file=sys.stderr)
        return 1
    spent: list[float | None] = []
    seen: list[dict[str, Any]] = []
    raws: list[str | None] = [None] * len(requests)

    call = selection_call(
        deployment,
        JUDGE_NODE,
        judge,
        JUDGE_SAMPLING,
        JUDGE_SAMPLING_SOURCE,
        JudgeAnswer,
        spent,
        seen,
    )
    # The sweep's own hold, between calls rather than between cases: it prices
    # the usage each call reported, and it asks again by typing, or stops where
    # --accept-cost leaves no hand to ask.
    ask = None if args.accept_cost is not None else input
    steps: list[list[NodeRun]] = []
    stopped: str | None = None
    # One event loop for every call, so each answer is written to the output
    # file here, as it arrives, before the next call runs.
    with asyncio.Runner() as runner:
        for index, request in enumerate(requests):
            remaining = [f"{r.case} sample {r.sample}" for r in requests[index:]]
            try:
                accepted = consent.hold(
                    accepted, steps, remaining, ask, ran=index, unit="call"
                )
            except consent.Refused as refusal:
                stopped = (
                    f"stopped before {request.case} sample {request.sample}: {refusal}"
                )
                break
            answered = len(seen)
            try:
                raws[index] = runner.run(_ask(call, instruction, request))
            except LiveInferenceRefused as refusal:
                stopped = str(refusal)
                break
            except Exception as error:  # noqa: BLE001 - keep the paid answers so far
                stopped = (
                    f"{request.case} sample {request.sample} failed:"
                    f" {type(error).__name__}: {error}"
                )
                break
            entry = seen[answered] if len(seen) > answered else None
            steps.append(
                [measured_run(entry, request_usage(instruction, request), judge.route)]
            )
            written = head | {"dry_run": False, "stopped": None, "answers": seen}
            written |= judged(inputs, requests, raws)
            args.out.write_text(json.dumps(written, indent=2) + "\n", encoding="utf-8")
    result = judged(inputs, requests, raws)
    written = head | {"dry_run": False, "stopped": stopped, "answers": seen, **result}
    args.out.write_text(json.dumps(written, indent=2) + "\n", encoding="utf-8")
    for line in summary_lines(result):
        print(line)
    print(spent_line(spent))
    if stopped is not None:
        print(f"stopped: {stopped}", file=sys.stderr)
        return 1
    return 0
