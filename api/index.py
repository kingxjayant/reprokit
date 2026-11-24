"""Vercel entrypoint.

Vercel's Python runtime detects an ASGI application exposed as ``app`` and serves
it as a serverless function. Everything else lives in the repo as normal, so the
same code runs on Render/Fly/local uvicorn with no changes.
"""

from app.main import app  # noqa: F401  (Vercel looks for this name)

# Exported so `vercel dev` and the runtime can both find it.
__all__ = ["app"]
