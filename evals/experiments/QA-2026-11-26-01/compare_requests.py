"""Compare the lane requests of the control and the treatment.

Usage: compare_requests.py <requests-ctl.jsonl> <requests-trt.jsonl>
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(path):
    rows = map(json.loads, Path(path).read_text(encoding="utf-8").splitlines())
    return {(r["case"], r["framework"], r["arm"], r["lane"]): r for r in rows}


control, treatment = load(sys.argv[1]), load(sys.argv[2])
assert control.keys() == treatment.keys()
same: Counter[tuple[str, str]] = Counter()
changed: defaultdict[tuple[str, str], list] = defaultdict(list)
for key in sorted(control):
    a, b = control[key], treatment[key]
    group = (key[1], key[3])
    if a["instruction"] == b["instruction"] and a["turn"] == b["turn"]:
        same[group] += 1
    else:
        changed[group].append((a, b))
print(f"requests: {len(control)}, cases: {len({key[0] for key in control})}")
print("identical (framework, lane): requests")
for group, count in sorted(same.items()):
    print(f"  {group}: {count}")
print(
    "changed (framework, lane): requests, instructions changed, turns changed, characters added"
)
for group, pairs in sorted(changed.items()):
    added = [b["instruction_chars"] - a["instruction_chars"] for a, b in pairs]
    print(
        f"  {group}: {len(pairs)}, {sum(a['instruction'] != b['instruction'] for a, b in pairs)},"
        f" {sum(a['turn'] != b['turn'] for a, b in pairs)}, {min(added)} to {max(added)}"
    )
