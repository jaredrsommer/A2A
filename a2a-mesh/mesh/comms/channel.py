"""Conversation channels for lateral agent communication."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    TEXT = "text"
    SUGGESTION = "suggestion"
    REVISION_REQUEST = "revision_request"
    REVISION_RESPONSE = "revision_response"
    HANDOFF = "handoff"
    DISCUSS = "discuss"


@dataclass
class ChannelMessage:
    """A message within a conversation channel."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    from_agent: str = ""
    from_agent_name: str = ""
    content: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_type: MessageType = MessageType.TEXT
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "from_agent_name": self.from_agent_name,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "message_type": self.message_type.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChannelMessage:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:12]),
            from_agent=data.get("from_agent", ""),
            from_agent_name=data.get("from_agent_name", ""),
            content=data.get("content", ""),
            message_type=MessageType(data.get("message_type", "text")),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConversationChannel:
    """A conversation channel between agents working on related tasks."""

    channel_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_id: str = ""
    name: str = ""
    participants: list[str] = field(default_factory=list)
    messages: list[ChannelMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(self, msg: ChannelMessage) -> None:
        self.messages.append(msg)

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "task_id": self.task_id,
            "name": self.name,
            "participants": self.participants,
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
        }

    def to_dict_full(self) -> dict:
        d = self.to_dict()
        d["messages"] = [m.to_dict() for m in self.messages]
        return d


class ChannelManager:
    """Manages conversation channels between agents."""

    def __init__(self):
        self._channels: dict[str, ConversationChannel] = {}
        self._event_bus = None

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    def create_channel(
        self,
        task_id: str,
        participants: list[str],
        name: str = "",
    ) -> ConversationChannel:
        channel = ConversationChannel(
            task_id=task_id,
            participants=participants,
            name=name or f"task-{task_id[:8]}",
        )
        self._channels[channel.channel_id] = channel
        logger.info(f"Created channel {channel.channel_id} for task {task_id}")
        return channel

    def get_channel(self, channel_id: str) -> ConversationChannel | None:
        return self._channels.get(channel_id)

    def get_channels_for_agent(self, agent_id: str) -> list[ConversationChannel]:
        return [
            ch for ch in self._channels.values()
            if agent_id in ch.participants
        ]

    def get_channels_for_task(self, task_id: str) -> list[ConversationChannel]:
        return [ch for ch in self._channels.values() if ch.task_id == task_id]

    def get_all_channels(self) -> list[ConversationChannel]:
        return list(self._channels.values())

    async def post_message(
        self,
        channel_id: str,
        from_agent: str,
        from_agent_name: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        metadata: dict | None = None,
    ) -> ChannelMessage | None:
        channel = self._channels.get(channel_id)
        if not channel:
            return None

        msg = ChannelMessage(
            from_agent=from_agent,
            from_agent_name=from_agent_name,
            content=content,
            message_type=message_type,
            metadata=metadata or {},
        )
        channel.add_message(msg)

        # Publish to event bus
        if self._event_bus:
            await self._event_bus.publish("channel_message", {
                "channel_id": channel_id,
                "message": msg.to_dict(),
            })

        return msg
