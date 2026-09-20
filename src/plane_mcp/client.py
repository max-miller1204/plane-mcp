"""Direct client for the Plane v1.4.2 public API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class PlaneAPIError(RuntimeError):
    """A Plane API request failed."""


class PlaneResolutionError(ValueError):
    """A readable Plane reference did not resolve to one resource."""


class PlaneClient:
    """Call one configured Plane workspace without SDK compatibility behavior."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace_slug: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("PLANE_BASE_URL is empty")
        if not api_key.strip():
            raise ValueError("PLANE_API_KEY is empty")
        if not workspace_slug.strip():
            raise ValueError("PLANE_WORKSPACE_SLUG is empty")

        self.base_url = base_url.rstrip("/")
        self.workspace_slug = workspace_slug
        self._http = httpx.Client(
            base_url=f"{self.base_url}/api/v1/",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    @property
    def workspace_path(self) -> str:
        return f"workspaces/{quote(self.workspace_slug, safe='')}/"

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        response = self._http.request(method, path, params=params, json=data)
        if not response.is_success:
            detail = response.text[:4000]
            raise PlaneAPIError(
                f"Plane API {method.upper()} {path} failed with HTTP "
                f"{response.status_code}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        return response.json()

    @staticmethod
    def results(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return payload["results"]
        raise PlaneAPIError("Plane returned an unexpected list response")

    @staticmethod
    def _resolve(
        items: list[dict[str, Any]], reference: str, fields: tuple[str, ...]
    ) -> dict[str, Any]:
        exact_id = [item for item in items if str(item.get("id", "")) == reference]
        if exact_id:
            return exact_id[0]

        lowered = reference.casefold()
        matches = [
            item
            for item in items
            if any(str(item.get(field, "")).casefold() == lowered for field in fields)
        ]
        if not matches:
            raise PlaneResolutionError(f"No resource matches {reference!r}")
        if len(matches) > 1:
            ids = ", ".join(str(item.get("id")) for item in matches)
            raise PlaneResolutionError(f"Reference {reference!r} is ambiguous. Matches: {ids}")
        return matches[0]

    def list_projects(self, **params: Any) -> Any:
        return self.request("GET", f"{self.workspace_path}projects/", params=params or None)

    def resolve_project(self, reference: str) -> dict[str, Any]:
        projects = self.results(self.list_projects(per_page=100))
        return self._resolve(projects, reference, ("identifier", "name"))

    def project_path(self, project: str) -> tuple[str, dict[str, Any]]:
        resolved = self.resolve_project(project)
        return f"{self.workspace_path}projects/{resolved['id']}/", resolved

    def resolve_named_resource(self, project: str, resource: str, reference: str) -> dict[str, Any]:
        base, _ = self.project_path(project)
        payload = self.request("GET", f"{base}{resource}/", params={"per_page": 100})
        return self._resolve(self.results(payload), reference, ("name",))

    def resolve_path(self, path: str, reference: str, *fields: str) -> dict[str, Any]:
        payload = self.request("GET", path, params={"per_page": 100})
        return self._resolve(self.results(payload), reference, fields)

    def resolve_member(self, reference: str) -> dict[str, Any]:
        payload = self.request(
            "GET", f"{self.workspace_path}members-lite/", params={"per_page": 100}
        )
        members = self.results(payload)
        lowered = reference.casefold()
        matches = []
        for member in members:
            full_name = f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
            values = (
                str(member.get("id", "")),
                str(member.get("email", "")),
                str(member.get("display_name", "")),
                full_name,
            )
            if any(value.casefold() == lowered for value in values):
                matches.append(member)
        if not matches:
            raise PlaneResolutionError(f"No member matches {reference!r}")
        if len(matches) > 1:
            ids = ", ".join(str(member.get("id")) for member in matches)
            raise PlaneResolutionError(
                f"Member reference {reference!r} is ambiguous. Matches: {ids}"
            )
        return matches[0]

    def resolve_work_item(self, reference: str, project: str | None = None) -> dict[str, Any]:
        if "-" in reference and project is None:
            return self.request(
                "GET",
                f"{self.workspace_path}work-items/{quote(reference, safe='-')}/",
                params={"expand": "assignees,labels,state"},
            )
        if project is None:
            raise PlaneResolutionError("project is required when item is a UUID")
        base, _ = self.project_path(project)
        return self.request(
            "GET",
            f"{base}work-items/{quote(reference, safe='')}/",
            params={"expand": "assignees,labels,state"},
        )
