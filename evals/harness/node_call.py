"""One graph node's model call, made outside the graph on the route the graph would use.

A replay runs one node over archived input and pays for one call. The call has
to reach the provider in the shape the graph gives it, or the replay measures
a different request: the adapter of the node's binding, the binding's
sampling, the node's output schema as ``response_schema``, and the instruction
as the system instruction. ADK builds all four from the ``LlmAgent``; this
builds the same four from the deployment, through
:meth:`~katra.deployment.Deployment.binding_of`, which is the one reader of the
walk from a graph node to its binding.

The user turn is the caller's, because it differs by node: a lane receives
``prepare``'s output and a critic receives its fan-in's, each through ADK's
``to_user_content``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from katra.binding import build_adapter, build_tier_adapters
from katra.deployment import Deployment
from katra.execution import (
    event_attempts,
    event_reasks,
    event_reported_charge,
    event_usage,
)
from katra.model_tiers import Binding, TierSelection
from katra.provider import ExecutedLlm
from katra.sampling import TierSampling

#: One call: the instruction and the user turn in, the model's raw text out.
NodeCall = Callable[[str, types.Content], Awaitable[str]]


def node_call(
    deployment: Deployment,
    graph_node: str,
    schema: Any,
    spent: list[float | None] | None = None,
    seen: list[dict[str, Any]] | None = None,
) -> NodeCall:
    """The call ``graph_node`` makes, on this deployment's route for it.

    ``spent`` receives the charge the provider reported for each call, or
    ``None`` where it reported none, read off the stamp
    :mod:`katra.charges` puts on the response. A replay is a paid
    call, and its caller states what it spent rather than an estimate.
    ``seen`` receives, for each call, the answer text, why the provider
    stopped and the tokens it counted, so a replay that parses to nothing can
    be read without a second paid call. Its ``usage`` is the call's
    :class:`~katra.report.TokenUsage` as :func:`~katra.execution.event_usage`
    reads it, or ``None`` where the provider reported none. Its ``attempts``
    and ``reasks`` are the retry driver's stamps, as
    :func:`~katra.execution.event_attempts` and
    :func:`~katra.execution.event_reasks` read them for a graph run, so a
    caller that prices the call prices each failed attempt too. Its
    ``reported_charge_usd`` is the charge in ``spent``, as
    :func:`~katra.execution.event_reported_charge` reads it for a graph run.
    """
    binding = deployment.binding_of(graph_node)
    adapter = build_tier_adapters(
        deployment.tiers,
        deployment.sampling,
        deployment.resilience,
        env=deployment.env,
    )[binding]
    return adapter_call(
        adapter, deployment.sampling.for_binding(binding), schema, spent, seen
    )


def selection_call(
    deployment: Deployment,
    binding: Binding,
    selection: TierSelection,
    sampling: TierSampling,
    schema: Any,
    spent: list[float | None] | None,
    seen: list[dict[str, Any]] | None,
) -> NodeCall:
    """One call on a model that no graph node runs on.

    An eval call that no graph node makes, such as the judge of
    ``evals/harness/judge_replay.py``, names its own model and sampling.
    :func:`~katra.binding.build_adapter` checks them as it checks a bound
    tier, and ``binding`` names the call in its error messages. ``spent`` and
    ``seen`` are as :func:`node_call` states them.
    """
    adapter = build_adapter(
        binding,
        selection,
        sampling,
        deployment.tiers,
        deployment.resilience,
        deployment.env,
    )
    return adapter_call(adapter, sampling, schema, spent, seen)


def adapter_call(
    adapter: ExecutedLlm,
    sampling: TierSampling,
    schema: Any,
    spent: list[float | None] | None,
    seen: list[dict[str, Any]] | None,
) -> NodeCall:
    """One call through ``adapter``, with ``sampling`` and ``schema`` on the request."""

    async def call(instruction: str, turn: types.Content) -> str:
        config = sampling.to_generate_content_config()
        config.system_instruction = instruction
        config.response_schema = schema
        request = LlmRequest(model=adapter.model, contents=[turn], config=config)
        chunks = []
        charge = None
        stops: list[dict[str, Any]] = []
        measured = None
        attempts, reasks = 1, 0
        async for response in adapter.generate_content_async(request, False):
            reported = event_reported_charge(response)
            charge = charge if reported is None else reported
            measured = event_usage(response) or measured
            attempts, reasks = event_attempts(response), event_reasks(response)
            chunks.append(answer_text(response))
            usage = response.usage_metadata
            stops.append(
                {
                    "finish_reason": None
                    if response.finish_reason is None
                    else str(response.finish_reason),
                    "error_message": response.error_message,
                    "output_tokens": None
                    if usage is None
                    else usage.candidates_token_count,
                    "thought_tokens": None
                    if usage is None
                    else usage.thoughts_token_count,
                }
            )
        if spent is not None:
            spent.append(charge)
        if seen is not None:
            seen.append(
                {
                    "text": "".join(chunks),
                    "responses": stops,
                    "usage": None if measured is None else measured.model_dump(),
                    "attempts": attempts,
                    "reasks": reasks,
                    "reported_charge_usd": charge,
                }
            )
        return "".join(chunks)

    return call


def spent_line(spent: list[float | None]) -> str:
    """The line a replay prints of what its calls cost, as the provider reported."""
    charged = [charge for charge in spent if charge is not None]
    missing = "" if len(charged) == len(spent) else "; the provider reported no charge"
    return f"spent: ${sum(charged):.4f} reported{missing}"


def answer_text(response: LlmResponse) -> str:
    """The text of a response's answer parts, without its thought parts.

    A reasoning model can return its thinking as text parts flagged
    ``thought``, ahead of the answer. ADK leaves those out of a node's output,
    so a replay that joined them handed the schema a paragraph of reasoning
    in front of the JSON the graph would have parsed.
    """
    parts = (response.content.parts if response.content else None) or []
    return "".join(part.text for part in parts if part.text and not part.thought)
