"""Violation: the lower-level escape routes — http.client and an urllib3 submodule."""

from http.client import HTTPSConnection

import urllib3.util
