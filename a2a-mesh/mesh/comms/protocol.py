"""Agent communication protocol — HTTP client for lateral messaging."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class AgentCommsClient:
    """HTTP client for agent-to-agent lateral communication."""

    def __init__(self, api_key: str = "", timeout: int = 30):
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def send_message(
        self,
        target_url: str,
        channel_id: str,
        from_agent: str,
        from_agent_name: str,
        content: str,
        message_type: str = "text",
    ) -> dict | None:
        """Send a message to another agent's /comms/receive endpoint."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{target_url.rstrip('/')}/comms/receive",
                    json={
                        "channel_id": channel_id,
                        "from_agent": from_agent,
                        "from_agent_name": from_agent_name,
                        "content": content,
                        "message_type": message_type,
                    },
                    headers=self._headers(),
                )
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to send message to {target_url}: {e}")
            return None

    async def request_revision(
        self,
        target_url: str,
        channel_id: str,
        from_agent: str,
        from_agent_name: str,
        artifact: str,
        feedback: str,
    ) -> dict | None:
        """Send a revision request to another agent."""
        return await self.send_message(
            target_url=target_url,
            channel_id=channel_id,
            from_agent=from_agent,
            from_agent_name=from_agent_name,
            content=f"REVISION REQUEST:\n\nArtifact:\n{artifact}\n\nFeedback:\n{feedback}",
            message_type="revision_request",
        )

    async def suggest(
        self,
        target_url: str,
        channel_id: str,
        from_agent: str,
        from_agent_name: str,
        suggestion: str,
    ) -> dict | None:
        """Send a suggestion to another agent."""
        return await self.send_message(
            target_url=target_url,
            channel_id=channel_id,
            from_agent=from_agent,
            from_agent_name=from_agent_name,
            content=suggestion,
            message_type="suggestion",
        )

    async def handoff(
        self,
        target_url: str,
        channel_id: str,
        from_agent: str,
        from_agent_name: str,
        context: str,
    ) -> dict | None:
        """Hand off work to another agent."""
        return await self.send_message(
            target_url=target_url,
            channel_id=channel_id,
            from_agent=from_agent,
            from_agent_name=from_agent_name,
            content=context,
            message_type="handoff",
        )
