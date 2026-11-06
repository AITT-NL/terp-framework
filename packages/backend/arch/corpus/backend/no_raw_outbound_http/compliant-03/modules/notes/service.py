"""Compliant near-misses: names that contain a restricted root without being it.

``socketserver`` is not ``socket``; ``httpx_mock`` is not ``httpx``; a comment
or string naming a client is not an import.
"""

from socketserver import BaseRequestHandler

import httpx_mock

# import httpx would be refused here.
CLIENT_DOC = "outbound calls never 'import requests'; use the declared capability"
