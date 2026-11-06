class ConnectorStatus:
    name: str
    api_key: str


@router.get('/status', response_model=ConnectorStatus)
def connector_status() -> ConnectorStatus:
    return ConnectorStatus()
