"""MCP server registry — configuration and persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    id: str = ""
    name: str = ""
    transport: str = "stdio"  # "stdio" or "sse"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""  # For SSE transport
    env: dict[str, str] = field(default_factory=dict)
    assigned_roles: list[str] = field(default_factory=list)
    assigned_workers: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "url": self.url,
            "env": self.env,
            "assigned_roles": self.assigned_roles,
            "assigned_workers": self.assigned_workers,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MCPServerConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class MCPRegistry:
    """Registry for MCP server configurations, persisted to JSON."""

    def __init__(self, data_dir: str = "data"):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._config_file = self._data_dir / "mcp_servers.json"
        self._servers: dict[str, MCPServerConfig] = {}
        self._load()

    def _load(self) -> None:
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    data = json.load(f)
                for item in data:
                    config = MCPServerConfig.from_dict(item)
                    self._servers[config.id] = config
                logger.info(f"Loaded {len(self._servers)} MCP server configs")
            except Exception as e:
                logger.error(f"Failed to load MCP configs: {e}")

    def _save(self) -> None:
        try:
            with open(self._config_file, "w") as f:
                json.dump([s.to_dict() for s in self._servers.values()], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save MCP configs: {e}")

    def add(self, config: MCPServerConfig) -> MCPServerConfig:
        if not config.id:
            import uuid
            config.id = str(uuid.uuid4())[:12]
        self._servers[config.id] = config
        self._save()
        logger.info(f"Added MCP server: {config.name} ({config.id})")
        return config

    def update(self, server_id: str, updates: dict) -> MCPServerConfig | None:
        server = self._servers.get(server_id)
        if not server:
            return None
        for key, value in updates.items():
            if hasattr(server, key):
                setattr(server, key, value)
        self._save()
        return server

    def remove(self, server_id: str) -> bool:
        if server_id in self._servers:
            del self._servers[server_id]
            self._save()
            return True
        return False

    def get(self, server_id: str) -> MCPServerConfig | None:
        return self._servers.get(server_id)

    def get_all(self) -> list[MCPServerConfig]:
        return list(self._servers.values())

    def get_for_role(self, role_id: str) -> list[MCPServerConfig]:
        return [
            s for s in self._servers.values()
            if role_id in s.assigned_roles and s.enabled
        ]

    def get_for_worker(self, worker_id: str) -> list[MCPServerConfig]:
        return [
            s for s in self._servers.values()
            if worker_id in s.assigned_workers and s.enabled
        ]
