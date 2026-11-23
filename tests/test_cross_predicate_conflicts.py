"""Rows of two predicates that state opposite states (#2307 N2).

The maintainer's ruling of 2026-11-23: a stated table of predicate pairs,
``assertions.CROSS_CONFLICTS``. Two source rows of a pair are both open
questions; an answer row settles its fact, and the source row it disagrees
with goes.
"""

from __future__ import annotations

from katra.assertions import (
    ABSENT,
    AssertionCatalog,
    Qualifier,
    assertion_id,
    conflicts,
    disputed,
    settled,
)
from katra.evidence import prepared_view
from katra.fact_answers import FactAnswer
from katra.links import apply_answers
from tests.factories import valid_model
from tests.test_contradicted_answers import CREDENTIAL, LOGIN, MECHANISM, SUBJECTS
from tests.test_part_rows import kind_answer

NO_AUTHENTICATION = MECHANISM.model_copy(
    update={"value": ABSENT, "explanation": "the call carries no credential"}
)
MFA = MECHANISM.model_copy(
    update={
        "predicate": "mfa-requirement",
        "value": "required",
        "explanation": "the sign-in asks for two factors",
    }
)
VALIDATED = MECHANISM.model_copy(
    update={
        "predicate": "content-validation",
        "value": "validated",
        "explanation": "the API checks each body against a schema",
    }
)


def catalog(*rows):
    return AssertionCatalog(subjects=SUBJECTS, entries=list(rows))


def ids(rows):
    return {assertion_id(row) for row in rows}


def part(value):
    return MECHANISM.model_copy(
        update={
            "predicate": "content-validation-validates",
            "value": value,
            "explanation": "the notes say how input is checked",
        }
    )


class TestTwoSourceRows:
    def test_no_authentication_beside_a_presented_credential(self):
        held = catalog(NO_AUTHENTICATION, CREDENTIAL)

        assert {(c.predicate, c.values) for c in conflicts(held)} == {
            ("authentication-mechanism", (ABSENT, "credential:client-cert")),
            ("credential-presented", (ABSENT, "credential:client-cert")),
        }
        assert ids(disputed(held)) == ids([NO_AUTHENTICATION, CREDENTIAL])
        assert settled(held) == ()

    def test_no_authentication_beside_a_second_factor(self):
        held = catalog(NO_AUTHENTICATION, MFA)

        assert ids(disputed(held)) == ids([NO_AUTHENTICATION, MFA])

    def test_a_validated_body_beside_a_part_that_says_no(self):
        held = catalog(VALIDATED, part("no"))

        assert ids(disputed(held)) == ids([VALIDATED, part("no")])

    def test_the_pair_holds_the_other_way_round(self):
        held = catalog(VALIDATED.model_copy(update={"value": ABSENT}), part("yes"))

        assert len(disputed(held)) == 2

    def test_the_lanes_read_no_stated_absence(self):
        """Through the model the lanes read: the field is a question, never
        the absence one side states."""
        for partner in (CREDENTIAL, MFA):
            _, _, offered = prepared_view(
                valid_model(), catalog(NO_AUTHENTICATION, partner)
            )

            assert f"absent:{LOGIN}:authentication" not in offered
            assert offered[f"unknown:{LOGIN}:authentication"].kind == (
                "unknown-attribute"
            )

    def test_the_second_factor_is_offered_as_a_question(self):
        _, _, offered = prepared_view(valid_model(), catalog(NO_AUTHENTICATION, MFA))

        assert offered[assertion_id(MFA)].kind == "unknown-assertion"


class TestNoConflict:
    def test_a_mechanism_beside_no_credential(self):
        """One-way: a mechanism such as an address allowlist presents none."""
        held = catalog(MECHANISM, CREDENTIAL.model_copy(update={"value": ABSENT}))

        assert conflicts(held) == ()

    def test_not_applicable_beside_no_validation(self):
        held = catalog(
            VALIDATED.model_copy(update={"value": ABSENT}), part("not applicable")
        )

        assert conflicts(held) == ()

    def test_two_scopes(self):
        backups = [Qualifier(kind="resource", value="backups")]
        held = catalog(
            NO_AUTHENTICATION, CREDENTIAL.model_copy(update={"scope": backups})
        )

        assert conflicts(held) == ()

    def test_a_row_a_reviewer_set_aside(self):
        held = catalog(
            NO_AUTHENTICATION,
            CREDENTIAL.model_copy(update={"assessment": "unsupported"}),
        )

        assert conflicts(held) == ()

    def test_a_pair_the_table_does_not_name(self):
        held = catalog(VALIDATED.model_copy(update={"value": ABSENT}), MFA)

        assert conflicts(held) == ()


def test_an_attribute_answer_settles_against_the_paired_source_row():
    """The attribute step writes an absent mechanism row beside a scoped one;
    the second factor the sources stated disagrees with it and goes."""
    scoped = MECHANISM.model_copy(
        update={"scope": [Qualifier(kind="resource", value="backups")]}
    )
    answer = FactAnswer(key=(LOGIN, "authentication", "", "", "", ""), value="none")

    written, issues = apply_answers(catalog(scoped, MFA), valid_model(), [], [answer])

    assert disputed(written) == ()
    assert assertion_id(MFA) in {
        issue.assertion for issue in issues if issue.code == "superseded-by-answer"
    }


def test_an_answer_settles_its_fact_and_the_source_row_goes():
    """The part answer says no; the extracted row said validated."""
    answer = kind_answer(LOGIN, "content-validation", validates="no")

    written, issues = apply_answers(catalog(VALIDATED), valid_model(), [], [answer])

    assert VALIDATED not in written.entries
    assert assertion_id(VALIDATED) in {
        issue.assertion for issue in issues if issue.code == "superseded-by-answer"
    }
    (row,) = [entry for entry in written.entries if entry.origin == "answer"]
    assert (row.predicate, row.value) == ("content-validation-validates", "no")
    assert row in settled(written)
