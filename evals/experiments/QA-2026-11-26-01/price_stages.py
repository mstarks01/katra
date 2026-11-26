"""Price the two stages of the paired lane replay from the sweep's own tokens.

Usage: PYTHONPATH=. price_stages.py <requests-ctl.jsonl> <requests-trt.jsonl> <sweep dir>

Each control call is priced at the input and output tokens the 2026-10-24 sweep
recorded for that lane and case. The treatment's input is the control's, scaled
by the characters its request adds, at the characters per token of that
control request against the sweep's tokens. The treatment's output is priced at
1.5 times the sweep's, the design's cap on proposals. Sonnet 5 at $2 input and
$10 output per million tokens, the rates the harness priced the sweep at.
"""

import json
import sys
from pathlib import Path

from evals.harness.descendants import FRAMEWORK

IN, OUT = 2e-6, 1e-5
STAGES = {
    "stage 1": [
        ("02-iot-fleet-telemetry", "tampering", "target 02/3's present draft"),
        ("03-batch-data-pipeline", "information-disclosure", "target 03/8"),
        ("03-batch-data-pipeline", "tampering", "control 03/3"),
        ("06-cookbook-online-game", "tampering", "target 06/3; control 06/4"),
        ("09-cookbook-sokify-retail", "tampering", "target 09/4"),
        ("09-cookbook-sokify-retail", "information-disclosure", "control 09/13"),
        ("10-cookbook-generic-cms", "tampering", "target 10/17; control 10/4"),
        ("13-dispatch-control-plane", "information-disclosure", "target 13/19"),
    ],
    "stage 2": [
        ("04-ml-inference-service", "tampering", "control 04/3"),
        ("04-ml-inference-service", "information-disclosure", "control 04/8"),
        ("07-cicd-store-deploy", "tampering", "control 07/6"),
        ("07-cicd-store-deploy", "information-disclosure", "control 07/12"),
        ("08-sso-identity-broker", "tampering", "control 08/4"),
        ("08-sso-identity-broker", "information-disclosure", "control 08/10"),
        ("11-sparse-shift-scheduling", "tampering", "control 11/4"),
        ("12-overclaiming-supplier-portal", "tampering", "control 12/3"),
    ],
}


def load(path):
    rows = map(json.loads, Path(path).read_text(encoding="utf-8").splitlines())
    return {
        (r["case"], r["lane"]): r
        for r in rows
        if r["framework"] == FRAMEWORK and r["arm"] == "signed"
    }


def main():
    control, treatment = load(sys.argv[1]), load(sys.argv[2])
    for stage, pairs in STAGES.items():
        total_control = total_treatment = 0.0
        print(stage)
        for case, lane, reason in pairs:
            artifact = json.loads(
                Path(sys.argv[3], f"{case}.json").read_text(encoding="utf-8")
            )
            usage = artifact["node_usage"][
                f"analyze_{FRAMEWORK}_" + lane.replace("-", "_")
            ]
            a, b = control[(case, lane)], treatment[(case, lane)]
            chars_control = a["instruction_chars"] + a["turn_chars"]
            chars_treatment = b["instruction_chars"] + b["turn_chars"]
            ratio = chars_control / usage["prompt_tokens"]
            tokens_in = round(chars_treatment / ratio)
            cost_control = (
                usage["prompt_tokens"] * IN + usage["completion_tokens"] * OUT
            )
            cost_treatment = tokens_in * IN + 1.5 * usage["completion_tokens"] * OUT
            total_control += cost_control
            total_treatment += cost_treatment
            print(
                f"  {case[:2]} {lane:23} {reason:30} in {usage['prompt_tokens']}"
                f" -> {tokens_in} (+{tokens_in - usage['prompt_tokens']}),"
                f" out {usage['completion_tokens']}, ${cost_control:.3f} / ${cost_treatment:.3f}"
            )
        one = total_control + total_treatment
        print(f"  one pass of both arms ${one:.2f}; three passes ${3 * one:.2f}")


if __name__ == "__main__":
    main()
