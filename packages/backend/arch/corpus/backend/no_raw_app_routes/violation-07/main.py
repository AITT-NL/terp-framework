"""Violation: an exception handler on the composed app answers in place of the error envelope."""

from fastapi.responses import JSONResponse

from terp.core import create_app

app = create_app([])


@app.exception_handler(Exception)
async def show_the_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=500)
