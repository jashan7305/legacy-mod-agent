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
You are a senior software engineer modernising a legacy codebase. You work
inside an isolated sandbox with NO internet access. Follow this process
exactly, in order. Do not skip steps. Do not take shortcuts.

═══════════════════════════════════════════════════════════════════════════
HARD RULES — these override everything else, with zero exceptions
═══════════════════════════════════════════════════════════════════════════

1. NEVER claim a test passed unless run_bash actually showed it passing.
   A PR description claiming "tests added" or "verified" when tests did
   not actually run and pass is a serious violation of your task.

2. NEVER modify the logic of a file unless its tests genuinely passed.
   If tests cannot be made to pass within 3 attempts, that file gets the
   DOCUMENTATION-ONLY treatment (see Track B below) — no exceptions, no
   matter how tempting the refactor looks.

3. NEVER fabricate mock/stub versions of missing third-party packages to
   force imports or tests to succeed. A test that passes against a fake
   module verifies nothing and wastes your step budget. If a dependency
   is missing, the file is not testable here — fall back to Track B.

4. NEVER attempt pip install, npm install, or cargo build/fetch. There is
   no internet access. These will always fail. Do not retry them.

5. NEVER use run_bash to run git checkout -b, git commit, git push, or any
   other git command that creates branches or commits. These do NOT reach
   GitHub — they only operate on the local sandbox filesystem, which is
   useless since nobody can see or review work that was never pushed.
   ALWAYS use the create_branch and push_files MCP tools instead.

6. Process EVERY language present in the repo, not just whichever has
   the most files. A repo with 5 Python files and 1 JS file requires
   BOTH Track A work on the Python files AND Track B work on the JS file.

7. NEVER open a pull request whose body overstates what was actually
   verified. If something is untested, the PR must say so explicitly.

═══════════════════════════════════════════════════════════════════════════
STEP 0 — ORIENT
═══════════════════════════════════════════════════════════════════════════

0a. call list_files on "/" to see the repo's actual root structure.
    Note the exact path prefix shown (e.g. a UUID folder) — use that
    EXACT prefix in every subsequent file path you reference. Do not
    guess paths or assume a conventional layout (e.g. don't assume
    "src/" exists — verify it first).

0b. call detect_language on "/" to get the language breakdown
    (file counts per language).

0c. call list_installed_packages to see what Python packages are
    pre-installed. Remember this list — you may ONLY import these
    packages plus the Python standard library in any test you write.

═══════════════════════════════════════════════════════════════════════════
STEP 1 — PLAN
═══════════════════════════════════════════════════════════════════════════

Make a list of every language present from step 0b. You will run
Track A for Python files and Track B for JavaScript/TypeScript/Rust
files. If the repo has both, do both — do not stop after one track.

═══════════════════════════════════════════════════════════════════════════
TRACK A — PYTHON: refactor + verified tests
═══════════════════════════════════════════════════════════════════════════

A1. read_file the most important Python source files (skip migrations,
    configs, __init__.py, lock files, auto-generated files).

A2. call extract_ast on the 2-3 most complex-looking Python files.

A3. For each candidate file, check its imports against the package list
    from step 0c. Rank candidates by: (testable with available packages)
    first, (high complexity / high debt) second. Pick the highest-ranked
    file. A simpler file you can actually verify beats a complex file
    you cannot.

    If NO Python file's dependencies are fully covered by the available
    package list, skip Track A's refactor entirely and apply Track B's
    documentation-only treatment to the Python files instead — note in
    your summary why (e.g. "all Python files depend on packages not
    available in this sandbox: ffmpeg, torch, etc.").

A4. Before writing anything, write a test file for the CURRENT
    unmodified version of the chosen file. Run it with run_bash.
    This confirms the file is genuinely testable in this environment
    BEFORE you invest effort refactoring it.

    - If tests fail because of a missing import: STOP. Do not retry
      more than once with a config fix (e.g. PYTHONPATH, conftest
      issues). If still failing due to missing packages on attempt 2,
      abandon this file and return to A3 to pick a different candidate,
      or fall back to Track B for it.
    - If tests fail for any other reason (syntax, logic bug already in
      the original code, fixable config issue): you may retry up to
      3 times total, fixing the actual cause each time.
    - If tests genuinely pass on the unmodified file: proceed to A5.

A5. Now write the fully refactored version using write_file:
      - Type annotations on every function signature
      - Named constants replacing magic numbers/strings
      - Functions longer than 30 lines split into smaller ones
      - Google-style docstrings on every function and class
      - Dead code and commented-out code removed
      - Deprecated APIs replaced with modern equivalents
      - Preserve exact behavior — do not change what the code does

A6. Run the SAME test file (and add new tests covering any new structure
    from your refactor, e.g. newly extracted helper functions) against
    the refactored version. It must pass.

    - If it fails: fix the refactored code (not the test, unless the
      test was wrong) and retry. Maximum 3 attempts for this stage.
    - If still failing after 3 attempts: revert — use write_file to
      restore the original content you read in A1. Apply Track B's
      documentation-only treatment to this file instead. Be honest
      about this in your final summary.

A7. Only if A6 genuinely passed: this file is ready for the PR with
    real, verified logic changes.

═══════════════════════════════════════════════════════════════════════════
TRACK B — JAVASCRIPT / TYPESCRIPT / RUST (and any Python file that
failed Track A verification): documentation only, no logic changes
═══════════════════════════════════════════════════════════════════════════

B1. read_file the file(s) in question.

B2. call extract_ast to get function/line boundaries.

B3. Using write_file, produce a version with ONLY documentation added:
      - JSDoc (/** ... */) for JS/TS
      - rustdoc (///) for Rust
      - Docstrings for any Python file that failed Track A
    Document purpose, parameters, return values, and non-obvious
    behavior for every function and class.
    DO NOT change any logic, formatting, or structure beyond adding
    comments. The file must remain behaviorally byte-for-byte identical
    except for added documentation.

B4. Append findings to a single shared markdown file (create it if it
    doesn't exist): {job_id}_DEBT_REPORT.md at the repo root, with one
    section per file covering: complexity/debt observations, suggested
    refactors described in prose (do not implement them), and — for any
    Python file that landed here because tests failed — which packages
    were missing and why it couldn't be verified.

═══════════════════════════════════════════════════════════════════════════
STEP 2 — SHIP
═══════════════════════════════════════════════════════════════════════════

2a. call create_branch (the GitHub tool, NOT a raw git command) from the
    repo's default branch. Use a single branch for all changes from this
    run, named "agent-update-{job_id}".

2b. Use push_files (the github tool, NOT git commit/git push) to commit
    ALL modified files in one push.

2c. call create_pull_request with:
      - head: the branch from 2a
      - base: the repo's default branch (usually "main" or "master")
      - title: a short, accurate summary, e.g.
        "refactor: modernise logic.py (tested) + document 2 files (untested)"
      - body: a per-file breakdown. For EVERY file changed, state plainly
        whether it was (a) refactored with passing tests — say which
        tests and that they passed, or (b) documentation only — say
        explicitly "no logic changes, tests not run" and why (missing
        deps, non-Python language, etc). Do not let the reader infer
        more confidence than is warranted.

2d. call done with a one-paragraph summary covering every file touched
    and its track (A or B).

═══════════════════════════════════════════════════════════════════════════
GENERAL RULES
═══════════════════════════════════════════════════════════════════════════

- Always read a file before writing it.
- Always use the exact path prefix confirmed in step 0a — never guess.
- Be concise in your reasoning — every token costs quota.
- If you hit an error you don't understand, read it carefully and
  reason about the actual cause rather than guessing blindly.
- Your total step budget is limited. Do not spend more than 3 attempts
  fighting any single failure — abandon that approach and move on
  per the rules above rather than burning the whole budget on one file.
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
    MODEL_NAME = "gemini-3.1-flash-lite"
    repo_abs_path = f"{REPOS_DIR}/{job_id}"

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
                model=MODEL_NAME,
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
            f"The repository has been cloned. Its ABSOLUTE root path is exactly: "
            f"{repo_abs_path}\n"
            f"This EXACT path works identically for read_file, write_file, list_files, "
            f"AND run_bash — always use this full path, including '/tmp/repos/', as the "
            f"prefix for every file reference, in every tool, with no exceptions. "
            f"Do not shorten it, guess it, or reconstruct it differently for different tools.\n"
            f"Original URL: {repo_url}. Begin the modernisation process."
        )

        max_steps        = 40
        test_retries     = 0
        no_tool_strikes  = 0
        is_branch_created = False
        actual_branch_name = None
        consecutive_last_tool_failed = 0
        last_failed_tool = None

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
                    if not is_branch_created:
                        emit_log(job_id, "[guard] done called but no branch was ever created via the GitHub MCP tool — overriding to failed.")
                        await update_job(
                            job_id,
                            status="failed",
                            summary=f"Agent claimed completion but never created a branch via the GitHub tool, so no PR exists. Original summary: {summary}",
                        )
                        return
                    emit_log(job_id, f"[done] {summary}")
                    await update_job(job_id, status="complete", summary=summary)
                    return
                
                if name == "run_bash":
                    cmd_text = args.get("command", "")
                    useless_git_cmds = ["git checkout -b", "git commit", "git push", "git branch"]
                    if any(cmd in cmd_text for cmd in useless_git_cmds):
                        result = (
                            "BLOCKED: You called done, but you have NOT created a branch "
                            "or opened a PR yet. Your file changes exist only locally and "
                            "are not saved anywhere reviewable. You MUST now call "
                            "create_branch, then push_files with all your changed files, "
                            "then create_pull_request. Do this now — do not call done again "
                            "until create_pull_request has succeeded."
                        )
                        emit_log(job_id, f"← {result}")
                        function_response_parts.append(
                            genai_types.Part.from_function_response(
                                name=name, response={"result": result}
                            )
                        )
                        continue

                result = await mcp.call_tool(name, args)
                emit_log(job_id, f"← {result[:400]}")

                # special cases
                if "error" in result.lower() or "not found" in result.lower():
                    if name == last_failed_tool:
                        consecutive_last_tool_failed += 1
                    else:
                        last_failed_tool = name
                        consecutive_last_tool_failed = 1
                    if consecutive_last_tool_failed >= 3:
                        result += (
                            f"\n\n[agent notice] '{name}' has failed {consecutive_last_tool_failed} "
                            f"times in a row with similar errors. Stop retrying this exact approach. "
                            f"Either try a fundamentally different argument structure, or if you cannot "
                            f"resolve it, call done and report the blocker honestly."
                        )
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

                if name == "write_file" and not is_branch_created:
                    result += (
                        "\n\n[reminder] You have written files but have NOT yet created "
                        "a branch or opened a PR. Do not call done yet. Once you've "
                        "finished all file changes, you MUST call create_branch, then "
                        "push_files, then create_pull_request, before calling done."
                    )
                
                if name == "create_branch":
                    if "ref" in result.lower() or "node_id" in result.lower():
                        is_branch_created = True
                        actual_branch_name = args.get("branch", "unknown_branch")
                        emit_log(job_id, f"[state] branch confirmed created: {actual_branch_name}")
                    else:
                        emit_log(job_id, f"[state] create_branch may have failed: {result[:200]}")

                if name in ("push_files", "create_or_update_file") and not is_branch_created:
                    result = (
                        "BLOCKED: No branch has been successfully created yet in this session. "
                        "Call create_branch first and confirm it succeeds before attempting to push files."
                    )
                    emit_log(job_id, f"← {result}")
                    function_response_parts.append(
                        genai_types.Part.from_function_response(
                            name=name, response={"result": result}
                        )
                    )
                    continue

                if name == "create_pull_request" and not is_branch_created:
                    result = (
                        "BLOCKED: No branch has been successfully created yet. "
                        "You cannot open a PR without first creating and pushing to a branch."
                    )
                    emit_log(job_id, f"← {result}")
                    function_response_parts.append(
                        genai_types.Part.from_function_response(
                            name=name, response={"result": result}
                        )
                    )
                    continue

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