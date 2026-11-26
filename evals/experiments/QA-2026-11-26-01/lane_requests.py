"""Hash every lane request today's prepare builds, for each development case.

Run from a checkout with PYTHONPATH=<checkout>/src:<checkout>. Prints one JSON
line per (case, framework, catalog arm, lane): the sha256 of the instruction
and of the user turn, and their lengths in characters.
"""

import asyncio
import hashlib
import json
import sys

from evals.harness.lane_replay import compose, prepare_today
from evals.harness.provenance import REPO_ROOT
from evals.harness.reference import DEFAULT_CORPUS, development_cases, load_corpus
from evals.reference_facts import facts_path
from katra.frameworks import PACKAGES
from katra.markdown_loader import MarkdownLoader


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


async def main(arms):
    prompts = MarkdownLoader(REPO_ROOT / "prompts")
    for case in development_cases(load_corpus(REPO_ROOT / DEFAULT_CORPUS)):
        for framework in sorted(PACKAGES):
            if framework not in case.frameworks:
                continue
            package = MarkdownLoader(REPO_ROOT / "frameworks" / framework)
            for arm in arms:
                signed = facts_path(REPO_ROOT / DEFAULT_CORPUS / case.id)
                if arm == "signed" and not signed.exists():
                    continue
                material = prepare_today(case, framework, arm).material
                for lane in PACKAGES[framework].lanes:
                    instruction, turn = await compose(
                        material, framework, lane, package, prompts
                    )
                    text = "\n".join(part.text or "" for part in turn.parts or [])
                    print(
                        json.dumps(
                            {
                                "case": case.id,
                                "framework": framework,
                                "arm": arm,
                                "lane": lane,
                                "instruction": digest(instruction),
                                "turn": digest(text),
                                "instruction_chars": len(instruction),
                                "turn_chars": len(text),
                            }
                        )
                    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
