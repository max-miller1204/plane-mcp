from __future__ import annotations

import httpx
import pytest

from plane_mcp.client import PlaneAPIError, PlaneClient, PlaneResolutionError


@pytest.fixture
def requests_log():
    return []


@pytest.fixture
def client(requests_log):
    def handler(request: httpx.Request) -> httpx.Response:
        requests_log.append(request)
        path = request.url.path
        if path.endswith("/projects/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "identifier": "DEV",
                            "name": "Development",
                        }
                    ]
                },
            )
        if path.endswith("/states/"):
            return httpx.Response(200, json=[{"id": "state-1", "name": "In Progress"}])
        if path.endswith("/members-lite/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "user-1",
                            "email": "dev@example.com",
                            "display_name": "Max Miller",
                        }
                    ]
                },
            )
        if path.endswith("/work-items/DEV-42/"):
            return httpx.Response(
                200,
                json={
                    "id": "item-42",
                    "sequence_id": 42,
                    "project_id": "11111111-1111-1111-1111-111111111111",
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    api = PlaneClient(
        "https://plane.example.com",
        "secret",
        "demo",
        transport=httpx.MockTransport(handler),
    )
    yield api
    api.close()


def test_resolve_project_by_identifier(client):
    project = client.resolve_project("dev")
    assert project["name"] == "Development"


def test_resolve_named_resource(client):
    state = client.resolve_named_resource("DEV", "states", "in progress")
    assert state["id"] == "state-1"


def test_resolve_member_by_display_name(client):
    member = client.resolve_member("max miller")
    assert member["id"] == "user-1"


def test_resolve_work_item_by_readable_key(client, requests_log):
    item = client.resolve_work_item("DEV-42")
    assert item["id"] == "item-42"
    assert requests_log[-1].url.params["expand"] == "assignees,labels,state"


def test_request_sends_api_key(client, requests_log):
    client.list_projects()
    assert requests_log[-1].headers["X-API-Key"] == "secret"


def test_request_error_is_explicit():
    api = PlaneClient(
        "https://plane.example.com",
        "secret",
        "demo",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"name": ["This field is required."]})
        ),
    )
    with pytest.raises(PlaneAPIError, match="HTTP 400"):
        api.list_projects()
    api.close()


def test_ambiguous_reference_fails():
    items = [
        {"id": "1", "name": "Same"},
        {"id": "2", "name": "same"},
    ]
    with pytest.raises(PlaneResolutionError, match="ambiguous"):
        PlaneClient._resolve(items, "Same", ("name",))


def test_delete_response_returns_ok():
    api = PlaneClient(
        "https://plane.example.com",
        "secret",
        "demo",
        transport=httpx.MockTransport(lambda request: httpx.Response(204)),
    )
    assert api.request("DELETE", "anything/") == {"ok": True}
    api.close()
