"""Example-app audit control plane: the audit policy — declared once.

The example app keeps the safe default: **every** mutation is audited, with the
central redaction of credential-bearing payload keys. A real app would tune the
retention window or, only as a conscious and justified act, opt out with
``AuditPolicy.disabled(reason=...)``.
"""

from __future__ import annotations

from terp.core import AuditPolicy

audit = AuditPolicy.default()

__all__ = ["audit"]
