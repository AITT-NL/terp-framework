"""Violation: the exempt shapes worn by values that are credentials anyway.

A suffix is not a password. Each line below carries a name that would qualify for
one of the structural exemptions and a value that disqualifies it, so a checker
that reads only the name — in either direction — gets every one of them wrong.
"""

TOKEN_ENV = "sk-live-abc123"
TOKEN_ENV_UPPER_SINGLE_WORD = "HUNTER2"
TOKEN_PATH = "sk-live-abc123"
AUTH_TOKEN_HEADER = "Bearer abc def"
CLIENT_SECRET_FIELD = "hunter2"
auth_token = "Bearer abc.def.ghi"
