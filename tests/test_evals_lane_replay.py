"""The lane replay rebuilds the request a lane made, and nothing else.

The one claim worth testing is fidelity: the instruction and the user turn the
replay composes from ``<case>.lanes.json`` are the ones the lane agent sent in
a real graph run. So a scripted sweep records every request the lanes make,
and the replay is held against those, byte for byte. Everything else here is a
refusal that keeps a replay from sending a request the lane never made.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.harness import lane_replay
from evals.harness.bundle import case_file, reports_dir, write_reports
from evals.harness.descendants import lane_must_finds
from evals.harness.identity import CaseFlows, SubsetVerbIdentity
from evals.harness.ledger import Ledger
from evals.harness.modes import EvalRunError
from evals.harness.node_call import NodeRoute
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS
from evals.harness.run_record import loaded
from evals.harness.scorer import score_case
from evals.reference_facts import load_facts
from katra.frameworks import LANE_CLOSING_DOC, PACKAGES
from katra.frameworks.stride.record import (
    ArchivedThreatProposals,
    DraftThreat,
)
from katra.graph import FrameworkNodes
from katra.markdown_loader import MarkdownLoader
from katra.model_tiers import ChargeMode, TierSelection
from katra.offline import LiveInferenceRefused
from katra.prompts import lane_closing
from katra.report import TokenUsage
from katra.sampling import TierSampling
from katra.system_model import ModelIndex
from tests import test_evals_run_grounds as grounds
from tests.eval_factories import PRICED_ROUTE, stub_route, write_emission_sweep
from tests.test_evals_run_grounds import case  # noqa: F401  (fixture)

PACKAGE_LOADER = MarkdownLoader(REPO_ROOT / "frameworks" / "stride")
PROMPT_LOADER = MarkdownLoader(REPO_ROOT / "prompts")


def finished(out, case_id):
    """The artifact of a sweep whose one case finished."""
    return write_emission_sweep(out, "analysis", [case_id])


def load_material(artifact, case_id):
    """One case's captured lane material, as the command reads it."""
    return lane_replay.material_at(lane_replay.lanes_file(artifact, case_id))


def replay_args(**given) -> argparse.Namespace:
    """The namespace the command's parser gives, with ``given`` in place of
    its defaults. ``case`` has no default, so each caller names one."""
    parser = argparse.ArgumentParser()
    lane_replay.arguments(parser)
    defaults = parser.parse_args(
        [
            "--case",
            "-",
            "--lane",
            "spoofing",
            "--framework",
            "stride",
            "--accept-cost",
            "unknown",
        ]
    )
    return argparse.Namespace(**{**vars(defaults), **given})


def _no_call(*args, **kwargs):
    raise AssertionError("the command reached the paid call")


def record_requests(monkeypatch) -> list[tuple[str, list]]:
    """Every request the scripted model is sent from now on, as it was sent."""
    seen: list[tuple[str, list]] = []
    real = grounds.QueuedLlm.generate_content_async

    async def recording(self, llm_request, stream=False):
        seen.append(
            (llm_request.config.system_instruction or "", list(llm_request.contents))
        )
        async for response in real(self, llm_request, stream):
            yield response

    monkeypatch.setattr(grounds.QueuedLlm, "generate_content_async", recording)
    return seen


@pytest.fixture
def recorded(monkeypatch, case, tmp_path):  # noqa: F811
    """A scripted sweep's reports, and every request its model was sent."""
    seen = record_requests(monkeypatch)
    run = grounds.sweep(monkeypatch, case, None)
    out = tmp_path / "artifact.json"
    write_reports(str(out), "analysis", run.runs)
    return out, seen


def test_every_lane_request_is_rebuilt_byte_for_byte(recorded, case):  # noqa: F811
    out, seen = recorded
    material = load_material(finished(out, case.id), case.id)
    sent = {instruction: contents for instruction, contents in seen}

    for lane in FrameworkNodes("stride").lanes:
        instruction, turn = asyncio.run(
            lane_replay.compose(
                material, "stride", lane.lane, PACKAGE_LOADER, PROMPT_LOADER
            )
        )
        assert instruction in sent, f"{lane.lane}: no lane sent this instruction"
        assert sent[instruction] == [turn], f"{lane.lane}: another user turn"


def test_a_replay_parses_the_answer_under_the_package_schema(recorded, case):  # noqa: F811
    out, _ = recorded
    material = load_material(finished(out, case.id), case.id)
    asked: list[str] = []

    async def call(instruction, turn):
        asked.append(instruction)
        return json.dumps({"claims": []})

    batch = asyncio.run(
        lane_replay.replay(
            material,
            "stride",
            "spoofing",
            call,
            PACKAGE_LOADER,
            PROMPT_LOADER,
            appended=None,
        )
    )

    assert batch.model_dump()["claims"] == []
    assert len(asked) == 1, "one lane, one call"


def test_an_appended_part_follows_the_captured_turn(recorded, case):  # noqa: F811
    out, _ = recorded
    material = load_material(finished(out, case.id), case.id)
    _, captured = asyncio.run(
        lane_replay.compose(
            material, "stride", "spoofing", PACKAGE_LOADER, PROMPT_LOADER
        )
    )
    sent: list = []

    async def call(instruction, turn):
        sent.append(turn)
        return json.dumps({"claims": []})

    asyncio.run(
        lane_replay.replay(
            material,
            "stride",
            "spoofing",
            call,
            PACKAGE_LOADER,
            PROMPT_LOADER,
            "Address every lead.",
        )
    )

    assert sent[0].parts[:-1] == captured.parts
    assert sent[0].parts[-1].text == "Address every lead."


def test_an_answer_outside_the_schema_is_refused(recorded, case):  # noqa: F811
    out, _ = recorded
    material = load_material(finished(out, case.id), case.id)

    async def call(instruction, turn):
        return json.dumps({"threats": []})

    with pytest.raises(ValueError):
        asyncio.run(
            lane_replay.replay(
                material,
                "stride",
                "spoofing",
                call,
                PACKAGE_LOADER,
                PROMPT_LOADER,
                appended=None,
            )
        )


def test_a_finished_case_with_a_lost_lanes_file_is_refused(recorded, case):  # noqa: F811
    out, _ = recorded
    case_file(out, case.id, "lanes").unlink()

    with pytest.raises(EvalRunError, match="holds no lanes file"):
        load_material(finished(out, case.id), case.id)


def test_a_failed_case_is_refused_and_its_stale_file_is_not_read(recorded, case):  # noqa: F811
    """A lanes file beside a failed case is an earlier sweep's, never this one's."""
    out, _ = recorded
    failed = write_emission_sweep(out, "analysis", [case.id], failed=[case.id])

    with pytest.raises(EvalRunError, match="an earlier sweep wrote it"):
        load_material(failed, case.id)
    case_file(out, case.id, "lanes").unlink()
    with pytest.raises(EvalRunError, match="wrote no lane material"):
        load_material(failed, case.id)


def test_a_case_the_artifact_does_not_list_is_refused(recorded, case):  # noqa: F811
    out, _ = recorded

    with pytest.raises(EvalRunError, match="does not list the case"):
        load_material(finished(out, "02-other"), case.id)


def test_the_command_refuses_a_failed_case_before_the_call(
    recorded,
    case,  # noqa: F811
    monkeypatch,
    capsys,
):
    out, _ = recorded
    write_emission_sweep(out, "analysis", [case.id], failed=[case.id])

    monkeypatch.setattr(lane_replay, "node_call", _no_call)
    args = replay_args(artifact=out, case=case.id)

    assert lane_replay.command_lane_replay(args) == 1
    assert "an earlier sweep wrote it" in capsys.readouterr().err


def test_the_out_file_starts_with_the_record_of_the_lane_material(
    recorded,
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    """A replay's proposals name the sweep files they were rebuilt from (#2029),
    and each prompt and package file the lane's request was built from."""
    out, _ = recorded
    finished(out, case.id)

    def scripted(*_):
        async def call(instruction, turn):
            return json.dumps({"claims": []})

        return call

    monkeypatch.setattr(lane_replay, "node_call", scripted)
    stub_route(monkeypatch, lane_replay)
    written = tmp_path / "proposals.json"
    args = replay_args(artifact=out, case=case.id, out=written)

    assert lane_replay.command_lane_replay(args) == 0

    held = json.loads(written.read_text(encoding="utf-8"))
    assert next(iter(held)) == "record"
    assert held["claims"] == []
    assert held["call"]["route"] == PRICED_ROUTE.selection.route
    assert held["call"]["binding"] == PRICED_ROUTE.binding
    assert held["record"]["table"]["lane"] == "spoofing"
    digests = {one["path"]: one["sha256"] for one in held["record"]["inputs"]}
    files = [
        loader.root / f"{name}.md"
        for loader in (PACKAGE_LOADER, PROMPT_LOADER)
        for name in loader.names()
    ]
    assert digests.keys() == {
        str(out),
        str(case_file(out, case.id, "lanes")),
        *map(str, files),
    }
    assert all(
        digests[str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    )


def test_a_replay_of_todays_prepare_names_each_file_it_loaded(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    """With no sweep, the record names each prompt, package and Domain Pack file
    the lane's request was built from, with its digest."""

    def scripted(*_):
        async def call(instruction, turn):
            return json.dumps({"claims": []})

        return call

    monkeypatch.setattr(lane_replay, "node_call", scripted)
    stub_route(monkeypatch, lane_replay)
    written = tmp_path / "proposals.json"
    args = replay_args(case=case.id, prepare_today="none", out=written)

    assert lane_replay.command_lane_replay(args) == 0

    held = json.loads(written.read_text(encoding="utf-8"))
    digests = {one["path"]: one["sha256"] for one in held["record"]["inputs"]}
    domains = MarkdownLoader(REPO_ROOT / "domains")
    named = loaded((PACKAGE_LOADER, PROMPT_LOADER, domains))
    assert digests.keys() == set(map(str, named))
    assert all(
        digests[str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()
        for path in named
    )


def test_a_system_model_file_replaces_the_blessed_model(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    """The lane reads the System Model file, and the record names it."""
    built = case.model.model_copy(deep=True)
    built.processes[0].notes = "a model in place of the blessed one"
    path = tmp_path / "model.json"
    path.write_text(built.model_dump_json(), encoding="utf-8")
    instructions: list[str] = []

    def scripted(*_):
        async def call(instruction, turn):
            instructions.append(instruction)
            return json.dumps({"claims": []})

        return call

    monkeypatch.setattr(lane_replay, "node_call", scripted)
    stub_route(monkeypatch, lane_replay)
    written = tmp_path / "proposals.json"

    assert (
        lane_replay.command_lane_replay(
            replay_args(
                case=case.id, prepare_today="none", system_model=path, out=written
            )
        )
        == 0
    )

    (instruction,) = instructions
    assert "a model in place of the blessed one" in instruction
    held = json.loads(written.read_text(encoding="utf-8"))
    assert held["record"]["table"]["system_model"] == str(path)
    digests = {one["path"]: one["sha256"] for one in held["record"]["inputs"]}
    assert digests[str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_model_the_gate_refuses_is_refused_before_the_call(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    built = case.model.model_dump(mode="json")
    built["data_flows"][0]["source"] = "process:nowhere"
    path = tmp_path / "model.json"
    path.write_text(json.dumps(built), encoding="utf-8")
    monkeypatch.setattr(lane_replay, "node_call", _no_call)

    assert (
        lane_replay.command_lane_replay(
            replay_args(case=case.id, prepare_today="none", system_model=path)
        )
        == 1
    )
    assert f"{path} is not valid" in capsys.readouterr().err


def test_a_system_model_file_reads_through_the_live_gate(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """A control written as a string reads in the archived corpus, and the
    live gate that a ``--system-model`` file passes refuses it."""
    built = case.model.model_dump(mode="json")
    built["data_stores"][0]["encryption_at_rest"] = "none"
    path = tmp_path / "model.json"
    path.write_text(json.dumps(built), encoding="utf-8")
    monkeypatch.setattr(lane_replay, "node_call", _no_call)

    assert (
        lane_replay.command_lane_replay(
            replay_args(case=case.id, prepare_today="none", system_model=path)
        )
        == 1
    )
    assert f"{path} is not valid" in capsys.readouterr().err


def test_a_system_model_file_without_an_element_is_refused_before_the_call(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """A dropped element would read the case's references on it as missed."""
    built = case.model.model_dump(mode="json")
    store = built["data_stores"].pop()
    built["data_flows"] = [
        flow
        for flow in built["data_flows"]
        if store["id"] not in (flow["source"], flow["destination"])
    ]
    flows = {flow["id"] for flow in built["data_flows"]}
    built["assumptions"] = [
        one
        for one in built["assumptions"]
        if one["element_id"] != store["id"]
        and (one["element_id"] in flows or not one["element_id"].startswith("flow:"))
    ]
    path = tmp_path / "model.json"
    path.write_text(json.dumps(built), encoding="utf-8")
    monkeypatch.setattr(lane_replay, "node_call", _no_call)

    assert (
        lane_replay.command_lane_replay(
            replay_args(case=case.id, prepare_today="none", system_model=path)
        )
        == 1
    )
    assert "must hold the blessed model's element IDs" in capsys.readouterr().err


def test_a_system_model_file_with_an_added_element_is_refused_before_the_call(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """An added element is one no reference names."""
    built = case.model.model_dump(mode="json")
    extra = {**built["external_entities"][0], "name": "auditor"}
    extra["id"] = "entity:auditor"
    built["external_entities"].append(extra)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(built), encoding="utf-8")
    monkeypatch.setattr(lane_replay, "node_call", _no_call)

    assert (
        lane_replay.command_lane_replay(
            replay_args(case=case.id, prepare_today="none", system_model=path)
        )
        == 1
    )
    assert "adds ['entity:auditor']" in capsys.readouterr().err


def test_a_system_model_without_prepare_today_is_refused_before_the_call(
    recorded,
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    out, _ = recorded
    finished(out, case.id)
    monkeypatch.setattr(lane_replay, "node_call", _no_call)
    args = replay_args(case=case.id, artifact=out, system_model=tmp_path / "model.json")

    assert lane_replay.command_lane_replay(args) == 1
    assert "--system-model replaces" in capsys.readouterr().err


def test_material_without_the_user_turn_is_refused(tmp_path):
    out = tmp_path / "artifact.json"
    reports_dir(out).mkdir()
    case_file(out, "01-payments-checkout", "lanes").write_text(
        json.dumps({"prepared": None, "shared": {}, "lanes": {}})
    )

    with pytest.raises(EvalRunError, match="no user turn"):
        load_material(finished(out, "01-payments-checkout"), "01-payments-checkout")


def test_a_lane_the_package_does_not_have_is_refused_with_the_real_ones():
    with pytest.raises(EvalRunError, match="spoofing"):
        lane_replay.lane_of("stride", "phishing")


def test_the_fidelity_check_fails_on_material_the_lane_never_had(recorded, case):  # noqa: F811
    """The positive check for the byte-for-byte test.

    A changed lead is a new request.
    """
    out, seen = recorded
    material = load_material(finished(out, case.id), case.id)
    material["lanes"]["stride"]["spoofing"]["candidates"] = "a lead nobody wrote"

    instruction, _ = asyncio.run(
        lane_replay.compose(
            material, "stride", "spoofing", PACKAGE_LOADER, PROMPT_LOADER
        )
    )

    assert instruction not in {sent for sent, _ in seen}


def test_a_thought_part_is_not_part_of_the_answer():
    """ADK leaves thoughts out of a node's output, so a replay must too."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    from evals.harness.node_call import answer_text

    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text="**Assessing security properties**", thought=True),
                types.Part(text='{"claims": []}'),
            ],
        )
    )

    assert answer_text(response) == '{"claims": []}'


def test_a_stride_lane_reads_its_closing_last(recorded):
    """ADR 0030's instruction is the last part of every STRIDE lane's user turn."""
    _, seen = recorded
    closing = lane_closing(PACKAGE_LOADER, "stride")
    lane_turns = [contents[-1] for _, contents in seen]
    stride_lanes = [turn for turn in lane_turns if turn.parts[-1].text == closing]

    # Two cases, six lanes each; the critic's request carries no closing.
    assert closing
    assert len(stride_lanes) == 2 * len(FrameworkNodes("stride").lanes)
    assert len(stride_lanes) < len(seen)


def test_the_closing_table_answers_for_every_package():
    assert set(LANE_CLOSING_DOC) == set(PACKAGES)


def test_fresh_leads_on_todays_run_are_the_leads_it_captured(recorded, case):  # noqa: F811
    """One reader: rebuilt with today's code, every lane's inputs are the captured ones."""
    out, _ = recorded
    material = load_material(finished(out, case.id), case.id)

    for lane in FrameworkNodes("stride").lanes:
        rebuilt = lane_replay.fresh_leads(
            material, case, "stride", lane.lane, PACKAGE_LOADER
        )
        assert rebuilt["lanes"] == material["lanes"], lane.lane


def test_a_node_call_keeps_what_the_provider_returned(monkeypatch):
    """A replay that parses to nothing can be read without a second paid call
    (#1555): the call keeps the answer text, why the provider stopped and the
    tokens it counted."""
    from types import SimpleNamespace

    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    from evals.harness import node_call as module
    from katra.report import TokenUsage

    class Adapter:
        model = "stub"

        async def generate_content_async(self, request, stream):
            yield LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part(text='{"claims": []}')]
                ),
                finish_reason=types.FinishReason.STOP,
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    candidates_token_count=7, thoughts_token_count=11
                ),
            )

    monkeypatch.setattr(
        module, "build_tier_adapters", lambda *a, **k: {"strong": Adapter()}
    )
    deployment = SimpleNamespace(
        binding_of=lambda node: "strong",
        tiers=SimpleNamespace(bound_tiers=frozenset({"strong"})),
        resilience=None,
        env={},
        sampling=SimpleNamespace(
            for_binding=lambda binding: SimpleNamespace(
                to_generate_content_config=types.GenerateContentConfig
            )
        ),
    )
    seen: list = []
    call = module.node_call(deployment, "critic", None, [], seen)
    text = asyncio.run(call("instruction", types.Content(role="user", parts=[])))

    assert text == '{"claims": []}'
    assert seen == [
        {
            "text": '{"claims": []}',
            "responses": [
                {
                    "finish_reason": "FinishReason.STOP",
                    "error_message": None,
                    "output_tokens": 7,
                    "thought_tokens": 11,
                }
            ],
            "usage": TokenUsage(completion_tokens=7, reasoning_tokens=11).model_dump(),
            "attempts": 1,
            "reasks": 0,
            "reported_charge_usd": None,
        }
    ]


def test_todays_prepare_without_a_catalog_is_what_a_run_captured(recorded, case):  # noqa: F811
    """One reader: the offline ``prepare`` writes the material a graph run captures."""
    out, _ = recorded

    prepared = lane_replay.prepare_today(case, "stride", "none")

    assert prepared.material == load_material(finished(out, case.id), case.id)


def test_the_signed_arm_changes_only_what_the_catalog_reaches(case):  # noqa: F811
    off = lane_replay.prepare_today(case, "stride", "none").material
    on = lane_replay.prepare_today(case, "stride", "signed").material
    facts = load_facts(REPO_ROOT / DEFAULT_CORPUS / case.id)

    assert on["shared"]["input_text"] == off["shared"]["input_text"]
    assert on["shared"]["evidence_catalog"] != off["shared"]["evidence_catalog"]
    assert off["prepared"]["assertion_count"] is None
    assert on["prepared"]["assertion_count"] == len(facts.rows)
    assert on["prepared"]["assertions_refused"] == 0


def test_an_unknown_catalog_arm_is_refused_with_the_real_ones(case):  # noqa: F811
    with pytest.raises(EvalRunError, match="none, signed"):
        lane_replay.prepare_today(case, "stride", "archived")


def test_each_lane_scores_the_must_finds_the_run_drafts_match(recorded, case):  # noqa: F811
    """Scored one lane at a time, the lanes match what the run's drafts match."""
    out, _ = recorded
    directory = reports_dir(out)
    proposals = json.loads((directory / f"{case.id}.proposals.json").read_text())
    drafts = json.loads((directory / f"{case.id}.drafts.json").read_text())["stride"]
    prepared = lane_replay.prepare_today(case, "stride", "none")
    references = case.stride_claims()
    flows = CaseFlows.of_graph(ModelIndex.of(case.model).flow_endpoints)

    by_lane = {
        index
        for lane, batch in proposals["stride"].items()
        for index in lane_must_finds(
            case, prepared.state, lane, ArchivedThreatProposals.model_validate(batch)
        )
    }
    whole = {
        pair.reference_index
        for pair in score_case(
            case,
            [DraftThreat.model_validate(draft) for draft in drafts],
            SubsetVerbIdentity({case.id: flows}),
            Ledger(),
        ).matched
        if references[pair.reference_index].must_find
    }

    assert whole, "the scripted run matches no must-find, so this compares nothing"
    assert by_lane == whole


@pytest.mark.parametrize(
    "given",
    [
        {"artifact": None, "prepare_today": None},
        {"artifact": Path("a.json"), "prepare_today": "none"},
        {"artifact": None, "prepare_today": "signed", "fresh_leads": True},
    ],
    ids=["neither", "both", "fresh-leads"],
)
def test_a_request_with_two_sources_or_none_is_refused_before_a_call(given, capsys):
    args = replay_args(case="01-payments-checkout", accept_cost="0", **given)

    assert lane_replay.command_lane_replay(args) == 1
    assert "--prepare-today" in capsys.readouterr().err


def _usage_calls(usage, sent, charge=None, answers=None):
    """A ``node_call`` whose every call reports ``usage`` and ``charge``. Each
    answer is the next of ``answers``: a text, or an exception to raise. With
    no ``answers`` every call drafts nothing."""

    def make(deployment, graph_node, schema, spent, seen):
        async def call(instruction, turn):
            sent.append(graph_node)
            answer = answers.pop(0) if answers else json.dumps({"claims": []})
            if isinstance(answer, Exception):
                raise answer
            spent.append(charge)
            seen.append(
                {
                    "text": answer,
                    "responses": [],
                    "usage": usage,
                    "attempts": 1,
                    "reasks": 0,
                    "reported_charge_usd": charge,
                }
            )
            return answer

        return call

    return make


def _plan(tmp_path, case_id, lanes):
    path = tmp_path / "plan.jsonl"
    path.write_text(
        "".join(
            json.dumps({"case": case_id, "lane": lane, "prepare_today": "none"}) + "\n"
            for lane in lanes
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    out.mkdir()
    return path, out


#: Ten thousand tokens each way: $0.12 a call on the priced stub route.
TEN_THOUSAND = TokenUsage(
    prompt_tokens=10_000, completion_tokens=10_000, total_tokens=20_000
).model_dump()


def test_a_word_that_is_not_an_amount_is_refused_before_the_call(
    case,  # noqa: F811
    monkeypatch,
    capsys,
):
    """#2400: the command reads --accept-cost and refuses a word that is not money."""
    monkeypatch.setattr(lane_replay, "node_call", _no_call)
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=case.id, prepare_today="none", accept_cost="banana")

    assert lane_replay.command_lane_replay(args) == 1
    assert "neither a number of dollars" in capsys.readouterr().err


def test_a_plan_stops_before_the_call_the_cap_refuses_and_keeps_the_answers(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """#2400: the hold prices each call's token usage on a priced route, and
    each call's file records its route, sampling and usage."""
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering", "repudiation"])
    sent: list[str] = []
    monkeypatch.setattr(lane_replay, "node_call", _usage_calls(TEN_THOUSAND, sent))
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="0.30")

    assert lane_replay.command_lane_replay(args) == 1

    assert len(sent) == 2
    assert "stopped before 003-" in capsys.readouterr().err
    first = out / f"001-{case.id}-spoofing-none.json"
    assert first.exists()
    assert (out / f"002-{case.id}-tampering-none.json").exists()
    assert not (out / f"003-{case.id}-repudiation-none.json").exists()
    held = json.loads(first.read_text(encoding="utf-8"))
    assert held["call"]["route"] == PRICED_ROUTE.selection.route
    assert held["call"]["sampling"] == PRICED_ROUTE.sampling.model_dump(mode="json")
    assert held["call"]["answer"]["usage"] == TEN_THOUSAND
    assert held["record"]["table"]["plan_line"] == 1


def test_a_plan_inside_the_cap_runs_every_call(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering", "repudiation"])
    sent: list[str] = []
    monkeypatch.setattr(lane_replay, "node_call", _usage_calls(TEN_THOUSAND, sent))
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="0.40")

    assert lane_replay.command_lane_replay(args) == 0
    assert len(sent) == 3


def test_a_call_with_no_usage_on_a_priced_route_stops_the_next_call(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """The hold would count such a call at nothing, so the spend is not known."""
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering"])
    sent: list[str] = []
    monkeypatch.setattr(lane_replay, "node_call", _usage_calls(None, sent))
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="5")

    assert lane_replay.command_lane_replay(args) == 1
    assert len(sent) == 1
    assert "reported no token usage" in capsys.readouterr().err


@pytest.mark.parametrize(
    "given",
    [{"case": "01-payments-checkout"}, {"prepare_today": "none"}, {"out": None}],
    ids=["case", "arm", "no-folder"],
)
def test_a_plan_with_a_single_call_flag_or_no_folder_is_refused(
    given, tmp_path, monkeypatch, capsys
):
    plan, out = _plan(tmp_path, "01-payments-checkout", ["spoofing"])
    monkeypatch.setattr(lane_replay, "node_call", _no_call)
    args = replay_args(
        **{"case": None, "lane": None, "plan": plan, "out": out, **given}
    )

    assert lane_replay.command_lane_replay(args) == 1
    assert "--plan" in capsys.readouterr().err


def test_a_plan_line_outside_the_schema_is_refused_by_its_number(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(
        '{"case": "c", "lane": "spoofing", "prepare_today": "none"}\n'
        '{"case": "c", "lane": "spoofing", "prepare_today": "all"}\n',
        encoding="utf-8",
    )

    with pytest.raises(EvalRunError, match="line 2"):
        lane_replay.read_plan(path)


def test_a_failed_call_keeps_the_files_before_it_and_exits_one(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """#2400: a refused or failed call stops the plan, and the paid answers stay."""
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering", "repudiation"])
    sent: list[str] = []
    answers = [json.dumps({"claims": []}), LiveInferenceRefused("offline")]
    monkeypatch.setattr(
        lane_replay, "node_call", _usage_calls(TEN_THOUSAND, sent, answers=answers)
    )
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="5")

    assert lane_replay.command_lane_replay(args) == 1
    assert len(sent) == 2
    assert "offline" in capsys.readouterr().err
    assert (out / f"001-{case.id}-spoofing-none.json").exists()
    assert not (out / f"002-{case.id}-tampering-none.json").exists()


def test_an_answer_outside_the_schema_is_written_and_exits_one(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering"])
    sent: list[str] = []
    answers = ['{"claims": "no"}', json.dumps({"claims": []})]
    monkeypatch.setattr(
        lane_replay, "node_call", _usage_calls(TEN_THOUSAND, sent, answers=answers)
    )
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="5")

    assert lane_replay.command_lane_replay(args) == 1
    assert len(sent) == 2
    held = json.loads(
        (out / f"001-{case.id}-spoofing-none.json").read_text(encoding="utf-8")
    )
    assert held["schema_error"]
    assert held["call"]["answer"]["text"] == '{"claims": "no"}'


def test_a_plan_on_a_charged_route_holds_the_reported_charges(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
    capsys,
):
    """On a route with no price, the hold counts the charge each call reports."""
    route = NodeRoute(
        "strong",
        TierSelection(vendor="openrouter", model="anthropic/claude-sonnet-5"),
        TierSampling(),
    )
    tiers = SimpleNamespace(charge_mode=lambda vendor: ChargeMode.DIRECT)
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering", "repudiation"])
    sent: list[str] = []
    monkeypatch.setattr(lane_replay, "node_call", _usage_calls(None, sent, charge=0.12))
    stub_route(monkeypatch, lane_replay, route, tiers)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="0.30")

    assert lane_replay.command_lane_replay(args) == 1
    printed = capsys.readouterr()
    assert "[charged]" in printed.out
    assert len(sent) == 2
    assert "up to $0.12 for the next" in printed.err


def test_unknown_on_a_priced_route_runs_a_call_with_no_usage(
    case,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    """With no cap there is nothing to hold, so a call with no usage stops nothing."""
    plan, out = _plan(tmp_path, case.id, ["spoofing", "tampering"])
    sent: list[str] = []
    monkeypatch.setattr(lane_replay, "node_call", _usage_calls(None, sent))
    stub_route(monkeypatch, lane_replay)
    args = replay_args(case=None, lane=None, plan=plan, out=out, accept_cost="unknown")

    assert lane_replay.command_lane_replay(args) == 0
    assert len(sent) == 2


@pytest.mark.parametrize("name", ["../01-payments-checkout", "a/b", "Spoofing"])
def test_a_plan_name_that_could_name_a_path_is_refused(name, tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(
        json.dumps({"case": name, "lane": "spoofing", "prepare_today": "none"}),
        encoding="utf-8",
    )

    with pytest.raises(EvalRunError, match="line 1"):
        lane_replay.read_plan(path)
