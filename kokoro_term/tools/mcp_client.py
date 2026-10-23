"""Model Context Protocol (MCP) Client for Roxy Agent.

Loads MCP server definitions from mcp_servers.json and registers remote MCP tools.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional
from kokoro_term.tools.base import BaseTool, ToolResult


class MCPToolWrapper(BaseTool):
    """Wrapper that exposes an external MCP tool as an internal BaseTool."""

    def __init__(self, server_name: str, tool_def: dict[str, Any], server_config: dict[str, Any]):
        self.server_name = server_name
        self.server_config = server_config
        self.name = f"mcp_{server_name}_{tool_def.get('name', 'tool')}"
        self.description = f"[MCP: {server_name}] {tool_def.get('description', '')}"
        self.parameters = tool_def.get("inputSchema", {}).get("properties", {})
        self.tier = "moderate"

    async def execute(self, **kwargs) -> ToolResult:
        # Standard MCP execution via JSON-RPC over stdio
        cmd = self.server_config.get("command")
        args = self.server_config.get("args", [])
        env = {**os.environ, **self.server_config.get("env", {})}

        if not cmd:
            return ToolResult(success=False, output="", error=f"Server '{self.server_name}' has no command configured.")

        try:
            req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": self.name.replace(f"mcp_{self.server_name}_", ""),
                    "arguments": kwargs,
                },
            }
            proc = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await proc.communicate(json.dumps(req).encode() + b"\n")
            if proc.returncode != 0:
                return ToolResult(success=False, output="", error=stderr.decode())

            resp_line = stdout.decode().strip().split("\n")[-1]
            data = json.loads(resp_line)
            content = data.get("result", {}).get("content", [])
            output = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
            return ToolResult(success=True, output=output or str(data.get("result", "")))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"MCP call failed: {e}")


def load_mcp_servers(config_paths: Optional[list[str | Path]] = None) -> list[BaseTool]:
    """Find mcp_servers.json in standard candidate paths and load tools."""
    if not config_paths:
        config_paths = [
            Path("mcp_servers.json"),
            Path.home() / ".config" / "kokoro-term" / "mcp_servers.json",
            Path.home() / ".config" / "roxy" / "mcp_servers.json",
        ]

    tools: list[BaseTool] = []
    for p in config_paths:
        path = Path(p)
        if path.exists() and path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                servers = data.get("mcpServers", {})
                for server_name, server_conf in servers.items():
                    # Register tools listed statically or configure server
                    declared_tools = server_conf.get("tools", [])
                    for t in declared_tools:
                        tools.append(MCPToolWrapper(server_name, t, server_conf))
            except Exception:
                pass
    return tools
