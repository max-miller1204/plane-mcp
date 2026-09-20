# Focused Plane MCP

A small Model Context Protocol server for Plane Community Edition v1.4.2.
It calls the Plane REST API directly. It does not use `plane-sdk` and does not switch API versions.

## Tools

The server exposes eight tools:

- `plane_context`
- `project`
- `work_item`
- `comment`
- `cycle`
- `module`
- `catalog`
- `relation`

Use readable project identifiers, cycle names, module names, and work-item keys such as `DEV-42`.
Delete operations require `confirm=true`.

## Configuration

Set these variables:

```text
PLANE_BASE_URL=https://plane.example.com
PLANE_API_KEY=plane_api_replace_me
PLANE_WORKSPACE_SLUG=my-workspace
MCP_AUTH_TOKEN=replace-with-a-long-random-value
```

Create a Plane personal access token in Profile Settings, then select Personal Access Tokens.

## Run locally

Run the stdio transport:

```sh
uv run plane-mcp stdio
```

Run the streamable HTTP transport:

```sh
uv run plane-mcp http
```

The HTTP MCP endpoint is `/mcp`. Send `Authorization: Bearer <MCP_AUTH_TOKEN>` with each request.
The unauthenticated health endpoint is `/health`.

## Test

```sh
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Railway

Deploy this directory as a Railway service. Railway detects the `Dockerfile`.
Set `PLANE_BASE_URL` to the public Plane URL first. Use private networking only after you verify the Plane AIO service accepts the internal host header.

Generate the MCP token:

```sh
openssl rand -hex 32
```

The container reads Railway's `PORT` variable and starts the HTTP transport.
