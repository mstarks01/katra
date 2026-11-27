"""Replay one lane agent over the material a sweep captured for it (#1091).

A ``place`` loss says a rule led a lane to a reference's elements and the lane
drafted nothing there. Whether the lane read its lead badly or the lead arrived
badly is a question about one lane's request, and a sweep answers it at the
price of every case and every node. This asks it at the price of one call: it
rebuilds the request the lane made from ``<case>.lanes.json`` and sends that
request again, or a changed one.

**The graph's readers, never a second copy.** The instruction is
:func:`~katra.graph.analyze_instruction`, and
:func:`~katra.node_requests.node_request` templates it over the
captured state keys and builds the user turn from ``prepare``'s captured
output, the way ADK does for the node. The answer parses under the package's own proposal schema.
``tests/test_evals_lane_replay.py`` holds the rebuilt request against the one a
real graph run sent.

**The prompt files are today's.** The captured material is the run's, and the
instruction around it is read from this checkout. The command prints both
commits, and a replay across a prompt change measures that change. The run
record names each prompt and package file the run loaded, with its digest, so
a record from a changed tree still shows the text the lane read.

**One extra user part, on request.** ``--append`` sends a file's text as a
second part of the user turn, after the captured input. ADR 0030's measurement
tries its instruction this way, so both of its arms read the same prompt files.

**Today's ``prepare``, on request.** ``--prepare-today`` builds the lane's whole
request from the case instead of from a sweep: the real ``prepare`` node runs
offline over the case's blessed model, with no catalog or with the case's
signed facts as the assertion proposal. The two arms differ only in that
catalog, so a pair of replays measures what ``KATRA_ASSERTIONS`` can give a
lane when its pass writes exactly the signed rows (#1231). The lane's drafts
are then scored by :func:`~evals.harness.descendants.lane_must_finds`, for the
package that scores drafts by an action and a place. ``--system-model`` puts a
System Model file in place of the blessed model: the same elements, other
attribute values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, get_args

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from evals.harness import consent
from evals.harness.artifact import (
    EvalArtifact,
    ProvenanceError,
    corpus_digest,
    load_artifact,
    repo_commit,
)
from evals.harness.bundle import check_out, finished_file
from evals.harness.descendants import FRAMEWORK as SCORED
from evals.harness.descendants import lane_must_finds
from evals.harness.modes import EvalRunError, case_framework_options
from evals.harness.node_call import (
    NodeCall,
    NodeRoute,
    measured_run,
    node_call,
    node_route,
    spent_line,
)
from evals.harness.prices import unit_prices
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import (
    DEFAULT_CORPUS,
    CorpusError,
    GoldenCase,
    load_case,
    load_model_file,
    refuse_holdout,
)
from evals.harness.run_record import Selections, loaded, run_record_for
from evals.reference_facts import load_facts, signed_proposal
from katra.claims import FrameworkName, ProposalBatch
from katra.deployment import Deployment
from katra.execution import GraphRun, seed_state
from katra.frameworks import PACKAGES, package_for, schemas_for
from katra.graph import (
    STATE_ASSERTION_PROPOSAL,
    STATE_EVIDENCE_CATALOG,
    STATE_FRAMEWORK_OPTIONS,
    STATE_SYSTEM_MODEL,
    STATE_VALID_MODEL,
    FrameworkNodes,
    GraphKeys,
    Lane,
    LaneArtifact,
    analyze_instruction,
    framework_lane_inputs,
    prepare_analysis,
    unfence,
)
from katra.markdown_loader import MarkdownLoader
from katra.node_requests import node_request
from katra.offline import LiveInferenceRefused
from katra.prompts import lane_closing
from katra.report import NodeRun
from katra.system_model import ELEMENT_GROUPS

#: What ``--prepare-today`` hands ``prepare`` as the catalog: none, which is a
#: job with ``KATRA_ASSERTIONS`` off, or the case's signed facts.
CatalogArm = Literal["none", "signed"]
CATALOG_ARMS: tuple[CatalogArm, ...] = get_args(CatalogArm)


def lane_of(framework: FrameworkName, name: str) -> Lane:
    """The lane ``name`` of ``framework``, or a refusal naming the real ones."""
    lanes = {lane.lane: lane for lane in FrameworkNodes(framework).lanes}
    if name not in lanes:
        raise EvalRunError(
            f"{framework} has no lane {name!r}; it has {', '.join(lanes)}"
        )
    return lanes[name]


def lanes_file(artifact: EvalArtifact, case_id: str) -> Path:
    """One case's ``<case>.lanes.json``, or a refusal saying why there is none.

    The file is found through :func:`~evals.harness.bundle.finished_file`, so
    a lost file of a finished case is refused by name. A failed case wrote no
    lane material, so it is refused too.
    """
    path = finished_file(artifact, case_id, "lanes")
    if path is None:
        raise EvalRunError(
            f"{case_id}: the artifact records the case as failed, so the sweep"
            " wrote no lane material for it"
        )
    return path


def material_at(path: Path) -> dict[str, Any]:
    """The lane material in one ``<case>.lanes.json``, or a refusal."""
    try:
        material = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise EvalRunError(f"{path} is not JSON: {error.msg}") from error
    if not isinstance(material, dict):
        raise EvalRunError(f"{path} holds no JSON object")
    if material.get("prepared") is None:
        raise EvalRunError(
            f"{path} carries no user turn; a lane's request without the input"
            " prepare handed it is not the request the lane made"
        )
    return material


def captured_lane(
    material: Mapping[str, Any], framework: FrameworkName, lane_name: str
) -> Mapping[LaneArtifact, str]:
    """One lane's captured artifacts in ``material``, keyed by placeholder, or a refusal.

    The one reader of a lane's artifacts in a lane capture.
    The capture holds each :data:`~katra.graph.LANE_ARTIFACTS` key
    and no other, as :meth:`~katra.graph.Lane.state` requires of
    what ``prepare`` writes, and each value is text.
    """
    lanes = material.get("lanes")
    framework_lanes = lanes.get(framework) if isinstance(lanes, Mapping) else None
    held = (
        framework_lanes.get(lane_name) if isinstance(framework_lanes, Mapping) else None
    )
    if not isinstance(held, Mapping):
        raise EvalRunError(f"the capture holds no {framework} lane {lane_name!r}")
    try:
        lane_of(framework, lane_name).state(held)
    except ValueError as error:
        raise EvalRunError(
            f"the {framework} lane {lane_name!r} capture is not a lane's state: {error}"
        ) from error
    unrendered = sorted(
        name for name, text in held.items() if not isinstance(text, str)
    )
    if unrendered:
        raise EvalRunError(
            f"the {framework} lane {lane_name!r} capture holds"
            f" {', '.join(unrendered)} as other than text"
        )
    artifacts: Mapping[LaneArtifact, str] = held
    return artifacts


@dataclass(frozen=True)
class SharedInput:
    """The shared keys a case's lanes were sent, as the sweep captured them."""

    #: Each element of the captured ``system_model``, by its ID, or ``None``
    #: where the key is refused.
    elements: Mapping[str, Mapping[str, Any]] | None
    #: The captured ``evidence_catalog`` table, or ``None`` where it is refused.
    evidence_catalog: str | None
    #: Why each refused key is refused, by its state key.
    refused: Mapping[str, str]


def captured_shared(material: Mapping[str, Any]) -> SharedInput:
    """The captured ``system_model`` and ``evidence_catalog`` of a case, each read apart.

    A key the capture lacks, or a model that is not a JSON object, is refused
    on its own, and the other key is still read.
    """
    shared = material.get("shared")
    held = shared if isinstance(shared, Mapping) else {}
    refused: dict[str, str] = {}
    texts: dict[str, str] = {}
    for key in (STATE_SYSTEM_MODEL, STATE_EVIDENCE_CATALOG):
        if isinstance(text := held.get(key), str):
            texts[key] = text
        else:
            refused[key] = f"the capture holds no shared {key} text"
    elements = None
    if STATE_SYSTEM_MODEL in texts:
        try:
            model = json.loads(unfence(texts[STATE_SYSTEM_MODEL]))
        except json.JSONDecodeError as error:
            model = None
            refused[STATE_SYSTEM_MODEL] = (
                f"the captured system model is not JSON: {error.msg}"
            )
        if isinstance(model, dict):
            elements = {
                element["id"]: element
                for group in ELEMENT_GROUPS
                if isinstance(collection := model.get(group), list)
                for element in collection
                if isinstance(element, dict) and isinstance(element.get("id"), str)
            }
        else:
            refused.setdefault(
                STATE_SYSTEM_MODEL, "the captured system model holds no JSON object"
            )
    return SharedInput(elements, texts.get(STATE_EVIDENCE_CATALOG), refused)


async def compose(
    material: dict[str, Any],
    framework: FrameworkName,
    lane_name: str,
    package_loader: MarkdownLoader,
    prompt_loader: MarkdownLoader,
) -> tuple[str, types.Content]:
    """The instruction and the user turn one lane was sent, rebuilt.

    The turn ends with the package's lane closing, as the graph's callback adds
    it, so ``--append`` comes after that.
    """
    lane = lane_of(framework, lane_name)
    state = {
        **material["shared"],
        **lane.state(captured_lane(material, framework, lane_name)),
    }
    template = analyze_instruction(
        package_loader, prompt_loader, package_for(framework), lane
    )
    return await node_request(
        template, state, material["prepared"], lane_closing(package_loader, framework)
    )


def fresh_leads(
    material: dict[str, Any],
    case: GoldenCase,
    framework: FrameworkName,
    lane_name: str,
    package_loader: MarkdownLoader,
) -> dict[str, Any]:
    """``material`` with one lane's leads, scope, notes and cases rebuilt today.

    The captured leads are the rules of the day the sweep ran. A replay that
    measures a rule change needs the lead the graph would send now, so this
    rebuilds the lane's four inputs from the case's blessed model through
    :func:`~katra.graph.framework_lane_inputs`, the function the
    prepare node calls. The shared inputs stay as captured. It reads the
    blessed model, so it is exact for an analysis-mode sweep, where the lanes
    read that model, with the assertion layer off.
    """
    nodes = FrameworkNodes(framework)
    inputs = framework_lane_inputs(
        nodes,
        case.model,
        case.declaration(framework).options,
        None,
        package_loader,
    )
    lanes = {**material["lanes"], framework: dict(material["lanes"][framework])}
    lanes[framework][lane_name] = dict(inputs.artifacts[lane_name])
    return {**material, "lanes": lanes}


@dataclass(frozen=True)
class PreparedToday:
    """What today's ``prepare`` wrote for one case: the lanes' material, the
    state, and each file its loaders held, for a run record."""

    material: dict[str, Any]
    state: dict[str, Any]
    inputs: dict[Path, Selections]


def prepare_today(
    case: GoldenCase, framework: FrameworkName, arm: str
) -> PreparedToday:
    """Every lane input today's ``prepare`` writes over the case's model: the
    blessed one, or the file that :func:`with_system_model` put in its place.

    The real node over a plain session, seeded by
    :func:`~katra.execution.seed_state` as a graph run is, with the
    case's options. On the ``signed`` arm the case's signed facts are the
    assertion proposal, and ``prepare`` resolves and gates them itself, as it
    does an ``assert`` node's. The material is read through
    :meth:`~katra.execution.GraphRun.lane_material`, the reader a
    sweep's lane capture uses.
    """
    if arm not in CATALOG_ARMS:
        raise EvalRunError(
            f"unknown catalog arm {arm!r}; use {', '.join(CATALOG_ARMS)}"
        )
    valid_model = case.model.model_dump(mode="json")
    extra: dict[str, Any] = {
        STATE_FRAMEWORK_OPTIONS: case_framework_options(case),
        STATE_VALID_MODEL: valid_model,
    }
    if arm == "signed":
        facts = load_facts(REPO_ROOT / DEFAULT_CORPUS / case.id)
        extra[STATE_ASSERTION_PROPOSAL] = signed_proposal(facts).model_dump(mode="json")
    ctx = SimpleNamespace(state=seed_state(case.sources, extra))
    domains = MarkdownLoader(REPO_ROOT / "domains")
    package = MarkdownLoader(REPO_ROOT / "frameworks" / framework)
    event = prepare_analysis(
        valid_model,
        ctx,
        GraphKeys.of([framework]),
        [framework],
        domains,
        {framework: package},
        assertions=arm == "signed",
    )
    run = GraphRun(final_state=ctx.state, node_runs=[], prepared=event.output)
    return PreparedToday(
        run.lane_material([framework]), ctx.state, loaded((domains, package))
    )


def with_system_model(case: GoldenCase, path: Path) -> GoldenCase:
    """``case`` with the System Model at ``path`` in place of its blessed one.

    The case's references and signed facts name the blessed model's elements,
    so the file holds the same element IDs. One that renames or drops an
    element is refused, because its references would read as missed. One that
    adds an element is refused too: no reference names it, so a draft on it
    reads as unlisted, and the replay measures a new system rather than the
    case with other attribute values.
    """
    try:
        model = load_model_file(path, archived=False)
    except CorpusError as error:
        raise EvalRunError(str(error)) from error
    built = {element.id for element in model.elements()}
    blessed = {element.id for element in case.model.elements()}
    if built != blessed:
        raise EvalRunError(
            f"{path}: the file must hold the blessed model's element IDs; it"
            f" drops {sorted(blessed - built)} and adds {sorted(built - blessed)}"
        )
    return replace(case, model=model)


def parse(raw: str, framework: FrameworkName) -> BaseModel:
    """The lane's answer under its package's own proposal schema, or a refusal."""
    return schemas_for(framework).proposals.model_validate_json(raw)


async def replay(
    material: dict[str, Any],
    framework: FrameworkName,
    lane_name: str,
    call: NodeCall,
    package_loader: MarkdownLoader,
    prompt_loader: MarkdownLoader,
    appended: str | None,
) -> BaseModel:
    """One lane's request sent again, with ``appended`` as a last user part."""
    instruction, turn = await compose(
        material, framework, lane_name, package_loader, prompt_loader
    )
    if appended is not None:
        turn.parts = [*(turn.parts or []), types.Part(text=appended)]
    return parse(await call(instruction, turn), framework)


class PlannedCall(BaseModel):
    """One line of a ``--plan`` file: one lane call on today's ``prepare``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case: str
    lane: str
    prepare_today: CatalogArm


def read_plan(path: Path) -> list[PlannedCall]:
    """Each call a ``--plan`` file names, one JSON object a line, or a refusal."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvalRunError(f"{path}: {error.strerror}") from error
    planned = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            planned.append(PlannedCall.model_validate_json(line))
        except ValidationError as error:
            raise EvalRunError(f"{path} line {number}: {error}") from error
    if not planned:
        raise EvalRunError(f"{path} names no call")
    return planned


@dataclass(frozen=True)
class LaneRequest:
    """One lane call, built offline before the gate: what it sends and where
    its answer goes."""

    name: str
    case: GoldenCase
    lane: Lane
    material: dict[str, Any]
    prepared: PreparedToday | None
    record: dict[str, Any] | None
    out: Path | None


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "artifact",
        type=Path,
        nargs="?",
        help="the sweep whose lane to replay; omit it with --prepare-today",
    )
    parser.add_argument("--case", help="the case the lane ran on")
    parser.add_argument("--lane", help="the lane, e.g. spoofing")
    parser.add_argument(
        "--framework", required=True, choices=sorted(PACKAGES), help="the package"
    )
    parser.add_argument(
        "--accept-cost",
        required=True,
        help="required: the dollars you accept as a cap on the calls, or"
        " 'unknown' to run with no cap on a route the hold cannot measure",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        help="a file of calls, one JSON object a line with case, lane and"
        " prepare_today, sent in order under one cap. It takes the place of"
        " --case, --lane and --prepare-today, and --out names a folder",
    )
    parser.add_argument(
        "--append",
        type=Path,
        help="a text file sent as one more user part, after the captured input",
    )
    parser.add_argument(
        "--fresh-leads",
        action="store_true",
        help="rebuild the lane's leads, scope, notes and cases with today's rules",
    )
    parser.add_argument(
        "--prepare-today",
        choices=CATALOG_ARMS,
        help="build the request with today's prepare over the case's blessed"
        " model, or --system-model, with no catalog or the case's signed facts,"
        " and score the drafts",
    )
    parser.add_argument(
        "--system-model",
        type=Path,
        help="with --prepare-today: a System Model file that replaces the case's"
        " blessed model. It passes the live validity gate and holds the blessed"
        " model's element IDs",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the run record, the call's route and usage, and the lane's"
        " proposals here; with --plan, a folder that gets one file a call",
    )


def _refuse_flags(args: argparse.Namespace) -> None:
    """Refuse a combination of flags that names no one request."""
    if args.plan is not None:
        given = [
            flag
            for flag, value in (
                ("an artifact", args.artifact),
                ("--case", args.case),
                ("--lane", args.lane),
                ("--prepare-today", args.prepare_today),
                ("--system-model", args.system_model),
                ("--append", args.append),
                ("--fresh-leads", args.fresh_leads or None),
            )
            if value is not None
        ]
        if given:
            raise EvalRunError(
                f"--plan names each call's case, lane and catalog arm, so it"
                f" takes no {', '.join(given)}"
            )
        if args.out is None or not args.out.is_dir():
            raise EvalRunError("--plan writes one file a call into the --out folder")
        return
    if args.case is None or args.lane is None:
        raise EvalRunError("name --case and --lane, or a --plan")
    if (args.artifact is None) == (args.prepare_today is None):
        raise EvalRunError("name a sweep artifact or --prepare-today, not both")
    if args.prepare_today is not None and (args.fresh_leads or args.append):
        raise EvalRunError(
            "--prepare-today builds the whole request, so it takes neither"
            " --fresh-leads nor --append"
        )
    if args.system_model is not None and args.prepare_today is None:
        raise EvalRunError("--system-model replaces the model --prepare-today reads")


def _one_request(
    args: argparse.Namespace,
    package_loader: MarkdownLoader,
    inputs: dict[Path, Selections],
) -> LaneRequest:
    """The one request the single-call flags name."""
    check_out(args.out)
    refuse_holdout(args.case)
    case = load_case(REPO_ROOT / DEFAULT_CORPUS / args.case)
    if args.system_model is not None:
        case = with_system_model(case, args.system_model)
        inputs[args.system_model] = {}
    prepared = None
    if args.prepare_today is not None:
        prepared = prepare_today(case, args.framework, args.prepare_today)
        material = prepared.material
        inputs |= prepared.inputs
        print(
            f"material from today's prepare, catalog {args.prepare_today};"
            f" prompt files from {repo_commit().commit}"
        )
    else:
        artifact = load_artifact(args.artifact)
        lanes = lanes_file(artifact, args.case)
        material = material_at(lanes)
        inputs |= {artifact.path: {}, lanes: {}}
        if args.fresh_leads:
            material = fresh_leads(
                material, case, args.framework, args.lane, package_loader
            )
        print(
            f"material from {artifact.commit.commit}; prompt files"
            f" from {repo_commit().commit}"
        )
    if args.append is not None:
        inputs[args.append] = {}
    record = run_record_for(
        [args.out],
        "lane-replay",
        {
            "case": args.case,
            "lane": args.lane,
            "framework": args.framework,
            "fresh_leads": args.fresh_leads,
            "prepare_today": args.prepare_today,
            "system_model": (
                None if args.system_model is None else str(args.system_model)
            ),
            "corpus_digest": corpus_digest(),
        },
        inputs,
    )
    return LaneRequest(
        f"{args.case} {args.lane}",
        case,
        lane_of(args.framework, args.lane),
        material,
        prepared,
        record,
        args.out,
    )


def _planned_requests(
    args: argparse.Namespace, inputs: dict[Path, Selections]
) -> list[LaneRequest]:
    """Each request a ``--plan`` file names, built offline, in its order."""
    planned = read_plan(args.plan)
    digest = corpus_digest()
    prepared: dict[tuple[str, str], PreparedToday] = {}
    requests = []
    for index, call in enumerate(planned, start=1):
        refuse_holdout(call.case)
        case = load_case(REPO_ROOT / DEFAULT_CORPUS / call.case)
        key = (call.case, call.prepare_today)
        if key not in prepared:
            prepared[key] = prepare_today(case, args.framework, call.prepare_today)
        today = prepared[key]
        name = f"{index:03d}-{call.case}-{call.lane}-{call.prepare_today}"
        out = args.out / f"{name}.json"
        if out.exists():
            raise EvalRunError(f"{out}: an earlier run wrote it")
        record = run_record_for(
            [out],
            "lane-replay",
            {
                "case": call.case,
                "lane": call.lane,
                "framework": args.framework,
                "fresh_leads": False,
                "prepare_today": call.prepare_today,
                "system_model": None,
                "corpus_digest": digest,
                "plan": str(args.plan),
                "plan_line": index,
            },
            inputs | today.inputs | {args.plan: {}},
        )
        requests.append(
            LaneRequest(
                name,
                case,
                lane_of(args.framework, call.lane),
                today.material,
                today,
                record,
                out,
            )
        )
    print(
        f"{len(requests)} calls from {args.plan} on today's prepare; prompt files"
        f" from {repo_commit().commit}"
    )
    return requests


def _unmeasured(steps: list[list[NodeRun]]) -> str | None:
    """Why the spend so far is not known, or ``None``: a call on a priced
    route that reported no token usage, which the hold would count at nothing."""
    for step in steps:
        for run in step:
            priced = run.model is not None and unit_prices(run.model) is not None
            if priced and run.usage is None:
                return (
                    f"a call on {run.model} reported no token usage, so the"
                    " spend so far is not known"
                )
    return None


def command_lane_replay(args: argparse.Namespace) -> int:
    """Send lane requests again under one cap, and print what each lane proposed."""
    package_loader = MarkdownLoader(REPO_ROOT / "frameworks" / args.framework)
    prompt_loader = MarkdownLoader(REPO_ROOT / "prompts")
    inputs = loaded((package_loader, prompt_loader))
    try:
        _refuse_flags(args)
        requests = (
            [_one_request(args, package_loader, inputs)]
            if args.plan is None
            else _planned_requests(args, inputs)
        )
        deployment = Deployment.from_env()
        routes = {
            request.lane.node_name: node_route(deployment, request.lane.node_name)
            for request in requests
        }
        cost = consent.replay_estimate(
            [route.selection for route in routes.values()], deployment.tiers
        )
        accepted = consent.gate(cost, args.accept_cost, None)
    except (CorpusError, EvalRunError, ProvenanceError) as error:
        print(error, file=sys.stderr)
        return 1
    except consent.Refused as refusal:
        print(refusal, file=sys.stderr)
        return 1
    appended = args.append.read_text(encoding="utf-8") if args.append else None
    schema = schemas_for(args.framework).proposals
    spent: list[float | None] = []
    steps: list[list[NodeRun]] = []
    stopped: str | None = None
    with asyncio.Runner() as runner:
        for index, request in enumerate(requests):
            remaining = [later.name for later in requests[index:]]
            try:
                if (unknown := _unmeasured(steps)) is not None:
                    raise consent.Refused(f"stopping: {unknown}")
                accepted = consent.hold(
                    accepted, steps, remaining, None, ran=index, unit="call"
                )
            except consent.Refused as refusal:
                stopped = f"stopped before {request.name}: {refusal}"
                break
            route = routes[request.lane.node_name]
            seen: list[dict[str, Any]] = []
            call = node_call(deployment, request.lane.node_name, schema, spent, seen)
            batch, schema_error = None, None
            try:
                batch = runner.run(
                    replay(
                        request.material,
                        args.framework,
                        request.lane.lane,
                        call,
                        package_loader,
                        prompt_loader,
                        appended,
                    )
                )
            except ValidationError as error:
                schema_error = str(error)
            except LiveInferenceRefused as refusal:
                stopped = str(refusal)
                break
            except Exception as error:  # noqa: BLE001 - keep the paid answers so far
                stopped = f"{request.name} failed: {type(error).__name__}: {error}"
                break
            entry = seen[0] if seen else None
            steps.append(
                [
                    measured_run(
                        entry, None, route.selection.route, request.lane.node_name
                    )
                ]
            )
            _report(args.framework, request, route, entry, batch, schema_error)
    print(spent_line(spent))
    if stopped is not None:
        print(f"stopped: {stopped}", file=sys.stderr)
        return 1
    return 0


def _report(
    framework: FrameworkName,
    request: LaneRequest,
    route: NodeRoute,
    entry: Mapping[str, Any] | None,
    batch: BaseModel | None,
    schema_error: str | None,
) -> None:
    """Print one call's drafts and write its output file."""
    print(f"{request.name}:")
    if batch is None:
        print(f"the answer was not read: {schema_error}")
        dumped: dict[str, Any] = {"schema_error": schema_error}
    else:
        dumped = batch.model_dump(mode="json")
        for claim in dumped["claims"]:
            print(f"- {claim.get('title')} | {claim.get('affected_element_ids')}")
    if request.out is not None:
        written = {
            "record": request.record,
            "call": {**route.record(), "answer": entry},
            **dumped,
        }
        request.out.write_text(json.dumps(written, indent=2) + "\n", encoding="utf-8")
    if batch is not None and request.prepared is not None and framework == SCORED:
        assert isinstance(batch, ProposalBatch)
        matched = lane_must_finds(
            request.case, request.prepared.state, request.lane.lane, batch
        )
        print(f"must-finds matched: {list(matched)}")
