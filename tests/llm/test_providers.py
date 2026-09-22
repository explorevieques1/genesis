# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""Provider selection, the dev-only guard, tier switching, and the meter."""

import pytest

from genesis.config import ConfigError, LLMTier, load_config
from genesis.errors import DegradedError
from genesis.llm.backend import Completion
from genesis.llm.openai_compat import PROVIDERS, OpenAICompatBackend, is_dev_only
from genesis.llm.tiers import set_tier
from genesis.llm.usage import MeteredBackend, UsageLog, estimate_cost


# -- config validation ------------------------------------------------------

def test_a_typo_in_backend_is_a_config_error_not_a_silent_none():
    with pytest.raises(Exception) as exc:
        LLMTier(backend="geminii", model="x")
    assert "unknown backend" in str(exc.value)


def test_dev_profile_changes_only_the_tiers():
    dev = load_config(__import__("pathlib").Path("config-dev.example.yaml"))
    prod = load_config(None)
    assert dev.llm.large.backend == "gemini"
    # The profile must not quietly relax risk while it is swapping models.
    assert dev.risk.max_position_pct == prod.risk.max_position_pct
    assert dev.approval.mode == prod.approval.mode


# -- the dev-only guard -----------------------------------------------------

def test_every_free_provider_is_marked_dev_only():
    # A provider added later without this flag would be reachable on a live
    # account, which is the failure the flag exists to prevent.
    assert all(p.dev_only for p in PROVIDERS.values())
    assert is_dev_only("gemini") and not is_dev_only("anthropic")


def test_a_missing_key_degrades_and_names_the_variable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(DegradedError) as exc:
        OpenAICompatBackend("gemini-flash-latest", provider="gemini")
    assert "GEMINI_API_KEY" in str(exc.value)
    assert "aistudio.google.com" in str(exc.value)


def test_a_model_that_rejects_reasoning_effort_is_asked_once(monkeypatch):
    """`reasoning_effort` is a per-model capability, not a per-provider one.

    `gemini-flash-latest` needs it or its own thinking truncates the answer;
    `gemini-flash-lite-latest` returns 400 "invalid argument" and cannot run
    with it at all. Both are the same provider entry, so the backend asks once
    and remembers rather than carrying a model list that goes stale.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    backend = OpenAICompatBackend("gemini-flash-lite-latest", provider="gemini")
    sent: list[dict] = []

    class Response:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.text = "invalid argument"

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            }

    class Client:
        def post(self, _path, json):  # noqa: A002 - httpx's own kwarg name
            sent.append(dict(json))
            return Response(400 if "reasoning_effort" in json else 200)

    monkeypatch.setattr(backend, "_http", lambda: Client())
    assert backend.complete("hi").text == "ok"
    assert [("reasoning_effort" in c) for c in sent] == [True, False]

    # And it does not ask again on the next call.
    assert backend.complete("hi").text == "ok"
    assert [("reasoning_effort" in c) for c in sent] == [True, False, False]


def test_a_503_is_retried_but_a_429_is_not(monkeypatch):
    """Busy and spent are different failures and get different answers.

    Google's free tier returns 503 "high demand" on an idle key often enough
    that a single attempt reads as a broken model. A 429 is a quota, and
    retrying one spends it faster.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("genesis.llm.openai_compat.BACKOFF_503", 0)
    backend = OpenAICompatBackend("gemini-flash-latest", provider="gemini")

    class Response:
        def __init__(self, status: int) -> None:
            self.status_code = status
            self.text = "busy"

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            }

    class Client:
        def __init__(self, statuses: list[int]) -> None:
            self.statuses = statuses
            self.calls = 0

        def post(self, _path, json):  # noqa: A002 - httpx's own kwarg name
            self.calls += 1
            return Response(self.statuses.pop(0))

    # Busy twice, then an answer: the caller never sees the outage.
    busy = Client([503, 503, 200])
    monkeypatch.setattr(backend, "_http", lambda: busy)
    assert backend.complete("hi").text == "ok"
    assert busy.calls == 3

    # Busy forever: it gives up rather than hanging, and says which failure.
    forever = Client([503, 503, 503])
    monkeypatch.setattr(backend, "_http", lambda: forever)
    with pytest.raises(DegradedError) as exc:
        backend.complete("hi")
    assert "503" in str(exc.value) and forever.calls == 3

    limited = Client([429])
    monkeypatch.setattr(backend, "_http", lambda: limited)
    with pytest.raises(DegradedError) as exc:
        backend.complete("hi")
    assert "rate limited" in str(exc.value) and limited.calls == 1


def test_gemini_asks_for_no_thinking_budget(monkeypatch):
    """The reasoning budget comes out of `max_tokens` and is never returned.

    Measured live at the Reasoner's own default of 300: without this the reply
    stops at `finish_reason=length` after eleven visible tokens, mid-sentence.
    So the request must say so on every call, not just when someone remembers.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    backend = OpenAICompatBackend("gemini-flash-latest", provider="gemini")
    sent: dict = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            }

    class Client:
        def post(self, _path, json):  # noqa: A002 - httpx's own kwarg name
            sent.update(json)
            return Response()

    monkeypatch.setattr(backend, "_http", lambda: Client())
    assert backend.complete("hi").text == "ok"
    assert sent["reasoning_effort"] == "none"


def test_an_empty_completion_is_refused_rather_than_returned(monkeypatch):
    """A 200 carrying no words is the silent failure this endpoint has.

    Gemini's reasoning models spend `max_tokens` thinking before they write. If
    the budget runs out first the response is a healthy 200 with
    `content: ""` and `finish_reason: length` -- and a caller that trusted it
    would treat an empty string as the model's answer. Measured against the
    live API: the same prompt returned "" at one budget and "online" at
    another, so this is nondeterministic rather than a threshold anyone can
    code around.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    backend = OpenAICompatBackend("gemini-flash-latest", provider="gemini")

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 0},
            }

    class Client:
        def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(backend, "_http", lambda: Client())
    with pytest.raises(DegradedError) as exc:
        backend.complete("Reply with the single word: online", max_tokens=64)
    # The message has to say what to change, not just that it failed.
    assert "empty completion" in str(exc.value)
    assert "64" in str(exc.value) and "budget" in str(exc.value)


# -- tier switching ---------------------------------------------------------

def test_set_tier_writes_only_the_user_layer(tmp_path):
    path = tmp_path / "config.yaml"
    change = set_tier("large", "ollama", "qwen2.5:3b", path=path)
    assert change.changed
    written = __import__("yaml").safe_load(path.read_text())
    # Only what was asked for. Freezing the packaged defaults into the user
    # file would silently pin today's values through a later upgrade.
    assert written == {"llm": {"large": {"backend": "ollama", "model": "qwen2.5:3b"}}}


def test_set_tier_rejects_nano():
    # nano is deterministic code; a model picker for it invites putting one
    # back on the sub-100ms hot path.
    with pytest.raises(ConfigError):
        set_tier("nano", "ollama", "qwen2.5:3b")


def test_a_bad_write_leaves_no_file_behind(tmp_path):
    path = tmp_path / "config.yaml"
    with pytest.raises(ConfigError):
        set_tier("large", "nope", "x", path=path)
    assert not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


# -- the meter --------------------------------------------------------------

class _Stub:
    model = "claude-opus-5"

    def __init__(self, blow_up: bool = False) -> None:
        self.blow_up = blow_up

    def complete(self, prompt: str, **kwargs: object) -> Completion:
        if self.blow_up:
            raise DegradedError("upstream is unwell")
        return Completion(text="ok", model=self.model, latency_ms=12.0,
                          input_tokens=100, output_tokens=50)


def test_the_meter_records_successes_and_failures(tmp_path):
    log = UsageLog(tmp_path / "usage.db")
    MeteredBackend(_Stub(), tier="large", backend="anthropic", log=log).complete("hi")
    with pytest.raises(DegradedError):
        MeteredBackend(_Stub(blow_up=True), tier="large", backend="anthropic", log=log).complete("hi")

    # Same tier/backend/model, so both calls land in one grouped row.
    (row,) = log.by_tier()
    assert log.tokens_today() == 150
    assert row.calls == 2 and row.failures == 1
    assert row.input_tokens == 100 and row.output_tokens == 50


def test_the_meter_never_breaks_the_call():
    # Instrumentation that can take down what it measures is a worse bug than
    # a gap in the data.
    broken = UsageLog("/nonexistent/dir/that/cannot/be/made/usage.db")
    reply = MeteredBackend(_Stub(), tier="large", backend="anthropic", log=broken).complete("hi")
    assert reply.text == "ok"


def test_an_unpriced_model_costs_none_not_zero():
    # "$0.00" for an unpriced hosted model is a number an operator would budget
    # against; None renders as "local"/"—".
    assert estimate_cost("qwen2.5:3b", 1000, 1000) is None
    assert estimate_cost("claude-haiku-4-5", 1_000_000, 0) == 1.0
