"""Password strength policy — the credential-strength control (Tier-B, ADR 0006/0032).

A safe default closes the gap that for a long time left Terp with only a
``max_length`` DoS cap on passwords and **zero** strength rules. Password strength
is **Tier-B** (design §10): the *shape* is the framework's (a minimum length, a
character-class floor, a cheap common-/breached-shaped denylist), the *content* —
how long, how many classes — is the consumer's to override, never the shape. The
DoS ``max_length`` cap on the schema field is a separate, never-weakened control;
this adds the strength floor.

Layering: ``terp.core`` (layer 0) must not import a capability, so this module is
the **seam** only — a typed :class:`PasswordPolicy` registry with a safe default,
the process-global active policy installed by ``create_app``, and
:func:`validate_password`, which raises the typed :class:`WeakPasswordError` (the
uniform envelope). The auth/users capabilities import ``terp.core`` and enforce it
at the credential write boundary; core never imports them.

Two-layer enforcement (ADR 0006): the runtime half is :func:`validate_password`
(fail-closed at the credential boundary — provision, reset, self-service change);
the construction/boot half is :meth:`PasswordPolicy.production_problems`, which
``create_app`` consults so a *relaxed* policy refuses to boot in production. Like
session management (ADR 0031), the pattern is entirely runtime/registry — there is
no agent-authored code shape to police — so **no ``terp.arch`` rule applies**.
Turning strength off is a conscious, greppable act (:meth:`PasswordPolicy.relaxed`),
mirroring ``CorsPolicy.disabled`` / ``AuditPolicy.disabled``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from terp.core.errors import AppError

# A small, cheap denylist of common / breached-shaped passwords (lowercased). Not a
# full breach corpus — that is a product concern an app layers on; this is the
# safe-default floor that rejects the passwords every credential-stuffing list leads
# with. Matched case-insensitively, before the character-class count.
_DEFAULT_DENYLIST: Final[tuple[str, ...]] = (
    "password",
    "passw0rd",
    "password1",
    "qwerty",
    "qwertyuiop",
    "12345678",
    "123456789",
    "1234567890",
    "letmein",
    "iloveyou",
    "admin",
    "welcome",
    "monkey",
    "dragon",
    "abc12345",
    "changeme",
    "trustno1",
)

_MIN_SAFE_LENGTH: Final[int] = 8


class WeakPasswordError(AppError):
    """422 — the password fails the active strength policy (length/classes/denylist)."""

    status_code = 422
    code = "weak_password"
    default_message = "The password does not meet the strength policy."


def _character_classes(password: str) -> int:
    """How many of {lowercase, uppercase, digit, symbol} *password* contains."""
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(not c.isalnum() for c in password)
    return sum((has_lower, has_upper, has_digit, has_symbol))


@dataclass(frozen=True)
class PasswordPolicy:
    """The single password-strength declaration consumed by the credential boundary.

    Tier-B: a consumer overrides the *values* (a longer minimum, more classes, extra
    denied terms) but never the *shape*. The default is production-safe, so a credential
    is strong with zero wiring. A relaxed policy (strength off) is allowed only as an
    explicit, justified opt-out (:meth:`relaxed`) and is refused at production boot.
    """

    min_length: int = 12
    min_character_classes: int = 2
    denylist: tuple[str, ...] = _DEFAULT_DENYLIST
    relaxed_reason: str | None = None

    def __post_init__(self) -> None:
        if self.min_length < 1:
            raise ValueError("PasswordPolicy.min_length must be at least 1")
        if not 1 <= self.min_character_classes <= 4:
            raise ValueError("PasswordPolicy.min_character_classes must be between 1 and 4")

    @classmethod
    def default(cls) -> PasswordPolicy:
        """The safe default: 12+ chars, 2+ character classes, common-password denylist."""
        return cls()

    @classmethod
    def relaxed(cls, *, reason: str) -> PasswordPolicy:
        """Strength off (only the DoS ``max_length`` cap remains) as a justified opt-out.

        Mirrors ``CorsPolicy.disabled`` / ``AuditPolicy.disabled``: a security control may
        not be silently absent. Production boot refuses a relaxed policy, so dropping the
        floor is a deliberate, greppable decision — not an accident.
        """
        if not reason or not reason.strip():
            raise ValueError("PasswordPolicy.relaxed(reason=...) requires a non-empty justification")
        return cls(min_length=1, min_character_classes=1, denylist=(), relaxed_reason=reason.strip())

    @property
    def is_relaxed(self) -> bool:
        return self.relaxed_reason is not None

    def violations(self, password: str) -> list[str]:
        """Every reason *password* is rejected (empty when it satisfies the policy)."""
        problems: list[str] = []
        if len(password) < self.min_length:
            problems.append(f"must be at least {self.min_length} characters")
        if _character_classes(password) < self.min_character_classes:
            problems.append(
                f"must mix at least {self.min_character_classes} of lowercase, "
                "uppercase, digits, and symbols"
            )
        lowered = password.lower()
        if any(term in lowered for term in self.denylist):
            problems.append("must not be a common or easily guessed password")
        return problems

    def validate(self, password: str) -> None:
        """Raise :class:`WeakPasswordError` if *password* fails the policy (fail closed)."""
        problems = self.violations(password)
        if problems:
            raise WeakPasswordError(f"Weak password: {'; '.join(problems)}.")

    def production_problems(self) -> list[str]:
        """Reasons this policy is unsafe to boot in production (relaxed = no floor)."""
        if self.is_relaxed:
            return [
                f"password strength is relaxed ({self.relaxed_reason!r}); production must "
                "keep a strength floor — use PasswordPolicy.default() (or raise its values)"
            ]
        if self.min_length < _MIN_SAFE_LENGTH:
            return [
                f"password min_length {self.min_length} is below the safe floor "
                f"({_MIN_SAFE_LENGTH}); raise it before production"
            ]
        return []


_active_policy: PasswordPolicy = PasswordPolicy.default()


def configure_password_policy(policy: PasswordPolicy) -> None:
    """Install the active password *policy* (called once by ``create_app``)."""
    global _active_policy
    _active_policy = policy


def reset_password_policy_runtime() -> None:
    """Restore the safe default policy (the composition-root/test baseline)."""
    global _active_policy
    _active_policy = PasswordPolicy.default()


def active_password_policy() -> PasswordPolicy:
    """The policy currently in force (the default until ``create_app`` installs one)."""
    return _active_policy


def validate_password(password: str) -> None:
    """Enforce the active policy at the credential boundary (raises ``WeakPasswordError``)."""
    _active_policy.validate(password)


__all__ = [
    "PasswordPolicy",
    "WeakPasswordError",
    "active_password_policy",
    "configure_password_policy",
    "reset_password_policy_runtime",
    "validate_password",
]
