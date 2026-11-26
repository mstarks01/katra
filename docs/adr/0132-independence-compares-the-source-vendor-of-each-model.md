# 132. Independence compares the source vendor of each model

- **Status**: accepted
- **Date**: 2026-11-24
- **Effort**: [#764](https://github.com/mstarks01/katra/issues/764)
- **Amended by**: [ADR 0136](0136-a-node-may-name-its-own-model.md), which
  compares the effective model of each node and names the judge with `--judge`

## Context

Two checks need a model that is independent of another model. The critic
policy `review_independence` keeps a framework's critic apart from its
analysis. The eval judge replay keeps its judge apart from the models that
wrote the sweep.

The maintainer's rule for an aggregator such as OpenRouter: the models must
differ by source vendor, the company that made each model. Anthropic models
must not judge one another, whichever aggregator serves them.

An aggregator chooses its upstream provider on each call. The upstream provider
is not known before the call, but the model is. The slug
`anthropic/claude-opus-4.7` names an Anthropic model on every upstream.

## Decision

**Independence compares the source vendor of each side's model.** The vendor
that serves the model does not matter.

- Each vendor row states `source_vendor_rule`. A row that serves the models of
  one source vendor names it: `anthropic`, `openai` and `gemini`. A row that
  serves more than one reads it from the model ID: `vertex` from the family
  word, `bedrock` from the segment after an optional scope, and `openrouter`
  from the segment before the slash.
- `katra.vendors.SourceVendor` is the closed set of source vendors.
- `katra.model_tiers.source_vendor_breach` is the rule. The critic policy
  `distinct_source_vendor` and `evals.harness.judge_replay` both call it.
- Two models from one source vendor breach, through any vendors. Two models
  from two source vendors pass, through any vendors.
- A model ID whose source vendor the row cannot read is a breach, and the
  message names the route.

## Considered options

- **Compare the serving vendor, and refuse an aggregator on either side.**
  Rejected: it refuses an OpenRouter judge on an Anthropic slug against an
  OpenAI sweep, which the maintainer's rule allows. It also passes Claude on
  Vertex against Claude on Anthropic's own API, which the rule refuses.
- **Compare the upstream provider that an aggregator reports.** Rejected: the
  upstream is known only after the call, and the rule is about the maker of
  the model, not about the host.

## Consequences

A deployment or a judge can run through OpenRouter when its model comes from a
different source vendor.

A model on a multi-maker vendor whose maker the row does not list fails
closed. Add the maker to the row's `makers` and to `SourceVendor` to admit it.
