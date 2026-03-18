"""Fake HTTP response objects for testing.

Replaces MagicMock-based HTTP mocks with typed, predictable fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class FakeHTTPResponse:
    """Fake httpx-style response with status_code, json(), and text."""

    status_code: int
    body: dict | list | str | None = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        """Return the body as parsed JSON."""
        return self.body

    def raise_for_status(self) -> None:
        """Raise httpx.HTTPStatusError if status_code >= 400."""
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://fake.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )


class FakeURLResponse:
    """Fake urllib-style response with read(), context manager, and headers.

    Mimics the object returned by urllib.request.urlopen().
    """

    def __init__(
        self,
        data: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._data = data
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        """Return response body as bytes."""
        return self._data

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get a header value (dict-style)."""
        return self.headers.get(key, default)

    def __enter__(self) -> FakeURLResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class FakeAsyncHTTPClient:
    """Fake httpx.AsyncClient for testing async code.

    Supports get, delete, post methods and async context manager protocol.
    """

    def __init__(
        self,
        default_response: FakeHTTPResponse | None = None,
        responses: dict[str, FakeHTTPResponse] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self._default_response = default_response or FakeHTTPResponse(status_code=200)
        self._responses = responses or {}
        self._side_effect = side_effect
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self) -> FakeAsyncHTTPClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def _resolve(self, method: str, url: str, **kwargs: Any) -> FakeHTTPResponse:
        self.calls.append((method, url, kwargs))
        if self._side_effect:
            raise self._side_effect
        return self._responses.get(url, self._default_response)

    async def get(self, url: str, **kwargs: Any) -> FakeHTTPResponse:
        """Fake GET request."""
        return self._resolve("GET", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> FakeHTTPResponse:
        """Fake DELETE request."""
        return self._resolve("DELETE", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> FakeHTTPResponse:
        """Fake POST request."""
        return self._resolve("POST", url, **kwargs)
