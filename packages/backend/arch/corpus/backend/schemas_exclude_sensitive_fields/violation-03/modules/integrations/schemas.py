from terp.core import BaseSchema


class IntegrationRead(BaseSchema):
    client_secret: str
    private_key: str
    refresh_token: str
