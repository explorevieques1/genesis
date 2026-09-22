# Spec: Genesis Markdown/70-Schemas/Workflow Schema.md
"""Validation and compilation: the chain rules, the grant, the declaration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genesis.automation.workflow import Workflow, compile_declaration


def body(**overrides):
    base = {
        "id": "tesla-news",
        "name": "Tesla news synopsis",
        "trigger": {"type": "cron", "at": "07:00"},
        "start": "news",
        "steps": [
            {"id": "news", "kind": "gather", "capability": "news.search",
             "args": {"query": "Tesla"}, "next": "has-news"},
            {"id": "has-news", "kind": "check", "input": "news",
             "predicate": "non_empty", "next": "synopsis"},
            {"id": "synopsis", "kind": "run", "agent": "topic-researcher",
             "input": "news", "args": {"subject": "Tesla news today"}},
        ],
    }
    base.update(overrides)
    return base


def test_the_canonical_workflow_validates_and_compiles() -> None:
    declaration = compile_declaration(Workflow.model_validate(body()))
    assert declaration.id == "wf-tesla-news"
    assert declaration.cadence[0].at == "07:00"
    assert declaration.tools == ("news.search",)
    assert declaration.model_tier == "none"


@pytest.mark.parametrize("capability", [
    "genesis-execution.propose_order", "genesis-execution.place_approved",
    "obsidian.write", "tradingview.click",
])
def test_a_gather_outside_the_grant_is_refused(capability: str) -> None:
    steps = [{"id": "x", "kind": "gather", "capability": capability}]
    with pytest.raises(ValidationError, match="outside the workflow grant"):
        Workflow.model_validate(body(start="x", steps=steps))


def test_fan_in_is_refused() -> None:
    steps = [
        {"id": "a", "kind": "gather", "capability": "news.search", "next": "c"},
        {"id": "b", "kind": "gather", "capability": "news.search", "next": "c"},
        {"id": "c", "kind": "refresh", "target": "vault-map"},
    ]
    with pytest.raises(ValidationError, match="two incoming edges"):
        Workflow.model_validate(body(start="a", steps=steps))


def test_a_loop_is_refused() -> None:
    steps = [
        {"id": "a", "kind": "refresh", "target": "vault-map", "next": "b"},
        {"id": "b", "kind": "refresh", "target": "vault-map", "next": "a"},
    ]
    with pytest.raises(ValidationError, match="loop"):
        Workflow.model_validate(body(start=None, steps=steps))


def test_only_a_check_branches() -> None:
    steps = [{"id": "a", "kind": "refresh", "target": "vault-map", "on_fail": "b"},
             {"id": "b", "kind": "refresh", "target": "vault-map"}]
    with pytest.raises(ValidationError, match="only a check"):
        Workflow.model_validate(body(start="a", steps=steps))


def test_input_must_come_from_earlier_on_the_path() -> None:
    steps = [
        {"id": "a", "kind": "check", "input": "b", "predicate": "non_empty", "next": "b"},
        {"id": "b", "kind": "gather", "capability": "news.search"},
    ]
    with pytest.raises(ValidationError, match="not an earlier step"):
        Workflow.model_validate(body(start="a", steps=steps))
