"""GitHub OAuth identity and access policy helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastmcp.server.dependencies import get_access_token


@dataclass(frozen=True)
class GitHubIdentity:
    user_id: str
    login: str


def allowed_github_users() -> set[str]:
    raw = os.environ.get("GITHUB_ALLOWED_USERS", "")
    users = {value.strip().casefold() for value in raw.split(",") if value.strip()}
    if not users:
        raise RuntimeError("GITHUB_ALLOWED_USERS must contain at least one GitHub login")
    return users


def current_identity() -> GitHubIdentity:
    token = get_access_token()
    if token is None:
        raise PermissionError("GitHub OAuth authentication is required")
    user_id = str(token.claims.get("sub", "")).strip()
    login = str(token.claims.get("login", "")).strip()
    if not user_id or not login:
        raise PermissionError("The OAuth token does not contain a GitHub identity")
    if login.casefold() not in allowed_github_users():
        raise PermissionError(f"GitHub user {login!r} is not allowed to use this MCP")
    return GitHubIdentity(user_id=user_id, login=login)
