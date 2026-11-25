# 135. A flow's protocol can satisfy ASVS and never refute it

- **Status**: accepted
- **Date**: 2026-11-25
- **Effort**: [#2382](https://github.com/mstarks01/katra/issues/2382), part of
  [#2354](https://github.com/mstarks01/katra/issues/2354)
- **Amends**: [ADR 0014](0014-applicability-reads-what-a-process-presents.md),
  whose precondition let the flows refute ASVS for a model with no processes
- **Relates to**: [ADR 0027](0027-vocabulary-raises-a-lead-and-rules-nothing-out.md),
  whose rule this decision applies to the precondition

## Context

The ASVS **Precondition** reads the processes first. Where no process states an
interface, it reads each **Data Flow**'s `protocol` against
`WEB_PROTOCOL_TERMS`, a word list. For a model with no processes, the
precondition returned `refuted` when every flow stated a protocol and no
protocol matched a term in the list.

The list does not hold every web protocol. A flow that states `h2` or
`connect-rpc` carries the web, and no term matches it. So a real web system
with no processes lost ASVS, and the report said that ASVS does not apply.
Nothing warned the operator.

ADR 0027 states the rule that this path broke: a word list raises a lead and
never rules anything out.

## Decision

**The web word list can only satisfy the precondition.** A flow that names a
listed web protocol, and negates nothing, gives `satisfied`. A flow that names
no listed web protocol rules nothing out.

**Only the processes refute.** The precondition gives `refuted` only when every
process states a `non-web` interface. A model with no processes, whose flows
name no listed web protocol, gives `undecidable`.

`asvs_precondition_facts` names each flow that does not speak a listed web
protocol, on the path with no processes. `_speaks_web` is the one reader of a
web protocol for the precondition and its facts.

## Consequences

- A real web system with no processes and an unlisted web protocol is no longer
  refused. Its ASVS block says that the input never settled the question.
- A system with no processes and only non-web flows, such as a message bus,
  also gets `undecidable` and not `refuted`. To refute ASVS, each process in
  the model must state a `non-web` interface.
- A paused job asks the protocol of each open flow only where `open_attribute`
  says the protocol is open. A stated protocol, such as `MQTT`, is not open,
  so the pause asks no question for it. The submitter settles the question with
  more input about the system.
- No model under `evals/` changes its answer. Each model there with no
  processes also has no flows, so it was `undecidable` under both rules.
- The live quality effect is unmeasured.
