import asyncio
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from config import SANDBOX_CONTAINER
# print(SANDBOX_CONTAINER)
app = Server("bash")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_bash",
            description=(
                "Run a bash command inside the isolated Docker sandbox container. "
                "The sandbox has no internet access. Use for: running pytest, "
                "pip install, linters (flake8, mypy), or any shell command on the repo."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run, e.g. 'cd /tmp/repos/abc && pytest tests/ -v'",
                    }
                },
                "required": ["command"],
            },
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "run_bash":
        result = _run_bash(arguments["command"])
    else:
        result = f"unknown tool: {name}"
    return [types.TextContent(type="text", text=result)]

def _run_bash(command: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "exec", SANDBOX_CONTAINER, "bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:4000] if output else "no output"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60 seconds"
    except FileNotFoundError:
        return "Error: Docker container not found"
    except Exception as e:
        return f"Error: {e}"
    
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

if __name__ == "__main__":
    asyncio.run(main())