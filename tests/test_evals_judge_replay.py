"""The judge replay builds blind batches and reads scripted verdicts (#764).

No test here reaches a provider. The judge's answers are scripted JSON, read by
the command's own reader, and the command is driven with a call that fails the
test where a path must send nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random

import pytest

from evals.harness import judge_replay, plants
from evals.harness.artifact import CORPUS_DIR, load_artifact, rendered_sources
from evals.harness.bundle import read_report, stride_threats
from evals.harness.identity import SubsetVerbIdentity
from evals.harness.ledger import Ledger
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import flows_by_case, load_case
from evals.harness.scorer import score_case
from evals.reference_facts import load_facts
from katra.claim_identity import report_rows
from katra.model_tiers import charges_env_var_for
from katra.offline import OFFLINE_ENV
from katra.report import TokenUsage
from tests.eval_factories import sweep_document, write_report_sweep

CASE = "01-payments-checkout"
REPORT = (
    REPO_ROOT
    / "evals/baselines/6bff717-gpt-5.6-terra-24dda4db"
    / "mstarks01-e32ad9c5.reports"
    / f"{CASE}.report.json"
)
#: A passage of the case's source, word for word.
SOURCE_QUOTE = "Shoppers sign in with email and password and get a session cookie"


@pytest.fixture
def sweep(tmp_path):
    """An analysis sweep of one case, with a real Baseline report, run on openai."""
    document = sweep_document(cases=(CASE,)) | {"mode": "analysis"}
    return write_report_sweep(
        tmp_path / "sweep.json", CASE, read_report(REPORT), document
    )


@pytest.fixture
def held(sweep):
    return judge_replay.case_input(load_artifact(sweep), CASE, random.Random(7))


def _findings(request):
    """The findings block of a request, as the judge reads it."""
    block = request.text.split("# Findings\n\n```json\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(block)


def _answer(request, verdict_of, quote=SOURCE_QUOTE):
    """A scripted judge answer: ``verdict_of(key)`` for each finding."""
    return json.dumps(
        {
            "findings": [
                {
                    "finding": label,
                    "verdict": verdict_of(key),
                    "reason": "scripted",
                    "quote": quote,
                }
                for label, key in request.labels
            ]
        }
    )


def _plants(held):
    return {item.key for item in held.items if item.population == "plant"}


def test_the_populations_are_the_scorers_matched_and_unmatched_claims(held):
    report = read_report(REPORT)
    case = load_case(CORPUS_DIR / CASE)
    flows = flows_by_case([case], {CASE: report.system_model})
    score = score_case(
        case,
        stride_threats(report),
        SubsetVerbIdentity(flows),
        Ledger(),
        report_rows(report),
    )

    keys = {
        population: {i.key for i in held.items if i.population == population}
        for population in judge_replay.POPULATIONS
    }

    assert keys["matched"] == {pair.threat_id for pair in score.matched}
    assert keys["unlisted"] == {entry.threat_id for entry in score.unlisted}
    assert len(keys["plant"]) == len(held.plants) > 0
    assert held.left_out == {"lane_errors": 0, "foreign": 0}


def test_the_judge_sees_no_critic_verdict_or_reason(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))
    reasons = [
        threat.verdict.reason
        for threat in stride_threats(read_report(REPORT))
        if threat.verdict.reason
    ]

    for request in requests:
        for finding in _findings(request):
            assert set(finding) == {"label", *judge_replay.VIEW_FIELDS}
        assert all(reason not in request.text for reason in reasons)
    assert reasons, "no report finding carries a critic reason, so this checks nothing"


def test_each_sample_holds_every_finding_in_its_own_order(held):
    first, second = judge_replay.requests_for([held], 2, random.Random(1))

    keys = [[key for _, key in request.labels] for request in (first, second)]
    assert sorted(keys[0]) == sorted(keys[1]) == sorted(i.key for i in held.items)
    assert keys[0] != keys[1]


def test_two_samples_that_agree_give_the_verdict_with_its_denominators(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))
    plants = _plants(held)

    def verdict(key):
        return "rejected" if key in plants else "supported"

    result = judge_replay.judged(
        [held], requests, [_answer(r, verdict) for r in requests]
    )

    sizes = {
        p: sum(i.population == p for i in held.items) for p in judge_replay.POPULATIONS
    }
    pooled = result["pooled"]
    assert pooled["plants"] == {
        "rejected": 2 * sizes["plant"],
        "supported": 0,
        "unsure": 0,
        "no_answer": 0,
        "of": 2 * sizes["plant"],
    }
    assert pooled["matched"] == {
        "supported": sizes["matched"],
        "rejected": 0,
        "unsure": 0,
        "of": sizes["matched"],
    }
    assert (
        pooled["unlisted"]["supported"] == pooled["unlisted"]["of"] == sizes["unlisted"]
    )
    assert pooled["self_agreement"] == {
        "agreed": sizes["matched"] + sizes["unlisted"],
        "of": sizes["matched"] + sizes["unlisted"],
    }
    assert result["cases"][0]["numbers"] == pooled
    assert result["void_batches"] == []


def test_a_finding_the_samples_answer_differently_reads_unsure(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))
    plants = _plants(held)
    split = next(i.key for i in held.items if i.population == "unlisted")

    def answers(request):
        def verdict(key):
            if key in plants:
                return "rejected"
            if key == split and request.sample == 2:
                return "rejected"
            return "supported"

        return _answer(request, verdict)

    result = judge_replay.judged([held], requests, [answers(r) for r in requests])

    unlisted = result["pooled"]["unlisted"]
    assert unlisted["unsure"] == 1
    assert unlisted["supported"] == unlisted["of"] - 1
    agreement = result["pooled"]["self_agreement"]
    assert agreement["agreed"] == agreement["of"] - 1


def test_a_finding_one_sample_leaves_unanswered_reads_unsure(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))
    plants = _plants(held)
    skipped = next(i.key for i in held.items if i.population == "matched")
    first = json.loads(
        _answer(requests[0], lambda k: "rejected" if k in plants else "supported")
    )
    first["findings"] = [
        f
        for f in first["findings"]
        if dict(requests[0].labels)[f["finding"]] != skipped
    ]
    second = _answer(requests[1], lambda k: "rejected" if k in plants else "supported")

    result = judge_replay.judged([held], requests, [json.dumps(first), second])

    assert result["pooled"]["matched"]["unsure"] == 1


def test_a_plant_the_judge_supports_voids_that_samples_batch(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))
    plants = _plants(held)

    def answers(request):
        if request.sample == 2:
            return _answer(request, lambda key: "supported")
        return _answer(
            request, lambda key: "rejected" if key in plants else "supported"
        )

    result = judge_replay.judged([held], requests, [answers(r) for r in requests])

    assert result["void_batches"] == [{"case": CASE, "sample": 2}]
    pooled = result["pooled"]
    assert pooled["plants"]["supported"] == len(plants)
    assert pooled["plants"]["of"] == 2 * len(plants)
    # The void sample's verdicts count for no finding, so one valid sample is
    # left, and one sample measures no agreement.
    assert pooled["matched"]["supported"] == pooled["matched"]["of"] > 0
    assert pooled["self_agreement"] == {"agreed": 0, "of": 0}
    assert result["cases"][0]["samples"][1]["void"] is True


def test_every_quote_is_checked_and_an_unverifiable_one_is_counted(held):
    requests = judge_replay.requests_for([held], 1, random.Random(1))
    plants = _plants(held)
    quotes = iter(
        ["the shop keeps its card numbers on a floppy disk", "", SOURCE_QUOTE]
    )

    def answer(request):
        payload = json.loads(
            _answer(request, lambda key: "rejected" if key in plants else "supported")
        )
        for finding in payload["findings"]:
            finding["quote"] = next(quotes, SOURCE_QUOTE)
        return json.dumps(payload)

    result = judge_replay.judged([held], requests, [answer(r) for r in requests])

    total = len(held.items)
    assert result["pooled"]["quotes"] == {
        "verified": total - 2,
        "unverifiable": 1,
        "absent": 1,
    }
    stated = result["cases"][0]["samples"][0]["findings"]
    assert {f["quote_state"] for f in stated} == set(judge_replay.QUOTE_STATES)
    assert any(
        f["quote"] == "the shop keeps its card numbers on a floppy disk" for f in stated
    )


def test_an_answer_that_does_not_parse_is_read_as_unreadable(held):
    requests = judge_replay.requests_for([held], 1, random.Random(1))

    result = judge_replay.judged([held], requests, ["not json"])

    sample = result["cases"][0]["samples"][0]
    assert sample["unreadable"] is True
    assert result["pooled"]["matched"]["of"] == 0
    assert result["pooled"]["plants"]["of"] == 0


def test_a_label_outside_the_batch_is_stray():
    request = judge_replay.Request("c", 1, (("F-01", "k"),), "")
    item = judge_replay.Item("k", "matched", {})
    raw = json.dumps(
        {
            "findings": [
                {"finding": "F-01", "verdict": "supported", "reason": "", "quote": ""},
                {"finding": "F-01", "verdict": "rejected", "reason": "", "quote": ""},
                {"finding": "F-09", "verdict": "rejected", "reason": "", "quote": ""},
            ]
        }
    )

    reading = judge_replay.read_answer(raw, request, [item], ())

    assert reading.stray == ("F-01", "F-09")
    assert reading.answers["k"].verdict == "supported"


@pytest.mark.parametrize(
    ("writer", "judge", "breach"),
    [
        ("openai/gpt-5.6", "anthropic/claude-opus-5", None),
        ("openai/gpt-5.6", "openrouter/anthropic/claude-opus-5", None),
        ("openrouter/openai/gpt-5.6", "anthropic/claude-opus-5", None),
        ("openai/gpt-5.6", "openai/gpt-5.5", "source vendor 'openai'"),
        ("openai/gpt-5.6", "openrouter/openai/gpt-5.6", "source vendor 'openai'"),
        ("openai/gpt-5.6", "openrouter/unknown-lab/model-1", "'openrouter/unknown"),
    ],
)
def test_the_judge_must_run_a_model_from_another_source_vendor(writer, judge, breach):
    found = judge_replay.independence_breach([writer], judge)

    if breach is None:
        assert found is None
    else:
        assert breach in found


def test_one_writer_from_the_judge_s_source_vendor_is_a_breach():
    writers = ["openai/gpt-5.6", "anthropic/claude-sonnet-4-6"]

    found = judge_replay.independence_breach(writers, "anthropic/claude-opus-5")

    assert "source vendor 'anthropic'" in found


def test_the_writers_are_the_routes_the_sweep_requested(sweep):
    routes = judge_replay.writer_routes(load_artifact(sweep))

    assert routes
    assert all(route.startswith("openai/") for route in routes)


def test_an_unpriced_route_reads_unpriced_never_zero(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))

    cost = judge_replay.estimate(
        "instruction", requests, "openrouter/openai/gpt-5.6-terra"
    )

    assert cost.label == "unpriced"
    assert cost.amount_usd is None


def test_a_priced_route_states_an_amount_per_case(held):
    requests = judge_replay.requests_for([held], 2, random.Random(1))

    cost = judge_replay.estimate("instruction", requests, "anthropic/claude-opus-5")

    assert cost.label == "estimated"
    assert cost.amount_usd > 0
    assert any(line.startswith(f"{CASE}: $") for line in cost.lines)


def _args(sweep, out, **given):
    namespace = {
        "artifact": sweep,
        "out": out,
        "samples": 2,
        "case": None,
        "dry_run": False,
        "accept_cost": None,
    }
    return argparse.Namespace(**(namespace | given))


@pytest.fixture
def no_call(monkeypatch):
    """Fail the test where the command builds a call."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("the command built a call it must not send")

    monkeypatch.setattr(judge_replay, "tier_call", refuse)


def test_the_dry_run_sends_nothing_and_writes_the_requests(sweep, tmp_path, no_call):
    out = tmp_path / "requests.json"

    assert judge_replay.command_judge_replay(_args(sweep, out, dry_run=True)) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["dry_run"] is True
    assert written["estimate"]["label"] == "estimated"
    assert [len(case["requests"]) for case in written["cases"]] == [2]
    assert written["cases"][0]["plants"][0]["fact"]["case"] == CASE
    assert written["instruction_sha256"]
    assert written["record"]["command"] == "judge-replay"


def test_the_command_refuses_a_judge_from_the_writers_source_vendor(
    sweep, tmp_path, monkeypatch, no_call, capsys
):
    monkeypatch.setenv("KATRA_MODEL_REVIEW_VENDOR", "openai")
    monkeypatch.setenv("KATRA_MODEL_REVIEW_MODEL", "gpt-4.1-mini")

    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="100")
    )

    assert code == 1
    assert "source vendor 'openai'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("model", "breach"),
    [("anthropic/claude-opus-5", None), ("openai/gpt-5.6", "source vendor 'openai'")],
)
def test_a_judge_through_an_aggregator_is_read_by_its_slug(
    sweep, tmp_path, monkeypatch, no_call, capsys, model, breach
):
    monkeypatch.setenv("KATRA_MODEL_REVIEW_VENDOR", "openrouter")
    monkeypatch.setenv("KATRA_MODEL_REVIEW_MODEL", model)
    monkeypatch.setenv(charges_env_var_for("openrouter"), "direct")
    out = tmp_path / "requests.json"

    assert judge_replay.command_judge_replay(_args(sweep, out, dry_run=True)) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["judge"]["route"] == f"openrouter/{model}"
    if breach is None:
        assert written["independence_breach"] is None
        assert "independence distinct source vendors" in capsys.readouterr().out
    else:
        assert breach in written["independence_breach"]


def test_the_command_refuses_a_cost_above_the_accepted_amount(
    sweep, tmp_path, no_call, capsys
):
    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="0.0001")
    )

    assert code == 1
    assert "raise --accept-cost" in capsys.readouterr().err


def test_offline_mode_refuses_the_first_call(sweep, tmp_path, capsys):
    out = tmp_path / "out.json"

    code = judge_replay.command_judge_replay(_args(sweep, out, accept_cost="100"))

    assert code == 1
    assert OFFLINE_ENV in capsys.readouterr().err
    written = json.loads(out.read_text(encoding="utf-8"))
    assert OFFLINE_ENV in written["stopped"]
    assert written["not_run"] == [
        {"case": CASE, "sample": 1},
        {"case": CASE, "sample": 2},
    ]
    assert written["pooled"]["matched"]["of"] == 0


def _scripted(usage=None, fail_on=None, sent=None, attempts=1, charge=None):
    """A ``tier_call`` stand-in that rejects every finding.

    ``usage`` is the token usage each call reports, as ``tier_call`` records
    it in ``seen``, and ``fail_on`` the number of the call that raises a
    provider error. ``charge`` is the charge each call reports, or ``None``
    for no charge, as on a direct vendor.
    """

    def build(_deployment, _tier, _schema, spent, seen):
        calls = []

        async def call(instruction, turn):
            calls.append(instruction)
            if sent is not None:
                sent.append(instruction)
            if fail_on is not None and len(calls) == fail_on:
                raise RuntimeError("the provider failed")
            text = turn.parts[0].text
            labels = [
                f["label"]
                for f in json.loads(text.split("```json\n")[-1].rsplit("```", 1)[0])
            ]
            spent.append(charge)
            seen.append(
                {
                    "text": "",
                    "responses": [],
                    "usage": usage,
                    "attempts": attempts,
                    "reasks": 0,
                    "reported_charge_usd": charge,
                }
            )
            return json.dumps(
                {
                    "findings": [
                        {
                            "finding": label,
                            "verdict": "rejected",
                            "reason": "",
                            "quote": "",
                        }
                        for label in labels
                    ]
                }
            )

        return call

    return build


def test_a_live_run_writes_the_verdicts_and_the_numbers(sweep, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(sent=sent))
    out = tmp_path / "out.json"

    assert judge_replay.command_judge_replay(_args(sweep, out, accept_cost="100")) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert len(sent) == 2
    assert sent[0] == judge_replay.INSTRUCTION.read_text(encoding="utf-8")
    assert (
        written["pooled"]["plants"]["rejected"] == written["pooled"]["plants"]["of"] > 0
    )
    assert written["void_batches"] == []
    assert written["not_run"] == []
    assert written["stopped"] is None
    assert written["judge"] == {"tier": "review", "route": "anthropic/claude-opus-5"}


def test_the_measured_usage_holds_the_next_call(sweep, tmp_path, monkeypatch, capsys):
    """On a direct route the provider reports usage and no charge. The first
    call reports far more tokens than its estimate, so its priced usage passes
    what was accepted and the hold stops the second call."""
    sent = []
    usage = TokenUsage(prompt_tokens=2_000_000, total_tokens=2_000_000).model_dump()
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(usage, sent=sent))
    out = tmp_path / "out.json"

    code = judge_replay.command_judge_replay(_args(sweep, out, accept_cost="5.00"))

    assert code == 1
    assert len(sent) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "pass $5.00 accepted" in written["stopped"]
    assert written["not_run"] == [{"case": CASE, "sample": 2}]
    assert written["cases"][0]["samples"][0]["sample"] == 1
    assert "stopped" in capsys.readouterr().err


@pytest.fixture
def openrouter_judge(monkeypatch):
    """A judge through an aggregator: a route with no price whose vendor
    reports the whole charge of each call."""
    monkeypatch.setenv("KATRA_MODEL_REVIEW_VENDOR", "openrouter")
    monkeypatch.setenv("KATRA_MODEL_REVIEW_MODEL", "anthropic/claude-opus-5")
    monkeypatch.setenv(charges_env_var_for("openrouter"), "direct")


def test_a_charged_judge_stops_at_the_cap(
    sweep, tmp_path, monkeypatch, openrouter_judge
):
    """The first call reports $0.60. Before the second, $0.60 spent and up to
    $0.60 for the next call pass the $1.00 cap, so the hold stops it."""
    sent = []
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(sent=sent, charge=0.60))
    out = tmp_path / "out.json"

    code = judge_replay.command_judge_replay(_args(sweep, out, accept_cost="1.00"))

    assert code == 1
    assert len(sent) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "pass $1.00 accepted" in written["stopped"]
    assert written["not_run"] == [{"case": CASE, "sample": 2}]


def test_a_charged_judge_inside_the_cap_runs_every_call(
    sweep, tmp_path, monkeypatch, openrouter_judge
):
    sent = []
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(sent=sent, charge=0.40))

    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="1.00")
    )

    assert (code, len(sent)) == (0, 2)


def test_a_charged_judge_call_that_reports_no_charge_stops_the_run(
    sweep, tmp_path, monkeypatch, openrouter_judge
):
    sent = []
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(sent=sent, charge=None))
    out = tmp_path / "out.json"

    code = judge_replay.command_judge_replay(_args(sweep, out, accept_cost="100"))

    assert (code, len(sent)) == (1, 1)
    assert "reported no charge" in json.loads(out.read_text())["stopped"]


def test_a_call_that_reports_no_usage_counts_at_its_estimate():
    request = judge_replay.Request("c", 1, (("F-01", "k"),), "x" * 400)
    fallback = judge_replay.request_usage("instruction", request)

    run = judge_replay.measured_run(None, fallback, "anthropic/claude-opus-5")
    reported = judge_replay.measured_run(
        {"usage": None, "attempts": 1, "reasks": 0, "reported_charge_usd": None},
        fallback,
        "anthropic/claude-opus-5",
    )

    assert run.usage == reported.usage == fallback


def test_usage_within_the_accepted_amount_runs_every_call(sweep, tmp_path, monkeypatch):
    usage = TokenUsage(prompt_tokens=1_000, total_tokens=1_000).model_dump()
    sent = []
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(usage, sent=sent))

    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="5.00")
    )

    assert code == 0
    assert len(sent) == 2


def test_a_provider_error_keeps_the_paid_answers(sweep, tmp_path, monkeypatch):
    monkeypatch.setattr(judge_replay, "tier_call", _scripted(fail_on=2))
    out = tmp_path / "out.json"

    code = judge_replay.command_judge_replay(_args(sweep, out, accept_cost="100"))

    assert code == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "the provider failed" in written["stopped"]
    assert written["not_run"] == [{"case": CASE, "sample": 2}]
    assert written["pooled"]["plants"]["of"] > 0
    assert len(written["answers"]) == 1


def test_each_answer_is_written_as_it_arrives(sweep, tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    seen_on_disk = []
    real = judge_replay.judged

    def judged(inputs, requests, raws):
        if out.exists():
            seen_on_disk.append(len(json.loads(out.read_text())["not_run"]))
        return real(inputs, requests, raws)

    monkeypatch.setattr(judge_replay, "judged", judged)
    monkeypatch.setattr(judge_replay, "tier_call", _scripted())

    assert judge_replay.command_judge_replay(_args(sweep, out, accept_cost="100")) == 0
    # The file held one call not run after the first answer.
    assert 1 in seen_on_disk


def test_a_sweep_that_names_no_writer_is_refused():
    breach = judge_replay.independence_breach([], "anthropic/claude-opus-5")

    assert breach is not None
    assert "records no requested model" in breach


def test_a_writer_from_the_judge_s_source_vendor_is_refused(
    sweep, tmp_path, monkeypatch, no_call, capsys
):
    monkeypatch.setattr(
        judge_replay,
        "writer_routes",
        lambda _artifact: ("openrouter/anthropic/claude-opus-4.7",),
    )

    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="100")
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "source vendor 'anthropic'" in err


def test_a_case_whose_sources_moved_is_left_out(tmp_path):
    document = sweep_document(cases=(CASE,)) | {
        "mode": "analysis",
        "rendered_sources": {CASE: "0" * 64},
    }
    path = write_report_sweep(
        tmp_path / "sweep.json", CASE, read_report(REPORT), document
    )

    assert judge_replay.moved_sources(load_artifact(path), [CASE]) == [CASE]


def test_a_case_whose_sources_match_is_kept(tmp_path):
    case = load_case(CORPUS_DIR / CASE)
    document = sweep_document(cases=(CASE,)) | {
        "mode": "analysis",
        "rendered_sources": rendered_sources([case]),
    }
    path = write_report_sweep(
        tmp_path / "sweep.json", CASE, read_report(REPORT), document
    )

    assert judge_replay.moved_sources(load_artifact(path), [CASE]) == []


def test_a_model_with_older_flow_ids_reaches_the_signed_facts():
    """d4edd64 spells its flows under flow identity version 1, and the signed
    facts spell them under the version this code writes."""
    report = read_report(
        REPO_ROOT
        / "evals/baselines/d4edd64-gpt-5.6-terra-fd1c49af"
        / "mstarks01-ab5d72fb.reports"
        / "02-iot-fleet-telemetry.report.json"
    )
    facts = load_facts(CORPUS_DIR / "02-iot-fleet-telemetry")
    renamed = judge_replay.current_flow_ids(report.system_model)

    found = plants.candidates("02", report.system_model, facts, renamed)

    assert renamed
    assert plants.candidates("02", report.system_model, facts, {}) == ()
    assert {fact.element_id for fact in found} <= set(renamed)
    assert found


@pytest.mark.parametrize(("attempts", "held"), [(1, False), (3, True)])
def test_the_hold_prices_each_failed_attempt(
    sweep, tmp_path, monkeypatch, capsys, attempts, held
):
    """400,000 prompt tokens price at about $2 a call on this route. Three
    attempts are three prompts, about $6, which passes $5.00 and holds the next
    call; one attempt does not."""
    usage = TokenUsage(prompt_tokens=400_000, total_tokens=400_000).model_dump()
    sent = []
    monkeypatch.setattr(
        judge_replay, "tier_call", _scripted(usage, sent=sent, attempts=attempts)
    )

    code = judge_replay.command_judge_replay(
        _args(sweep, tmp_path / "out.json", accept_cost="5.00")
    )

    assert (code, len(sent)) == ((1, 1) if held else (0, 2))
    if held:
        assert "1 call(s) have not run" in capsys.readouterr().out


def _tier_call_on(monkeypatch, response):
    """Run one ``tier_call`` whose adapter yields ``response``; return what it
    recorded in ``seen`` and ``spent``."""
    from types import SimpleNamespace

    from google.genai import types

    from evals.harness import node_call as module

    class Adapter:
        model = "stub"

        async def generate_content_async(self, request, stream):
            yield response

    monkeypatch.setattr(
        module, "build_tier_adapters", lambda *a, **k: {"review": Adapter()}
    )
    deployment = SimpleNamespace(
        tiers=SimpleNamespace(bound_tiers=frozenset({"review"})),
        resilience=None,
        env={},
        sampling=SimpleNamespace(
            for_tier=lambda tier: SimpleNamespace(
                to_generate_content_config=types.GenerateContentConfig
            )
        ),
    )
    seen: list = []
    spent: list = []
    call = module.tier_call(deployment, "review", None, spent, seen)
    asyncio.run(call("instruction", types.Content(role="user", parts=[])))
    return seen, spent


def test_a_judge_call_prices_as_a_graph_run_prices_the_same_response(monkeypatch):
    """The sweep path builds its node run from the response's stamps through
    ``event_usage``, ``event_attempts`` and ``event_reasks``; the replay builds
    it from what ``tier_call`` records. The two price alike."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    from evals.harness import consent
    from katra.execution import event_attempts, event_reasks, event_usage
    from katra.provider import REASKS_METADATA_KEY
    from katra.report import NodeRun
    from katra.retry import ATTEMPTS_METADATA_KEY

    response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text="{}")]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1_000, candidates_token_count=10
        ),
        custom_metadata={ATTEMPTS_METADATA_KEY: 3, REASKS_METADATA_KEY: 1},
    )
    seen, _ = _tier_call_on(monkeypatch, response)
    route = "anthropic/claude-opus-5"
    swept = NodeRun(
        node="judge",
        model=route,
        requested_model=route,
        duration_ms=0,
        usage=event_usage(response),
        attempts=event_attempts(response),
        reasks=event_reasks(response),
    )

    replayed = judge_replay.measured_run(seen[0], TokenUsage(), route)

    assert (replayed.attempts, replayed.reasks) == (3, 1)
    assert consent.spent([replayed]) == consent.spent([swept]) > 0


def test_a_reported_charge_of_zero_stays_zero(monkeypatch):
    """A free or cached call reports 0.0, and 0.0 is a charge, not a missing one."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    from katra.charges import CHARGE_METADATA_KEY

    response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text="{}")]),
        custom_metadata={CHARGE_METADATA_KEY: 0.0},
    )

    seen, spent = _tier_call_on(monkeypatch, response)

    assert seen[0]["reported_charge_usd"] == 0.0
    assert spent == [0.0]
