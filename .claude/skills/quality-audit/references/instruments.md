# Instruments

Every reading available to an audit, what it answers, and what it costs.
`tests/test_doc_command_lints.py` checks that each subcommand here exists and
that each flag beside it is one the subcommand accepts. It does not check the
positional arguments, their order or a required flag, so read a command's
`--help` before you trust its shape.

Run everything from the repository root, under `uv run`.

## Free, and where an audit starts

| Command | Answers |
| --- | --- |
| `python -m evals.harness.run score <artifact>` | re-scores a finished sweep against the corpus and the vote ledger, and writes the loss-attribution blocks |
| `python -m evals.harness.run replay <artifacts>` | re-scores archived extraction and assertion emissions under today's code, giving every reference element one fate |
| `python -m evals.harness.run bind <proposals> --graphs <artifacts>` | binds archived assertion proposals to archived graphs and names every binding the graphs refuse |
| `python -m evals.harness.run assembly <artifact>` | assembles every archived block again from its drafts and the rulings its report carries, and names any ruled draft the report omits |
| `python -m evals.harness.run descendants <artifact>` | runs the fan-in again over a sweep's archived proposals, with `--inject` proposals added, and bounds what the critic would keep |
| `python -m evals.harness.run stability <artifacts>` | the run-to-run band, from sweeps already paid for |
| `python -m evals.harness.run compare <before> <after>` | what a prompt edit did: the instruction delta beside the score delta |
| `python -m evals.harness.run price-verbs` | prices a verb equivalence on the frontier, with no run at all |
| `python -m evals.harness.run extraction-losses <end-to-end> <analysis>` | what an end-to-end run lost before its lanes ran, against an analysis-mode run of the same corpus |
| `python -m evals.harness.run pairing <artifact> --case <case>` | the two sides of one case's applicability disagreement |
| `python -m evals.harness.run calibrate` | how far the identity rule agrees with the calibration labels |
| `python -m evals.harness.run review --voter <login> <artifacts>` | what a reviewer has waiting over a finished sweep |
| `python -m evals.harness.run near-misses <artifact> --out ballot.csv` | the missed must-finds a free same-lane draft may state with another verb or place, as a ballot a person answers; `near-miss-rulings` records the answers in `rulings.json` |
| `python -m evals.harness.run gain <baseline> <candidate> --framework <name> --spread spread.json` | whether a coverage gain rests on supported output: unmatched volume, findings no live vote answers, and rejected rate, on development cases |
| `python -m evals.harness.run gain <baseline> <candidate> --framework <name> --held-out` | rung 5, held-out confirmation: the same gates on the held-out cases alone. It costs no money but uses one read of each held-out case, refuses an exhausted case, and names each case to record in `holdout_reads` |
| `python -m evals.harness.run experiments` | what a prior audit already tested, and whether the tree moved under it |
| `python -m evals.harness.run phases` | the six phases and the graph nodes each owns; `--node` answers for one node |
| `python evals/verify_corpus.py` | the corpus lint: what each case holds, how much of it is unsigned, and whether a verified input carries a reference answer |
| `pytest -q` | every offline gate, including the neutrality, licence and prose lints |

## The archives these read

| Directory | What it holds |
| --- | --- |
| `evals/runs/` | every sweep artifact, each with its `.reports/` directory beside it |
| `evals/emissions/` | what `extract` emitted and what `assert` proposed, per paid sweep |
| `evals/baselines/` | merged Baselines, digest-sealed; score one to a copy, never in place |
| `evals/corpus/` | the golden cases, their reference sets and their signed facts |
| `evals/review/votes/` | the vote ledger: the only human judgements in the tree |
| `evals/experiments/` | the experiment ledger this skill writes |

`evals/baselines/README.md` is generated. Rows compare only inside one commit
and corpus-digest group, and `evals/README.md` says what every figure does not
mean.

## Paid, and only on explicit permission

`python -m evals.harness.run run --mode <mode>` is the sweep command, and it
needs provider credentials. It states its own cost estimate and holds the
operator to what they accept; see `evals/harness/consent.py` and
`evals/TUNING.md`.

`python -m evals.harness.run lane-replay <artifact> --case <case> --framework <package> --lane <lane> --accept-cost <usd>`
costs one lane call. `python -m evals.harness.run critic-replay <artifact> --case <case> --framework <package> --accept-cost <usd>`
costs one critic call, compares each draft's verdict with the archived one, and counts a draft with no archived verdict on its own line. Pass `--out <file>` to keep the rulings, because a status says what moved and not why. It rebuilds the request one lane made from the sweep's
`<case>.lanes.json` and sends it again, so a `place` loss can be read against
what the lane was shown. The material is the run's and the prompt files are
this checkout's, and the command prints both commits. To compare a lane with and without the assertion catalog, use
`lane-replay --case <case> --framework stride --lane <lane> --prepare-today none|signed --accept-cost <usd>`
with no artifact: it runs today's `prepare` offline, so the two arms differ only in the
catalog, and it prints the must-finds the lane's drafts match. Add
`--system-model <file>` to put a System Model file in place of the case's
blessed model: the file passes the live validity gate, and it holds the blessed model's
element IDs.

Each replay reads `--accept-cost` through the consent gate: pass the dollars
you accept, or `unknown` to accept a cost nobody states. On a priced route,
or on a route that reports its charge, the amount caps the run. A one-call
replay runs its call with no bound. To send many lane calls under one cap, use
`lane-replay --framework <package> --plan <file> --out <folder> --accept-cost <usd>`:
each line of the file is a JSON object with `case`, `lane` and `prepare_today`.
The hold runs before each call and stops before a call that can pass the cap.
Each output file records the call's binding, route, sampling and token usage.

`python -m evals.harness.run recritic-replay <artifact> --case <case> --framework <package> --faults <file> --draft <id> --fault <shape> --accept-cost <usd>`
costs one re-ask call. It reads the case's critic first pass from its report,
applies the one Control the fault set holds, answers each row it shows with the
refusal the file states, and puts one fault of the shape on the draft.
`FaultShape` in `evals/harness/recritic_replay.py` lists the shapes: Control
row faults, and at least one shape for each other kind of problem the check
names. The round's check must name exactly the problems `PROBLEMS_BY_SHAPE`
gives the shape, or the command refuses the view before the call. With `--out
<file>` it writes the problems the re-ask was sent, its answer, the problems
that remain and each ruling it changed that no problem named.

`python -m evals.harness.run judge-replay <artifact> --out <file> --judge <vendor>/<model> --accept-cost <amount>`
costs one judge call for each case and sample (two samples by default). The
judge, on the model that `--judge` names, reads each case's STRIDE findings, mixed with
**Plant**s as known negatives, and answers whether the source supports each
one. The command refuses a judge whose model comes from the source vendor of a
model that wrote the sweep. The source vendor is the company that made the
model, so a judge or a writer through `openrouter` is read by its slug. The
test runs on the Baseline `d4edd64-gpt-5.6-terra-fd1c49af`, whose tiers ran
OpenAI models: its dry run estimates $2.08 to $2.10 for 26 calls on `anthropic/claude-opus-5`. The
figure moves because case 01 has four plant candidates and each run chooses two
or three of them at random. A judge through `openrouter` has no price: its
estimate is `charged`, and `--accept-cost <amount>` caps the run on the charge
that OpenRouter reports after each call. Before each call it runs the sweep's
hold, `consent.hold`. The hold stops when the spend so far plus the dearest call
so far passes the accepted amount. The first call runs with no bound. A
call on a route with no price that reports no charge stops the run, and a
call that reports no usage counts at its estimate. It keeps each answer as
it arrives. Its verdicts never enter the vote ledger. With
`--dry-run` in place of `--accept-cost` it is free: it writes every request
and prints the estimate and the batch sizes, and sends nothing.

The four replays send a live request, so `KATRA_OFFLINE` refuses them. Only
`judge-replay --dry-run` sends none. Their names say "replay"; their cost says
paid. `replay` and `score` above re-read an
archive and are free.

Narrow it as far as the question allows: `--case` for one case, `--framework`
to narrow to one package. The cases and the repeats come from the design of the
question in `references/experiment-protocol.md`, not from a fixed count. A
corpus sweep is for a batch of must-find fixes whose combined ceiling clears
the band, or for a question only the whole corpus can answer.

## What has no instrument today

Name these as blockers when an audit needs one, rather than approximating them:

- **Report prose.** The claim scorer reads structured claims. A report whose
  prose contradicts its own claims scores the same.
- **Entailment.** Evidence validation proves shape and quotation, not that the
  quote supports the claim.
- **Blind comparison against a human analyst.** No holdout of that kind exists.
  Corpus recall cannot stand in for it.
- **Reviewed precision.** The rejected rate and the writing objections both
  need votes, and most Baselines have none.

Each of these is a real gap with an open issue behind it. Check the tracker
before writing a new extension ticket for one.
