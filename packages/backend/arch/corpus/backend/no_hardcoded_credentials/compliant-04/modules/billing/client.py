"""Compliant: credential-shaped names whose VALUE cannot be a credential.

The name matcher is broad on purpose — narrowing the word list would lose real
findings — so these three shapes are decided on what the string holds instead.

Each pattern below has to REFUSE a password to earn its place, which is a sharper
bar than "looks plausible": ``hunter2`` is a valid identifier, a valid header name
and a valid environment variable name once upper-cased, so an identifier-shaped
exemption would exempt exactly the passwords people write. The conventions do the
discriminating: an environment variable's name is multi-word, a header's name is
hyphenated, a path starts at a root, and a field name spells itself.

This matters beyond noise. The escape-hatch budget is the only friction metric a
Terp app has and its only ratchet; once a reviewer learns that a marker for this
rule is usually nothing, the one that is something gets the same glance.
"""

import os

# 1. The module itself uses the literal as an environment key — it is stating, in
#    code, that the string is the NAME of a credential rather than one.
TOKEN_ENV = "BILLING_API_TOKEN"
PASSWORD_ENV = "BILLING_API_PASSWORD"
token = os.environ[TOKEN_ENV]
password = os.getenv(PASSWORD_ENV)

# 2. A suffix that says what the value is, with the grammar that claim implies.
CLIENT_SECRET_ENV = "BILLING_CLIENT_SECRET"
TOKEN_PATH = "/api/v1/auth/token"
API_KEY_PATH = "./secrets/billing.json"
AUTH_TOKEN_HEADER = "X-Auth-Token"
API_KEY_HEADER = "Authorization"

#    ...and where no grammar can tell a field name from a password, the value has
#    to spell the name itself — the self-naming enum member, generalised.
CLIENT_SECRET_FIELD = "client_secret"
ACCESS_TOKEN_PARAM = "access-token"

# 3. A _FORMAT / _TEMPLATE / _PATTERN name whose literal carries a substitution slot
#    is a wire FORMAT: the part that would be secret is the part that is not there.
#    The suffix is required — see violation-07 for why the value alone cannot decide.
AUTH_TOKEN_FORMAT = "Bearer {token}"
API_KEY_TEMPLATE = "key=%s"
