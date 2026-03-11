"""WebSocket handler for real-time UI updates."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class EventBus:
    """Simple pub/sub event bus for pushing events to WebSocket clients.

    Supports bidirectional communication and event filtering per subscriber.
    """

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._filters: dict[int, set[str] | None] = {}  # queue id -> event types or None (all)

    def subscribe(self, event_types: set[str] | None = None) -> asyncio.Queue:
        """Subscribe to events. Returns a queue to read from.

        Args:
            event_types: Set of event types to receive, or None for all.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        self._filters[id(queue)] = event_types
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from events."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
            self._filters.pop(id(queue), None)

    async def publish(self, event_type: str, data: Any):
        """Publish an event to all subscribers."""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for queue in self._subscribers:
            # Check filter
            allowed_types = self._filters.get(id(queue))
            if allowed_types is not None and event_type not in allowed_types:
                continue
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop events for slow consumers


# Global event bus
event_bus = EventBus()


async def websocket_handler(websocket: WebSocket):
    """WebSocket endpoint for real-time mesh events.

    Supports bidirectional communication:
    - Server → Client: event stream
    - Client → Server: commands (subscribe, unsubscribe, ping)

    Event types:
    - agent_joined / agent_left / role_assigned
    - task_created / task_assigned / task_started / task_completed / task_failed
    - channel_message
    - intent_pending / intent_decided
    - plan_created / plan_step_started / plan_step_completed
    """
    await websocket.accept()
    queue = event_bus.subscribe()

    async def send_events():
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except Exception:
            pass

    async def receive_commands():
        try:
            while True:
                data = await websocket.receive_json()
                cmd = data.get("command", "")
                if cmd == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
                elif cmd == "subscribe":
                    # Update filter for this subscriber
                    types = data.get("event_types")
                    if types:
                        event_bus._filters[id(queue)] = set(types)
                elif cmd == "unsubscribe":
                    event_bus._filters[id(queue)] = None
        except Exception:
            pass

    try:
        # Run both tasks concurrently
        send_task = asyncio.create_task(send_events())
        recv_task = asyncio.create_task(receive_commands())
        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        event_bus.unsubscribe(queue)
