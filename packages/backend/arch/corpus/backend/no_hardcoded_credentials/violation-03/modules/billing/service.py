"""Violation: credential-shaped targets beyond a plain name — attribute, annotated, chained."""


class BillingClient:
    api_key: str = "sk_live_1234567890"

    def configure(self) -> None:
        self._auth_token = "Bearer abc.def.ghi"


password = admin_password = "hunter2"
