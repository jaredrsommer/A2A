"""MCP manager — per-worker management of multiple MCP tool bridges."""

from __future__ import annotations

import logging

from mesh.agent.tools import ToolRegistry
from mesh.mcp.client import MCPToolBridge
from mesh.mcp.registry import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages multiple MCP tool bridges for a worker."""

    def __init__(self):
        self._bridges: dict[str, MCPToolBridge] = {}

    async def configure(self, configs: list[MCPServerConfig]) -> None:
        """Connect to MCP servers from configuration list."""
        # Disconnect existing
        await self.shutdown()

        for config in configs:
            if not config.enabled:
                continue
            bridge = MCPToolBridge(config)
            success = await bridge.connect()
            if success:
                self._bridges[config.id] = bridge
                logger.info(f"MCP connected: {config.name} ({len(bridge.get_tools())} tools)")
            else:
                logger.warning(f"MCP failed to connect: {config.name}")

    def get_all_tools(self) -> ToolRegistry:
        """Get a ToolRegistry with all MCP tools merged in."""
        registry = ToolRegistry()

        for bridge in self._bridges.values():
            for tool_info in bridge.get_tools():
                mcp_server_id = tool_info["mcp_server_id"]
                mcp_tool_name = tool_info["mcp_tool_name"]

                # Capture in closure
                _bridge = bridge
                _tool_name = mcp_tool_name

                async def handler(_b=_bridge, _t=_tool_name, **kwargs):
                    return await _b.execute_tool(_t, kwargs)

                registry.register(
                    name=tool_info["name"],
                    description=tool_info["description"],
                    parameters=tool_info["parameters"],
                    handler=handler,
                )

        return registry

    def get_bridge(self, server_id: str) -> MCPToolBridge | None:
        return self._bridges.get(server_id)

    @property
    def connected_servers(self) -> list[str]:
        return [sid for sid, b in self._bridges.items() if b.connected]

    async def shutdown(self) -> None:
        """Disconnect all MCP bridges."""
        for bridge in self._bridges.values():
            await bridge.disconnect()
        self._bridges.clear()
