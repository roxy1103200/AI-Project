"""Shared Java API transport for the Agent and the cinema MCP server."""

import os
from typing import Any

import httpx


class JavaApiClient:
    """Call fixed business endpoints with the private service credential."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=os.getenv("JAVA_API_URL", "http://localhost:8080").rstrip("/"),
            headers={"X-Internal-Token": os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")},
            timeout=8.0,
            trust_env=False,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return decoded JSON after checking the upstream HTTP status."""
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        """Call the recommendation endpoint and return decoded JSON."""
        response = await self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        """Release pooled HTTP connections when the service stops."""
        await self.client.aclose()
