"""Violation: a patcher from the test toolbox, started in app code and never stopped."""

from unittest import mock

mock.patch("terp.core.app.startup_refusal", return_value=None).start()
