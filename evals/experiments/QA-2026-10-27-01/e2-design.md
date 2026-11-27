# QA-2026-10-27-01-E2 design, written before any call

Hypothesis: a paragraph in frameworks/stride/output.md that tells the lane to ask
first about the parties the model already trusts at a place, then a party that
makes a trusted one act for it, and last a party between the ends, makes the
lane match more of the 14 must-finds the Sonnet 5 medium sweep missed.

Instrument: lane-replay --prepare-today signed, on the tier file's strong route
(openai/gpt-5.6-terra through openai/flex), for each (case, lane) in
targets.txt, 2 passes a side. Control at main, treatment on branch
prompt/stride-attacker-positions. Spend stops before a batch that could pass
$2.85 of the $3 the user granted.

Rule, declared now:
- supported: over 28 trials a side, the treatment matches at least 4 more
  target references than control, and its matches of the other must-finds in
  the same lanes fall by no more than 2;
- refuted: the treatment matches 1 or fewer more target references;
- inconclusive: anything else, or fewer than 20 trials a side finish.
