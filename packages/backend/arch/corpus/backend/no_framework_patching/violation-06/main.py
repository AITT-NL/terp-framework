"""Violation: the framework's settings object rewritten, so a deployed app reads as local."""

from terp.core.config import settings

settings.ENVIRONMENT = "local"
