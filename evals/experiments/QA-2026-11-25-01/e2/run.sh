#!/bin/bash
# Run the remaining QA-2026-11-25-01-E2 lane replays; stop before the cap.
S=/tmp/claude-1000/-home-me-katra/2eed979a-0c7c-453b-8f10-f662ac48aac3/scratchpad
export KATRA_TIERS_FILE=$HOME/.config/katra/model_tiers.toml
MODEL=evals/experiments/QA-2026-11-25-01/case01-system-model.json
spent=0.0549
dearest=0.0549
for pass in 1 2 3; do
  for lane in information-disclosure tampering; do
    for arm in control treatment; do
      out=$S/runs-e2/$arm-$lane-$pass.json
      [ -f "$out" ] && continue
      if python3 -c "import sys; sys.exit(0 if $spent + 1.5 * $dearest <= 1.00 else 1)"; then :; else
        echo "STOP before $arm $lane $pass: spent $spent"; exit 0
      fi
      wt=$S/wt-ctl; [ $arm = treatment ] && wt=$S/wt-trt
      log=$S/runs-e2/$arm-$lane-$pass.log
      (cd $wt && PYTHONPATH=src:. timeout 900 /home/me/katra/.venv/bin/python -m evals.harness.run lane-replay \
        --case 01-payments-checkout --framework stride --lane $lane --prepare-today signed \
        --system-model $S/wt-ctl/$MODEL --accept-cost unknown --out $out) > $log 2>&1
      cost=$(grep -o 'spent: \$[0-9.]*' $log | grep -o '[0-9.]*$')
      [ -z "$cost" ] && { echo "NO COST in $log"; tail -5 $log; exit 1; }
      spent=$(python3 -c "print(round($spent + $cost, 4))")
      dearest=$(python3 -c "print(max($dearest, $cost))")
      echo "$arm $lane $pass: \$$cost, total \$$spent"
    done
  done
done
echo "DONE total \$$spent"
