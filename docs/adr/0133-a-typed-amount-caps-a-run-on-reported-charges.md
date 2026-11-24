# 133. A typed amount caps a run on reported charges

- **Status**: accepted
- **Date**: 2026-11-24
- **Effort**: [#764](https://github.com/mstarks01/katra/issues/764)

## Context

The maintainer approves a paid run by a dollar amount. A route through
OpenRouter has no unit price: one slug reaches many endpoints at many rates, and
`evals/harness/prices.py` does not take a price from another vendor's entry. So
the estimate gate labelled such a run `unpriced`, accepted only `unknown`, and
the spend hold then had no amount to compare with. A live run on such a route
had no spend limit.

OpenRouter reports the whole charge of each call after the call, under the
`direct` charge arrangement (`docs/research/openrouter-reported-charge.md`).
`katra.charges.records_reported_charge` is the rule for that.

## Decision

**An unpriced estimate whose routes with no price each report the whole charge
of a call has the label `charged`, and a typed amount caps it.**

- `consent.charged` makes the label from an `unpriced` estimate. The sweep and
  the judge replay both call it.
- The gate takes a number for a `charged` estimate as a cap, and says that no
  estimate exists before the calls. It also takes `unknown`, which runs with no
  cap. It still refuses an infinite, a not-a-number and a negative amount, and
  it still refuses a number for an `unpriced` estimate.
- `consent.spent` counts a node run on a route with no price at its reported
  charge, once for each attempt. Such a run that reports no charge stops the
  run.
- **Before each step, the hold stops the run when the spend so far plus the
  dearest step so far passes the accepted amount.** A step is a batch of cases
  of a sweep, or one call of a replay. This rule applies to every run, priced
  or charged.
- The first step has no bound, because no charge is known before it. A
  reported charge above `katra.charges.MAX_CALL_CHARGE_USD` is not recorded, so
  the first call then stops the run on its missing charge.

## Considered options

- **Price the route at the dearest endpoint of the slug.** Rejected:
  `prices.py` refuses a third party's rate for a gateway route, and the dearest
  endpoint changes without a sign here.
- **Bound the next step by the mean step so far.** Rejected: a step dearer than
  the mean takes the run past the amount more often. The dearest step so far is
  larger or equal.
- **Compare only the spend so far, after the step.** Rejected: the last step
  then always runs past the amount by up to one step.

## Consequences

A run through OpenRouter can be approved by a dollar amount. A step dearer than
every earlier step can still take the run past the amount, and the first step
always runs. A priced sweep now stops one batch earlier than a comparison of the
spend alone would stop it.
