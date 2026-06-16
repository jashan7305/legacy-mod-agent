import asyncio
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from config import REPOS_DIR
# print(REPOS_DIR)

app = Server("filesystem")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_files",
            description="Recursively list all files in a directory of the cloned repo. Skips hidden dirs, node_modules, __pycache__.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repo root, e.g. '/' or 'src/'"}
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="read_file",
            description="Read the full content of a file in the cloned repo. Capped at 50,000 characters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repo root"}
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="write_file",
            description="Write or overwrite a file in the cloned repo with new content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "Path relative to the repo root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        ),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "list_files":
        result = _list_files(arguments["path"])
    elif name == "read_file":
        result = _read_file(arguments["path"])
    elif name == "write_file":
        result = _write_file(arguments["path"], arguments["content"])
    else:
        result = f"Unknown tool: {name}"
    return [types.TextContent(type="text", text=result)]

def _list_files(path: str) -> str:
    full_path = os.path.join(REPOS_DIR, path.lstrip("/"))
    if not os.path.exists(full_path):
        return f"path not found: {path}"
    
    entries = []
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}

    for root, dirs, files in os.walk(full_path):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        level = root.replace(full_path, "").count(os.sep)
        indent = "  " * level
        entries.append(f"{indent}{os.path.basename(root)}/")
        for f in files:
            entries.append(f"{indent}  {f}")
        if len(entries) > 300:
            entries.append("... (truncated at 300 entries)")
            break

    return "\n".join(entries)


def _read_file(path: str) -> str:
    full_path = os.path.join(REPOS_DIR, path.lstrip("/"))
    if not os.path.exists(full_path):
        return f"file not found: {path}"
    
    try:
        with open(full_path, "r", errors="replace") as f:
            content = f.read(50000)
        return content
    except Exception as e:
        return f"error reading file: {e}"

def _write_file(path: str, content: str) -> str:
    full = os.path.join(REPOS_DIR, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return f"Written: {path} ({len(content)} chars)"

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

if __name__ == "__main__":
    asyncio.run(main())