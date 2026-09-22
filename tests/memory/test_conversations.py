# Spec: Genesis Markdown/70-Schemas/Conversation Store.md
"""Saved Ask Genesis conversations: create-on-first-turn, append, delete.

Unlike the Episodic Log this store is *deletable* -- that is the whole reason it
is a separate store -- so the tests that matter are the lifecycle ones, not an
append-only guarantee.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from genesis.memory.conversations import ConversationStore


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations.db")


def _reply(spoken: str = "ok", **kw) -> dict:
    return {"ok": True, "spoken": spoken, "command": "status", **kw}


def test_first_turn_mints_a_conversation(store: ConversationStore) -> None:
    cid = store.append(None, operator_text="why is NVDA down", reply=_reply())
    assert cid.startswith("cv_")
    rows = store.list()
    assert len(rows) == 1
    assert rows[0]["id"] == cid
    assert rows[0]["title"] == "why is NVDA down"
    assert rows[0]["turns"] == 2  # operator + genesis


def test_append_grows_the_same_conversation(store: ConversationStore) -> None:
    cid = store.append(None, operator_text="first", reply=_reply())
    same = store.append(cid, operator_text="second", reply=_reply())
    assert same == cid
    assert store.list()[0]["turns"] == 4
    conv = store.get(cid)
    assert [t["role"] for t in conv["turns"]] == ["operator", "genesis", "operator", "genesis"]
    assert conv["turns"][0]["text"] == "first"


def test_title_is_the_first_line_only(store: ConversationStore) -> None:
    cid = store.append(None, operator_text="a question\nwith detail below", reply=_reply())
    assert store.get(cid)["title"] == "a question"


def test_genesis_turn_keeps_the_work_behind_it(store: ConversationStore) -> None:
    cid = store.append(
        None,
        operator_text="chart NVDA",
        reply=_reply(spoken="Charted.", command="chart", detail="1D",
                     data={"symbol": "NVDA"}, trace="tr_9"),
    )
    genesis = store.get(cid)["turns"][1]
    assert genesis["command"] == "chart"
    assert genesis["detail"] == "1D"
    assert genesis["data"] == {"symbol": "NVDA"}
    assert genesis["trace"] == "tr_9"
    assert genesis["ok"] is True


def test_delete_removes_the_conversation_and_its_turns(store: ConversationStore) -> None:
    cid = store.append(None, operator_text="throwaway", reply=_reply())
    assert store.delete(cid) is True
    assert store.list() == []
    assert store.get(cid) is None
    # cascade: no orphan turns
    assert store._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0


def test_delete_of_a_missing_conversation_is_false(store: ConversationStore) -> None:
    assert store.delete("cv_nope") is False


def test_get_of_a_missing_conversation_is_none(store: ConversationStore) -> None:
    assert store.get("cv_nope") is None


def test_list_is_most_recently_updated_first(store: ConversationStore) -> None:
    a = store.append(None, operator_text="older", reply=_reply())
    b = store.append(None, operator_text="newer", reply=_reply())
    # `b`'s ULID sorts after `a`'s, so it leads even inside the same millisecond.
    assert [r["id"] for r in store.list()] == [b, a]
    time.sleep(0.002)  # push `updated` into a later millisecond
    store.append(a, operator_text="touch the older one", reply=_reply())
    assert [r["id"] for r in store.list()] == [a, b]
