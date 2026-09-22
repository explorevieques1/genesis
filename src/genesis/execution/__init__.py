# Spec: Genesis Markdown/20-Agents/Execution/Execution Family.md
"""The order path. Every module here is ``tier: none``: rules and arithmetic.

    proposal -> risk.evaluate -> approval.issue -> order_manager.place_approved
             -> ibkr_broker -> IBKR (paper)

There is no ``place_order``. The only way to the broker is an approval the risk
engine issued for that exact order, used once, within its TTL.
"""
