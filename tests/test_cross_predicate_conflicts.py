"""Rows of two predicates that state opposite states (#2307 N2).

The maintainer's ruling of 2026-11-23: a stated table of predicate pairs,
``assertions.CROSS_CONFLICTS``. Two source rows of a pair are both open
questions; an answer row settles its fact, and the source row it disagrees
with goes.
"""

from __future__ import annotations

import pytest

from katra.assertions import (
    ABSENT,
    UNKNOWN,
    AssertionCatalog,
    Qualifier,
    assertion_id,
    conflicts,
    disputed,
    place_identity,
    project,
    settled,
    support_span,
)
from katra.evidence import prepared_view
from katra.fact_answers import FactAnswer
from katra.links import apply_answers, check_answers
from katra.sources import ANSWERS_LABEL
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


def test_an_assertion_answer_settles_against_the_paired_source_row():
    """The submitter answers the open mechanism: no authentication. The
    credential the sources named disagrees with it and goes."""
    open_row = MECHANISM.model_copy(update={"value": UNKNOWN, "reason": "silent"})
    place = place_identity(open_row)
    answer = FactAnswer(key=("", "", place, "", "", ""), value=ABSENT)

    written, issues = apply_answers(
        catalog(open_row, CREDENTIAL), valid_model(), [], [answer]
    )

    assert disputed(written) == ()
    assert assertion_id(CREDENTIAL) in {
        issue.assertion for issue in issues if issue.code == "superseded-by-answer"
    }
    (row,) = [entry for entry in written.entries if entry.origin == "answer"]
    assert (row.predicate, row.value) == ("authentication-mechanism", ABSENT)


def test_a_part_answer_writes_nothing_beside_a_paired_source_row():
    """A stated fact stands against a part, as it does for the part's own
    predicate (ADR 0125), so a Control cannot remove it either."""
    answer = kind_answer(LOGIN, "content-validation", validates="no")

    written, _ = apply_answers(catalog(VALIDATED), valid_model(), [], [answer])

    assert [entry.origin for entry in written.entries] == ["assertion-pass"]
    assert ids(settled(written)) == ids([VALIDATED])


def test_a_part_that_agrees_with_an_answer_at_a_disputed_place_is_written():
    """The assertion answer settles the disputed place, so the source row it
    removes is no stated fact the part must stand aside for."""
    absent = VALIDATED.model_copy(update={"value": ABSENT, "explanation": "none"})
    place = FactAnswer(
        key=("", "", place_identity(VALIDATED), "", "", ""), value=ABSENT
    )
    part_no = kind_answer(LOGIN, "content-validation", validates="no")

    written, _ = apply_answers(
        catalog(VALIDATED, absent), valid_model(), [], [place, part_no]
    )

    assert {
        (entry.predicate, entry.value)
        for entry in written.entries
        if entry.origin == "answer"
    } == {("content-validation", ABSENT), ("content-validation-validates", "no")}


def test_an_answer_beside_its_own_disagreeing_row_still_projects():
    """Only a paired predicate's dispute qualifies the field; an answer that
    drives the value over a row of its own predicate projects its value."""
    line = "Login: mutual TLS."
    answer_row = MECHANISM.model_copy(
        update={
            "value": "mutual TLS",
            "basis": "stated",
            "origin": "answer",
            "explanation": "",
            "support": [support_span(line, ANSWERS_LABEL, line)],
        }
    )
    (projection,) = project(catalog(answer_row, NO_AUTHENTICATION))

    assert (projection.value, projection.reason) == ("mutual TLS", "stated")


class TestTwoAnswersThatDisagree:
    """The maintainer's ruling of 2026-11-23: a submission whose answers write
    rows of a stated pair that disagree is refused, as two answers to one fact
    are, because the service cannot know which one is meant."""

    OPEN = VALIDATED.model_copy(update={"value": UNKNOWN})
    PLACE = FactAnswer(
        key=("", "", place_identity(OPEN), "", "", ""), value="validated"
    )

    def check(self, *facts):
        check_answers(
            [],
            list(facts),
            valid_model(),
            catalog(self.OPEN),
            {fact.key for fact in facts},
            [],
            asked_links=(),
            earlier_links=(),
            reopen=False,
        )

    def test_the_pair_is_refused_by_position(self):
        part_no = kind_answer(LOGIN, "content-validation", validates="no")

        with pytest.raises(ValueError, match=r"facts\[0\] and facts\[1\]"):
            self.check(self.PLACE, part_no)

    def test_two_answers_that_agree_are_admitted(self):
        self.check(
            self.PLACE, kind_answer(LOGIN, "content-validation", validates="yes")
        )

    def test_an_answer_that_disagrees_with_an_earlier_one_is_refused(self):
        part_no = kind_answer(LOGIN, "content-validation", validates="no")

        with pytest.raises(ValueError, match=r"facts\[0\] and an earlier answer"):
            check_answers(
                [],
                [part_no],
                valid_model(),
                catalog(self.OPEN),
                {part_no.key, self.PLACE.key},
                [self.PLACE],
                asked_links=(),
                earlier_links=(),
                reopen=False,
            )

    def test_a_facet_answer_merged_with_an_earlier_one_is_checked(self):
        """The run merges a facet answer with the earlier one, so the check
        reads the merged answer: its earlier "validates: no" stays."""
        earlier = kind_answer(LOGIN, "content-validation", validates="no")
        encodes = kind_answer(LOGIN, "content-validation", encodes="yes")

        with pytest.raises(ValueError, match=r"facts\[0\] and facts\[1\]"):
            check_answers(
                [],
                [self.PLACE, encodes],
                valid_model(),
                catalog(self.OPEN),
                {self.PLACE.key, encodes.key},
                [earlier],
                asked_links=(),
                earlier_links=(),
                reopen=False,
            )

    def test_two_earlier_answers_that_disagree_are_not_this_submissions(self):
        """The earlier answers alone write the pair, so a submission that
        adds an unrelated facet is admitted."""
        earlier = kind_answer(LOGIN, "content-validation", validates="no")
        encodes = kind_answer(LOGIN, "content-validation", encodes="yes")

        check_answers(
            [],
            [encodes],
            valid_model(),
            catalog(self.OPEN),
            {encodes.key, self.PLACE.key},
            [self.PLACE, earlier],
            asked_links=(),
            earlier_links=(),
            reopen=False,
        )
