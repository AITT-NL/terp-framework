"""Federated identity links — the identity backing for SSO logins (ADR 0058).

The OIDC capability owns *protocol*; this owns the *rows*: which local user an
external ``(issuer, subject)`` identity resolves to. Linking is keyed on that
OIDC-stable pair and **never** on email alone — an IdP can reassign an email, so an
email match would be an account-takeover vector.

Writes (a link, a JIT-provisioned user) route through the audited ``BaseService``
chokepoint, so every federated link and every provisioned account lands an audit
record. JIT provisioning is **off by default**: an app opts in with
``allow_provisioning=True``, and even then a provisioned account requires a
**verified** email claim, is created at the given (lowest, by default) rank with
**no local password** (``hashed_password=None`` — password login refuses it), and is
never auto-linked onto an existing user with the same email.

Opting in also requires saying **whose** identities may be provisioned —
``allowed_email_domains`` for the usual case, ``provision_allowed`` for a rule that
is not a list of domains. Verified-email is a check on the claim, not on who may
hold one: point the app at a multi-tenant IdP (an app registration left open to any
directory, which is an ordinary configuration mistake) and every other gate here
still passes for an account nobody in this deployment has heard of. Outside
production the allowlist is optional, so a local run against a test IdP needs no
ceremony; in production its absence refuses at construction.

What the allowlist cannot say is "let them in, but not yet". Both of the knobs above
are admission rules evaluated once, and the account they admit is live the moment it
exists — because the *lowest* rank is not "no access": a rung is a floor that modules
read, so `viewer` is already whatever an application's `role:viewer` routes chose to
expose. An application wanting the ordinary internal-tool shape — anyone the directory
vouches for may ask for an account, a human decides whether it opens — had nowhere to
put the second half. ``provisioned_active=False`` is that seam: the row and its link
are written, this login is refused, and the account waits for an administrator exactly
as a deactivated one does (ADR 0142).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable

from sqlmodel import Field, Session, select

from terp.core import (
    AuditAction,
    BaseSchema,
    BaseService,
    BaseUpdateSchema,
    Roles,
    settings,
)

from terp.capabilities.identity.models import FederatedIdentity, User

#: Decide whether a verified email may have an account provisioned for it. The
#: richer half of the allowlist seam: a deployment whose rule is not "one of these
#: domains" (a directory lookup, a joiners feed, an invitation table) writes it here
#: rather than being pushed back onto verified-email-only, which is no rule at all.
ProvisionGate = Callable[[str], bool]

_logger = logging.getLogger("terp.capabilities.identity.federated")


class FederatedIdentityLink(BaseSchema):
    """The create DTO for a federated link (an explicit admin/app-driven link)."""

    user_id: uuid.UUID
    issuer: str = Field(max_length=512)
    subject: str = Field(max_length=255)


class FederatedIdentityUpdate(BaseUpdateSchema):
    """A federated link is immutable: it is created or removed, never edited.

    Present only to satisfy the service's generic shape; it declares no editable
    fields, so an ``update`` can change nothing but still carries the OCC version.
    """


class FederatedIdentityService(
    BaseService[FederatedIdentity, FederatedIdentityLink, FederatedIdentityUpdate]
):
    """Resolve / link / (optionally) JIT-provision users for SSO logins."""

    model = FederatedIdentity

    def __init__(
        self,
        *,
        allow_provisioning: bool = False,
        provisioned_rank: int = int(Roles.VIEWER),
        provisioned_active: bool = True,
        allowed_email_domains: Iterable[str] | None = None,
        provision_allowed: ProvisionGate | None = None,
    ) -> None:
        domains = (
            None
            if allowed_email_domains is None
            else tuple(domain.strip().lower().lstrip("@") for domain in allowed_email_domains)
        )
        if domains is not None and (not domains or not all(domains)):
            raise ValueError(
                "allowed_email_domains must name at least one non-empty domain; pass "
                "None to decline the allowlist (and supply provision_allowed instead)"
            )
        self._allow_provisioning = allow_provisioning
        self._provisioned_rank = provisioned_rank
        self._provisioned_active = provisioned_active
        self._allowed_email_domains = domains
        self._provision_allowed = provision_allowed

        # Fail-closed at construction, the shape OIDCProviderConfig already uses for its
        # own production invariants — but decided by an environment-INDEPENDENT predicate,
        # so the answer exists somewhere a gate can read it and not only inside a branch
        # that runs on the production host. Outside production the same state is spoken
        # aloud rather than tolerated in silence: permissive in the inner loop, never
        # quiet, which is the asymmetry ADR 0128 names as deliberate.
        problems = self.production_problems()
        if problems:
            if settings.is_production:
                raise ValueError(
                    "; ".join(problems)
                    + ". Pass allowed_email_domains=(...) for the usual case, or "
                    "provision_allowed=<callable> to decide per claim."
                )
            _logger.warning(
                "federated identity is UNGATED in this deployment: %s. A production boot "
                "is REFUSED in this state.",
                "; ".join(problems),
            )

    def production_problems(self) -> list[str]:
        """What a production boot refuses about this declaration, environment-independent.

        The same shape ``ControlPlane`` uses, and for the same reason: the question "would
        this configuration boot in production" must be answerable off the production host,
        by a gate, from the declaration alone. A constructor that raises is the enforcement;
        it is not an answer anything else can ask for.

        Verified-email is a check on the *claim*, not on who may hold one. Against a
        multi-tenant IdP — an app registration left open to any directory, which is an
        ordinary configuration mistake and not an exotic one — every other gate here still
        passes for an account nobody in this deployment has heard of, and the result is open
        registration into the platform. The answer has to be a statement about which
        identities this deployment accepts, and there is no safe value to guess.
        """
        if (
            self._allow_provisioning
            and self._allowed_email_domains is None
            and self._provision_allowed is None
        ):
            return [
                "FederatedIdentityService(allow_provisioning=True) requires an identity "
                "allowlist in production: verified-email alone means anyone the configured "
                "IdP will authenticate gets an account"
            ]
        return []

    def _may_provision(self, email: str) -> bool:
        """Whether *email* is an identity this deployment provisions accounts for.

        Both gates apply when both are given, and a refusal from either is final: an
        allowlist that a callback could widen would not be an allowlist. Absent both,
        this is the pre-allowlist behaviour — permitted outside production, refused at
        construction inside it.
        """
        domain = email.rpartition("@")[2].lower()
        if self._allowed_email_domains is not None and domain not in self._allowed_email_domains:
            return False
        # An exact match, never a suffix: accepting every subdomain of a listed domain
        # hands provisioning to whoever controls one, and a deployment that wants
        # `sub.example.test` can say so in one more tuple entry.
        return self._provision_allowed is None or self._provision_allowed(email)

    def get_link(
        self, session: Session, issuer: str, subject: str
    ) -> FederatedIdentity | None:
        """The link row for ``(issuer, subject)``, or ``None``."""
        return session.exec(
            select(FederatedIdentity).where(
                FederatedIdentity.issuer == issuer,
                FederatedIdentity.subject == subject,
            )
        ).first()

    def link(
        self, session: Session, *, user_id: uuid.UUID, issuer: str, subject: str
    ) -> FederatedIdentity:
        """Link *user_id* to the external identity — an explicit, audited act."""
        row = FederatedIdentity(user_id=user_id, issuer=issuer, subject=subject)
        return self._save(session, row, AuditAction.CREATED)

    def resolve_or_provision(
        self,
        session: Session,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        email_verified: bool,
    ) -> User | None:
        """The user an SSO login resolves to, or ``None`` when it must be refused.

        A linked identity resolves to its user only while that user is **active**. An
        unlinked identity is refused unless JIT provisioning is enabled — and even
        then only with a **verified** email claim, and never when a user with that
        email already exists (auto-linking by email is the account-takeover vector;
        link the existing account explicitly via :meth:`link` instead).

        Under ``provisioned_active=False`` a first login **writes** the account and its
        link and still returns ``None``: the rows record that someone asked, and an
        administrator decides whether the door opens. Every later attempt then takes the
        linked path above and is refused by the same ``is_active`` check that holds a
        deactivated account, so activation is the one act that admits them and no second
        state has to be invented for it.
        """
        existing = self.get_link(session, issuer, subject)
        if existing is not None:
            user = session.get(User, existing.user_id)
            if user is None or not user.is_active:
                return None
            return user
        if not self._allow_provisioning:
            return None
        if not email or not email_verified:
            return None
        if not self._may_provision(email):
            # A verified claim from an identity this deployment does not provision for.
            # Refused as a plain "no account", identical to every other refusal here, so
            # the response cannot be used to enumerate which domains are accepted.
            return None
        already = session.exec(select(User).where(User.email == email)).first()
        if already is not None:
            return None
        user = User(
            email=email,
            hashed_password=None,  # SSO-only: no local credential (ADR 0058)
            role=self._provisioned_rank,
            is_active=self._provisioned_active,
        )
        self._save(session, user, AuditAction.CREATED)  # type: ignore[arg-type]
        self.link(session, user_id=user.id, issuer=issuer, subject=subject)
        if not self._provisioned_active:
            # Refusing *here* is the whole of the feature, and returning the row would
            # undo it: the active check sits on the linked path above, which a first
            # login never reaches, so handing this user back would mint a session for an
            # account that is inactive in the database — the one state the caller has no
            # way to notice, since it receives a principal like any other.
            return None
        return user


__all__ = [
    "FederatedIdentityLink",
    "FederatedIdentityService",
    "FederatedIdentityUpdate",
    "ProvisionGate",
]
