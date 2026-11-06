def dsn() -> str:
    return decrypt_config(settings.DB_DSN)
