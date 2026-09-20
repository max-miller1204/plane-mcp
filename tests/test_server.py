from __future__ import annotations

import asyncio

import pytest

from plane_mcp import server
from plane_mcp.server import _confirm, _normalize_work_item_data, mcp


def test_server_exposes_nine_focused_tools():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "credential",
        "plane_context",
        "project",
        "work_item",
        "comment",
        "cycle",
        "module",
        "catalog",
        "relation",
    }


def test_destructive_action_requires_confirmation():
    with pytest.raises(ValueError, match="confirm=true"):
        _confirm(False, "delete")


class ResolverStub:
    def resolve_named_resource(self, project, resource, reference):
        return {"id": f"{resource}:{reference}"}

    def resolve_work_item(self, reference, project=None):
        return {"id": f"item:{reference}"}


def test_work_item_payload_resolves_readable_references():
    result = _normalize_work_item_data(
        ResolverStub(),
        "DEV",
        {
            "name": "Example",
            "state": "In Progress",
            "labels": ["backend", "urgent"],
            "parent": "DEV-1",
        },
    )
    assert result == {
        "name": "Example",
        "state": "states:In Progress",
        "labels": ["labels:backend", "labels:urgent"],
        "parent": "item:DEV-1",
    }


class SearchStub:
    workspace_path = "workspaces/demo/"

    def resolve_project(self, reference):
        assert reference == "DEV"
        return {"id": "project-1"}

    def request(self, method, path, *, params=None, data=None):
        return {"method": method, "path": path, "params": params, "data": data}


def test_work_item_search_uses_ce_limit_and_project_id(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: SearchStub())
    result = server.work_item(action="search", query="oauth", project="DEV", per_page=20)

    assert result["params"] == {"search": "oauth", "limit": 20, "project_id": "project-1"}


def test_work_item_search_rejects_cursor(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: SearchStub())

    with pytest.raises(ValueError, match="does not support cursors"):
        server.work_item(action="search", query="oauth", cursor="next")
