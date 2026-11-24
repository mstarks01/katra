# Code decides first

A model gives a different answer on a different run, costs money and time, and
can pass a check without doing it. Code gives one answer every time, and it
raises when it cannot decide. So code makes each decision that a fixed rule can
make, and a model makes only the decisions that need judgement.

## Sort each decision

When you design or change a node, a prompt or a check, list its decisions and
put each one in one of two groups.

| Code decides | A model decides |
| --- | --- |
| An ID resolves to an element, or it does not. | Whether the evidence supports an argument. |
| A value is in a closed set. | Whether two differently worded claims are one finding. |
| A quote occurs in the source. | How severe a threat is. |
| A verdict follows from the critic's answers. | Which check a draft fails. |
| A schema, a count, a lookup, an assembly. | What a source means where its words are not exact. |

Put the first group in code around the model call: a validator, a function
node before or after it, or a lint. Write the prompt for the second group only.

## Render a closed set; never ask a model to compose a member

Where a prompt asks for a reference into a set that code knows, render the set
as a table to copy from. A model that composes an ID produces a well-formed
value that resolves to nothing. A prompt sentence such as "it must be present
in the model" does not stop that; a rendered table does.

## A constraint with no mechanism is not a rule

A prompt that restates a rule which code could enforce leaves the rule
unenforced. If code knows the legal answer, enforce it in code. Keep the
sentence in the prompt only where it helps the model, never as the
enforcement.

## Move a decision when you find one

A decision that a model makes today and code could make is a defect, whatever
other work is open. Move it into code, and add a test through the production
function that holds the rule. A decision that needs judgement stays with the
model, and code checks the shape of its answer.

Examples here: the **Verdict**, which code sets from the critic's answers; the
quote check before the critic; the assertion layer (ADR 0042); and the
**Candidate** rules, which fire on structure alone.
