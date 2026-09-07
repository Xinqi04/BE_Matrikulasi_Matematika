"""Bound multipart bodies before Starlette spools uploaded files to disk."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette._utils import get_route_path

from app.config import get_settings


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or get_route_path(scope).rstrip("/") != "/pdf/extract":
            return await self.app(scope, receive, send)
        # Allow multipart headers and form fields in addition to the file limit.
        limit = (get_settings().max_pdf_upload_mb + 1) * 1024 * 1024
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Content-Length tidak valid"}, 400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({"detail": "Ukuran upload melebihi batas"}, 413)(scope, receive, send)
        received = 0
        exceeded = False

        async def bounded_receive():
            nonlocal received, exceeded
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                exceeded = True
                # Multipart parser closes its temporary files on this exception.
                raise MultiPartException("Ukuran upload melebihi batas")
            return message

        async def bounded_send(message):
            if exceeded and message["type"] == "http.response.start":
                message = {**message, "status": 413}
            await send(message)

        await self.app(scope, bounded_receive, bounded_send)
