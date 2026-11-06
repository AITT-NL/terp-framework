from terp.core import SecurityConfig, create_app

app = create_app(modules=[], security=SecurityConfig())
