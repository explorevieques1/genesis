# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""A 400 is not one failure. Account state degrades; a bad body is fatal."""

from genesis.errors import DegradedError, FatalError
from genesis.llm.anthropic_backend import _bad_request


def test_no_credit_degrades_with_an_actionable_message():
    err = _bad_request(
        Exception(
            "Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'Your credit balance is too low "
            "to access the Anthropic API. Please go to Plans & Billing...'}}"
        )
    )
    assert isinstance(err, DegradedError)
    assert "Plans & Billing" in str(err)


def test_unscoped_workspace_degrades_and_names_the_variable():
    err = _bad_request(
        Exception(
            "Error code: 400 - this request must include the "
            "anthropic-workspace-id header with the ID of the workspace to use."
        )
    )
    assert isinstance(err, DegradedError)
    assert "ANTHROPIC_WORKSPACE_ID" in str(err)


def test_a_genuinely_malformed_request_stays_fatal():
    # Retrying our own bug on every utterance burns the voice budget.
    assert isinstance(_bad_request(Exception("max_tokens: must be >= 1")), FatalError)
