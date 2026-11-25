#!/bin/bash
# Four more spoofing lane replays on case 01 for each arm of -E3.
# usage: lane_more.sh BEFORE_WORKTREE AFTER_WORKTREE, run from the repository root.
before_wt=$1
after_wt=$2
O=${OUT:-$PWD/evals/runs/20261125T-qa-2026-11-25-02}/2307
mkdir -p "$O"
for i in 5 6 7 8; do
  for arm in before after; do
    wt=$before_wt
    [ "$arm" = after ] && wt=$after_wt
    (cd "$wt" && KATRA_TIERS_FILE=$HOME/.config/katra/model_tiers.toml PYTHONPATH=$wt/src:$wt \
      uv run --frozen --no-sync python -m evals.harness.run \
      lane-replay --case 01-payments-checkout --framework stride --lane spoofing \
      --prepare-today signed --accept-cost 0.20 --out "$O/$arm-lane-$i.json" > "$O/$arm-lane-$i.log" 2>&1)
    echo "$arm lane-$i exit $?"
  done
done
