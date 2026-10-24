"""The whole site from one process: the API under /api and the built frontend at /.

Serving both from one origin means the sign-in cookie is first-party and the browser
needs no CORS. The frontend already calls /api (frontend/src/api/client.ts), as it does
through the Vite proxy in development. Run with `uvicorn app.site:app`; STATIC_DIR names
the frontend build (frontend/dist), which the root Dockerfile puts in place.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.config import get_settings
from app.main import app as api


class Frontend(StaticFiles):
    """The built single-page app, with long caching for Vite's content-hashed assets
    and none for index.html, so a deploy shows up on the next reload."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                hashed = scope["path"].startswith("/assets/")
                cache = "public, max-age=31536000, immutable" if hashed else "no-cache"
                message.setdefault("headers", []).append((b"cache-control", cache.encode()))
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


# Mounted apps don't run their own startup, so the site runs the API's (the ACLED check).
app = FastAPI(lifespan=lambda _: api.router.lifespan_context(api), docs_url=None, redoc_url=None)
app.mount("/api", api)

static = get_settings().static_dir
if static and Path(static, "index.html").is_file():
    app.mount("/", Frontend(directory=static, html=True), name="frontend")
