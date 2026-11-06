from terp.core import create_app

app = create_app(modules=[])
app.add_middleware(object)
