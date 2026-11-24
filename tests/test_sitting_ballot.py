"""A CSV sitting ballot: written with plants, read back with the plants apart."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from evals.harness import run
from evals.harness.near_misses import read_rows
from evals.harness.sitting import prepare
from evals.harness.sitting_ballot import CLAIM_JOIN, COLUMNS, BallotError, read, write

CASE = Path(__file__).resolve().parents[1] / "evals" / "corpus" / "01-payments-checkout"


@pytest.fixture
def case_dir(tmp_path):
    target = tmp_path / CASE.name
    shutil.copytree(CASE, target)
    return target


def _fill(ballot: Path, key: Path, plant_mark: str = "reject") -> list[dict[str, str]]:
    """Mark each finding ``agree`` and each plant ``plant_mark``."""
    kinds = {
        int(n): row["kind"] for n, row in json.loads(key.read_text())["rows"].items()
    }
    rows = read_rows(ballot)
    for row in rows:
        row["mark"] = plant_mark if kinds[int(row["row"])] == "plant" else "agree"
    _save(ballot, rows)
    return rows


def _save(path: Path, rows: list[dict[str, str]]) -> None:
    """Write ``rows`` back as a spreadsheet app saves a ballot."""
    lines = [COLUMNS, *(tuple(row.values()) for row in rows)]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(lines)


@pytest.fixture
def ballot(case_dir, tmp_path):
    csv_path, key_path = tmp_path / "ballot.csv", tmp_path / "key.json"
    write(case_dir, csv_path, key_path, plants=True)
    return csv_path, key_path


def test_a_round_trip_gives_the_real_marks_and_the_plant_marks_apart(case_dir, ballot):
    csv_path, key_path = ballot
    assert tuple(read_rows(csv_path)[0]) == COLUMNS
    _fill(csv_path, key_path)
    reading = read(case_dir, csv_path, key_path)
    key = json.loads(key_path.read_text())
    plant_keys = {row["key"] for row in key["rows"].values() if row["kind"] == "plant"}
    assert len(plant_keys) == 3
    assert reading.plants_mixed
    assert reading.plants == dict.fromkeys(plant_keys, "reject")
    assert not plant_keys & set(reading.marks)
    assert set(reading.marks.values()) == {"agree"}
    assert len(reading.marks) + len(plant_keys) == len(key["rows"])


def test_a_blank_plant_reads_as_unmarked_and_a_capital_letter_is_allowed(
    case_dir, ballot
):
    csv_path, key_path = ballot
    rows = _fill(csv_path, key_path, plant_mark="")
    for row in rows:
        row["mark"] = row["mark"].capitalize()
    _save(csv_path, rows)
    reading = read(case_dir, csv_path, key_path)
    assert set(reading.plants.values()) == {None}


def test_no_plants_writes_the_recorded_findings_only(case_dir, tmp_path):
    csv_path, key_path = tmp_path / "ballot.csv", tmp_path / "key.json"
    key = write(case_dir, csv_path, key_path, plants=False)
    assert not key.plants_mixed
    assert {row.kind for row in key.rows.values()} == {"finding"}
    _fill(csv_path, key_path)
    reading = read(case_dir, csv_path, key_path)
    assert reading.plants == {}
    assert not reading.plants_mixed


def test_each_finding_shows_every_claim_it_covers_in_one_cell(case_dir, ballot):
    csv_path, key_path = ballot
    key = json.loads(key_path.read_text())
    cells = {
        key["rows"][row["row"]]["key"]: row["claim"] for row in read_rows(csv_path)
    }
    for target in prepare(case_dir).mark_targets:
        assert cells[target.fingerprint] == CLAIM_JOIN.join(target.claims)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda rows: rows[0].update(claim=rows[0]["claim"] + " Also."), "claim cell"),
        (lambda rows: rows.pop(), "does not hold these rows"),
        (lambda rows: rows.append({**rows[0], "row": "999"}), "row 999"),
        (lambda rows: rows.append(dict(rows[0])), "twice"),
        (lambda rows: rows[0].update(mark="maybe"), "is not one of"),
        (lambda rows: rows[0].update(row="one"), "not a number"),
    ],
    ids=[
        "changed-claim",
        "missing-row",
        "extra-row",
        "repeated-row",
        "unknown-mark",
        "bad-number",
    ],
)
def test_a_changed_ballot_is_refused_by_row(case_dir, ballot, change, message):
    csv_path, key_path = ballot
    rows = _fill(csv_path, key_path)
    change(rows)
    _save(csv_path, rows)
    with pytest.raises(BallotError, match=message):
        read(case_dir, csv_path, key_path)


def test_an_unmarked_finding_is_refused_by_row(case_dir, ballot):
    csv_path, key_path = ballot
    rows = _fill(csv_path, key_path)
    finding = next(row for row in rows if row["mark"] == "agree")
    finding["mark"] = ""
    _save(csv_path, rows)
    with pytest.raises(BallotError, match=f"row {finding['row']}: "):
        read(case_dir, csv_path, key_path)


def test_a_case_that_moved_after_the_ballot_is_refused(case_dir, ballot):
    csv_path, key_path = ballot
    _fill(csv_path, key_path)
    source = case_dir / "source.md"
    source.write_text(source.read_text() + "\nOne more line.\n")
    with pytest.raises(BallotError, match="source.md"):
        read(case_dir, csv_path, key_path)


def test_the_two_commands_write_the_ballot_and_read_it_back(case_dir, tmp_path, capsys):
    csv_path, key_path, out = (
        tmp_path / "b.csv",
        tmp_path / "k.json",
        tmp_path / "m.json",
    )
    assert (
        run.main(
            [
                "sitting-ballot",
                str(case_dir),
                "--out",
                str(csv_path),
                "--key",
                str(key_path),
            ]
        )
        == 0
    )
    _fill(csv_path, key_path, plant_mark="agree")
    assert (
        run.main(
            [
                "sitting-ballot-read",
                str(case_dir),
                str(csv_path),
                "--key",
                str(key_path),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert "3 plant(s): 0 reject, 3 agree, 0 other or blank" in capsys.readouterr().out
    written = json.loads(out.read_text())
    assert set(written) == {"marks", "plants", "plants_mixed"}
    assert written["plants_mixed"] is True
