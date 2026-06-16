import asyncio
import json
import re

from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GITHUB_TOKEN, REPOS_DIR
from agent.rate_limiter import RateLimiter
from agent.mcp_client import mcp_client_manager

SYSTEM = """
You are a senior software engineer modernising a legacy codebase.

Your process — follow it strictly, never skip a step:

1.  call list_files on "/" to understand the repo layout.
2.  call detect_language on "/" to identify the primary language and file count.
3.  read_file the most important source files — skip migrations, configs,
    __init__.py, lock files, and auto-generated files.
4.  call extract_ast on the most complex-looking source file.
5.  Reason about the technical debt in that file based on the AST output
    and what you read. Identify the single highest-debt file to refactor.
6.  Write a fully refactored version of that file using write_file:
      - Type annotations on every function signature
      - Named constants replacing all magic numbers and strings
      - Functions longer than 30 lines split into smaller focused ones
      - Google-style docstrings on every function and class
      - Dead code removed
      - Deprecated APIs replaced with modern equivalents
7.  Write a test file using write_file. Place it in tests/ (create the
    directory if it does not exist). Tests must cover every public function
    in the refactored file.
8.  call run_bash to install dependencies and run the tests.
    Use the suggested test command from extract_ast output.
    Example: cd /tmp/repos/{job_id} && pip install -e . -q && pytest tests/ -v
9.  If tests fail: read the error, fix the code or the tests, run_bash again.
    Maximum 3 retries. If still failing after 3 retries, proceed to step 10
    and note the failures clearly in the PR body.
10. call create_pull_request with:
      - A clear title: "refactor: modernise <filename>"
      - A markdown body listing every change made, debt score reasoning,
        and any outstanding test failures if applicable.
11. call done with a one-paragraph summary of everything completed.

Rules:
- Always read a file before writing it.
- Never modify a test file after its tests pass.
- Be concise in your reasoning — every token costs quota.
- If the repo has no tests/ directory, create it.
- Always use the test command suggested by extract_ast for the detected language.
"""


def _mcp_schema_to_genai(schema: dict) -> genai_types.FunctionDeclaration:
    """Convert an MCP tool schema into a google-genai FunctionDeclaration."""
    return genai_types.FunctionDeclaration(
        name=        schema["name"],
        description= schema["description"],
        parameters=  schema["parameters"] or {"type": "object", "properties": {}},
    )


async def run_agent(
    repo_url:         str,
    job_id:           str,
    emit_log,
    update_job,
    save_file_result,
):
    limiter = RateLimiter(min_gap_seconds=6.5) # rate limiter
    client  = genai.Client(api_key=GEMINI_API_KEY) 

    async with mcp_client_manager() as mcp:

        emit_log(job_id, f"[mcp] servers online: {mcp.connected_servers}")
        emit_log(job_id, f"[mcp] tools available: {[t['name'] for t in mcp.tool_schemas]}")

        # clone the repo
        emit_log(job_id, f"[init] cloning {repo_url}")
        clone_cmd = (
            f"git clone --depth 1 "
            f"https://{GITHUB_TOKEN}@{repo_url.replace('https://', '')} "
            f"/tmp/repos/{job_id} 2>&1"
        )
        clone_result = await mcp.call_tool("run_bash", {"command": clone_cmd})
        emit_log(job_id, f"[init] {clone_result[:300]}")
        if "fatal" in clone_result.lower() or "error" in clone_result.lower():
            await update_job(job_id, status="failed", summary=f"Clone failed: {clone_result}")
            return

        await update_job(job_id, status="running")

        all_schemas = mcp.tool_schemas + [
            {
                "name":        "done",
                "description": "Signal that the modernisation task is fully complete.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type":        "string",
                            "description": "One-paragraph summary of all changes made.",
                        }
                    },
                    "required": ["summary"],
                },
            }
        ]
        function_declarations = [_mcp_schema_to_genai(s) for s in all_schemas]
        gemini_tool = genai_types.Tool(function_declarations=function_declarations)

        # create a chat session with system prompts and all tools available
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM.format(job_id=job_id),
                tools=[gemini_tool],
            ),
        )

        message = (
            f"The repository has been cloned to /tmp/repos/{job_id}. "
            f"Original URL: {repo_url}. "
            f"Begin the modernisation process."
        )
        max_steps        = 40
        test_retries     = 0
        no_tool_strikes  = 0

        # main loop
        for step in range(max_steps):
            emit_log(job_id, f"[loop] step {step + 1}/{max_steps}")
            await limiter.wait()

            try:
                response = chat.send_message(message)
            except Exception as e:
                emit_log(job_id, f"[error] Gemini call failed: {e}")
                await asyncio.sleep(20)
                message = (
                    "The previous API call failed due to a transient error. "
                    "Please continue from where you left off."
                )
                continue
            
            # collect all function calls
            fn_calls = response.function_calls or []
            if not fn_calls:
                text = response.text or ""
                emit_log(job_id, f"[agent] {text[:400]}")
                no_tool_strikes += 1
                if no_tool_strikes >= 3:
                    emit_log(job_id, "[loop] 3 consecutive turns with no tool call — stopping.")
                    await update_job(job_id, status="failed",
                                     summary="Agent stopped producing tool calls.")
                    return
                message = (
                    "You did not call a tool. "
                    "Continue with the next step in the process and call the appropriate tool."
                )
                continue

            no_tool_strikes = 0

            function_response_parts = []

            # execute each tool
            for fn_call in fn_calls:
                name = fn_call.name
                args = dict(fn_call.args) if fn_call.args else {}

                emit_log(job_id, f"→ [{name}]  {json.dumps(args)[:200]}")

                if name == "done":
                    summary = args.get("summary", "")
                    emit_log(job_id, f"[done] {summary}")
                    await update_job(job_id, status="complete", summary=summary)
                    return

                result = await mcp.call_tool(name, args)
                emit_log(job_id, f"← {result[:400]}")

                # special cases
                if name == "run_bash":
                    output_lower = result.lower()
                    if "failed" in output_lower or "error" in output_lower:
                        test_retries += 1
                        emit_log(job_id, f"[test] retry {test_retries}/3")
                        if test_retries >= 3:
                            result += (
                                "\n\n[agent notice] Maximum test retries reached. "
                                "Proceed to open a PR and note the failing tests in the PR body."
                            )

                if name == "create_pull_request":
                    urls = re.findall(r'https://github\.com/[^\s"\']+/pull/\d+', result)
                    if urls:
                        await update_job(job_id, pr_url=urls[0])
                        emit_log(job_id, f"[pr] {urls[0]}")

                if name == "extract_ast":
                    await save_file_result(job_id, args.get("path", ""), None, None, None)

                function_response_parts.append(
                    genai_types.Part.from_function_response(
                        name=name,
                        response={"result": result},
                    )
                )

            message = function_response_parts

        # max steps reached, done not called
        emit_log(job_id, f"[loop] max steps ({max_steps}) reached without completion.")
        await update_job(job_id, status="failed",
                         summary=f"Agent did not complete within {max_steps} steps.")