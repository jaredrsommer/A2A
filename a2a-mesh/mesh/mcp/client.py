"""MCP tool bridge — connects to MCP servers and adapts tools."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mesh.mcp.registry import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPToolBridge:
    """Connects to an MCP server and exposes its tools.

    Supports stdio and SSE transports. Discovers tools on connect
    and adapts them to the ToolDef format used by the agent executor.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._tools: list[dict] = []
        self._connected = False
        self._request_id = 0

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to the MCP server and discover tools."""
        if self.config.transport == "stdio":
            return await self._connect_stdio()
        elif self.config.transport == "sse":
            return await self._connect_sse()
        else:
            logger.error(f"Unknown transport: {self.config.transport}")
            return False

    async def _connect_stdio(self) -> bool:
        """Connect via stdio transport."""
        try:
            cmd = [self.config.command] + self.config.args
            env = dict(**self.config.env) if self.config.env else None

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Send initialize request
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "a2a-mesh", "version": "0.1.0"},
            })

            if init_result is None:
                logger.error(f"MCP initialize failed for {self.config.name}")
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            # Discover tools
            tools_result = await self._send_request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self._tools = tools_result["tools"]
                logger.info(
                    f"MCP {self.config.name}: discovered {len(self._tools)} tools"
                )

            self._connected = True
            return True

        except FileNotFoundError:
            logger.error(f"MCP command not found: {self.config.command}")
            return False
        except Exception as e:
            logger.error(f"MCP connect failed for {self.config.name}: {e}")
            return False

    async def _connect_sse(self) -> bool:
        """Connect via SSE transport using MCP SDK."""
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client

            async with sse_client(self.config.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    self._tools = [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
                        }
                        for t in tools_result.tools
                    ]
                    self._connected = True
                    return True
        except ImportError:
            logger.warning("MCP SDK not installed, SSE transport unavailable")
            return False
        except Exception as e:
            logger.error(f"MCP SSE connect failed: {e}")
            return False

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request via stdio."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        msg = json.dumps(request) + "\n"
        self._process.stdin.write(msg.encode())
        await self._process.stdin.drain()

        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30
            )
            if line:
                response = json.loads(line.decode())
                if "error" in response:
                    logger.error(f"MCP error: {response['error']}")
                    return None
                return response.get("result")
        except asyncio.TimeoutError:
            logger.error(f"MCP request timeout: {method}")
        except Exception as e:
            logger.error(f"MCP request error: {e}")

        return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        msg = json.dumps(notification) + "\n"
        self._process.stdin.write(msg.encode())
        await self._process.stdin.drain()

    def get_tools(self) -> list[dict]:
        """Get discovered tools as ToolDef-compatible dicts."""
        return [
            {
                "name": f"mcp_{self.config.id}_{t['name']}",
                "description": f"[MCP:{self.config.name}] {t.get('description', t['name'])}",
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                "mcp_server_id": self.config.id,
                "mcp_tool_name": t["name"],
            }
            for t in self._tools
        ]

    async def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute an MCP tool by its original name."""
        if self.config.transport == "stdio":
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            if result and "content" in result:
                parts = result["content"]
                texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
                return "\n".join(texts) or json.dumps(result)
            return json.dumps(result) if result else "Tool execution failed"
        else:
            return "SSE tool execution not yet supported in bridge mode"

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
            self._process = None
        self._connected = False
        self._tools = []
