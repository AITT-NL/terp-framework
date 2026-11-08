"""Compliant: an error a module raises is a typed AppError, which the envelope renders."""

from terp.core import AppError, create_app


class InvoiceAlreadyPostedError(AppError):
    status_code = 409
    code = "invoice_already_posted"
    default_message = "This invoice is posted, so it can no longer change."


app = create_app([])
