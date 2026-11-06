"""Violation: aliased and multiline import forms of raw HTTP clients."""

import urllib.request as transport
from aiohttp import (
    ClientSession,
    ClientTimeout,
)
