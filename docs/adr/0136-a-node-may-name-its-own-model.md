# 136. A node may name its own model

- **Status**: accepted
- **Date**: 2026-11-26
- **Effort**: [#2352](https://github.com/mstarks01/katra/issues/2352)
- **Supersedes**: [ADR 0101](0101-a-lane-may-run-on-its-own-tier.md), whose
  lane key names a tier
- **Amends**: [ADR 0132](0132-independence-compares-the-source-vendor-of-each-model.md),
  which compares the models of two tiers

## Context

A node gets its model in two steps. The `[nodes]` map in
`config/model_tiers.toml` puts each node on a tier: `base`, `strong` or
`review`. Each tier names one vendor and one model.

The Settings page changes only the second step. It shows a vendor field and a
model field for each tier. No field changes the node map. The shipped map puts
no node on `review`, so the **Review vendor** and **Review model** fields change
a tier that nothing uses, and the page does not say so.

`review` exists so that a critic can run on a model other than the analysis it
checks. To get that, an operator edits the node map, moves the critic and the
recritic, and selects a third pair. The loader then checks that the recritic
sits on the critic's tier.

## Decision

**Two tiers stay: `base` and `strong`.** Each node belongs to the tier that it
uses in the shipped map, and code holds that membership. A deployment that sets
only the two tiers runs each node on the model it ran before.

**A node can name its own model.** An override on a node gives it its own
vendor and model. A node with no override uses its tier's model. An override
can carry its own sampling block in `config/sampling.toml`. A node with an
override and no block uses its tier's sampling, and an empty block gives the
vendor's defaults.

**The `review` tier goes.** An independent critic is an override on
`critic/<framework>`.

**The recritic follows its critic.** `recritic/<framework>` has no setting. It
runs on the effective model and sampling of `critic/<framework>`, so the
pairing check goes: the mismatch cannot occur.

**A lane override names a model.** `analyze/<framework>/<lane>` names a vendor
and a model, and not a tier. A lane with no override runs on the effective
model of `analyze/<framework>`.

**`review_independence` stays.** It compares the critic's effective model with
the effective model of each analysis node of its framework, by the rules of
ADR 0132.

**A binding keys each node's model setting.** A binding is a tier name, or the
key of a node with an override. `ModelTierConfig.binding_of` is the one reader
of which binding a node runs on. The adapters, the sampling resolver, the
execution record of a sweep and each report row key a node by its binding.
Each `NodeRun` carries `binding`, so a reader of a report sees where each
node's model came from without the config file. That is report schema 4.1.

**The judge replay names its own model.** It is an eval and not a node.
`--judge <vendor>/<model>` names the judge, which runs at the vendor's default
sampling, and the output records both.

**The cutover is hard.** The tier config gets a new version. The loader refuses
a string under `[nodes]` and a `review` tier, with a message that names the new
shape.

## Consequences

- The execution fingerprint of a node does not change for a deployment that
  sets only the two tiers. `katra.identity.execution_fingerprint` hashes the
  requested route, the served route, the sampling, the instruction digest and
  the build. It hashes no tier and no binding, so a blessed fingerprint stays
  valid.
- The identity of a Baseline changes once at the cutover. Its `sampling` part
  holds a block for each tier of the sweep's record, and that record lists
  `review` before the cutover and does not after it. A sweep after the
  cutover is a new Baseline in any case, because the commit is also a part of
  the identity.
- A sweep's execution record keeps the field name `tier` and holds the
  binding there. An archived record that names `review` stays readable.
- More overrides make fewer runs comparable with a Baseline. Each execution
  records its requested route and its sampling, so a comparison stays correct.
- A change to an override makes a run uncertified until a sweep measures it,
  as a change to a tier does.
- A second-opinion model beside the critic is a separate decision.
