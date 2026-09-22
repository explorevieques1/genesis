# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""Everything Genesis knows about an issuer that is not a bar.

Afferent, tier 3, and deliberately not real-time: a sector does not change
intraday and a 10-Q is not restated while you look at it. Nothing here may
reach [[Pre-Trade Risk Engine]], which reads tier 1 and nothing else.

``resolve("NVDA")`` is the entry point.
"""

from __future__ import annotations

__all__ = ["CompanyProfile", "CompanyStore", "resolve", "summarise"]


def __getattr__(name: str):  # noqa: ANN202
    if name in ("resolve", "summarise"):
        from genesis.company import profile as _profile

        return getattr(_profile, name)
    if name == "CompanyProfile":
        from genesis.company.schema import CompanyProfile

        return CompanyProfile
    if name == "CompanyStore":
        from genesis.company.store import CompanyStore

        return CompanyStore
    raise AttributeError(name)
