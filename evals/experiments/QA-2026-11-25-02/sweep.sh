#!/bin/bash
# Five extraction sweeps of the corpus for one arm, one after another.
# usage: sweep.sh ARM WORKTREE, run from the repository root.
# Arm A is 2c29ad31, arm B is 294bee59, arm C is 142d9807.
arm=$1
wt=$2
out=${OUT:-$PWD/evals/runs/20261125T-qa-2026-11-25-02}
mkdir -p "$out"
cd "$wt" || exit 1
# The OpenRouter tier routes have no price, so no estimate exists. The sweeps ran
# with --accept-cost unknown, which sets no cap; read the charge from node_charges.
for r in 1 2 3 4 5; do
  KATRA_TIERS_FILE=$HOME/.config/katra/model_tiers.toml PYTHONPATH=$wt/src:$wt \
    uv run --frozen --no-sync python -m evals.harness.run run --mode extraction \
    --cases-in-flight 3 --accept-cost unknown \
    --out "$out/$arm-r$r.json" > "$out/$arm-r$r.log" 2>&1
  echo "$arm r$r exit $?"
done
