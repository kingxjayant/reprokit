"""Shared test fixtures and helpers."""

from __future__ import annotations

import httpx


class FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code: int, payload: dict, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class FakeClient:
    """Replaces httpx.Client in a module under test."""

    def __init__(self, handler, *args, **kwargs):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None, **kwargs):
        return self._handler(url, headers or {})


def patch_client(monkeypatch, module, handler) -> None:
    """Point a module's httpx.Client at a fake handler."""
    monkeypatch.setattr(module.httpx, "Client", lambda *a, **k: FakeClient(handler, *a, **k))


def real_httpx_client_for_reference():  # pragma: no cover
    return httpx.Client
