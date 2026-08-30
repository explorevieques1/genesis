# Genesis evals

**Scaffold. No LLM evals yet — they arrive in Phase 2.**

Pattern adapted from `~/Work/jarvis/EVALS.md` and its `evals/` layout (a
reference repo, read for structure only). Everything here is expressed in
Genesis terms.

## Why these are separate from `tests/`

| | `tests/` | `evals/` |
|---|---|---|
| Asks | is this **correct**? | is this **good**? |
| Subject | sizing, risk, metrics, schemas | agent routing, tool selection, memory recall, intent classification |
| Answer | exact, deterministic | graded, varies run to run |
| Runs | every commit, always | deliberately, and when a prompt or model changes |

`Conventions.md` draws the line: *unit tests for math — these must be exact;
**evals** for LLM behaviour.* A non-deterministic check in the unit suite makes
the suite untrustworthy, and a flaky suite gets ignored, so they stay apart.

**Nothing safety-critical is evaluated here.** The whole execution family, the
risk engine, backtest, metrics and allocation are `tier: none` — no language
model is in those paths, so they are tested, never evaluated. If you find
yourself writing an eval for position sizing, something has gone wrong upstream.

## Running

Evals are excluded from the default run via `testpaths` in `pyproject.toml`.

```bash
pytest                      # unit tests only
pytest evals                # the eval suite
pytest evals -v -k routing  # one slice
GENESIS_EVAL_JUDGE_MODEL=<model> pytest evals    # enable judge-backed evals
```

| Variable | Default | Purpose |
|---|---|---|
| `GENESIS_EVAL_JUDGE_MODEL` | *unset* | judge model; unset ⇒ judge evals skip |
| `GENESIS_EVAL_JUDGE_BASE_URL` | `http://localhost:11434` | Ollama-compatible endpoint |
| `GENESIS_EVAL_JUDGE_TIMEOUT` | `120` | seconds |

An unreachable judge produces a **skip, never a pass**. A suite that reports
green because no model answered is worse than no suite at all.

## Writing one

Prefer deterministic gates. Reach for the judge only when the quality genuinely
cannot be expressed as a keyword — it is slow, costs tokens, and is itself
non-deterministic.

```python
from helpers import EvalCase, EvalResult, assert_meets_criteria

CASE = EvalCase(
    name="screener-routes-to-screener",
    utterance="Genesis, find me a long setup in semis",
    expects="routes to the screener, does not touch the order path",
    expected_agent="screener",
    forbidden_tools=("propose_order", "place_approved"),
)
```

Then run it through the system under test and call `assert_meets_criteria`.
Judge-backed cases carry `judge_criteria` and the `requires_judge` marker from
`conftest.py`.

## Layout

| File | Holds |
|---|---|
| `helpers.py` | `EvalCase`, `EvalResult`, `assert_meets_criteria`, `ToolCallCapture`, judge client |
| `conftest.py` | `requires_judge` marker, `tools` and `config` fixtures, auto `eval` marking |
| `test_scaffold.py` | self-checks for the harness — proves `pytest evals` runs something |

## Planned suites (Phase 2+)

| Suite | Phase | Question |
|---|---|---|
| Intent classification | 2 | directed vs. ambient vs. follow-up vs. stop |
| Orchestrator planning | 2 | does an utterance decompose into a sensible task list? |
| Tool selection | 3 | with 100+ tools registered, is the right handful chosen? |
| Agent routing | 4 | does work reach the agent that should do it? |
| Memory recall | 4 | does the right prior context come back? |
| Idea quality | 4 | thesis, invalidation, and confidence that means something |

The last one is the eval that matters. `Observability.md` names **idea → trade
conversion** and **idea outcome by confidence bucket** as the two metrics that
say whether the system is worth running; this is where that judgement gets
made repeatably.
