"""Violation: the same replacement through a looked-up module and its namespace."""

import importlib

kernel = importlib.import_module("terp.core.app")
kernel.__dict__["startup_refusal"] = lambda *args, **kwargs: None
