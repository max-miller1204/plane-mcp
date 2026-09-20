# Focused Plane MCP

A small Model Context Protocol server for Plane Community Edition v1.4.2.
It calls the Plane REST API directly. It does not use `plane-sdk` and does not switch API versions.

## Tools

The server exposes nine focused tools:

- `credential`
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

## Remote team authentication

Remote mode uses GitHub OAuth to identify each MCP user. Each user registers their own Plane personal access token through a one-time browser setup link. The server encrypts the token before storing it.

This design preserves each user's Plane permissions and activity identity. It does not modify Plane Community Edition.

Create a GitHub OAuth application with this callback URL:

```text
https://your-mcp.example.com/auth/callback
```

Set these variables:

```text
MCP_AUTH_MODE=github
MCP_PUBLIC_URL=https://your-mcp.example.com
GITHUB_OAUTH_CLIENT_ID=replace_me
GITHUB_OAUTH_CLIENT_SECRET=replace_me
GITHUB_ALLOWED_USERS=github-user-one,github-user-two
MCP_JWT_SIGNING_KEY=replace-with-32-random-bytes
PAT_VAULT_KEY=replace-with-a-fernet-key
PAT_VAULT_PATH=/data/plane-mcp.db
XDG_DATA_HOME=/data
PLANE_BASE_URL=https://plane.example.com
PLANE_WORKSPACE_SLUG=my-workspace
```

Generate the signing key and PAT vault key:

```sh
openssl rand -hex 32
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

After OAuth succeeds, call:

```text
credential(action="create_setup_link")
```

Open the returned link. Paste a Plane personal access token into the protected form. The token does not pass through the MCP client or model.

## Local stdio mode

Set these variables:

```text
PLANE_BASE_URL=https://plane.example.com
PLANE_API_KEY=plane_api_replace_me
PLANE_WORKSPACE_SLUG=my-workspace
```

Run:

```sh
uv run plane-mcp stdio
```

## Legacy bearer mode

Set `MCP_AUTH_MODE=bearer` and `MCP_AUTH_TOKEN`. Then run:

```sh
uv run plane-mcp http
```

The HTTP MCP endpoint is `/mcp`. The unauthenticated health endpoint is `/health`.

## Test

```sh
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## Railway

Deploy this directory as a Railway service. Railway detects the `Dockerfile`.
Mount a persistent volume at `/data`. The container reads Railway's `PORT` variable and starts the HTTP transport.
