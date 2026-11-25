# 134. A control carries its state

- **Status**: accepted
- **Date**: 2026-11-25
- **Effort**: [#2366](https://github.com/mstarks01/katra/issues/2366)
- **Amends**: [ADR 0012](0012-the-catalog-carries-a-stated-absence.md). The
  catalog still carries a stated absence. What changes is where the absence
  is written.

## Context

The model wrote each control field — `authentication` and
`encryption_in_transit` on a flow, `encryption_at_rest` on a store — as one
string. Code then decided the state from the first word: `unknown` or a blank
string was unverified, `none` was absent, and every other value was stated. A
model that wrote "no MFA" or "not encrypted" made a stated control, so the gate
refused a value that opened with a negation or a doubt and sent it to repair
(`ambiguous-control`, `blank-control`).

The model knows which of the three states it means. Code decided it a second
time from the words, and a closed set in the schema can say it once.

## Decision

**A control field holds `ElementControl`: a `state` from the closed set
`stated`, `absent`, `unknown`, and a `detail`.**

- A `stated` control names its mechanism in `detail`, and a blank `detail` is
  refused. An `absent` or `unknown` control may give its reason in `detail`.
- The provider schema states the set as an enum. The compact transport carries
  the same object and takes no string.
- Every reader decides on `state`, through one mapping in
  `katra.analysis.CONTROL_READING`: `unknown` reads as `unverified`.
  `held_state` and `held_text` read an attribute that is a control or text.
  `control_state` still reads a text attribute — `exposure`,
  `data_classification`, `protocol` — by its first word.
- `blank-control` and `ambiguous-control` read only the text attributes.
- `SCHEMA_VERSION` is 4.0.

**A model's output refuses the string; recorded data reads through one archive
reader.**

- `parse_and_validate` validates under `LIVE_CONTEXT` unless the caller passes
  `archived=True`. Under it, a control written as a string is a `schema` issue,
  and the issue goes to repair.
- The archive reader is the `BeforeValidator` on the control field. It reads a
  string by `first_word_state`: blank or `unknown` is `unknown`, `none` is
  `absent`, and any other value is `stated` with the whole string as its
  `detail`. After a sentinel, the rest of the string is the reason.
- Recorded emissions, Baselines and experiments keep the string. The replay of
  emissions and the reader of a corpus case at an earlier revision pass
  `archived=True`. `evals/verify_corpus.py` holds the current corpus to the new
  shape, and the corpus models are rewritten.
- A stored 3.5 job record gets 409 `UnreadableSchema`, as for every version
  change. The report page reads a control of either shape, because the report
  route serves a stored report of any version.

**An answer to a control field stays one line.** The HTTP API takes `none`,
`none; <reason>`, `unknown` or the mechanism, and `control_from_text` reads it
by the same first-word rule. An answer that opens with a negation or a doubt
is refused (`control_answer_issue`).

**The text an agent reads keeps the words.** `control_text` writes a stated
control as its mechanism, and an absent or unknown one as `none` or `unknown`,
then `; <reason>` where it has one. A candidate fact, an evidence gloss and a
qualified projection therefore read as they did.

## Consequences

- A model can no longer write a stated control that reads as absent, or the
  reverse. The gate refuses a string and does not guess.
- Code decides nothing from the words of a control field. A mechanism that
  opens with "no" is a mechanism, because the model said `stated`.
- The corpus rewrite changes the digest of each case's `model.json`, so each
  merged Case Sitting no longer clears its case.
- The fix is verified by the listed offline evidence; its live quality effect
  remains unmeasured.
