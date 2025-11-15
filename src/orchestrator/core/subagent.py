"""Subagent wrapper for Claude Code CLI in non-interactive mode."""

from datetime import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from .. import __version__
from ..models import EventType
from .logger import EventLogger


def _generate_directory_tree(workspace: Path, max_depth: int = 3, max_files: int = 50) -> str:
    """Generate a concise directory tree for context."""
    lines = []
    file_count = 0

    # Directories to ignore
    ignore = {".agentic", ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
              ".ruff_cache", "node_modules", ".next", "dist", "build", ".DS_Store"}

    def add_tree(path: Path, prefix: str = "", depth: int = 0):
        nonlocal file_count
        if depth > max_depth or file_count >= max_files:
            return

        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            items = [i for i in items if i.name not in ignore and not i.name.startswith('.')]

            for i, item in enumerate(items):
                if file_count >= max_files:
                    lines.append(f"{prefix}... (truncated)")
                    return

                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                next_prefix = "    " if is_last else "│   "

                if item.is_dir():
                    lines.append(f"{prefix}{current_prefix}{item.name}/")
                    add_tree(item, prefix + next_prefix, depth + 1)
                else:
                    lines.append(f"{prefix}{current_prefix}{item.name}")
                    file_count += 1
        except PermissionError:
            pass

    lines.append(f"{workspace.name}/")
    add_tree(workspace)
    return "\n".join(lines)


def find_claude_executable() -> Optional[str]:
    """Find claude executable in common locations."""
    # Try common locations
    possible_paths = [
        # User local installation
        os.path.expanduser("~/.claude/local/node_modules/.bin/claude"),
        # Global npm installation
        "/usr/local/bin/claude",
        # Direct in PATH
        "claude",
    ]

    for path in possible_paths:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None


class Subagent:
    def __init__(
        self,
        task_id: str,
        task_description: str,
        context: str,
        parent_trace_id: str,
        logger: EventLogger,
        step: int,
        workspace: Path,
        max_turns: int = 10,
        claude_executable: Optional[str] = None,
        next_action: Optional[str] = None,
        model: str = "haiku",
        log_workspace: Optional[Path] = None,
    ):
        self.task_id = task_id
        self.task_description = task_description
        self.context = context
        self.trace_id = f"sub-{uuid4().hex[:8]}"
        self.parent_trace_id = parent_trace_id
        self.logger = logger
        self.step = step
        self.workspace = workspace
        self.max_turns = max_turns
        self.claude_executable = claude_executable or find_claude_executable()
        self.next_action = next_action
        self.model = model
        self.log_workspace = Path(log_workspace).resolve() if log_workspace else Path(workspace).resolve()

    def _log_detailed_execution(
        self,
        instruction: str,
        raw_stdout: str,
        raw_stderr: str,
        result: Dict[str, Any],
        returncode: int,
        duration_seconds: float
    ) -> None:
        """Log detailed subagent execution for debugging."""
        log_dir = self.log_workspace / "logs" / "subagents"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / f"{self.trace_id}.json"

        detailed_log = {
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "step": self.step,
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "workspace": str(self.workspace),
            "max_turns": self.max_turns,
            "duration_seconds": round(duration_seconds, 2),
            "instruction_sent": instruction,
            "claude_cli_returncode": returncode,
            "raw_stdout": raw_stdout,
            "raw_stderr": raw_stderr if raw_stderr else None,
            "parsed_result": result,
            "next_action_feedback": self.next_action
        }

        with open(log_file, 'w') as f:
            json.dump(detailed_log, f, indent=2)

    def execute(self) -> Dict[str, Any]:
        """Execute task via Claude Code CLI."""
        start_time = datetime.now()

        # Ensure workspace is absolute
        if isinstance(self.workspace, Path):
            self.workspace = self.workspace.resolve()
        else:
            self.workspace = Path(self.workspace).resolve()

        # Validate workspace is absolute (defensive check)
        if not self.workspace.is_absolute():
            raise ValueError(f"Subagent workspace must be absolute: {self.workspace}")

        # Log spawn with absolute workspace path
        self.logger.log(
            event_type=EventType.SPAWN,
            actor=self.trace_id,
            payload={
                "task_id": self.task_id,
                "task": self.task_description[:200],
                "context_length": len(self.context),
                "workspace": str(self.workspace),
                "workspace_cwd": str(self.workspace)  # Debug: show what cwd will be
            },
            trace_id=self.trace_id,
            parent_trace_id=self.parent_trace_id,
            step=self.step,
                version=__version__
        )

        # Build full instruction
        instruction = self._build_instruction()

        try:
            # Invoke claude CLI in non-interactive mode
            # -p = print mode (SDK mode, exits after response)
            # --output-format json = structured output
            # --dangerously-skip-permissions = no prompts (required for automation)
            # --add-dir = additional working directories
            # --max-turns = limit conversation length

            if not self.claude_executable:
                raise FileNotFoundError("Claude Code CLI not found. Install it or provide claude_executable path.")

            result = subprocess.run(
                [
                    self.claude_executable,
                    "-p", instruction,
                    "--output-format", "json",
                    "--dangerously-skip-permissions",
                    "--add-dir", str(self.workspace.absolute()),
                    "--max-turns", str(self.max_turns),
                    "--model", self.model  # Configurable model (haiku by default, sonnet for audits)
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout
                cwd=str(self.workspace)  # Run in workspace
            )

            if result.returncode != 0:
                error_response = {
                    "status": "failed",
                    "error": result.stderr or "Unknown error",
                    "returncode": result.returncode,
                    "stdout": result.stdout
                }

                # Log detailed execution for CLI errors
                duration = (datetime.now() - start_time).total_seconds()
                self._log_detailed_execution(
                    instruction=instruction,
                    raw_stdout=result.stdout,
                    raw_stderr=result.stderr,
                    result=error_response,
                    returncode=result.returncode,
                    duration_seconds=duration
                )

                self.logger.log(
                    event_type=EventType.ERROR,
                    actor=self.trace_id,
                    payload=error_response,
                    trace_id=self.trace_id,
                    parent_trace_id=self.parent_trace_id,
                    step=self.step,
                version=__version__
                )

                return error_response

            # Parse JSON output
            try:
                claude_output = json.loads(result.stdout)

                # Extract content from Claude's response
                # Format varies - adapt based on actual output structure
                if isinstance(claude_output, dict):
                    content = claude_output.get("content", str(claude_output))
                    usage = claude_output.get("usage", {})
                else:
                    content = str(claude_output)
                    usage = {}

                # Parse the response content for structured data
                response_data = self._parse_response_content(content)

                success_response = {
                    "status": response_data.get("status", "success"),
                    "output": content,
                    "summary": response_data.get("summary", "Task completed"),
                    "files_created": response_data.get("files_created", []),
                    "files_modified": response_data.get("files_modified", []),
                    "commands_run": response_data.get("commands_run", []),
                    "blockers": response_data.get("blockers", None),
                    "next_steps": response_data.get("next_steps", None),
                    "tokens_used": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                }

                # Log detailed execution
                duration = (datetime.now() - start_time).total_seconds()
                self._log_detailed_execution(
                    instruction=instruction,
                    raw_stdout=result.stdout,
                    raw_stderr=result.stderr,
                    result=success_response,
                    returncode=result.returncode,
                    duration_seconds=duration
                )

                self.logger.log(
                    event_type=EventType.COMPLETE,
                    actor=self.trace_id,
                    payload=success_response,
                    trace_id=self.trace_id,
                    parent_trace_id=self.parent_trace_id,
                    step=self.step,
                version=__version__
                )

                return success_response

            except json.JSONDecodeError as e:
                # Fallback if JSON parsing fails
                fallback_response = {
                    "status": "success",
                    "output": result.stdout,
                    "summary": "Task completed (unstructured output)",
                    "tokens_used": 0,
                    "parse_error": str(e)
                }

                # Log detailed execution
                duration = (datetime.now() - start_time).total_seconds()
                self._log_detailed_execution(
                    instruction=instruction,
                    raw_stdout=result.stdout,
                    raw_stderr=result.stderr,
                    result=fallback_response,
                    returncode=result.returncode,
                    duration_seconds=duration
                )

                self.logger.log(
                    event_type=EventType.COMPLETE,
                    actor=self.trace_id,
                    payload=fallback_response,
                    trace_id=self.trace_id,
                    parent_trace_id=self.parent_trace_id,
                    step=self.step,
                version=__version__
                )

                return fallback_response

        except subprocess.TimeoutExpired as timeout_exc:
            timeout_response = {
                "status": "failed",
                "error": "Subagent timed out after 10 minutes"
            }

            # Log detailed execution for timeout
            duration = (datetime.now() - start_time).total_seconds()
            self._log_detailed_execution(
                instruction=instruction,
                raw_stdout=timeout_exc.stdout.decode() if timeout_exc.stdout else "",
                raw_stderr=timeout_exc.stderr.decode() if timeout_exc.stderr else "",
                result=timeout_response,
                returncode=-1,
                duration_seconds=duration
            )

            self.logger.log(
                event_type=EventType.ERROR,
                actor=self.trace_id,
                payload=timeout_response,
                trace_id=self.trace_id,
                parent_trace_id=self.parent_trace_id,
                step=self.step,
                version=__version__
            )

            return timeout_response

        except Exception as e:
            exception_response = {
                "status": "failed",
                "error": str(e)
            }

            # Log detailed execution for exceptions
            duration = (datetime.now() - start_time).total_seconds()
            self._log_detailed_execution(
                instruction=instruction,
                raw_stdout="",
                raw_stderr=str(e),
                result=exception_response,
                returncode=-1,
                duration_seconds=duration
            )

            self.logger.log(
                event_type=EventType.ERROR,
                actor=self.trace_id,
                payload=exception_response,
                trace_id=self.trace_id,
                parent_trace_id=self.parent_trace_id,
                step=self.step,
                version=__version__
            )

            return exception_response

    def _build_instruction(self) -> str:
        """Build instruction for Claude Code CLI."""
        retry_section = ""
        if self.next_action:
            retry_section = f"""
## Previous Attempt Feedback
**This is a retry attempt.** The previous attempt failed with the following issue:
{self.next_action}

Please address this feedback and try again.
"""

        # Generate directory tree for context
        dir_tree = _generate_directory_tree(self.workspace)

        return f"""# Subagent Task {self.trace_id}

## Context
{self.context}
{retry_section}
## Current Project Structure
```
{dir_tree}
```

## Your Task
{self.task_description}

## Instructions
Complete this task using all available tools (bash, file operations, web_search, MCP servers).

When complete, your final message MUST include a markdown code block with JSON in this exact format:

```json
{{
  "status": "SUCCESS | BLOCKED | FAILED",
  "summary": "Brief description of what you accomplished",
  "files_created": ["path/to/file1.py", "path/to/file2.txt"],
  "files_modified": ["path/to/existing.py"],
  "commands_run": ["pytest", "ruff check"],
  "blockers": "If BLOCKED, explain what's preventing progress",
  "next_steps": "What should happen next (if applicable)"
}}
```

## Critical Rules
1. **WORKING DIRECTORY**: You are running in: {self.workspace}
2. **FILE CREATION RULES - EXACT PATH REQUIRED**:
   - Create files at the EXACT path specified in the task description
   - Example: If task says "src/module/file.py", create EXACTLY that path, not "src/other_module/file.py"
   - DO NOT put files in similar existing directories - create the exact directory structure specified
   - Create all necessary parent directories first with mkdir -p
   - Verify the full path matches the task specification before creating the file
   - DO NOT create files in any `.agentic` subdirectory
   - DO NOT use relative paths like `../.agentic/`
   - All paths are relative to the current working directory ({self.workspace})

3. **MVP-FIRST INCREMENTAL DEVELOPMENT** - Build the simplest working version first:
   - Start with the absolute minimum needed to make something work
   - Build ONE thing at a time, not everything at once
   - Test each piece IMMEDIATELY after building it (functionally, not just assertions)
   - If it doesn't work, fix it RIGHT NOW before adding anything else
   - Only add more features after the basic version is verified working
   - DO NOT build a massive system and test it at the end - that creates unusable junk

4. **ALWAYS USE EXISTING CODE FIRST** - Before writing new code:
   - Search for existing modules, classes, and functions that can be reused
   - Inherit from existing base classes when applicable
   - Import and use existing utilities and helpers
   - Extend existing patterns rather than creating new ones
   - Only write new code if existing code cannot be reused

5. **IMMEDIATE FUNCTIONAL TESTING** - After implementing:
   - Actually RUN the code you just wrote (don't just write it)
   - Check if it does what it's supposed to do (manual/functional test, not just unit tests)
   - If it fails, debug and fix it NOW before reporting success
   - Include evidence of working code in your response (output, screenshots, etc.)

6. Focus ONLY on this task - don't expand scope
7. Document blockers clearly if you encounter them
8. Use MCPs when helpful
9. Include the JSON status block in your final response

Begin now.
"""

    def _parse_response_content(self, content: str) -> Dict[str, Any]:
        """Extract structured data from Claude's response content."""
        # Try to find JSON code block in the response
        import re

        # Look for ```json ... ``` blocks
        json_pattern = r'```json\s*\n(.*?)\n```'
        matches = re.findall(json_pattern, content, re.DOTALL)

        if matches:
            try:
                return json.loads(matches[-1])  # Use last JSON block
            except json.JSONDecodeError:
                pass

        # Fallback: return empty dict
        return {}
