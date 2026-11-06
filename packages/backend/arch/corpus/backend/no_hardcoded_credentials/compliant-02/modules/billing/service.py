"""Compliant near-misses: credential-adjacent code that must stay clean.

* a credential-shaped name is fine when the value is dynamic (env read) or not a
  string (a numeric policy knob);
* names that merely resemble the credential words (``passphrase_env``,
  ``credentials_path``) are not in the shape list;
* comments and truncated look-alike tokens are not secrets.
"""

import os

token_kind = os.environ.get("TOKEN_KIND", "opaque")
password_min_length = 12
passphrase_env = "BILLING_PASSPHRASE"
credentials_path = "/run/secrets/billing.json"

# password = "hunter2" in a comment must not fire.
EXAMPLE_DOC = "an AKIA_EXAMPLE_NOT_A_KEY placeholder is not a real AWS key id"
