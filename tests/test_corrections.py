"""A final report takes corrections and runs nothing (#1289, ADR 0054)."""

from __future__ import annotations

import asyncio

import pytest

from katra.answer_sets import AnswerSet
from katra.assertions import (
    UNKNOWN,
    Assertion,
    AssertionCatalog,
    Subject,
    answer,
    assertion_id,
)
from katra.claims import Ground, UnknownRef
from katra.fact_answers import FactAnswer, control_line, fact_line
from katra.grounding import verify_quote
from katra.jobs import Checkpoint, JobRecord, Resumption
from katra.links import apply_answers
from katra.report_conditions import corrected_findings
from katra.sources import ANSWERS_LABEL, Source
from tests.factories import (
    DESCRIPTION_TEXT,
    asking_threat,
    sample_analysis,
    sample_report,
    sample_selection,
    sample_threat,
    valid_model,
)
from tests.test_api import auth, make_client
from tests.test_part_rows import PROCESS, kind_answer

ASKED = UnknownRef(
    element_id=valid_model().data_flows[1].id, attribute="encryption_in_transit"
)
ANSWER = FactAnswer(key=ASKED.key, value="TLS 1.3")


def finished(store, *, final: bool = True) -> str:
    """A completed job whose run read ``ANSWER``; its report is final where asked."""
    from tests.test_api import admit

    report = sample_report([asking_threat(ASKED)])
    parent = JobRecord.create(
        assertion_pass=True,
        ask_questions=True,
        owner_id="alice",
        sources=[Source.description(DESCRIPTION_TEXT)],
        frameworks=sample_selection(),
    )
    parent.transition("running")
    parent.report = report
    parent.transition("completed")
    asyncio.run(admit(store, parent))
    record = JobRecord.create(
        assertion_pass=True,
        ask_questions=True,
        owner_id="alice",
        sources=[Source.description(DESCRIPTION_TEXT)],
        frameworks=sample_selection(),
        answers=AnswerSet(facts=(ANSWER,)),
        resumption=Resumption(
            parent_id=parent.id,
            checkpoint=Checkpoint(system_model=report.system_model, assertions=None),
            follow_up=final,
        ),
        parent_revision=parent.revision,
    )
    record.transition("running")
    record.report = report
    record.transition("completed")
    asyncio.run(admit(store, record))
    return record.id


def correct(client, job, *facts, revision=0):
    return client.post(
        f"/v1/jobs/{job}/corrections",
        json={
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "revision": revision,
        },
        headers=auth(),
    )


class TestTheRoute:
    def test_a_final_report_takes_a_correction_and_names_what_it_reaches(self):
        client, store = make_client()
        job = finished(store)
        back = FactAnswer(key=ASKED.key, value="unknown")

        response = correct(client, job, back)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["corrections"] == [back.model_dump(mode="json")]
        assert body["corrected_findings"] == ["stride/S-01"]
        record = asyncio.run(store.get(job))
        assert record.corrections == [back]
        assert record.answers.facts == (ANSWER,), (
            "the answers the run read stay as they were"
        )
        questions = client.get(f"/v1/jobs/{job}/questions", headers=auth()).json()
        assert questions["corrections"] == body["corrections"]
        assert questions["corrected_findings"] == ["stride/S-01"]

    def test_two_corrections_that_read_one_revision_land_once(self):
        """The second correction would drop the first, so it gets 409 (ADR 0090)."""
        client, store = make_client()
        job = finished(store)
        first = correct(client, job, FactAnswer(key=ASKED.key, value="unknown"))
        second = correct(client, job, FactAnswer(key=ASKED.key, value="TLS 1.2"))
        assert first.status_code == 200, first.text
        assert first.json()["revision"] == 1
        assert second.status_code == 409, second.text
        record = asyncio.run(store.get(job))
        assert [fact.value for fact in record.corrections] == ["unknown"]
        again = correct(
            client, job, FactAnswer(key=ASKED.key, value="TLS 1.2"), revision=1
        )
        assert again.status_code == 200, again.text

    def test_a_correction_names_the_revision_it_read(self):
        client, store = make_client()
        job = finished(store)
        response = client.post(
            f"/v1/jobs/{job}/corrections",
            json={
                "facts": [
                    ANSWER.model_copy(update={"value": "unknown"}).model_dump(
                        mode="json"
                    )
                ]
            },
            headers=auth(),
        )
        assert response.status_code == 422, response.text

    def test_an_empty_correction_is_refused_by_the_correction_rule(self):
        client, store = make_client()
        job = finished(store)
        response = correct(client, job)
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "a correction changes at least one answer"

    def test_a_report_that_is_not_final_refuses_it(self):
        client, store = make_client()
        job = finished(store, final=False)
        response = correct(client, job, FactAnswer(key=ASKED.key, value="none"))
        assert response.status_code == 400
        assert "only a final report" in response.json()["detail"]

    def test_a_fact_the_run_did_not_read_is_refused(self):
        client, store = make_client()
        job = finished(store)
        other = (valid_model().data_flows[1].id, "authentication", "", "", "", "")
        response = correct(client, job, FactAnswer(key=other, value="none"))
        assert response.status_code == 400
        assert "only an answer the report read" in response.json()["detail"]
        assert "('" not in response.json()["detail"], "a label, never a raw key"

    def test_a_correction_that_changes_nothing_is_refused(self):
        client, store = make_client()
        job = finished(store)
        response = correct(client, job, ANSWER)
        assert response.status_code == 400
        assert "change no answer" in response.json()["detail"]


def test_v1_reads_a_follow_up_s_report_as_final():
    """The envelope left out the resumption, so /v1 read every report as not
    final and admitted a second follow-up (#1336)."""
    client, store = make_client()
    job = finished(store)
    body = client.get(f"/v1/jobs/{job}/questions", headers=auth()).json()
    again = client.post(
        f"/v1/jobs/{job}/answers",
        json={
            "facts": [FactAnswer(key=ASKED.key, value="none").model_dump(mode="json")]
        },
        headers=auth(),
    )
    assert body["final"] is True
    assert again.status_code == 400
    assert "this report is final" in again.json()["detail"]


class TestWhichFindingsACorrectionReaches:
    """The one reader of "which findings rest on a corrected fact"."""

    BACK = FactAnswer(key=ASKED.key, value="unknown")

    def reached(self, threat, controls=()):
        report = sample_report([threat])
        return corrected_findings(
            report.analyses, [ANSWER], [self.BACK], report.system_model, None, controls
        )

    def test_a_finding_that_quotes_the_answer_s_line(self):
        quote = Ground(kind="quote", text=fact_line(ANSWER), source_label=ANSWERS_LABEL)
        assert self.reached(sample_threat(grounds=[quote])) == ("stride/S-01",)

    @pytest.mark.parametrize(
        "spelled",
        [
            str.casefold,
            lambda line: line.replace('"TLS', "\u201cTLS").replace('3"', "3\u201d"),
            lambda line: line.replace("TLS 1.3", "**TLS 1.3**"),
            lambda line: line.replace(" of ", " … ").split(" … ")[0] + " … TLS 1.3",
        ],
    )
    def test_a_quote_the_grounding_ladder_admits(self, spelled):
        """The ladder folds case, curly quotes and markup, and takes a cut."""
        line = fact_line(ANSWER)
        text = spelled(line)
        assert text != line and verify_quote(text, line)
        quote = Ground(kind="quote", text=text, source_label=ANSWERS_LABEL)
        assert self.reached(sample_threat(grounds=[quote])) == ("stride/S-01",)

    def test_a_finding_that_grounds_on_the_attribute(self):
        ground = Ground(
            kind="unknown-attribute",
            element_id=ASKED.element_id,
            attribute=ASKED.attribute,
        )
        assert self.reached(sample_threat(grounds=[ground])) == ("stride/S-01",)

    def test_a_finding_that_rests_on_neither_is_not_reached(self):
        assert self.reached(sample_threat()) == ()

    def test_a_cut_of_a_control_s_line(self):
        """A Control writes the fact on a line that names the Control, so a
        cut of that line rests on the fact (#2307 A3)."""
        line = control_line("Edge TLS", ANSWER)
        text = "TLS 1.3" + line.split("TLS 1.3", 1)[1]
        quote = Ground(kind="quote", text=text, source_label=ANSWERS_LABEL)
        controls = [("Edge TLS", ANSWER)]
        assert self.reached(sample_threat(grounds=[quote]), controls) == (
            "stride/S-01",
        )

    def test_a_control_s_line_of_another_value_is_not_reached(self):
        """The answer's own line replaced that Control's line in the run."""
        other = ANSWER.model_copy(update={"value": "TLS 1.2"})
        quote = Ground(
            kind="quote",
            text=control_line("Edge TLS", other),
            source_label=ANSWERS_LABEL,
        )
        controls = [("Edge TLS", other)]
        assert self.reached(sample_threat(grounds=[quote]), controls) == ()

    def test_a_quote_from_another_source_is_not_reached(self):
        quote = Ground(kind="quote", text=fact_line(ANSWER), source_label="description")
        assert self.reached(sample_threat(grounds=[quote])) == ()


class TestACorrectionReachesTheRowItsAnswerWrote:
    """A finding that grounds on the stated row an answer wrote rests on that
    answer, so a correction of it reaches the finding (#2307 A3). A row at the
    same place that another answer wrote rests on that other answer."""

    OPEN = Assertion(
        subject=PROCESS,
        predicate="record-attribution",
        value=UNKNOWN,
        reason="silent",
        basis="inferred",
        origin="assertion-pass",
        explanation="the notes do not say",
    )
    PLACE = FactAnswer(
        key=UnknownRef(assertion=assertion_id(OPEN)).key, value="principal"
    )
    KIND = kind_answer(PROCESS, "audit-evidence", records_actor="yes")

    def reached(self, answers, corrections, controls=()):
        """The findings a correction reaches, each grounded on the one
        ``record-attribution`` row that ``answers`` wrote."""
        held = AssertionCatalog(
            subjects=[Subject(id=PROCESS, type="component", label="Web app")],
            entries=[self.OPEN],
        )
        catalog, _ = apply_answers(held, valid_model(), [], answers, controls)
        (row,) = [
            row
            for row in answer(catalog, PROCESS, "record-attribution").rows
            if row.origin == "answer"
        ]
        ground = Ground(kind="assertion", assertion=assertion_id(row))
        analyses = [sample_analysis([sample_threat(grounds=[ground])])]
        return corrected_findings(
            analyses, answers, corrections, valid_model(), catalog, controls
        )

    def test_an_assertion_answer_s_row(self):
        changed = self.PLACE.model_copy(update={"value": UNKNOWN})
        assert self.reached([self.PLACE], [changed]) == ("stride/S-01",)

    def test_a_question_kind_answer_s_part_row(self):
        changed = kind_answer(PROCESS, "audit-evidence", records_actor="no")
        assert self.reached([self.KIND], [changed]) == ("stride/S-01",)

    def test_a_kind_correction_misses_the_assertion_answer_s_row(self):
        """The assertion answer writes the place, so the part writes no row."""
        changed = kind_answer(PROCESS, "audit-evidence", records_actor="no")
        assert self.reached([self.PLACE, self.KIND], [changed]) == ()

    def test_an_assertion_correction_misses_the_part_row(self):
        """An unknown assertion answer writes nothing, so the row is the part's."""
        unknown = self.PLACE.model_copy(update={"value": UNKNOWN})
        assert self.reached([unknown, self.KIND], [self.PLACE]) == ()

    def test_a_detail_that_ends_like_a_control_s_name(self):
        """The row quotes the whole line, whatever its detail says."""
        fact = self.PLACE.model_copy(update={"detail": 'ok From the Control "x'})
        changed = fact.model_copy(update={"value": UNKNOWN})
        assert self.reached([fact], [changed]) == ("stride/S-01",)

    @pytest.mark.parametrize("fact", [PLACE, KIND], ids=["assertion", "kind"])
    def test_a_row_a_control_wrote(self, fact):
        """The row quotes the Control's line, which names the Control."""
        changed = fact.model_copy(update={"value": UNKNOWN, "facets": None})
        controls = [("Audit log", fact)]
        assert self.reached([fact], [changed], controls) == ("stride/S-01",)
