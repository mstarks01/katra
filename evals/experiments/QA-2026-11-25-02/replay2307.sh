#!/bin/bash
# The #2307 harm check of -E3: lane, critic and re-ask replays on each arm.
# usage: replay2307.sh BEFORE_WORKTREE AFTER_WORKTREE, run from the repository root.
# The before worktree is at 294bee59, the after worktree at 59f2ea6a.
# before-lane-1 ran on its own before this script, with the same command.
before_wt=$1
after_wt=$2
O=${OUT:-$PWD/evals/runs/20261125T-qa-2026-11-25-02}/2307
ART=$PWD/evals/runs/20261024T-sonnet-medium-sweep/05-cookbook-queue-webapp.json
mkdir -p "$O"
run() {
  arm=$1
  name=$2
  shift 2
  wt=$before_wt
  [ "$arm" = after ] && wt=$after_wt
  (cd "$wt" && KATRA_TIERS_FILE=$HOME/.config/katra/model_tiers.toml PYTHONPATH=$wt/src:$wt \
    uv run --frozen --no-sync python -m evals.harness.run "$@" > "$O/$arm-$name.log" 2>&1)
  echo "$arm $name exit $?"
}
for i in 1 2 3 4; do
  [ $i -gt 1 ] && run before lane-$i lane-replay --case 01-payments-checkout --framework stride \
    --lane spoofing --prepare-today signed --accept-cost 0.20 --out "$O/before-lane-$i.json"
  run after lane-$i lane-replay --case 01-payments-checkout --framework stride \
    --lane spoofing --prepare-today signed --accept-cost 0.20 --out "$O/after-lane-$i.json"
done
for i in 1 2 3; do
  for arm in before after; do
    run $arm critic-$i critic-replay "$ART" --case 05-cookbook-queue-webapp --framework stride \
      --accept-cost 0.25 --out "$O/$arm-critic-$i.json"
  done
done
for d in I-02 R-03; do
  for arm in before after; do
    run $arm recritic-$d recritic-replay "$ART" --case 05-cookbook-queue-webapp --framework stride \
      --faults evals/experiments/QA-2026-11-05-02/faults.json --fault dropped --draft $d \
      --accept-cost 0.10 --out "$O/$arm-recritic-$d.json"
  done
done
