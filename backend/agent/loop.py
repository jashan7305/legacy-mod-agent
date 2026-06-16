import asyncio
import json
import re
import subprocess

from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GITHUB_TOKEN, REPOS_DIR
from agent.rate_limiter import RateLimiter
from agent.mcp_client import mcp_client_manager

SYSTEM = """
You are a senior software engineer modernising a legacy codebase.

CRITICAL CONSTRAINT: The sandbox has no internet access, so dependency
installation will always fail. Because of this, your approach differs
by language:

- PYTHON: You can fully refactor AND write/run tests, since the sandbox
  has Python's standard library plus a baseline of common packages
  pre-installed. Verify your work with real test execution.

- JAVASCRIPT / TYPESCRIPT / RUST: Do NOT attempt to run tests or install
  dependencies — this will always fail offline. Instead, focus entirely
  on documentation and static analysis: produce clear docstrings/JSDoc/
  rustdoc comments, a debt assessment, and a written explanation of
  suggested refactors. Do not modify the actual logic of these files —
  only add documentation and report findings. Never claim tests passed
  for non-Python code.

Your process — follow it strictly:

0.  call detect_language on "/" to identify the primary language(s)
    and file count for the repo.

1.  call list_files on "/" to understand the repo layout.

2.  IF the primary language is Python:
    a. read_file the most important source files (skip migrations,
       configs, __init__.py, lock files, auto-generated files).
    b. call extract_ast on the most complex file.
    c. call list_available_dependencies to see what's installable —
       prefer refactoring a file whose imports are all available.
    d. Write a fully refactored version using write_file:
         - Type annotations on every function signature
         - Named constants replacing magic numbers/strings
         - Functions >30 lines split into smaller ones
         - Google-style docstrings on every function and class
         - Dead code removed
    e. Write a pytest test file using write_file.
    f. call run_bash to run the tests. If they fail for reasons other
       than missing packages, fix and retry (max 3 attempts).

3.  IF the primary language is JavaScript, TypeScript, or Rust:
    a. read_file the most important source files.
    b. call extract_ast on the 2-3 most complex files.
    c. For each file: write a documentation-only patch using write_file —
       add JSDoc (/** ... */) for JS/TS or rustdoc (///) comments above
       every function and class, explaining purpose, parameters, return
       values, and any non-obvious behavior. DO NOT change any logic.
    d. Write a single markdown file (e.g. DEBT_REPORT.md) summarising:
         - Technical debt findings per file (complexity, dead code,
           missing types, anti-patterns)
         - Suggested refactors, described in prose — do not implement them
         - A note that tests could not be run in this environment

4.  Before opening a PR: call create_branch (e.g. "agent-docs-{job_id}"
    for doc-only work, or "agent-refactor-{job_id}" for Python refactors)
    from the default branch. Then push your changes with push_files or
    create_or_update_file.

5.  call create_pull_request with:
      - head: the branch you just created
      - base: the repo's default branch (usually "main" or "master")
      - title: clearly state whether this is a refactor+tests PR (Python)
        or a documentation-only PR (JS/TS/Rust)
      - body: list every file touched and what was done to it. For
        Python, mention test results. For JS/TS/Rust, explicitly state
        "Documentation only — no logic changes, tests not run."

6.  call done with a one-paragraph summary.

Rules:
- Never modify the actual logic of JS, TypeScript, or Rust files — comments
  and a separate markdown report only.
- Never claim a test passed unless you actually ran it via run_bash and
  saw it pass.
- Be concise in your reasoning — every token costs quota.
"""


_UNSUPPORTED_SCHEMA_KEYS = {"$schema", "$id", "additionalProperties", "definitions", "$defs"}


def _sanitize_schema(schema: dict) -> dict:
    """Recursively strip JSON Schema metadata keys that Gemini's
    FunctionDeclaration rejects, while preserving the actual
    type/properties/required structure it needs."""
    if not isinstance(schema, dict):
        return schema

    cleaned = {
        k: _sanitize_schema(v) if isinstance(v, dict) else
           ([_sanitize_schema(i) for i in v] if isinstance(v, list) else v)
        for k, v in schema.items()
        if k not in _UNSUPPORTED_SCHEMA_KEYS
    }
    return cleaned


def _mcp_schema_to_genai(schema: dict) -> genai_types.FunctionDeclaration:
    """Convert an MCP tool schema into a google-genai FunctionDeclaration."""
    parameters = _sanitize_schema(schema["parameters"]) if schema["parameters"] else {
        "type": "object",
        "properties": {},
    }
    return genai_types.FunctionDeclaration(
        name=        schema["name"],
        description= schema["description"],
        parameters=  parameters,
    )


async def run_agent(
    repo_url: str,
    job_id: str,
    emit_log,
    update_job,
    save_file_result,
):
    limiter = RateLimiter(min_gap_seconds=20)
    client  = genai.Client(api_key=GEMINI_API_KEY)

    async with mcp_client_manager() as mcp:
        try:
            emit_log(job_id, f"[mcp] servers online: {mcp.connected_servers}")
            emit_log(job_id, f"[mcp] tools available: {[t['name'] for t in mcp.tool_schemas]}")

            emit_log(job_id, f"[init] cloning {repo_url}")
            clone_url = f"https://{GITHUB_TOKEN}@{repo_url.replace('https://', '')}"
            clone_proc = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, f"{REPOS_DIR}/{job_id}"],
                capture_output=True, text=True, timeout=120,
            )
            clone_result = clone_proc.stdout + clone_proc.stderr
            emit_log(job_id, f"[init] {clone_result[:300]}")

            if clone_proc.returncode != 0:
                await update_job(job_id, status="failed", summary=f"Clone failed: {clone_result}")
                return

            await update_job(job_id, status="running")

            emit_log(job_id, "[debug] building tool declarations...")
            all_schemas = mcp.tool_schemas + [{
                "name": "done",
                "description": "Signal that the modernisation task is fully complete.",
                "parameters": {
                    "type": "object",
                    "properties": {"summary": {"type": "string", "description": "One-paragraph summary."}},
                    "required": ["summary"],
                },
            }]

            for s in all_schemas:
                emit_log(job_id, f"[debug] schema: {s['name']}")

            function_declarations = [_mcp_schema_to_genai(s) for s in all_schemas]
            emit_log(job_id, "[debug] tool declarations built OK")

            gemini_tool = genai_types.Tool(function_declarations=function_declarations)
            emit_log(job_id, "[debug] Tool object created OK")

            chat = client.chats.create(
                model="gemini-3.1-flash-lite",
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM.format(job_id=job_id),
                    tools=[gemini_tool],
                ),
            )
            emit_log(job_id, "[debug] chat session created OK")
        except Exception as e:
            import traceback
            emit_log(job_id, f"[debug] EXCEPTION before/during setup: {type(e).__name__}: {e}")
            emit_log(job_id, f"[debug] traceback:\n{traceback.format_exc()}")
            await update_job(job_id, status="failed", summary=f"{type(e).__name__}: {e}")
            return

        message = (
            f"The repository has been cloned to /tmp/repos/{job_id}. "
            f"Original URL: {repo_url}. "
            f"Begin the modernisation process."
        )
        max_steps        = 40
        test_retries     = 0
        no_tool_strikes  = 0
        is_branch_created = False

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
                
                if name == "create_branch" and not is_branch_created and "error" not in result.lower():
                    is_branch_created = True

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
        if is_branch_created:
            fallback_pr_result = await mcp.call_tool("create_pull_request", {
                "title": "refactor: partial modernisation (agent ran out of steps)",
                "body": (
                    "This PR was opened automatically after the agent reached its "
                    "step limit before calling `done`. The changes below reflect "
                    "whatever work was completed up to that point and may be "
                    "incomplete or untested.\n\n"
                    f"Job ID: {job_id}"
                ),
            })
            emit_log(job_id, f"[fallback] attempted PR creation: {fallback_pr_result[:300]}")

            import re
            urls = re.findall(r'https://github\.com/[^\s"\']+/pull/\d+', fallback_pr_result)
            pr_url = urls[0] if urls else None
            if pr_url:
                emit_log(job_id, f"[fallback] PR opened: {pr_url}")

            await update_job(
                job_id,
                status="failed",
                summary=f"Agent did not complete within {max_steps} steps. Partial work was committed.",
                pr_url=pr_url,
            )
        else:
            await update_job(job_id, status="failed",
                            summary=f"Agent did not complete within {max_steps} steps.")