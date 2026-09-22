# Spec: Genesis Markdown/10-Architecture/Operating Model.md §2 §4
#       Genesis Markdown/00-Meta/UI-0 Build Order.md §step 0
"""The parity rule, as checks rather than as a promise.

*"Anything Genesis can do, a person can do by hand — through the same door,
with the same audit line."*

Parity is the kind of property that is true on the day it is written and false
four commits later, because breaking it requires no deliberate act: adding a
capability to one path and forgetting the other is enough. So it is pinned
here, from both ends.

**The ladder.** The answer ladder used to live inside ``VoiceLoop._handle``,
whose input is audio frames. A sentence typed into ``POST /v1/command`` matched
the deterministic command table and stopped, with a fully-wired reasoner one
import away. That made a microphone a capability, which is exactly the failure
Operating Model §2 names.

**The grants.** The ``operator`` allow-list is the ``orchestrator``'s *reading*
surface. A read granted to the model and not to the person is a tool whose
output the person cannot check.
"""

from __future__ import annotations

import pytest

from genesis.orchestrator.answer import Ladder, Rung
from genesis.orchestrator.answers import Answer, TrivialAnswerer


class FakeReasoner:
    """The large tier, without the network. Records what it was asked."""

    def __init__(self, reply: str | None = "Semis are extended.") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def answer(self, text: str, *, context: str = "") -> Answer | None:  # noqa: ARG002
        self.calls.append(text)
        return Answer(self.reply, "llm:claude-opus-5") if self.reply is not None else None


# -- the ladder is one ladder ----------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "what time does the market open",   # the trivial rung
        "what do you make of semis here",   # falls through to the large tier
    ],
)
def test_the_typed_and_spoken_paths_walk_the_same_rung(question):
    """The exit criterion for UI-0 step 0.

    Not "both produce an answer" -- both must take the *same rung*, because a
    typed question that quietly skipped the calendar and paid for a model call
    would satisfy a weaker test while being the bug this refactor exists to
    prevent.
    """
    from tests.test_voice_loop import build

    audio = b"parity"
    loop, turns, _memory, _tts = build({audio: f"Genesis, {question}?"})
    loop.reasoner = FakeReasoner()

    # The typed path: the ladder called directly, exactly as `server/app.py`
    # calls it once the command table declines.
    typed: Rung = Ladder(
        answerer=TrivialAnswerer(),
        reasoner=FakeReasoner(),
    ).answer(question)

    # The spoken path: the same rungs, reached through audio.
    loop._handle(audio)
    spoken = turns[0]

    assert typed.path == spoken.path
    assert typed.answer.source == spoken.source
    assert typed.answer.text == spoken.spoken


def test_a_ladder_with_nothing_wired_still_answers():
    """A trader with no API key hears a sentence, not a stack trace.

    The fail-open rule is that the user is never left unanswered, and it has to
    survive the case where *every* rung is absent -- which is the state of a
    fresh checkout.
    """
    rung = Ladder().answer("what do you make of semis here")
    assert rung.answer.text
    assert rung.path == "unhandled"
    assert not rung.reached


def test_the_cheap_rungs_get_first_refusal():
    """LLM Model Tiers' "default down": a calendar question never reaches the
    large tier, on either path."""
    reasoner = FakeReasoner()
    rung = Ladder(answerer=TrivialAnswerer(), reasoner=reasoner).answer(
        "what time does the market open"
    )
    assert reasoner.calls == [], "a deterministic answer still hit the model"
    assert rung.path == "trivial"


# -- the HTTP route reaches it ---------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """A test client whose analyst is a fake, so nothing builds a gateway."""
    starlette_testclient = pytest.importorskip("starlette.testclient")
    from genesis.server import analyst as analyst_module
    from genesis.server.app import EventBus, build_app

    fake = Ladder(answerer=TrivialAnswerer(), reasoner=FakeReasoner())
    monkeypatch.setattr(analyst_module.ANALYST, "_ladder", fake)

    with starlette_testclient.TestClient(build_app(EventBus())) as c:
        yield c, fake


def test_an_unmatched_sentence_reaches_the_analyst(client):
    """The regression this whole step exists for.

    Before: *"I didn't catch a command in that."* A sentence the deterministic
    table does not know is not an error -- it is the boundary between the fast
    path and the slow one.
    """
    c, fake = client
    body = c.post("/v1/command", json={"text": "what do you make of semis here"}).json()

    assert body["ok"] is True
    assert body["spoken"] == "Semis are extended."
    assert body["command"] == "analyst.reasoned", "the trace does not say which rung ran"
    assert fake.reasoner.calls == ["what do you make of semis here"]


def test_the_command_table_still_goes_first(client):
    """"status" is in the table, so it must never cost a model call.

    The ladder is the fall-through, not a replacement. A terminal where every
    keystroke pays for a hosted round trip is slower and less predictable than
    the one it replaced.
    """
    c, fake = client
    body = c.post("/v1/command", json={"text": "status"}).json()

    assert body["command"] == "status"
    assert fake.reasoner.calls == [], "a table command was handed to the model"


def test_a_dead_ladder_answers_over_http_rather_than_500(monkeypatch):
    """The daemon must not return an error page because a key is missing."""
    starlette_testclient = pytest.importorskip("starlette.testclient")
    from genesis.server import analyst as analyst_module
    from genesis.server.app import EventBus, build_app

    monkeypatch.setattr(analyst_module.ANALYST, "_ladder", Ladder())
    with starlette_testclient.TestClient(build_app(EventBus())) as c:
        body = c.post("/v1/command", json={"text": "what do you make of semis"}).json()

    assert body["ok"] is False
    assert body["spoken"], "the trader was left with nothing"
    assert body["command"] == "analyst.unhandled"


# -- the grants are symmetrical --------------------------------------------


#: Reads the orchestrator has and the operator deliberately does not.
#:
#: Each one is a decision recorded in `mcp/build.py`, not an accident:
#: `vault.*` includes writes; `chart.*` drives the desktop chart; `research.*`
#: costs credits and minutes, which belongs on a lane rather than behind Enter.
#: `convert.*` is the odd one out -- it looks like an oversight rather than a
#: decision, and widening a grant is not something a test should do quietly.
DELIBERATE_ASYMMETRY = {"vault.*", "chart.*", "research.*", "convert.*", "fs.*"}


def test_the_operator_can_reach_what_the_orchestrator_can_read():
    """Operating Model §2, as a check.

    This fails when a new read capability is granted to the model and not to
    the person. That is the review prompt: either grant it to both, or add it
    above with the reason it is asymmetric.
    """
    from genesis.mcp.build import ALLOW_LISTS

    model = set(ALLOW_LISTS["orchestrator"])
    person = set(ALLOW_LISTS["operator"])
    unreachable = model - person - DELIBERATE_ASYMMETRY

    assert not unreachable, (
        f"the model can reach {sorted(unreachable)} and the operator cannot — "
        "a tool whose output the person cannot check"
    )


def test_the_operator_is_granted_no_write():
    """The other direction. Parity is on reads; writes stay behind the gate."""
    from genesis.mcp.build import ALLOW_LISTS

    for pattern in ALLOW_LISTS["operator"]:
        assert not any(
            pattern.startswith(p) for p in ("vault.create", "vault.edit", "order", "broker")
        ), f"{pattern} is a write on a surface whose muscle memory is type-and-Enter"
