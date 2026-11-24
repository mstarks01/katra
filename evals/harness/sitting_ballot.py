"""A **Case Sitting** held as a CSV ballot, with plants mixed in.

:func:`write` puts each recorded finding of one case on a CSV row, adds the
case's plants (:mod:`evals.harness.plants`) and shuffles the rows. The reader
fills the ``mark`` column. :func:`read` checks the returned CSV against the key
file and gives the real marks and the plant marks apart, so a plant key never
reaches a submission.

The key file belongs to the operator. It says which row is a plant, so the
reader never sees it.

Nothing here writes a submission. The operator puts the real marks into the
submission, and the shipped checks of :mod:`evals.harness.sitting` refuse the
same marks there that they refuse here.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from evals.harness import sitting
from evals.harness.plants import plants_for
from evals.harness.reference import load_case
from evals.harness.sitting import MARKS, Mark

#: The columns of a ballot, in order. The reader fills ``mark`` only.
COLUMNS = ("row", "framework", "claim", "mark")

#: How one cell shows a finding that several recorded claims share.
CLAIM_JOIN = " | "

#: What a key row stands for: a recorded finding or a plant.
RowKind = Literal["finding", "plant"]


class BallotError(ValueError):
    """The ballot does not read against its key; the message names the row."""


class KeyRow(BaseModel):
    """One ballot row as the operator's key holds it."""

    model_config = ConfigDict(extra="forbid")

    kind: RowKind
    #: The finding's fingerprint, or the plant's key.
    key: str
    framework: str
    claim: str


class BallotKey(BaseModel):
    """The operator's key to one ballot."""

    model_config = ConfigDict(extra="forbid")

    case: str
    plants_mixed: bool
    #: The case's files as the ballot read them, from :attr:`sitting.Prepared.digests`.
    digests: dict[str, str]
    rows: dict[int, KeyRow]


@dataclass(frozen=True)
class BallotReading:
    """The marks of one returned ballot, with the plants apart."""

    #: Fingerprint -> mark, for the recorded findings.
    marks: dict[str, Mark]
    #: Plant key -> mark, or ``None`` where the reader left the cell blank.
    plants: dict[str, Mark | None]
    plants_mixed: bool


def write(case_dir: Path, csv_path: Path, key_path: Path, *, plants: bool) -> BallotKey:
    """Write one case's ballot and its key, and return the key."""
    prepared = sitting.prepare(case_dir)
    rows = [
        KeyRow(
            kind="finding",
            key=target.fingerprint,
            framework=target.framework,
            claim=CLAIM_JOIN.join(target.claims),
        )
        for target in prepared.mark_targets
    ]
    planted = plants_for(load_case(case_dir)) if plants else ()
    rows += [
        KeyRow(
            kind="plant", key=plant.key, framework=plant.framework, claim=plant.claim
        )
        for plant in planted
    ]
    random.SystemRandom().shuffle(rows)
    key = BallotKey(
        case=prepared.case_id,
        plants_mixed=bool(planted),
        digests=prepared.digests,
        rows=dict(enumerate(rows, start=1)),
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for number, row in key.rows.items():
            writer.writerow((number, row.framework, row.claim, ""))
    key_path.write_text(key.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return key


def read(case_dir: Path, csv_path: Path, key_path: Path) -> BallotReading:
    """The marks of a returned ballot, or a refusal that names what is wrong.

    The CSV may come back from a spreadsheet app, so a byte order mark, blank
    space around a cell and a capital letter in a mark are allowed. Each other
    change to a row refuses the whole ballot.
    """
    key = _load_key(key_path)
    if stale := sitting.moved(case_dir, key.digests):
        raise BallotError(
            f"{key.case}: {', '.join(stale)} changed after the ballot was written;"
            " write a new ballot"
        )
    prepared = sitting.prepare(case_dir)
    if prepared.case_id != key.case:
        raise BallotError(
            f"{key_path}: this key is for {key.case}, not {prepared.case_id}"
        )
    marks: dict[str, Mark] = {}
    plants: dict[str, Mark | None] = {}
    for number, mark in _returned_marks(csv_path, key).items():
        row = key.rows[number]
        if row.kind == "plant":
            plants[row.key] = mark
        elif mark is None:
            raise BallotError(f"row {number}: a recorded finding carries no mark")
        else:
            marks[row.key] = mark
    sitting.check_marks(prepared, marks, name=sitting.mark_key)
    sitting.check_every_finding_marked(
        prepared, marks, {target.framework for target in prepared.mark_targets}
    )
    return BallotReading(marks=marks, plants=plants, plants_mixed=key.plants_mixed)


def _load_key(key_path: Path) -> BallotKey:
    try:
        return BallotKey.model_validate_json(key_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise BallotError(f"{key_path}: {sitting.first_problem(exc)}") from exc


def _returned_marks(csv_path: Path, key: BallotKey) -> dict[int, Mark | None]:
    """Row number -> mark, from a CSV whose rows match the key exactly."""
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise BallotError(
                f"{csv_path}: the columns are {reader.fieldnames}, not {list(COLUMNS)}"
            )
        returned: dict[int, Mark | None] = {}
        for cells in reader:
            number = _row_number(cells)
            if number in returned:
                raise BallotError(f"row {number}: the ballot holds this row twice")
            if number not in key.rows:
                raise BallotError(f"row {number}: the key holds no such row")
            row = key.rows[number]
            for column, issued in (("framework", row.framework), ("claim", row.claim)):
                if cells[column].strip() != issued:
                    raise BallotError(f"row {number}: the {column} cell changed")
            returned[number] = _mark(number, cells["mark"])
    if absent := sorted(set(key.rows) - set(returned)):
        raise BallotError(f"rows {absent}: the ballot does not hold these rows")
    return returned


def _row_number(cells: Mapping[str | None, object]) -> int:
    text = cells["row"]
    if None in cells or None in cells.values():
        raise BallotError(f"row {text!r}: the row does not hold one cell per column")
    try:
        return int(str(text).strip())
    except ValueError:
        raise BallotError(f"row {text!r}: the row number is not a number") from None


def _mark(number: int, cell: str) -> Mark | None:
    word = cell.strip().lower()
    if not word:
        return None
    for mark in MARKS:
        if word == mark:
            return mark
    raise BallotError(
        f"row {number}: the mark {cell!r} is not one of {', '.join(MARKS)}"
    )


def plant_result(reading: BallotReading) -> str:
    """One line that says how the reader marked the plants."""
    counts = Counter(reading.plants.values())
    other = len(reading.plants) - counts["reject"] - counts["agree"]
    return (
        f"{len(reading.plants)} plant(s): {counts['reject']} reject,"
        f" {counts['agree']} agree, {other} other or blank"
    )


def command_ballot(args: argparse.Namespace) -> int:
    """``run sitting-ballot <case dir> --out <csv> --key <json>``."""
    try:
        key = write(
            Path(args.case_dir),
            Path(args.out),
            Path(args.key),
            plants=not args.no_plants,
        )
    except ValueError as exc:
        print(f"no ballot was written:\n{exc}")
        return 1
    planted = sum(row.kind == "plant" for row in key.rows.values())
    print(f"{len(key.rows)} row(s) written to {args.out}, the key to {args.key}")
    if args.no_plants:
        print("the ballot carries no plants: --no-plants")
    elif not planted:
        print(
            f"the ballot carries no plants: the {key.case} model states no flow"
            " control that a plant can invert"
        )
    else:
        print(f"{planted} plant(s) mixed in; never show the key to the reader")
    return 0


def ballot_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("case_dir", help="the case directory to hold a sitting of")
    parser.add_argument("--out", required=True, help="where to write the ballot CSV")
    parser.add_argument(
        "--key",
        required=True,
        help="where to write the key file; the reader never sees it",
    )
    parser.add_argument(
        "--no-plants", action="store_true", help="write the recorded findings only"
    )


def command_ballot_read(args: argparse.Namespace) -> int:
    """``run sitting-ballot-read <case dir> <csv> --key <json> --out <json>``."""
    try:
        reading = read(Path(args.case_dir), Path(args.ballot), Path(args.key))
    except ValueError as exc:
        print(f"the ballot was not read:\n{exc}")
        return 1
    result = {
        "marks": reading.marks,
        "plants": reading.plants,
        "plants_mixed": reading.plants_mixed,
    }
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(reading.marks)} mark(s) written to {args.out}")
    print(plant_result(reading))
    return 0


def ballot_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "case_dir", help="the case directory the ballot was written for"
    )
    parser.add_argument("ballot", help="the ballot CSV the reader filled")
    parser.add_argument(
        "--key", required=True, help="the key file the ballot was written with"
    )
    parser.add_argument("--out", required=True, help="where to write the marks JSON")
