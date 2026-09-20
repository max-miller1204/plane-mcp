"""Run the focused Plane MCP server over stdio or streamable HTTP."""

from __future__ import annotations

import os
import sys
from secrets import compare_digest

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from .server import mcp


class BearerTokenMiddleware:
    """Require the configured bearer token for remote MCP requests."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"").decode("utf-8")
        expected = f"Bearer {self.token}"
        if not compare_digest(supplied, expected):
            response = PlainTextResponse("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "focused-plane-mcp"})


def build_http_app() -> Starlette:
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    if not token:
        raise ValueError("MCP_AUTH_TOKEN is required for HTTP mode")
    mcp_app = BearerTokenMiddleware(mcp.http_app(stateless_http=True), token)
    return Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.app.lifespan,
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    for name in ("PLANE_BASE_URL", "PLANE_API_KEY", "PLANE_WORKSPACE_SLUG"):
        if not os.environ.get(name):
            raise ValueError(f"{name} is required")
    if mode == "stdio":
        mcp.run()
        return
    if mode != "http":
        raise ValueError("mode must be 'stdio' or 'http'")
    uvicorn.run(
        build_http_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
