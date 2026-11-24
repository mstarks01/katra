"""The baseline manifest of QA-2026-11-24-01: what the 2026-10-24 sweep ran on.

Usage::

    python manifest.py <run dir> <out file>

The script reads every case artifact of ``<run dir>`` and writes one JSON
manifest. It refuses a sweep whose artifacts disagree on an identity, because
such a sweep is not one baseline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: The version of this manifest's shape.
MANIFEST_VERSION = 1

#: The artifact fields that must agree across the cases of one baseline.
SHARED = (
    "artifact_version",
    "mode",
    "frameworks",
    "repo_commit",
    "corpus_digest",
    "flow_identity_version",
    "models",
    "gating",
)


def identity(artifact):
    """The fields of one artifact that make it part of one baseline."""
    provenance = artifact["provenance"]
    return {
        **{field: artifact[field] for field in SHARED},
        "build": provenance["build"],
        "sampling_config_version": provenance["sampling_config_version"],
        "sampling": provenance["sampling"],
        "instruction": {
            entry["node"]: entry["sha256"] for entry in artifact["instruction"]
        },
    }


def main(run_dir, out):
    paths = sorted(run_dir.glob("[0-9]*.json"))
    artifacts = {
        path.stem: json.loads(path.read_text(encoding="utf-8")) for path in paths
    }
    identities = {case: identity(artifact) for case, artifact in artifacts.items()}
    first = next(iter(identities.values()))
    differing = sorted(case for case, value in identities.items() if value != first)
    if differing:
        raise SystemExit(f"the cases disagree on an identity: {differing}")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "run": run_dir.name,
        "cases": sorted(artifacts),
        "trusted": sorted({artifact["trusted"] for artifact in artifacts.values()}),
        **first,
    }
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(artifacts)} cases agree; manifest written to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
