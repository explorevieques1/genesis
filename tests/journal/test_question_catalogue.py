# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""The question catalogue is the feature list, so it has to stay true.

`evals/charting_questions.yaml` is written first and used three ways: as the
feature list, as the router eval, and as the answer-shape eval. That only works
if it cannot drift from the code — a catalogue naming an agent that does not
exist, or a task type nothing handles, is a promise the system does not keep.

These are cheap structural checks, not LLM evals, so they run in the normal
suite rather than under `pytest evals`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from genesis.agents.charting.fleet import CAPABILITIES as CHARTING
from genesis.agents.journal.fleet import CAPABILITIES as JOURNAL

CATALOGUE = Path(__file__).resolve().parents[2] / "evals" / "charting_questions.yaml"

#: Agents that exist but are deliberately not planner-facing — the journal
#: writes itself on a fill and drift runs nightly, so neither is orderable.
NON_PLANNED = {"trade-journal", "drift"}


@pytest.fixture(scope="module")
def catalogue() -> dict:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def questions(catalogue) -> list[dict]:
    return catalogue["questions"] + catalogue["journal_questions"]


def test_every_question_names_an_agent_or_is_marked_unsupported(questions) -> None:
    for question in questions:
        assert question.get("agent") or question.get("unsupported"), question["ask"]


def test_every_named_agent_exists(questions) -> None:
    known = {c.agent for c in (*CHARTING, *JOURNAL)} | NON_PLANNED
    for question in questions:
        agent = question.get("agent")
        if agent:
            assert agent in known, f"{question['ask']} routes to unknown agent {agent}"


def test_every_task_type_is_one_the_agent_declares(questions) -> None:
    by_agent = {c.agent: c.task_types for c in (*CHARTING, *JOURNAL)}
    for question in questions:
        agent, task_type = question.get("agent"), question.get("type")
        if agent and task_type and agent in by_agent:
            assert task_type in by_agent[agent], (
                f"{question['ask']} dispatches {task_type} at {agent}, which "
                f"declares {by_agent[agent]}"
            )


def test_every_question_says_what_a_right_answer_looks_like(questions) -> None:
    for question in questions:
        assert question.get("answers"), question["ask"]


def test_unsupported_questions_say_what_they_are_waiting_on(questions) -> None:
    """The honest edge of the system, stated rather than discovered."""
    unsupported = [q for q in questions if q.get("unsupported")]
    assert unsupported, "a catalogue with no honest edge is a catalogue that is lying"
    for question in unsupported:
        assert len(question["unsupported"]) > 40, question["ask"]


def test_every_planner_facing_agent_is_asked_about(questions) -> None:
    """A capability nobody has a question for is one nobody will use."""
    asked = {q.get("agent") for q in questions}
    for capability in (*CHARTING, *JOURNAL):
        assert capability.agent in asked, f"no question routes to {capability.agent}"
