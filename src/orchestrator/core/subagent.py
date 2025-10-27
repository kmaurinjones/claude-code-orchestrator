"""Subagent wrapper for Claude Code CLI in non-interactive mode."""

import subprocess
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from uuid import uuid4

from .. import __version__
from ..models import EventType
from .logger import EventLogger


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
        next_action: Optional[str] = None
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

    def execute(self) -> Dict[str, Any]:
        """Execute task via Claude Code CLI."""
        # Ensure workspace is absolute
        if isinstance(self.workspace, Path):
            self.workspace = self.workspace.resolve()

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
                    "--model", "haiku"  # Latest Haiku for subagents
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

        except subprocess.TimeoutExpired:
            timeout_response = {
                "status": "failed",
                "error": "Subagent timed out after 10 minutes"
            }

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

        return f"""# Subagent Task {self.trace_id}

## Context
{self.context}
{retry_section}
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
2. **CREATE ALL FILES HERE**: All files must be created in the CURRENT working directory ({self.workspace})
   - DO NOT create files in any `.agentic` subdirectory
   - DO NOT use relative paths like `../.agentic/`
   - Create files directly in the current directory or its subdirectories

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
