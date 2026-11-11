"""Compliant: an attribute on the app's own objects, and on a library the framework does not read."""

import mailer_sdk
from fastapi import APIRouter

from app import defaults

mailer_sdk.timeout_seconds = 5
defaults.PAGE_SIZE = 50

router = APIRouter()
router.tags = ["notes"]
