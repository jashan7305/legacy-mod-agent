import asyncio
import os
import sys
from typing import Any
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import GITHUB_TOKEN

def _server_configs() -> list[tuple[str, StdioServerParameters]]:
    python = sys.executable

    return [
        (
            "fs",
            StdioServerParameters(
                command=python,
                args=["-m", "mcp_servers.fs_server"],
            ),
        ),
        (
            "bash",
            StdioServerParameters(
                command=python,
                args=["-m", "mcp_servers.bash_server"],
            ),
        ),
        (
            "ast",
            StdioServerParameters(
                command=python,
                args=["-m", "mcp_servers.ast_server"],
            ),
        ),
        (
            "github",
            StdioServerParameters(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={
                    **os.environ,
                    "GITHUB_PERSONAL_ACCESS_TOKEN": GITHUB_TOKEN,
                },
            ),
        ),
    ]

class MCPClientManager:
    """
    Starts all MCP server subprocesses, holds their sessions open,
    discovers their tools, and routes call_tool() to the right server.
    """

    def __init__(self):
        self._sessions:     dict[str, ClientSession] = {}
        self._tool_map:     dict[str, str]           = {}  # tool_name → server_name
        self._tool_schemas: list[dict]               = []  # Gemini-format declarations
        self._cms:          list                     = []  # context managers to close on exit

    async def start(self):
        """Spawn every MCP server and discover its tools."""
        for server_name, params in _server_configs():
            try:
                cm = stdio_client(params)
                read, write = await cm.__aenter__()
                self._cms.append(cm)

                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()

                self._sessions[server_name] = session

                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    self._tool_map[tool.name] = server_name
                    self._tool_schemas.append({
                        "name":        tool.name,
                        "description": tool.description or "",
                        "parameters":  tool.inputSchema or {},
                    })

            except Exception as e:
                # log but don't crash — agent can still run with partial tools
                print(
                    f"[mcp_client] WARNING: failed to start '{server_name}' server: {e}",
                    file=sys.stderr,
                )

    async def stop(self):
        """Cleanly shut down all sessions and subprocesses."""
        for session in self._sessions.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
        for cm in reversed(self._cms):
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass

    @property
    def tool_schemas(self) -> list[dict]:
        """
        All discovered tools as Gemini-compatible declarations.
        The agent loop passes these directly to GenerativeModel.
        """
        return self._tool_schemas

    @property
    def connected_servers(self) -> list[str]:
        """Names of servers that started successfully."""
        return list(self._sessions.keys())

    def is_tool_available(self, tool_name: str) -> bool:
        return tool_name in self._tool_map

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Route a tool call to the correct MCP server.
        Always returns a string — errors are returned as strings too
        so the agent can read and react to them rather than crashing.
        """
        server_name = self._tool_map.get(tool_name)
        if not server_name:
            return (
                f"Error: no MCP server has registered a tool named '{tool_name}'. "
                f"Available tools: {list(self._tool_map.keys())}"
            )

        session = self._sessions.get(server_name)
        if not session:
            return f"Error: server '{server_name}' is registered but not running."

        try:
            result = await session.call_tool(tool_name, arguments)

            # MCP returns a list of content blocks — join all text blocks
            texts = [
                block.text
                for block in result.content
                if hasattr(block, "text")
            ]
            output = "\n".join(texts).strip()
            return output or "(tool returned no output)"

        except Exception as e:
            return f"Error calling '{tool_name}' on server '{server_name}': {e}"
        
@asynccontextmanager
async def mcp_client_manager():
    """
    Async context manager that starts all MCP servers on entry
    and shuts them down cleanly on exit.

    Usage in loop.py:
        async with mcp_client_manager() as mcp:
            tools = mcp.tool_schemas
            result = await mcp.call_tool("read_file", {"path": "/main.py"})
    """
    manager = MCPClientManager()
    await manager.start()
    try:
        yield manager
    finally:
        await manager.stop()