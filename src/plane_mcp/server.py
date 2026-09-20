"""Focused MCP tools for Plane CE v1.4.2."""

from __future__ import annotations

import hashlib
import os
from html import escape
from typing import Any, Literal
from urllib.parse import urlencode

from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider

from .auth import current_identity
from .client import PlaneClient
from .vault import CredentialVault


def _build_auth() -> GitHubProvider | None:
    mode = os.environ.get("MCP_AUTH_MODE", "none")
    if mode in {"none", "bearer"}:
        return None
    if mode != "github":
        raise ValueError("MCP_AUTH_MODE must be 'none', 'bearer', or 'github'")
    return GitHubProvider(
        client_id=os.environ["GITHUB_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
        base_url=os.environ["MCP_PUBLIC_URL"],
        required_scopes=[],
        cache_ttl_seconds=300,
        jwt_signing_key=os.environ["MCP_JWT_SIGNING_KEY"],
        allowed_client_redirect_uris=[
            "http://localhost:*",
            "http://localhost:*/*",
            "http://127.0.0.1:*",
            "http://127.0.0.1:*/*",
            "cursor://anysphere.cursor-mcp/oauth/*",
            "https://www.cursor.com/*",
            "https://vscode.dev/redirect",
            "https://insiders.vscode.dev/redirect",
            "https://claude.ai/*",
            "https://chatgpt.com/connector/oauth/*",
            "https://chatgpt.com/connector_platform_oauth_redirect",
        ],
    )


mcp = FastMCP(
    "Focused Plane MCP",
    instructions=(
        "Manage one Plane CE v1.4.2 workspace. Prefer readable project identifiers and "
        "work-item keys such as DEV-42. Destructive actions require confirm=true."
    ),
    auth=_build_auth(),
)

_clients: dict[str, tuple[str, PlaneClient]] = {}
_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    global _vault
    if _vault is None:
        _vault = CredentialVault.from_env()
    return _vault


def get_client() -> PlaneClient:
    if os.environ.get("MCP_AUTH_MODE", "none") == "github":
        identity = current_identity()
        api_key = get_vault().get_token(identity.user_id)
        if api_key is None:
            raise PermissionError(
                "No Plane token is registered. Call credential(action='create_setup_link') first"
            )
        cache_key = identity.user_id
    else:
        api_key = os.environ["PLANE_API_KEY"]
        cache_key = "stdio"

    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    cached = _clients.get(cache_key)
    if cached is None or cached[0] != fingerprint:
        if cached is not None:
            cached[1].close()
        _clients[cache_key] = (
            fingerprint,
            PlaneClient(
                base_url=os.environ["PLANE_BASE_URL"],
                api_key=api_key,
                workspace_slug=os.environ["PLANE_WORKSPACE_SLUG"],
            ),
        )
    return _clients[cache_key][1]


def _required(value: Any, name: str) -> Any:
    if value is None or value == "" or value == []:
        raise ValueError(f"{name} is required")
    return value


def _confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(f"{action} is destructive. Call again with confirm=true")


def _project_base(client: PlaneClient, project: str) -> tuple[str, dict[str, Any]]:
    return client.project_path(_required(project, "project"))


def _item(client: PlaneClient, item: str, project: str | None) -> tuple[dict[str, Any], str]:
    resolved = client.resolve_work_item(_required(item, "item"), project)
    project_id = str(resolved.get("project_id") or resolved.get("project"))
    if not project_id:
        raise ValueError("Plane did not return the work item's project ID")
    return resolved, f"{client.workspace_path}projects/{project_id}/work-items/{resolved['id']}/"


def _resolve_item_ids(client: PlaneClient, items: list[str], project: str | None) -> list[str]:
    return [str(client.resolve_work_item(item, project)["id"]) for item in items]


def _normalize_work_item_data(
    client: PlaneClient, project: str, data: dict[str, Any]
) -> dict[str, Any]:
    normalized = dict(data)
    if "state" in normalized:
        normalized["state"] = client.resolve_named_resource(
            project, "states", str(normalized["state"])
        )["id"]
    if "labels" in normalized:
        normalized["labels"] = [
            client.resolve_named_resource(project, "labels", str(label))["id"]
            for label in normalized["labels"]
        ]
    if "assignees" in normalized:
        normalized["assignees"] = [
            client.resolve_member(str(member))["id"] for member in normalized["assignees"]
        ]
    if "parent" in normalized:
        normalized["parent"] = client.resolve_work_item(str(normalized["parent"]), project)["id"]
    return normalized


@mcp.tool
def credential(
    action: Literal["status", "create_setup_link", "revoke"],
    confirm: bool = False,
) -> Any:
    """Manage the current GitHub user's encrypted Plane credential."""
    identity = current_identity()
    vault = get_vault()
    if action == "status":
        return {
            "github_login": identity.login,
            "plane_token_registered": vault.has_token(identity.user_id),
        }
    if action == "create_setup_link":
        code = vault.create_setup_code(identity.user_id, identity.login)
        query = urlencode({"code": code})
        return {
            "setup_url": f"{os.environ['MCP_PUBLIC_URL'].rstrip('/')}/setup?{query}",
            "expires_in_seconds": vault.setup_ttl_seconds,
        }
    _confirm(confirm, "credential revoke")
    revoked = vault.revoke(identity.user_id)
    cached = _clients.pop(identity.user_id, None)
    if cached is not None:
        cached[1].close()
    return {"revoked": revoked}


@mcp.tool(annotations={"readOnlyHint": True})
def plane_context(
    action: Literal["health", "workspace_summary", "capabilities"],
    project: str | None = None,
) -> Any:
    """Inspect the configured Plane workspace and this server's supported surface."""
    client = get_client()
    if action == "health":
        projects = client.list_projects(per_page=1)
        return {"ok": True, "workspace": client.workspace_slug, "api_reachable": bool(projects)}
    if action == "capabilities":
        return {
            "plane_version": "v1.4.2",
            "tools": [
                "credential",
                "plane_context",
                "project",
                "work_item",
                "comment",
                "cycle",
                "module",
                "catalog",
                "relation",
            ],
            "unsupported": [
                "relation removal because Plane CE v1.4.2 has no public route",
                "pages because Plane CE v1.4.2 has no public API route",
            ],
        }
    projects = client.list_projects(per_page=100)
    result: dict[str, Any] = {"projects": projects}
    if project:
        base, resolved = _project_base(client, project)
        result["project"] = resolved
        result["states"] = client.request("GET", f"{base}states/", params={"per_page": 100})
        result["labels"] = client.request("GET", f"{base}labels/", params={"per_page": 100})
        result["cycles"] = client.request("GET", f"{base}cycles/", params={"per_page": 100})
        result["modules"] = client.request("GET", f"{base}modules/", params={"per_page": 100})
    return result


@mcp.tool
def project(
    action: Literal["list", "get", "create", "update", "archive", "unarchive"],
    project: str | None = None,
    data: dict[str, Any] | None = None,
    cursor: str | None = None,
    per_page: int = 50,
) -> Any:
    """List or manage projects. Use data for Plane project fields."""
    client = get_client()
    if action == "list":
        params = {"per_page": per_page}
        if cursor:
            params["cursor"] = cursor
        return client.list_projects(**params)
    if action == "create":
        return client.request(
            "POST", f"{client.workspace_path}projects/", data=_required(data, "data")
        )
    base, _ = _project_base(client, _required(project, "project"))
    if action == "get":
        return client.request("GET", base)
    if action == "update":
        return client.request("PATCH", base, data=_required(data, "data"))
    archive_path = f"{base}archive/"
    return client.request("POST" if action == "archive" else "DELETE", archive_path)


@mcp.tool
def work_item(
    action: Literal[
        "list", "get", "search", "create", "update", "delete", "batch_create", "batch_update"
    ],
    project: str | None = None,
    item: str | None = None,
    query: str | None = None,
    data: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
    filters: dict[str, Any] | None = None,
    cursor: str | None = None,
    per_page: int = 50,
    confirm: bool = False,
    dry_run: bool = False,
) -> Any:
    """Manage work items. References can be UUIDs or readable keys such as DEV-42."""
    client = get_client()
    if action == "search":
        if cursor:
            raise ValueError("Plane CE v1.4.2 work-item search does not support cursors")
        params: dict[str, Any] = {
            "search": _required(query, "query"),
            "limit": min(per_page, 100),
        }
        if project:
            params["project_id"] = client.resolve_project(project)["id"]
        return client.request("GET", f"{client.workspace_path}work-items/search/", params=params)
    if action == "get":
        return client.resolve_work_item(_required(item, "item"), project)

    base, _ = _project_base(client, _required(project, "project"))
    collection = f"{base}work-items/"
    if action == "list":
        params = dict(filters or {})
        params["per_page"] = per_page
        if cursor:
            params["cursor"] = cursor
        return client.request("GET", collection, params=params)
    if action == "create":
        payload = _normalize_work_item_data(client, project, _required(data, "data"))
        return client.request("POST", collection, data=payload)
    if action == "batch_create":
        payloads = [
            _normalize_work_item_data(client, project, payload)
            for payload in _required(items, "items")
        ]
        if dry_run:
            return {"dry_run": True, "requests": payloads}
        return [client.request("POST", collection, data=payload) for payload in payloads]
    if action == "batch_update":
        updates = _required(items, "items")
        prepared = []
        for update in updates:
            reference = _required(update.get("item"), "items[].item")
            payload = _normalize_work_item_data(
                client, project, _required(update.get("data"), "items[].data")
            )
            resolved = client.resolve_work_item(reference, project)
            prepared.append({"id": resolved["id"], "data": payload})
        if dry_run:
            return {"dry_run": True, "requests": prepared}
        return [
            client.request("PATCH", f"{collection}{entry['id']}/", data=entry["data"])
            for entry in prepared
        ]

    resolved = client.resolve_work_item(_required(item, "item"), project)
    detail = f"{collection}{resolved['id']}/"
    if action == "update":
        payload = _normalize_work_item_data(client, project, _required(data, "data"))
        return client.request("PATCH", detail, data=payload)
    _confirm(confirm, "work_item delete")
    return client.request("DELETE", detail)


@mcp.tool
def comment(
    action: Literal["list", "get", "add", "update", "delete"],
    item: str,
    project: str | None = None,
    comment_id: str | None = None,
    body: str | None = None,
    comment_html: str | None = None,
    access: Literal["INTERNAL", "EXTERNAL"] = "INTERNAL",
    confirm: bool = False,
) -> Any:
    """Manage work-item comments. Plain body text is safely converted to HTML."""
    client = get_client()
    _, item_path = _item(client, item, project)
    collection = f"{item_path}comments/"
    if action == "list":
        return client.request("GET", collection)
    if action == "add":
        html = (
            comment_html
            if comment_html is not None
            else f"<p>{escape(_required(body, 'body'))}</p>"
        )
        return client.request("POST", collection, data={"comment_html": html, "access": access})
    detail = f"{collection}{_required(comment_id, 'comment_id')}/"
    if action == "get":
        return client.request("GET", detail)
    if action == "update":
        html = (
            comment_html
            if comment_html is not None
            else f"<p>{escape(_required(body, 'body'))}</p>"
        )
        return client.request("PATCH", detail, data={"comment_html": html, "access": access})
    _confirm(confirm, "comment delete")
    return client.request("DELETE", detail)


@mcp.tool
def cycle(
    action: Literal[
        "list",
        "get",
        "create",
        "update",
        "delete",
        "archive",
        "unarchive",
        "list_items",
        "add_items",
        "remove_items",
        "transfer_items",
    ],
    project: str,
    cycle: str | None = None,
    data: dict[str, Any] | None = None,
    items: list[str] | None = None,
    target_cycle: str | None = None,
    confirm: bool = False,
) -> Any:
    """Manage cycles and cycle membership. Cycle names and work-item keys are accepted."""
    client = get_client()
    base, _ = _project_base(client, project)
    collection = f"{base}cycles/"
    if action == "list":
        return client.request("GET", collection, params={"per_page": 100})
    if action == "create":
        return client.request("POST", collection, data=_required(data, "data"))
    if action == "unarchive":
        archived = client.resolve_path(f"{base}archived-cycles/", _required(cycle, "cycle"), "name")
        return client.request("DELETE", f"{base}archived-cycles/{archived['id']}/unarchive/")
    cycle_obj = client.resolve_named_resource(project, "cycles", _required(cycle, "cycle"))
    detail = f"{collection}{cycle_obj['id']}/"
    if action == "get":
        return client.request("GET", detail)
    if action == "update":
        return client.request("PATCH", detail, data=_required(data, "data"))
    if action == "delete":
        _confirm(confirm, "cycle delete")
        return client.request("DELETE", detail)
    if action == "archive":
        return client.request("POST", f"{detail}archive/")
    membership = f"{detail}cycle-issues/"
    if action == "list_items":
        return client.request("GET", membership)
    ids = _resolve_item_ids(client, _required(items, "items"), project)
    if action == "add_items":
        return client.request("POST", membership, data={"issues": ids})
    if action == "remove_items":
        return [client.request("DELETE", f"{membership}{item_id}/") for item_id in ids]
    target = client.resolve_named_resource(
        project, "cycles", _required(target_cycle, "target_cycle")
    )
    return client.request("POST", f"{detail}transfer-issues/", data={"new_cycle_id": target["id"]})


@mcp.tool
def module(
    action: Literal[
        "list",
        "get",
        "create",
        "update",
        "delete",
        "archive",
        "unarchive",
        "list_items",
        "add_items",
        "remove_items",
    ],
    project: str,
    module: str | None = None,
    data: dict[str, Any] | None = None,
    items: list[str] | None = None,
    confirm: bool = False,
) -> Any:
    """Manage modules and module membership. Module names and work-item keys are accepted."""
    client = get_client()
    base, _ = _project_base(client, project)
    collection = f"{base}modules/"
    if action == "list":
        return client.request("GET", collection, params={"per_page": 100})
    if action == "create":
        return client.request("POST", collection, data=_required(data, "data"))
    if action == "unarchive":
        archived = client.resolve_path(
            f"{base}archived-modules/", _required(module, "module"), "name"
        )
        return client.request("DELETE", f"{base}archived-modules/{archived['id']}/unarchive/")
    module_obj = client.resolve_named_resource(project, "modules", _required(module, "module"))
    detail = f"{collection}{module_obj['id']}/"
    if action == "get":
        return client.request("GET", detail)
    if action == "update":
        return client.request("PATCH", detail, data=_required(data, "data"))
    if action == "delete":
        _confirm(confirm, "module delete")
        return client.request("DELETE", detail)
    if action == "archive":
        return client.request("POST", f"{detail}archive/")
    membership = f"{detail}module-issues/"
    if action == "list_items":
        return client.request("GET", membership)
    ids = _resolve_item_ids(client, _required(items, "items"), project)
    if action == "add_items":
        return client.request("POST", membership, data={"issues": ids})
    return [client.request("DELETE", f"{membership}{item_id}/") for item_id in ids]


@mcp.tool
def catalog(
    action: Literal[
        "states",
        "labels",
        "project_members",
        "workspace_members",
        "create_state",
        "update_state",
        "create_label",
        "update_label",
    ],
    project: str | None = None,
    resource: str | None = None,
    data: dict[str, Any] | None = None,
) -> Any:
    """Read supporting resources and create or update states and labels."""
    client = get_client()
    if action == "workspace_members":
        return client.request("GET", f"{client.workspace_path}members/", params={"per_page": 100})
    base, _ = _project_base(client, _required(project, "project"))
    if action in {"states", "labels", "project_members"}:
        kind = "members" if action == "project_members" else action
        return client.request("GET", f"{base}{kind}/", params={"per_page": 100})
    kind = "states" if action.endswith("state") else "labels"
    if action.startswith("create"):
        return client.request("POST", f"{base}{kind}/", data=_required(data, "data"))
    resolved = client.resolve_named_resource(project, kind, _required(resource, "resource"))
    return client.request("PATCH", f"{base}{kind}/{resolved['id']}/", data=_required(data, "data"))


@mcp.tool
def relation(
    action: Literal["list", "add", "list_links", "add_link", "update_link", "delete_link"],
    item: str,
    project: str | None = None,
    relation_type: Literal[
        "blocking",
        "blocked_by",
        "duplicate",
        "relates_to",
        "start_before",
        "start_after",
        "finish_before",
        "finish_after",
    ]
    | None = None,
    related_items: list[str] | None = None,
    link_id: str | None = None,
    data: dict[str, Any] | None = None,
    confirm: bool = False,
) -> Any:
    """Manage work-item relations and external links. Relation removal is not in Plane CE v1.4.2."""
    client = get_client()
    _, item_path = _item(client, item, project)
    if action == "list":
        return client.request("GET", f"{item_path}relations/")
    if action == "add":
        ids = _resolve_item_ids(client, _required(related_items, "related_items"), project)
        return client.request(
            "POST",
            f"{item_path}relations/",
            data={"relation_type": _required(relation_type, "relation_type"), "issues": ids},
        )
    links = f"{item_path}links/"
    if action == "list_links":
        return client.request("GET", links)
    if action == "add_link":
        return client.request("POST", links, data=_required(data, "data"))
    detail = f"{links}{_required(link_id, 'link_id')}/"
    if action == "update_link":
        return client.request("PATCH", detail, data=_required(data, "data"))
    _confirm(confirm, "link delete")
    return client.request("DELETE", detail)
