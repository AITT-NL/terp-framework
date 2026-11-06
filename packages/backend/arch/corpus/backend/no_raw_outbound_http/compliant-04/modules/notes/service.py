"""Compliant near-miss: the mail FORMAT library is not a mail client.

``email.message`` builds and parses messages and opens no connection; only
``smtplib`` reaches a relay, and that is what the rule refuses.
"""

from email.message import EmailMessage
from email.utils import formataddr
