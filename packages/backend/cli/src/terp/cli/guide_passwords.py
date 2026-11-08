"""The ``terp guide passwords`` topic: password strength and self-service accounts."""

from __future__ import annotations

TOPIC = """\
Password strength (PasswordPolicy, Tier-B)

- Provisioning and resets enforce the app's PasswordPolicy at the users-service
  credential boundary: a weak password is refused with a typed 422 (code weak_password,
  the uniform envelope), the max_length cap stays the separate DoS guard.
- The safe default is 12+ chars, 2+ character classes, and a common-password denylist
  (length over forced complexity, NIST-aligned). Tier-B: override the VALUES, not shape:
      from terp.core import PasswordPolicy, ControlPlane
      control_plane = ControlPlane(passwords=PasswordPolicy(min_length=16, min_character_classes=3))
- Relaxing strength is an explicit, justified opt-out and is refused at production boot.
  The reason is the opt-out: it is stored as `relaxed_reason` and named back to you in the
  BootError, so "why is this off" always has an answer that travels with the declaration.
      PasswordPolicy.relaxed(reason="legacy bulk import")
- SELF-SERVICE accounts (ADR 0196) hold sign-up and reset to the same policy. They are
  opt-in and never discovered: after configure_mail(...), build the module and mount it
      build_accounts_module(SelfService(reason="members open their own accounts",
          users=users_service, throttle_store=shared_store,
          link_base="https://app.example.com"))
  for POST /api/v1/accounts/sign-up, /verify, /password-reset, /password-reset/confirm
  and /me/close. Sign-up takes only the address: the account opens when the mailed token
  is redeemed at /verify with the password, so whoever asked cannot choose it. Every
  request about an address answers 202 the same way and sends that address exactly one
  message, whether or not it has an account, and addresses compare case-insensitively.
  Tokens are sealed, expire, work once, and ride the URL fragment, so your account pages
  read them from location.hash and post them. Closing needs the password again and ends
  every session (AccountDeletion.SCRUB by default, or REMOVE: building the module refuses
  it while a reference to the user table would refuse the delete, so declare CASCADE or
  SET NULL on that reference; one the build cannot see is scrubbed instead, with a warning).
  Where your login consults a second factor, wire the same one into the declaration
  (SelfService(..., second_factor=MfaService())): closing an account that enrolled one then
  asks for a code from it in mfa_code, a 403 second_factor_required without one and a 403
  second_factor_not_confirmed for a wrong one, which counts toward the backoff as a wrong
  password does.
- No terp.arch check applies (no module code shape to police) — enforcement is the
  service chokepoint plus the create_app production fail-fast.
"""
