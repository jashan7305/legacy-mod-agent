import asyncio
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from config import REPOS_DIR

app = Server("ast-analyser")

# ── language registry ─────────────────────────────────────────────────────────
# Maps file extension → (tree-sitter module, language accessor, test runner hint)

def _build_language_registry() -> dict:
    registry = {}

    try:
        import tree_sitter_python as tspython
        from tree_sitter import Language
        registry[".py"] = {
            "language":    Language(tspython.language()),
            "name":        "Python",
            "test_cmd":    "pytest tests/ -v",
        }
    except ImportError:
        pass

    try:
        import tree_sitter_javascript as tsjs
        from tree_sitter import Language
        registry[".js"] = {
            "language":    Language(tsjs.language()),
            "name":        "JavaScript",
            "test_cmd":    "npm test",
        }
    except ImportError:
        pass

    try:
        import tree_sitter_typescript as tsts
        from tree_sitter import Language
        # typescript package exposes two grammars: typescript and tsx
        registry[".ts"] = {
            "language":    Language(tsts.language_typescript()),
            "name":        "TypeScript",
            "test_cmd":    "npx tsc --noEmit && npm test",
        }
        registry[".tsx"] = {
            "language":    Language(tsts.language_tsx()),
            "name":        "TSX",
            "test_cmd":    "npx tsc --noEmit && npm test",
        }
    except ImportError:
        pass

    try:
        import tree_sitter_rust as tsrust
        from tree_sitter import Language
        registry[".rs"] = {
            "language":    Language(tsrust.language()),
            "name":        "Rust",
            "test_cmd":    "cargo test",
        }
    except ImportError:
        pass

    return registry


LANGUAGE_REGISTRY = _build_language_registry()

# ── node types per language that represent "functions" ────────────────────────
FUNCTION_NODE_TYPES = {
    ".py":  {"function_definition", "async_function_definition"},
    ".js":  {"function_declaration", "function_expression",
             "arrow_function", "method_definition"},
    ".ts":  {"function_declaration", "function_expression",
             "arrow_function", "method_definition",
             "abstract_method_signature"},
    ".tsx": {"function_declaration", "function_expression",
             "arrow_function", "method_definition"},
    ".rs":  {"function_item", "closure_expression"},
}

# node types that increase cyclomatic complexity
COMPLEXITY_NODE_TYPES = {
    "if_expression", "if_statement", "else_clause",
    "for_statement", "for_in_statement", "while_statement",
    "match_expression", "switch_statement",
    "try_statement", "catch_clause",
    "ternary_expression", "conditional_expression",
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    supported = ", ".join(
        f"{ext} ({v['name']})"
        for ext, v in LANGUAGE_REGISTRY.items()
    )
    return [
        types.Tool(
            name="extract_ast",
            description=(
                f"Parse a source file and return all function definitions "
                f"with line numbers and complexity scores, plus the top 20 "
                f"most-called names (call graph). "
                f"Supported languages: {supported}. "
                f"Use this before scoring debt or refactoring any file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type":        "string",
                        "description": "Path to the file, relative to the repo root.",
                    }
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="count_lines",
            description="Return the number of lines in a file. Used for sizing the debt heatmap.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="detect_language",
            description=(
                "Detect the primary programming language of a repository "
                "by scanning file extensions. Returns a ranked list of "
                "languages by file count."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type":        "string",
                        "description": "Path to the repo root, relative to REPOS_DIR.",
                    }
                },
                "required": ["repo_path"],
            },
        ),
        types.Tool(
            name="report_debt_score",
            description=(
                "Report a technical debt score for a file you've analysed. "
                "Call this once for every file you process, in BOTH Track A and "
                "Track B, right after you've reasoned about its complexity and "
                "issues — typically right after extract_ast and reading the file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Full absolute path to the file being scored.",
                    },
                    "debt_score": {
                        "type": "integer",
                        "description": "0-100. 0 = pristine, well-structured code. 100 = unmaintainable.",
                    },
                    "reasons": {
                        "type": "string",
                        "description": "Brief comma-separated list of reasons for the score, e.g. 'no type hints, deeply nested logic, missing tests'.",
                    },
                },
                "required": ["path", "debt_score", "reasons"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "extract_ast":
        result = _extract_ast(arguments["path"])
    elif name == "count_lines":
        result = _count_lines(arguments["path"])
    elif name == "detect_language":
        result = _detect_language(arguments["repo_path"])
    elif name == "report_debt_score":
        result = (
            f"Recorded debt score {arguments['debt_score']}/100 for "
            f"{arguments['path']}: {arguments['reasons']}"
        )
    else:
        result = f"unknown tool: {name}"

    return [types.TextContent(type="text", text=result)]

def _extract_ast(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    if ext not in LANGUAGE_REGISTRY:
        supported = ", ".join(LANGUAGE_REGISTRY.keys())
        return (
            f"unsupported file type: '{ext}'. "
            f"supported: {supported}"
        )

    full = path
    if not os.path.isabs(full):
        full = os.path.join(REPOS_DIR, full)
    if not os.path.exists(full):
        return f"file not found: {path}"

    try:
        from tree_sitter import Parser

        lang_entry = LANGUAGE_REGISTRY[ext]
        parser     = Parser(lang_entry["language"])

        with open(full, "rb") as f:
            source = f.read()

        tree = parser.parse(source)

        fn_types = FUNCTION_NODE_TYPES.get(ext, set())
        functions: list[str] = []
        calls:     list[str] = []

        def walk(node):
            # function definitions
            if node.type in fn_types:
                # try common field names across languages
                name_node = (
                    node.child_by_field_name("name") or
                    node.child_by_field_name("identifier")
                )
                fname     = name_node.text.decode() if name_node else "<anonymous>"
                lineno    = node.start_point[0] + 1
                end_line  = node.end_point[0] + 1
                length    = end_line - lineno

                complexity = sum(
                    1 for n in _iter_nodes(node)
                    if n.type in COMPLEXITY_NODE_TYPES
                )
                functions.append(
                    f"  {fname}()  line {lineno}  "
                    f"length={length}  complexity={complexity}"
                )

            # call expressions — works across all four languages
            if node.type in ("call", "call_expression"):
                fn_node = node.child_by_field_name("function")
                if fn_node:
                    calls.append(fn_node.text.decode().strip())

            for child in node.children:
                walk(child)

        walk(tree.root_node)

        call_counts: dict[str, int] = {}
        for c in calls:
            call_counts[c] = call_counts.get(c, 0) + 1
        top_calls = sorted(call_counts.items(), key=lambda x: -x[1])[:20]

        lang_name = lang_entry["name"]
        test_cmd  = lang_entry["test_cmd"]

        out  = f"=== {path} ({lang_name}) ===\n"
        out += f"Functions ({len(functions)}):\n"
        out += "\n".join(functions[:60]) or "  none found"
        out += "\n\nTop called names:\n"
        out += "\n".join(f"  {n}: {c}x" for n, c in top_calls) or "  none"
        out += f"\n\nSuggested test command: {test_cmd}"
        return out

    except Exception as e:
        return f"AST extraction error for {path}: {e}"


def _count_lines(path: str) -> str:
    full = path
    if not os.path.isabs(full):
        full = os.path.join(REPOS_DIR, full)
    if not os.path.exists(full):
        return f"file not found: {path}"
    try:
        with open(full, "r", errors="replace") as f:
            count = sum(1 for _ in f)
        return str(count)
    except Exception as e:
        return f"Error: {e}"


def _detect_language(repo_path: str) -> str:
    """Scan a repo and rank languages by file count."""
    full = repo_path
    if not os.path.isabs(full):
        full = os.path.join(REPOS_DIR, full)
    if not os.path.exists(full):
        return f"path not found: {repo_path}"

    counts: dict[str, int] = {}
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "target", "dist"}

    for root, dirs, files in os.walk(full):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in LANGUAGE_REGISTRY:
                lang = LANGUAGE_REGISTRY[ext]["name"]
                counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return "no supported language files found."

    ranked = sorted(counts.items(), key=lambda x: -x[1])
    lines  = [f"  {lang}: {n} files" for lang, n in ranked]
    return "Language breakdown:\n" + "\n".join(lines)


def _iter_nodes(node):
    yield node
    for child in node.children:
        yield from _iter_nodes(child)

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())