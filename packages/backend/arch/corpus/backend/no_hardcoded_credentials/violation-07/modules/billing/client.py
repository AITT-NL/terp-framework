"""Violation: credentials that contain a substitution slot are still credentials.

A wire FORMAT is exempt because the part that would be secret is the part that is not
there. Testing the VALUE alone for a slot does not express that — generated passwords
and pasted service-account JSON contain a brace pair as readily as a template does, so
a value-only test exempts exactly the secrets the rule exists to catch.

So the NAME has to declare it. These five wear the shape and declare nothing.
"""

DB_PASSWORD = "aB3{xY9}qZ"
SERVICE_TOKEN = "tok{}en"
CLIENT_SECRET = "s3cr3t%s"
ADMIN_PASSWORD = "50%d0llars"
API_SECRET = '{"type": "service_account", "private_key_id": "abc"}'
