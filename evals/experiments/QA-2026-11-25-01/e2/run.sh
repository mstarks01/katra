#!/bin/bash
# The -E2 lane replays: 2 lanes x 2 arms x 3 passes on the changed model of
# case 01, alternating the arms. It stops before a call that could take the
# spend past CAP, a cap in USD.
#
#   run.sh CONTROL_WORKTREE TREATMENT_WORKTREE OUT_DIR CAP
#
# CONTROL_WORKTREE is the row's revision; TREATMENT_WORKTREE is the branch
# qa/QA-2026-11-25-01-E2. KATRA_TIERS_FILE names the tier selection; the
# vendor key comes from the login shell.
set -u
CONTROL=$1 TREATMENT=$2 OUT=$3 CAP=$4
MODEL=$CONTROL/evals/experiments/QA-2026-11-25-01/case01-system-model.json
mkdir -p "$OUT"
spent=0
dearest=0
for pass in 1 2 3; do
  for lane in information-disclosure tampering; do
    for arm in control treatment; do
      out=$OUT/$arm-$lane-$pass.json
      [ -f "$out" ] && continue
      if ! python3 -c "import sys; sys.exit(0 if $spent + 1.5 * $dearest <= $CAP else 1)"; then
        echo "STOP before $arm $lane $pass: spent $spent"; exit 0
      fi
      worktree=$CONTROL; [ "$arm" = treatment ] && worktree=$TREATMENT
      log=$OUT/$arm-$lane-$pass.log
      (cd "$worktree" && PYTHONPATH=src:. uv run --no-sync python -m evals.harness.run lane-replay \
        --case 01-payments-checkout --framework stride --lane "$lane" \
        --prepare-today signed --system-model "$MODEL" --accept-cost unknown \
        --out "$out") > "$log" 2>&1
      cost=$(grep -o 'spent: \$[0-9.]*' "$log" | grep -o '[0-9.]*$')
      [ -z "$cost" ] && { echo "NO COST in $log"; tail -5 "$log"; exit 1; }
      spent=$(python3 -c "print(round($spent + $cost, 4))")
      dearest=$(python3 -c "print(max($dearest, $cost))")
      echo "$arm $lane $pass: \$$cost, total \$$spent"
    done
  done
done
echo "DONE total \$$spent"
