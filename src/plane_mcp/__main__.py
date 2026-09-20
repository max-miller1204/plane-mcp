"""Run the focused Plane MCP server over stdio or streamable HTTP."""

from __future__ import annotations

import os
import sys
from html import escape
from secrets import compare_digest

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from .client import PlaneClient
from .server import get_vault, mcp


class BearerTokenMiddleware:
    """Require the configured bearer token for legacy remote MCP requests."""

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


def _setup_page(code: str, login: str) -> str:
    safe_code = escape(code, quote=True)
    safe_login = escape(login)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Connect Plane</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      max-width: 36rem;
      margin: 4rem auto;
      padding: 0 1rem;
    }}
    label, input, button {{ display: block; width: 100%; box-sizing: border-box; }}
    input, button {{ margin-top: .5rem; padding: .75rem; }}
    button {{ margin-top: 1rem; cursor: pointer; }}
    code {{ overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <h1>Connect your Plane account</h1>
  <p>GitHub user: <strong>{safe_login}</strong></p>
  <p>Create a Personal Access Token in Plane Profile Settings. Paste it here once.</p>
  <form method="post" action="/setup/token">
    <input type="hidden" name="code" value="{safe_code}">
    <label for="plane_token">Plane personal access token</label>
    <input id="plane_token" name="plane_token" type="password" required autocomplete="off">
    <button type="submit">Validate and store token</button>
  </form>
</body>
</html>"""


async def setup_form(request: Request) -> HTMLResponse:
    code = request.query_params.get("code", "")
    identity = get_vault().setup_identity(code)
    if identity is None:
        return HTMLResponse("Setup link is invalid, expired, or already used.", status_code=400)
    _, login = identity
    return HTMLResponse(
        _setup_page(code, login),
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )


async def setup_token(request: Request) -> HTMLResponse:
    form = await request.form()
    code = str(form.get("code", ""))
    plane_token = str(form.get("plane_token", "")).strip()
    identity = get_vault().setup_identity(code)
    if identity is None:
        return HTMLResponse("Setup link is invalid, expired, or already used.", status_code=400)
    if not plane_token:
        return HTMLResponse("Plane token is required.", status_code=400)

    client = PlaneClient(
        base_url=os.environ["PLANE_BASE_URL"],
        api_key=plane_token,
        workspace_slug=os.environ["PLANE_WORKSPACE_SLUG"],
    )
    try:
        client.list_projects(per_page=1)
    except Exception:
        return HTMLResponse(
            "Plane rejected the token or the token cannot access this workspace.",
            status_code=400,
        )
    finally:
        client.close()

    _, login = get_vault().store_token(code, plane_token)
    return HTMLResponse(
        f"<h1>Connected</h1><p>{escape(login)}, your Plane token is stored securely. "
        "You can close this tab and return to your MCP client.</p>",
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )


def build_http_app() -> Starlette:
    auth_mode = os.environ.get("MCP_AUTH_MODE", "bearer")
    raw_mcp_app = mcp.http_app(stateless_http=True)
    if auth_mode == "github":
        mcp_app = raw_mcp_app
        setup_routes = [
            Route("/setup", endpoint=setup_form, methods=["GET"]),
            Route("/setup/token", endpoint=setup_token, methods=["POST"]),
        ]
    elif auth_mode == "bearer":
        token = os.environ.get("MCP_AUTH_TOKEN", "")
        if not token:
            raise ValueError("MCP_AUTH_TOKEN is required for bearer HTTP mode")
        mcp_app = BearerTokenMiddleware(raw_mcp_app, token)
        setup_routes = []
    else:
        raise ValueError("MCP_AUTH_MODE must be 'bearer' or 'github' for HTTP mode")

    return Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            *setup_routes,
            Mount("/", app=mcp_app),
        ],
        lifespan=raw_mcp_app.lifespan,
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    for name in ("PLANE_BASE_URL", "PLANE_WORKSPACE_SLUG"):
        if not os.environ.get(name):
            raise ValueError(f"{name} is required")
    if mode == "stdio":
        if not os.environ.get("PLANE_API_KEY"):
            raise ValueError("PLANE_API_KEY is required for stdio mode")
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
